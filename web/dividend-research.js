(()=>{
  "use strict";
  const $=id=>document.getElementById(id), charts={};
  for(const id of ["yield-chart","reg-chart","reg-z-chart","ah-chart","ah-ratio-chart"]) charts[id]=echarts.init($(id));
  const state={yieldRows:[],ahRows:[],latestYield:null,regression:null};
  const n=(v,d=2)=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toFixed(d);
  const pct=(v,d=2)=>v==null||!Number.isFinite(Number(v))?"—":`${(Number(v)*100).toFixed(d)}%`;
  const pp=(v,d=2)=>v==null||!Number.isFinite(Number(v))?"—":`${Number(v).toFixed(d)} pp`;
  const iso=day=>day?`${day.slice(0,4)}-${day.slice(4,6)}-${day.slice(6,8)}`:"—";
  const esc=x=>String(x??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  async function json(url,options){const response=await fetch(url,options);let body={};try{body=await response.json()}catch{}if(!response.ok&&response.status!==207)throw new Error(body.detail?.message||body.detail||response.statusText);return body}
  function csvDownload(name,headers,rows){const quote=v=>`"${String(v??"").replaceAll('"','""')}"`;const content="\ufeff"+[headers.map(quote).join(","),...rows.map(row=>row.map(quote).join(","))].join("\r\n");const link=document.createElement("a");link.href=URL.createObjectURL(new Blob([content],{type:"text/csv;charset=utf-8"}));link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000)}
  function dateQuery(){const s=$("research-start").value.replaceAll("-","");const e=$("research-end").value.replaceAll("-","");return `${s?`&start=${s}`:""}${e?`&end=${e}`:""}`}
  function inRange(day){const start=$("research-start").value.replaceAll("-","");const end=$("research-end").value.replaceAll("-","");return (!start||day>=start)&&(!end||day<=end)}
  function statusText(el,text,kind=""){el.textContent=text;el.dataset.state=kind}
  function renderYield(data){
    const rows=data.rows.filter(row=>inRange(row.tradeDate));state.yieldRows=rows;state.latestYield=data.latest;
    const valid=rows.filter(row=>row.dividendYield2Pct!=null).map(row=>row.dividendYield2Pct);
    $("yield-kpi-avg").textContent=valid.length?`${n(valid.reduce((a,b)=>a+b,0)/valid.length)}%`:"—";
    $("yield-kpi-max").textContent=valid.length?`${n(Math.max(...valid))}%`:"—";
    $("yield-kpi-min").textContent=valid.length?`${n(Math.min(...valid))}%`:"—";
    const latest=[...rows].reverse().find(row=>row.yieldPercentile!=null);$("yield-kpi-pct").textContent=latest?`${n(latest.yieldPercentile)}%`:"历史不足";
    const c=data.coverage||{};$("yield-coverage").textContent=`区间 ${rows[0]?iso(rows[0].tradeDate):"无记录"} 至 ${rows.at(-1)?iso(rows.at(-1).tradeDate):"无记录"} · 股息率2 ${c.yieldCount||0} 条（${c.yieldStart?iso(c.yieldStart):"—"} 至 ${c.yieldEnd?iso(c.yieldEnd):"—"}）· 中债10Y ${c.bondCount||0} 条 · 同日配对 ${rows.filter(r=>r.spreadPp!=null).length} 条 · 分位窗口按股息率观测日计算`;
    charts["yield-chart"].setOption({animation:false,tooltip:{trigger:"axis"},legend:{bottom:0},grid:{left:65,right:65,top:25,bottom:70},xAxis:{type:"category",data:rows.map(r=>iso(r.tradeDate)),axisLabel:{hideOverlap:true}},yAxis:[{type:"value",name:"收益率（%）",axisLabel:{formatter:v=>`${v}%`}},{type:"value",name:"利差（pp）",axisLabel:{formatter:v=>`${v} pp`}}],dataZoom:[{type:"inside"},{type:"slider",bottom:28}],series:[{name:"中证红利股息率2",type:"line",color:"#c9362b",showSymbol:false,connectNulls:false,data:rows.map(r=>r.dividendYield2Pct),yAxisIndex:0,lineStyle:{color:"#c9362b",width:2}},{name:"中债国债收益率曲线10Y",type:"line",color:"#2c6bed",showSymbol:false,connectNulls:false,data:rows.map(r=>r.cn10yPct),yAxisIndex:0,lineStyle:{color:"#2c6bed",width:2}},{name:"股息率利差（pp）",type:"line",color:"#16834a",showSymbol:false,connectNulls:false,data:rows.map(r=>r.spreadPp),yAxisIndex:1,lineStyle:{color:"#16834a",width:2}}]},true);
    $("yield-table").querySelector("tbody").innerHTML=rows.slice().reverse().map(r=>`<tr><td>${iso(r.tradeDate)}</td><td>${n(r.dividendYield2Pct)}%</td><td>${n(r.cn10yPct)}%</td><td>${pp(r.spreadPp)}</td><td>${r.yieldPercentile==null?"—":`${n(r.yieldPercentile)}% (${r.sampleCount}样本)`}</td><td>${esc(r.qualityStatus)}</td></tr>`).join("");
    const sy=data.sources?.yield,sb=data.sources?.bond;$("yield-source").textContent=`来源：股息率 ${sy?.upstream||"未采集"}（${sy?.source_url||sy?.sourceUrl||"Wind MCP"}）；10Y ${sb?.upstream||"未采集"}（${sb?.source_url||sb?.sourceUrl||"Wind EDB"}）。当前研究数据统一使用 Wind MCP，历史值与口径以 Wind 返回字段为准。`;
    if(!rows.length)$("yield-source").textContent+=" 当前筛选区间无已保存记录。";
  }
  function renderRegression(r){
    state.regression=r;const rows=r.rows||[];const fitRows=rows.filter(row=>row.trend!=null);
    $("reg-meta").textContent=`模式：${r.mode==="fixed_asof"?"全样本事后拟合":"扩展窗口点时拟合"} · 拟合区间 ${r.fitStartDate||"—"} 至 ${r.fitEndDate||rows.at(-1)?.tradeDate||"—"} · n=${r.sampleCount||fitRows.length} · 年化趋势 ${(100*(r.annualizedGrowth||0)).toFixed(2)}% · 残差标准差 ${r.residualStd==null?"—":n(r.residualStd*100,3)+"%"}`;
    const labels=rows.map(row=>iso(row.tradeDate));
    charts["reg-chart"].setOption({animation:false,tooltip:{trigger:"axis"},legend:{bottom:0},grid:{left:75,right:30,top:25,bottom:65},xAxis:{type:"category",data:labels,axisLabel:{hideOverlap:true}},yAxis:{type:"log",name:"指数点位（对数轴）"},dataZoom:[{type:"inside"},{type:"slider",bottom:28}],series:[{name:"H00922全收益点位",type:"line",showSymbol:false,data:rows.map(x=>x.close),lineStyle:{color:"#2c6bed",width:2}},{name:"回归趋势",type:"line",showSymbol:false,data:rows.map(x=>x.trend),lineStyle:{color:"#f0aa27",width:2}},{name:`上轨（+${r.sigma||$("sigma").value}σ）`,type:"line",showSymbol:false,data:rows.map(x=>x.upper),lineStyle:{color:"#c9362b",type:"dashed"}},{name:`下轨（−${r.sigma||$("sigma").value}σ）`,type:"line",showSymbol:false,data:rows.map(x=>x.lower),lineStyle:{color:"#16834a",type:"dashed"}}]},true);
    charts["reg-z-chart"].setOption({animation:false,tooltip:{trigger:"axis"},legend:{bottom:0},grid:{left:65,right:25,top:20,bottom:60},xAxis:{type:"category",data:labels,axisLabel:{hideOverlap:true}},yAxis:{type:"value",name:"Z值"},dataZoom:[{type:"inside"}],series:[{name:"回归Z值",type:"line",showSymbol:false,data:rows.map(x=>x.z),lineStyle:{color:"#8953bd",width:2}},{name:"+1.5σ研究参考",type:"line",showSymbol:false,data:rows.map(()=>1.5),lineStyle:{color:"#94a3b8",type:"dashed"}},{name:"−1.5σ研究参考",type:"line",showSymbol:false,data:rows.map(()=>-1.5),lineStyle:{color:"#94a3b8",type:"dashed"}}]},true);
    $("reg-z-explanation").textContent="Z 值表示指数点位相对回归趋势的偏离，单位为对数残差标准差。0 表示位于趋势线上；正值在上方，负值在下方；±1.5 虚线是研究参考位置，并非涨跌幅或买卖信号。"+(r.mode==="fixed_asof"?"当前全样本模式使用截至观察日的数据事后拟合，历史 Z 值不能视为当时可见的信号。":"扩展窗口模式逐日仅用当时及此前的数据拟合；仍不能单凭 Z 值作交易决策。");
    $("reg-source").textContent=`快照 ${r.snapshotId||"—"} · ${r.qualityStatus} · ${r.warning||""}`;
  }
  function renderAh(a){
    let rows=a.rows||[];state.ahRows=rows;const latest=[...rows].reverse().find(x=>x.aClose!=null&&x.hClose!=null);
    $("ah-kpi-date").textContent=latest?iso(latest.tradeDate):"—";$("ah-kpi-spread").textContent=latest?pp(latest.spread40Pp):"预热不足";
    const coverage=a.coverage||{};$("ah-kpi-quality").textContent=`${coverage.ready40Rows||0} / ${coverage.commonRows||0}`;
    $("ah-state").textContent=`${a.qualityStatus} · 共同有效点 ${coverage.commonRows||0} · 可计算D40 ${coverage.ready40Rows||0} · ${a.warning||a.message||""}`;
    const selected=rows.filter(r=>inRange(r.tradeDate));const labels=selected.map(r=>iso(r.tradeDate));
    charts["ah-chart"].setOption({animation:false,tooltip:{trigger:"axis"},legend:{bottom:0},grid:{left:68,right:72,top:25,bottom:65},xAxis:{type:"category",data:labels,axisLabel:{hideOverlap:true}},yAxis:[{type:"value",name:"归一化全收益（起点=100）"},{type:"value",name:"收益差（pp）",axisLabel:{formatter:v=>`${v} pp`}}],dataZoom:[{type:"inside"},{type:"slider",bottom:28}],series:[{name:"中证红利全收益 H00922",type:"line",showSymbol:false,data:selected.map(r=>r.aNormalized),lineStyle:{color:"#c9362b",width:2}},{name:"港股通高股息人民币全收益 H20915",type:"line",showSymbol:false,data:selected.map(r=>r.hNormalized),lineStyle:{color:"#16834a",width:2}},{name:"A−H 40共同日收益差（pp）",type:"bar",yAxisIndex:1,data:selected.map(r=>r.spread40Pp),barMaxWidth:5,itemStyle:{color:p=>p.value>=0?"#c9362b":"#16834a"}}]},true);
    charts["ah-ratio-chart"].setOption({animation:false,tooltip:{trigger:"axis"},legend:{bottom:0},grid:{left:65,right:30,top:20,bottom:60},xAxis:{type:"category",data:labels,axisLabel:{hideOverlap:true}},yAxis:{type:"value",name:"相对比值"},dataZoom:[{type:"inside"}],series:[{name:"H00922 / H20915 相对比值",type:"line",showSymbol:false,data:selected.map(r=>r.ratio),lineStyle:{color:"#2c6bed",width:2}},{name:"242日均线",type:"line",showSymbol:false,data:selected.map(r=>r.ratioMa242),lineStyle:{color:"#e67e32",type:"dashed"}},{name:"242日布林上轨（+2σ）",type:"line",showSymbol:false,data:selected.map(r=>r.ratioUpper242),lineStyle:{color:"#94a3b8",type:"dotted"}},{name:"242日布林下轨（−2σ）",type:"line",showSymbol:false,data:selected.map(r=>r.ratioLower242),lineStyle:{color:"#94a3b8",type:"dotted"}}]},true);
    $("ah-table").querySelector("tbody").innerHTML=selected.slice().reverse().slice(0,500).map(r=>`<tr><td>${iso(r.tradeDate)}</td><td>${n(r.aNormalized)}</td><td>${n(r.hNormalized)}</td><td>${pct(r.aReturn40)}</td><td>${pct(r.hReturn40)}</td><td>${pp(r.spread40Pp)}</td><td>${esc(r.quality)}</td></tr>`).join("");
    $("ah-source").textContent="来源：项目指数事实库；H00922/H20915均按中证全收益人民币序列。共同日使用两端实际记录日期交集，不使用插值或前值填充。无独立港股指数交易日历时，无法判断单边缺行属于源缺数还是休市，故保留UNVERIFIED_SOURCE状态。理论指数比较，不是可交易ETF回测。";
  }
  function renderAhBacktest(data){
    const names={buy_hold_a:"始终持有中证红利 H00922",buy_hold_h:"始终持有港股通高股息 H20915",daily_rebalanced_50_50:"固定50:50（每日再平衡）",d40_momentum_switch:"D40相对动量切换（研究基准）"};
    const rows=data.summary||[];
    $("ah-backtest-table").querySelector("tbody").innerHTML=rows.map(row=>`<tr><td>${names[row.strategy]||esc(row.strategy)}</td><td>${n(row.finalValue,4)}</td><td>${pct(row.totalReturn)}</td><td>${pct(row.maxDrawdown)}</td><td>${n(row.oneWayTurnover,4)}</td><td>${n(row.estimatedTradingCost,5)}</td></tr>`).join("");
    const switchRow=rows.find(row=>row.strategy==="d40_momentum_switch");
    $("ah-backtest-state").textContent=`${data.qualityStatus||""} · ${iso(data.startDate)} 至 ${iso(data.endDate)} · ${data.observationCount||0}个共同观测点 · ${switchRow?.firstSignalDate?`首信号 ${iso(switchRow.firstSignalDate)}，次共同观测日执行 ${iso(switchRow.firstExecutionDate)}`:"尚无可用D40信号"} · ${data.dataWarning||""}`;
  }
  async function loadAhBacktest(){
    const cost=Number($("ah-cost-bps").value||0), query=dateQuery().replace(/^&/,"");
    const url=`/api/research/dividend-ah-backtest?${query}${query?"&":""}lookback=40&cost_bps=${encodeURIComponent(cost)}`;
    const data=await json(url);renderAhBacktest(data);
  }
  async function loadRegression(){
    const r=await json(`/api/research/dividend-regression?mode=${$("mode").value}&fit_start=${$("fit-start").value.replaceAll("-","")}&sigma=${$("sigma").value}`);
    renderRegression(r);
    return r;
  }
  function reloadRegression(){loadRegression().catch(error=>statusText($("research-status"),`回归数据加载失败：${error.message}`,"error"))}
  async function loadAll(){
    statusText($("research-status"),"读取本地数据库和指数快照……","loading");
    try{const [y,a,r]=await Promise.all([json(`/api/research/dividend-yield?window=5y${dateQuery()}`),json("/api/research/dividend-ah"),loadRegression(),loadAhBacktest()]);
      renderYield(y);renderAh(a);
      const yDate=y.latest?.yieldDate||"无官方股息率记录",bondDate=y.latest?.cn10yDate||"无中债10Y记录";
      statusText($("research-status"),`估值数据：${y.qualityStatus}${y.qualityStatus==="MISSING_OFFICIAL"?"（暂无官方股息率记录）":""}（股息率日期 ${yDate}；国债日期 ${bondDate}） · A/H：${a.qualityStatus}${a.qualityStatus==="MISSING_SERIES"?"（H20915尚无本地历史）":""} · 指数回归：${r.qualityStatus}${r.sourceProvider?`（${r.sourceProvider}点位）`:"（来源待核验）"}`,y.qualityStatus==="READY"&&a.qualityStatus==="READY"?"normal":"incomplete");
    }catch(error){statusText($("research-status"),`数据加载失败：${error.message}`,"error")}
  }
  async function refresh(){const button=$("yield-refresh"),out=$("research-refresh-state");button.disabled=true;out.textContent="正在访问官方来源……";try{const result=await json(`/api/research/refresh?${dateQuery().replace(/^&/,"")}`,{method:"POST"});out.textContent=`${result.status} · 股息率新增 ${result.inserted?.CSI_DIV_YIELD2_000922??0} 条 · 国债新增 ${result.inserted?.CCDC_CN10Y??0} 条`;await loadAll()}catch(error){out.textContent=`刷新失败：${error.message}`}finally{button.disabled=false}}
  $("yield-refresh").addEventListener("click",refresh);$("ah-backtest").addEventListener("click",loadAhBacktest);$("reg-load").addEventListener("click",reloadRegression);$("mode").addEventListener("change",reloadRegression);$("sigma").addEventListener("change",reloadRegression);$("fit-start").addEventListener("change",reloadRegression);
  $("yield-range").addEventListener("change",()=>{const end=new Date();const months={"1m":1,"3m":3,"6m":6,"1y":12,"5y":60};const value=$("yield-range").value;if(months[value]){const start=new Date(end);start.setMonth(start.getMonth()-months[value]);$("research-start").value=start.toISOString().slice(0,10);$("research-end").value=end.toISOString().slice(0,10)}else if(value==="all"){$("research-start").value="";$("research-end").value=""}loadAll()});
  $("research-start").addEventListener("change",loadAll);$("research-end").addEventListener("change",loadAll);
  $("yield-export").addEventListener("click",()=>csvDownload("dividend-yield2-cn10y.csv",["tradeDate","dividendYield2Pct","cn10yPct","spreadPp","yieldPercentile","qualityStatus"],state.yieldRows.map(r=>[r.tradeDate,r.dividendYield2Pct,r.cn10yPct,r.spreadPp,r.yieldPercentile,r.qualityStatus])));
  $("ah-export").addEventListener("click",()=>csvDownload("dividend-ah40.csv",["tradeDate","aNormalized","hNormalized","aReturn40","hReturn40","spread40Pp","ratio","ratioMa242","ratioUpper242","ratioLower242","quality"],state.ahRows.map(r=>[r.tradeDate,r.aNormalized,r.hNormalized,r.aReturn40,r.hReturn40,r.spread40Pp,r.ratio,r.ratioMa242,r.ratioUpper242,r.ratioLower242,r.quality])));
  window.addEventListener("resize",()=>Object.values(charts).forEach(c=>c.resize()));
  loadAll();
})();
