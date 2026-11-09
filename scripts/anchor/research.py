"""Research helpers: training-only selection and lagged empirical quantiles."""
import math
from bisect import bisect_left, insort

from .backtest import run_backtest


def lagged_quantiles(values, length=756, quantile=.8):
    if length < 1 or not 0 <= quantile <= 1:
        raise ValueError('invalid quantile parameters')
    output = []
    ordered = []
    missing = 0
    for i in range(len(values)):
        if i:
            value = values[i-1]
            if value is None:
                missing += 1
            else:
                insort(ordered, value)
        if i > length:
            value = values[i-length-1]
            if value is None:
                missing -= 1
            else:
                ordered.pop(bisect_left(ordered, value))
        if i < length or missing:
            output.append(None)
            continue
        rank=(length-1)*quantile
        lo=math.floor(rank); hi=math.ceil(rank)
        output.append(ordered[lo]+(ordered[hi]-ordered[lo])*(rank-lo))
    return output


def walk_forward(rows, thresholds, train_days, test_days, start, end, **kwargs):
    if not thresholds or train_days < 1 or test_days < 1:
        raise ValueError('invalid research parameters')
    eligible=[r for r in rows if start <= r['tradeDate'] <= end and r.get('deviation') is not None]
    folds=[]
    position=train_days
    while position < len(eligible):
        train=eligible[position-train_days:position]
        test=eligible[position:min(position+test_days,len(eligible))]
        results=[]
        for threshold in thresholds:
            train_result=run_backtest(rows,strategy='DCA_ANCHOR',start=train[0]['tradeDate'],end=train[-1]['tradeDate'],upper=threshold,**kwargs)
            if train_result['twr'] is None:
                raise ValueError('训练区间没有外部投入，无法比较阈值')
            results.append((train_result['twr'],threshold))
        best=sorted(results,key=lambda item:(-item[0],item[1]))[0][1]
        test_result=run_backtest(rows,strategy='DCA_ANCHOR',start=test[0]['tradeDate'],end=test[-1]['tradeDate'],upper=best,**kwargs)
        benchmark=run_backtest(rows,strategy='DCA_ALWAYS',start=test[0]['tradeDate'],end=test[-1]['tradeDate'],**kwargs)
        excess=None if test_result['twr'] is None or benchmark['twr'] is None else test_result['twr']-benchmark['twr']
        folds.append({'trainStart':train[0]['tradeDate'],'trainEnd':train[-1]['tradeDate'],'testStart':test[0]['tradeDate'],'testEnd':test[-1]['tradeDate'],'chosenThreshold':best,'trainScores':[{'threshold':t,'twr':s} for s,t in results],'testTwr':test_result['twr'],'benchmarkTwr':benchmark['twr'],'excessTwr':excess,'testTrades':test_result['tradeCount']})
        position += test_days
    return folds
