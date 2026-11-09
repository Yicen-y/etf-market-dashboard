"""Point-in-time state transitions; no orders execute on a signal date."""
from __future__ import annotations


def dca_states(rows, upper_pct=0.15, thresholds=None):
    """Replay from the start of the input so a later backtest inherits its state.

    A missing observation locks the replay until source data are repaired and
    the complete series is replayed. Warm-up before the first signal is not a
    data failure.
    """
    state = 'NORMAL'
    started = blocked = False
    events = []
    output = []
    if thresholds is not None and len(thresholds) != len(rows):
        raise ValueError('thresholds must match the trading calendar')
    for i, row in enumerate(rows):
        day, value = row['tradeDate'], row.get('deviation')
        threshold = upper_pct if thresholds is None else thresholds[i]
        old = state
        event = None
        if row.get('quality') == 'BLOCKED':
            blocked = True
        if blocked:
            display = 'BLOCKED_DATA'
        elif value is None or threshold is None:
            display = 'INSUFFICIENT_HISTORY'
        else:
            display = state
            if not started:
                started = True
                if value > threshold:
                    state, event = 'WAIT_RETURN_TO_MA', 'INITIAL_PAUSED'
            elif state == 'NORMAL' and value > threshold:
                state, event = 'WAIT_RETURN_TO_MA', 'PAUSE_DCA'
            elif state == 'WAIT_RETURN_TO_MA' and value <= 0:
                state, event = 'NORMAL', 'RELEASE_AND_RESUME'
            display = state
            if event:
                events.append({'tradeDate': day, 'event': event, 'fromState': old, 'toState': state, 'execution': 'NEXT_TRADING_DAY_OR_LATER'})
        output.append({'tradeDate': day, 'state': display, 'event': event, 'underlyingState': state})
    return {'states': output, 'events': events}


def rebalance_events(rows, lower_pct=0.15):
    events = []
    previous = None
    for row in rows:
        if row.get('quality') == 'BLOCKED' or row.get('deviation') is None:
            previous = None
            continue
        reasons = []
        if previous is not None:
            p, q = previous.get('deviation'), row['deviation']
            if p > 0 and q <= 0:
                reasons.append('MA_DOWN_CROSS')
            if p > -lower_pct and q <= -lower_pct:
                reasons.append('LOWER_DOWN_CROSS')
            a, b = previous.get('rsi'), row.get('rsi')
            if a is not None and b is not None:
                if a < 57 <= b: reasons.append('RSI57_UP_CROSS')
                if a < 70 <= b: reasons.append('RSI70_UP_CROSS')
        if reasons:
            events.append({'tradeDate': row['tradeDate'], 'reasonCodes': reasons, 'execution': 'NEXT_TRADING_DAY_OR_LATER'})
        previous = row
    return events
