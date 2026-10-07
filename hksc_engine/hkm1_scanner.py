"""Deterministic current-day scanner for frozen HK-M1 v0.1."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from .core_universe import load_core_universe, symbols_sha256
from .hkm1_snapshot_quality import assess_rows


SCHEMA_VERSION = "hkm1_public_scan_v0.1"
STRATEGY_VERSION = "hkm1_public_research_v0.1"
UNIVERSE_VERSION = "core_tradable_universe_v0.1-provisional"
QUALIFICATION_STATE = "RESEARCH_ONLY"
BENCHMARK = "HK.800000"

TURNOVER_MIN = 200_000_000.0
MIN_BARS = 120
MIN_COVERAGE = 126
MAX_TRADES = 3

GATE_FIELDS = (
    "liquidity",
    "absolute_momentum",
    "relative_momentum",
    "trend",
    "breakout",
    "volume_confirmation",
)
FAILURE_CODES = {
    "liquidity": "LIQUIDITY",
    "absolute_momentum": "ABSOLUTE_MOMENTUM",
    "relative_momentum": "RELATIVE_MOMENTUM",
    "trend": "TREND",
    "breakout": "BREAKOUT",
    "volume_confirmation": "VOL",
}
FOUNDATION_GATES = GATE_FIELDS[:4]


class ScannerInputError(ValueError):
    """Raised when the complete scan must fail closed."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _finite_float(value: str, *, field: str, symbol: str, date: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScannerInputError(f"NON_NUMERIC_{field.upper()}:{symbol}:{date}") from exc
    if not math.isfinite(number):
        raise ScannerInputError(f"NON_FINITE_{field.upper()}:{symbol}:{date}")
    return number


def load_daily_series(path: str | Path) -> dict[str, dict[str, list[Any]]]:
    required = {"symbol", "date", "open", "high", "low", "close", "amount"}
    result: dict[str, dict[str, list[Any]]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            missing = sorted(required.difference(reader.fieldnames or []))
            raise ScannerInputError(f"MISSING_CSV_COLUMNS:{','.join(missing)}")
        for row in reader:
            symbol = row["symbol"].strip()
            date = row["date"].strip()
            series = result.setdefault(
                symbol,
                {"dates": [], "open": [], "high": [], "low": [], "close": [], "amount": []},
            )
            series["dates"].append(date)
            for field in ("open", "high", "low", "close", "amount"):
                series[field].append(
                    _finite_float(row[field], field=field, symbol=symbol, date=date)
                )

    for symbol, series in result.items():
        order = sorted(range(len(series["dates"])), key=series["dates"].__getitem__)
        for field in ("dates", "open", "high", "low", "close", "amount"):
            series[field] = [series[field][idx] for idx in order]
        if len(series["dates"]) != len(set(series["dates"])):
            raise ScannerInputError(f"DUPLICATE_SYMBOL_DATE:{symbol}")
        series["by_date"] = {date: idx for idx, date in enumerate(series["dates"])}
    return result


def _load_calendar(path: str | Path, as_of_date: str) -> tuple[str, dict[str, Any]]:
    evidence = _read_json(path)
    dates = evidence.get("trading_dates") or evidence.get("completed_trading_dates") or []
    dates = sorted({str(value) for value in dates})
    latest = evidence.get("latest_completed_trade_date")
    if latest is None and dates:
        latest = max(value for value in dates if value <= as_of_date)
    if latest != as_of_date:
        raise ScannerInputError(f"CALENDAR_LATEST_MISMATCH:{latest}:{as_of_date}")
    if dates and as_of_date not in dates:
        raise ScannerInputError(f"AS_OF_NOT_TRADING_DAY:{as_of_date}")
    next_date = evidence.get("next_trade_date")
    if next_date is None and dates:
        later = [value for value in dates if value > as_of_date]
        next_date = later[0] if later else None
    if not next_date or str(next_date) <= as_of_date:
        raise ScannerInputError("NEXT_TRADE_DATE_UNAVAILABLE")
    return str(next_date), evidence


def _validate_adjustment(source_manifest: dict[str, Any], symbols: tuple[str, ...]) -> None:
    assessment = source_manifest.get("stock_provenance_assessment", {})
    global_adjustment = str(assessment.get("adjustment", "")).lower()
    raw_entries = source_manifest.get("symbols") or source_manifest.get("per_symbol") or []
    entries = {
        str(item.get("symbol")): str(item.get("adjustment", "")).lower()
        for item in raw_entries
        if isinstance(item, dict)
    }
    invalid = [
        symbol
        for symbol in symbols
        if entries.get(symbol, global_adjustment) not in {"qfq", "forward_adjusted"}
    ]
    if invalid:
        raise ScannerInputError(f"QFQ_PROVENANCE_MISSING:{','.join(invalid[:10])}")


def _true_range(series: dict[str, list[Any]], idx: int) -> float:
    high = series["high"][idx]
    low = series["low"][idx]
    if idx == 0:
        return high - low
    previous_close = series["close"][idx - 1]
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _evaluate(
    series: dict[str, list[Any]],
    idx: int,
    benchmark: dict[str, list[Any]],
    benchmark_idx: int,
) -> dict[str, Any]:
    close = series["close"]
    high = series["high"]
    amount = series["amount"]
    benchmark_close = benchmark["close"]

    return20 = close[idx] / close[idx - 20] - 1.0
    return60 = close[idx] / close[idx - 60] - 1.0
    benchmark20 = benchmark_close[benchmark_idx] / benchmark_close[benchmark_idx - 20] - 1.0
    benchmark60 = benchmark_close[benchmark_idx] / benchmark_close[benchmark_idx - 60] - 1.0
    sma20 = _mean(close[idx - 19 : idx + 1])
    sma60 = _mean(close[idx - 59 : idx + 1])
    liquidity_median = statistics.median(amount[idx - 19 : idx + 1])
    prior_turnover_median = statistics.median(amount[idx - 20 : idx])
    prior_high = max(high[idx - 20 : idx])
    atr14 = _mean([_true_range(series, pos) for pos in range(idx - 13, idx + 1)])

    gates = {
        "liquidity": "PASS" if liquidity_median >= TURNOVER_MIN else "FAIL",
        "absolute_momentum": "PASS" if return20 > 0 and return60 > 0 else "FAIL",
        "relative_momentum": (
            "PASS" if return20 > benchmark20 and return60 > benchmark60 else "FAIL"
        ),
        "trend": "PASS" if close[idx] > sma20 > sma60 else "FAIL",
        "breakout": "PASS" if close[idx] > prior_high else "FAIL",
        "volume_confirmation": (
            "PASS" if amount[idx] >= 1.2 * prior_turnover_median else "FAIL"
        ),
    }
    failures = [FAILURE_CODES[field] for field in GATE_FIELDS if gates[field] == "FAIL"]
    return {
        "gates": gates,
        "failure_reasons": failures,
        "score": (return20 - benchmark20) + (return60 - benchmark60),
        "signal_close": close[idx],
        "atr14": atr14,
        "chase_limit": close[idx] + atr14,
    }


def _blocked_symbol(symbol: str, valid_for_trade_date: str | None) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "decision": "DATA_BLOCKED",
        "actionability_state": "DATA_BLOCKED",
        "qualified_rank": None,
        "score": None,
        "gates": {field: "DATA_BLOCKED" for field in GATE_FIELDS},
        "failure_reasons": ["INSUFFICIENT_OR_STALE_SYMBOL_DATA"],
        "signal_close": None,
        "atr14": None,
        "chase_limit": None,
        "initial_stop_formula": None,
        "target_formula": None,
        "valid_for_trade_date": valid_for_trade_date,
        "is_actual_trade": False,
    }


def _classify(row: dict[str, Any], rank: int | None, next_date: str) -> dict[str, Any]:
    gates = row["gates"]
    all_pass = all(gates[field] == "PASS" for field in GATE_FIELDS)
    foundation_pass = all(gates[field] == "PASS" for field in FOUNDATION_GATES)
    failed_trigger_gates = {
        field for field in GATE_FIELDS[4:] if gates[field] == "FAIL"
    }
    if all_pass and rank is not None and rank <= MAX_TRADES:
        decision, action = "TRADE", "ENTER_IF"
    elif all_pass:
        decision, action = "WATCH_CAPACITY", "NO_ACTION"
    elif foundation_pass and failed_trigger_gates:
        decision, action = "WATCH_NEAR_TRIGGER", "NO_ACTION"
    else:
        decision, action = "PASS", "NO_ACTION"

    actionable_plan = decision in {"TRADE", "WATCH_CAPACITY"}
    return {
        "symbol": row["symbol"],
        "decision": decision,
        "actionability_state": action,
        "qualified_rank": rank if all_pass else None,
        "score": round(row["score"], 10),
        "gates": gates,
        "failure_reasons": row["failure_reasons"],
        "signal_close": round(row["signal_close"], 10),
        "atr14": round(row["atr14"], 10),
        "chase_limit": round(row["chase_limit"], 10),
        "initial_stop_formula": (
            "max(lowest_low_t_minus_9_to_t, open_next - 2*ATR14_t)"
            if actionable_plan
            else None
        ),
        "target_formula": (
            "open_next + 3*(open_next-initial_stop)" if actionable_plan else None
        ),
        "valid_for_trade_date": next_date,
        "is_actual_trade": False,
    }


def build_scan(
    *,
    universe_path: str | Path,
    bars_path: str | Path,
    benchmark_path: str | Path,
    calendar_path: str | Path,
    source_manifest_path: str | Path,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    core = load_core_universe(universe_path)
    if core.version != UNIVERSE_VERSION or len(core.symbols) != 140:
        raise ScannerInputError("CORE_UNIVERSE_VERSION_OR_COUNT_MISMATCH")
    # Public universe is bound by the supplied manifest and its source hash.

    # Reuse the frozen quality policy on the original CSV, not a external coverage
    # table or a filtered time series. Never shift momentum/ATR windows by
    # removing historical anomalies. Volume is mandatory here, not invented.
    with Path(bars_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "date", "open", "high", "low", "close", "amount", "volume"}
        if not required.issubset(reader.fieldnames or []):
            missing = sorted(required.difference(reader.fieldnames or []))
            raise ScannerInputError(f"MISSING_CSV_COLUMNS:{','.join(missing)}")
        quality = assess_rows(list(reader), core.symbols, as_of_date)
    if quality["mechanical_outcome"] != "DATA_READY":
        raise ScannerInputError("SNAPSHOT_QUALITY:" + ",".join(quality["blockers"]))
    symbol_quality = {row["symbol"]: row for row in quality["coverage"]}

    next_date, calendar = _load_calendar(calendar_path, as_of_date)
    source_manifest = _read_json(source_manifest_path)
    _validate_adjustment(source_manifest, core.symbols)
    stocks = load_daily_series(bars_path)
    benchmarks = load_daily_series(benchmark_path)
    if set(stocks).difference(core.symbols):
        raise ScannerInputError("BARS_CONTAIN_OUT_OF_UNIVERSE_SYMBOLS")
    if set(benchmarks) != {BENCHMARK}:
        raise ScannerInputError("BENCHMARK_FILE_SCOPE_MISMATCH")
    benchmark = benchmarks[BENCHMARK]
    benchmark_idx = benchmark["by_date"].get(as_of_date)
    if benchmark_idx is None or benchmark_idx < 60:
        raise ScannerInputError("BENCHMARK_AS_OF_OR_HISTORY_MISSING")
    if benchmark["dates"][-1] != as_of_date:
        raise ScannerInputError("BENCHMARK_HAS_STALE_OR_FUTURE_ROWS")

    coverage_rows: list[dict[str, Any]] = []
    eligible: list[str] = []
    for symbol in core.symbols:
        series = stocks.get(symbol)
        valid_bars = symbol_quality[symbol]["valid_ohlc_rows"]
        first_date = series["dates"][0] if series else None
        last_date = series["dates"][-1] if series else None
        qualifies = symbol_quality[symbol]["qualifies"]
        if qualifies:
            eligible.append(symbol)
        coverage_rows.append(
            {
                "symbol": symbol,
                "valid_bars": valid_bars,
                "first_date": first_date,
                "last_date": last_date,
                "qualifies": qualifies,
                "failure_reason": "" if qualifies else "INSUFFICIENT_OR_STALE_SYMBOL_DATA",
            }
        )
    if len(eligible) < MIN_COVERAGE:
        raise ScannerInputError(f"COVERAGE_GATE_FAILED:{len(eligible)}:{MIN_COVERAGE}")

    evaluated: dict[str, dict[str, Any]] = {}
    qualified: list[tuple[float, str]] = []
    for symbol in eligible:
        series = stocks[symbol]
        idx = series["by_date"][as_of_date]
        if idx < 60:
            continue
        row = _evaluate(series, idx, benchmark, benchmark_idx)
        row["symbol"] = symbol
        evaluated[symbol] = row
        if not row["failure_reasons"]:
            qualified.append((row["score"], symbol))
    qualified.sort(key=lambda item: (-item[0], item[1]))
    ranks = {symbol: rank for rank, (_, symbol) in enumerate(qualified, start=1)}

    symbol_results = []
    for symbol in core.symbols:
        if symbol not in evaluated:
            symbol_results.append(_blocked_symbol(symbol, next_date))
        else:
            symbol_results.append(_classify(evaluated[symbol], ranks.get(symbol), next_date))
    counts = Counter(row["decision"] for row in symbol_results)
    scan = {
        "schema_version": SCHEMA_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "universe_version": UNIVERSE_VERSION,
        "as_of_date": as_of_date,
        "valid_for_trade_date": next_date,
        "scan_status": "READY",
        "qualification_state": QUALIFICATION_STATE,
        "is_actual_trade": False,
        "global_blockers": [],
        "summary": {
            "core_count": 140,
            "eligible_count": len(eligible),
            "trade_count": counts["TRADE"],
            "watch_near_trigger_count": counts["WATCH_NEAR_TRIGGER"],
            "watch_capacity_count": counts["WATCH_CAPACITY"],
            "pass_count": counts["PASS"],
            "data_blocked_count": counts["DATA_BLOCKED"],
        },
        "symbols": symbol_results,
        "input_hashes": {
            "universe": sha256_file(universe_path),
            "bars": sha256_file(bars_path),
            "benchmark": sha256_file(benchmark_path),
            "calendar": sha256_file(calendar_path),
            "source_manifest": sha256_file(source_manifest_path),
        },
    }
    coverage = {
        "as_of_date": as_of_date,
        "minimum_coverage": MIN_COVERAGE,
        "eligible_count": len(eligible),
        "coverage_gate": "PASS",
        "calendar": {
            "latest_completed_trade_date": calendar.get("latest_completed_trade_date"),
            "next_trade_date": next_date,
        },
        "symbols": coverage_rows,
    }
    return scan, coverage


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def write_scan_outputs(
    scan: dict[str, Any],
    coverage: dict[str, Any],
    *,
    output_dir: str | Path,
    source_manifest_path: str | Path,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "scan.json", scan)
    _write_json(output / "coverage.json", coverage)
    _write_json(output / "source_manifest.json", _read_json(source_manifest_path))

    with (output / "scan.csv").open("w", encoding="utf-8", newline="") as handle:
        columns = [
            "symbol", "decision", "actionability_state", "qualified_rank", "score",
            *GATE_FIELDS, "failure_reasons", "signal_close", "atr14", "chase_limit",
            "valid_for_trade_date", "is_actual_trade",
        ]
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for item in scan["symbols"]:
            writer.writerow(
                {
                    "symbol": item["symbol"],
                    "decision": item["decision"],
                    "actionability_state": item["actionability_state"],
                    "qualified_rank": item["qualified_rank"] or "",
                    "score": "" if item["score"] is None else item["score"],
                    **item["gates"],
                    "failure_reasons": ",".join(item["failure_reasons"]),
                    "signal_close": "" if item["signal_close"] is None else item["signal_close"],
                    "atr14": "" if item["atr14"] is None else item["atr14"],
                    "chase_limit": "" if item["chase_limit"] is None else item["chase_limit"],
                    "valid_for_trade_date": item["valid_for_trade_date"] or "",
                    "is_actual_trade": "false",
                }
            )
    (output / "run_log.txt").write_text(
        "\n".join(
            [
                f"scanner={SCHEMA_VERSION}",
                f"strategy={STRATEGY_VERSION}",
                f"as_of_date={scan['as_of_date']}",
                f"scan_status={scan['scan_status']}",
                f"eligible_count={scan['summary']['eligible_count']}",
                f"trade_count={scan['summary']['trade_count']}",
            ]
        )
        + "\n",
        encoding="utf-8", newline="\n",
    )
    hash_targets = ["scan.json", "scan.csv", "coverage.json", "source_manifest.json", "run_log.txt"]
    hashes = {name: sha256_file(output / name) for name in hash_targets}
    _write_json(output / "result_hashes.json", hashes)
    return hashes
