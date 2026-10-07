"""Cross-file research invariants, in addition to byte-level evidence binding."""
import math

from .bundle import iso_day


RUN_ARTIFACTS = {'run.json', 'scan.json', 'coverage.json', 'candidates.json',
                 'lifecycle.json', 'events.json', 'history_bindings.json',
                 'daily_plan.json', 'report.md', 'report.html'}
TERMINAL = {'PASS_TERMINAL', 'INVALIDATED', 'TARGET_HIT'}


def validate_state(run, candidates, states, events, scan):
    day = iso_day(run['as_of_date'])
    if run.get('format') != 'hksc-public-run/2' or run.get('is_actual_trade') is not False:
        raise ValueError('Unsupported public research run; prototype runs require a new research start')
    if scan['as_of_date'] != day or scan['strategy_version'] != run['strategy_version']:
        raise ValueError('Run and scanner date or strategy mismatch')
    calendar = run['bound_calendar']
    if calendar != sorted(set(calendar)) or day not in calendar:
        raise ValueError('Run calendar contract mismatch')
    if run['completed_calendar'] != [d for d in calendar if d <= day]:
        raise ValueError('Completed run calendar mismatch')
    by_candidate = {c['candidate_id']: c for c in candidates}
    by_state = {s['candidate_id']: s for s in states}
    if len(by_candidate) != len(candidates) or len(by_state) != len(states) or by_candidate.keys() != by_state.keys():
        raise ValueError('Candidate/state IDs must be unique and correspond exactly')
    global_events = {e['event_id']: e for e in events}
    if len(global_events) != len(events):
        raise ValueError('Duplicate global event ID')
    state_events = {}
    for identifier, candidate in by_candidate.items():
        signal, entry_day = iso_day(candidate['signal_date']), iso_day(candidate['valid_for_trade_date'])
        if signal not in calendar or entry_day not in calendar or signal > day:
            raise ValueError('Candidate signal or entry is outside bound calendar')
        if calendar.index(entry_day) != calendar.index(signal) + 1:
            raise ValueError('Candidate entry must be the next bound trading day')
        if candidate.get('is_actual_trade') is not False or candidate.get('frozen_decision') != 'TRADE':
            raise ValueError('Candidate must be research-only')
        state = by_state[identifier]
        if state['symbol'] != candidate['symbol'] or state.get('is_actual_trade') is not False:
            raise ValueError('Candidate/state symbol or mode mismatch')
        entry_events, exit_events = [], []
        for event in state['events']:
            observed = iso_day(event['observed_trade_date'])
            if event['candidate_id'] != identifier or event.get('is_actual_trade') is not False:
                raise ValueError('Lifecycle event candidate or mode mismatch')
            if observed not in calendar or not entry_day <= observed <= day:
                raise ValueError('Lifecycle event date outside candidate observation window')
            if event['event_id'] in state_events:
                raise ValueError('Duplicate lifecycle event ID')
            state_events[event['event_id']] = event
            if event['event_type'] == 'SIMULATED_ENTRY':
                entry_events.append(event)
                if observed != entry_day:
                    raise ValueError('Entry event does not match frozen next-open date')
                for field in ('entry_price', 'initial_stop', 'target'):
                    value = event[field]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                        raise ValueError('Invalid simulated entry number')
                    if state[field] != value:
                        raise ValueError('Entry event and lifecycle prices disagree')
                if not event['initial_stop'] < event['entry_price'] < event['target']:
                    raise ValueError('Entry risk and target contract mismatch')
            elif event['event_type'] == 'SIMULATED_EXIT':
                exit_events.append(event)
                value = event['exit_price']
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise ValueError('Invalid simulated exit price')
                if state['exit_price'] != event['exit_price'] or state['exit_reason'] != event['reason']:
                    raise ValueError('Exit event and lifecycle disagree')
        if len(entry_events) > 1 or len(exit_events) > 1 or (exit_events and not entry_events):
            raise ValueError('Inconsistent simulated event sequence')
        if exit_events and exit_events[0]['observed_trade_date'] < entry_events[0]['observed_trade_date']:
            raise ValueError('Exit precedes entry')
    if state_events != global_events:
        raise ValueError('Global events and lifecycle events disagree')
    active = sum(s['lifecycle_status'] not in TERMINAL for s in states)
    if active != run['open_candidate_count'] or active > 3:
        raise ValueError('Open-candidate capacity or count mismatch')
