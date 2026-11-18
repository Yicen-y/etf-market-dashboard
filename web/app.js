const PRODUCTS={"512530":{name:"建信沪深300红利ETF"},"562310":{name:"银华沪深300成长ETF"},"510330":{name:"华夏沪深300ETF"}};
const DATA_URL="/api/snapshot/data/etf_prices.json";
const INDEX_DATA_URL="/api/snapshot/data/index_prices.json";
const INDEX_VIEW_URL="/api/snapshot/index-view";
function showDataStatus(payload){
  const element=document.getElementById("data-status");if(!element||!payload)return;
  const isIndex=!!payload.indexes,day=payload.latestTradeDate;
  window.DashboardStatus.render(element,{
    state:day?"review":"error",
    summary:`${isIndex?"指数":"ETF"}快照截至 ${day||"未知"} · 历史来源待核验`,
    detail:`快照 ${payload.snapshot_id||"未知"}；${isIndex?"指数实际来源见逐条记录":"ETF采集：AkShare；新浪回退需独立校核；未复权价格收益，非总回报"}；快照结构已校验。`
  });
}
const chartTheme=window.DashboardChartTheme,CHART_COLORS=chartTheme.colors;
let dataset,indexDataset,charts={},activeSnapshotId=null;
const etfDatasetLoad={snapshotId:null,promise:null},indexDatasetLoad=new Map();
let loadedIndexStrategy=null;
let indexChartRequest=0;
let snapshotManifestReload=null;
const DEFAULT_BENCHMARK="2025-12-31";
const BENCHMARK_KEYS={"dividend-growth":"etf-dashboard-benchmark","prism":"prism-dashboard-benchmark"};
const isoToKey=x=>x.replaceAll("-","");const keyToIso=x=>`${x.slice(0,4)}-${x.slice(4,6)}-${x.slice(6,8)}`;const currentLocalIsoDate=()=>{const now=new Date(),pad=value=>String(value).padStart(2,"0");return `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())}`};const fmtPct=x=>chartTheme.formatPercent(x);const fmt=x=>x==null?"—":Number(x).toFixed(6);const cls=x=>x>0?"positive":x<0?"negative":"neutral";
async function fetchJson(url,options){const response=await fetch(url,options);if(!response.ok){const error=Error(`无法读取数据（HTTP ${response.status}）：${url}`);error.status=response.status;throw error}return response.json()}
function acceptSnapshotManifest(manifest){
  if(activeSnapshotId!==manifest.snapshot_id){
    activeSnapshotId=manifest.snapshot_id;dataset=null;indexDataset=null;loadedIndexStrategy=null;
    etfDatasetLoad.snapshotId=null;etfDatasetLoad.promise=null;indexDatasetLoad.clear();
    Object.values(charts).forEach(chart=>chart?.clear());
    for(const id of ["kpis","index-kpis","prism-observation","prism-snapshot","strategy-universe"])
      document.getElementById(id)?.replaceChildren();
    for(const id of ["data-status","freshness","index-total-freshness","prism-freshness","etf-metrics-context"]){
      const element=document.getElementById(id);if(element)element.textContent="正在读取当前快照…";
    }
    for(const id of ["data-table","prism-table"])
      document.getElementById(id)?.querySelector("tbody")?.replaceChildren();
    message.textContent="快照已更新，正在重新读取当前版本…";message.dataset.state="loading";message.classList.remove("hidden");
  }
  return manifest.snapshot_id;
}
async function reloadSnapshotManifest(){
  if(!snapshotManifestReload)snapshotManifestReload=fetchJson("/api/snapshot",{cache:"no-store"}).then(acceptSnapshotManifest).finally(()=>{snapshotManifestReload=null});
  return snapshotManifestReload;
}
async function recoverSnapshotConflict(error,strategy,retried){
  if(error.status!==409||retried)throw error;
  await reloadSnapshotManifest();
  return ensureDashboardDataWithRetry(strategy,true);
}
function dashboardNeedsIndex(strategy){return strategy!=="dividend-growth"}
async function ensureDashboardData(strategy){return ensureDashboardDataWithRetry(strategy,false)}
async function ensureDashboardDataWithRetry(strategy,retried){
  const needsIndex=dashboardNeedsIndex(strategy),snapshotId=activeSnapshotId;
  if(!needsIndex){
    if(dataset?.snapshot_id===snapshotId){showDataStatus(dataset);return dataset}
    if(etfDatasetLoad.snapshotId!==snapshotId){
      const request=fetchJson(`${DATA_URL}?snapshot_id=${encodeURIComponent(snapshotId||"legacy")}`);
      etfDatasetLoad.snapshotId=snapshotId;etfDatasetLoad.promise=request;
      request.catch(()=>{if(etfDatasetLoad.promise===request){etfDatasetLoad.snapshotId=null;etfDatasetLoad.promise=null}});
    }
    let result;try{result=await etfDatasetLoad.promise}catch(error){return recoverSnapshotConflict(error,strategy,retried)}
    if(activeSnapshotId!==snapshotId)return ensureDashboardData(strategy);
    dataset=result;showDataStatus(result);return result;
  }
  if(indexDataset?.snapshot_id===snapshotId&&loadedIndexStrategy===strategy){showDataStatus(indexDataset);return indexDataset}
  const key=`${snapshotId}:${strategy}`;
  if(!indexDatasetLoad.has(key)){
    const url=`${INDEX_VIEW_URL}?strategy=${encodeURIComponent(strategy)}&snapshot_id=${encodeURIComponent(snapshotId||"legacy")}`;
    const request=fetchJson(url);
    indexDatasetLoad.set(key,request);
    request.catch(()=>{if(indexDatasetLoad.get(key)===request)indexDatasetLoad.delete(key)});
  }
  let result;try{result=await indexDatasetLoad.get(key)}catch(error){return recoverSnapshotConflict(error,strategy,retried)}
  if(activeSnapshotId!==snapshotId)return ensureDashboardData(strategy);
  if(window.activeDashboard===strategy||(strategy==="etf-index"&&window.activeDashboard==="dividend-growth")){
    indexDataset=result;loadedIndexStrategy=strategy;showDataStatus(result);
  }
  return result;
}
function resolveBenchmarkDate(selected,records){const v=records.map(r=>r.tradeDate).filter(x=>x<=isoToKey(selected));if(!v.length)throw Error("选择日期早于可用数据范围。");return v.at(-1)}
function buildSeries(records,selected,endSelected){const actual=resolveBenchmarkDate(selected,records),end=resolveBenchmarkDate(endSelected,records),base=records.find(r=>r.tradeDate===actual).prices;return{actual,end,rows:records.filter(r=>r.tradeDate>=actual&&r.tradeDate<=end).map(r=>{const returns={};for(const code of Object.keys(PRODUCTS))returns[code]=r.prices[code]==null||base[code]==null?null:r.prices[code]/base[code]-1;const d=returns["512530"],g=returns["562310"];return{...r,returns,difference:d==null||g==null?null:d-g,portfolio5050:d==null||g==null?null:(d+g)/2}})}}
function line(name,data,color,type){const roleColor=color==="#c9362b"?CHART_COLORS.assetA:color==="#16834a"?CHART_COLORS.assetB:color==="#999"?CHART_COLORS.secondary:color;return{name,type:"line",showSymbol:false,connectNulls:false,data,lineStyle:{color:roleColor,width:2,type:type||"solid"},itemStyle:{color:roleColor}}}
function compositeChartBase(dates){
  const option=chartTheme.createBaseChartOption({dates,percentAxis:true,bottom:76});
  option.yAxis.name="% / pp";option.yAxis.nameGap=8;option.yAxis.nameTextStyle={color:"#64748b",fontSize:11};
  return option;
}
async function renderETFIndexChart(){
  const status=document.getElementById("index-total-freshness"),indexKpis=document.getElementById("index-kpis");
  const snapshot=activeSnapshotId,requestId=++indexChartRequest,selectedBase=benchmark.value,selectedEnd=endDate.value;
  indexKpis.replaceChildren();
  status.textContent="正在读取全收益指数数据…";
  try{
    const payload=await ensureDashboardData("etf-index");
    if(snapshot!==activeSnapshotId){
      if(window.activeDashboard==="dividend-growth"){
        await ensureDashboardData("dividend-growth");
        if(window.activeDashboard==="dividend-growth")render();
      }
      return;
    }
    if(requestId!==indexChartRequest||window.activeDashboard!=="dividend-growth"||benchmark.value!==selectedBase||endDate.value!==selectedEnd)return;
    showDataStatus(dataset);
    const codes=["H00821","H00918","H00300"],valid=payload.records.filter(r=>codes.every(code=>Number(r.values?.[code])>0));
    if(!valid.length)throw Error("三条全收益指数没有共同交易日");
    const baseDay=resolveBenchmarkDate(selectedBase,valid),base=valid.find(r=>r.tradeDate===baseDay).values;
    const rows=valid.filter(r=>r.tradeDate>=baseDay&&r.tradeDate<=isoToKey(selectedEnd));
    if(!rows.length)throw Error("所选区间没有共同交易日");
    const returns=code=>rows.map(r=>r.values[code]/base[code]-1);
    const dividend=returns(codes[0]),growth=returns(codes[1]);
    const indexItems=[
      ["沪深300红利全收益 · H00821",dividend.at(-1),fmtPct],
      ["沪深300成长全收益 · H00918",growth.at(-1),fmtPct],
      ["沪深300全收益 · H00300",returns(codes[2]).at(-1),fmtPct],
      ["指数红利−成长差值",dividend.at(-1)-growth.at(-1),chartTheme.formatPercentagePoints]
    ];
    indexKpis.innerHTML=indexItems.map(([label,value,formatter])=>`<div class="kpi"><div class="label">${label}</div><div class="value ${cls(value)}">${formatter(value)}</div></div>`).join("");
    indexKpis.dataset.baseDate=baseDay;
    indexKpis.dataset.tradeDate=rows.at(-1).tradeDate;
    charts.indexTotal.setOption({...compositeChartBase(rows.map(r=>keyToIso(r.tradeDate))),
      tooltip:chartTheme.axisTooltip(name=>name.includes("pp")?chartTheme.formatPercentagePoints:fmtPct),dataZoom:[{type:"inside",filterMode:"none",start:0,end:100}],
      xAxis:{type:"category",data:rows.map(r=>keyToIso(r.tradeDate)),axisLabel:{rotate:45,hideOverlap:true}},
      series:[line("沪深300红利全收益",dividend,CHART_COLORS.assetA),line("沪深300成长全收益",growth,CHART_COLORS.assetB),
        line("沪深300全收益",returns(codes[2]),CHART_COLORS.benchmark),
        {name:"红利−成长收益差（pp）",type:"bar",data:rows.map((_,i)=>dividend[i]-growth[i]),barMaxWidth:8,itemStyle:{color:CHART_COLORS.difference},markLine:{silent:true,symbol:"none",label:{show:false},lineStyle:{color:CHART_COLORS.difference},data:[{yAxis:0}]}}]},true);
    const indexLastDay=rows.at(-1).tradeDate;
    const missingLater=payload.latestTradeDate>indexLastDay&&isoToKey(selectedEnd)>indexLastDay;
    status.textContent=`共同基准日 ${keyToIso(baseDay)} · 指数截至 ${keyToIso(indexLastDay)}${missingLater?" · 此后暂无共同有效点位，不补值":""} · 全收益口径（含分红再投资）；历史来源待核验`;
    charts.indexTotal.resize();
  }catch(error){if(requestId===indexChartRequest&&window.activeDashboard==="dividend-growth"){indexKpis.replaceChildren();charts.indexTotal.clear();status.textContent=`全收益指数数据暂不可用：${error.message}`}}
}
function renderETF(){
  const latest=dataset.latestTradeDate,selectedEnd=endDate.value||currentLocalIsoDate(),actualBase=resolveBenchmarkDate(benchmark.value,dataset.records);endDate.min=keyToIso(actualBase);endDate.max=currentLocalIsoDate();if(!endDate.value)endDate.value=currentLocalIsoDate();if(isoToKey(selectedEnd)<actualBase)endDate.value=keyToIso(actualBase);const s=buildSeries(dataset.records,benchmark.value,endDate.value),last=s.rows.at(-1);
  pageTitle.textContent="300红利与300成长轮动";
  pageSubline.textContent="以选定交易日收盘价为基准，比较红利、成长与沪深300 ETF 的表现。";
  freshness.textContent=`数据截至 ${keyToIso(dataset.latestTradeDate)} · 更新时间 ${dataset.updatedAt||"未记录"}`;
  kpis.classList.remove("hidden");prismContent.classList.add("hidden");document.querySelector(".chart-panel").classList.remove("hidden");dataTable.closest(".panel").classList.remove("hidden");
  const items=[["建信沪深300红利ETF · 512530",last.returns["512530"],fmtPct],["银华沪深300成长ETF · 562310",last.returns["562310"],fmtPct],["华夏沪深300ETF · 510330",last.returns["510330"],fmtPct],["ETF 红利/成长初始各50%买入持有",last.portfolio5050,fmtPct],["ETF 红利−成长差值",last.difference,chartTheme.formatPercentagePoints]];
  document.getElementById("etf-metrics-context").textContent=`共同基准日 ${keyToIso(s.actual)} · ETF 截至 ${keyToIso(last.tradeDate)} · 未复权收盘价累计收益，不含分红再投资`;
  kpis.innerHTML=items.map(([l,v,formatter])=>`<div class="kpi"><div class="label">${l}</div><div class="value ${cls(v)}">${formatter(v)}</div></div>`).join("");
  const rows=s.rows,dates=rows.map(r=>keyToIso(r.tradeDate));
  charts.main.setOption({
    ...compositeChartBase(dates),
    tooltip:chartTheme.axisTooltip(name=>name.includes("pp")?chartTheme.formatPercentagePoints:fmtPct),
    dataZoom:[{type:"inside",filterMode:"none",start:0,end:100}],
    xAxis:{type:"category",data:dates,axisLabel:{rotate:45,hideOverlap:true}},
    series:[
      {name:"红利−成长差值（pp）",type:"bar",data:rows.map(r=>r.difference),barMaxWidth:8,itemStyle:{color:CHART_COLORS.difference},markLine:{silent:true,symbol:"none",label:{show:false},lineStyle:{color:CHART_COLORS.difference},data:[{yAxis:0}]}},
      line("建信沪深300红利ETF",rows.map(r=>r.returns["512530"]),CHART_COLORS.assetA),
      line("银华沪深300成长ETF",rows.map(r=>r.returns["562310"]),CHART_COLORS.assetB),
      line("华夏沪深300ETF",rows.map(r=>r.returns["510330"]),CHART_COLORS.benchmark),
      line("红利/成长初始各50%买入持有",rows.map(r=>r.portfolio5050),CHART_COLORS.portfolio,"dashed")
    ]
  });
  document.getElementById("index-total-panel").classList.remove("hidden");
  renderETFIndexChart();
  dataTable.querySelector("thead").innerHTML="<tr><th>交易日</th><th>红利累计</th><th>成长累计</th><th>沪深300累计</th><th>红利−成长（pp）</th><th>50/50组合</th></tr>";
  dataTable.querySelector("tbody").innerHTML=rows.map(r=>`<tr><td>${keyToIso(r.tradeDate)}</td><td class="${cls(r.returns["512530"])}">${fmtPct(r.returns["512530"])}</td><td class="${cls(r.returns["562310"])}">${fmtPct(r.returns["562310"])}</td><td class="${cls(r.returns["510330"])}">${fmtPct(r.returns["510330"])}</td><td class="${cls(r.difference)}">${chartTheme.formatPercentagePoints(r.difference)}</td><td class="${cls(r.portfolio5050)}">${fmtPct(r.portfolio5050)}</td></tr>`).join("");
}
function renderPrism(){const actual=resolveBenchmarkDate(benchmark.value,indexDataset.records),rows=indexDataset.records.filter(r=>r.tradeDate>=actual),dates=rows.map(r=>keyToIso(r.tradeDate));pageTitle.textContent="成长100R与价值100R轮动三棱镜";pageSubline.textContent="基于成长100R与价值100R原始指数点位，观察比值、趋势差和 RSI 三组信号。";kpis.classList.add("hidden");document.querySelector(".chart-panel").classList.add("hidden");dataTable.closest(".panel").classList.add("hidden");prismContent.classList.remove("hidden");prismFreshness.textContent=`数据截至 ${keyToIso(indexDataset.latestTradeDate)} · 更新时间 ${indexDataset.updatedAt||"未记录"}`;charts.prismMain.setOption({animation:false,tooltip:{trigger:"axis",valueFormatter:fmtPct},legend:{bottom:0},grid:{left:60,right:20,top:25,bottom:60},xAxis:{type:"category",data:dates,axisLabel:{rotate:45}},yAxis:{type:"value",axisLabel:{formatter:fmtPct}},series:[line("40日收益差",rows.map(r=>r.return40Spread),"#c9362b"),line("40日收益差242日均线",rows.map(r=>r.return40Ma242),"#16834a","dashed")]});charts.ratio.setOption({animation:false,tooltip:{trigger:"axis"},legend:{bottom:0},grid:{left:58,right:18,top:20,bottom:48},xAxis:{type:"category",data:dates,axisLabel:{show:false}},yAxis:{type:"value"},series:[line("比值（成长100R/价值100R）",rows.map(r=>r.ratio),"#2c6bed"),line("242日均线",rows.map(r=>r.ratioMa242),"#e67e32","dashed"),line("上轨",rows.map(r=>r.ratioUpper242),"#999","dotted"),line("下轨",rows.map(r=>r.ratioLower242),"#999","dotted")]});charts.spread.setOption({animation:false,tooltip:{trigger:"axis",valueFormatter:fmtPct},legend:{bottom:0},grid:{left:58,right:18,top:20,bottom:48},xAxis:{type:"category",data:dates,axisLabel:{show:false}},yAxis:{type:"value",axisLabel:{formatter:fmtPct}},series:[line("40日收益差",rows.map(r=>r.return40Spread),"#c9362b"),line("242日均线",rows.map(r=>r.return40Ma242),"#16834a","dashed")]});charts.rsi.setOption({animation:false,tooltip:{trigger:"axis"},grid:{left:58,right:18,top:20,bottom:32},xAxis:{type:"category",data:dates,axisLabel:{show:false}},yAxis:{type:"value",min:0,max:100},series:[line("14日 RSI",rows.map(r=>r.rsi14),"#9a63c8")]});prismTable.querySelector("thead").innerHTML="<tr><th>交易日</th><th>成长100R</th><th>价值100R</th><th>比值</th><th>242日均线</th><th>40日收益差</th><th>40日均线</th><th>14日RSI</th></tr>";prismTable.querySelector("tbody").innerHTML=rows.map(r=>`<tr><td>${keyToIso(r.tradeDate)}</td><td>${fmt(r.values["480080"])}</td><td>${fmt(r.values["480081"])}</td><td>${fmt(r.ratio)}</td><td>${fmt(r.ratioMa242)}</td><td class="${cls(r.return40Spread)}">${fmtPct(r.return40Spread)}</td><td>${fmtPct(r.return40Ma242)}</td><td>${r.rsi14==null?"—":r.rsi14.toFixed(2)}</td></tr>`).join("")}
function renderPrismVertical(){const actual=resolveBenchmarkDate(benchmark.value,indexDataset.records),rows=indexDataset.records.filter(r=>r.tradeDate>=actual),dates=rows.map(r=>keyToIso(r.tradeDate)),base=indexDataset.records.find(r=>r.tradeDate===actual).values;pageTitle.textContent="成长100R与价值100R轮动三棱镜";pageSubline.textContent="四张图使用同一基准日期，展示累计收益、比值布林线、40日收益差和RSI。";kpis.classList.add("hidden");document.querySelector(".chart-panel").classList.add("hidden");dataTable.closest(".panel").classList.add("hidden");prismContent.classList.remove("hidden");prismFreshness.textContent=`数据截至 ${keyToIso(indexDataset.latestTradeDate)} · 更新时间 ${indexDataset.updatedAt||"未记录"}`;const ret=(r,c)=>base[c]&&r.values[c]!=null?r.values[c]/base[c]-1:null;charts.prismMain.setOption({animation:false,tooltip:{trigger:"axis",valueFormatter:fmtPct},legend:{bottom:0},grid:{left:60,right:20,top:25,bottom:60},xAxis:{type:"category",data:dates,axisLabel:{rotate:45}},yAxis:{type:"value",axisLabel:{formatter:fmtPct}},series:[line("成长100R累计收益",rows.map(r=>ret(r,"480080")),"#c9362b"),line("价值100R累计收益",rows.map(r=>ret(r,"480081")),"#16834a")]});const common={animation:false,tooltip:{trigger:"axis"},legend:{bottom:0},grid:{left:60,right:20,top:25,bottom:60},xAxis:{type:"category",data:dates,axisLabel:{rotate:45}}};charts.ratio.setOption({...common,yAxis:{type:"value"},series:[line("比值（成长100R/价值100R）",rows.map(r=>r.ratio),"#2c6bed"),line("242日均线",rows.map(r=>r.ratioMa242),"#e67e32","dashed"),line("上轨（+2σ）",rows.map(r=>r.ratioUpper242),"#999","dotted"),line("下轨（−2σ）",rows.map(r=>r.ratioLower242),"#999","dotted")]});charts.spread.setOption({...common,tooltip:{trigger:"axis",valueFormatter:fmtPct},yAxis:{type:"value",axisLabel:{formatter:fmtPct}},series:[line("40日收益差",rows.map(r=>r.return40Spread),"#c9362b"),line("242日均线",rows.map(r=>r.return40Ma242),"#16834a","dashed")]});charts.rsi.setOption({...common,yAxis:{type:"value",min:0,max:100},series:[line("14日 RSI",rows.map(r=>r.rsi14),"#9a63c8"),line("RSI 242日均线",rows.map(r=>r.rsiMa242),"#e67e32","dashed")]});prismTable.querySelector("thead").innerHTML="<tr><th>交易日</th><th>成长100R</th><th>价值100R</th><th>比值</th><th>40日收益差</th><th>14日RSI</th></tr>";prismTable.querySelector("tbody").innerHTML=rows.map(r=>`<tr><td>${keyToIso(r.tradeDate)}</td><td class="${cls(ret(r,"480080"))}">${fmtPct(ret(r,"480080"))}</td><td class="${cls(ret(r,"480081"))}">${fmtPct(ret(r,"480081"))}</td><td>${fmt(r.ratio)}</td><td class="${cls(r.return40Spread)}">${fmtPct(r.return40Spread)}</td><td>${r.rsi14==null?"—":r.rsi14.toFixed(2)}</td></tr>`).join("")}
function stylePrismRatio(){if(!charts.ratio||window.activeDashboard!=="prism"||charts.ratio.__bandStyled)return;const series=charts.ratio.getOption().series||[];if(series.length<4)return;const lower=series[3].data||[],upper=series[2].data||[],value=x=>typeof x==="object"&&x!==null?x.value:x;charts.ratio.setOption({legend:{bottom:10},grid:{bottom:105},series:[{...series[0]}, {...series[1]}, {...series[3],name:"下轨（−2σ）",stack:"bollinger-band",areaStyle:{opacity:0},lineStyle:{color:"#999",type:"dotted"}}, {...series[2],name:"布林带区间",stack:"bollinger-band",data:upper.map((x,i)=>value(x)==null||value(lower[i])==null?null:value(x)-value(lower[i])),lineStyle:{color:"#999",type:"dotted"},itemStyle:{opacity:0},areaStyle:{color:"#8fb3d9",opacity:.28}}]});charts.ratio.__bandStyled=true}
function stylePrismRatioCorrect(){if(!charts.ratio||window.activeDashboard==="dividend-growth"||charts.ratio.__bandCorrected)return;const series=charts.ratio.getOption().series||[];if(series.length<4)return;const upper=series[2].data||[],lower=series[3].data||[],value=x=>typeof x==="object"&&x!==null?x.value:x,bandData=upper.slice(0,-1).map((x,i)=>[i,value(lower[i]),value(lower[i+1]),value(upper[i]),value(upper[i+1])]);charts.ratio.setOption({legend:{bottom:10,data:["比值（成长100R/价值100R）","242日均线","上轨（+2σ）","下轨（−2σ）"]},grid:{bottom:105},series:[{...series[0],name:"比值（成长100R/价值100R）"},{...series[1],name:"242日均线"},{...series[2],name:"上轨（+2σ）",lineStyle:{color:"#999",type:"dotted"},areaStyle:{opacity:0}},{...series[3],name:"下轨（−2σ）",lineStyle:{color:"#999",type:"dotted"},areaStyle:{opacity:0}},{name:"布林带阴影",type:"custom",silent:true,tooltip:{show:false},renderItem(params,api){const d=bandData[params.dataIndex];if(!d||d.slice(1).some(x=>x==null))return;const p1=api.coord([d[0],d[1]]),p2=api.coord([d[0]+1,d[2]]),p3=api.coord([d[0]+1,d[4]]),p4=api.coord([d[0],d[3]]);return{type:"polygon",shape:{points:[p1,p2,p3,p4]},style:{fill:"#8fb3d9",opacity:.28}}},data:bandData}]});charts.ratio.__bandCorrected=true}
function resizeCharts(){requestAnimationFrame(()=>requestAnimationFrame(()=>{stylePrismRatioCorrect();const prismCharts=new Set([charts.prismMain,charts.ratio,charts.spread,charts.rsi]);Object.values(charts).forEach(chart=>{if(!chart)return;if(window.activeDashboard!=="dividend-growth"&&prismCharts.has(chart))chart.setOption({legend:{bottom:10},grid:{bottom:84}});chart.resize()})}))}
function benchmarkKey(strategy){return BENCHMARK_KEYS[strategy]||`strategy-benchmark-${strategy}`}
function loadBenchmark(strategy){return localStorage.getItem(benchmarkKey(strategy))||DEFAULT_BENCHMARK}
function saveBenchmark(strategy){localStorage.setItem(benchmarkKey(strategy),benchmark.value)}
function calculateConfiguredRows(records,strategy){const ratio=records.map(r=>{const a=r.values[strategy.a],b=r.values[strategy.b];return a==null||!b?null:a/b}),changes=ratio.map((v,i)=>i&&v!=null&&ratio[i-1]!=null?v-ratio[i-1]:null),g=changes.map(v=>v>0?v:0),l=changes.map(v=>v<0?-v:0),out=[],avgG=[],avgL=[];for(let i=0;i<records.length;i++){if(i===14){avgG[i]=g.slice(1,15).reduce((a,b)=>a+b,0)/14;avgL[i]=l.slice(1,15).reduce((a,b)=>a+b,0)/14}else if(i>14){avgG[i]=(avgG[i-1]*13+g[i])/14;avgL[i]=(avgL[i-1]*13+l[i])/14}const rsi=i<14?null:avgL[i]===0?100:100-100/(1+avgG[i]/avgL[i]),w=ratio.slice(Math.max(0,i-241),i+1).filter(v=>v!=null),ma=w.length===242?w.reduce((a,b)=>a+b,0)/242:null,std=ma==null?null:Math.sqrt(w.reduce((a,b)=>a+(b-ma)**2,0)/241),old=records[i-40]?.values,spread=i>=40&&old?.[strategy.a]&&old?.[strategy.b]?((records[i].values[strategy.a]/old[strategy.a]-1)-(records[i].values[strategy.b]/old[strategy.b]-1)):null,sw=out.slice(Math.max(0,i-241)).map(x=>x.rsi14).filter(v=>v!=null),ss=out.slice(Math.max(0,i-241)).map(x=>x.return40Spread).filter(v=>v!=null);out.push({...records[i],ratio:ratio[i],ratioMa242:ma,ratioUpper242:ma==null?null:ma+2*std,ratioLower242:ma==null?null:ma-2*std,return40Spread:spread,return40Ma242:ss.length===241&&spread!=null?(ss.reduce((a,b)=>a+b,0)+spread)/242:null,rsi14:rsi,rsiMa242:sw.length===241&&rsi!=null?(sw.reduce((a,b)=>a+b,0)+rsi)/242:null})}return out}
function indexLabel(code){const item=indexDataset?.indexes?.[code];return item?`${item.name}（${code}）`:code}
function renderConfiguredPrism(){const s=indexDataset.strategies.find(x=>x.id===window.activeDashboard),actual=resolveBenchmarkDate(benchmark.value,indexDataset.records),all=calculateConfiguredRows(indexDataset.records,s),rows=all.filter(r=>r.tradeDate>=actual),dates=rows.map(r=>keyToIso(r.tradeDate)),base=indexDataset.records.find(r=>r.tradeDate===actual).values,ret=(r,c)=>base[c]&&r.values[c]!=null?r.values[c]/base[c]-1:null;pageTitle.textContent=s.name;pageSubline.textContent=`四张图使用同一基准日期，比较${indexLabel(s.a)}与${indexLabel(s.b)}的全收益表现。`;document.getElementById("strategy-universe").textContent=`A：${indexLabel(s.a)}　B：${indexLabel(s.b)}`;document.getElementById("prism-main-title").textContent=`同一基准下的${indexLabel(s.a)}与${indexLabel(s.b)}累计收益`;document.getElementById("prism-ratio-title").textContent=`${indexLabel(s.a)} / ${indexLabel(s.b)}比值及242日布林线`;document.getElementById("prism-spread-title").textContent=`${indexLabel(s.a)}与${indexLabel(s.b)}的40日收益差及242日均线`;document.getElementById("prism-rsi-title").textContent=`${indexLabel(s.a)} / ${indexLabel(s.b)}比值14日RSI及242日均线`;kpis.classList.add("hidden");document.querySelector(".chart-panel").classList.add("hidden");dataTable.closest(".panel").classList.add("hidden");prismContent.classList.remove("hidden");prismFreshness.textContent=`数据截至 ${keyToIso(indexDataset.latestTradeDate)} · 更新时间 ${indexDataset.updatedAt||"未记录"}`;const common={animation:false,tooltip:{trigger:"axis"},legend:{bottom:10},grid:{left:60,right:20,top:25,bottom:105},xAxis:{type:"category",data:dates,axisLabel:{rotate:45}}};charts.prismMain.setOption({...common,yAxis:{type:"value",axisLabel:{formatter:fmtPct}},series:[line(`${indexLabel(s.a)}累计收益`,rows.map(r=>ret(r,s.a)),"#c9362b"),line(`${indexLabel(s.b)}累计收益`,rows.map(r=>ret(r,s.b)),"#16834a")]});charts.ratio.setOption({...common,yAxis:{type:"value"},series:[line(`${indexLabel(s.a)} / ${indexLabel(s.b)}比值`,rows.map(r=>r.ratio),"#2c6bed"),line("242日均线",rows.map(r=>r.ratioMa242),"#e67e32","dashed"),line("上轨（+2σ）",rows.map(r=>r.ratioUpper242),"#999","dotted"),line("下轨（−2σ）",rows.map(r=>r.ratioLower242),"#999","dotted")]});charts.spread.setOption({...common,tooltip:{trigger:"axis",valueFormatter:fmtPct},yAxis:{type:"value",axisLabel:{formatter:fmtPct}},series:[line("40日收益差",rows.map(r=>r.return40Spread),"#c9362b"),line("242日均线",rows.map(r=>r.return40Ma242),"#16834a","dashed")]});charts.rsi.setOption({...common,yAxis:{type:"value",min:0,max:100},series:[line("14日RSI",rows.map(r=>r.rsi14),"#9a63c8"),line("RSI 242日均线",rows.map(r=>r.rsiMa242),"#e67e32","dashed")]})}
function render(){try{document.getElementById("index-total-panel").classList.toggle("hidden",window.activeDashboard!=="dividend-growth");message.classList.add("hidden");benchmark.value=loadBenchmark(window.activeDashboard||"dividend-growth");if(charts.ratio){charts.ratio.__bandStyled=false;charts.ratio.__bandCorrected=false;if(window.activeDashboard!=="dividend-growth")charts.ratio.clear()}window.activeDashboard==="prism"?renderPrismVertical():window.activeDashboard.startsWith("dividend-hs300")||window.activeDashboard.startsWith("growth-value-300")||window.activeDashboard.startsWith("csi2000")||window.activeDashboard.startsWith("nonferrous")||window.activeDashboard.startsWith("banks-")||window.activeDashboard.startsWith("dividend-growth-300")||window.activeDashboard.startsWith("dividend-a-")?renderConfiguredPrism():renderETF();if(window.activeDashboard==="dividend-growth"){document.getElementById("strategy-universe").textContent="A：建信沪深300红利ETF（512530）　B：银华沪深300成长ETF（562310）　基准：华夏沪深300ETF（510330）"}if(window.activeDashboard==="prism"){document.getElementById("strategy-universe").textContent=`A：${indexLabel("480080")}　B：${indexLabel("480081")}`;document.getElementById("prism-main-title").textContent=`同一基准下的${indexLabel("480080")}与${indexLabel("480081")}累计收益`;document.getElementById("prism-ratio-title").textContent=`${indexLabel("480080")} / ${indexLabel("480081")}比值及242日布林线`;document.getElementById("prism-spread-title").textContent=`${indexLabel("480080")}与${indexLabel("480081")}的40日收益差及242日均线`;document.getElementById("prism-rsi-title").textContent=`${indexLabel("480080")} / ${indexLabel("480081")}比值14日RSI及242日均线`}resizeCharts()}catch(e){message.textContent=e.message;message.dataset.state="error";message.classList.remove("hidden")}}
async function refreshData(){
  const button=document.getElementById("refresh-data"),oldLatest=(window.activeDashboard==="dividend-growth"?dataset?.latestTradeDate:indexDataset?.latestTradeDate),oldEnd=endDate.value,followedLatest=!oldEnd||!oldLatest||isoToKey(oldEnd)===oldLatest;
  button.disabled=true;button.textContent="正在启动更新任务…";message.classList.remove("hidden","success");message.dataset.state="loading";
  try{
    const response=await fetch("/api/jobs/update",{method:"POST"}),body=await response.json();
    if(!response.ok)throw Error(body.detail||"无法启动更新任务");
    if(!/^[a-f0-9]{32}$/.test(body.job_id))throw Error("任务编号无效");
    let job;
    for(let attempt=0;attempt<300;attempt++){
      job=await fetchJson(`/api/jobs/${body.job_id}`);
      if(["SUCCEEDED","FAILED","PARTIAL"].includes(job.state))break;
      button.textContent="数据更新中…";message.textContent=`更新任务 ${body.job_id.slice(0,8)}：${job.stage||job.state}；当前仍显示已发布版本。`;
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
    if(!job||!["SUCCEEDED","FAILED","PARTIAL"].includes(job.state))throw Error("任务仍在运行，请到数据中心查看状态");
    if(job.state==="FAILED"||job.state==="PARTIAL"&&!job.snapshot_id)throw Error(`任务${job.state==="PARTIAL"?"部分完成":"失败"}（${job.error||job.stage}）；请到数据中心查看`);
    const manifest=await fetchJson("/api/snapshot");acceptSnapshotManifest(manifest);
    await ensureDashboardData(window.activeDashboard);
    const newLatest=(window.activeDashboard==="dividend-growth"?dataset?.latestTradeDate:indexDataset?.latestTradeDate);
    if(followedLatest&&newLatest)endDate.value=keyToIso(newLatest);
    let detail;
    try{detail=await fetchJson(`/api/jobs/${body.job_id}/details`)}catch{}
    const etfLatest=detail?.datasets?.find(item=>item.dataset_id==="etf_prices")?.latest_date;
    const indexLatest=detail?.datasets?.find(item=>item.dataset_id==="index_prices")?.latest_date;
    const indexLags=Boolean(etfLatest&&indexLatest&&indexLatest<etfLatest);
    const routePending=detail?.datasets?.some(item=>item.dataset_id==="index:480080"&&item.reason_code==="CNI_ROUTE_PENDING");
    render();
    message.textContent=indexLags
      ?`ETF 价格截至 ${keyToIso(etfLatest)}，指数点位仍截至 ${keyToIso(indexLatest)}；快照 ${manifest.snapshot_id} 已发布，但本次指数未更新到 ETF 日期。${routePending?"成长100R 的同日路线证据尚未齐备；":""}请到数据中心查看核验原因。`
      :job.publication_status==="UNCHANGED"?`本次无新行情，继续使用版本 ${manifest.snapshot_id}${job.state==="PARTIAL"?"；部分数据源未更新，请到数据中心查看。":"。"}`
      :job.state==="PARTIAL"?`行情已发布版本 ${manifest.snapshot_id}；其他数据部分失败，请到数据中心查看。`
      :`更新任务已发布版本 ${manifest.snapshot_id}`;
    if(job.state==="SUCCEEDED"&&!indexLags)message.classList.add("success");
    message.dataset.state=job.state==="SUCCEEDED"&&!indexLags?"success":"warning";message.classList.remove("hidden");
  }catch(e){
    const retained=(window.activeDashboard==="dividend-growth"?dataset?.latestTradeDate:indexDataset?.latestTradeDate);
    message.textContent=`刷新未发布：${e.message}${retained?`；当前仍显示截至 ${keyToIso(retained)} 的已发布数据`:""}`;
    message.dataset.state="error";message.classList.remove("hidden");
  }finally{button.disabled=false;button.textContent="刷新全部数据"}
}
async function init(){try{const manifest=await fetchJson("/api/snapshot");activeSnapshotId=manifest.snapshot_id;const requested=new URLSearchParams(location.search).get("strategy"),strategyButtons=[...document.querySelectorAll(".strategy-item[data-strategy]")];window.activeDashboard=strategyButtons.some(b=>b.dataset.strategy===requested)?requested:"dividend-growth";await ensureDashboardData(window.activeDashboard);localStorage.removeItem("etf-dashboard-end-date");endDate.value=currentLocalIsoDate();for(const [key,id] of Object.entries({main:"main-chart",indexTotal:"index-total-chart",prismMain:"prism-main-chart",ratio:"prism-ratio-chart",spread:"prism-spread-chart",rsi:"prism-rsi-chart"}))charts[key]=chartTheme.init(document.getElementById(id));strategyButtons.forEach(b=>{b.classList.toggle("active",b.dataset.strategy===window.activeDashboard);b.onclick=async()=>{saveBenchmark(window.activeDashboard);strategyButtons.forEach(x=>x.classList.toggle("active",x===b));window.activeDashboard=b.dataset.strategy;history.replaceState(null,"",`${location.pathname}?strategy=${encodeURIComponent(window.activeDashboard)}`);message.textContent="正在读取所选看板数据…";message.dataset.state="loading";message.classList.remove("hidden");try{await ensureDashboardData(window.activeDashboard);if(window.activeDashboard===b.dataset.strategy)render()}catch(e){message.textContent=`数据加载失败：${e.message}`;message.dataset.state="error";message.classList.remove("hidden")}}});bindTableToggles();observeChartContainers();benchmark.addEventListener("change",()=>{saveBenchmark(window.activeDashboard);render()});benchmark.addEventListener("input",()=>{saveBenchmark(window.activeDashboard);render()});endDate.addEventListener("change",render);document.getElementById("refresh-data").addEventListener("click",refreshData);window.addEventListener("resize",()=>{Object.values(charts).forEach(x=>x.resize());if(isPrismDashboard())prismUpdateAxisLabels()});render();locateOverviewDate()}catch(e){message.textContent=`数据加载失败：${e.message}`;message.dataset.state="error";message.classList.remove("hidden")}}
const benchmark=document.getElementById("benchmark-date"),endDate=document.getElementById("end-date"),pageTitle=document.getElementById("page-title"),pageSubline=document.getElementById("page-subline"),freshness=document.getElementById("freshness"),kpis=document.getElementById("kpis"),message=document.getElementById("message"),dataTable=document.getElementById("data-table"),prismContent=document.getElementById("prism-content"),prismFreshness=document.getElementById("prism-freshness"),prismTable=document.getElementById("prism-table");
function bindTableToggles(){[["toggle-main-table","main-table-region"],["toggle-prism-table","prism-table-region"]].forEach(([buttonId,regionId])=>{const button=document.getElementById(buttonId),region=document.getElementById(regionId);button?.addEventListener("click",()=>{const expanded=button.getAttribute("aria-expanded")==="true",rows=region.querySelectorAll("tbody tr").length;button.setAttribute("aria-expanded",String(!expanded));region.hidden=expanded;button.textContent=`${expanded?"展开":"收起"}交易日数据${rows?`（${rows}行）`:""}`})})}
function observeChartContainers(){if(!window.ResizeObserver)return;const observer=new ResizeObserver(entries=>{let rsiResized=false;entries.forEach(entry=>{const chart=Object.values(charts).find(item=>item?.getDom()===entry.target);chart?.resize();if(chart===charts.rsi)rsiResized=true});if(rsiResized&&isPrismDashboard())prismUpdateAxisLabels()});Object.values(charts).forEach(chart=>{if(chart)observer.observe(chart.getDom())});window.dashboardChartResizeObserver=observer}
const legacyCalculateConfiguredRows=calculateConfiguredRows;
calculateConfiguredRows=function(records,strategy){return indexDataset?.strategyMetrics?.[window.activeDashboard]||legacyCalculateConfiguredRows(records,strategy)};
const originalRenderConfiguredPrism=renderConfiguredPrism;
renderConfiguredPrism=function(){const strategy=indexDataset.strategies.find(x=>x.id===window.activeDashboard),previousRecords=indexDataset.records,previousLatest=indexDataset.latestTradeDate;if(strategy){const shared=previousRecords.filter(r=>r.values?.[strategy.a]!=null&&r.values?.[strategy.b]!=null);indexDataset.records=shared;indexDataset.latestTradeDate=shared.at(-1)?.tradeDate||previousLatest}try{return originalRenderConfiguredPrism()}finally{indexDataset.records=previousRecords;indexDataset.latestTradeDate=previousLatest}};
if(typeof window!=="undefined")window.addEventListener("DOMContentLoaded",init);if(typeof module!=="undefined")module.exports={resolveBenchmarkDate,buildSeries};
const GUIDES_URL=new URL("strategy-guides.json",document.baseURI).toString(),guideModal=document.getElementById("strategy-guide-modal"),guideButton=document.getElementById("strategy-guide-button"),guideClose=document.getElementById("strategy-guide-close"),guideTitle=document.getElementById("strategy-guide-title"),guideContent=document.getElementById("strategy-guide-content");
let strategyGuides=null;
let guideReturnFocus=null;
function escapeGuideHtml(value){return String(value??"").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[c]))}
function guideText(value,strategy){const names={"{{A_NAME}}":indexLabel(strategy?.a||"480080"),"{{B_NAME}}":indexLabel(strategy?.b||"480081")};return escapeGuideHtml(value).replace(/\{\{A_NAME\}\}|\{\{B_NAME\}\}/g,m=>escapeGuideHtml(names[m]||m))}
function guideFormula(item,strategy){return `<div class="guide-formula"><div class="guide-formula-label">${guideText(item.label||"",strategy)}</div><div>${guideText(item.formula||"",strategy)}</div>${item.note?`<p class="guide-note">${guideText(item.note,strategy)}</p>`:""}</div>`}
function guideSection(section,strategy){if(section.type==="table")return `<table class="guide-table"><thead><tr>${(section.headers||[]).map(x=>`<th>${guideText(x,strategy)}</th>`).join("")}</tr></thead><tbody>${(section.rows||[]).map(row=>`<tr>${row.map(x=>`<td>${guideText(x,strategy)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;if(section.type==="formulas")return (section.items||[]).map(item=>guideFormula(item,strategy)).join("");if(section.type==="text")return `${(section.paragraphs||[]).map(x=>`<p>${guideText(x,strategy)}</p>`).join("")}${(section.formulas||[]).map(item=>guideFormula(item,strategy)).join("")}`;if(section.type==="steps")return `<ol>${(section.items||[]).map(x=>`<li>${guideText(x,strategy)}</li>`).join("")}</ol>`;if(section.type==="uses")return (section.items||[]).map(item=>`<article class="guide-use"><div class="guide-use-head"><span class="guide-use-number">${guideText(item.number,strategy)}</span><span class="guide-use-tag">${guideText(item.tag,strategy)}</span><span class="guide-use-title">${guideText(item.title,strategy)}</span></div><p>${guideText(item.text,strategy)}</p></article>`).join("");if(section.type==="notice")return `<div class="guide-notice">${guideText(section.text,strategy)}</div>`;if(section.type==="dynamic-pair")return `<div class="guide-dynamic-pair">${guideText(section.text,strategy)}</div>`;return section.text?`<p>${guideText(section.text,strategy)}</p>`:""}
function guideMarkup(guide,strategy){return `<p class="guide-intro">${guideText(guide.intro,strategy)}</p>${(guide.sections||[]).map(section=>`<section class="guide-section"><h3>${guideText(section.title,strategy)}</h3>${guideSection(section,strategy)}</section>`).join("")}`}
async function typesetGuide(){if(!window.MathJax)return;if(window.MathJax.startup?.promise)await window.MathJax.startup.promise;if(window.MathJax.typesetPromise)await window.MathJax.typesetPromise([guideContent])}
async function openStrategyGuide(){guideReturnFocus=document.activeElement;document.querySelector('main').inert=true;guideModal.classList.remove("hidden");guideClose.focus();guideContent.innerHTML="<p>正在加载策略说明…</p>";try{if(!strategyGuides)strategyGuides=await fetchJson(`${GUIDES_URL}?t=${Date.now()}`);const dashboard=window.activeDashboard||"dividend-growth",strategy=dashboard==="prism"?{a:"480080",b:"480081"}:indexDataset?.strategies?.find(x=>x.id===dashboard),guide=dashboard==="dividend-growth"?strategyGuides.etf:strategyGuides.prism;guideTitle.textContent=`${pageTitle.textContent||guide.title}｜策略说明`;guideContent.innerHTML=guideMarkup(guide,strategy);await typesetGuide()}catch(error){guideContent.innerHTML=`<div class="guide-notice">策略说明加载失败：${escapeGuideHtml(error.message)}</div>`}}
function closeStrategyGuide(){guideModal.classList.add("hidden");document.querySelector('main').inert=false;guideReturnFocus?.focus();guideReturnFocus=null}
if(typeof window!=="undefined")window.addEventListener("DOMContentLoaded",()=>{guideButton?.addEventListener("click",openStrategyGuide);guideClose?.addEventListener("click",closeStrategyGuide);guideModal?.addEventListener("click",event=>{if(event.target.dataset.guideClose==="true")closeStrategyGuide()});document.addEventListener("keydown",event=>{if(guideModal.classList.contains("hidden"))return;if(event.key==="Escape"){event.preventDefault();closeStrategyGuide();return}if(event.key!=="Tab")return;const items=[...guideModal.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(item=>item.getClientRects().length);if(!items.length){event.preventDefault();guideClose.focus();return}const first=items[0],last=items[items.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}})});

// 三棱镜四图共享时间交互：只改变可视窗口，不参与任何指标计算。
const PRISM_TIME_RANGE_KEY="prism-dashboard-time-range";
const prismInteraction={rangeKey:localStorage.getItem(PRISM_TIME_RANGE_KEY)||"all",viewStart:0,viewEnd:0,hoverIndex:null,lockedIndex:null,rows:[],dates:[],labels:{a:"成长100R",b:"价值100R"},syncing:false,bound:false,leaveTimer:null};
const prismChartList=()=>[charts.prismMain,charts.ratio,charts.spread,charts.rsi].filter(Boolean);
const PRISM_STRATEGY_IDS=new Set(["prism","dividend-hs300","growth-value-300","csi2000-hs300","nonferrous-chemical","banks-exbank-financial","dividend-growth-300","dividend-a-share","dividend-a-hk"]);
function isPrismDashboard(){return PRISM_STRATEGY_IDS.has(window.activeDashboard)}
const prismFormatRatio=x=>x==null?"—":Number(x).toFixed(3);
const prismFormatRsi=x=>x==null?"—":Number(x).toFixed(1);
function prismRangeIndices(rangeKey){const last=prismInteraction.dates.length-1;if(last<=0)return{start:0,end:Math.max(0,last)};const months={"6m":6,"1y":12,"3y":36,"5y":60}[rangeKey];if(!months)return{start:0,end:last};const latest=prismInteraction.dates[last],date=new Date(`${keyToIso(latest)}T00:00:00Z`);date.setUTCMonth(date.getUTCMonth()-months);const target=isoToKey(date.toISOString().slice(0,10));const start=prismInteraction.dates.findIndex(value=>value>=target);return{start:start<0?0:start,end:last}}
function prismUpdateSnapshot(index){const rows=prismInteraction.rows;if(!rows.length)return;const safe=Math.max(0,Math.min(index==null?rows.length-1:index,rows.length-1)),row=rows[safe],snapshot=document.getElementById("prism-snapshot"),selected=document.getElementById("prism-selected-date"),unlock=document.getElementById("prism-unlock"),observation=document.getElementById("prism-observation");
  const spread=row.return40CoverageStatus==="PASS"&&Number.isFinite(row.return40Spread)?row.return40Spread:null;
  const lead=spread==null?"相对强弱待计算":spread>0?`${prismInteraction.labels.a}近40日相对占优`:spread<0?`${prismInteraction.labels.b}近40日相对占优`:"近40日收益持平";
  observation.replaceChildren();
  for(const [label,value] of [["当前观察日",keyToIso(row.tradeDate)],["当前研究信号",lead],["40日收益差",fmtPct(spread)],["RSI(14)",prismFormatRsi(row.rsi14)]]){
    const cell=document.createElement("div"),caption=document.createElement("span"),number=document.createElement("strong");
    caption.textContent=label;number.textContent=value;cell.append(caption,number);observation.append(cell);
  }
  const note=document.createElement("small");note.textContent="历史研究观察，不构成交易指令；缺失指标不补值。";observation.append(note);
  snapshot.innerHTML=[
  ["交易日",keyToIso(row.tradeDate),"prism-snapshot-date"],[`${prismInteraction.labels.a}累计收益`,fmtPct(row.returnA)], [`${prismInteraction.labels.b}累计收益`,fmtPct(row.returnB)], ["相对比值",prismFormatRatio(row.ratio)], ["242日均线",prismFormatRatio(row.ratioMa242)], ["40日收益差",fmtPct(row.return40Spread)], ["RSI(14)",prismFormatRsi(row.rsi14)]
].map(([label,value,extra=""])=>`<div class="prism-snapshot-item ${extra}"><span>${label}</span><strong>${value}</strong></div>`).join("");selected.textContent=`当前观察日：${keyToIso(row.tradeDate)} · ${prismInteraction.lockedIndex==null?"未锁定":"已锁定"}`;unlock.classList.toggle("hidden",prismInteraction.lockedIndex==null);snapshot.dataset.index=String(safe)}
function prismHideTips(){prismChartList().forEach(chart=>chart.dispatchAction({type:"hideTip"}))}
function prismShowTips(index){if(index==null||!prismInteraction.dates[index])return;prismInteraction.syncing=true;prismChartList().forEach(chart=>chart.dispatchAction({type:"showTip",seriesIndex:0,dataIndex:index}));prismInteraction.syncing=false}
function prismSetCursor(index){if(index==null||!prismInteraction.rows.length)return;prismInteraction.hoverIndex=index;prismUpdateSnapshot(index);prismShowTips(index)}
function prismUnlock(){prismInteraction.lockedIndex=null;prismInteraction.hoverIndex=null;prismHideTips();prismUpdateSnapshot(prismInteraction.rows.length-1)}
function prismLock(index){if(index==null)return;if(prismInteraction.lockedIndex===index){prismUnlock();return}prismInteraction.lockedIndex=index;prismInteraction.hoverIndex=index;prismUpdateSnapshot(index);prismShowTips(index)}
function prismDateIndexFromEvent(params){const item=Array.isArray(params)?params[0]:params;if(item?.dataIndex!=null&&Number.isFinite(Number(item.dataIndex)))return Number(item.dataIndex);const axis=item?.axesInfo?.find(info=>info.axisDim==="x")||item?.axesInfo?.[0];const value=axis?.value;if(typeof value==="number")return Math.round(value);if(value!=null){const index=prismInteraction.dates.indexOf(String(value));if(index>=0)return index}return null}
function prismScheduleLeave(){clearTimeout(prismInteraction.leaveTimer);prismInteraction.leaveTimer=setTimeout(()=>{if(prismInteraction.lockedIndex==null){prismHideTips();prismInteraction.hoverIndex=null;prismUpdateSnapshot(prismInteraction.rows.length-1)}},100)}
function prismSyncZoom(start,end,fromChart=false){const count=prismInteraction.dates.length;if(!count)return;const safeStart=Math.max(0,Math.min(100,Number(start)||0)),safeEnd=Math.max(safeStart,Math.min(100,Number(end)==null?100:Number(end)));prismInteraction.viewStart=Math.round(safeStart*(count-1)/100);prismInteraction.viewEnd=Math.round(safeEnd*(count-1)/100);if(prismInteraction.lockedIndex!=null&&(prismInteraction.lockedIndex<prismInteraction.viewStart||prismInteraction.lockedIndex>prismInteraction.viewEnd))prismUnlock();prismInteraction.syncing=true;prismChartList().forEach(chart=>chart.dispatchAction({type:"dataZoom",start:safeStart,end:safeEnd}));prismInteraction.syncing=false;const view=document.getElementById("prism-view-range");if(view)view.textContent=`显示区间：${keyToIso(prismInteraction.dates[prismInteraction.viewStart])} 至 ${keyToIso(prismInteraction.dates[prismInteraction.viewEnd])}`;if(fromChart){prismInteraction.rangeKey="custom";document.querySelectorAll(".prism-range-button").forEach(button=>button.classList.remove("active"))}prismUpdateAxisLabels()}
function prismUpdateAxisLabels(){
  const visible=Math.max(1,prismInteraction.viewEnd-prismInteraction.viewStart+1);
  const formatDate=value=>{const raw=String(value);return raw.includes("-")?raw.slice(0,7):keyToIso(raw).slice(0,7)};
  prismChartList().forEach(chart=>{
    const width=chart.getWidth()||720;
    const maxLabels=Math.max(2,Math.min(8,Math.floor((width-100)/95)));
    const step=Math.max(1,Math.ceil(visible/maxLabels));
    chart.setOption({grid:{bottom:50},xAxis:{axisLabel:{show:true,rotate:0,hideOverlap:true,interval:index=>index%step===0,formatter:formatDate}}});
  });
}
function prismSetRange(rangeKey){if(!prismInteraction.dates.length)return;prismInteraction.rangeKey=rangeKey;localStorage.setItem(PRISM_TIME_RANGE_KEY,rangeKey);document.querySelectorAll(".prism-range-button").forEach(button=>button.classList.toggle("active",button.dataset.prismRange===rangeKey));const range=prismRangeIndices(rangeKey),start=range.start/(prismInteraction.dates.length-1||1)*100,end=range.end/(prismInteraction.dates.length-1||1)*100;prismSyncZoom(start,end,false)}
function prismHandleAxisPointer(params){if(!isPrismDashboard()||prismInteraction.lockedIndex!=null||prismInteraction.syncing)return;const index=prismDateIndexFromEvent(params);if(index==null)return;clearTimeout(prismInteraction.leaveTimer);prismSetCursor(index)}
function prismIndexFromPixel(chart,event){try{const x=event.zrX??event.offsetX,y=event.zrY??event.offsetY,value=chart.convertFromPixel({xAxisIndex:0},[x,y]),index=Math.round(Number(value?.[0]));return Number.isFinite(index)&&index>=0&&index<prismInteraction.dates.length?index:null}catch{return null}}
function prismBindChartInteractions(){if(prismInteraction.bound)return;prismInteraction.bound=true;prismChartList().forEach(chart=>{chart.off("updateAxisPointer");chart.off("datazoom");chart.off("click");chart.off("globalout");chart.on("updateAxisPointer",prismHandleAxisPointer);chart.on("datazoom",params=>{if(!isPrismDashboard()||prismInteraction.syncing)return;const item=Array.isArray(params?.batch)?params.batch[0]:params,option=chart.getOption().dataZoom?.[0]||{};prismSyncZoom(item?.start??option.start,item?.end??option.end,true)});const zr=chart.getZr?.();if(zr){if(chart.__prismZrClickHandler)zr.off("click",chart.__prismZrClickHandler);const handler=event=>{if(!isPrismDashboard())return;const index=prismIndexFromPixel(chart,event)??prismInteraction.hoverIndex;if(index!=null)prismLock(index)};chart.__prismZrClickHandler=handler;zr.on("click",handler)};chart.on("globalout",prismScheduleLeave)});document.querySelectorAll(".prism-range-button").forEach(button=>button.addEventListener("click",()=>prismSetRange(button.dataset.prismRange)));document.getElementById("prism-unlock")?.addEventListener("click",prismUnlock);document.addEventListener("keydown",event=>{if(event.key==="Escape"&&isPrismDashboard()&&prismInteraction.lockedIndex!=null)prismUnlock()})}
function prismBindWhenReady(){if(!charts.prismMain){setTimeout(prismBindWhenReady,50);return}prismBindChartInteractions()}
if(typeof window!=="undefined")window.addEventListener("DOMContentLoaded",prismBindWhenReady);
const overviewDate = new URLSearchParams(location.search).get("observed_date");
function prismDisplayRows(rows) {
  const effective=indexDataset.strategyInputStatus?.[window.activeDashboard]?.effectiveDate||indexDataset.latestTradeDate;
  const cutoff = isoToKey(endDate.value || keyToIso(effective));
  const visible = rows.filter(row => row.tradeDate <= cutoff);
  if (!visible.length) throw Error("结束日期早于该策略可显示的历史数据。");
  return visible;
}

function locateOverviewDate() {
  if (!overviewDate || !isPrismDashboard() || !message.classList.contains("hidden")) return;
  const index = prismInteraction.dates.indexOf(overviewDate);
  if (index < 0 || prismInteraction.rows[index].ratio == null) {
    message.textContent = "当前策略没有该观察日的有效数据。"; message.dataset.state = "warning";
    message.classList.remove("hidden");
    return;
  }
  if (index < prismInteraction.viewStart || index > prismInteraction.viewEnd) prismSyncZoom(0, 100);
  prismLock(index);
}

function renderPrismVertical(){const actual=resolveBenchmarkDate(benchmark.value,indexDataset.records),sourceRows=prismDisplayRows(indexDataset.records),base=indexDataset.records.find(r=>r.tradeDate===actual).values,ret=(r,c)=>base[c]&&r.values[c]!=null?r.values[c]/base[c]-1:null,rows=sourceRows.map(r=>({...r,returnA:ret(r,"480080"),returnB:ret(r,"480081")})),dates=rows.map(r=>r.tradeDate);prismInteraction.rows=rows;prismInteraction.dates=dates;prismInteraction.labels={a:"成长100R",b:"价值100R"};prismInteraction.lockedIndex=null;prismInteraction.hoverIndex=null;pageTitle.textContent="成长100R与价值100R轮动三棱镜";pageSubline.textContent="四张图使用同一基准日期，展示累计收益、比值布林线、40日收益差和RSI。";kpis.classList.add("hidden");document.querySelector(".chart-panel").classList.add("hidden");dataTable.closest(".panel").classList.add("hidden");prismContent.classList.remove("hidden");prismFreshness.textContent=`数据截至 ${keyToIso(indexDataset.latestTradeDate)} · 更新时间 ${indexDataset.updatedAt||"未记录"}`;const common={animation:false,tooltip:{trigger:"axis",axisPointer:{type:"cross",snap:true}},legend:{bottom:10},grid:{left:60,right:20,top:25,bottom:105},dataZoom:[{type:"inside",xAxisIndex:0,filterMode:"none",start:0,end:100}],xAxis:{type:"category",data:dates,axisPointer:{show:true,type:"line",snap:true}},};charts.prismMain.setOption({...common,yAxis:{type:"value",axisLabel:{formatter:fmtPct}},series:[line("成长100R累计收益",rows.map(r=>r.returnA),"#c9362b"),line("价值100R累计收益",rows.map(r=>r.returnB),"#16834a")]});charts.ratio.setOption({...common,yAxis:{type:"value"},series:[line("比值（成长100R/价值100R）",rows.map(r=>r.ratio),"#2c6bed"),line("242日均线",rows.map(r=>r.ratioMa242),"#e67e32","dashed"),line("上轨（+2σ）",rows.map(r=>r.ratioUpper242),"#999","dotted"),line("下轨（−2σ）",rows.map(r=>r.ratioLower242),"#999","dotted")]});charts.spread.setOption({...common,tooltip:{trigger:"axis",valueFormatter:fmtPct,axisPointer:{type:"cross",snap:true}},yAxis:{type:"value",axisLabel:{formatter:fmtPct}},series:[line("40日收益差",rows.map(r=>r.return40Spread),"#c9362b"),line("242日均线",rows.map(r=>r.return40Ma242),"#16834a","dashed")]});charts.rsi.setOption({...common,yAxis:{type:"value",min:0,max:100},series:[line("14日 RSI",rows.map(r=>r.rsi14),"#9a63c8"),line("RSI 242日均线",rows.map(r=>r.rsiMa242),"#e67e32","dashed")]});prismTable.querySelector("thead").innerHTML="<tr><th>交易日</th><th>成长100R</th><th>价值100R</th><th>比值</th><th>40日收益差</th><th>14日RSI</th></tr>";prismTable.querySelector("tbody").innerHTML=rows.map(r=>`<tr><td>${keyToIso(r.tradeDate)}</td><td class="${cls(r.returnA)}">${fmtPct(r.returnA)}</td><td class="${cls(r.returnB)}">${fmtPct(r.returnB)}</td><td>${fmt(r.ratio)}</td><td class="${cls(r.return40Spread)}">${fmtPct(r.return40Spread)}</td><td>${r.rsi14==null?"—":r.rsi14.toFixed(2)}</td></tr>`).join("");document.querySelectorAll(".prism-range-button").forEach(button=>button.classList.toggle("active",button.dataset.prismRange===prismInteraction.rangeKey));const range=prismRangeIndices(prismInteraction.rangeKey),start=range.start/(dates.length-1||1)*100,end=range.end/(dates.length-1||1)*100;prismSyncZoom(start,end,false);prismUpdateSnapshot(rows.length-1)}

function applyPrismSharedInteractionView(rows,labels){const dates=rows.map(r=>r.tradeDate);prismInteraction.rows=rows;prismInteraction.dates=dates;prismInteraction.labels=labels;prismInteraction.lockedIndex=null;prismInteraction.hoverIndex=null;document.body.classList.add("prism-active");const common={animation:false,tooltip:{trigger:"axis",axisPointer:{type:"cross",snap:true}},legend:{bottom:10},grid:{left:60,right:20,top:25,bottom:105},dataZoom:[{type:"inside",xAxisIndex:0,filterMode:"none",start:0,end:100}],xAxis:{type:"category",data:dates,axisPointer:{show:true,type:"line",snap:true}}};charts.prismMain.setOption({...common,yAxis:{type:"value",axisLabel:{formatter:fmtPct}},series:[line(`${labels.a}累计收益`,rows.map(r=>r.returnA),"#c9362b"),line(`${labels.b}累计收益`,rows.map(r=>r.returnB),"#16834a")]});charts.ratio.setOption({...common,yAxis:{type:"value"},series:[line(`${labels.a} / ${labels.b}比值`,rows.map(r=>r.ratio),"#2c6bed"),line("242日均线",rows.map(r=>r.ratioMa242),"#e67e32","dashed"),line("上轨（+2σ）",rows.map(r=>r.ratioUpper242),"#999","dotted"),line("下轨（−2σ）",rows.map(r=>r.ratioLower242),"#999","dotted")]});charts.spread.setOption({...common,tooltip:{trigger:"axis",valueFormatter:fmtPct,axisPointer:{type:"cross",snap:true}},yAxis:{type:"value",axisLabel:{formatter:fmtPct}},series:[line("40日收益差",rows.map(r=>r.return40Spread),"#c9362b"),line("242日均线",rows.map(r=>r.return40Ma242),"#16834a","dashed")]});charts.rsi.setOption({...common,yAxis:{type:"value",min:0,max:100},series:[line("14日RSI",rows.map(r=>r.rsi14),"#9a63c8"),line("RSI 242日均线",rows.map(r=>r.rsiMa242),"#e67e32","dashed"),line("RSI 50基准线",rows.map(()=>50),"#999","dashed")]});document.querySelectorAll(".prism-range-button").forEach(button=>button.classList.toggle("active",button.dataset.prismRange===prismInteraction.rangeKey));const range=prismRangeIndices(prismInteraction.rangeKey),start=range.start/(dates.length-1||1)*100,end=range.end/(dates.length-1||1)*100;prismSyncZoom(start,end,false);prismUpdateSnapshot(rows.length-1)}
function buildConfiguredPrismRows(){const strategy=indexDataset.strategies.find(x=>x.id===window.activeDashboard),records=indexDataset.strategyMetrics?.[strategy.id]||indexDataset.records.filter(r=>r.values?.[strategy.a]!=null&&r.values?.[strategy.b]!=null),actual=resolveBenchmarkDate(benchmark.value,records),all=calculateConfiguredRows(records,strategy),base=records.find(r=>r.tradeDate===actual).values,ret=(r,c)=>base[c]!=null&&r.values[c]!=null?r.values[c]/base[c]-1:null;return{rows:prismDisplayRows(all).map(r=>({...r,returnA:ret(r,strategy.a),returnB:ret(r,strategy.b)})),labels:{a:indexLabel(strategy.a),b:indexLabel(strategy.b)}}}


renderConfiguredPrism=function(){
  const strategy=indexDataset.strategies.find(x=>x.id===window.activeDashboard);
  const {rows,labels}=buildConfiguredPrismRows();
  pageTitle.textContent=strategy.name;
  pageSubline.textContent=`四张图使用同一基准日期，比较${labels.a}与${labels.b}的全收益表现。`;
  document.getElementById("strategy-universe").textContent=`A：${labels.a}　B：${labels.b}`;
  document.getElementById("prism-main-title").textContent=`同一基准下的${labels.a}与${labels.b}累计收益`;
  document.getElementById("prism-ratio-title").textContent=`${labels.a} / ${labels.b}比值及242日布林线`;
  document.getElementById("prism-spread-title").textContent=`${labels.a}与${labels.b}的40日收益差及242日均线`;
  document.getElementById("prism-rsi-title").textContent=`${labels.a} / ${labels.b}比值14日RSI及242日均线`;
  kpis.classList.add("hidden");document.querySelector(".chart-panel").classList.add("hidden");
  dataTable.closest(".panel").classList.add("hidden");prismContent.classList.remove("hidden");
  const effectiveDate=indexDataset.strategyInputStatus?.[strategy.id]?.effectiveDate||rows.at(-1)?.tradeDate;
  prismFreshness.textContent=`数据截至 ${keyToIso(effectiveDate)} · 快照 ${indexDataset.snapshot_id||"未知"} · 更新时间 ${indexDataset.updatedAt||"未记录"}`;
  prismTable.querySelector("thead").innerHTML="<tr><th>交易日</th><th>成长累计</th><th>价值累计</th><th>比值</th><th>40日收益差</th><th>14日RSI</th></tr>";
  prismTable.querySelector("tbody").innerHTML=rows.map(r=>`<tr><td>${keyToIso(r.tradeDate)}</td><td class="${cls(r.returnA)}">${fmtPct(r.returnA)}</td><td class="${cls(r.returnB)}">${fmtPct(r.returnB)}</td><td>${fmt(r.ratio)}</td><td class="${cls(r.return40Spread)}">${fmtPct(r.return40Spread)}</td><td>${r.rsi14==null?"—":r.rsi14.toFixed(2)}</td></tr>`).join("");
  applyPrismSharedInteractionView(rows,labels);
};
const renderNativePrism=renderPrismVertical;
renderPrismVertical=function(){
  const result=renderNativePrism();
  const effectiveDate=indexDataset.records.at(-1)?.tradeDate;
  if(effectiveDate)prismFreshness.textContent=`数据截至 ${keyToIso(effectiveDate)} · 快照 ${indexDataset.snapshot_id||"未知"} · 更新时间 ${indexDataset.updatedAt||"未记录"}`;
  return result;
};
const originalRenderForPrismClass=render;render=function(){const prism=isPrismDashboard();document.body.classList.toggle("prism-active",prism);document.getElementById("etf-metrics").classList.toggle("hidden",prism);if(prism){endDate.removeAttribute("min");endDate.max=currentLocalIsoDate()}return originalRenderForPrismClass()};
function resizeCharts(){requestAnimationFrame(()=>requestAnimationFrame(()=>{stylePrismRatioCorrect();const prism=isPrismDashboard();Object.entries(charts).forEach(([key,chart])=>{if(!chart)return;if(prism&&["prismMain","ratio","spread","rsi"].includes(key)){chart.setOption({legend:{top:2,bottom:null,type:"scroll",left:58,right:16},grid:{top:38,bottom:key==="rsi"?50:20},xAxis:{axisLabel:{show:key==="rsi",rotate:0}}})}else{chart.setOption({legend:{bottom:10},grid:{bottom:105}})}chart.resize()});if(prism)prismUpdateAxisLabels()}))}

function downloadDashboardTableCsv(table, filename) {
  const bodyRows = [...table.tBodies[0]?.rows || []];
  if (!bodyRows.length) {
    message.textContent = "当前看板没有可导出的交易日数据。";
    message.dataset.state = "warning";
    message.classList.remove("hidden");
    return;
  }
  const escapeCell = cell => `"${cell.textContent.trim().replaceAll('"', '""')}"`;
  const rows = [table.tHead.rows[0], ...bodyRows].map(row =>
    [...row.cells].map(escapeCell).join(",")
  );
  const url = URL.createObjectURL(new Blob(["\ufeff", rows.join("\r\n")], {type: "text/csv;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
document.getElementById("download-csv")?.addEventListener("click", () =>
  downloadDashboardTableCsv(dataTable, `etf-rotation-${endDate.value}.csv`)
);
document.getElementById("download-prism-csv")?.addEventListener("click", () =>
  downloadDashboardTableCsv(prismTable, `prism-${window.activeDashboard}-${endDate.value}.csv`)
);
