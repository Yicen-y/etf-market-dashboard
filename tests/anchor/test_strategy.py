from scripts.anchor.strategy import dca_states, rebalance_events


def make(values):
    return [{'tradeDate':str(i), 'deviation':v, 'rsi':r, 'quality':'READY'} for i,(v,r) in enumerate(values)]


def test_pause_hysteresis_resume_and_exact_thresholds():
    rows = make([(0.15,40),(.16,40),(.1,40),(0,40)])
    result = dca_states(rows)
    assert [r['state'] for r in result['states']] == ['NORMAL','WAIT_RETURN_TO_MA','WAIT_RETURN_TO_MA','NORMAL']
    assert [r['event'] for r in result['events']] == ['PAUSE_DCA','RELEASE_AND_RESUME']
    assert all(e['execution'] == 'NEXT_TRADING_DAY_OR_LATER' for e in result['events'])


def test_initial_pause_and_blocked_state_preserved():
    rows = make([(.2,40),(.1,40),(0,40)])
    rows[1]['quality'] = 'BLOCKED'
    result = dca_states(rows)
    assert result['events'][0]['event'] == 'INITIAL_PAUSED'
    assert result['states'][2]['state'] == 'BLOCKED_DATA'
    assert result['states'][2]['underlyingState'] == 'WAIT_RETURN_TO_MA'
    assert len(result['events']) == 1


def test_rebalance_deduplicates_simultaneous_crossings():
    rows = make([(.01,56),(-.16,71),(-.17,72)])
    events = rebalance_events(rows)
    assert len(events) == 1
    assert set(events[0]['reasonCodes']) == {'MA_DOWN_CROSS','LOWER_DOWN_CROSS','RSI57_UP_CROSS','RSI70_UP_CROSS'}
