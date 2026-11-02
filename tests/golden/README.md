# Golden samples

冻结样本保存在 `data/raw/dividend/`，由测试以 SHA-256、发布机构、公告URL、页码/字段和独立 Decimal 复算核验：

- ETF:510880：上海证券交易所公告，2026-01-16，`1.4300元/10份`，2026-01-21除息，SHA-256 见 `evidence_manifest.json`。
- STOCK:600519：官方URL当前不可访问，保留可追溯镜像和镜像状态，不将其标记为官方已核验。

`tests/dividend/reference_calculator.py` 是独立于生产领域函数的最小复算实现；生产代码不得反向驱动这些预期值。
