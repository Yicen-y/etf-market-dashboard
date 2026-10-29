from __future__ import annotations

import argparse
from datetime import date, timedelta

from scripts.config import DATABASE_PATH
from scripts.fund_flow.config import ETF_UNIVERSE
from scripts.fund_flow.providers.nav_provider import AkshareNavProvider
from scripts.fund_flow.providers.sse_provider import AkshareSSEProvider
from scripts.fund_flow.providers.szse_provider import AkshareSZSEProvider
from scripts.fund_flow.services.sync import sync_recent


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 ETF 交易所份额和独立单位净值")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--backfill", action="store_true")
    mode.add_argument("--incremental", action="store_true")
    parser.add_argument("--start", default="2023-12-29")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--overlap-days", type=int, default=5)
    args = parser.parse_args()
    end = date.fromisoformat(args.end)
    start = date.fromisoformat(args.start)
    if args.incremental:
        start = end - timedelta(days=max(1, args.overlap_days) * 3)
    report = sync_recent(
        DATABASE_PATH,
        share_providers=[AkshareSSEProvider(), AkshareSZSEProvider()],
        nav_provider=AkshareNavProvider(),
        codes=list(ETF_UNIVERSE),
        start=start,
        end=end,
    )
    print({
        "inserted": report.inserted,
        "updated": report.updated,
        "latest_trade_date": report.latest_trade_date.isoformat() if report.latest_trade_date else None,
        "provider_status": report.provider_status,
        "warnings": report.warnings,
    })
    return 0 if not report.warnings else 1


if __name__ == "__main__":
    raise SystemExit(main())

