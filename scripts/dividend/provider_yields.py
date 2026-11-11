"""Provider reported yields, kept separate from issuer-cash TTM calculations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from scripts.wind_credentials import get_authorization
from scripts.wind_mcp_client import WindMcpClient
from scripts.credential_settings import get_credential
from .db import connect, init_schema


STOCK_PROVIDER = 'wind:mcp:stock_fundamentals'
ETF_PROVIDER = 'htbr:fund-valuation'
STOCK_LABEL = 'Wind股息率（提供方口径）'
ETF_LABEL = '华泰柏瑞持仓加权股息率'
WIND_URL = 'https://mcp.wind.com.cn/vserver_stock_data/mcp/'
SKILL_ROOT = Path.home() / '.codex' / 'skills' / 'htbr-etf-skill'
_WIND_CALL_LOCK = threading.Lock()
_WIND_LAST_CALL = 0.0


def _wind_call(client, tool_name: str, arguments: dict):
    """Serialize Wind calls and leave a small configurable gap between requests."""
    global _WIND_LAST_CALL
    interval = max(0.0, float(os.getenv('WIND_MIN_INTERVAL_SECONDS', '2.0')))
    with _WIND_CALL_LOCK:
        wait = interval - (time.monotonic() - _WIND_LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _WIND_LAST_CALL = time.monotonic()
        return client.call_tool(tool_name, arguments)


def _percent(value) -> str:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or result > 100:
        raise ValueError('提供方股息率超出有效百分比区间')
    return str(result)


def _looks_like_rate_limit(error: Exception) -> bool:
    text = str(error).lower()
    return any(token in text for token in ('频次', '调用次数', 'rate limit', 'too many', 'temporarily limited'))


def parse_wind_stock_yield(snapshot: dict, fundamentals: dict, windcode: str) -> dict:
    """Require an explicit % unit and the same dated ticker in both Wind responses."""
    if snapshot.get('error') or fundamentals.get('error'):
        raise ValueError('Wind返回业务错误')
    quote = snapshot['data']
    names = [column['name'] for column in quote['columns']]
    rows = quote['rows']
    if names.count('最新交易日') != 1 or names.count('Wind代码') != 1 or len(rows) != 1:
        raise ValueError('Wind交易日快照缺失或多标的混入')
    row = rows[0]
    day_raw = str(row[names.index('最新交易日')])
    if row[names.index('Wind代码')] != windcode or not re.fullmatch(r'\d{8}', day_raw):
        raise ValueError('Wind标的或交易日不一致')
    day = datetime.strptime(day_raw, '%Y%m%d').date().isoformat()
    groups = fundamentals['data']['data']
    if len(groups) != 1:
        raise ValueError('Wind股息率结果缺失或不唯一')
    group = groups[0]
    columns = group['columns']
    data_rows = group['rows']
    expected_name = f'{day[:4]}年{int(day[5:7])}月{int(day[8:10])}日股息率'
    match = [i for i, col in enumerate(columns) if col.get('name') == expected_name and col.get('unit') == '%']
    ticker = [i for i, col in enumerate(columns) if col.get('name') == 'Wind代码']
    if len(match) != 1 or len(ticker) != 1 or len(data_rows) != 1:
        raise ValueError('Wind股息率日期或百分比单位不明确')
    values = data_rows[0]
    if values[ticker[0]] != windcode or values[match[0]] is None:
        raise ValueError('Wind股息率标的或数值不匹配')
    return {'value_pct': _percent(values[match[0]]), 'as_of_date': day,
            'metric_label': STOCK_LABEL, 'provider': STOCK_PROVIDER,
            'raw': {'snapshot': snapshot, 'fundamentals': fundamentals}}


def _wind_payload(result: dict) -> dict:
    if result.get('isError'):
        raise ValueError('Wind MCP返回工具错误')
    blocks = [block['text'] for block in result.get('content', []) if block.get('type') == 'text']
    if len(blocks) != 1:
        raise ValueError('Wind MCP响应不是唯一文本块')
    payload = json.loads(blocks[0])
    if not isinstance(payload, dict):
        raise ValueError('Wind MCP响应不是对象')
    return payload


def fetch_wind_stock_yield(code: str, market: str) -> dict:
    authorization = get_authorization()
    if not authorization:
        raise RuntimeError('Wind MCP凭证不可用')
    windcode = f'{code}.{market}'
    with WindMcpClient(WIND_URL, authorization, timeout=60) as client:
        client.initialize()
        snapshot = _wind_payload(_wind_call(client, 'get_stock_price_indicators', {
            'windcode': windcode, 'indexes': '最新交易日'}))
        names = [c['name'] for c in snapshot.get('data', {}).get('columns', [])]
        if '最新交易日' not in names or len(snapshot.get('data', {}).get('rows', [])) != 1:
            raise ValueError('Wind最新交易日不可用')
        day = str(snapshot['data']['rows'][0][names.index('最新交易日')])
        if not re.fullmatch(r'\d{8}', day):
            raise ValueError('Wind最新交易日无效')
        question = f'查询{windcode}在{day[:4]}-{day[4:6]}-{day[6:]}的股息率（%）。'
        fundamentals = _wind_payload(_wind_call(client, 'get_stock_fundamentals', {'question': question}))
    return parse_wind_stock_yield(snapshot, fundamentals, windcode)


def _historical_value_from_fundamentals(fundamentals: dict, windcode: str, trade_date: str) -> str:
    """Extract one dated percentage from the Wind fundamentals response.

    Wind's natural-language fundamentals tool may use either a Chinese dated
    column name or a plain ``股息率`` name.  We accept only an explicit percent
    unit and a single value; ambiguous responses are rejected rather than
    silently interpreted.
    """
    if fundamentals.get('error'):
        raise ValueError('Wind返回业务错误')
    groups = fundamentals.get('data', {}).get('data', [])
    if len(groups) != 1:
        raise ValueError('Wind历史股息率结果缺失或不唯一')
    columns = groups[0].get('columns', [])
    rows = groups[0].get('rows', [])
    if len(rows) != 1:
        raise ValueError('Wind历史股息率行数不唯一')
    day = datetime.strptime(trade_date, '%Y-%m-%d')
    day_tokens = {trade_date, trade_date.replace('-', ''),
                  f'{day.year}年{day.month}月{day.day}日'}
    candidates = []
    for index, column in enumerate(columns):
        name = str(column.get('name', ''))
        if column.get('unit') == '%' and '股息率' in name and (
            any(token in name for token in day_tokens) or name == '股息率'
        ):
            candidates.append(index)
    ticker_indexes = [i for i, column in enumerate(columns)
                      if column.get('name') == 'Wind代码']
    if len(candidates) != 1 or len(ticker_indexes) != 1:
        raise ValueError('Wind历史股息率日期或百分比单位不明确')
    if rows[0][ticker_indexes[0]] != windcode:
        raise ValueError('Wind历史股息率标的不匹配')
    value = rows[0][candidates[0]]
    if value is None:
        raise ValueError('Wind历史股息率为空')
    return _percent(value)


def fetch_wind_stock_yield_on_date(code: str, market: str, trade_date: str) -> dict:
    """Fetch one Wind-provided stock dividend yield for a specified date."""
    authorization = get_authorization()
    if not authorization:
        raise RuntimeError('Wind MCP凭证不可用')
    windcode = f'{code}.{market}'
    with WindMcpClient(WIND_URL, authorization, timeout=60) as client:
        client.initialize()
        question = f'查询{windcode}在{trade_date}的股息率（%）。'
        fundamentals = _wind_payload(_wind_call(client,
            'get_stock_fundamentals', {'question': question}))
    return {
        'value_pct': _historical_value_from_fundamentals(fundamentals, windcode, trade_date),
        'as_of_date': trade_date, 'metric_label': STOCK_LABEL,
        'provider': STOCK_PROVIDER, 'raw': {'fundamentals': fundamentals},
    }


def _wind_dates_from_payload(payload: dict) -> list[str]:
    data = payload.get('data', {})
    columns = data.get('columns', [])
    rows = data.get('rows', [])
    names = [column.get('name') if isinstance(column, dict) else str(column)
             for column in columns]
    date_index = next((i for i, name in enumerate(names)
                       if name in {'交易日期', '交易日', '日期', '时间', 'date'}), None)
    if date_index is None and rows:
        date_index = 0
    if date_index is None:
        raise ValueError('Wind交易日历响应缺少日期字段')
    result = []
    for row in rows:
        raw = str(row[date_index])[:10]
        if re.fullmatch(r'\d{8}', raw):
            raw = f'{raw[:4]}-{raw[4:6]}-{raw[6:]}'
        try:
            result.append(date.fromisoformat(raw).isoformat())
        except ValueError:
            continue
    if not result:
        raise ValueError('Wind交易日历为空')
    return sorted(set(result))


def fetch_wind_stock_trading_dates(code: str, market: str,
                                   start_date: str = '2000-01-01',
                                   end_date: str | None = None) -> list[str]:
    """Get actual exchange dates from Wind K-line, never fabricate weekdays."""
    authorization = get_authorization()
    if not authorization:
        raise RuntimeError('Wind MCP凭证不可用')
    windcode = f'{code}.{market}'
    with WindMcpClient(WIND_URL, authorization, timeout=60) as client:
        client.initialize()
        result = _wind_call(client, 'get_stock_kline', {
            'windcode': windcode, 'begin_date': start_date,
            'end_date': end_date or date.today().isoformat(),
            'period': '1d',
        })
    return _wind_dates_from_payload(_wind_payload(result))


def calculate_provider_yield_summary(rows, current_value=None) -> dict:
    valid = []
    for row in rows:
        if row.get('status') != 'READY' or row.get('value_pct') is None:
            continue
        try:
            value = Decimal(str(row['value_pct']))
        except Exception:
            continue
        if value.is_finite():
            valid.append(value)
    valid.sort()
    result = {
        'sample_count': len(valid), 'minimum': None, 'maximum': None,
        'mean': None, 'median': None, 'percentile': None,
    }
    if not valid:
        return result
    result.update(
        minimum=valid[0], maximum=valid[-1],
        mean=(sum(valid, Decimal('0')) / Decimal(len(valid))).quantize(
            Decimal('0.0001'), rounding=ROUND_HALF_UP),
        median=(valid[len(valid) // 2] if len(valid) % 2 else
                (valid[len(valid)//2 - 1] + valid[len(valid)//2]) / 2),
    )
    if current_value is not None:
        current = Decimal(str(current_value))
        result['percentile'] = (Decimal(sum(value <= current for value in valid)) /
                                Decimal(len(valid)) * Decimal('100')).quantize(
            Decimal('0.0001'), rounding=ROUND_HALF_UP)
    return result


def sync_wind_stock_yield_history(path: Path, security_id: str, *,
                                  date_fetcher=None, yield_fetcher=None,
                                  retry_count: int = 3, start_date: str = '2000-01-01',
                                  end_date: str | None = None) -> dict:
    """Backfill missing Wind history and retry failed dates without filling values."""
    init_schema(path)
    with connect(path) as db:
        security = db.execute(
            'SELECT code,market,security_type FROM dividend_securities WHERE security_id=?',
            (security_id,)).fetchone()
    if security is None:
        raise ValueError('证券不存在')
    if security['security_type'] != 'STOCK':
        raise ValueError('Wind历史股息率仅支持股票')
    code, market = security['code'], security['market']
    dates = (date_fetcher or fetch_wind_stock_trading_dates)(
        code, market, start_date, end_date or date.today().isoformat())
    dates = sorted(set(str(item)[:10] for item in dates))
    with connect(path) as db:
        existing = {row['trade_date']: row['status'] for row in db.execute(
            'SELECT trade_date,status FROM dividend_provider_yield_history WHERE security_id=?',
            (security_id,))}
    pending = [day for day in dates if existing.get(day) != 'READY']
    fetch = yield_fetcher or fetch_wind_stock_yield_on_date
    failed = []
    for trade_date in pending:
        row, error = None, None
        for _ in range(max(1, retry_count)):
            try:
                row = fetch(code, market, trade_date)
                break
            except Exception as exc:
                error = str(exc)
        fetched_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(row.get('raw', {}), ensure_ascii=False,
                             sort_keys=True, default=str) if row else None
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest() if payload is not None else None
        status = 'READY' if row else 'FAILED'
        reason = None if row else error
        value = _percent(row['value_pct']) if row else None
        with connect(path) as db:
            if payload is not None:
                db.execute('INSERT OR IGNORE INTO raw_source_records(payload,sha256) VALUES (?,?)',
                           (payload, digest))
            db.execute('''INSERT INTO dividend_provider_yield_history
                (security_id,trade_date,value_pct,provider,metric_label,source_sha256,
                 fetched_at,status,reason) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(security_id,trade_date) DO UPDATE SET
                value_pct=excluded.value_pct, provider=excluded.provider,
                metric_label=excluded.metric_label, source_sha256=excluded.source_sha256,
                fetched_at=excluded.fetched_at, status=excluded.status, reason=excluded.reason''',
                       (security_id, trade_date, value, STOCK_PROVIDER, STOCK_LABEL,
                        digest, fetched_at, status, reason))
        if not row:
            failed.append(trade_date)
    with connect(path) as db:
        ready = db.execute('''SELECT trade_date,value_pct,source_sha256 FROM dividend_provider_yield_history
            WHERE security_id=? AND status='READY' ORDER BY trade_date''', (security_id,)).fetchall()
        if ready:
            latest = ready[-1]
            db.execute('''INSERT INTO dividend_provider_yields
                (security_id,value_pct,as_of_date,fetched_at,provider,metric_label,source_sha256,status,reason)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(security_id) DO UPDATE SET
                value_pct=excluded.value_pct,as_of_date=excluded.as_of_date,fetched_at=excluded.fetched_at,
                provider=excluded.provider,metric_label=excluded.metric_label,
                source_sha256=excluded.source_sha256,status='READY',reason=NULL''',
                       (security_id, latest['value_pct'], latest['trade_date'],
                        datetime.now(timezone.utc).isoformat(), STOCK_PROVIDER, STOCK_LABEL,
                        latest['source_sha256'], 'READY', None))
    return {'security_id': security_id, 'status': 'READY' if ready else 'FAILED',
            'ready_count': len(ready), 'queried_count': len(pending),
            'failed_dates': failed, 'earliest_date': ready[0]['trade_date'] if ready else None,
            'latest_date': ready[-1]['trade_date'] if ready else None}


def record_wind_stock_yield_observation(path: Path, security_id: str, result: dict,
                                        *, minimum_date: str = '2026-01-01') -> dict:
    """Store one fresh Wind observation without initiating historical backfill."""
    if result.get('provider') != STOCK_PROVIDER or result.get('metric_label') != STOCK_LABEL:
        raise ValueError('提供方指标身份不符')
    observed = datetime.fromisoformat(str(result['as_of_date'])).date().isoformat()
    if observed < minimum_date:
        return {'status': 'SKIPPED', 'trade_date': observed, 'reason': '早于本地观测起始日期'}
    value = _percent(result['value_pct'])
    payload = json.dumps(result.get('raw', {}), ensure_ascii=False,
                         sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    fetched_at = datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        db.execute('INSERT OR IGNORE INTO raw_source_records(payload,sha256) VALUES (?,?)',
                   (payload, digest))
        db.execute('''INSERT INTO dividend_provider_yield_history
            (security_id,trade_date,value_pct,provider,metric_label,source_sha256,
             fetched_at,status,reason) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(security_id,trade_date) DO UPDATE SET
            value_pct=excluded.value_pct, provider=excluded.provider,
            metric_label=excluded.metric_label, source_sha256=excluded.source_sha256,
            fetched_at=excluded.fetched_at, status='READY', reason=NULL
            WHERE dividend_provider_yield_history.status='FAILED' ''',
                   (security_id, observed, value, STOCK_PROVIDER, STOCK_LABEL,
                    digest, fetched_at, 'READY', None))
    return {'status': 'READY', 'trade_date': observed, 'value_pct': value}


def provider_yield_history_detail(path: Path, security_id: str) -> dict | None:
    init_schema(path)
    with connect(path) as db:
        security = db.execute('SELECT * FROM dividend_securities WHERE security_id=?', (security_id,)).fetchone()
        if security is None:
            return None
        latest_row = db.execute('''SELECT value_pct,as_of_date,status,provider,metric_label,
            last_refresh_status,last_refresh_reason
            FROM dividend_provider_yields WHERE security_id=?''', (security_id,)).fetchone()
        rows = db.execute('''SELECT trade_date,value_pct,provider,metric_label,source_sha256,
            fetched_at,status,reason FROM dividend_provider_yield_history
            WHERE security_id=? ORDER BY trade_date''', (security_id,)).fetchall()
    packed = [dict(row) for row in rows]
    current = next((row['value_pct'] for row in reversed(packed) if row['status'] == 'READY'), None)
    if current is None and latest_row is not None and latest_row['status'] == 'READY':
        current = latest_row['value_pct']
    summary = calculate_provider_yield_summary(packed, current)
    def serial(value): return str(value) if value is not None else None
    summary = {key: serial(value) if key != 'sample_count' else value
               for key, value in summary.items()}
    return {'security_id': security_id, 'security': dict(security), 'rows': packed,
            'current_value_pct': current, 'summary': summary,
            'provider': latest_row['provider'] if latest_row else STOCK_PROVIDER,
            'metric_label': latest_row['metric_label'] if latest_row else STOCK_LABEL,
            'quality_status': 'READY' if summary['sample_count'] else 'NO_HISTORY',
            'missing_dates': [row['trade_date'] for row in packed if row['status'] != 'READY']}


def _htbr_python() -> str:
    configured = os.getenv('HTBR_PYTHON')
    if configured:
        return configured
    candidate = Path('D:/Anaconda3/envs/IStock/python.exe')
    return str(candidate) if candidate.is_file() else sys.executable


def _htbr_environment(api_key: str | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    key = api_key if api_key is not None else get_credential('htbr')
    if key:
        environment['HTBR_ETF_API_KEY'] = key
    return environment


def _skill_call(api_id: str, params: dict, *, environment: dict[str, str] | None = None) -> dict:
    script = SKILL_ROOT / 'scripts' / 'api_client.py'
    if not script.is_file():
        raise RuntimeError('华泰柏瑞ETF技能未安装')
    cmd = [_htbr_python(), str(script), 'invoke', api_id,
           json.dumps(params, ensure_ascii=False)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=70, check=False,
                            env=environment or _htbr_environment())
    if result.returncode != 0:
        raise RuntimeError(f'华泰柏瑞接口调用失败（退出码{result.returncode}）')
    payload = json.loads(result.stdout)
    if payload.get('success') is not True or payload.get('error'):
        raise RuntimeError('华泰柏瑞接口返回错误')
    return payload


def parse_htbr_etf_yield(resolved: dict, valuation: dict, code: str) -> dict:
    candidates = resolved['data']['candidates']
    if resolved['data'].get('matchCount') != 1 or len(candidates) != 1 or candidates[0].get('secuCode') != code:
        raise ValueError('ETF代码无法唯一映射到基金内码')
    inner = int(candidates[0]['innerCode'])
    data = valuation['data']
    if data.get('innerCode') != inner:
        raise ValueError('华泰柏瑞估值结果基金内码不一致')
    rows = [row for row in data.get('records', [])
            if row.get('fundcode') == code and row.get('fundobject') == inner
            and row.get('dividendratio') is not None]
    if not rows:
        raise ValueError('华泰柏瑞未返回该ETF持仓股息率')
    latest_day = max(row['reportdate'] for row in rows)
    latest = [row for row in rows if row['reportdate'] == latest_day]
    values = {_percent(row['dividendratio']) for row in latest}
    if len(values) != 1:
        raise ValueError('同一报告期存在冲突的持仓股息率')
    return {'value_pct': values.pop(), 'as_of_date': latest_day,
            'metric_label': ETF_LABEL, 'provider': ETF_PROVIDER,
            'raw': {'resolved': resolved, 'valuation': valuation}}


def fetch_htbr_etf_yield(code: str, api_key: str | None = None) -> dict:
    environment = _htbr_environment(api_key)
    status = subprocess.run([_htbr_python(), str(SKILL_ROOT / 'config.py'), 'status'],
                            capture_output=True, timeout=15, check=False, env=environment)
    if status.returncode != 0:
        raise RuntimeError('华泰柏瑞ETF凭证不可用')
    resolved = _skill_call('fund-resolve', {'secuCode': code}, environment=environment)
    candidates = resolved['data']['candidates']
    if resolved['data'].get('matchCount') != 1 or len(candidates) != 1:
        raise ValueError('ETF代码无法唯一映射到基金内码')
    valuation = _skill_call('fund-valuation', {'innerCode': int(candidates[0]['innerCode'])}, environment=environment)
    return parse_htbr_etf_yield(resolved, valuation, code)


def provider_yield_detail(path: Path, security_id: str) -> dict | None:
    init_schema(path)
    with connect(path) as db:
        security = db.execute('SELECT security_type FROM dividend_securities WHERE security_id=?',
                              (security_id,)).fetchone()
        if security is None:
            return None
        row = db.execute('SELECT * FROM dividend_provider_yields WHERE security_id=?',
                         (security_id,)).fetchone()
    if row:
        result = dict(row)
        if result['status'] == 'READY':
            try:
                age = (date.today() - date.fromisoformat(result['as_of_date'])).days
            except (TypeError, ValueError):
                age = 10_000
            limit = 7 if security['security_type'] == 'STOCK' else 150
            if age < 0 or age > limit:
                result.update(value_pct=None, status='STALE',
                              reason=f'提供方数据日期超出{limit}天有效窗口，请刷新')
        return result
    kind = security['security_type']
    result = {'security_id': security_id, 'value_pct': None, 'as_of_date': None,
            'fetched_at': None, 'provider': STOCK_PROVIDER if kind == 'STOCK' else ETF_PROVIDER,
            'metric_label': STOCK_LABEL if kind == 'STOCK' else ETF_LABEL,
            'status': 'NOT_FETCHED', 'reason': '尚未获取提供方股息率', 'source_sha256': None,
            'last_refresh_status': 'NOT_FETCHED', 'last_refresh_reason': '尚未获取提供方股息率'}
    return result


def sync_provider_yield(path: Path, security_id: str, *, stock_fetcher=None, etf_fetcher=None) -> dict:
    init_schema(path)
    with connect(path) as db:
        security = db.execute('SELECT code,market,security_type FROM dividend_securities WHERE security_id=?',
                              (security_id,)).fetchone()
    if security is None:
        raise ValueError('证券不存在')
    kind = security['security_type']
    label = STOCK_LABEL if kind == 'STOCK' else ETF_LABEL
    provider = STOCK_PROVIDER if kind == 'STOCK' else ETF_PROVIDER
    try:
        if kind == 'STOCK':
            fetch = stock_fetcher or fetch_wind_stock_yield
            row = None
            for attempt in range(3):
                try:
                    row = fetch(security['code'], security['market'])
                    break
                except Exception as error:
                    if not _looks_like_rate_limit(error) or attempt == 2:
                        raise
                    time.sleep(5 * (attempt + 1))
        else:
            row = (etf_fetcher or fetch_htbr_etf_yield)(security['code'])
        if row['provider'] != provider or row['metric_label'] != label:
            raise ValueError('提供方指标身份不符')
        value = _percent(row['value_pct'])
        as_of = datetime.fromisoformat(row['as_of_date']).date().isoformat()
        age = (date.today() - date.fromisoformat(as_of)).days
        if age < 0 or age > (7 if kind == 'STOCK' else 150):
            raise ValueError('提供方返回的数据日期已过期或晚于当前日期')
        payload = json.dumps(row['raw'], ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        status, reason = 'READY', None
    except Exception as exc:
        value, as_of, payload, digest = None, None, None, None
        status, reason = 'UNAVAILABLE', str(exc)
    checked_at = datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        previous = db.execute('''SELECT value_pct,as_of_date,fetched_at,provider,metric_label,
            source_sha256,status,reason,last_refresh_status,last_refresh_reason
            FROM dividend_provider_yields WHERE security_id=?''', (security_id,)).fetchone()
        if payload is not None:
            db.execute('INSERT OR IGNORE INTO raw_source_records(payload,sha256) VALUES (?,?)',
                       (payload, digest))
        if status == 'READY' or previous is None or kind != 'STOCK':
            db.execute('''INSERT INTO dividend_provider_yields
                (security_id,value_pct,as_of_date,fetched_at,provider,metric_label,source_sha256,status,reason,
                 last_refresh_status,last_refresh_reason)
                VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(security_id) DO UPDATE SET
                value_pct=excluded.value_pct,as_of_date=excluded.as_of_date,
                fetched_at=excluded.fetched_at,source_sha256=excluded.source_sha256,
                status=excluded.status,reason=excluded.reason,
                provider=excluded.provider,metric_label=excluded.metric_label,
                last_refresh_status=excluded.last_refresh_status,
                last_refresh_reason=excluded.last_refresh_reason''',
                (security_id, value, as_of, checked_at, provider, label, digest, status, reason,
                 status, reason))
        else:
            db.execute('''UPDATE dividend_provider_yields
                SET last_refresh_status=?, last_refresh_reason=?
                WHERE security_id=?''',
                (status, reason, security_id))
    return provider_yield_detail(path, security_id)
