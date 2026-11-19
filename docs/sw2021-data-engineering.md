# 申万2021版一级行业数据工程

## 范围与实际口径

本模块采集 31 个申万一级行业普通指数的日线，不将其声明为全收益指数，也不做复权或分红再投资。代码与中文名称固定在 `scripts/sw2021.py` 的 `INDUSTRIES`。AKShare `index_hist_sw(symbol=代码, period="day")` 返回全历史，程序在本地按日期截取；本次环境版本为 AKShare 1.18.64。收盘、开高低以原始指数点位存储；成交量和成交额保存 AKShare 原始数值，不做未经证实的单位换算。字段映射与单位证据在 `sw2021_source_fields`。

Wind 核验使用 Codex 已配置的 MCP 服务：先由 `index_data.get_index_basicinfo` 按行业名称确认标准代码，再用 `index_data.get_index_kline` 的 `windcode`、`begin_date`、`end_date`、`period=1d`、`count=0` 获取日 K。实际返回字段为 `TIME`、`OPEN`、`MATCH`、`HIGH`、`LOW` 等；以 `MATCH` 作为收盘点位，与有色金属多个同日 AKShare 收盘值核对后采用。2019-01-01 至 2026-11-18 的单次查询每行业返回 1,910 条，随后单独补取 11 月 19 日一条；未观察到分页截断。31 个实际确认代码均为对应六位代码加 `.SI`；映射详见本地 `data/verification/sw2021/wind_mcp/mapping.json` 和数据库 `sw2021_indices.wind_code`。Wind MCP 返回的 `TIME` 时区偏移在历史行中并不恒定，按字符串的日历日期部分归一到上海交易日；不将其当作 UTC 时间戳进行换日。

| AKShare代码 | 行业 | 已核实Wind代码 |
|---|---|---|
| 801010 | 农林牧渔 | 801010.SI |
| 801030 | 基础化工 | 801030.SI |
| 801040 | 钢铁 | 801040.SI |
| 801050 | 有色金属 | 801050.SI |
| 801080 | 电子 | 801080.SI |
| 801110 | 家用电器 | 801110.SI |
| 801120 | 食品饮料 | 801120.SI |
| 801130 | 纺织服饰 | 801130.SI |
| 801140 | 轻工制造 | 801140.SI |
| 801150 | 医药生物 | 801150.SI |
| 801160 | 公用事业 | 801160.SI |
| 801170 | 交通运输 | 801170.SI |
| 801180 | 房地产 | 801180.SI |
| 801200 | 商贸零售 | 801200.SI |
| 801210 | 社会服务 | 801210.SI |
| 801230 | 综合 | 801230.SI |
| 801710 | 建筑材料 | 801710.SI |
| 801720 | 建筑装饰 | 801720.SI |
| 801730 | 电力设备 | 801730.SI |
| 801740 | 国防军工 | 801740.SI |
| 801750 | 计算机 | 801750.SI |
| 801760 | 传媒 | 801760.SI |
| 801770 | 通信 | 801770.SI |
| 801780 | 银行 | 801780.SI |
| 801790 | 非银金融 | 801790.SI |
| 801880 | 汽车 | 801880.SI |
| 801890 | 机械设备 | 801890.SI |
| 801950 | 煤炭 | 801950.SI |
| 801960 | 石油石化 | 801960.SI |
| 801970 | 环保 | 801970.SI |
| 801980 | 美容护理 | 801980.SI |

**边界：** Codex 可调用 Wind MCP，不代表部署后的 FastAPI 进程有该权限。项目运行时只采集 AKShare；Wind 历史或增量快照须由已授权的 Codex 环境调用 MCP 后导入。本模块不会伪造运行时 Wind 连接。Wind 与 AKShare 是不同访问通道，但 Wind 行情可能仍来自申万发布的数据，逐日一致不证明存在两个独立编制机构。

## 数据结构与放行

数据库沿用现有 SQLite 文件以及 `raw_observations`、`quality_issues`，新增 `sw2021_*` 元数据、日线、采集批次、Wind 快照批次、逐日核验与修订表。现有 `index_prices` 是已发布策略所用的收盘点位表，不能承载 OHLC 和待核验状态；本模块不写入它，也不修改现有指数的放行规则。AKShare 返回的 DataFrame 序列化快照保存在数据目录的 `raw/market/`（AKShare 接口未暴露底层 HTTP 原始字节），Wind MCP 原始信封保存在 `verification/sw2021/wind/`；批次表保存路径与 SHA-256。源值修订保存在 `sw2021_daily_revisions` 或 `sw2021_wind_revisions`，旧快照不删除。

采集批次 `COMPLETED/PARTIAL/FAILED`、本地日线 `QC_PASSED/REVIEW/FAILED`、跨源结果 `VERIFIED/CONFLICT/AK_MISSING/HISTORICAL_BACKFILL_ONLY/WIND_MISSING/QC_BLOCKED/STALE` 分开记录。`sw2021_approved_daily` 只给出本地 QC 通过、Wind 点位相对误差不超过 `0.0001`，且核验仍对应当前 AKShare 批次的日期。新数据、冲突、修订后待补验、异常跳变以及缺口不会由该视图放行。阈值是工程值，不代表编制机构标准。未来策略应只读该视图并自行处理历史分类可用性。

## 分类历史

[申万宏源研究的2021版分类说明](https://wxweb.swsresearch.com/swsreport/2021_08/328340.pdf)指出新版分类于 2021-07-30 推出，一级行业由 28 个调整为 31 个，新增美容护理，石油石化、环保等结构也发生调整。本次实测 AKShare 中 `801960`、`801970`、`801980` 的序列从 2021-12-13 才开始，Wind 则对这些代码提供 2019 年起的历史点位。库内将 2021-12-13 前的序列标为需要分类回溯审查：旧行业的早期点位可能沿用旧分类，也可能经过回算，不能仅凭日期连续推断其在当时按 SW2021 分类实时可得。三项新行业的 Wind 早期点位尤其不能直接用于无前视偏差的历史轮动回测。

## 运行和恢复

在项目根目录使用当前 Python 环境运行：

```powershell
python -m scripts.sw2021 calendar
python -m scripts.sw2021 collect --start 2019-01-01
python -m scripts.sw2021 collect --code 801050 --start 2021-01-01 --end 2021-12-31
python -m scripts.sw2021 collect --incremental --overlap-days 30
```

采集逐指数隔离失败，单指数最多尝试三次并退避，指数间默认间隔 0.6 秒；失败批次及异常记录保存在数据库，可用 `--code` 和 `--start/--end` 补采。增量模式重读最近 30 个自然日并比较历史值。AKShare 接口本身没有起止日期参数，增量时网络仍下载该指数全历史，只在本地处理重叠范围。

Wind MCP 操作须在 Codex 的授权环境中执行。先对目标指数用 `get_index_basicinfo` 核实代码，再用 `get_index_kline` 查询尚未核验的日期范围；保存原始 MCP/CLI JSON 响应后运行：

```powershell
python -m scripts.sw2021 import-wind --code 801050 --wind-code 801050.SI --start 2026-11-19 --end 2026-11-19 --file <MCP原始JSON路径>
python -m scripts.sw2021 verify --code 801050
python -m scripts.sw2021 report --output data/verification/sw2021/acceptance
```

`import-wind` 支持重试同一快照；失败信封记录为失败批次，成功快照的内容哈希确定批次号。对其他行业分别使用经 Wind 档案核实的代码与原始 JSON。中断后检查 `sw2021_wind_batches` 与 `sw2021_verification`，只补未完成范围，再运行 `verify`；核验是幂等 upsert。不能把短区间抽样写成全历史核验。

## 2026-11-19 首次验收

正式库在采集前已进行一致性备份。AKShare 31 行业共 56,519 条，所有有效行本地 QC 通过，源站末日均为 2026-11-09；再次运行增量采集无新增、无修订。Wind 31 行业共 59,241 条，覆盖至 2026-11-19。双方共同的 56,519 个交易日点位全部一致，最大绝对和相对误差均为 0，超限记录 0。A 股交易日历对照的 AKShare 缺口为 2,722 个行业交易日，其中 2,145 条是三项新行业在 2021-12-13 前仅有 Wind 回溯点位，其余 577 条为其他历史缺行与近期滞后。故数据库写入和已入库行本地 QC 为 `PASS`，全区间覆盖与 Wind 整体核验为 `PARTIAL`，不满足整批无缺口准入。逐行业明细与异常原始值在本地 `data/verification/sw2021/acceptance-20261119-final.*`，该目录被 Git 忽略，不应推送 Wind 原始数据或数据库文件。
