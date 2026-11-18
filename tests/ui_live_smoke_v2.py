"""Local read-only UI smoke; uses current data and is not a fixed-fixture acceptance test."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


PAGES = ("index.html", "overview.html", "fund-flow.html", "dividend.html", "anchor.html",
         "bond-value.html", "dividend-research.html", "data-center.html")
OUT = Path(os.environ.get("ETF_TEST_EVIDENCE_DIR") or
           Path(__file__).resolve().parents[1] / "docs" / "engineering-v2" / "evidence")


def main():
    base = os.environ.get("ETF_TEST_URL", "http://127.0.0.1:8765")
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        browser = playwright.chromium.launch(executable_path=str(chrome) if chrome.exists() else None, headless=True)
        for width in (1440, 390):
            for name in PAGES:
                page = browser.new_page(viewport={"width": width, "height": 900}, locale="zh-CN", timezone_id="Asia/Shanghai")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                response = page.goto(f"{base}/web/{name}", wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1800)
                heading = page.locator("h1").first.inner_text(timeout=5000) if page.locator("h1").count() else ""
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                results.append({"page": name, "width": width, "http": response.status,
                                "heading": heading[:50], "overflow": overflow, "page_errors": errors[:3]})
                page.screenshot(path=str(OUT / f"live-{name[:-5]}-{width}.png"), full_page=True,
                                animations="disabled")
                page.close()
        browser.close()
    (OUT / "live-smoke.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Live local UI smoke: {len(results)} page/viewport pairs; report and screenshots in {OUT}")
    assert all(item["http"] == 200 and item["heading"] and not item["overflow"] and not item["page_errors"]
               for item in results)


if __name__ == "__main__":
    main()
