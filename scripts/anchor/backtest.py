"""Idealized index-proxy simulations with explicit cash and next-close execution.

The index is not a tradable asset.  The only supported defensive proxy here is
zero-return cash; genuine ETF/bond simulations require separate verified data.
"""
from __future__ import annotations

from datetime import datetime
import math
import statistics
from .strategy import dca_states, rebalance_events


def xirr(cashflows):
    if not cashflows or not any(v < 0 for _, v in cashflows) or not any(v > 0 for _, v in cashflows):
        return None
    origin = datetime.strptime(cashflows[0][0], '%Y%m%d')
    flows = [((datetime.strptime(d, '%Y%m%d') - origin).days / 365, v) for d, v in cashflows]
    if max(t for t, _ in flows) == 0:
        return None
    def npv(rate):
        return sum(v / ((1 + rate) ** t) for t, v in flows)
    lo, hi = -.9999, 1.0
    while npv(lo) * npv(hi) > 0 and hi < 1000000:
        hi = hi * 2 + 1
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(150):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0: hi = mid
        else: lo = mid
    return (lo + hi) / 2


def run_backtest(rows, *, strategy, start, end, amount=1000.0, initial=10000.0, weight=.6, commission=0.0, slippage=0.0, upper=.15, lower=.15, rebalance_frequency='yearly', thresholds=None):
    modes = {'DCA_ALWAYS', 'DCA_ANCHOR', 'REBAL_CALENDAR', 'REBAL_ANCHOR'}
    parameters=(amount, initial, weight, commission, slippage, upper, lower)
    if any(not isinstance(value,(int,float)) or not math.isfinite(value) for value in parameters) or strategy not in modes or start > end or amount <= 0 or initial < 0 or not 0 < weight < 1 or not 0 <= commission < .1 or not 0 <= slippage < .1 or not 0 <= upper <= 2 or not 0 <= lower <= 1 or rebalance_frequency not in {'yearly','quarterly'}:
        raise ValueError('invalid backtest parameters')
    dates = [r['tradeDate'] for r in rows]
    if dates != sorted(set(dates)):
        raise ValueError('invalid calendar')
    selected = [r for r in rows if start <= r['tradeDate'] <= end]
    date_positions = {day: i for i, day in enumerate(dates)}
    if not selected or any(r.get('close') is None or r.get('quality') == 'BLOCKED' for r in selected):
        raise ValueError('数据缺失或质量阻断，无法完成回测')
    if strategy in {'DCA_ANCHOR','REBAL_ANCHOR'} and any(r.get('deviation') is None for r in selected):
        raise ValueError('五年均线历史不足，无法完成回测')
    states = dca_states(rows, upper, thresholds)
    state_by_date = {r['tradeDate']:r for r in states['states']}
    if strategy == 'DCA_ANCHOR' and any(state_by_date[r['tradeDate']]['state'] == 'BLOCKED_DATA' for r in selected):
        raise ValueError('历史状态回放被数据缺口阻断')
    if strategy == 'DCA_ANCHOR' and any(state_by_date[r['tradeDate']]['state'] == 'INSUFFICIENT_HISTORY' for r in selected):
        raise ValueError('策略阈值或均线预热历史不足')
    events = {e['tradeDate']:e for e in rebalance_events(rows, lower)}
    cash = shares = total_fees = total_slippage = invested = 0.0
    prev_value = nav = 0.0
    fills, valuations, cashflows, orders = [], [], [], []
    pending = None
    first_position = date_positions[selected[0]['tradeDate']]
    if first_position > 0:
        previous_day = dates[first_position - 1]
        if strategy == 'DCA_ANCHOR' and state_by_date[previous_day]['event'] == 'RELEASE_AND_RESUME':
            pending = (previous_day, 'RELEASE_AND_RESUME')
        elif strategy == 'REBAL_ANCHOR' and previous_day in events:
            pending = (previous_day, ','.join(events[previous_day]['reasonCodes']))
    # The schedule is based on the full exchange calendar, not the selected
    # backtest slice: starting mid-month must not create a new contribution.
    previous_month = dates[first_position - 1][:6] if first_position > 0 else None
    previous_period = None
    for i, row in enumerate(selected):
        day, price = row['tradeDate'], float(row['close'])
        if not math.isfinite(price) or price <= 0:
            raise ValueError('invalid index close')
        dca = strategy.startswith('DCA')
        month = day[:6]
        external = amount if dca and month != previous_month else (initial if not dca and i == 0 else 0)
        previous_month = month
        if external:
            cash += external; invested += external; cashflows.append((day, -external))
        def trade(side, gross_budget, reason, signal_date=None):
            nonlocal cash, shares, total_fees, total_slippage
            if gross_budget <= 1e-12: return
            if side == 'BUY':
                spent = min(cash, gross_budget)
                if spent <= 1e-12: return
                gross = spent / (1 + commission)
                fee = spent - gross
                fillprice = price * (1 + slippage)
                quantity = gross / fillprice
                cash -= spent; shares += quantity
            else:
                quantity = min(shares, gross_budget / (price * (1 - slippage)))
                fillprice = price * (1 - slippage)
                gross = quantity * fillprice
                fee = gross * commission
                cash += gross - fee; shares -= quantity
            total_fees += fee
            slip_cost=quantity*price*slippage
            total_slippage += slip_cost
            orders.append({'date':day,'signalDate':signal_date,'status':'FILLED','side':side,'reason':reason})
            fills.append({'date':day,'signalDate':signal_date,'side':side,'price':fillprice,'quantity':quantity,'gross':gross,'fee':fee,'slippageCost':slip_cost,'reason':reason})
        def rebalance(reason, signal_date=None):
            value = cash + shares * price
            current = shares * price
            if value <= 0: return
            if abs(current - weight * value) < 1e-9:
                orders.append({'date':day,'signalDate':signal_date,'status':'SIGNAL_NO_TRADE','reason':reason})
                return
            side = 'BUY' if current < weight * value else 'SELL'
            lo, hi = 0.0, cash if side == 'BUY' else current
            for _ in range(60):
                mid=(lo+hi)/2
                if side == 'BUY':
                    newcash=cash-mid; newshares=shares+mid/(1+commission)/(price*(1+slippage))
                else:
                    qty=min(shares,mid/(price*(1-slippage))); newshares=shares-qty; newcash=cash+qty*price*(1-slippage)*(1-commission)
                newweight=newshares*price/(newcash+newshares*price)
                if (newweight < weight) == (side == 'BUY'): lo=mid
                else: hi=mid
            trade(side,(lo+hi)/2,reason,signal_date)
        executed_pending = pending is not None
        if pending:
            signal_day, reason = pending
            if strategy == 'DCA_ANCHOR':
                before = len(fills)
                trade('BUY',cash,reason,signal_day)
                if len(fills) == before:
                    orders.append({'date':day,'signalDate':signal_day,'status':'SIGNAL_NO_TRADE','reason':'没有可投入现金'})
            elif strategy == 'REBAL_ANCHOR': rebalance(reason,signal_day)
            pending = None
        if dca and external:
            position = date_positions[day]
            prior_state = state_by_date[dates[position-1]]['state'] if position > 0 else 'NORMAL'
            if strategy == 'DCA_ALWAYS' or prior_state == 'NORMAL':
                trade('BUY', external, 'MONTHLY_CONTRIBUTION')
        if not dca:
            period = day[:4] if rebalance_frequency == 'yearly' else day[:4] + str((int(day[4:6])-1)//3)
            if i == 0 and not executed_pending: rebalance('INITIAL_ALLOCATION')
            elif strategy == 'REBAL_CALENDAR' and period != previous_period: rebalance('CALENDAR')
            previous_period = period
        value = cash + shares * price
        basis = prev_value + external
        if basis > 0: nav = (nav if nav else 1.0) * value / basis
        valuations.append({'tradeDate':day,'cash':cash,'shares':shares,'equityValue':shares*price,'totalValue':value,'externalFlow':external,'unitNav':nav,'equityWeight':shares*price/value if value else 0})
        prev_value=value
        if strategy == 'DCA_ANCHOR' and state_by_date[day]['event'] == 'RELEASE_AND_RESUME': pending=(day,'RELEASE_AND_RESUME')
        if strategy == 'REBAL_ANCHOR' and day in events: pending=(day,','.join(events[day]['reasonCodes']))
    if pending: orders.append({'date':selected[-1]['tradeDate'],'signalDate':pending[0],'status':'UNFILLED','reason':pending[1]})
    last=valuations[-1]
    flows = cashflows + [(last['tradeDate'], last['totalValue'])]
    peak=0; drawdown=0
    for point in valuations:
        peak=max(peak,point['unitNav'])
        point['drawdown'] = point['unitNav']/peak-1 if peak else 0
        if peak: drawdown=min(drawdown,point['drawdown'])
    returns = [valuations[i]['unitNav']/valuations[i-1]['unitNav']-1 for i in range(1,len(valuations)) if valuations[i-1]['unitNav'] > 0]
    elapsed=(datetime.strptime(selected[-1]['tradeDate'],'%Y%m%d')-datetime.strptime(cashflows[0][0],'%Y%m%d')).days if cashflows else 0
    annualized=(nav ** (365/elapsed)-1) if elapsed > 0 and nav > 0 else None
    pause_days = longest_pause = current_pause = 0
    pause_periods = []
    signal_events = []
    if strategy == 'DCA_ANCHOR':
        for row in selected:
            state = state_by_date[row['tradeDate']]
            if state['state'] == 'WAIT_RETURN_TO_MA':
                pause_days += 1; current_pause += 1; longest_pause = max(longest_pause, current_pause)
            else:
                if current_pause: pause_periods.append(current_pause)
                current_pause = 0
        if current_pause: pause_periods.append(current_pause)
        signal_events = [e for e in states['events'] if start <= e['tradeDate'] <= end]
    elif strategy == 'REBAL_ANCHOR':
        signal_events = [e for day,e in events.items() if start <= day <= end]
    return {'strategy':strategy,'assetMode':'theoretical_index','cashMode':'zero_return','execution':'next_trading_close','initialInvestment':invested,'finalValue':last['totalValue'],'profit':last['totalValue']-invested,'cash':cash,'cashWeight':cash/last['totalValue'] if last['totalValue'] else 0,'totalFees':total_fees,'totalSlippage':total_slippage,'twr':nav-1 if nav else None,'annualizedTwr':annualized,'annualizedVolatility':statistics.stdev(returns)*math.sqrt(242) if len(returns)>1 else None,'xirr':xirr(flows),'maxDrawdown':drawdown,'averageEquityWeight':sum(v['equityWeight'] for v in valuations)/len(valuations),'tradeCount':len(fills),'signalCount':len(signal_events),'signalEvents':signal_events,'pausedTradingDays':pause_days,'longestPauseTradingDays':longest_pause,'averagePauseTradingDays':sum(pause_periods)/len(pause_periods) if pause_periods else None,'pausePeriodsIncludeWindowBoundaries':True,'endingPaused':current_pause > 0,'fills':fills,'orders':orders,'dividends':[],'dividendNote':'全收益指数已包含股息再投资，理论回测不重复记入分红','valuations':valuations,'cashFlows':[{'date':d,'amount':-v} for d,v in cashflows], 'unfilled':bool(pending)}
