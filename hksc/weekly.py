"""Period reviews and append-only research questions; never tune strategy."""
import hashlib

from .bundle import iso_day, read_json, sha
from .delivery import load_delivery, load_run, publish_report
from .plan import cell


def linked_sidecars(directories, kind, by_hash, synthetic):
    result = []
    for directory in directories:
        root, _ = load_delivery(directory, (kind + '.json',))
        value = read_json(root / (kind + '.json'))
        bound = value.get('run_result_hashes_sha256')
        if bound not in by_hash or value.get('as_of_date') != by_hash[bound]['as_of_date']:
            raise ValueError('Review sidecar not bound to a supplied run')
        if value.get('synthetic') is not synthetic or value.get('is_actual_trade') is not False:
            raise ValueError('Review sidecar mode mismatch')
        expected_mode = 'SYNTHETIC_REPLAY' if synthetic else 'EXTERNAL_DATA_REPLAY'
        if value.get('observation_mode') != expected_mode:
            raise ValueError('Review sidecar observation mode mismatch')
        if value.get('bundle_sha256') != by_hash[bound]['bundle_sha256']:
            raise ValueError('Review sidecar input bundle mismatch')
        if value.get('strategy_version') != by_hash[bound]['strategy_version'] or value.get('universe_symbols_sha256') != by_hash[bound]['universe_symbols_sha256']:
            raise ValueError('Review sidecar strategy or universe mismatch')
        if value.get('format') != 'hksc-' + kind + '/1':
            raise ValueError('Review sidecar format mismatch')
        result.append((value, sha(root / 'result_hashes.json')))
    return result


def render_weekly(review):
    coverage = review['coverage']
    lines = [f'# HKSC 周末复盘 | {review["start_date"]} 至 {review["end_date"]}', '',
             f'模式：{"合成数据回放" if review["synthetic"] else "外部数据回放"}；所有事件均为模拟。', '',
             '## 期间覆盖', '',
             f'已提供研究日：{len(coverage["provided_dates"])}；已知期间交易日：{len(coverage["expected_dates"])}。',
             '缺失研究日：' + (', '.join(coverage['missing_dates']) or '无（在已知日历范围内）') + '。',
             '日历未覆盖的期间：' + (str(coverage['unknown_calendar_range']) if coverage['unknown_calendar_range'] else '无') + '。',
             '不连续的前序绑定：' + (', '.join(review['chain_gaps']) or '无（所提供结果之间）') + '。', '',
             '## 候选与事件', '',
             f'本期新增信号 {review["summary"]["new_signal_count"]}；模拟进入 {review["summary"]["entry_count"]}；'
             f'模拟退出 {review["summary"]["exit_count"]}。', '',
             '| 日期 | 标的 | 事件 | 原因 |', '| --- | --- | --- | --- |']
    for event in review['period_events']:
        lines.append('| ' + ' | '.join(cell(event.get(k, '--')) for k in
                                      ('observed_trade_date', 'symbol', 'event_type', 'reason')) + ' |')
    lines += ['', '## 效果观察', '']
    if review['evaluation_as_of'] is None:
        lines.append('本期未提供有效效果观察，不推断策略表现。')
    else:
        lines.append(f'观察截至 {review["evaluation_as_of"]}；本期已结束候选 {len(review["closed_candidates"])}。')
        if review['evaluation_as_of'] < review['end_date']:
            lines.append('效果观察尚未覆盖期间末尾，不能视为完整期间结论。')
        for row in review['closed_candidates']:
            lines.append(f'- {cell(row["symbol"])}：{row["exit_date"]}；毛收益 {row["gross_return"]:.2%}；'
                         f'退出原因 {cell(row["exit_reason"])}。')
    lines += ['', '## 市场环境', '']
    if review['context_as_of'] is None:
        lines.append('本期未提供有效环境观察，不补造环境归因。')
    else:
        lines.append(f'最新环境观察截至 {review["context_as_of"]}；'
                     '研究池广度不代表全市场，也不能单独证明收益原因。')
        facts = review['latest_context']
        lines.append(f'基准 20 日收益 {facts["benchmark"]["return_20d"]:.2%}；'
                     f'池内有效覆盖 {facts["pool_breadth"]["observed_count"]}。')
    lines += ['', '## 下周关注与待验证问题', '']
    for question in review['questions']:
        lines.append(f'- {cell(question["question"])} 首次提出：{question["first_proposed_date"]}；'
                     f'状态：{question["status"]}；观察条件：{cell(question["observation_condition"])}。')
    lines += ['', '## 研究边界', '',
              '事实、观察和问题分开保存。以上问题需要人工复核，不自动调参，不回写信号或候选。',
              '合成回放、外部数据回放与真实前向研究不混为一条业绩序列。']
    return '\n'.join(lines) + '\n'


def build_weekly(run_directories, output, start_date, end_date,
                 evaluations=(), contexts=(), prior=None):
    start, end = iso_day(start_date), iso_day(end_date)
    if start > end or not run_directories:
        raise ValueError('Review requires an ordered period and at least one run')
    loaded = []
    for directory in run_directories:
        root, run, _ = load_run(directory)
        if not start <= run['as_of_date'] <= end:
            raise ValueError('Review run is outside explicit period')
        loaded.append((root, run, sha(root / 'result_hashes.json')))
    loaded.sort(key=lambda x: x[1]['as_of_date'])
    dates = [run['as_of_date'] for _, run, _ in loaded]
    if len(set(dates)) != len(dates):
        raise ValueError('Review contains duplicate research dates')
    synthetic = loaded[0][1]['synthetic']
    universe = loaded[0][1]['universe_symbols_sha256']
    strategy = read_json(loaded[0][0] / 'scan.json')['strategy_version']
    all_events, all_candidates, chain_gaps = {}, {}, []
    previous_hash = None
    expected, known_calendar = set(), set()
    by_hash = {}
    for root, run, digest in loaded:
        if run['synthetic'] is not synthetic or run['universe_symbols_sha256'] != universe:
            raise ValueError('Review cannot mix modes or research universes')
        if read_json(root / 'scan.json')['strategy_version'] != strategy:
            raise ValueError('Review cannot mix strategy versions')
        if previous_hash and run['prior_result_hashes_sha256'] != previous_hash:
            chain_gaps.append(run['as_of_date'])
        previous_hash = digest
        by_hash[digest] = run
        known_calendar.update(run['bound_calendar'])
        expected.update(d for d in run['bound_calendar'] if start <= d <= end)
        for candidate in read_json(root / 'candidates.json'):
            identifier = candidate['candidate_id']
            if identifier in all_candidates and all_candidates[identifier] != candidate:
                raise ValueError('Review candidate changed across runs')
            all_candidates[identifier] = candidate
        for event in read_json(root / 'events.json'):
            identifier = event['event_id']
            if identifier in all_events and all_events[identifier] != event:
                raise ValueError('Review event changed across runs')
            all_events[identifier] = event
    calendar_from, calendar_through = min(known_calendar), max(known_calendar)
    unknown_ranges = []
    if start < calendar_from:
        unknown_ranges.append({'from': start, 'before': calendar_from})
    if end > calendar_through:
        unknown_ranges.append({'after': calendar_through, 'through': end})
    period_events = []
    for event in all_events.values():
        if start <= event['observed_trade_date'] <= end:
            if event['candidate_id'] not in all_candidates:
                raise ValueError('Review event references unknown candidate')
            period_events.append(dict(event, symbol=all_candidates[event['candidate_id']]['symbol']))
    period_events.sort(key=lambda e: (e['observed_trade_date'], e['event_id']))
    evals = linked_sidecars(evaluations, 'evaluation', by_hash, synthetic)
    envs = linked_sidecars(contexts, 'context', by_hash, synthetic)
    latest_eval = max(evals, key=lambda x: x[0]['as_of_date'])[0] if evals else None
    latest_env = max(envs, key=lambda x: x[0]['as_of_date'])[0] if envs else None
    closed = [r for r in latest_eval['candidates'] if r['status'] == 'CLOSED' and start <= r['exit_date'] <= end] if latest_eval else []
    missing = sorted(expected - set(dates))
    evidence = [{'as_of_date': run['as_of_date'], 'result_hashes_sha256': digest} for _, run, digest in loaded]
    old_questions = []
    prior_digest = None
    if prior:
        prior_root, _ = load_delivery(prior, ('weekly.json',))
        old = read_json(prior_root / 'weekly.json')
        if old.get('format') != 'hksc-weekly/1' or old.get('synthetic') is not synthetic or old.get('is_actual_trade') is not False:
            raise ValueError('Prior review mode or format mismatch')
        if old['end_date'] >= start or old['universe_symbols_sha256'] != universe or old['strategy_version'] != strategy:
            raise ValueError('Prior review period, pool or strategy mismatch')
        old_questions = old['questions']
        prior_digest = sha(prior_root / 'result_hashes.json')
    topics = [('SIGNAL_OUTCOMES', '当前研究方法的进入与失效条件是否值得继续观察？',
               '累积已结束与未结束候选，保留失败案例，人工比较不同期间的结果。'),
              ('ENVIRONMENT_LINK', '候选结果与研究池、基准环境之间有什么可验证的关系？',
               '在同一口径下积累环境与候选结果，不从单周样本直接推断因果。')]
    if missing or chain_gaps or unknown_ranges:
        topics.append(('DATA_GAPS', '期间的数据与研究记录缺口是否影响结论？',
                       '后续取得可核验资料或说明限制，不回填为当时已完成的研究。'))
    questions = {q['question_id']: q for q in old_questions}
    continued_topics = {q['topic']: (q['topic'], q['question'], q['observation_condition']) for q in old_questions}
    continued_topics.update({topic[0]: topic for topic in topics})
    for topic, text, condition in continued_topics.values():
        identifier = 'Q-' + hashlib.sha256((strategy + '|' + topic).encode()).hexdigest()[:16]
        old = questions.get(identifier)
        observation = {'start_date': start, 'end_date': end, 'closed_candidate_count': len(closed),
                       'missing_dates': missing, 'unknown_calendar_range': unknown_ranges or None,
                       'current_period_has_data_gaps': bool(missing or chain_gaps or unknown_ranges),
                       'evidence': evidence}
        questions[identifier] = {
            'question_id': identifier, 'topic': topic, 'question': text,
            'first_proposed_date': old['first_proposed_date'] if old else end,
            'status': 'AWAITING_HUMAN_REVIEW', 'observation_condition': condition,
            'observations': (old['observations'] if old else []) + [observation],
            'changes_strategy': False,
        }
    payload = {
        'format': 'hksc-weekly/1', 'start_date': start, 'end_date': end,
        'synthetic': synthetic, 'is_actual_trade': False, 'strategy_version': strategy,
        'observation_mode': 'SYNTHETIC_REPLAY' if synthetic else 'EXTERNAL_DATA_REPLAY',
        'universe_symbols_sha256': universe, 'prior_review_sha256': prior_digest,
        'run_evidence': evidence, 'chain_gaps': chain_gaps,
        'coverage': {'provided_dates': dates, 'expected_dates': sorted(expected), 'missing_dates': missing,
                     'unknown_calendar_range': unknown_ranges or None,
                     'complete': not missing and not chain_gaps and not unknown_ranges},
        'summary': {'new_signal_count': sum(start <= c['signal_date'] <= end for c in all_candidates.values()),
                    'entry_count': sum(e['event_type'] == 'SIMULATED_ENTRY' for e in period_events),
                    'exit_count': sum(e['event_type'] == 'SIMULATED_EXIT' for e in period_events)},
        'period_events': period_events, 'closed_candidates': closed,
        'evaluation_as_of': latest_eval['as_of_date'] if latest_eval else None,
        'context_as_of': latest_env['as_of_date'] if latest_env else None,
        'latest_context': latest_env,
        'sidecar_evidence': {'evaluation': [d for _, d in evals], 'context': [d for _, d in envs]},
        'questions': sorted(questions.values(), key=lambda q: q['question_id']),
        'automatic_rule_changes': False,
    }
    return publish_report(output, 'weekly', payload, render_weekly(payload), 'HKSC 周末复盘')
