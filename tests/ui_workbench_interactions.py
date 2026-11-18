"""Read-only interaction smoke for the local dashboard; does not trigger data refresh."""
import csv
import os
import re
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright


HOST = os.environ.get("ETF_TEST_URL", "http://127.0.0.1:8010")
BASE = HOST + "/web"


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True,
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page.goto(f"{BASE}/index.html?strategy=prism")
        page.locator("#prism-content").wait_for(state="visible", timeout=15000)
        page.locator("#prism-observation strong").first.wait_for(state="visible", timeout=15000)
        assert page.evaluate("document.querySelector('#prism-observation').compareDocumentPosition(document.querySelector('#prism-main-chart')) & Node.DOCUMENT_POSITION_FOLLOWING")
        assert page.evaluate("document.querySelector('#prism-main-chart').compareDocumentPosition(document.querySelector('#prism-snapshot')) & Node.DOCUMENT_POSITION_FOLLOWING")
        assert page.locator("#prism-observation").inner_text().find("40日收益差") >= 0
        benchmark = page.locator("#benchmark-date").input_value()
        page.locator('[data-prism-range="1y"]').click()
        assert page.locator('[data-prism-range="1y"]').get_attribute("class").find("active") >= 0
        assert page.locator("#benchmark-date").input_value() == benchmark
        assert page.locator("#prism-view-range").inner_text().startswith("显示区间：")
        tick_counts = """() => [charts.prismMain,charts.ratio,charts.spread,charts.rsi].map(chart => {
          const axis=chart.getOption().xAxis[0].axisLabel;
          let count=0; for(let i=prismInteraction.viewStart;i<=prismInteraction.viewEnd;i++)
            if(axis.interval(i,prismInteraction.dates[i])) count++;
          return {count,show:axis.show,format:axis.formatter(prismInteraction.dates[prismInteraction.viewStart])};})"""
        assert all(tick["show"] and 1 <= tick["count"] <= 8 and len(tick["format"]) == 7
                   for tick in page.evaluate(tick_counts))
        page.set_viewport_size({"width": 375, "height": 900})
        page.wait_for_timeout(250)
        assert all(tick["show"] and 1 <= tick["count"] <= 3 for tick in page.evaluate(tick_counts))
        page.set_viewport_size({"width": 1440, "height": 900})
        assert all(page.locator(f"#{chart}").is_visible() for chart in (
            "prism-main-chart", "prism-ratio-chart", "prism-spread-chart", "prism-rsi-chart"
        ))
        with page.expect_download(timeout=10000) as download:
            page.locator("#download-prism-csv").click()
        assert download.value.suggested_filename.endswith(".csv")
        with Path(download.value.path()).open(encoding="utf-8-sig", newline="") as file:
            prism_rows = list(csv.reader(file))
        assert prism_rows[0][0] == "交易日" and len(prism_rows) > 100
        assert len(prism_rows[0]) == len(prism_rows[-1])
        page.goto(f"{BASE}/index.html")
        page.locator("#data-table tbody tr").first.wait_for(state="attached", timeout=15000)
        with page.expect_download(timeout=10000) as download:
            page.locator("#download-csv").click()
        with Path(download.value.path()).open(encoding="utf-8-sig", newline="") as file:
            etf_rows = list(csv.reader(file))
        assert etf_rows[0][0] == "交易日" and len(etf_rows) > 2
        assert len(etf_rows[0]) == len(etf_rows[-1])
        page.locator("#index-kpis .kpi").first.wait_for(state="visible", timeout=15000)
        assert page.locator("#kpis .kpi").count() == 5
        assert page.locator("#index-kpis .kpi").count() == 4
        assert "未复权收盘价" in page.locator("#etf-metrics-context").inner_text()
        assert "全收益口径" in page.locator("#index-total-freshness").inner_text()
        snapshot_id = page.evaluate("activeSnapshotId")
        index_data = page.request.get(
            f"{HOST}/api/snapshot/data/index_prices.json?snapshot_id={quote(snapshot_id)}"
        ).json()
        codes = ("H00821", "H00918", "H00300")
        valid = [row for row in index_data["records"]
                 if all(isinstance(row.get("values", {}).get(code), (int, float))
                        and row["values"][code] > 0 for code in codes)]
        selected_base = page.locator("#benchmark-date").input_value().replace("-", "")
        selected_end = page.locator("#end-date").input_value().replace("-", "")
        base_row = max((row for row in valid if row["tradeDate"] <= selected_base),
                       key=lambda row: row["tradeDate"])
        latest_row = max((row for row in valid if base_row["tradeDate"] <= row["tradeDate"] <= selected_end),
                         key=lambda row: row["tradeDate"])
        expected = [latest_row["values"][code] / base_row["values"][code] - 1 for code in codes]
        expected.append(expected[0] - expected[1])
        displayed = [float(re.search(r"[+-]?\d+(?:\.\d+)?", value).group()) / 100
                     for value in page.locator("#index-kpis .value").all_inner_texts()]
        assert all(abs(actual - value) < 0.000051 for actual, value in zip(displayed, expected))
        assert page.locator("#index-kpis").get_attribute("data-trade-date") == latest_row["tradeDate"]
        if index_data["latestTradeDate"] > latest_row["tradeDate"] and selected_end > latest_row["tradeDate"]:
            assert "不补值" in page.locator("#index-total-freshness").inner_text()
        page.locator("#benchmark-date").fill("2026-03-02")
        page.locator("#benchmark-date").dispatch_event("change")
        page.wait_for_function("document.querySelector('#index-kpis').dataset.baseDate >= '20260301'", timeout=15000)
        assert page.locator("#index-kpis .kpi").count() == 4
        page.locator('[data-strategy="prism"]').click()
        page.locator("#prism-content").wait_for(state="visible", timeout=15000)
        assert page.locator("#etf-metrics").is_hidden()
        assert page.locator("#index-total-panel").is_hidden()
        page.goto(f"{BASE}/fund-flow.html")
        page.locator("#summary .summary-card").first.wait_for(state="visible", timeout=15000)
        assert page.locator("#summary").inner_text().find("当日估算净申赎") >= 0
        assert page.evaluate("document.querySelector('#daily-flow-chart').compareDocumentPosition(document.querySelector('#cumulative-flow-chart')) & Node.DOCUMENT_POSITION_FOLLOWING")
        assert page.evaluate("document.querySelector('#cumulative-flow-chart').compareDocumentPosition(document.querySelector('#shares-chart')) & Node.DOCUMENT_POSITION_FOLLOWING")
        page.locator("#fund-flow-table-toggle").click()
        assert page.locator("#fund-flow-table-region").is_visible()
        page.goto(f"{BASE}/anchor.html")
        page.locator("#anchor-observation strong").first.wait_for(state="visible", timeout=15000)
        assert page.evaluate("document.querySelector('#anchor-observation').compareDocumentPosition(document.querySelector('#chart')) & Node.DOCUMENT_POSITION_FOLLOWING")
        assert "RSI90" in page.locator("#anchor-observation").inner_text()
        assert "最近有效" in page.locator("#anchor-observation").inner_text()
        assert page.locator("#status .status-badge").count() == 1
        page.locator("#anchor-table-toggle").click()
        assert page.locator("#anchor-table-region").is_visible()
        page.goto(f"{BASE}/overview.html")
        page.locator("#overview-content").wait_for(state="visible", timeout=15000)
        assert page.locator("h1").inner_text() == "信息总览"
        assert page.locator(".overview-shortcuts a").count() == 4
        assert page.locator(".sidebar-group-label").filter(has_text="策略看板").evaluate(
            "element => element.nextElementSibling.textContent.trim()"
        ) == "300红利 / 300成长（累计收益率）"
        report = page.request.get(f"{HOST}/api/rotation/overview").json()
        complete = sum(group["quality"] == "完整" for group in report["groups"])
        assert page.locator("#overview-complete").inner_text() == f"{complete} / {len(report['groups'])}"
        assert page.locator("#overview-triggered").inner_text().endswith("组")
        assert page.locator('#overview-filter').is_visible()
        assert page.locator('[aria-current="page"]').count() == 1
        page.locator("#overview-filter").select_option("quality")
        issue_count = len(report["groups"]) - complete
        assert page.locator("#overview-rows tr").count() == max(issue_count, 1)
        if not issue_count:
            assert "该筛选下无组合" in page.locator("#overview-rows").inner_text()
        page.locator("#event-period").select_option("5")
        recent_events = sum(len(group["events"]) for group in report["groups"])
        assert page.locator("#overview-events li").count() == max(recent_events, 1)
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.locator("#overview-mobile-list").is_visible()
        assert page.locator(".overview-mobile-item").count() == issue_count
        if issue_count:
            page.locator(".overview-mobile-item summary").first.click()
            assert page.locator(".overview-mobile-item details").first.get_attribute("open") is not None
        else:
            assert "该筛选下无组合" in page.locator("#overview-mobile-list").inner_text()
        assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        page.locator(".mobile-nav-toggle").click()
        assert page.locator(".sidebar-feature").is_visible()
        browser.close()
    print("Prism range/benchmark/CSV, ETF CSV, fund-flow and anchor tables, overview data/filter/mobile/navigation: PASS")


if __name__ == "__main__":
    main()
