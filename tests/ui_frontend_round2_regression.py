"""Isolated browser and API checks for the targeted frontend performance changes."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from bench_frontend_round2 import CHROME, EVIDENCE, ROOT, copy_data, wait_server


def api(base, code):
    query = urllib.parse.urlencode({"index_code": code, "ma_window": 1250,
                                    "base_date": "20200101", "upper_pct": .15,
                                    "lower_pct": .15})
    with urllib.request.urlopen(f"{base}/api/anchor/metrics?{query}", timeout=30) as response:
        return json.load(response)


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="etf-front-regression-") as temporary:
        data = Path(temporary)
        manifest = copy_data(data)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env={**os.environ, "ETF_DATA_DIR": str(data), "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            wait_server(base, process)
            combined = api(base, "all")
            api_parity = {}
            for code in ("H20903", "H00922"):
                single = api(base, code)
                assert single["snapshot_id"] == combined["snapshot_id"] == manifest["snapshot_id"]
                assert single["indexes"][code] == combined["indexes"][code]
                api_parity[code] = {"rows": len(single["indexes"][code]["rows"]),
                                    "first": single["indexes"][code]["rows"][0]["tradeDate"],
                                    "last": single["indexes"][code]["rows"][-1]["tradeDate"]}
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(CHROME), headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900})
                page = context.new_page()
                errors = []
                requests = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("response", lambda response: requests.append(response.url)
                        if "/api/anchor/metrics?" in response.url else None)
                page.goto(base + "/web/anchor.html", wait_until="domcontentloaded")
                page.wait_for_function("echarts.getInstanceByDom(document.querySelector('#chart'))?.getOption()?.series?.length>0")
                assert len(requests) == 1 and "index_code=H20903" in requests[-1]
                page.locator("#range").select_option("all")
                assert len(requests) == 1
                initial = page.evaluate("""() => {
                  const o=echarts.getInstanceByDom(document.querySelector('#chart')).getOption();
                  return {rows:o.series[0].data.length, start:o.dataZoom[0].startValue, end:o.dataZoom[0].endValue};
                }""")
                assert initial["rows"] == api_parity["H20903"]["rows"]
                page.locator('[data-view="H00922"]').click()
                page.wait_for_function("document.querySelector('#chart') && echarts.getInstanceByDom(document.querySelector('#chart'))?.getOption()?.title?.[0]?.text?.includes('中证红利')")
                assert len(requests) == 2 and "index_code=H00922" in requests[-1]
                dividend_rows = page.evaluate("echarts.getInstanceByDom(document.querySelector('#chart')).getOption().series[0].data.length")
                assert dividend_rows == api_parity["H00922"]["rows"]
                page.locator('[data-view="all"]').click()
                page.wait_for_function("echarts.getInstanceByDom(document.querySelector('#chart'))?.getOption()?.title?.[0]?.text?.includes('双指数')")
                assert len(requests) == 3 and "index_code=all" in requests[-1]
                assert not errors, errors
                result = {"snapshot_id": manifest["snapshot_id"], "api_parity": api_parity,
                          "browser_requests": [url.split("/api/", 1)[1] for url in requests],
                          "all_range_chart": initial, "dividend_chart_rows": dividend_rows,
                          "errors": errors}
                context.close()
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
    output = EVIDENCE / "round2_regression.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(output), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
