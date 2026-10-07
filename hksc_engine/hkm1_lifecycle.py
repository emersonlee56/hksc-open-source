"""Mechanical simulated lifecycle for frozen HK-M1 TRADE candidates."""

from __future__ import annotations

import hashlib
import math
from typing import Any


def _event(candidate_id: str, event_type: str, date: str, **facts: Any) -> dict[str, Any]:
    payload = f"{candidate_id}|{event_type}|{date}|{sorted(facts.items())}"
    return {
        "event_id": "EVT-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20],
        "candidate_id": candidate_id,
        "event_type": event_type,
        "observed_trade_date": date,
        **facts,
        "is_actual_trade": False,
    }


def _state(
    candidate: dict[str, Any],
    *,
    lifecycle_status: str,
    actionability_state: str,
    events: list[dict[str, Any]],
    entry_price: float | None = None,
    initial_stop: float | None = None,
    target: float | None = None,
    exit_reason: str | None = None,
    exit_price: float | None = None,
    next_action_trade_date: str | None = None,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "symbol": candidate["symbol"],
        "frozen_decision": "TRADE",
        "lifecycle_status": lifecycle_status,
        "actionability_state": actionability_state,
        "entry_price": entry_price,
        "initial_stop": initial_stop,
        "target": target,
        "exit_reason": exit_reason,
        "exit_price": exit_price,
        "next_action_trade_date": next_action_trade_date,
        "events": events,
        "is_actual_trade": False,
    }


def replay_candidate_lifecycle(
    candidate: dict[str, Any],
    series: dict[str, list[Any]],
    trading_dates: list[str],
    through_date: str,
    prior_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay one candidate using only completed bars through ``through_date``.

    The caller supplies the authoritative HKEX trading calendar. The function is
    pure and returns deterministic events; persistence remains append-only at the
    application boundary.
    """
    if candidate.get("frozen_decision") != "TRADE" or candidate.get("is_actual_trade") is not False:
        raise ValueError("lifecycle accepts research-only TRADE candidates")
    calendar = sorted(dict.fromkeys(trading_dates))
    if through_date not in calendar:
        raise ValueError("through_date must be an HKEX trading date")
    entry_date = candidate["valid_for_trade_date"]
    signal_date = candidate["signal_date"]
    if entry_date not in calendar:
        raise ValueError("valid_for_trade_date missing from calendar")
    if through_date < entry_date:
        return _state(
            candidate,
            lifecycle_status="ACTIONABLE_SETUP_TRIGGERED",
            actionability_state="ENTER_IF",
            events=[],
            next_action_trade_date=entry_date,
        )

    by_date = series.get("by_date") or {
        date: idx for idx, date in enumerate(series.get("dates", []))
    }
    entry_idx = by_date.get(entry_date)

    seeded_entry = False
    if prior_state is not None:
        if prior_state.get("candidate_id") != candidate["candidate_id"]:
            raise ValueError("prior lifecycle state candidate mismatch")
        if prior_state.get("is_actual_trade") is not False:
            raise ValueError("prior lifecycle state must be research-only")
        if prior_state.get("actionability_state") in {"NO_ACTION", "DATA_BLOCKED"}:
            return prior_state
        prior_events = list(prior_state.get("events", []))
        seeded_entry = (
            prior_state.get("entry_price") is not None
            and prior_state.get("initial_stop") is not None
            and prior_state.get("target") is not None
            and any(row.get("event_type") == "SIMULATED_ENTRY" for row in prior_events)
        )
        if seeded_entry:
            entry_price = float(prior_state["entry_price"])
            initial_stop = float(prior_state["initial_stop"])
            target = float(prior_state["target"])
            events = prior_events

    signal_idx = by_date.get(signal_date)
    frozen_stop_floor = candidate.get("signal_lowest_low10")
    signal_history_available = signal_idx is not None and signal_idx >= 9
    if not seeded_entry and (
        (not signal_history_available and frozen_stop_floor is None)
        or entry_idx is None
    ):
        event = _event(candidate["candidate_id"], "DATA_BLOCKED", entry_date, reason="ENTRY_OR_SIGNAL_BAR_MISSING")
        return _state(
            candidate,
            lifecycle_status="DATA_BLOCKED",
            actionability_state="DATA_BLOCKED",
            events=[event],
            exit_reason="ENTRY_OR_SIGNAL_BAR_MISSING",
        )

    if not seeded_entry:
        entry_price = series["open"][entry_idx]
    if not seeded_entry and entry_price > candidate["chase_limit"]:
        event = _event(candidate["candidate_id"], "SKIPPED_CHASE", entry_date, entry_price=entry_price)
        return _state(
            candidate,
            lifecycle_status="PASS_TERMINAL",
            actionability_state="NO_ACTION",
            events=[event],
            entry_price=entry_price,
            exit_reason="SKIPPED_CHASE",
        )

    if not seeded_entry:
        lowest_low10 = (
            float(frozen_stop_floor)
            if frozen_stop_floor is not None
            else min(series["low"][signal_idx - 9 : signal_idx + 1])
        )
        initial_stop = max(lowest_low10, entry_price - 2.0 * candidate["atr14"])
    if not seeded_entry and initial_stop >= entry_price:
        event = _event(candidate["candidate_id"], "INVALID_STOP", entry_date, entry_price=entry_price, initial_stop=initial_stop)
        return _state(
            candidate,
            lifecycle_status="PASS_TERMINAL",
            actionability_state="NO_ACTION",
            events=[event],
            entry_price=entry_price,
            initial_stop=initial_stop,
            exit_reason="INVALID_STOP",
        )

    if not seeded_entry:
        target = entry_price + 3.0 * (entry_price - initial_stop)
        events = [
            _event(
                candidate["candidate_id"],
                "SIMULATED_ENTRY",
                entry_date,
                entry_price=entry_price,
                initial_stop=initial_stop,
                target=target,
            )
        ]
    entry_calendar_idx = calendar.index(entry_date)
    through_calendar_idx = calendar.index(through_date)
    queued_exit: tuple[str, str] | None = None

    for calendar_idx in range(entry_calendar_idx, through_calendar_idx + 1):
        date = calendar[calendar_idx]
        idx = by_date.get(date)
        if idx is None:
            event = _event(candidate["candidate_id"], "DATA_BLOCKED", date, reason="HOLDING_BAR_MISSING")
            events.append(event)
            return _state(
                candidate,
                lifecycle_status="DATA_BLOCKED",
                actionability_state="DATA_BLOCKED",
                events=events,
                entry_price=entry_price,
                initial_stop=initial_stop,
                target=target,
                exit_reason="HOLDING_BAR_MISSING",
            )

        if queued_exit is not None:
            reason, queued_for = queued_exit
            if date == queued_for:
                exit_price = series["open"][idx]
                events.append(_event(candidate["candidate_id"], "SIMULATED_EXIT", date, reason=reason, exit_price=exit_price))
                return _state(
                    candidate,
                    lifecycle_status="INVALIDATED",
                    actionability_state="EXIT" if date == through_date else "NO_ACTION",
                    events=events,
                    entry_price=entry_price,
                    initial_stop=initial_stop,
                    target=target,
                    exit_reason=reason,
                    exit_price=exit_price,
                )

        open_price = series["open"][idx]
        low = series["low"][idx]
        high = series["high"][idx]
        if open_price <= initial_stop:
            exit_price, reason = open_price, "STOP_GAP"
        elif low <= initial_stop:
            exit_price, reason = initial_stop, "STOP"
        elif high >= target:
            exit_price, reason = target, "TARGET"
        else:
            exit_price = None
            reason = None
        if reason is not None:
            status = "TARGET_HIT" if reason == "TARGET" else "INVALIDATED"
            events.append(_event(candidate["candidate_id"], "SIMULATED_EXIT", date, reason=reason, exit_price=exit_price))
            return _state(
                candidate,
                lifecycle_status=status,
                actionability_state="EXIT" if date == through_date else "NO_ACTION",
                events=events,
                entry_price=entry_price,
                initial_stop=initial_stop,
                target=target,
                exit_reason=reason,
                exit_price=exit_price,
            )

        next_date = calendar[calendar_idx + 1] if calendar_idx + 1 < len(calendar) else None
        if idx >= 19:
            sma20 = sum(series["close"][idx - 19 : idx + 1]) / 20.0
            if series["close"][idx] < sma20:
                if next_date is None:
                    return _state(
                        candidate,
                        lifecycle_status="HOLDING_RESEARCH_STATE",
                        actionability_state="DATA_BLOCKED",
                        events=events,
                        entry_price=entry_price,
                        initial_stop=initial_stop,
                        target=target,
                        exit_reason="TREND_EXIT_NEXT_OPEN_DATE_UNKNOWN",
                    )
                queued_exit = ("TREND", next_date)
        if queued_exit is None and calendar_idx - entry_calendar_idx >= 60:
            if next_date is None:
                return _state(
                    candidate,
                    lifecycle_status="HOLDING_RESEARCH_STATE",
                    actionability_state="DATA_BLOCKED",
                    events=events,
                    entry_price=entry_price,
                    initial_stop=initial_stop,
                    target=target,
                    exit_reason="TIME_EXIT_NEXT_OPEN_DATE_UNKNOWN",
                )
            queued_exit = ("TIME_60D", next_date)

    if queued_exit is not None:
        return _state(
            candidate,
            lifecycle_status="HOLDING_RESEARCH_STATE",
            actionability_state="EXIT",
            events=events,
            entry_price=entry_price,
            initial_stop=initial_stop,
            target=target,
            exit_reason=queued_exit[0],
            next_action_trade_date=queued_exit[1],
        )
    return _state(
        candidate,
        lifecycle_status="HOLDING_RESEARCH_STATE",
        actionability_state="HOLD",
        events=events,
        entry_price=entry_price,
        initial_stop=initial_stop,
        target=target,
    )


def evaluate_candidate_open(
    candidate: dict[str, Any],
    series: dict[str, list[Any]],
    observation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate only the frozen next-open gate without using intraday facts."""
    if candidate.get("frozen_decision") != "TRADE" or candidate.get("is_actual_trade") is not False:
        raise ValueError("open evaluation accepts research-only TRADE candidates")
    entry_date = candidate["valid_for_trade_date"]
    if observation is None:
        event = _event(candidate["candidate_id"], "DATA_BLOCKED", entry_date, reason="OPEN_EVIDENCE_MISSING")
        return _state(
            candidate,
            lifecycle_status="DATA_BLOCKED",
            actionability_state="DATA_BLOCKED",
            events=[event],
            exit_reason="OPEN_EVIDENCE_MISSING",
        )
    if observation.get("symbol") != candidate["symbol"] or observation.get("trade_date") != entry_date:
        raise ValueError("open observation symbol or trade_date mismatch")
    if observation.get("trading_status") != "NORMAL":
        event = _event(candidate["candidate_id"], "DATA_BLOCKED", entry_date, reason="OPEN_NOT_NORMAL")
        return _state(
            candidate,
            lifecycle_status="DATA_BLOCKED",
            actionability_state="DATA_BLOCKED",
            events=[event],
            exit_reason="OPEN_NOT_NORMAL",
        )
    try:
        entry_price = float(observation["open_price"])
    except (KeyError, TypeError, ValueError):
        entry_price = math.nan
    if not math.isfinite(entry_price) or entry_price <= 0:
        event = _event(candidate["candidate_id"], "DATA_BLOCKED", entry_date, reason="OPEN_PRICE_INVALID")
        return _state(
            candidate,
            lifecycle_status="DATA_BLOCKED",
            actionability_state="DATA_BLOCKED",
            events=[event],
            exit_reason="OPEN_PRICE_INVALID",
        )

    by_date = series.get("by_date") or {
        date: idx for idx, date in enumerate(series.get("dates", []))
    }
    signal_idx = by_date.get(candidate["signal_date"])
    if signal_idx is None or signal_idx < 9:
        event = _event(candidate["candidate_id"], "DATA_BLOCKED", entry_date, reason="SIGNAL_HISTORY_MISSING")
        return _state(
            candidate,
            lifecycle_status="DATA_BLOCKED",
            actionability_state="DATA_BLOCKED",
            events=[event],
            exit_reason="SIGNAL_HISTORY_MISSING",
        )
    if entry_price > candidate["chase_limit"]:
        event = _event(candidate["candidate_id"], "SKIPPED_CHASE", entry_date, entry_price=entry_price)
        return _state(
            candidate,
            lifecycle_status="PASS_TERMINAL",
            actionability_state="NO_ACTION",
            events=[event],
            entry_price=entry_price,
            exit_reason="SKIPPED_CHASE",
        )

    lowest_low10 = min(series["low"][signal_idx - 9 : signal_idx + 1])
    initial_stop = max(lowest_low10, entry_price - 2.0 * candidate["atr14"])
    if initial_stop >= entry_price:
        event = _event(candidate["candidate_id"], "INVALID_STOP", entry_date, entry_price=entry_price, initial_stop=initial_stop)
        return _state(
            candidate,
            lifecycle_status="PASS_TERMINAL",
            actionability_state="NO_ACTION",
            events=[event],
            entry_price=entry_price,
            initial_stop=initial_stop,
            exit_reason="INVALID_STOP",
        )

    target = entry_price + 3.0 * (entry_price - initial_stop)
    event = _event(
        candidate["candidate_id"],
        "SIMULATED_ENTRY",
        entry_date,
        entry_price=entry_price,
        initial_stop=initial_stop,
        target=target,
    )
    return _state(
        candidate,
        lifecycle_status="HOLDING_RESEARCH_STATE",
        actionability_state="HOLD",
        events=[event],
        entry_price=entry_price,
        initial_stop=initial_stop,
        target=target,
    )
