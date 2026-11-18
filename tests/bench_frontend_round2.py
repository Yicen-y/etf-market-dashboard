"""Repeatable A07/anchor/fund-flow browser baseline on an isolated snapshot.

Run `python tests/bench_frontend_round2.py before` before edits and `after` after
edits. No update endpoint is called and the source data directory stays read-only.
"""

import argparse
import json
import math
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

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "engineering_audit" / "evidence"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
ANCHOR_PATH = "/web/anchor.html"
FLOW_PATH = "/web/fund-flow.html"


def copy_data(target):
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
    for name in ("jobs.db", "fund_flow.db"):
        path = source / name
        if path.exists():
            shutil.copyfile(path, target / name)
    return manifest


def wait_server(base, process):
    for _ in range(150):
        try:
            urllib.request.urlopen(base + "/api/live", timeout=1).close()
            return
        except Exception:
            if process.poll() is not None:
                raise RuntimeError("isolated server exited before readiness")
            time.sleep(.1)
    raise RuntimeError("isolated server did not start")


def percentile(values, proportion):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * proportion) - 1)], 2)


def summary(samples, key):
    values = [sample[key] for sample in samples if sample.get(key) is not None]
    return {"n": len(values), "p50": round(statistics.median(values), 2), "p95": percentile(values, .95), "samples": [round(v, 2) for v in values]} if values else None


INIT_JS = """(() => {
  window.__round2 = {longTasks:[],shifts:[],anchor:{setOption:[],renders:[],parse:[],body:[]}};
  new PerformanceObserver(list=>list.getEntries().forEach(e=>window.__round2.longTasks.push({start:e.startTime,duration:e.duration}))).observe({type:'longtask',buffered:true});
  new PerformanceObserver(list=>list.getEntries().forEach(e=>{
    if(e.hadRecentInput)return;
    window.__round2.shifts.push({value:e.value,start:e.startTime,sources:(e.sources||[]).map(s=>({node:s.node?{tag:s.node.tagName,id:s.node.id,className:String(s.node.className).slice(0,100)}:null,previous:s.previousRect,current:s.currentRect}))});
  })).observe({type:'layout-shift',buffered:true});
})();"""


def instrument_anchor(route):
    response = route.fetch()
    body = response.text().replace("\r\n", "\n")
    original = body
    marker = "(() => {"
    injected = """(() => {
  const probe = window.__round2.anchor;
  const originalInit = echarts.init.bind(echarts);
  echarts.init = (...args) => {
    const instance = originalInit(...args);
    const originalSetOption = instance.setOption.bind(instance);
    instance.setOption = (...options) => {
      const start = performance.now();
      const result = originalSetOption(...options);
      const end=performance.now();probe.setOption.push({id:instance.getDom().id,start,end,ms:end-start});
      return result;
    };
    return instance;
  };
"""
    body = body.replace(marker, injected, 1)
    marker = "function render() {"
    body = body.replace(marker, "function render() { const round2RenderStart=performance.now();", 1)
    marker = "    const rows = data.indexes[codes[0]].rows;"
    body = body.replace(marker, "    const round2SeriesStart=performance.now();\n" + marker, 1)
    marker = "    let end = $('end').value.replaceAll('-','') || dates[dates.length - 1];"
    body = body.replace(marker, "    probe.seriesMs=performance.now()-round2SeriesStart;\n" + marker, 1)
    marker = "    chart.setOption({title:titles,graphic,tooltip:"
    body = body.replace(marker, "    probe.configMs=performance.now()-round2SeriesStart-probe.seriesMs;\n" + marker, 1)
    marker = "    if (!$('anchor-table-region').hidden) renderDataTable();\n  }"
    body = body.replace(marker, "    if (!$('anchor-table-region').hidden) renderDataTable();\n    const done=performance.now(); probe.renders.push({end:done,ms:done-round2RenderStart,seriesMs:probe.seriesMs,configMs:probe.configMs});\n    requestAnimationFrame(()=>requestAnimationFrame(()=>{probe.readyAt=performance.now()}));\n  }", 1)
    marker = "      const result = await response.json();"
    body = body.replace(marker, "      const bodyStart=performance.now(); const raw=await response.text(); probe.body.push(performance.now()-bodyStart);\n      const parseStart=performance.now(); const result=JSON.parse(raw); probe.parse.push(performance.now()-parseStart);", 1)
    for required in ("const probe = window.__round2.anchor", "round2RenderStart", "probe.seriesMs=", "probe.configMs=", "probe.renders.push", "probe.parse.push"):
        if required not in body:
            raise RuntimeError("anchor instrumentation marker missing: " + required)
    if body == original:
        raise RuntimeError("anchor instrumentation made no change")
    route.fulfill(response=response, body=body)


def capture_resources(page):
    return page.evaluate("""() => ({
      resources:performance.getEntriesByType('resource').filter(e=>e.name.includes('/api/')).map(e=>({url:new URL(e.name).pathname+new URL(e.name).search,duration_ms:e.duration,response_end_ms:e.responseEnd,transfer_size:e.transferSize})),
      heap_bytes:performance.memory?.usedJSHeapSize??null,
      shifts:window.__round2.shifts,
      long_tasks:window.__round2.longTasks
    })""")


def attach_network(page, collector):
    def received(response):
        if "/api/" in response.url and response.request.method == "GET":
            collector.append({"url": response.url.split("/api/", 1)[1], "status": response.status, "bytes": len(response.body())})
    page.on("response", received)


def anchor_visit(page, base, phase, kind, iteration, trace=False):
    requests, errors = [], []
    attach_network(page, requests)
    page.on("pageerror", lambda error: errors.append(str(error)))
    started = time.perf_counter()
    page.goto(base + ANCHOR_PATH, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_function("window.__round2?.anchor?.readyAt>0 && document.querySelector('#anchor-observation strong')", timeout=45000)
    ready_ms = (time.perf_counter() - started) * 1000
    evidence = capture_resources(page)
    probe = page.evaluate("window.__round2.anchor")
    chart = page.evaluate("""() => {const e=document.querySelector('#chart');const c=echarts.getInstanceByDom(e);const o=c.getOption();return {instance:c.id,series:o.series.map(s=>({name:s.name,length:s.data?.length})),zoom:o.dataZoom.map(z=>({startValue:z.startValue,endValue:z.endValue}))}}""")
    if trace:
        page.screenshot(path=str(EVIDENCE / f"{phase}_anchor_{kind}.png"), full_page=False)
    active_render=probe["renders"][-1] if probe["renders"] else None
    active_sets=[x for x in probe["setOption"] if active_render and active_render["end"]-active_render["ms"]<=x["start"]<=x["end"]<=active_render["end"]]
    return {"ready_ms":ready_ms,"requests":requests,"errors":errors,"resources":evidence["resources"],"heap_bytes":evidence["heap_bytes"],"long_tasks":evidence["long_tasks"],"layout_shifts":evidence["shifts"],"parse_ms":probe["parse"][-1] if probe["parse"] else None,"body_read_ms":probe["body"][-1] if probe["body"] else None,"render_ms":active_render["ms"] if active_render else None,"series_ms":active_render["seriesMs"] if active_render else None,"config_ms":active_render["configMs"] if active_render else None,"set_option_ms":sum(x["ms"] for x in active_sets),"chart_set_option_ms":sum(x["ms"] for x in active_sets if x["id"]=="chart"),"set_option_calls":active_sets,"chart":chart}


def anchor_filter(page):
    before_count = len(page.evaluate("window.__round2.anchor.renders"))
    before_chart = page.evaluate("echarts.getInstanceByDom(document.querySelector('#chart')).id")
    started = time.perf_counter()
    page.locator("#range").select_option("5")
    page.wait_for_function("count => window.__round2.anchor.renders.length>count && window.__round2.anchor.readyAt>=window.__round2.anchor.renders.at(-1).end", arg=before_count)
    elapsed = (time.perf_counter()-started)*1000
    probe = page.evaluate("window.__round2.anchor")
    chart = page.evaluate("""() => {const c=echarts.getInstanceByDom(document.querySelector('#chart'));const o=c.getOption();return {id:c.id,series_length:o.series[0].data.length,zoom:o.dataZoom.map(z=>({startValue:z.startValue,endValue:z.endValue}))}}""")
    resources = capture_resources(page)["resources"]
    return {"elapsed_ms":elapsed,"render_ms":probe["renders"][-1]["ms"],"chart_same_instance":before_chart==chart["id"],"chart":chart,"api_requests":len(resources)}


def rects(page):
    return page.evaluate("""() => Object.fromEntries(['#universe','#summary','#etf-cards','.fund-flow-focus','.fund-flow-primary-chart','#daily-flow-chart'].map(s=>{const e=document.querySelector(s),r=e.getBoundingClientRect();return [s,{x:r.x,y:r.y,width:r.width,height:r.height}]}))""")


def flow_visit(page, base, phase, kind, viewport, trace=False):
    requests, errors = [], []
    attach_network(page, requests)
    page.on("pageerror", lambda error: errors.append(str(error)))
    started=time.perf_counter()
    page.goto(base+FLOW_PATH,wait_until="domcontentloaded",timeout=45000)
    before=rects(page)
    if trace:
        page.screenshot(path=str(EVIDENCE / f"{phase}_flow_{kind}_{viewport}.png"),full_page=False)
    page.locator("#summary .summary-card").first.wait_for(state="visible",timeout=45000)
    page.wait_for_function("echarts.getInstanceByDom(document.querySelector('#daily-flow-chart'))?.getOption()?.series?.length>0")
    page.evaluate("() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
    elapsed=(time.perf_counter()-started)*1000
    after=rects(page)
    evidence=capture_resources(page)
    if trace:
        page.screenshot(path=str(EVIDENCE / f"{phase}_flow_ready_{viewport}.png"),full_page=False)
    return {"ready_ms":elapsed,"requests":requests,"errors":errors,"resources":evidence["resources"],"heap_bytes":evidence["heap_bytes"],"long_tasks":evidence["long_tasks"],"shifts":evidence["shifts"],"cls":sum(x["value"] for x in evidence["shifts"]),"before_rects":before,"after_rects":after,"overflow":page.evaluate("document.documentElement.scrollWidth>innerWidth")}


def quick_page(browser, base, path, ready):
    context=browser.new_context(viewport={"width":1440,"height":900})
    page=context.new_page();requests=[];attach_network(page,requests)
    page.goto(base+path,wait_until="domcontentloaded",timeout=45000)
    page.locator(ready).first.wait_for(state="visible",timeout=45000)
    page.wait_for_timeout(150)
    result={"path":path,"requests":requests,"errors":[]}
    context.close()
    return result


def compare_anchor_api(base):
    from urllib.parse import urlencode
    rows=[]
    for _ in range(5):
        for code in ("all","H20903"):
            url=base+"/api/anchor/metrics?"+urlencode({"index_code":code,"ma_window":1250,"base_date":"20200101","upper_pct":.15,"lower_pct":.15})
            start=time.perf_counter()
            with urllib.request.urlopen(url,timeout=30) as response:
                body=response.read()
            rows.append({"code":code,"duration_ms":(time.perf_counter()-start)*1000,"bytes":len(body)})
    return rows


def race_probe(browser,base,path,selector,new_value,expected):
    context=browser.new_context(viewport={"width":1440,"height":900})
    context.add_init_script("""(() => {
      const original=window.fetch.bind(window);let count=0;window.__raceEvents=[];
      window.fetch=(input,init)=>{const url=String(input),pending=original(input,init);
        if(!url.includes('/api/anchor/metrics')&&!url.includes('/api/fund-flow/overview'))return pending;
        const call=++count;
        return pending.then(response=>new Promise(resolve=>{
          setTimeout(()=>{window.__raceEvents.push({call,url,at:performance.now()});resolve(response)},call===1?3000:0)
        })).catch(error=>{window.__raceEvents.push({call,url,at:performance.now(),error:error.name});throw error});
      };
    })();""")
    page=context.new_page()
    page.goto(base+path,wait_until="domcontentloaded",timeout=45000)
    page.locator(selector).select_option(new_value)
    page.wait_for_function("window.__raceEvents?.length>=2",timeout=30000)
    page.wait_for_timeout(150)
    observed=page.evaluate("""() => ({
      selected:document.querySelector('#window')?.value||document.querySelector('#preset')?.value,
      chart_title:document.querySelector('#chart')?echarts.getInstanceByDom(document.querySelector('#chart')).getOption().title?.[0]?.text:null,
      card_count:document.querySelectorAll('#etf-cards .etf-card').length,
      events:window.__raceEvents
    })""")
    observed["expected"]=expected
    observed["stale_result"]=(expected not in (observed["chart_title"] or "")) if "anchor" in path else observed["card_count"]!=expected
    context.close()
    return observed


def run(phase):
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    result={"phase":phase,"environment":{},"anchor":{"cold":[],"hot":[],"filter":[]},"flow":{"desktop":[],"narrow":[],"hot":[],"zoom125":[]},"request_chains":[],"api_comparison":[],"races":{}}
    with tempfile.TemporaryDirectory(prefix="etf-front-perf-") as temporary:
        data=Path(temporary)
        manifest=copy_data(data)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        base=f"http://127.0.0.1:{port}"
        flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
        process=subprocess.Popen([sys.executable,"-B","-m","uvicorn","server:app","--host","127.0.0.1","--port",str(port)],cwd=ROOT,env={**os.environ,"ETF_DATA_DIR":str(data),"PYTHONDONTWRITEBYTECODE":"1"},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
        try:
            wait_server(base,process)
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(executable_path=str(CHROME),headless=True)
                result["environment"]={"snapshot_id":manifest["snapshot_id"],"chrome":browser.version,"python":sys.version.split()[0],"viewport":"1440x900","cold":"new browser context; one warmed server process","hot":"new page in same context and HTTP cache","data_copy":True}
                for iteration in range(5):
                    context=browser.new_context(viewport={"width":1440,"height":900})
                    context.add_init_script(INIT_JS)
                    context.route("**/web/anchor.js?**",instrument_anchor)
                    if iteration==0:context.tracing.start(screenshots=True,snapshots=True,sources=True)
                    page=context.new_page()
                    cold=anchor_visit(page,base,phase,"cold",iteration,trace=iteration==0)
                    result["anchor"]["cold"].append(cold)
                    if iteration==0:context.tracing.stop(path=str(EVIDENCE/f"{phase}_anchor_trace.zip"))
                    page.close();page=context.new_page()
                    hot=anchor_visit(page,base,phase,"hot",iteration,trace=iteration==0)
                    result["anchor"]["hot"].append(hot)
                    result["anchor"]["filter"].append(anchor_filter(page))
                    context.close()
                    print(f"{phase} anchor {iteration+1}/5",flush=True)
                for width,kind in ((1440,"desktop"),(1100,"narrow")):
                    for iteration in range(5):
                        context=browser.new_context(viewport={"width":width,"height":900})
                        context.add_init_script(INIT_JS)
                        if iteration==0 and kind=="desktop":context.tracing.start(screenshots=True,snapshots=True,sources=True)
                        page=context.new_page()
                        cold=flow_visit(page,base,phase,"cold",width,trace=iteration==0)
                        result["flow"][kind].append(cold)
                        if iteration==0 and kind=="desktop":context.tracing.stop(path=str(EVIDENCE/f"{phase}_flow_trace.zip"))
                        if kind=="desktop":
                            page.close();page=context.new_page()
                            result["flow"]["hot"].append(flow_visit(page,base,phase,"hot",width))
                        context.close()
                    print(f"{phase} flow {kind} 5/5",flush=True)
                # A 1152 CSS-pixel viewport at 1.25 device scale reproduces a
                # 1440-pixel physical window at 125% scaling before first paint.
                # Changing CSS zoom on DOMContentLoaded creates a test-induced CLS.
                for iteration in range(5):
                    context=browser.new_context(viewport={"width":1152,"height":720},device_scale_factor=1.25)
                    context.add_init_script(INIT_JS)
                    page=context.new_page()
                    result["flow"]["zoom125"].append(flow_visit(page,base,phase,"scaled",1152))
                    context.close()
                for path,ready in (("/web/index.html?strategy=prism","#prism-observation strong"),("/web/index.html?strategy=dividend-hs300","#prism-observation strong"),("/web/index.html?strategy=growth-value-300","#prism-observation strong"),("/web/fund-flow.html","#summary .summary-card")):
                    result["request_chains"].append(quick_page(browser,base,path,ready))
                result["races"]["anchor"]=race_probe(browser,base,ANCHOR_PATH,"#window","1000","1000")
                result["races"]["flow"]=race_probe(browser,base,FLOW_PATH,"#preset","all_six",6)
                browser.close()
            result["api_comparison"]=compare_anchor_api(base)
        finally:
            process.terminate();process.wait(timeout=10)
    result["summary"]={"anchor_cold_ready":summary(result["anchor"]["cold"],"ready_ms"),"anchor_hot_ready":summary(result["anchor"]["hot"],"ready_ms"),"anchor_cold_parse":summary(result["anchor"]["cold"],"parse_ms"),"anchor_cold_render":summary(result["anchor"]["cold"],"render_ms"),"anchor_cold_set_option":summary(result["anchor"]["cold"],"set_option_ms"),"anchor_chart_set_option":summary(result["anchor"]["cold"],"chart_set_option_ms"),"anchor_filter":summary(result["anchor"]["filter"],"elapsed_ms"),"flow_desktop_cls":summary(result["flow"]["desktop"],"cls"),"flow_narrow_cls":summary(result["flow"]["narrow"],"cls")}
    for kind in ("cold","hot"):
        result["summary"][f"anchor_{kind}_api"] = summary([{"duration":max(x["duration_ms"] for x in sample["resources"] if "/api/anchor/metrics" in x["url"])} for sample in result["anchor"][kind]],"duration")
    for code in ("all","H20903"):
        result["summary"][f"direct_{code}_api"]=summary([x for x in result["api_comparison"] if x["code"]==code],"duration_ms")
    output=EVIDENCE/f"{phase}_frontend_round2.json"
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"file":str(output),"summary":result["summary"]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("phase",choices=("before","after"));run(parser.parse_args().phase)
