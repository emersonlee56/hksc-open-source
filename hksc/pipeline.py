"""Local research orchestration; no scheduler, network access or trading."""
from datetime import date
from pathlib import Path
import html

from .bundle import read_json, sha, write_json
from .context import observe_context
from .delivery import load_delivery, load_run
from .demo import generate
from .evaluation import evaluate_run
from .plan import cell, document_html
from .research import run_research
from .weekly import build_weekly


def seal_directory(root):
    files = {p.relative_to(root).as_posix(): sha(p)
             for p in sorted(root.rglob('*')) if p.is_file() and p != root / 'result_hashes.json'}
    write_json(root / 'result_hashes.json', files)


def isolate_failed_stage(root, name):
    """Preserve new partial bytes as evidence, not as a completed delivery."""
    stage = root / name
    if not stage.exists():
        return None
    if stage.is_symlink() or not stage.is_dir():
        raise ValueError('Failed stage must be a local directory')
    records = {}
    for path in sorted(stage.rglob('*')):
        if path.is_symlink():
            raise ValueError('Failed stage evidence cannot contain symlinks')
        if not path.is_file():
            continue
        original = path.relative_to(stage).as_posix()
        if path.name == 'result_hashes.json':
            stored = path.with_name('result_hashes.json.incomplete')
            if stored.exists():
                raise ValueError('Failed stage evidence filename collision')
            path.rename(stored)
            path = stored
        records[original] = {'stored_path': path.relative_to(stage).as_posix(), 'sha256': sha(path)}
    destination = root / 'failed_artifacts' / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError('Failed stage evidence already exists')
    stage.rename(destination)
    write_json(destination / 'failure_evidence.json',
               {'format': 'hksc-failed-stage/1', 'stage': name,
                'is_completed_delivery': False, 'files': records})
    return destination.relative_to(root).as_posix()


def failure_receipt(root, filename, receipt, exc):
    receipt.update(status='BLOCKED', reason=str(exc), error_type=type(exc).__name__)
    # This directory has not completed publication; never touch a prior delivery.
    try:
        path = root / filename
        pending = root / (filename + '.failure.tmp')
        pending.write_text(__import__('json').dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        pending.replace(path)
    except Exception:
        receipt['failure_receipt_persisted'] = False
    return receipt


def prior_agenda(directory, run):
    root, _ = load_delivery(directory, ('weekly.json',))
    review = read_json(root / 'weekly.json')
    if review.get('format') != 'hksc-weekly/1' or review.get('is_actual_trade') is not False:
        raise ValueError('Agenda requires a public research review')
    if review['end_date'] >= run['as_of_date'] or review['synthetic'] is not run['synthetic']:
        raise ValueError('Prior review must precede this run in the same research mode')
    if review['universe_symbols_sha256'] != run['universe_symbols_sha256'] or review['strategy_version'] != run['strategy_version']:
        raise ValueError('Prior review universe or strategy mismatch')
    return {'format': 'hksc-research-agenda/1', 'as_of_date': run['as_of_date'],
            'prior_review_sha256': sha(root / 'result_hashes.json'),
            'questions': review['questions'], 'changes_strategy': False}


def daily(input_directory, output, prior=None, policy_path=None, prior_review=None):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    receipt = {'format': 'hksc-daily-receipt/1', 'status': 'BLOCKED', 'stages': {},
               'is_actual_trade': False, 'repair_authorized': False}
    links, notes = [], []
    try:
        previous = load_run(prior)[0] if prior else None
        run = run_research(input_directory, root / 'research', previous)
        receipt.update(as_of_date=run['as_of_date'], synthetic=run['synthetic'],
                       research_result_hashes_sha256=sha(root / 'research/result_hashes.json'))
        receipt['stages']['research'] = {'status': 'COMPLETE'}
        receipt['degradations'] = list(run.get('degradations', []))
        links.append(('每日行动计划', 'research/report.html'))
        for name, callback in (('evaluation', lambda: evaluate_run(root / 'research', input_directory, root / 'evaluation', policy_path)),
                               ('context', lambda: observe_context(root / 'research', input_directory, root / 'context'))):
            try:
                value = callback()
                receipt['stages'][name] = {'status': 'COMPLETE',
                                           'result_hashes_sha256': sha(root / name / 'result_hashes.json')}
                links.append(('效果观察' if name == 'evaluation' else '市场环境', name + '/report.html'))
                if name == 'evaluation' and value['portfolio'] and any(v['status'] in {'DATA_BLOCKED', 'ASSUMPTION_BLOCKED'} for v in value['portfolio'].values()):
                    receipt['degradations'].append({'module': 'portfolio_model', 'status': 'DEGRADED',
                                                     'reason': 'Explicit simulation assumptions or valuation data cannot support a complete portfolio curve'})
            except Exception as exc:
                evidence = isolate_failed_stage(root, name)
                receipt['stages'][name] = {'status': 'DEGRADED', 'reason': str(exc),
                                           'failure_evidence_directory': evidence}
                receipt['degradations'].append({'module': name, 'status': 'DEGRADED', 'reason': str(exc)})
        if prior_review:
            try:
                agenda = prior_agenda(prior_review, run)
                write_json(root / 'research_agenda.json', agenda)
                receipt['stages']['agenda'] = {'status': 'COMPLETE', 'prior_review_sha256': agenda['prior_review_sha256']}
                notes = [q['question'] + ' / ' + q['observation_condition'] for q in agenda['questions']]
            except Exception as exc:
                receipt['stages']['agenda'] = {'status': 'DEGRADED', 'reason': str(exc)}
                receipt['degradations'].append({'module': 'agenda', 'status': 'DEGRADED', 'reason': str(exc)})
        else:
            receipt['stages']['agenda'] = {'status': 'NOT_PROVIDED'}
        receipt['status'] = 'COMPLETE_WITH_DEGRADATION' if receipt['degradations'] else 'COMPLETE'
    except Exception as exc:
        receipt['stages']['research'] = {'status': 'BLOCKED', 'reason': str(exc)}
        receipt['reason'] = str(exc)
    lines = ['# HKSC 日常研究', '', f'运行状态：{receipt["status"]}；仅用于研究。', '',
             '模式：' + ('合成数据回放。' if receipt.get('synthetic') is True else
                         ('外部数据回放。' if receipt.get('synthetic') is False else '未建立有效研究输入。')), '',
             '| 阶段 | 状态 | 原因 |', '| --- | --- | --- |']
    for name, stage in receipt['stages'].items():
        lines.append(f'| {name} | {stage["status"]} | {cell(stage.get("reason", "--"))} |')
    lines += ['', '## 上次复盘留下的研究问题', '']
    lines += ['- ' + cell(note) for note in notes] if notes else ['本次未取得前序复盘问题，不推断已有问题已解决。']
    lines += ['', '## 边界', '', '各阶段失败不会自动修复输入或重新运行主线。所有候选均为研究模拟，不操作账户。']
    markdown = '\n'.join(lines) + '\n'
    navigation = '<nav>' + ' · '.join(f'<a href="{html.escape(path, quote=True)}">{html.escape(label)}</a>' for label, path in links) + '</nav>'
    try:
        (root / 'report.md').write_text(markdown, encoding='utf-8')
        (root / 'index.html').write_text(document_html('HKSC 日常研究', markdown).replace('<main>', '<main>' + navigation, 1), encoding='utf-8')
        write_json(root / 'daily_receipt.json', receipt)
        seal_directory(root)
    except Exception as exc:
        failure_receipt(root, 'daily_receipt.json', receipt, exc)
    return receipt


def full_demo(output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    try:
        return _full_demo(root)
    except Exception as exc:
        return failure_receipt(root, 'demo.json', {'format': 'hksc-closed-loop-demo/1',
                               'synthetic': True, 'is_actual_trade': False, 'repair_authorized': False}, exc)


def _full_demo(root):
    inputs = generate(root / 'inputs', range(129, 140))
    policy = {'format': 'hksc-evaluation-policy/1',
              'label': 'Fictional closed-loop demonstration; not a live allocation or actual broker cost',
              'initial_capital_hkd': 1000000, 'allocation_fraction': 0.25,
              'commission_bps': 10, 'slippage_bps': 5}
    policy_path = root / 'evaluation.demo.json'
    write_json(policy_path, policy)
    previous, review, current_days, reviews, days = None, None, [], [], []
    for index, input_directory in enumerate(inputs):
        day = read_json(input_directory / 'bundle.json')['as_of_date']
        destination = root / 'daily' / day
        receipt = daily(input_directory, destination, previous, policy_path, review)
        if receipt['status'] == 'BLOCKED':
            raise ValueError('Synthetic demo mainline blocked: ' + receipt['reason'])
        previous = destination
        current_days.append(destination)
        days.append({'as_of_date': day, 'directory': destination.relative_to(root).as_posix(),
                     'status': receipt['status'], 'stages': receipt['stages']})
        if date.fromisoformat(day).weekday() == 4 or index == len(inputs) - 1:
            destination = root / 'weekly' / day
            completed = {record['as_of_date']: record['stages'] for record in days}
            evaluations = [d / 'evaluation' for d in current_days if completed[d.name]['evaluation']['status'] == 'COMPLETE']
            contexts = [d / 'context' for d in current_days if completed[d.name]['context']['status'] == 'COMPLETE']
            start = current_days[0].name
            try:
                result = build_weekly(current_days, destination, start, day, evaluations, contexts, review)
                record = {'start_date': result['start_date'], 'end_date': day, 'status': 'COMPLETE',
                          'directory': destination.relative_to(root).as_posix(),
                          'question_count': len(result['questions'])}
            except Exception as exc:
                evidence = isolate_failed_stage(root / 'weekly', day)
                record = {'start_date': start, 'end_date': day, 'status': 'DEGRADED',
                          'directory': None, 'reason': str(exc), 'error_type': type(exc).__name__,
                          'failure_evidence_directory': (Path('weekly') / evidence).as_posix() if evidence else None}
            else:
                review = destination
            reviews.append(record)
            current_days = []
    payload = {'format': 'hksc-closed-loop-demo/1',
               'status': 'COMPLETE_WITH_DEGRADATION' if any(d['status'] != 'COMPLETE' for d in days + reviews) else 'COMPLETE', 'synthetic': True,
               'is_actual_trade': False, 'days': days, 'reviews': reviews,
               'last_daily': days[-1]['directory'], 'last_review': review.relative_to(root).as_posix() if review else None,
               'data_sources': 'All data and background facts are generated; no supplier was queried',
               'evaluation_assumptions': policy}
    write_json(root / 'demo.json', payload)
    rows = ''.join(f'<tr><td>{d["as_of_date"]}</td><td>{d["status"]}</td>'
                   f'<td><a href="{d["directory"]}/index.html">日常研究</a></td>'
                   f'<td><a href="{d["directory"]}/research/report.html">行动计划</a></td>' +
                   ('<td><a href="' + d['directory'] + '/evaluation/report.html">效果观察</a></td></tr>'
                    if d['stages']['evaluation']['status'] == 'COMPLETE' else '<td>评价降级，未提供报告</td></tr>') for d in days)
    weekly_links = ''.join(
        (f'<p><a href="{r["directory"]}/report.html">{r["start_date"]} 至 {r["end_date"]}：周末复盘</a>'
         f' / 待验证问题 {r["question_count"]}</p>') if r['status'] == 'COMPLETE' else
        (f'<p>{r["start_date"]} 至 {r["end_date"]}：复盘降级 / {html.escape(r["reason"])}</p>')
        for r in reviews)
    markdown = '# HKSC 完整研究演示\n\n11 个连续合成研究日，覆盖行动计划、候选跟踪、效果观察、环境与复盘问题延续。\n\n' \
               '所有价格、日历、背景与成本模型均为虚构，不代表真实接入或策略业绩。\n'
    extra = '<div class="scroll"><table><tr><th>研究日</th><th>状态</th><th>入口</th><th>计划</th><th>评价</th></tr>' + rows + '</table></div><h2>期间复盘</h2>' + weekly_links
    (root / 'index.html').write_text(document_html('HKSC 完整研究演示', markdown).replace('</main>', extra + '</main>', 1), encoding='utf-8')
    (root / 'report.md').write_text(markdown + '\n' + '\n'.join(d['as_of_date'] + ': ' + d['directory'] for d in days), encoding='utf-8')
    seal_directory(root)
    return payload
