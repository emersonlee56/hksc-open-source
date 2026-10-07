"""Synthetic market scenarios; no downloaded or private market data."""
from datetime import date, timedelta
from pathlib import Path
import csv

from hksc_engine.core_universe import symbols_sha256
from .bundle import sha, write_json


def generate(directory, ends=None):
    ends = tuple(ends) if ends is not None else (129, 133)
    if not ends or tuple(sorted(set(ends))) != ends or min(ends) < 120:
        raise ValueError('Synthetic endpoints must be ordered unique indices with enough history')
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)
    dates = []
    day = date(2025, 1, 2)
    while len(dates) < max(135, max(ends) + 2):
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += timedelta(days=1)
    symbols = tuple(f'DEMO.{i:05d}' for i in range(1, 141))
    fields = ('symbol', 'date', 'open', 'high', 'low', 'close', 'amount', 'volume')
    roots = []
    for end in ends:
        name = ('signal' if end == 129 else 'followup') if ends == (129, 133) else dates[end]
        bundle = root / name
        bundle.mkdir()
        roots.append(bundle)
        with (bundle / 'universe.csv').open('x', encoding='utf-8', newline='') as handle:
            columns = ('security_code', 'eligible_phase0', 'normalized_security_type',
                       'exchange_board', 'trading_currency', 'trading_status',
                       'liquidity_verified', 'turnover_20d_median_hkd')
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for symbol in symbols:
                writer.writerow(dict(zip(columns, (symbol, 'true', 'ORDINARY',
                                                   'MAIN', 'HKD', 'NORMAL', 'true', 300000000))))
        write_json(bundle / 'universe.json', {
            'artifact_type': 'HK_CORE_TRADABLE_UNIVERSE', 'production_trading_pool': False,
            'version': 'core_tradable_universe_v0.1-provisional', 'status': 'SYNTHETIC_DEMO',
            'source': {'data_path': 'universe.csv', 'sha256': sha(bundle / 'universe.csv')},
            'symbols': symbols, 'symbols_sha256': symbols_sha256(symbols), 'expected_count': 140,
            'effective_from': dates[0], 'refresh_policy': {'next_scheduled_refresh': dates[-1]},
            'rules': {'turnover_20d_median_hkd_min': 200000000},
        })
        with (bundle / 'bars.csv').open('x', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for number, symbol in enumerate(symbols):
                for idx, current in enumerate(dates[:end + 1]):
                    if number < 5:
                        close = (20 + number) * (1 + idx * (0.003 + number * 0.0002))
                        if idx >= 129:
                            close *= 1.03
                    else:
                        close = (30 + number / 10) * (1 - idx * 0.0003)
                    # Three different lifecycle paths: stop, hold, profit target.
                    if idx > 129 and number == 0:
                        close *= 0.93
                    if idx > 129 and number == 4:
                        close *= 1.05
                    opening = close * 0.997 if idx <= 129 else ((20 + number) * (1 + 129 * (0.003 + number * 0.0002)) * 1.03 if number < 5 else close)
                    high, low = max(opening, close) * 1.003, min(opening, close) * 0.997
                    volume = 18000000 if idx == 129 else 12000000
                    amount = round(close * volume, 6)
                    writer.writerow(dict(zip(fields, (symbol, current, round(opening, 6), round(high, 6),
                                                       round(low, 6), round(close, 6), amount, volume))))
        with (bundle / 'benchmark.csv').open('x', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for idx, current in enumerate(dates[:end + 1]):
                close = 20000 + idx * 5
                writer.writerow(dict(zip(fields, ('HK.800000', current, close, close + 30,
                                                   close - 30, close, close * 1000000, 1000000))))
        write_json(bundle / 'calendar.json', {
            'trading_dates': dates, 'latest_completed_trade_date': dates[end],
            'next_trade_date': dates[end + 1], 'synthetic': True,
            'source': 'synthetic weekday calendar, not the actual HKEX calendar',
        })
        record = {
            'provider': 'synthetic', 'access_tool': 'hksc.demo.generate',
            'data_as_of': dates[end], 'source_timestamp': dates[end] + 'T16:10:00+08:00',
            'retrieved_at': dates[end] + 'T16:11:00+08:00', 'currency': 'HKD',
            'amount_unit': 'HKD', 'volume_unit': 'shares', 'adjustment': 'qfq',
            'evidence_reference': 'procedurally generated fictional fixture',
        }
        write_json(bundle / 'sources.json', {
            'bars': record, 'benchmark': record,
            'stock_provenance_assessment': {'adjustment': 'qfq', 'synthetic': True},
        })
        write_json(bundle / 'gildata_facts.json', [{
            'provider': 'synthetic', 'symbol': 'DEMO.00005', 'category': 'fictional_company_context',
            'statement': '合成背景示例：此记录不对应真实公告或公司，且不参与 HK-M1 扫描。',
            'published_at': dates[end] + 'T15:30:00+08:00',
            'retrieved_at': dates[end] + 'T16:11:00+08:00',
            'evidence_reference': 'fictional fact generated independently of all suppliers',
        }])
        files = {p.name: sha(p) for p in sorted(bundle.iterdir())}
        write_json(bundle / 'bundle.json', {
            'format': 'hksc-public-bundle/1', 'as_of_date': dates[end],
            'synthetic': True, 'files': files,
        })
    return roots
