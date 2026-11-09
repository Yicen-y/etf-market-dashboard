import pytest
from scripts.anchor.research import lagged_quantiles, walk_forward
from scripts.anchor.strategy import dca_states


def test_quantile_uses_only_previous_values_and_requires_complete_history():
    values=[1.,2.,3.,100.,None,5.]
    result=lagged_quantiles(values, length=3, quantile=.5)
    assert result[:3] == [None,None,None]
    assert result[3] == 2
    assert result[5] is None
    changed=lagged_quantiles([1.,2.,3.,-100.,None,5.],length=3,quantile=.5)
    assert changed[3] == result[3]


def test_walk_forward_train_ends_before_test_and_folds_do_not_overlap():
    rows=[{'tradeDate':f'2025{m:02}01','close':100+m,'deviation':.02*m,'rsi':50,'quality':'READY'} for m in range(1,13)]
    folds=walk_forward(rows,[.1,.2],train_days=4,test_days=3,start='20250101',end='20251201',amount=100)
    assert len(folds)==3
    assert all(f['trainEnd'] < f['testStart'] <= f['testEnd'] for f in folds)
    assert all(folds[i]['testEnd'] < folds[i+1]['testStart'] for i in range(len(folds)-1))
    assert all(f['chosenThreshold'] in (.1,.2) for f in folds)


def test_dynamic_threshold_uses_supplied_lagged_series():
    rows=[{'tradeDate':str(i),'deviation':d,'quality':'READY'} for i,d in enumerate([.1,.2,.1,0])]
    result=dca_states(rows, thresholds=[None,.15,.15,.15])
    assert result['states'][0]['state']=='INSUFFICIENT_HISTORY'
    assert [e['event'] for e in result['events']]==['INITIAL_PAUSED','RELEASE_AND_RESUME']
