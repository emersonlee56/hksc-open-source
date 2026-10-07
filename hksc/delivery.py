"""Immutable, hash-bound local research deliveries."""
from pathlib import Path

from .bundle import confined, read_json, sha, write_json
from .contracts import RUN_ARTIFACTS, validate_state
from .plan import document_html


def load_delivery(directory, required=()):
    root = Path(directory).resolve()
    if not (root / 'result_hashes.json').is_file():
        raise ValueError('Delivery is incomplete: result manifest unavailable')
    hashes = read_json(root / 'result_hashes.json')
    if not isinstance(hashes, dict) or not set(required) <= hashes.keys():
        raise ValueError('Delivery manifest is incomplete')
    if 'result_hashes.json' in hashes:
        raise ValueError('Delivery manifest cannot bind itself')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and p != root / 'result_hashes.json'}
    if actual != set(hashes):
        raise ValueError('Delivery manifest does not cover the complete file set')
    for name, digest in hashes.items():
        if not isinstance(digest, str) or sha(confined(root, name)) != digest:
            raise ValueError('Delivery hash mismatch: ' + name)
    selected = []
    nested = sorted({(root / name).parent for name in hashes if name.endswith('/result_hashes.json')},
                    key=lambda p: len(p.parts))
    for child in nested:
        if not any(child.is_relative_to(parent) for parent in selected):
            load_delivery(child)
            selected.append(child)
    return root, hashes


def load_run(directory):
    directory = Path(directory)
    if not (directory / 'run.json').exists() and (directory / 'daily_receipt.json').exists():
        pipeline_root, _ = load_delivery(directory, ('daily_receipt.json', 'research/result_hashes.json'))
        receipt = read_json(pipeline_root / 'daily_receipt.json')
        if receipt.get('status') not in {'COMPLETE', 'COMPLETE_WITH_DEGRADATION'}:
            raise ValueError('Blocked daily pipeline cannot be a prior research run')
        directory = pipeline_root / 'research'
    root, hashes = load_delivery(directory, RUN_ARTIFACTS)
    run = read_json(root / 'run.json')
    if not isinstance(run, dict):
        raise ValueError('Run receipt must be an object')
    if run.get('format') != 'hksc-public-run/2' or run.get('is_actual_trade') is not False:
        raise ValueError('Only public research runs may be consumed')
    if type(run.get('synthetic')) is not bool:
        raise ValueError('Research mode must be explicit')
    validate_state(run, read_json(root / 'candidates.json'), read_json(root / 'lifecycle.json'),
                   read_json(root / 'events.json'), read_json(root / 'scan.json'))
    plan = read_json(root / 'daily_plan.json')
    expected_mode = 'SYNTHETIC_REPLAY' if run['synthetic'] else 'EXTERNAL_DATA_REPLAY'
    if run.get('observation_mode') != expected_mode or plan.get('synthetic') is not run['synthetic'] or plan.get('observation_mode') != expected_mode:
        raise ValueError('Run and plan observation mode mismatch')
    if any((run['source_records'][kind]['provider'] == 'synthetic') is not run['synthetic'] for kind in ('bars', 'benchmark')):
        raise ValueError('Run and source research mode mismatch')
    return root, run, hashes


def validate_run_input(run, root, manifest):
    if run['bundle_sha256'] != sha(root / 'bundle.json') or run['as_of_date'] != manifest['as_of_date'] or run['synthetic'] is not manifest['synthetic']:
        raise ValueError('Input is not the input bound by the research run')
    calendar = read_json(root / 'calendar.json')['trading_dates']
    universe = read_json(root / 'universe.json')
    if run['bound_calendar'] != calendar or run['completed_calendar'] != [d for d in calendar if d <= run['as_of_date']]:
        raise ValueError('Run calendar does not match bound input calendar')
    if run['universe_symbols_sha256'] != universe['symbols_sha256']:
        raise ValueError('Run universe does not match bound input universe')
    if run['source_records'] != read_json(root / 'sources.json'):
        raise ValueError('Run source records do not match bound input sources')


def publish_report(output, name, payload, markdown, title):
    target = Path(output)
    target.mkdir(parents=True, exist_ok=False)
    write_json(target / (name + '.json'), payload)
    (target / 'report.md').write_text(markdown, encoding='utf-8')
    (target / 'report.html').write_text(document_html(title, markdown), encoding='utf-8')
    write_json(target / 'result_hashes.json', {p.name: sha(p) for p in sorted(target.iterdir())})
    return payload
