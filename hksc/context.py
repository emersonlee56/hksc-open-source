"""Read-only pool breadth and benchmark observations, not strategy filters."""
from statistics import median

from hksc_engine.hkm1_scanner import load_daily_series
from .bundle import read_json, sha, validate_bundle
from .delivery import load_run, publish_report, validate_run_input


def observe_context(run_directory, input_directory, output):
    run_root, run, _ = load_run(run_directory)
    root, manifest, _ = validate_bundle(input_directory)
    validate_run_input(run, root, manifest)
    symbols = read_json(root / 'universe.json')['symbols']
    series = load_daily_series(root / 'bars.csv')
    benchmark_rows = load_daily_series(root / 'benchmark.csv')
    if len(benchmark_rows) != 1:
        raise ValueError('Context requires one benchmark')
    benchmark_symbol, benchmark = next(iter(benchmark_rows.items()))
    index = benchmark['by_date'].get(run['as_of_date'])
    if index is None or index < 20:
        raise ValueError('Benchmark context needs completed 20-day history')
    close = benchmark['close'][index]
    sma20 = sum(benchmark['close'][index - 19:index + 1]) / 20
    returns, above, unavailable = [], 0, []
    for symbol in symbols:
        daily = series.get(symbol, {})
        pos = daily.get('by_date', {}).get(run['as_of_date'])
        if pos is None or pos < 20:
            unavailable.append(symbol)
            continue
        value = daily['close'][pos]
        returns.append(value / daily['close'][pos - 20] - 1)
        above += value > sum(daily['close'][pos - 19:pos + 1]) / 20
    count = len(returns)
    payload = {
        'format': 'hksc-context/1', 'as_of_date': run['as_of_date'],
        'synthetic': run['synthetic'], 'is_actual_trade': False,
        'observation_mode': run['observation_mode'], 'strategy_version': run['strategy_version'],
        'universe_symbols_sha256': run['universe_symbols_sha256'],
        'run_result_hashes_sha256': sha(run_root / 'result_hashes.json'),
        'bundle_sha256': sha(root / 'bundle.json'), 'strategy_input': False,
        'benchmark': {'symbol': benchmark_symbol, 'close': close, 'sma20': sma20,
                      'above_sma20': close > sma20,
                      'return_20d': close / benchmark['close'][index - 20] - 1},
        'pool_breadth': {'pool_count': len(symbols), 'observed_count': count,
                         'above_sma20_fraction': above / count if count else None,
                         'positive_return_20d_fraction': sum(r > 0 for r in returns) / count if count else None,
                         'median_return_20d': median(returns) if returns else None,
                         'unavailable_symbols': unavailable},
        'limitations': ['广度仅覆盖使用者研究池，不代表整个港股市场。',
                        '指标是已发生的日线事实，不证明策略因果关系，也不改变候选或规则。',
                        '不推断完整南向、市场资金流或公司事件；需要对应来源证据。'],
    }
    breadth = payload['pool_breadth']
    pct = lambda v: '--' if v is None else f'{v:.2%}'
    text = '\n'.join([f'# HKSC 市场环境观察 | {run["as_of_date"]}', '',
                       '只读研究旁路；不调整 HK-M1 准入或候选状态。', '',
                       f'模式：{"合成数据回放" if run["synthetic"] else "外部数据回放"}。', '',
                       '| 指标 | 观察值 |', '| --- | --- |',
                       f'| 基准 20 日收益 | {payload["benchmark"]["return_20d"]:.2%} |',
                       f'| 基准高于 SMA20 | {payload["benchmark"]["above_sma20"]} |',
                       f'| 研究池覆盖 | {count}/{len(symbols)} |',
                       f'| 研究池高于 SMA20 比例 | {pct(breadth["above_sma20_fraction"])} |',
                       f'| 研究池 20 日正收益比例 | {pct(breadth["positive_return_20d_fraction"])} |',
                       f'| 研究池 20 日收益中位数 | {pct(breadth["median_return_20d"])} |', '',
                       '## 限制', ''] + ['- ' + n for n in payload['limitations']]) + '\n'
    return publish_report(output, 'context', payload, text, 'HKSC 市场环境观察')
