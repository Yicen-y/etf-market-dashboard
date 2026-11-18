"""Repeatable, read-only UI evidence on an isolated snapshot copy."""

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import closing
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE = ROOT / "docs" / "engineering_audit" / "evidence"


def isolated_data(target):
    source = ROOT / "data"
    manifest = json.loads((source / "current_manifest.json").read_text(encoding="utf-8"))
    (target / "current_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative in manifest["files"].values():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
    with closing(sqlite3.connect((source / "etf_market.db").as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(target / "etf_market.db")) as copy:
            original.backup(copy)
    return manifest


def run(phase):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    results = {"phase": phase, "environment": {"viewport": "1440x900", "browser": "Chrome headless", "snapshot_copy": True}, "pages": {}, "interactions": {}}
    with tempfile.TemporaryDirectory(prefix="etf-ui-a07-a09-") as temporary:
        data = Path(temporary)
        manifest = isolated_data(data)
        results["environment"]["snapshot_id"] = manifest["snapshot_id"]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env={**os.environ, "ETF_DATA_DIR": str(data), "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
        )
        try:
            for _ in range(150):
                try:
                    urllib.request.urlopen(base + "/api/live", timeout=1).close()
                    break
                except Exception:
                    if process.poll() is not None:
                        raise RuntimeError("isolated server exited")
                    time.sleep(.1)
            else:
                raise RuntimeError("isolated server did not start")
            with sync_playwright() as playwright:
                chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                browser = playwright.chromium.launch(executable_path=str(chrome) if chrome.exists() else None, headless=True)
                paths = [
                    ("etf", "index.html", "#index-kpis .kpi", "#main-chart"),
                    ("prism", "index.html?strategy=prism", "#prism-observation strong", "#prism-main-chart"),
                    ("configured", "index.html?strategy=dividend-hs300", "#prism-observation strong", "#prism-main-chart"),
                    ("overview", "overview.html", "#overview-content", None),
                    ("flow", "fund-flow.html", "#summary .summary-card", "#daily-flow-chart"),
                    ("anchor", "anchor.html", "#anchor-observation strong", "#chart"),
                    ("bond", "bond-value.html", "#bond-chart-price", "#bond-chart-price"),
                    ("data", "data-center.html", "h1", None),
                    ("settings", "settings.html", "h1", None),
                ]
                for label, path, ready, chart in paths:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.add_init_script("window.__layoutShifts=[];new PerformanceObserver(list=>list.getEntries().forEach(e=>{if(!e.hadRecentInput)window.__layoutShifts.push(e.value)})).observe({type:'layout-shift',buffered:true})")
                    cdp = page.context.new_cdp_session(page)
                    cdp.send("Performance.enable")
                    errors, requests = [], []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("response", lambda response: requests.append({"url": response.url.replace(base, ""), "status": response.status, "bytes": len(response.body())}) if "/api/" in response.url and response.request.method == "GET" else None)
                    start = time.perf_counter()
                    page.goto(f"{base}/web/{path}", wait_until="domcontentloaded", timeout=45000)
                    page.locator(ready).first.wait_for(state="visible", timeout=45000)
                    if label == "etf":
                        page.wait_for_function("document.querySelector('#index-kpis')?.dataset.tradeDate", timeout=45000)
                    page.wait_for_timeout(150)
                    ready_ms = round((time.perf_counter() - start) * 1000, 1)
                    option = page.evaluate("id => {const e=document.querySelector(id);const c=e&&window.echarts?.getInstanceByDom(e);if(!c)return null;const o=c.getOption();return {series:o.series?.map(s=>({name:s.name,type:s.type,yAxisIndex:s.yAxisIndex||0})), yAxis:o.yAxis?.map(a=>({name:a.name||'',formatter:String(a.axisLabel?.formatter||'')})),legend:o.legend?.map(l=>({type:l.type,selected:l.selected}))}}", chart) if chart else None
                    composite = None
                    if label == "etf":
                        composite = page.evaluate("() => {const main=echarts.getInstanceByDom(document.querySelector('#main-chart')).getOption();const index=echarts.getInstanceByDom(document.querySelector('#index-total-chart')).getOption();const sample=main.tooltip[0].formatter([{axisValueLabel:'2026-11-17',seriesName:'红利−成长差值（pp）',value:0.2,marker:''},{axisValueLabel:'2026-11-17',seriesName:'建信沪深300红利ETF',value:0.1,marker:''}]);return {main_axis:main.yAxis[0].name,index_axis:index.yAxis[0].name,main_bar_count:main.series.filter(s=>s.type==='bar').length,index_bar_count:index.series.filter(s=>s.type==='bar').length,tooltip_sample:sample}}")
                        page.locator("#main-chart").screenshot(path=str(EVIDENCE / f"{phase}_etf_chart.png"))
                        page.locator("#index-total-chart").screenshot(path=str(EVIDENCE / f"{phase}_index_chart.png"))
                    timings = page.evaluate("() => ({api:performance.getEntriesByType('resource').filter(e=>e.name.includes('/api/')).map(e=>({url:new URL(e.name).pathname,duration_ms:Math.round(e.duration*10)/10,response_end_ms:Math.round(e.responseEnd*10)/10,transfer_size:e.transferSize})),paint:performance.getEntriesByType('paint').map(e=>({name:e.name,ms:Math.round(e.startTime*10)/10})),layout_shift:window.__layoutShifts.reduce((a,b)=>a+b,0)})")
                    cpu = {item["name"]: round(item["value"] * 1000, 1) for item in cdp.send("Performance.getMetrics")["metrics"] if item["name"] in ("ScriptDuration", "LayoutDuration", "RecalcStyleDuration", "TaskDuration")}
                    page.screenshot(path=str(EVIDENCE / f"{phase}_{label}_desktop.png"), full_page=False)
                    results["pages"][label] = {"title": page.title(), "heading": page.locator("h1").first.inner_text(), "ready_ms": ready_ms, "api": requests, "page_errors": errors, "chart": option, "composite": composite, "timings": timings, "cpu_ms": cpu, "horizontal_overflow": page.evaluate("document.documentElement.scrollWidth > innerWidth")}
                    page.close()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(f"{base}/web/index.html?strategy=prism", wait_until="domcontentloaded")
                page.locator("#prism-observation strong").first.wait_for(state="visible")
                start = time.perf_counter()
                page.locator('[data-strategy="dividend-hs300"]').click()
                page.wait_for_function("document.querySelector('#page-title')?.textContent.includes('沪深300')")
                results["interactions"]["strategy_switch_ms"] = round((time.perf_counter() - start) * 1000, 1)
                start = time.perf_counter()
                page.locator("#end-date").fill("2026-08-31")
                page.locator("#end-date").dispatch_event("change")
                page.wait_for_function("() => {const c=echarts.getInstanceByDom(document.querySelector('#prism-main-chart'));const d=c?.getOption()?.xAxis?.[0]?.data;return d?.length && String(d.at(-1)).replaceAll('-','') <= '20260831'}")
                results["interactions"]["date_filter_ms"] = round((time.perf_counter() - start) * 1000, 1)
                page.locator('[data-strategy="prism"]').click()
                page.wait_for_function("document.querySelector('#page-title')?.textContent.includes('成长100R')")
                page.locator('[data-prism-range="1y"]').click()
                results["interactions"]["range_label"] = page.locator("#prism-view-range").inner_text()
                page.close()
                page = browser.new_page(viewport={"width": 375, "height": 812})
                page.goto(f"{base}/web/index.html", wait_until="domcontentloaded")
                page.locator("#index-kpis .kpi").first.wait_for(state="visible")
                page.screenshot(path=str(EVIDENCE / f"{phase}_etf_mobile.png"), full_page=False)
                results["pages"]["etf_mobile"] = {"horizontal_overflow": page.evaluate("document.documentElement.scrollWidth > innerWidth")}
                page.close()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                conflict = {"injected": 0, "index_requests": 0, "manifest_requests": 0}
                def on_index_view(route):
                    conflict["index_requests"] += 1
                    if conflict["injected"] == 0:
                        conflict["injected"] += 1
                        route.fulfill(status=409, content_type="application/json", body='{"detail":"snapshot expired"}')
                    else:
                        route.continue_()
                def on_manifest(route):
                    conflict["manifest_requests"] += 1
                    route.continue_()
                page.route("**/api/snapshot/index-view?**", on_index_view)
                page.route("**/api/snapshot", on_manifest)
                page.goto(f"{base}/web/index.html?strategy=prism", wait_until="domcontentloaded")
                page.wait_for_function("document.querySelector('#prism-observation strong') || document.querySelector('#message')?.dataset.state === 'error'", timeout=30000)
                conflict["ready"] = page.locator("#prism-observation strong").count() > 0
                conflict["message"] = page.locator("#message").inner_text()
                conflict["message_visible"] = page.locator("#message").is_visible()
                page.screenshot(path=str(EVIDENCE / f"{phase}_409.png"), full_page=False)
                results["interactions"]["http_409_once"] = conflict
                page.close()
                from scripts.storage import publish_snapshot
                old_id = manifest["snapshot_id"]
                next_id = "ui-a07-a09-isolated-switch"
                etf_payload = json.loads((data / manifest["files"]["etf"]).read_text(encoding="utf-8"))
                index_payload = json.loads((data / manifest["files"]["index"]).read_text(encoding="utf-8"))
                etf_payload["snapshot_id"] = next_id
                index_payload["snapshot_id"] = next_id
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                switch_responses = []
                page.on("response", lambda response: switch_responses.append((response.status, response.url.replace(base, ""))) if "/api/snapshot/" in response.url else None)
                page.goto(f"{base}/web/index.html?strategy=prism", wait_until="domcontentloaded")
                page.locator("#prism-observation strong").first.wait_for(state="visible")
                publish_snapshot(data, next_id, etf_payload, index_payload)
                page.locator('[data-strategy="dividend-hs300"]').click()
                try:
                    page.wait_for_function("id => activeSnapshotId===id && indexDataset?.snapshot_id===id && document.querySelector('#page-title')?.textContent.includes('沪深300')", arg=next_id, timeout=30000)
                    switched = True
                except PlaywrightTimeoutError:
                    switched = False
                results["interactions"]["real_version_switch"] = {"old_id": old_id, "new_id": next_id, "ready": switched, "statuses": switch_responses, "active_id": page.evaluate("activeSnapshotId"), "data_id": page.evaluate("indexDataset?.snapshot_id"), "message": page.locator("#message").inner_text()}
                page.screenshot(path=str(EVIDENCE / f"{phase}_version_switch.png"), full_page=False)
                page.close()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                failures = {"requests": 0}
                def always_conflict(route):
                    failures["requests"] += 1
                    route.fulfill(status=409, content_type="application/json", body='{"detail":"snapshot expired"}')
                page.route("**/api/snapshot/index-view?**", always_conflict)
                page.goto(f"{base}/web/index.html?strategy=prism", wait_until="domcontentloaded")
                page.wait_for_function("document.querySelector('#message')?.dataset.state === 'error'", timeout=30000)
                failures["error_visible"] = page.locator("#message").is_visible()
                failures["message"] = page.locator("#message").inner_text()
                results["interactions"]["http_409_persistent"] = failures
                page.close()
                browser.close()
            smoke = subprocess.run([sys.executable, "tests/ui_workbench_interactions.py"], cwd=ROOT,
                                   env={**os.environ, "ETF_TEST_URL": base, "PYTHONDONTWRITEBYTECODE": "1"},
                                   capture_output=True, text=True, timeout=120)
            results["existing_ui_smoke"] = {"exit_code": smoke.returncode, "stdout": smoke.stdout.strip(), "stderr": smoke.stderr[-1500:]}
        finally:
            process.terminate()
            process.wait(timeout=10)
    output = EVIDENCE / f"{phase}_browser_metrics.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": str(output), "pages": {k: v.get("ready_ms") for k, v in results["pages"].items()}, "interactions": results["interactions"]}, ensure_ascii=False))
    if phase in ("after", "round2"):
        assert results["interactions"]["http_409_once"]["ready"]
        assert results["interactions"]["http_409_once"]["index_requests"] == 2
        assert results["interactions"]["real_version_switch"]["ready"]
        assert results["interactions"]["http_409_persistent"]["requests"] == 2
        assert results["interactions"]["http_409_persistent"]["error_visible"]
        assert results["pages"]["etf"]["composite"]["main_axis"] == "% / pp"
        assert results["pages"]["etf"]["composite"]["index_axis"] == "% / pp"
        assert results["pages"]["etf"]["composite"]["main_bar_count"] == 1
        assert results["pages"]["etf"]["composite"]["index_bar_count"] == 1
        assert "+20.00pp" in results["pages"]["etf"]["composite"]["tooltip_sample"]
        assert "+10.00%" in results["pages"]["etf"]["composite"]["tooltip_sample"]
        assert results["existing_ui_smoke"]["exit_code"] == 0, results["existing_ui_smoke"]["stderr"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["before", "after", "round2"])
    run(parser.parse_args().phase)
