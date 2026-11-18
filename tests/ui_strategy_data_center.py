"""Real isolated snapshot: data center shows each strategy's effective date."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    base = os.environ.get("ETF_TEST_URL", "http://127.0.0.1:8017")
    out = Path(os.environ.get("ETF_TEST_EVIDENCE_DIR") or
               Path(__file__).resolve().parents[1] / "docs" / "engineering-v2" / "evidence")
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        browser = playwright.chromium.launch(executable_path=str(chrome) if chrome.exists() else None,
                                             headless=True)
        expected_prism = next(row["calculation_date"] for row in
                              browser.new_page().request.get(base + "/api/data-center").json()["strategy_calculations"]
                              if row["id"] == "prism")
        for width in (1440, 390):
            page = browser.new_page(viewport={"width": width, "height": 900}, locale="zh-CN")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            response = page.goto(base + "/web/data-center.html", wait_until="networkidle")
            page.locator("#dc-message").filter(has_text="诊断已读取").wait_for()
            rows = page.locator("#dc-strategy-dates tr")
            assert response.status == 200 and rows.count() == 9
            assert expected_prism in rows.first.inner_text()
            assert all("一致" in rows.nth(i).inner_text() for i in range(9))
            assert page.locator("#dc-series tr").count() == 26
            assert not errors
            page.locator("#dc-strategy-dates").scroll_into_view_if_needed()
            page.screenshot(path=str(out / f"strategy-dates-{width}.png"), full_page=True)
            results.append({"width": width, "rows": 9, "series": 26,
                            "first_row": rows.first.inner_text(), "errors": errors})
            page.close()
        browser.close()
    (out / "strategy-dates-ui.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    print("STRATEGY_DATA_CENTER_UI_PASS", len(results))


if __name__ == "__main__":
    main()
