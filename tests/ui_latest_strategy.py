"""Read-only browser acceptance for a partial index release."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    base = os.environ.get("ETF_TEST_URL", "http://127.0.0.1:8016")
    out = Path(os.environ.get("ETF_TEST_EVIDENCE_DIR") or Path(__file__).resolve().parents[1] / "docs" / "engineering-v2" / "evidence")
    out.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as playwright:
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        browser = playwright.chromium.launch(executable_path=str(chrome) if chrome.exists() else None,headless=True)
        request = browser.new_page().request
        snapshot = request.get(base + "/api/snapshot").json()["snapshot_id"]
        cutoffs = {row["id"]: row["calculation_date"] for row in
                   request.get(base + "/api/data-center").json()["strategy_calculations"]}
        results = {}
        for strategy in ("prism", "dividend-hs300"):
            raw_cutoff = cutoffs[strategy]
            cutoff = f"{raw_cutoff[:4]}-{raw_cutoff[4:6]}-{raw_cutoff[6:]}"
            page = browser.new_page(viewport={"width":1440,"height":900})
            errors = []
            page.on("pageerror",lambda error:errors.append(str(error)))
            page.goto(base + f"/web/index.html?strategy={strategy}",wait_until="networkidle")
            page.wait_for_function("document.querySelector('#prism-freshness')?.textContent.includes('快照')")
            freshness = page.locator("#prism-freshness").inner_text()
            last_day = page.locator("#prism-table tbody tr").last.locator("td").first.inner_text()
            print(strategy, freshness, last_day)
            assert cutoff in freshness and cutoff == last_day
            assert snapshot in freshness
            assert page.locator("#prism-main-chart canvas").count() > 0
            assert not errors
            page.screenshot(path=str(out / f"latest-strategy-{strategy}.png"))
            results[strategy] = {"cutoff":cutoff,"snapshot_id":snapshot,"last_table_day":last_day,"page_errors":errors}
            page.close()
        browser.close()
    (out / "latest-strategy-ui.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print("LATEST_STRATEGY_UI_PASS",snapshot)


if __name__ == "__main__":
    main()
