"""Deterministic mechanical QA; never an ACCEPT decision or a data cleaner.

Old finite OHLC anomalies remain evidence, not a blanket snapshot veto. Required
trajectory windows are still checked by the separate price-basis guards.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

VERSION = 'hkm1-snapshot-quality/0.1'
FIELDS = ('open', 'high', 'low', 'close', 'amount', 'volume')


def valid_row(row):
    try:
        v = {k: Decimal(str(row[k])) for k in FIELDS}
        return (all(x.is_finite() for x in v.values())
                and all(v[k] > 0 for k in FIELDS[:4])
                and v['amount'] >= 0 and v['volume'] >= 0
                and v['low'] <= min(v['open'], v['close'])
                <= max(v['open'], v['close']) <= v['high'])
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return False


def assess_rows(rows, symbols, as_of_date, *, required_symbols=()):
    """Frozen 140/126/120 coverage; latest 61 raw rows must be valid.

    Return mechanical findings only. Non-numeric rows are global failures since
    the downstream loader reads the whole file. No row is removed or repaired.
    """
    if date.fromisoformat(as_of_date).isoformat() != as_of_date:
        raise ValueError('AS_OF_DATE')
    symbols = sorted(symbols)
    if len(symbols) != 140 or len(set(symbols)) != 140:
        raise ValueError('CORE_COUNT_OR_DUPLICATE')
    if not set(required_symbols) <= set(symbols):
        raise ValueError('REQUIRED_SYMBOL_OUTSIDE_CORE')
    grouped = defaultdict(list)
    blockers, anomalies, recent, scale = set(), [], [], []
    seen = set()
    for row in rows:
        symbol, day = row['symbol'], row['date']
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError(day)
        except ValueError:
            blockers.add('INVALID_DATE')
        if day > as_of_date:
            blockers.add('FUTURE_ROW')
        if symbol not in symbols:
            blockers.add('OUTSIDE_UNIVERSE')
        key = symbol, day
        if key in seen:
            blockers.add('DUPLICATE_KEY')
        seen.add(key)
        try:
            if not all(Decimal(str(row[k])).is_finite() for k in FIELDS):
                blockers.add('NONFINITE_FIELD')
        except (InvalidOperation, KeyError, TypeError, ValueError):
            blockers.add('NONNUMERIC_FIELD')
        grouped[symbol].append(row)
    coverage = []
    for symbol in symbols:
        history = sorted(grouped[symbol], key=lambda r: r['date'])
        bad = [dict(r) for r in history if not valid_row(r)]
        anomalies.extend(bad)
        current_bad = [dict(r) for r in history[-61:] if not valid_row(r)]
        recent.extend(current_bad)
        valid_count = sum(valid_row(r) for r in history)
        latest = history[-1]['date'] if history else None
        qualifies = valid_count >= 120 and latest == as_of_date and not current_bad
        coverage.append({'symbol': symbol, 'row_count': len(history),
                         'valid_ohlc_rows': valid_count, 'first_date': history[0]['date'] if history else None,
                         'last_date': latest, 'qualifies': qualifies})
        if latest == as_of_date and valid_row(history[-1]):
            r = history[-1]
            v, a = Decimal(r['volume']), Decimal(r['amount'])
            if (v == 0 and a != 0) or (v > 0 and not Decimal(r['low'])*Decimal('.99') <= a/v <= Decimal(r['high'])*Decimal('1.01')):
                scale.append(symbol)
    eligible = [r['symbol'] for r in coverage if r['qualifies']]
    if len(eligible) < 126:
        blockers.add('COVERAGE_BELOW_126')
    if recent:
        blockers.add('RECENT61_INVALID_REQUIRES_REVIEW')
    if scale:
        blockers.add('LATEST_SCALE_ANOMALY')
    required_missing = sorted(set(required_symbols)-set(eligible))
    if required_missing:
        blockers.add('REQUIRED_TRAJECTORY_DATA_MISSING')
    return {'version': VERSION, 'as_of_date': as_of_date,
            'mechanical_outcome': 'DATA_NO_GO' if blockers else 'DATA_READY',
            'requires_human_review': True, 'blockers': sorted(blockers),
            'rows_modified': False, 'invalid_rows': anomalies, 'latest61_invalid': recent,
            'eligible120': len(eligible), 'coverage': coverage,
            'missing_symbols': [s for s in symbols if not grouped[s]],
            'required_symbols_missing': required_missing, 'scale_violations': scale}
