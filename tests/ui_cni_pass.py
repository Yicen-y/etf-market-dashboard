"""Browser check for currently published CNI route approvals."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


URL = os.environ.get("ETF_TEST_URL", "http://127.0.0.1:8770")
OUT = Path(os.environ["ETF_TEST_EVIDENCE_DIR"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
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
            for code in ("480080", "480081"):
                page.locator("#dc-series-search").fill(code)
                row = page.locator("#dc-series tr")
                assert row.count() == 1
                detail = row.inner_text()
                assert "PASS" in detail and "20261116" in detail and "双路径点位一致放行" in detail
                row.scroll_into_view_if_needed()
                screenshot = OUT / f"data-center-{code}-{width}.png"
                page.screenshot(path=str(screenshot))
                row_screenshot = OUT / f"data-center-{code}-{width}-row.png"
                row.screenshot(path=str(row_screenshot))
                row.locator("td").nth(7).scroll_into_view_if_needed()
                quality_screenshot = OUT / f"data-center-{code}-{width}-quality.png"
                page.screenshot(path=str(quality_screenshot))
                results.append({"width": width, "code": code, "row": detail,
                                "http_status": response.status, "page_errors": errors,
                                "screenshot": str(screenshot), "row_screenshot": str(row_screenshot),
                                "quality_screenshot": str(quality_screenshot)})
            assert not errors
            page.close()
        browser.close()
    (OUT / "data-center-cni-pass-ui.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
    print("CNI_PASS_UI_OK", len(results))


if __name__ == "__main__":
    main()
