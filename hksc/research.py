"""Independent public workflow around the inherited scanner and lifecycle."""
from pathlib import Path
import hashlib
import html
import json

from hksc_engine.core_universe import load_core_universe
from hksc_engine.hkm1_scanner import build_scan, load_daily_series
from hksc_engine.hkm1_lifecycle import replay_candidate_lifecycle
from .bundle import read_json, sha, validate_bundle, write_json


def history_digest(series, through_date):
    rows = [[d] + [series[k][i] for k in ('open', 'high', 'low', 'close', 'amount')]
            for i, d in enumerate(series['dates']) if d <= through_date]
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


def candidate_from(scan, row):
    key = f"PUBLIC|{scan['as_of_date']}|{row['symbol']}|{scan['strategy_version']}"
    return {
        'candidate_id': 'PUBLIC-' + hashlib.sha256(key.encode()).hexdigest()[:16],
        'symbol': row['symbol'], 'signal_date': scan['as_of_date'],
        'valid_for_trade_date': scan['valid_for_trade_date'], 'frozen_decision': 'TRADE',
        'signal_close': row['signal_close'], 'atr14': row['atr14'],
        'chase_limit': row['chase_limit'], 'is_actual_trade': False,
    }


def validate_prior(directory, current_manifest, series, calendar, universe_hash):
    prior = Path(directory).resolve()
    hashes = read_json(prior / 'result_hashes.json')
    for name in ('run.json', 'candidates.json', 'lifecycle.json', 'history_bindings.json', 'events.json'):
        if hashes.get(name) != sha(prior / name):
            raise ValueError('Prior artifact hash mismatch: ' + name)
    run = read_json(prior / 'run.json')
    if run['format'] != 'hksc-public-run/1' or run['as_of_date'] >= current_manifest['as_of_date']:
        raise ValueError('Prior run date or format mismatch')
    if run['synthetic'] is not current_manifest['synthetic'] or run['is_actual_trade'] is not False:
        raise ValueError('Prior run research mode mismatch')
    if run['universe_symbols_sha256'] != universe_hash:
        raise ValueError('Universe changed between research runs')
    if calendar[:len(run['completed_calendar'])] != run['completed_calendar']:
        raise ValueError('Completed calendar changed')
    bindings = read_json(prior / 'history_bindings.json')
    for symbol, digest in bindings.items():
        if symbol not in series or history_digest(series[symbol], run['as_of_date']) != digest:
            raise ValueError('Historical prices changed; separate price-basis review required')
    candidates = read_json(prior / 'candidates.json')
    if len({c['candidate_id'] for c in candidates}) != len(candidates):
        raise ValueError('Duplicate prior candidate')
    return candidates, read_json(prior / 'events.json')


def render_report(run, scan, states, sources):
    demo = '合成数据演示' if run['synthetic'] else '外部数据研究'
    counts = scan['summary']
    lines = [f'# HKSC 研究日报 | {run["as_of_date"]}', '',
             f'模式：{demo}；研究用途；所有入场和退出均为模拟。', '',
             f'数据覆盖：{counts["eligible_count"]}/{counts["core_count"]}；'
             f'本次扫描合格候选：{counts["trade_count"]}；'
             f'容量观察：{counts["watch_capacity_count"]}。', '',
             f'当前开放模拟候选：{run["open_candidate_count"]}/3。', '',
             '| 标的 | 生命周期 | 行动状态 | 模拟入场 | 初始止损 | 目标 |',
             '|---|---|---|---:|---:|---:|']
    for state in states:
        values = [state['symbol'], state['lifecycle_status'], state['actionability_state']]
        values += ['--' if state[key] is None else f'{state[key]:.4f}'
                   for key in ('entry_price', 'initial_stop', 'target')]
        lines.append('| ' + ' | '.join(values) + ' |')
    lines += ['', '## 数据来源', '']
    for kind in ('bars', 'benchmark'):
        record = sources[kind]
        lines.append(f'- {kind}: {record["provider"]} / {record["access_tool"]}；'
                     f'数据时点 {record["source_timestamp"]}；获取时点 {record["retrieved_at"]}。')
    lines += ['', '## 解释边界', '',
              'TRADE / ENTER_IF 是示例规则的研究状态，不是实际交易指令。',
              '本报告未计算组合净收益、交易成本、容量影响或策略 Alpha。',
              '公告和财务背景不参与 HK-M1 行情信号的计算。',
              '外部来源可用性和生产运行验收须另行完成；合成日期不代表真实交易日。', '']
    return '\n'.join(lines)


def report_html(run, scan, states, sources):
    esc = html.escape
    demo = '合成数据演示' if run['synthetic'] else '外部数据研究'
    rows = ''.join('<tr>' + ''.join('<td>' + esc(str(value)) + '</td>' for value in
                                 (state['symbol'], state['lifecycle_status'], state['actionability_state'],
                                  '--' if state['entry_price'] is None else round(state['entry_price'], 4))) + '</tr>'
                   for state in states)
    source_rows = ''.join(f'<p><b>{esc(kind)}</b> {esc(sources[kind]["provider"])} / '
                          f'{esc(sources[kind]["access_tool"])}<br>'
                          f'<small>{esc(sources[kind]["source_timestamp"])}</small></p>'
                          for kind in ('bars', 'benchmark'))
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>HKSC 研究日报</title>
<style>:root{{--ink:#153a35;--paper:#f5f2e9;--accent:#bd652f}}*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(at top right,#e1e9db,transparent 65%),var(--paper);color:var(--ink);font-family:Georgia,"Songti SC",serif}}
main{{max-width:1000px;margin:auto;padding:50px 24px}}header{{border-top:5px solid var(--accent);padding-top:24px}}
.label{{letter-spacing:3px;color:var(--accent)}}h1{{font-size:clamp(30px,6vw,54px);margin:18px 0}}
.metrics{{display:flex;gap:24px;flex-wrap:wrap;margin:32px 0}}.metric{{flex:1;min-width:150px;border-top:1px solid #b8c3b6;padding:18px 0}}
.metric b{{display:block;font-size:36px}}.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}
th,td{{text-align:left;padding:14px 10px;border-bottom:1px solid #ccd1c3}}h2{{margin-top:36px}}p{{line-height:1.7}}
footer{{margin-top:36px;border-top:1px solid #b8c3b6;padding-top:20px;font-size:14px}}</style>
<main><header><div class="label">HKSC / RESEARCH JOURNAL</div><h1>港股研究，留下证据。</h1>
<p>{esc(run['as_of_date'])} · {demo} · 全部为模拟研究</p></header><div class="metrics">
<div class="metric"><b>{scan['summary']['eligible_count']}/140</b>历史数据覆盖</div>
<div class="metric"><b>{scan['summary']['trade_count']}</b>本次扫描候选</div>
<div class="metric"><b>{run['open_candidate_count']}/3</b>开放模拟候选</div></div>
<h2>候选生命周期</h2><div class="scroll"><table><tr><th>标的</th><th>生命周期</th><th>行动状态</th><th>模拟入场</th></tr>{rows}</table></div>
<h2>本次数据来源</h2>{source_rows}<footer>该演示未计算组合净收益、成本或 Alpha。合成数据和合成日历不代表真实市场。
<br>JSON 输入哈希、扫描结果、事件与研究状态保存在同目录。公告和财务背景不参与行情信号计算。</footer></main></html>'''


def run_research(directory, output, prior=None):
    root, manifest, sources = validate_bundle(directory)
    target = Path(output)
    if target.exists():
        raise ValueError('Output must be a new directory')
    core = load_core_universe(root / 'universe.json')
    series = load_daily_series(root / 'bars.csv')
    calendar = read_json(root / 'calendar.json')['trading_dates']
    completed = [d for d in calendar if d <= manifest['as_of_date']]
    previous, old_events = (validate_prior(prior, manifest, series, completed,
                                         read_json(root / 'universe.json')['symbols_sha256'])
                            if prior else ([], []))
    scan, coverage = build_scan(universe_path=root / 'universe.json',
                               bars_path=root / 'bars.csv', benchmark_path=root / 'benchmark.csv',
                               calendar_path=root / 'calendar.json', source_manifest_path=root / 'sources.json',
                               as_of_date=manifest['as_of_date'])
    states = [replay_candidate_lifecycle(c, series[c['symbol']], calendar,
                                       manifest['as_of_date']) for c in previous]
    terminal = {'PASS_TERMINAL', 'INVALIDATED', 'TARGET_HIT'}
    active = {s['symbol'] for s in states if s['lifecycle_status'] not in terminal}
    free = max(0, 3 - len(active))
    qualified = sorted((r for r in scan['symbols'] if r['decision'] in {'TRADE', 'WATCH_CAPACITY'}),
                       key=lambda r: r['qualified_rank'])
    new_candidates = []
    for row in qualified:
        if row['symbol'] in active:
            continue
        if len(new_candidates) >= free:
            break
        candidate = candidate_from(scan, row)
        new_candidates.append(candidate)
        states.append(replay_candidate_lifecycle(candidate, series[row['symbol']], calendar,
                                                manifest['as_of_date']))
    candidates = previous + new_candidates
    events = {event['event_id']: event for event in old_events}
    for state in states:
        for event in state['events']:
            if event['event_id'] in events and events[event['event_id']] != event:
                raise ValueError('Existing event changed')
            events[event['event_id']] = event
    bindings = {s: history_digest(series[s], manifest['as_of_date']) for s in core.symbols if s in series}
    run = {'format': 'hksc-public-run/1', 'as_of_date': manifest['as_of_date'],
           'synthetic': manifest['synthetic'], 'is_actual_trade': False,
           'qualification_state': 'RESEARCH_ONLY', 'review_required': True,
           'universe_symbols_sha256': read_json(root / 'universe.json')['symbols_sha256'],
           'completed_calendar': completed, 'bundle_sha256': sha(root / 'bundle.json'),
           'prior_result_hashes_sha256': sha(Path(prior) / 'result_hashes.json') if prior else None,
           'open_candidate_count': sum(s['lifecycle_status'] not in terminal for s in states),
           'new_candidate_count': len(new_candidates), 'source_records': sources}
    target.mkdir(parents=True, exist_ok=False)
    artifacts = {'run.json': run, 'scan.json': scan, 'coverage.json': coverage,
                 'candidates.json': candidates, 'lifecycle.json': states,
                 'events.json': sorted(events.values(), key=lambda e: (e['observed_trade_date'], e['event_id'])),
                 'history_bindings.json': bindings}
    for name, value in artifacts.items():
        write_json(target / name, value)
    (target / 'report.md').write_text(render_report(run, scan, states, sources), encoding='utf-8')
    (target / 'report.html').write_text(report_html(run, scan, states, sources), encoding='utf-8')
    write_json(target / 'result_hashes.json', {p.name: sha(p) for p in sorted(target.iterdir())})
    return run
