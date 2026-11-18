"""Inspect a real isolated data center with an archived simulated 403 event."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


URL = os.environ.get("ETF_TEST_URL", "http://127.0.0.1:8768")
OUT = Path(os.environ["ETF_TEST_EVIDENCE_DIR"])


def main():
    results = []
    with sync_playwright() as playwright:
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        browser = playwright.chromium.launch(executable_path=str(chrome) if chrome.exists() else None,
                                             headless=True)
        for width in (1440, 390):
            page = browser.new_page(viewport={"width": width, "height": 900}, locale="zh-CN")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            response = page.goto(URL + "/web/data-center.html", wait_until="networkidle")
            page.locator("#dc-message").filter(has_text="诊断已读取").wait_for()
            row = page.locator("#dc-series tr").filter(has_text="H00918")
            assert response.status == 200
            assert row.count() == 1
            assert "HTTP 403" in row.inner_text()
            assert "20261116" in row.inner_text()
            assert "H00918 HTTP 403" in page.locator("#dc-daily-failures").inner_text()
            assert page.locator("#dc-strategy-dates tr").count() == 9
            assert not errors
            screenshot = OUT / f"data-center-403-{width}.png"
            page.screenshot(path=str(screenshot), full_page=True)
            results.append({"width": width, "http_status": response.status,
                            "h00918": row.inner_text(), "strategy_rows": 9,
                            "page_errors": errors, "screenshot": str(screenshot)})
            page.close()
        browser.close()
    (OUT / "data-center-403-ui.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")
    print("DATA_CENTER_403_UI_PASS", len(results))


if __name__ == "__main__":
    main()
