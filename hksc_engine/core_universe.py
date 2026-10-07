from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .public_paths import resolve_source_path, sha256_file


@dataclass(frozen=True)
class CoreUniverse:
    version: str
    status: str
    symbols: tuple[str, ...]
    effective_from: str
    next_scheduled_refresh: str
    source_csv: Path
    source_sha256: str


def symbols_sha256(symbols: tuple[str, ...] | list[str]) -> str:
    payload = ("\n".join(symbols) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def derive_core_symbols(source_csv: str | Path, turnover_min_hkd: float) -> tuple[str, ...]:
    source = Path(source_csv)
    symbols: list[str] = []
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("eligible_phase0", "").strip().lower() != "true":
                continue
            required = {
                "normalized_security_type": "ORDINARY",
                "exchange_board": "MAIN",
                "trading_currency": "HKD",
                "trading_status": "NORMAL",
            }
            if any(row.get(field, "").strip() != value for field, value in required.items()):
                continue
            if row.get("liquidity_verified", "").strip().lower() != "true":
                continue
            try:
                turnover = float(row["turnover_20d_median_hkd"])
            except (KeyError, TypeError, ValueError):
                continue
            if turnover >= turnover_min_hkd:
                symbols.append(row["security_code"].strip())

    unique = tuple(dict.fromkeys(symbols))
    if len(unique) != len(symbols):
        raise ValueError("core universe source contains duplicate eligible symbols")
    return tuple(sorted(unique))


def load_core_universe(manifest_path: str | Path) -> CoreUniverse:
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("artifact_type") != "HK_CORE_TRADABLE_UNIVERSE":
        raise ValueError("unexpected core universe artifact_type")
    if manifest.get("production_trading_pool") is not False:
        raise ValueError("core universe must remain non-production")

    source_csv = resolve_source_path(manifest_file, manifest["source"]["data_path"])
    declared_source_sha = str(manifest["source"]["sha256"]).lower()
    actual_source_sha = sha256_file(source_csv).lower()
    if actual_source_sha != declared_source_sha:
        raise ValueError(
            f"core universe source hash mismatch: {actual_source_sha} != {declared_source_sha}"
        )

    declared_symbols = tuple(str(value) for value in manifest["symbols"])
    expected_count = int(manifest["expected_count"])
    if len(declared_symbols) != expected_count:
        raise ValueError("core universe declared count mismatch")
    if len(set(declared_symbols)) != len(declared_symbols):
        raise ValueError("core universe manifest contains duplicate symbols")
    if tuple(sorted(declared_symbols)) != declared_symbols:
        raise ValueError("core universe symbols must be sorted")
    if symbols_sha256(declared_symbols) != str(manifest["symbols_sha256"]).lower():
        raise ValueError("core universe symbol hash mismatch")

    turnover_min = float(manifest["rules"]["turnover_20d_median_hkd_min"])
    derived_symbols = derive_core_symbols(source_csv, turnover_min)
    if derived_symbols != declared_symbols:
        raise ValueError("core universe does not match deterministic source derivation")

    return CoreUniverse(
        version=str(manifest["version"]),
        status=str(manifest["status"]),
        symbols=declared_symbols,
        effective_from=str(manifest["effective_from"]),
        next_scheduled_refresh=str(manifest["refresh_policy"]["next_scheduled_refresh"]),
        source_csv=source_csv,
        source_sha256=declared_source_sha,
    )
