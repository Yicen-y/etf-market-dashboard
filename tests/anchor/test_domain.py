import pytest

from scripts.anchor.domain import indicators, compare_indexes


def test_ma_channel_and_deviation():
    rows = indicators(['1', '2', '3'], {'1': 1, '2': 2, '3': 3}, window=3, rsi_period=2)
    assert rows[1]['ma'] is None
    assert rows[2]['ma'] == 2
    assert rows[2]['upper'] == pytest.approx(2.3)
    assert rows[2]['lower'] == pytest.approx(1.7)
    assert rows[2]['deviation'] == pytest.approx(.5)
    assert rows[2]['rsi'] == 100


def test_gap_resets_warmup_and_no_fill():
    rows = indicators(['1', '2', '3', '4'], {'1': 2, '3': 2, '4': 2}, window=2, rsi_period=1)
    assert rows[1]['quality'] == 'BLOCKED'
    assert rows[2]['ma'] is None
    assert rows[2]['quality'] == 'BLOCKED'
    assert rows[3]['ma'] == 2
    assert rows[3]['rsi'] == 50


def test_reject_nonpositive_and_nonfinite():
    for price in (0, -1, float('nan'), True):
        with pytest.raises(ValueError):
            indicators(['1'], {'1': price})


def test_1250_day_warmup_and_rsi_boundaries():
    days = [f'{i:04}' for i in range(1251)]
    rows = indicators(days, {d: float(i + 1) for i, d in enumerate(days)})
    assert rows[1248]['ma'] is None
    assert rows[1249]['ma'] == pytest.approx(625.5)
    assert rows[90]['rsi'] == 100
    falling = indicators(days, {d: float(1251-i) for i, d in enumerate(days)})
    assert falling[90]['rsi'] == 0


def test_comparison_uses_common_prior_base_and_preserves_missing_values():
    left = [{'tradeDate':'20260102','close':100,'deviation':.1}, {'tradeDate':'20260105','close':110,'deviation':.2}]
    right = [{'tradeDate':'20260102','close':200,'deviation':.3}, {'tradeDate':'20260105','close':None,'deviation':None}]
    result = compare_indexes({'H20903':left,'H00922':right}, '20260104')
    assert result['baseDate'] == '20260102'
    assert result['rows'][0]['deviationSpread'] == pytest.approx(.2)
    assert result['rows'][1]['normalized']['H00922'] is None


def test_future_prices_do_not_change_past_indicators():
    days=[f'{i:04}' for i in range(120)]
    values={day:100+i for i,day in enumerate(days)}
    before=indicators(days,values,window=20,rsi_period=14)
    for day in days[80:]: values[day] *= 2
    after=indicators(days,values,window=20,rsi_period=14)
    assert before[:80] == after[:80]


def test_wilder_rsi_against_independent_reference():
    days=[f'{i:04}' for i in range(120)]
    values=[100 + i*.2 + (i%5-2)*1.1 for i in range(120)]
    computed=indicators(days,dict(zip(days,values)),window=20,rsi_period=14)
    deltas=[values[i]-values[i-1] for i in range(1,len(values))]
    gains=sum(max(x,0) for x in deltas[:14])/14
    losses=sum(max(-x,0) for x in deltas[:14])/14
    for delta in deltas[14:]:
        gains=(gains*13+max(delta,0))/14
        losses=(losses*13+max(-delta,0))/14
    assert computed[-1]['rsi']==pytest.approx(100-100/(1+gains/losses))
