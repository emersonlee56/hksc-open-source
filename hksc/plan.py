"""Deterministic daily research plans, separate from account actions."""
import html


TERMINAL = {'PASS_TERMINAL', 'INVALIDATED', 'TARGET_HIT'}
ACTION_LABELS = {'REVIEW_DATA': '复核数据缺口', 'REVIEW_RECORDED_EXIT': '复核新增终止事件',
                 'ARCHIVE': '保留历史', 'WATCH_ENTRY_CONDITION': '等待进入条件',
                 'WATCH_EXIT_CONDITION': '等待退出开盘证据', 'TRACK_CANDIDATE': '继续跟踪'}


def build_plan(run, scan, candidates, states, previous_states=(), facts=()):
    previous = {s['candidate_id']: s for s in previous_states}
    by_id = {c['candidate_id']: c for c in candidates}
    items = []
    for state in states:
        candidate = by_id[state['candidate_id']]
        status = state['lifecycle_status']
        today = [e for e in state['events'] if e['observed_trade_date'] == run['as_of_date']]
        old = previous.get(state['candidate_id'])
        old_event_ids = {e['event_id'] for e in old['events']} if old else set()
        new_events = [e for e in state['events'] if e['event_id'] not in old_event_ids]
        next_date = state.get('next_action_trade_date')
        if state['actionability_state'] == 'DATA_BLOCKED':
            blocked = [e for e in state['events'] if e['event_type'] == 'DATA_BLOCKED']
            detail = blocked[-1] if blocked else {}
            action, explanation = 'REVIEW_DATA', '缺少必要证据：' + str(detail.get('reason', state.get('exit_reason'))) + '；日期 ' + str(detail.get('observed_trade_date', next_date))
        elif status in TERMINAL:
            action = 'REVIEW_RECORDED_EXIT' if new_events or old is None else 'ARCHIVE'
            explanation = state.get('exit_reason') or status
        elif state['entry_price'] is None:
            action, explanation = 'WATCH_ENTRY_CONDITION', '等待指定交易日开盘，核对追价与止损条件。'
        elif state['actionability_state'] == 'EXIT' and next_date:
            action, explanation = 'WATCH_EXIT_CONDITION', '已触发退出条件，等待指定交易日开盘证据。'
        else:
            action, explanation = 'TRACK_CANDIDATE', '继续跟踪已记录的止损、目标及趋势退出条件。'
        change = 'NEW' if old is None else ('UNCHANGED' if old == state else 'UPDATED')
        items.append({
            'candidate_id': state['candidate_id'], 'symbol': state['symbol'],
            'signal_date': candidate['signal_date'], 'change': change,
            'lifecycle_status': status, 'research_action': action,
            'previous_lifecycle_status': old['lifecycle_status'] if old else None,
            'reason': explanation, 'next_observation_date': next_date,
            'entry_price': state['entry_price'], 'chase_limit': candidate['chase_limit'],
            'initial_stop': state['initial_stop'], 'target': state['target'],
            'events_today': today, 'events_since_prior': new_events, 'is_actual_trade': False,
            'signal_gates': candidate.get('signal_gates', {}), 'signal_score': candidate.get('signal_score'),
            'initial_stop_formula': candidate.get('initial_stop_formula'),
            'target_formula': candidate.get('target_formula'),
        })
    return {
        'format': 'hksc-daily-plan/1', 'as_of_date': run['as_of_date'],
        'next_trade_date': scan['valid_for_trade_date'],
        'strategy_version': scan['strategy_version'], 'synthetic': run['synthetic'],
        'observation_mode': 'SYNTHETIC_REPLAY' if run['synthetic'] else 'EXTERNAL_DATA_REPLAY',
        'is_actual_trade': False, 'review_required': True,
        'lineage': {'bundle_sha256': run['bundle_sha256'],
                    'prior_result_hashes_sha256': run['prior_result_hashes_sha256'],
                    'prior_as_of_date': run.get('prior_as_of_date'),
                    'universe_version': run.get('universe_version'),
                    'universe_symbols_sha256': run.get('universe_symbols_sha256')},
        'summary': {'qualified_count': scan['summary']['trade_count'] + scan['summary']['watch_capacity_count'],
                    'new_candidate_count': run['new_candidate_count'],
                    'open_candidate_count': run['open_candidate_count'],
                    'data_blocked_count': sum(i['research_action'] == 'REVIEW_DATA' for i in items)},
        'scan_coverage': {'observed_count': scan['summary'].get('eligible_count', 0),
                          'pool_count': scan['summary'].get('core_count', 0),
                          'blocked_count': scan['summary'].get('data_blocked_count', 0)},
        'scan_data_gaps': [{'symbol': row['symbol'], 'reasons': row['failure_reasons']}
                           for row in scan.get('symbols', []) if row['decision'] == 'DATA_BLOCKED'],
        'degradations': run.get('degradations', []),
        'items': items, 'background_facts': list(facts), 'source_records': run['source_records'],
        'human_review': ['背景资料不参与 HK-M1 准入规则。',
                         '模拟事件来自完成日线回放，不代表当时已经取得前向证据。',
                         '研究动作不是账户指令，交易与投资判断由使用者自行承担。'],
    }


def cell(value):
    return str(value).replace('|', '&#124;').replace('\n', ' ')


def render_plan(plan):
    mode = '合成数据回放' if plan['synthetic'] else '外部数据回放'
    summary = plan['summary']
    lines = [f'# HKSC 每日行动计划 | {plan["as_of_date"]}', '',
             f'模式：{mode}；仅用于研究，全部进入与退出均为模拟。', '',
             f'规则版本：`{plan["strategy_version"]}`；下一交易日：{plan["next_trade_date"]}。', '',
             ('起始研究。' if plan['lineage']['prior_as_of_date'] is None else
              f'续接 {plan["lineage"]["prior_as_of_date"]}；前序绑定 {plan["lineage"]["prior_result_hashes_sha256"]}。'),
             f'研究池版本：{plan["lineage"]["universe_version"]}；成员绑定：{plan["lineage"]["universe_symbols_sha256"]}。', '',
             f'扫描覆盖 {plan["scan_coverage"]["observed_count"]}/{plan["scan_coverage"]["pool_count"]}；'
             f'扫描数据缺口 {plan["scan_coverage"]["blocked_count"]}。', '',
             f'合格扫描结果 {summary["qualified_count"]}；新增候选 {summary["new_candidate_count"]}；'
             f'开放候选 {summary["open_candidate_count"]}；已有候选数据缺口 {summary["data_blocked_count"]}。', '',
             '## 今日关注', '',
             '| 标的 | 变化 | 研究动作 | 下一观察日 | 追价上限 | 止损 | 目标 |',
             '| --- | --- | --- | --- | ---: | ---: | ---: |']
    focused = [i for i in plan['items'] if i['research_action'] != 'ARCHIVE']
    for item in focused:
        values = [item[k] for k in ('symbol', 'change', 'research_action', 'next_observation_date',
                                   'chase_limit', 'initial_stop', 'target')]
        values[2] = ACTION_LABELS[values[2]]
        lines.append('| ' + ' | '.join('--' if v is None else cell(round(v, 4) if isinstance(v, float) else v)
                                     for v in values) + ' |')
    if not focused:
        lines += ['', '当前没有需要继续跟踪的候选，不新增推荐。']
    lines += ['', '## 候选变化与依据', '']
    for item in focused:
        lines.append(f'- {cell(item["symbol"])}：{cell(item["previous_lifecycle_status"] or "首次记录")} → '
                     f'{cell(item["lifecycle_status"])}；{cell(item["reason"])}')
        lines.append(f'- 入选依据：{cell(item["signal_gates"])}；信号分数 {item["signal_score"]}。')
        if item['initial_stop_formula']:
            lines.append(f'- 初始止损条件：{cell(item["initial_stop_formula"])}；目标条件：{cell(item["target_formula"])}。')
        for event in item['events_since_prior']:
            lines.append(f'- 新记录事件：{event["observed_trade_date"]} / {cell(event["event_type"])} / {cell(event.get("reason", "--"))}。')
    lines += ['', '## 数据缺口与降级', '']
    for gap in plan['scan_data_gaps']:
        lines.append(f'- 扫描缺口 {cell(gap["symbol"])}：{cell(gap["reasons"])}。')
    for degradation in plan['degradations']:
        lines.append(f'- {cell(degradation["module"])}：{cell(degradation["reason"])}；主线继续，未使用无效背景。')
    if not plan['scan_data_gaps'] and not plan['degradations']:
        lines.append('本次没有扫描覆盖缺口或可选模块降级；候选缺口见今日关注。')
    lines += ['', '## 公司与事件背景', '']
    if not plan['background_facts']:
        lines.append('本次未提供公司背景资料，不据此推断公司没有事件。')
    for fact in plan['background_facts']:
        lines.append(f'- {cell(fact.get("symbol", "市场"))}：{cell(fact.get("statement", "无摘要"))}；'
                     f'发布时间 {cell(fact["published_at"])}；引用 {cell(fact["evidence_reference"])}。')
    lines += ['', '## 数据来源', '']
    for kind in ('bars', 'benchmark'):
        record = plan['source_records'][kind]
        lines.append(f'- {kind}: {cell(record["provider"])} / {cell(record["access_tool"])}；'
                     f'来源时间 {cell(record["source_timestamp"])}；获取时间 {cell(record["retrieved_at"])}。')
    lines += ['', '## 人工复核', ''] + ['- ' + note for note in plan['human_review']]
    return '\n'.join(lines) + '\n'


def document_html(title, markdown):
    """Render a small, escaped report dialect; never execute source markup."""
    blocks, table = [], []
    def flush():
        if table:
            rows = []
            for index, line in enumerate(table):
                cells = [c.strip() for c in line.strip('|').split('|')]
                if cells and all(set(c) <= set('-: ') for c in cells):
                    continue
                tag = 'th' if index == 0 else 'td'
                rows.append('<tr>' + ''.join(f'<{tag}>{html.escape(c)}</{tag}>' for c in cells) + '</tr>')
            blocks.append('<div class="scroll"><table>' + ''.join(rows) + '</table></div>')
            table.clear()
    for line in markdown.splitlines():
        if line.startswith('|'):
            table.append(line)
            continue
        flush()
        if line.startswith('# '):
            blocks.append('<h1>' + html.escape(line[2:]) + '</h1>')
        elif line.startswith('## '):
            blocks.append('<h2>' + html.escape(line[3:]) + '</h2>')
        elif line.strip():
            blocks.append('<p>' + html.escape(line) + '</p>')
    flush()
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">' \
        '<meta name="viewport" content="width=device-width,initial-scale=1">' \
        '<title>' + html.escape(title) + '</title><style>' \
        ':root{--ink:#153a35;--paper:#f5f2e9;--accent:#bd652f}*{box-sizing:border-box}' \
        'body{margin:0;background:radial-gradient(at top right,#e1e9db,transparent 65%),var(--paper);' \
        'color:var(--ink);font-family:Georgia,"Songti SC",serif}' \
        'main{max-width:1100px;margin:auto;padding:40px 24px;border-top:5px solid var(--accent)}' \
        'h1{font-size:clamp(25px,5vw,42px)}h2{margin-top:36px}p{line-height:1.8;overflow-wrap:anywhere}' \
        '.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}' \
        'td,th{text-align:left;padding:12px 10px;border-bottom:1px solid #b8c3b6;min-width:90px}' \
        'th{color:var(--accent)}@media(max-width:600px){main{padding:24px 14px}}' \
        '</style></head><body><main>' + ''.join(blocks) + '</main></body></html>\n'
