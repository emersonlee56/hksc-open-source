"""Validate file evidence before deterministic research calculations."""
from datetime import date, datetime
from pathlib import Path
import csv
import hashlib
import json
import math

REQUIRED = ('universe.json', 'universe.csv', 'bars.csv', 'benchmark.csv',
            'calendar.json', 'sources.json')
PROVIDERS = {'synthetic', 'westock', 'futu', 'gildata'}


def read_json(path):
    def bad(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      parse_constant=bad, object_pairs_hook=unique)


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False,
                  indent=2, sort_keys=True)
        handle.write('\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Timestamp requires an explicit timezone')
    return result


def iso_day(value):
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError('Date must be YYYY-MM-DD')
    return value


def confined(root, name):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name:
        raise ValueError('Bundle path must be relative and contained')
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root) or (root / relative).is_symlink():
        raise ValueError('Bundle path escaped input directory')
    return resolved


def validate_bundle(directory):
    root = Path(directory).resolve()
    manifest = read_json(root / 'bundle.json')
    if manifest.get('format') != 'hksc-public-bundle/1':
        raise ValueError('Unsupported bundle format')
    if type(manifest.get('synthetic')) is not bool:
        raise ValueError('Bundle requires explicit synthetic flag')
    day = iso_day(manifest['as_of_date'])
    files = manifest['files']
    if not set(REQUIRED) <= set(files):
        raise ValueError('Bundle missing required files')
    for name, digest in files.items():
        if not isinstance(digest, str) or sha(confined(root, name)) != digest:
            raise ValueError('Bundle hash mismatch: ' + name)
    sources = read_json(root / 'sources.json')
    bars = sources['bars']
    benchmark = sources['benchmark']
    for kind, record in (('bars', bars), ('benchmark', benchmark)):
        if record['provider'] not in PROVIDERS:
            raise ValueError('Unknown provider')
        if manifest['synthetic'] != (record['provider'] == 'synthetic'):
            raise ValueError('Synthetic source flag mismatch')
        if record['data_as_of'] != day:
            raise ValueError('Source date mismatch')
        observed = stamp(record['source_timestamp'])
        retrieved = stamp(record['retrieved_at'])
        if observed > retrieved or observed.date().isoformat() != day:
            raise ValueError('Source timestamp mismatch')
        if not record.get('access_tool') or not record.get('evidence_reference'):
            raise ValueError('Source tool and evidence reference are required')
        if record.get('currency') != 'HKD' or record.get('amount_unit') != 'HKD':
            raise ValueError('Source currency or turnover units mismatch')
        if record.get('volume_unit') != 'shares':
            raise ValueError('Volume must be expressed in shares')
        if kind == 'bars' and record.get('adjustment') != 'qfq':
            raise ValueError('Stock OHLC must have explicit qfq basis')
        if not manifest['synthetic']:
            raw_ref = record['raw_evidence_file']
            if raw_ref not in files:
                raise ValueError('Real-source evidence must be included and hashed')
    calendar = read_json(root / 'calendar.json')
    dates = calendar['trading_dates']
    if dates != sorted(set(dates)) or any(iso_day(d) != d for d in dates):
        raise ValueError('Calendar must be ordered unique ISO dates')
    if calendar.get('synthetic') is not manifest['synthetic']:
        raise ValueError('Calendar synthetic flag mismatch')
    if calendar['latest_completed_trade_date'] != day or day not in dates:
        raise ValueError('Calendar completed date mismatch')
    later = [d for d in dates if d > day]
    if not later or calendar['next_trade_date'] != later[0]:
        raise ValueError('Next date must be the next bound calendar date')
    if not manifest['synthetic'] and calendar.get('calendar_evidence_file') not in files:
        raise ValueError('Real calendar requires hashed calendar evidence')
    for name in ('bars.csv', 'benchmark.csv'):
        seen = set()
        with (root / name).open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                row_day = iso_day(row['date'])
                key = row['symbol'], row_day
                if key in seen or row_day > day or row_day not in dates:
                    raise ValueError('Duplicate, future or noncalendar market row')
                seen.add(key)
                values = {k: float(row[k]) for k in ('open', 'high', 'low', 'close', 'amount', 'volume')}
                if not all(math.isfinite(v) for v in values.values()):
                    raise ValueError('Nonfinite market data')
                if min(values[k] for k in ('open', 'high', 'low', 'close')) <= 0:
                    raise ValueError('Nonpositive OHLC')
                if min(values['amount'], values['volume']) < 0:
                    raise ValueError('Negative turnover or volume')
                if not values['low'] <= min(values['open'], values['close']) <= max(values['open'], values['close']) <= values['high']:
                    raise ValueError('Invalid OHLC ordering')
    if 'gildata_facts.json' in files:
        facts = read_json(root / 'gildata_facts.json')
        for fact in facts:
            if fact['provider'] != ('synthetic' if manifest['synthetic'] else 'gildata'):
                raise ValueError('Financial fact provider mismatch')
            if stamp(fact['published_at']) > stamp(fact['retrieved_at']):
                raise ValueError('Financial fact timestamp mismatch')
            if stamp(fact['published_at']).date().isoformat() > day:
                raise ValueError('Financial fact published after snapshot date')
            if not fact.get('evidence_reference'):
                raise ValueError('Financial fact requires an evidence reference')
    return root, manifest, sources
