"""Read-only browser check for the latest real update job on a local server."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    host = os.environ.get("ETF_TEST_URL", "http://127.0.0.1:8000")
    output = Path(os.environ.get("ETF_TEST_EVIDENCE_DIR", Path(__file__).resolve().parents[1] / "docs" / "engineering-v2" / "evidence"))
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        center = page.request.get(host + "/api/data-center").json()
        job = center["recent_jobs"][0]
        page.goto(host + "/web/job-detail.html?job=" + job["job_id"], wait_until="networkidle")
        page.locator("#job-detail-summary dd").first.wait_for()
        summary = page.locator("#job-detail-summary").inner_text()
        assert job["job_id"] in summary
        assert job["snapshot_id"] in summary
        message = page.locator("#job-detail-message").inner_text()
        assert "HTTP 404" not in message, message
        assert page.locator("#job-detail-datasets tr").count() >= 1
        page.screenshot(path=str(output / "latest-job-detail.png"), full_page=True)
        result = {"job_id": job["job_id"], "snapshot_id": job["snapshot_id"],
                  "message": message, "dataset_rows": page.locator("#job-detail-datasets tr").count()}
        (output / "latest-job-detail.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
