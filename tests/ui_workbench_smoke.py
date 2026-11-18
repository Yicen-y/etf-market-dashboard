"""Read-only local layout smoke at the four supported viewport widths."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


PAGES = (
    "overview.html", "data-center.html", "index.html?strategy=prism",
    "fund-flow.html", "anchor.html", "dividend-research.html",
    "dividend.html?type=STOCK", "settings.html",
)
WIDTHS = (375, 768, 1024, 1440)


def main():
    base = os.environ.get("ETF_TEST_URL", "http://127.0.0.1:8010")
    out = Path(os.environ.get("ETF_TEST_EVIDENCE_DIR") or "docs/engineering-v2/evidence/workbench")
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True,
        )
        for width in WIDTHS:
            for route in PAGES:
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                response = page.goto(f"{base}/web/{route}", wait_until="domcontentloaded", timeout=20000)
                if route == "overview.html":
                    page.locator("#overview-content").wait_for(state="visible", timeout=15000)
                elif route == "index.html?strategy=prism":
                    page.locator("#prism-content").wait_for(state="visible", timeout=15000)
                else:
                    page.wait_for_timeout(900)
                if page.locator(".data-summary").count():
                    page.wait_for_function(
                        "!document.querySelector('.data-summary').textContent.includes('正在核对')",
                        timeout=12000,
                    )
                result = {
                    "route": route, "width": width, "http": response.status,
                    "heading": page.locator("h1").first.inner_text() if page.locator("h1").count() else "",
                    "overflow": page.evaluate("document.documentElement.scrollWidth > window.innerWidth"),
                    "errors": errors[:2],
                }
                results.append(result)
                if width in (375, 1440) and route in ("overview.html", "index.html?strategy=prism", "fund-flow.html", "dividend.html?type=STOCK"):
                    name = route.split("?")[0].removesuffix(".html")
                    page.screenshot(path=str(out / f"{name}-{width}.png"), full_page=False)
                page.close()
        browser.close()
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = [item for item in results if item["http"] != 200 or not item["heading"] or item["overflow"] or item["errors"]]
    print(f"Checked {len(results)} page/viewport pairs; failures={len(failures)}")
    for item in failures:
        print(item)
    assert not failures


if __name__ == "__main__":
    main()
