"""Offline Chromium smoke test for data center. Run against a local server."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("ETF_TEST_EVIDENCE_DIR", ROOT / "docs" / "engineering-v2" / "evidence"))
FIXTURE = {
    "generated_at": "2026-11-13T12:00:00+08:00",
    "current_snapshot_id": "fixture-v2",
    "last_fetch_at": "2026-11-12T18:00:00+08:00",
    "prepared_releases": 0,
    "summary": {"published": 1, "total": 2},
    "datasets": [
        {"id": "etf_prices", "name": "ETF 日收盘", "latest_trade_date": "20261112",
         "expected_trade_date": "20261112", "freshness_status": "CURRENT", "using_previous_release": False,
         "fetch_status": "FETCH_OK", "validation_status": "STRUCTURE_PASS",
         "publication_status": "PUBLISHED", "snapshot_id": "fixture-v2",
         "source_verification": "UNKNOWN", "affected_dashboards": ["主看板"], "open_issue_count": 0},
        {"id": "index_prices", "name": "指数日点位", "latest_trade_date": "20261111",
         "expected_trade_date": "20261112", "freshness_status": "UNKNOWN", "using_previous_release": False,
         "fetch_status": "CANDIDATE_BLOCKED", "validation_status": "FAILED",
         "publication_status": "FAILED", "snapshot_id": None,
         "source_verification": "UNKNOWN", "affected_dashboards": ["三棱镜"], "open_issue_count": 1},
    ],
    "series_summary": {"total": 3, "normal": 2, "stale": 0, "fetch_failed": 1, "anomaly": 0},
    "series": [
        {"id":"index:H00300","code":"H00300","name":"沪深300","type":"index",
         "primary_source":"ETFirst","actual_source":"PROVENANCE_UNKNOWN","last_valid_date":"20261111",
         "fetch_status":"FAILED","fetch_error":{"error_type":"HTTP_403"},"quality_status":"ANOMALY",
         "operational_status":"FETCH_FAILED","verification_coverage":0.98,"open_issue_count":1,
         "previous_release_available":True,"affected_dashboards":["三棱镜"]},
        {"id":"index:H00821","code":"H00821","name":"沪深300红利","type":"index",
         "primary_source":"ETFirst","actual_source":"PROVENANCE_UNKNOWN","last_valid_date":"20261112",
         "fetch_status":"RECORDED","quality_status":"PASS","operational_status":"NORMAL",
         "verification_coverage":1,"open_issue_count":0,"previous_release_available":True},
        {"id":"etf:512530","code":"512530","name":"红利ETF","type":"etf",
         "primary_source":"ETFirst","actual_source":"ETFirst","last_valid_date":"20261112",
         "fetch_status":"RECORDED","quality_status":"UNKNOWN","operational_status":"NORMAL",
         "verification_coverage":None,"open_issue_count":0}],
    "index_anomalies":[{"index_code":"H00300","trade_date":"20261110","quality_status":"VENDOR_DISAGREEMENT",
                        "local_close":6112.80,"official_close":6112.80,"vendor_close":6112.81}],
    "versions":[{"snapshot_id":"fixture-v2","status":"published","published_at":"2026-11-12T18:00:00+08:00"}],
    "provider_diagnostics":[{"index_code":"H00300","upstream":"CSI","endpoint":"index-perf",
                             "error_type":"HTTP_403","observed_at":"2026-11-13T00:00:00Z"}],
    "last_daily_verification":{"through":"20261113","indexes":{
        "H00300":{"status":"REFERENCE_UNAVAILABLE"},"H00821":{"status":"CHECKED"}},
        "publication":{"status":"WITHHELD"}},
    "snapshot_database_consistency":"MATCH","storage_bytes":{"database":1024,"releases":2048,"backups":0},
    "recent_issues": [], "recent_jobs": [{"job_id":"a"*32,"trigger":"manual","state":"PARTIAL",
        "stage":"PUBLISHED_WITH_PARTIAL_FAILURE","fetch_status":"FETCH_OK",
        "validation_status":"VERIFIED","publication_status":"PUBLISHED",
        "started_at":"2026-11-15T15:19:23Z","finished_at":"2026-11-15T15:20:51Z",
        "error":None}],
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    url = os.environ.get("ETF_TEST_URL", "http://127.0.0.1:8765")
    with sync_playwright() as playwright:
        local_chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        browser = playwright.chromium.launch(executable_path=str(local_chrome) if local_chrome.exists() else None, headless=True)
        for width, name in ((1440, "desktop"), (390, "mobile")):
            page = browser.new_page(viewport={"width": width, "height": 900}, locale="zh-CN", timezone_id="Asia/Shanghai")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/api/data-center", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(FIXTURE)))
            page.goto(url + "/web/data-center.html", wait_until="networkidle")
            assert page.get_by_role("heading", name="数据中心").count() == 1
            assert page.locator(".dc-card").count() == 2
            assert page.locator("#dc-series tr").count() == 3
            assert "1 / 2" in page.locator("#dc-daily-summary").inner_text()
            assert "H00300" in page.locator("#dc-daily-failures").inner_text()
            page.locator("#dc-series-status").select_option("FETCH_FAILED")
            assert page.locator("#dc-series tr").count() == 1
            assert "H00300" in page.locator("#dc-series").inner_text()
            page.locator("#dc-series-status").select_option("all")
            page.locator("#dc-series-search").fill("512530")
            assert page.locator("#dc-series tr").count() == 1
            page.locator("#dc-series-search").fill("")
            page.route("**/api/data-center/indexes/H00300?*",lambda route: route.fulfill(
                status=200,content_type="application/json",body=json.dumps({"code":"H00300","status":"AVAILABLE",
                  "rows":[{"trade_date":"20261110","local_close":6112.8,"official_close":6112.8,
                           "vendor_close":6112.81,"quality_status":"VENDOR_DISAGREEMENT",
                           "official_raw_sha256":"a"*64,"vendor_raw_sha256":"b"*64}]})))
            page.locator("#dc-index-anomalies button").first.click()
            assert "6112.81" in page.locator("#dc-index-rows").inner_text()
            page.locator("#dc-index-close").click()
            assert page.locator("#dc-jobs a").count() == 1
            page.locator("#dc-filter").select_option("FAILED")
            assert page.locator(".dc-card").count() == 1
            page.locator("#dc-filter").select_option("all")
            overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            assert not overflow, f"global horizontal overflow at {width}px"
            assert not errors, errors
            page.screenshot(path=str(OUT / f"data-center-{name}.png"), full_page=True)
            page.route("**/api/jobs/" + "a"*32 + "/details",lambda route:route.fulfill(
                status=200,content_type="application/json",body=json.dumps({
                    **FIXTURE["recent_jobs"][0],"snapshot_id":"fixture-v2",
                    "historical_detail_incomplete":True,
                    "datasets":[{"dataset_id":"etf_prices","label":"ETF 行情","state":"PUBLISHED"},
                                {"dataset_id":"index_prices","label":"指数行情","state":"PUBLISHED"},
                                {"dataset_id":"nikkei225_anchor","label":"日经225临时基准（五年之锚）",
                                 "state":"UNKNOWN","provider":"Wind MCP",
                                 "reason_code":"LEGACY_DETAIL_NOT_RECORDED"}]})))
            page.locator("#dc-jobs a").click()
            assert page.get_by_role("heading",name="更新任务详情").count() == 1
            page.locator("#job-detail-datasets").get_by_text("日经225临时基准（五年之锚）").wait_for(timeout=10000)
            assert "日经225临时基准" in page.locator("#job-detail-datasets").inner_text()
            assert "旧任务未保存具体失败原因" in page.locator("#job-detail-datasets").inner_text()
            assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            assert not errors, errors
            page.screenshot(path=str(OUT / f"job-detail-{name}.png"), full_page=True)
            page.close()
        page = browser.new_page(viewport={"width": 390, "height": 900})
        legacy_id = "b" * 32
        page.route(f"**/api/jobs/{legacy_id}/details", lambda route: route.fulfill(
            status=404, content_type="application/json", body='{"detail":"Not Found"}'))
        page.route(f"**/api/jobs/{legacy_id}", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "job_id": legacy_id, "state": "SUCCEEDED", "stage": "PUBLISHED",
                "snapshot_id": "legacy-published-v1", "fetch_status": "FETCH_OK",
                "validation_status": "VERIFIED", "publication_status": "PUBLISHED"})))
        page.goto(url + f"/web/job-detail.html?job={legacy_id}", wait_until="networkidle")
        assert "服务仍运行旧版" in page.locator("#job-detail-message").inner_text()
        assert "legacy-published-v1" in page.locator("#job-detail-summary").inner_text()
        assert page.locator("#job-detail-datasets tr").count() == 1
        page.screenshot(path=str(OUT / "job-detail-legacy-fallback.png"), full_page=True)
        page.close()
        page = browser.new_page(viewport={"width": 390, "height": 900})
        attempts = {"count": 0}
        def fail_then_succeed(route):
            attempts["count"] += 1
            if attempts["count"] == 1:
                route.fulfill(status=503, content_type="application/json", body='{"detail":"unavailable"}')
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({**FIXTURE, "datasets": []}))
        page.route("**/api/data-center", fail_then_succeed)
        page.goto(url + "/web/data-center.html", wait_until="networkidle")
        assert "读取失败" in page.locator("#dc-message").inner_text()
        page.locator("#dc-retry").click()
        page.wait_for_function("document.querySelector('#dc-datasets').textContent.includes('没有数据集')")
        assert "没有数据集" in page.locator("#dc-datasets").inner_text()
        page.close()
        page = browser.new_page(viewport={"width": 390, "height": 900})
        status_fixture = {**FIXTURE, "datasets": [
            {**FIXTURE["datasets"][0], "freshness_status": "STALE", "using_previous_release": True},
            FIXTURE["datasets"][1]]}
        page.route("**/api/data-center", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(status_fixture)))
        page.goto(url + "/tests/fixtures/navigation-status.html?strategy=dividend-growth", wait_until="networkidle")
        assert "沿用旧版" in page.locator(".data-summary").inner_text()
        assert "dataset-etf_prices" in page.locator(".data-summary a").get_attribute("href")
        page.evaluate("history.replaceState(null,'','?strategy=prism');window.dispatchEvent(new Event('dashboard:strategy-changed'))")
        page.wait_for_function("document.querySelector('.data-summary').textContent.includes('指数日点位')")
        assert "失败" in page.locator(".data-summary").inner_text()
        page.close()
        browser.close()
    print("T15 data center desktop/mobile, error/retry/empty: PASS; screenshots in", OUT)


if __name__ == "__main__":
    main()
