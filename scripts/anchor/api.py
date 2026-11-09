"""Read-only five-year-anchor indicators from the published index snapshot."""
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from scripts.config import ROOT
from scripts.anchor.domain import indicators, compare_indexes
from scripts.anchor.strategy import dca_states, rebalance_events
from scripts.anchor.backtest import run_backtest
from scripts.anchor.research import lagged_quantiles, walk_forward
from scripts.config import DATABASE_PATH
from scripts.storage import read_nikkei_anchor_records

router = APIRouter(prefix='/api/anchor', tags=['anchor'])
NAMES = {'H20903': '中证A股全收益指数', 'H00922': '中证红利全收益指数'}
NIKKEI_CODE = 'NKY225_TEMP'


def get_nikkei_metrics(window, upper, lower):
    """Return the locally stored Nikkei 225 index-point series.

    The observations are treated as price-index points, not a total-return
    index. The original Wind name lookup did not provide a verified Wind code.
    """
    try:
        records = read_nikkei_anchor_records(DATABASE_PATH)
        observations = {row['tradeDate']: float(row['close']) for row in records}
        calendar = sorted(observations)
        rows = indicators(calendar, observations, window, upper, lower)
    except (OSError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f'日经临时数据不可用：{exc}') from exc
    if not records:
        raise HTTPException(status_code=503, detail='数据库尚无日经基准数据；请先刷新数据。')
    anomalies = []
    previous = None
    for row in rows:
        value = row['close']
        if previous is not None and value is not None and abs(value / previous - 1) > .10:
            anomalies.append({'tradeDate': row['tradeDate'], 'dailyChange': value / previous - 1,
                              'status': 'WARNING', 'reason': '单日变动超过10%，需要核验'})
        previous = value
    modified = records[-1]['updatedAt']
    item = {'name': '日经225指数点位（Wind临时数据）', 'return_type': 'price_index',
            'provenance': 'WIND_MCP_NAME_LOOKUP_UNVERIFIED_CODE', 'missing_dates': [],
            'blocked_dates': [], 'open_quality_issues': [], 'anomalies': anomalies,
            'rows': rows, 'dca': [], 'rebalanceEvents': []}
    return {'snapshot_id': 'wind-nikkei-temporary', 'updated_at': modified,
            'calendar_reference': 'Wind返回的东京市场日线日期', 'rsi_method': 'wilder_v1',
            'window': window, 'upper_pct': upper, 'lower_pct': lower,
            'indexes': {NIKKEI_CODE: item},
            'data_note': '当前展示本地保存的日经225指数点位（价格指数）；不是日经全收益指数。数据来自Wind中文名称查询临时序列，具体Wind代码映射仍待核验。'}


def open_quality_issues(symbol):
    if not DATABASE_PATH.exists():
        return []
    with sqlite3.connect(DATABASE_PATH) as connection:
        table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='quality_issues'").fetchone()
        if not table:
            return []
        rows = connection.execute("SELECT trade_date,issue_code,severity FROM quality_issues WHERE kind='index' AND symbol=? AND resolution_status='open' ORDER BY trade_date,issue_code,severity",(symbol,)).fetchall()
    return [{'tradeDate':d,'issueCode':code,'severity':severity} for d,code,severity in rows]


def load_snapshot():
    root = ROOT / 'data'
    try:
        manifest = json.loads((root / 'current_manifest.json').read_text(encoding='utf-8'))
        path = (root / manifest['files']['index']).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('invalid snapshot path')
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest['sha256']['index']:
            raise ValueError('snapshot hash mismatch')
        return manifest, json.loads(payload)
    except (OSError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f'指数快照不可用：{exc}') from exc


def get_metrics(code, window, upper, lower):
    manifest, data = load_snapshot()
    calendar = data.get('tradingCalendar', {}).get('dates')
    if not calendar:
        raise HTTPException(status_code=503, detail='快照缺少交易日历，无法确认指标')
    try:
        for day in calendar:
            if len(day) != 8 or datetime.strptime(day, '%Y%m%d').strftime('%Y%m%d') != day:
                raise ValueError(day)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail=f'交易日历日期无效：{exc}') from exc
    result = {}
    calendar_days = set(calendar)
    for symbol in NAMES if code == 'all' else [code]:
        obs = {}
        outside_calendar_dates = []
        for row in data.get('flatRecords', []):
            if row.get('indexCode') == symbol:
                day = row['tradeDate']
                if day not in calendar_days:
                    outside_calendar_dates.append(day)
                    continue
                if day in obs:
                    raise HTTPException(status_code=503, detail=f'{symbol}存在重复交易日：{day}')
                obs[day] = row['closeValue']
        if not obs:
            raise HTTPException(status_code=503, detail=f'{symbol}没有指数数据')
        issues=open_quality_issues(symbol)
        blocked_dates={issue['tradeDate'] for issue in issues if issue['severity']=='BLOCKED' and issue['tradeDate'] in calendar_days}
        # The raw snapshot remains untouched; a known unresolved conflict cannot
        # enter a signal window or be hidden by carrying forward a value.
        blocked_values={day:obs.pop(day) for day in blocked_dates if day in obs}
        try:
            rows = indicators(calendar, obs, window, upper, lower)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=f'{symbol}数据质量问题：{exc}') from exc
        anomalies=[]
        previous=None
        for row in rows:
            value=row['close']
            if previous is not None and value is not None and abs(value/previous-1) > .10:
                anomalies.append({'tradeDate':row['tradeDate'], 'dailyChange':value/previous-1, 'status':'WARNING', 'reason':'单日变动超过10%，需要核验'})
            previous=value
        result[symbol] = {'name': NAMES[symbol], 'return_type': 'total_return', 'provenance': 'LEGACY_UNVERIFIED', 'missing_dates': [r['tradeDate'] for r in rows if r['close'] is None and r['tradeDate'] not in blocked_values], 'blocked_dates':sorted(blocked_dates), 'outside_calendar_dates': sorted(set(outside_calendar_dates)), 'open_quality_issues':issues, 'anomalies':anomalies, 'rows': rows, 'dca': dca_states(rows, upper), 'rebalanceEvents': rebalance_events(rows, lower)}
    return {'snapshot_id': manifest['snapshot_id'], 'updated_at': data.get('updatedAt'), 'calendar_reference': data.get('tradingCalendar',{}).get('referenceCode','UNKNOWN'), 'rsi_method': 'wilder_v1', 'window': window, 'upper_pct': upper, 'lower_pct': lower, 'indexes': result}


@router.get('/metrics')
def metrics(index_code: str = 'all', ma_window: int = Query(1250, ge=1, le=5000), upper_pct: float = Query(.15, ge=0, le=2), lower_pct: float = Query(.15, ge=0, le=1), base_date: str = Query(None, pattern=r'^\d{8}$')):
    if index_code == 'nikkei225':
        return get_nikkei_metrics(ma_window, upper_pct, lower_pct)
    if index_code != 'all' and index_code not in NAMES:
        raise HTTPException(status_code=422, detail='不支持的指数代码')
    result = get_metrics(index_code, ma_window, upper_pct, lower_pct)
    if index_code == 'all':
        series = {code: result['indexes'][code]['rows'] for code in NAMES}
        try:
            result['comparison'] = compare_indexes(series, base_date or series['H20903'][0]['tradeDate'])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


@router.get('/data-quality')
def data_quality(index_code: str = 'all'):
    if index_code != 'all' and index_code not in NAMES:
        raise HTTPException(status_code=422, detail='不支持的指数代码')
    data = get_metrics(index_code, 1250, .15, .15)
    return {'snapshot_id': data['snapshot_id'], 'updated_at':data['updated_at'], 'calendar_reference':data['calendar_reference'], 'quality_registry_scope':'current_local_database', 'indexes': {code: {'provenance': item['provenance'], 'missing_dates': item['missing_dates'], 'blocked_dates':item['blocked_dates'], 'open_quality_issues':item['open_quality_issues'], 'anomalies': item['anomalies']} for code, item in data['indexes'].items()}}


@router.get('/events')
def events(index_code: str, mode: str = 'dca', ma_window: int = Query(1250, ge=1, le=5000), upper_pct: float = Query(.15, ge=0, le=2), lower_pct: float = Query(.15, ge=0, le=1)):
    if index_code not in NAMES or mode not in {'dca', 'rebalance'}:
        raise HTTPException(status_code=422, detail='指数代码或事件模式无效')
    data = get_metrics(index_code, ma_window, upper_pct, lower_pct)
    rows = data['indexes'][index_code]['rows']
    result = dca_states(rows, upper_pct) if mode == 'dca' else {'events': rebalance_events(rows, lower_pct)}
    return {'snapshot_id': data['snapshot_id'], 'index_code': index_code, 'provenance': 'LEGACY_UNVERIFIED', 'rule_version': 'fixed_original_v1', **result}


class BacktestRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    index_code: Literal['H20903', 'H00922']
    strategy_mode: Literal['DCA_ALWAYS', 'DCA_ANCHOR', 'REBAL_CALENDAR', 'REBAL_ANCHOR']
    data_snapshot_id: str
    start_date: str
    end_date: str
    asset_mode: Literal['theoretical_index', 'tradable_asset'] = 'theoretical_index'
    ma_window: int = Field(1250, ge=1, le=5000)
    upper_pct: float = Field(.15, ge=0, le=2)
    lower_pct: float = Field(.15, ge=0, le=1)
    contribution: float = Field(1000, gt=0)
    initial_cash: float = Field(10000, ge=0)
    equity_weight: float = Field(.6, gt=0, lt=1)
    commission_rate: float = Field(..., ge=0, lt=.1)
    slippage_rate: float = Field(..., ge=0, lt=.1)
    rebalance_frequency: Literal['yearly', 'quarterly'] = 'yearly'


def _date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='日期应为 YYYY-MM-DD') from exc


def compute_backtest(request):
    if request.asset_mode != 'theoretical_index':
        raise HTTPException(status_code=422, detail='INSUFFICIENT_ASSET_DATA：尚无核验的可交易资产及分红数据')
    data = get_metrics(request.index_code, request.ma_window, request.upper_pct, request.lower_pct)
    if data['snapshot_id'] != request.data_snapshot_id:
        raise HTTPException(status_code=409, detail='数据快照已更新，请重新选择当前快照')
    try:
        result = run_backtest(data['indexes'][request.index_code]['rows'], strategy=request.strategy_mode,
            start=_date(request.start_date), end=_date(request.end_date), amount=request.contribution,
            initial=request.initial_cash, weight=request.equity_weight, commission=request.commission_rate,
            slippage=request.slippage_rate, upper=request.upper_pct, lower=request.lower_pct,
            rebalance_frequency=request.rebalance_frequency)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    params = request.model_dump() if hasattr(request, 'model_dump') else request.dict()
    key = json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    code_dir = Path(__file__).parent
    code_version = hashlib.sha256(b''.join((code_dir / name).read_bytes() for name in ('api.py', 'domain.py', 'strategy.py', 'backtest.py'))).hexdigest()
    quality_json = json.dumps(data['indexes'][request.index_code]['open_quality_issues'], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    quality_hash = hashlib.sha256(quality_json.encode()).hexdigest()
    run_id = hashlib.sha256((code_version + ':' + quality_hash + ':' + key).encode()).hexdigest()
    return {'run_id': run_id, 'snapshot_id': data['snapshot_id'], 'code_hash': code_version, 'quality_hash':quality_hash, 'quality_issues':data['indexes'][request.index_code]['open_quality_issues'], 'rule_version':'fixed_original_v1', 'parameters': params, 'provenance': 'LEGACY_UNVERIFIED', 'warning': '理论指数代理和零收益现金；不可作为真实可交易收益。成本为用户输入假设，历史来源待核验。', **result}


@router.post('/backtest')
def backtest(request: BacktestRequest):
    result = compute_backtest(request)
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS anchor_backtest_runs (run_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, created_at TEXT NOT NULL, result_json TEXT NOT NULL)')
        connection.execute('INSERT OR IGNORE INTO anchor_backtest_runs VALUES (?, ?, ?, ?)', (result['run_id'], result['snapshot_id'], datetime.now().astimezone().isoformat(), json.dumps(result, ensure_ascii=False, allow_nan=False)))
    return result


@router.get('/backtest/{run_id}')
def get_backtest(run_id: str):
    if len(run_id) != 64 or any(c not in '0123456789abcdef' for c in run_id):
        raise HTTPException(status_code=422, detail='无效的回测编号')
    with sqlite3.connect(DATABASE_PATH) as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='anchor_backtest_runs'").fetchone()
        row = connection.execute('SELECT result_json FROM anchor_backtest_runs WHERE run_id=?', (run_id,)).fetchone() if exists else None
    if row is None:
        raise HTTPException(status_code=404, detail='未找到回测记录')
    result=json.loads(row[0])
    result['is_current_snapshot'] = result['snapshot_id'] == load_snapshot()[0]['snapshot_id']
    current_quality=json.dumps(open_quality_issues(result['parameters']['index_code']),sort_keys=True,ensure_ascii=False,separators=(',', ':'))
    result['is_current_quality'] = result.get('quality_hash') == hashlib.sha256(current_quality.encode()).hexdigest()
    return result


class RobustnessRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    backtest: BacktestRequest
    thresholds: list[float] = Field(default_factory=lambda: [.10, .15, .20, .25, .30], min_length=1, max_length=10)
    train_days: int = Field(500, ge=30, le=3000)
    test_days: int = Field(242, ge=10, le=1000)
    quantile_window: int = Field(756, ge=20, le=3000)


@router.post('/robustness')
def robustness(request: RobustnessRequest):
    config = request.backtest
    if config.strategy_mode != 'DCA_ANCHOR' or config.asset_mode != 'theoretical_index' or any(not 0 <= t <= 2 for t in request.thresholds):
        raise HTTPException(status_code=422, detail='稳健性研究当前只支持理论指数定投及合法固定阈值')
    data = get_metrics(config.index_code, config.ma_window, config.upper_pct, config.lower_pct)
    if config.data_snapshot_id != data['snapshot_id']:
        raise HTTPException(status_code=409, detail='数据快照已更新')
    rows=data['indexes'][config.index_code]['rows']
    start, end = _date(config.start_date), _date(config.end_date)
    kwargs={'amount':config.contribution,'initial':config.initial_cash,'weight':config.equity_weight,'commission':config.commission_rate,'slippage':config.slippage_rate,'lower':config.lower_pct,'rebalance_frequency':config.rebalance_frequency}
    try:
        sensitivity=[]
        for threshold in request.thresholds:
            result=run_backtest(rows,strategy='DCA_ANCHOR',start=start,end=end,upper=threshold,**kwargs)
            sensitivity.append({'threshold':threshold,'twr':result['twr'],'xirr':result['xirr'],'finalValue':result['finalValue'],'cash':result['cash'],'tradeCount':result['tradeCount'],'signalCount':result['signalCount'],'pausedTradingDays':result['pausedTradingDays'],'longestPauseTradingDays':result['longestPauseTradingDays'],'endingPaused':result['endingPaused']})
        folds=walk_forward(rows,request.thresholds,request.train_days,request.test_days,start,end,**kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    quantiles=lagged_quantiles([r['deviation'] for r in rows],request.quantile_window,.8)
    stress=[]
    for multiplier in (1, 2, 5):
        stressed_kwargs={**kwargs,'commission':min(config.commission_rate*multiplier,.099),'slippage':min(config.slippage_rate*multiplier,.099)}
        stress_result=run_backtest(rows,strategy='DCA_ANCHOR',start=start,end=end,upper=config.upper_pct,**stressed_kwargs)
        stress.append({'costMultiplier':multiplier,'commission':stressed_kwargs['commission'],'slippage':stressed_kwargs['slippage'],'twr':stress_result['twr'],'fees':stress_result['totalFees'],'slippageCost':stress_result['totalSlippage']})
    try:
        usable=[r['tradeDate'] for r,q in zip(rows,quantiles) if start <= r['tradeDate'] <= end and q is not None and r['deviation'] is not None]
        if not usable:
            raise ValueError('所选日期内没有完成滚动分位预热的交易日')
        effective_start=usable[0]
        q_result=run_backtest(rows,strategy='DCA_ANCHOR',start=effective_start,end=end,thresholds=quantiles,**kwargs)
        q_benchmark=run_backtest(rows,strategy='DCA_ALWAYS',start=effective_start,end=end,**kwargs)
        q_fixed=run_backtest(rows,strategy='DCA_ANCHOR',start=effective_start,end=end,upper=config.upper_pct,**kwargs)
        q_summary={'status':'READY','effectiveStart':effective_start,'end':end,'twr':q_result['twr'],'xirr':q_result['xirr'],'cash':q_result['cash'],'tradeCount':q_result['tradeCount'],'baselineTwr':q_benchmark['twr'],'fixedThresholdTwr':q_fixed['twr']}
    except ValueError as exc:
        q_summary={'status':'INSUFFICIENT_HISTORY','reason':str(exc)}
    parameters=request.model_dump() if hasattr(request,'model_dump') else request.dict()
    quality_json=json.dumps(data['indexes'][config.index_code]['open_quality_issues'],sort_keys=True,ensure_ascii=False,separators=(',', ':'))
    quality_hash=hashlib.sha256(quality_json.encode()).hexdigest()
    code_dir=Path(__file__).parent
    code_hash=hashlib.sha256(b''.join((code_dir/name).read_bytes() for name in ('api.py','domain.py','strategy.py','backtest.py','research.py'))).hexdigest()
    param_json=json.dumps(parameters,sort_keys=True,ensure_ascii=False,separators=(',', ':'))
    run_id=hashlib.sha256((code_hash+':'+quality_hash+':'+param_json).encode()).hexdigest()
    result={'run_id':run_id,'code_hash':code_hash,'quality_hash':quality_hash,'parameters':parameters,'snapshot_id':data['snapshot_id'],'index_code':config.index_code,'thresholdTrials':len(request.thresholds),'sensitivity':sensitivity,'walkForward':folds,'costStress':stress,'quantileMethod':'linear_interpolation_prior_observations_only','quantileWindow':request.quantile_window,'quantile80':[{'tradeDate':r['tradeDate'],'value':v} for r,v in zip(rows,quantiles) if start <= r['tradeDate'] <= end], 'quantileBacktest':q_summary,'warnings':['研究假设，样本可能不足；不可将样本内最优参数视为样本外有效。','滚动分位为研究扩展；恢复条件仍为偏离率不高于零。','样本外区间重放历史信号状态，但每个测试区间从空账户开始。','历史数据来源待核验；本结果为理论指数代理。']}
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS anchor_research_runs (run_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, created_at TEXT NOT NULL, result_json TEXT NOT NULL)')
        connection.execute('INSERT OR IGNORE INTO anchor_research_runs VALUES (?, ?, ?, ?)', (run_id, data['snapshot_id'], datetime.now().astimezone().isoformat(), json.dumps(result,ensure_ascii=False,allow_nan=False)))
    return result


@router.get('/robustness/{run_id}')
def get_robustness(run_id: str):
    if len(run_id) != 64 or any(c not in '0123456789abcdef' for c in run_id):
        raise HTTPException(status_code=422,detail='无效的研究编号')
    with sqlite3.connect(DATABASE_PATH) as connection:
        exists=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='anchor_research_runs'").fetchone()
        row=connection.execute('SELECT result_json FROM anchor_research_runs WHERE run_id=?',(run_id,)).fetchone() if exists else None
    if row is None:
        raise HTTPException(status_code=404,detail='未找到研究记录')
    result=json.loads(row[0])
    result['is_current_snapshot']=result['snapshot_id']==load_snapshot()[0]['snapshot_id']
    quality_json=json.dumps(open_quality_issues(result['index_code']),sort_keys=True,ensure_ascii=False,separators=(',', ':'))
    result['is_current_quality']=result.get('quality_hash')==hashlib.sha256(quality_json.encode()).hexdigest()
    return result
