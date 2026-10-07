"""Candidate observations and explicitly configured fictional portfolio models."""
import math

from hksc_engine.hkm1_scanner import load_daily_series
from .bundle import read_json, sha, validate_bundle
from .delivery import load_run, publish_report, validate_run_input
from .plan import cell


def number(value, name, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('Evaluation policy needs finite number: ' + name)
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError('Evaluation policy out of range: ' + name)
    return float(value)


def validate_policy(policy):
    if policy.get('format') != 'hksc-evaluation-policy/1' or not isinstance(policy.get('label'), str) or not policy['label'].strip():
        raise ValueError('Evaluation policy needs format and explicit assumption label')
    result = dict(policy)
    for key in ('initial_capital_hkd', 'allocation_fraction', 'commission_bps', 'slippage_bps'):
        result[key] = number(policy[key], key)
    if result['initial_capital_hkd'] <= 0 or not 0 < result['allocation_fraction'] <= 1:
        raise ValueError('Capital and allocation must be positive; fraction cannot exceed one')
    if result['slippage_bps'] >= 10000 or result['commission_bps'] >= 10000:
        raise ValueError('Friction must be less than 10000 bps per side')
    return result


def net_return(entry, exit_price, policy):
    fee, slip = policy['commission_bps'] / 10000, policy['slippage_bps'] / 10000
    return exit_price * (1 - slip) * (1 - fee) / (entry * (1 + slip) * (1 + fee)) - 1


def reference_return(benchmark, entry_date, through_date):
    start, end = benchmark['by_date'].get(entry_date), benchmark['by_date'].get(through_date)
    if start is None or end is None:
        return None
    return benchmark['close'][end] / benchmark['open'][start] - 1


def candidate_observations(run, candidates, states, series, benchmark, policy):
    by_id = {s['candidate_id']: s for s in states}
    if len({c['candidate_id'] for c in candidates}) != len(candidates) or len(by_id) != len(states) or by_id.keys() != {c['candidate_id'] for c in candidates}:
        raise ValueError('Candidate evaluation needs unique corresponding states')
    calendar_order = run.get('bound_calendar', run.get('completed_calendar', []))
    calendar = set(calendar_order)
    rows = []
    for candidate in candidates:
        signal, entered = candidate['signal_date'], candidate['valid_for_trade_date']
        if signal not in calendar or entered not in calendar or calendar_order.index(entered) != calendar_order.index(signal) + 1:
            raise ValueError('Candidate entry is not the next bound trading day')
        state = by_id[candidate['candidate_id']]
        entries = [e for e in state['events'] if e['event_type'] == 'SIMULATED_ENTRY']
        exits = [e for e in state['events'] if e['event_type'] == 'SIMULATED_EXIT']
        for event in state['events']:
            event_day = event['observed_trade_date']
            if event_day not in calendar or not candidate['valid_for_trade_date'] <= event_day <= run['as_of_date']:
                raise ValueError('Candidate event date is outside bound trading window')
        if entries and (entries[0]['observed_trade_date'] != candidate['valid_for_trade_date'] or candidate['signal_date'] >= entries[0]['observed_trade_date']):
            raise ValueError('Candidate signal and entry chronology mismatch')
        if len(entries) > 1 or len(exits) > 1 or (exits and not entries):
            raise ValueError('Inconsistent simulated candidate events')
        row = {'candidate_id': candidate['candidate_id'], 'symbol': candidate['symbol'],
               'signal_date': candidate['signal_date'], 'status': 'NOT_ENTERED',
               'entry_date': None, 'exit_date': None, 'valuation_date': None,
               'gross_return': None, 'net_return': None, 'benchmark_reference_return': None,
               'excess_reference_return': None, 'r_multiple': None,
               'exit_reason': state.get('exit_reason'), 'is_actual_trade': False}
        if state['actionability_state'] == 'DATA_BLOCKED':
            row['status'] = 'INCOMPLETE'
        if entries:
            entry = entries[0]
            entry_price = number(entry['entry_price'], 'entry_price', minimum=0.00000001)
            if entry['observed_trade_date'] > run['as_of_date']:
                raise ValueError('Entry lies after observation date')
            row['entry_date'] = entry['observed_trade_date']
            row['status'] = 'OPEN'
            final_price = None
            if exits:
                exit_event = exits[0]
                final_price = number(exit_event['exit_price'], 'exit_price', minimum=0.00000001)
                row.update(status='CLOSED', exit_date=exit_event['observed_trade_date'],
                           valuation_date=exit_event['observed_trade_date'], exit_reason=exit_event['reason'])
                if not row['entry_date'] <= row['exit_date'] <= run['as_of_date']:
                    raise ValueError('Exit chronology mismatch')
            elif state['actionability_state'] == 'DATA_BLOCKED':
                row['status'] = 'INCOMPLETE'
            else:
                daily = series.get(candidate['symbol'], {})
                index = daily.get('by_date', {}).get(run['as_of_date'])
                if index is None:
                    row['status'] = 'INCOMPLETE'
                else:
                    final_price = daily['close'][index]
                    row['valuation_date'] = run['as_of_date']
            if final_price is not None:
                row['gross_return'] = final_price / entry_price - 1
                risk = entry_price - entry['initial_stop']
                row['r_multiple'] = (final_price - entry_price) / risk if risk > 0 else None
                row['benchmark_reference_return'] = reference_return(benchmark, row['entry_date'], row['valuation_date'])
                if row['benchmark_reference_return'] is not None:
                    row['excess_reference_return'] = row['gross_return'] - row['benchmark_reference_return']
                if policy and row['status'] == 'CLOSED':
                    row['net_return'] = net_return(entry_price, final_price, policy)
        rows.append(row)
    return rows


def portfolio_model(run, candidates, states, series, benchmark, policy, friction=True):
    symbols = {c['candidate_id']: c['symbol'] for c in candidates}
    events = [e for s in states for e in s['events'] if e['event_type'] in {'SIMULATED_ENTRY', 'SIMULATED_EXIT'}]
    if not events:
        return {'status': 'NO_ENTRIES', 'curve': [], 'total_return': None, 'max_drawdown': None}
    initial = policy['initial_capital_hkd']
    budget = initial * policy['allocation_fraction']
    fee = policy['commission_bps'] / 10000 if friction else 0
    slip = policy['slippage_bps'] / 10000 if friction else 0
    first = min(e['observed_trade_date'] for e in events)
    calendar = [d for d in run['completed_calendar'] if first <= d <= run['as_of_date']]
    by_day = {}
    for event in events:
        if event['observed_trade_date'] not in calendar:
            raise ValueError('Portfolio event not in completed calendar')
        by_day.setdefault(event['observed_trade_date'], []).append(event)
    start_index = benchmark['by_date'].get(first)
    if start_index is None:
        return {'status': 'DATA_BLOCKED', 'reason': 'BENCHMARK_START_MISSING', 'curve': []}
    reference_open = benchmark['open'][start_index]
    cash, peak, drawdown, costs = initial, initial, 0.0, 0.0
    positions, curve = {}, []
    def order(event):
        if event['event_type'] == 'SIMULATED_EXIT' and event.get('reason') in {'STOP_GAP', 'TREND', 'TIME_60D'}:
            return (0, event['candidate_id'])
        return (1 if event['event_type'] == 'SIMULATED_ENTRY' else 2, event['candidate_id'])
    for day in calendar:
        for event in sorted(by_day.get(day, []), key=order):
            identifier = event['candidate_id']
            if event['event_type'] == 'SIMULATED_ENTRY':
                if identifier in positions or len(positions) >= 3:
                    raise ValueError('Portfolio entry violates candidate capacity')
                if budget > cash + 0.000001:
                    return {'status': 'ASSUMPTION_BLOCKED', 'reason': 'FIXED_ALLOCATION_EXCEEDS_AVAILABLE_CASH', 'curve': []}
                raw = event['entry_price']
                filled = raw * (1 + slip)
                units = budget / (filled * (1 + fee))
                costs += units * (filled - raw) + units * filled * fee
                positions[identifier] = (symbols[identifier], units)
                cash -= budget
            else:
                if identifier not in positions:
                    raise ValueError('Portfolio exit without held candidate')
                _, units = positions.pop(identifier)
                raw = event['exit_price']
                filled = raw * (1 - slip)
                costs += units * (raw - filled) + units * filled * fee
                cash += units * filled * (1 - fee)
        marked = 0.0
        for symbol, units in positions.values():
            daily = series.get(symbol, {})
            index = daily.get('by_date', {}).get(day)
            if index is None:
                return {'status': 'DATA_BLOCKED', 'reason': 'HELD_CANDIDATE_BAR_MISSING', 'curve': []}
            marked += units * daily['close'][index]
        index = benchmark['by_date'].get(day)
        if index is None:
            return {'status': 'DATA_BLOCKED', 'reason': 'BENCHMARK_BAR_MISSING', 'curve': []}
        equity = cash + marked
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
        curve.append({'date': day, 'cash_hkd': cash, 'marked_value_hkd': marked,
                      'equity_hkd': equity, 'open_candidates': len(positions),
                      'benchmark_equity_hkd': initial * benchmark['close'][index] / reference_open})
    return {'status': 'SIMULATION_ONLY', 'curve': curve,
            'total_return': curve[-1]['equity_hkd'] / initial - 1,
            'max_drawdown': drawdown, 'modeled_friction_hkd': costs,
            'benchmark_reference_return': curve[-1]['benchmark_equity_hkd'] / initial - 1,
            'unliquidated_candidate_count': len(positions)}


def render_evaluation(payload):
    summary = payload['summary']
    lines = [f'# HKSC 策略效果观察 | {payload["as_of_date"]}', '',
             '仅评价研究模拟事件，不是账户收益，也不构成 Alpha 验证。', '',
             f'规则版本：{payload["strategy_version"]}。', '',
             f'研究池成员绑定：{payload["universe_symbols_sha256"]}。', '',
             f'模式：{payload["observation_mode"]}；已结束 {summary["closed_count"]}；'
             f'未结束 {summary["open_count"]}；未进入 {summary["not_entered_count"]}；'
             f'数据不完整 {summary["incomplete_count"]}。', '',
             '| 标的 | 状态 | 毛收益 | 成本后已结束收益 | 日线基准参考 | R 倍数 |',
             '| --- | --- | ---: | ---: | ---: | ---: |']
    for row in payload['candidates']:
        values = [cell(row['symbol']), row['status']]
        values += ['--' if row[k] is None else f'{row[k]:.2%}'
                   for k in ('gross_return', 'net_return', 'benchmark_reference_return')]
        values += ['--' if row['r_multiple'] is None else f'{row["r_multiple"]:.3f}']
        lines.append('| ' + ' | '.join(values) + ' |')
    lines += ['', '## 评价口径', ''] + ['- ' + note for note in payload['limitations']]
    policy = payload['policy']
    lines += ['', '## 组合研究模型', '']
    if policy is None:
        lines.append('未提供资金与成本假设，不输出组合净值或净收益。')
    else:
        lines += [f'假设名称：{cell(policy["label"])}。每个候选使用初始假设资金的 '
                  f'{policy["allocation_fraction"]:.2%}；单边佣金 {policy["commission_bps"]} bps，'
                  f'滑点 {policy["slippage_bps"]} bps。', '']
        for name in ('gross', 'net'):
            result = payload['portfolio'][name]
            lines.append(f'- {name}: {result["status"]}；' +
                         (f'区间收益 {result["total_return"]:.2%}，最大日线回撤 {result["max_drawdown"]:.2%}。'
                          if result.get('total_return') is not None else str(result.get('reason', '无可评价事件'))))
    return '\n'.join(lines) + '\n'


def evaluate_run(run_directory, input_directory, output, policy_path=None):
    run_root, run, _ = load_run(run_directory)
    root, manifest, _ = validate_bundle(input_directory)
    validate_run_input(run, root, manifest)
    policy = validate_policy(read_json(policy_path)) if policy_path else None
    candidates = read_json(run_root / 'candidates.json')
    states = read_json(run_root / 'lifecycle.json')
    series = load_daily_series(root / 'bars.csv')
    benchmarks = load_daily_series(root / 'benchmark.csv')
    if len(benchmarks) != 1:
        raise ValueError('Evaluation requires exactly one benchmark')
    benchmark = next(iter(benchmarks.values()))
    rows = candidate_observations(run, candidates, states, series, benchmark, policy)
    closed = [r for r in rows if r['status'] == 'CLOSED']
    payload = {
        'format': 'hksc-evaluation/1', 'as_of_date': run['as_of_date'],
        'synthetic': run['synthetic'], 'is_actual_trade': False,
        'strategy_version': run['strategy_version'],
        'universe_symbols_sha256': run['universe_symbols_sha256'],
        'observation_mode': 'SYNTHETIC_REPLAY' if run['synthetic'] else 'EXTERNAL_DATA_REPLAY',
        'run_result_hashes_sha256': sha(run_root / 'result_hashes.json'),
        'bundle_sha256': sha(root / 'bundle.json'),
        'policy_sha256': sha(policy_path) if policy_path else None, 'policy': policy,
        'summary': {'closed_count': len(closed), 'open_count': sum(r['status'] == 'OPEN' for r in rows),
                    'not_entered_count': sum(r['status'] == 'NOT_ENTERED' for r in rows),
                    'incomplete_count': sum(r['status'] == 'INCOMPLETE' for r in rows),
                    'closed_mean_gross_return': sum(r['gross_return'] for r in closed) / len(closed) if closed else None},
        'candidates': rows, 'portfolio': None,
        'limitations': [
            '候选均值不是组合收益；未结束候选按研究日收盘标记，不计入已实现结果。',
            '基准参考使用候选进入日开盘至退出或观察日收盘；不能还原候选盘中退出时刻的同步基准。',
            '未提供显式成本政策时，仅报告候选毛收益，不假设零成本。',
            '可选组合模型使用固定初始资金比例、允许分数股、无杠杆；不是真实仓位规则。',
            '成本为显式线性佣金与滑点假设，不代表券商费率、税费、容量或完整市场冲击。',
            '开放候选按收盘标记，未扣未来清算成本；基准为无成本的日线参考。',
            '不合并合成数据、历史回放与真实前向业绩；研究池选择可能存在幸存者偏差。',
        ],
    }
    if policy:
        payload['portfolio'] = {name: portfolio_model(run, candidates, states, series, benchmark, policy, friction)
                                for name, friction in (('gross', False), ('net', True))}
    return publish_report(output, 'evaluation', payload, render_evaluation(payload), 'HKSC 策略效果观察')
