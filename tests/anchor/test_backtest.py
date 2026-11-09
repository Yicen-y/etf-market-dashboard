import pytest
from scripts.anchor.backtest import run_backtest, xirr


def rows():
    return [
        {'tradeDate':'20250102','close':100,'deviation':0.0,'rsi':40,'quality':'READY'},
        {'tradeDate':'20250203','close':110,'deviation':.16,'rsi':60,'quality':'READY'},
        {'tradeDate':'20250303','close':90,'deviation':.10,'rsi':55,'quality':'READY'},
        {'tradeDate':'20250401','close':80,'deviation':0.0,'rsi':50,'quality':'READY'},
        {'tradeDate':'20250402','close':100,'deviation':.01,'rsi':51,'quality':'READY'},
    ]


def test_xirr_known_one_year_cashflow():
    assert xirr([('20250101',-100),('20260101',110)]) == pytest.approx(.1)


def test_paused_contributions_released_only_on_next_day():
    out=run_backtest(rows(),strategy='DCA_ANCHOR',start='20250102',end='20250402',amount=100)
    fill=out['fills'][-1]
    assert fill['date']=='20250402' and fill['signalDate']=='20250401'
    assert fill['gross'] == pytest.approx(200)
    assert out['initialInvestment']==400
    assert out['cash']==pytest.approx(0)
    assert all(v['totalValue'] == pytest.approx(v['cash']+v['equityValue']) for v in out['valuations'])


def test_end_before_execution_keeps_cash_and_unfilled_order():
    out=run_backtest(rows(),strategy='DCA_ANCHOR',start='20250102',end='20250401',amount=100)
    assert out['cash']==pytest.approx(200)
    assert out['unfilled'] is True
    assert any(order['status']=='UNFILLED' for order in out['orders'])


def test_rebalance_next_day_and_cost_accounting():
    out=run_backtest(rows(),strategy='REBAL_ANCHOR',start='20250102',end='20250402',initial=1000,commission=.001)
    assert out['fills'][0]['reason']=='INITIAL_ALLOCATION'
    assert all(x['signalDate'] is None or x['date'] > x['signalDate'] for x in out['fills'])
    assert out['totalFees'] > 0
    assert len([order for order in out['orders'] if order['status']=='FILLED']) == len(out['fills'])
    assert all(v['cash'] >= -1e-9 and v['shares'] >= -1e-9 for v in out['valuations'])


def test_missing_data_blocks_simulation():
    data=rows(); data[1]['close']=None
    with pytest.raises(ValueError,match='数据缺失'):
        run_backtest(data,strategy='DCA_ALWAYS',start='20250102',end='20250402')


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1])
def test_invalid_contributions_are_rejected(value):
    with pytest.raises(ValueError,match='invalid backtest parameters'):
        run_backtest(rows(),strategy='DCA_ALWAYS',start='20250102',end='20250402',amount=value)


def test_first_day_executes_prior_day_signal():
    data=rows()
    data[-2]['tradeDate']='20250430'
    data[-1]['tradeDate']='20250501'
    out=run_backtest(data,strategy='DCA_ANCHOR',start='20250501',end='20250501',amount=100)
    assert out['fills'][0]['signalDate']=='20250430'
    assert out['fills'][0]['date']=='20250501'
    assert len(out['fills'])==1


def test_starting_midmonth_does_not_create_contribution():
    data=rows()
    data.insert(1, {'tradeDate':'20250115','close':105,'deviation':.05,'rsi':40,'quality':'READY'})
    out=run_backtest(data,strategy='DCA_ALWAYS',start='20250115',end='20250203',amount=100)
    assert out['cashFlows']==[{'date':'20250203','amount':100}]


def test_contributions_are_not_investment_return():
    data=rows()
    for row in data: row['close']=100
    out=run_backtest(data,strategy='DCA_ALWAYS',start='20250102',end='20250402',amount=100)
    assert out['initialInvestment']==400
    assert out['finalValue']==pytest.approx(400)
    assert out['twr']==pytest.approx(0)


def test_buy_costs_are_reflected_in_cash_and_marked_value():
    data=[{'tradeDate':'20250102','close':100.,'deviation':0.,'rsi':40.,'quality':'READY'}]
    out=run_backtest(data,strategy='DCA_ALWAYS',start='20250102',end='20250102',amount=100,commission=.01,slippage=.02)
    assert out['finalValue']+out['totalFees']+out['totalSlippage']==pytest.approx(100)
    assert out['fills'][0]['quantity']==pytest.approx(100/1.01/102)


def test_rebalance_signal_can_result_in_no_trade():
    data=[{'tradeDate':'20250102','close':100.,'deviation':.01,'rsi':56.,'quality':'READY'},
          {'tradeDate':'20250103','close':100.,'deviation':0.,'rsi':57.,'quality':'READY'},
          {'tradeDate':'20250106','close':100.,'deviation':0.,'rsi':57.,'quality':'READY'}]
    out=run_backtest(data,strategy='REBAL_ANCHOR',start='20250102',end='20250106',initial=1000,weight=.6)
    assert len(out['fills'])==1
    assert any(o['status']=='SIGNAL_NO_TRADE' and o['signalDate']=='20250103' for o in out['orders'])
