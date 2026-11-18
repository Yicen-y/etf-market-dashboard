"""Compare the same chart with the full payload and the projected payload."""

import json
import os
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import closing
from pathlib import Path


def main():
    root_dir = Path(__file__).resolve().parents[1]
    source = root_dir / "data"
    manifest = json.loads((source / "current_manifest.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="etf-a03-browser-") as temporary:
        root = Path(temporary)
        (root / "current_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for relative in manifest["files"].values():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
        with closing(sqlite3.connect((source / "etf_market.db").as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(root / "etf_market.db")) as copy:
                original.backup(copy)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        env = {**os.environ, "ETF_DATA_DIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen([sys.executable, "-B", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
                                   cwd=root_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=flags)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(base + "/api/live", timeout=1).close()
                    break
                except Exception:
                    if process.poll() is not None:
                        raise RuntimeError("isolated server exited")
                    time.sleep(.1)
            else:
                raise RuntimeError("isolated server did not start")
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                browser = playwright.chromium.launch(executable_path=str(chrome) if chrome.exists() else None, headless=True)
                results = {"full": [], "projected": []}
                for mode in ("full", "projected"):
                    for _ in range(5):
                        page = browser.new_page(viewport={"width": 1440, "height": 900})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        if mode == "full":
                            def serve_full(route):
                                replacement = route.fetch(url=base + "/api/snapshot/data/index_prices.json?snapshot_id=" + manifest["snapshot_id"])
                                route.fulfill(response=replacement)
                            page.route("**/api/snapshot/index-view?**", serve_full)
                        started = time.perf_counter()
                        page.goto(base + "/web/index.html?strategy=prism", wait_until="domcontentloaded", timeout=30000)
                        page.locator("#prism-observation strong").first.wait_for(state="visible", timeout=30000)
                        page.wait_for_function("document.querySelector('#prism-freshness')?.textContent.includes('数据截至')", timeout=30000)
                        elapsed = (time.perf_counter() - started) * 1000
                        if errors:
                            raise RuntimeError(errors)
                        results[mode].append(elapsed)
                        page.close()
                for mode, values in results.items():
                    print(json.dumps({"mode": mode, "n": len(values), "page_ready_p50_ms": round(statistics.median(values), 2),
                                      "page_ready_samples_ms": [round(value, 2) for value in values]}, ensure_ascii=False))
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                requests = []
                page.on("request", lambda request: requests.append(request.url) if "/api/snapshot/index-view" in request.url else None)
                page.goto(base + "/web/index.html?strategy=prism")
                page.locator("#prism-observation strong").first.wait_for(state="visible", timeout=30000)
                page.locator('[data-strategy="dividend-hs300"]').click()
                page.wait_for_function("document.querySelector('#page-title')?.textContent.includes('沪深300')", timeout=30000)
                page.locator('[data-strategy="prism"]').click()
                page.wait_for_function("document.querySelector('#page-title')?.textContent.includes('成长100R')", timeout=30000)
                if len(requests) != 2:
                    raise RuntimeError(f"repeated index requests: {requests}")
                print(json.dumps({"strategy_switch_requests": len(requests), "switch_sequence": "prism -> dividend-hs300 -> prism"}, ensure_ascii=False))
                page.close()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(base + "/web/index.html")
                page.wait_for_function("document.querySelector('#index-total-freshness')?.textContent.includes('指数截至')", timeout=30000)
                print(json.dumps({"etf_composite_chart_ready": True}, ensure_ascii=False))
                page.close()
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
