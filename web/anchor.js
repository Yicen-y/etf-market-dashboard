(() => {
  const chart = echarts.init(document.getElementById('chart'));
  const pointChartA = echarts.init(document.getElementById('compare-point-a'));
  const pointChartB = echarts.init(document.getElementById('compare-point-b'));
  const $ = id => document.getElementById(id);
  const RANGE_KEY = 'anchor-history-range';
  const ZOOM_KEY = 'anchor-history-zoom';
  const fmt = value => value == null ? '—' : Number(value).toFixed(2);
  const setStatus = (message, state) => { const element = $('status'); element.textContent = message; element.dataset.state = state; };
  const syncCustomDates = () => {
    const custom = $('range').value === 'custom';
    for (const id of ['start', 'end']) $(id).closest('label').hidden = !custom;
  };
  function clearCharts() { chart.clear(); pointChartA.clear(); pointChartB.clear(); }
  const infoDialog = document.getElementById('anchor-chart-info');
  const infoCopy = document.getElementById('anchor-chart-info-copy');
  const guideDialog=document.getElementById('anchor-guide-dialog');
  document.getElementById('anchor-guide-button').addEventListener('click',async()=>{try{const guide=await (await fetch('strategy-guides.json')).json();const g=guide.anchor;const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));document.getElementById('anchor-guide-content').innerHTML=`<p>${esc(g.intro)}</p>${g.sections.map(section=>`<section><h3>${esc(section.title)}</h3>${section.type==='table'?`<table><thead><tr>${section.headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${section.rows.map(row=>`<tr>${row.map(x=>`<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table>`:section.type==='formulas'?section.items.map(x=>`<div class="anchor-guide-formula"><div class="anchor-guide-formula-label">${esc(x.label)}</div><div>${esc(x.formula)}</div><p>${esc(x.note||'')}</p></div>`).join(''):section.type==='uses'?section.items.map(x=>`<p><b>${esc(x.number)}｜${esc(x.tag)}｜${esc(x.title)}</b><br>${esc(x.text)}</p>`).join(''):section.items?`<ul>${section.items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:`<p>${esc(section.text)}</p>`}</section>`).join('')}`;guideDialog.showModal();if(window.MathJax?.startup?.promise)await window.MathJax.startup.promise;if(window.MathJax?.typesetPromise)await window.MathJax.typesetPromise([document.getElementById('anchor-guide-content')])}catch(error){document.getElementById('anchor-guide-content').textContent=`策略说明加载失败：${error.message}`;guideDialog.showModal()}});
  const explanations = [
    '指数点位显示所选全收益指数的每日收盘点位。长期均线按上方选择的均线周期计算；上轨和下轨分别是均线加上轨偏离比例、减去下轨偏离比例。它们是观察区间的参考线，不代表估值或买卖建议。',
    '相对均线偏离率 =（指数点位 ÷ 长期均线 − 1）× 100%。正值表示指数高于均线，负值表示低于均线。虚线标出上、下轨对应的偏离阈值。',
    '90日 RSI 根据最近90个交易日的平均上涨幅度和平均下跌幅度计算，用于观察近期涨跌动能。图中的参考线是本策略的观察阈值，不应单独视为买卖信号。'
  ];
  function showChartInfo(index) { infoCopy.textContent=explanations[index]; infoDialog.showModal(); }
  let data;
  function renderDataTable() {
    const table = $('anchor-table'), head = table.tHead || table.createTHead(), body = table.tBodies[0];
    head.replaceChildren(); body.replaceChildren();
    if (!data?.indexes) return;
    const view = document.querySelector('.anchor-view-button.active')?.dataset.view || 'H20903';
    const codes = view === 'all' ? Object.keys(data.indexes) : [view === 'nikkei225' ? 'NKY225_TEMP' : view];
    if (!codes.every(code => data.indexes[code]?.rows?.length)) return;
    const fields = view === 'all' ? ['close', 'ma', 'deviation', 'rsi'] : ['close', 'ma', 'upper', 'lower', 'deviation', 'rsi'];
    const names = {close:'指数点位', ma:'均线', upper:'上轨', lower:'下轨', deviation:'偏离率（%）', rsi:'RSI90'};
    const header = document.createElement('tr');
    for (const title of ['交易日', ...codes.flatMap(code => fields.map(field => `${data.indexes[code].name} ${names[field]}`))]) {
      const th = document.createElement('th'); th.scope = 'col'; th.textContent = title; header.append(th);
    }
    head.append(header);
    const byCode = Object.fromEntries(codes.map(code => [code, new Map(data.indexes[code].rows.map(row => [row.tradeDate, row]))]));
    const fragment = document.createDocumentFragment();
    for (const day of data.indexes[codes[0]].rows.map(row => row.tradeDate)) {
      const tr = document.createElement('tr');
      const values = [day, ...codes.flatMap(code => fields.map(field => {
        const value = byCode[code].get(day)?.[field];
        return value == null ? '—' : fmt(field === 'deviation' ? value * 100 : value);
      }))];
      for (const value of values) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
      fragment.append(tr);
    }
    body.append(fragment);
  }
  function render() {
    if (!data) return;
    const view = document.querySelector('.anchor-view-button.active')?.dataset.view || 'H20903';
    const single = view !== 'all';
    const viewCode = view === 'nikkei225' ? 'NKY225_TEMP' : view;
    const codes = single ? [viewCode] : Object.keys(data.indexes);
    if (!data.indexes || !codes.length || codes.some(code => !data.indexes[code]?.rows?.length)) {
      clearCharts();
      $('anchor-table').tBodies[0].replaceChildren();
      setStatus(`数据不可用：${data.data_note || '所选视图没有有效数据。'}`, 'error');
      return;
    }
    const rows = data.indexes[codes[0]].rows;
    const dates = rows.map(r => r.tradeDate);
    const series = [];
    for (const code of codes) {
      const item = data.indexes[code];
      if (single) {
        const upperLabel = `均线+${Number(data.upper_pct*100).toFixed(0)}%`;
        const lowerLabel = `均线-${Number(data.lower_pct*100).toFixed(0)}%`;
        for (const [key, name] of [['close','指数点位'],['ma','长期均线'],['upper',upperLabel],['lower',lowerLabel]])
          series.push({name,type:'line',xAxisIndex:0,yAxisIndex:0,showSymbol:false,connectNulls:false,data:item.rows.map(r => r[key])});
        series.push({name:'偏离率',type:'line',xAxisIndex:1,yAxisIndex:1,showSymbol:false,connectNulls:false,data:item.rows.map(r=>r.deviation == null ? null : r.deviation * 100),markLine:{silent:true,symbol:'none',data:[{yAxis:0},{yAxis:data.upper_pct*100},{yAxis:-data.lower_pct*100}]}});
        series.push({name:'90日RSI',type:'line',xAxisIndex:2,yAxisIndex:2,showSymbol:false,connectNulls:false,data:item.rows.map(r=>r.rsi),markLine:{silent:true,symbol:'none',data:[{yAxis:43},{yAxis:57},{yAxis:70}]}});
      } else {
        const normalized = $('comparison').value === 'normalized';
        series.push({name:item.name + (normalized ? '归一化' : '偏离率'),type:'line',showSymbol:false,connectNulls:false,data:normalized ? data.comparison.rows.map(r=>r.normalized[code]) : item.rows.map(r=>r.deviation == null ? null : r.deviation * 100)});
      }
    }
    let end = $('end').value.replaceAll('-','') || dates[dates.length - 1];
    let start = $('start').value.replaceAll('-','') || dates[0];
    if ($('range').value !== 'custom' && $('range').value !== 'all') {
      const year = Number(end.slice(0,4)) - Number($('range').value);
      start = String(year) + end.slice(4);
    } else if ($('range').value === 'all') {start = dates[0]; end = dates[dates.length-1];}
    if ($('range').value === 'custom' && ! $('start').value && ! $('end').value) {
      try {
        const savedZoom = JSON.parse(localStorage.getItem(ZOOM_KEY) || 'null');
        if (savedZoom?.start && savedZoom?.end && savedZoom.start >= dates[0] && savedZoom.end <= dates[dates.length-1] && savedZoom.start <= savedZoom.end) {
          start = savedZoom.start;
          end = savedZoom.end;
        }
      } catch {}
    }
    const startIndex=dates.findIndex(day=>day>=start);
    let endIndex=dates.length-1;
    while(endIndex>=0 && dates[endIndex]>end) endIndex--;
    if(startIndex<0 || endIndex<startIndex) { clearCharts(); $('anchor-table').tBodies[0].replaceChildren(); setStatus('所选日期范围内没有交易日，请调整起止日期。', 'warning'); return; }
    start=dates[startIndex]; end=dates[endIndex];
    const pointA=document.getElementById('compare-point-a'),pointB=document.getElementById('compare-point-b');
    pointA.classList.toggle('hidden',single); pointB.classList.toggle('hidden',single);
    document.getElementById('chart').style.height=single?'700px':'440px';
    if (!single) {
      const zoomStart=startIndex/(dates.length-1||1)*100, zoomEnd=endIndex/(dates.length-1||1)*100;
      for (const [chartInstance,code] of [[pointChartA,codes[0]],[pointChartB,codes[1]]]) {
        const item=data.indexes[code];
        chartInstance.setOption({title:{text:`${item.name}：指数点位与${data.window}日均线`,left:75,textStyle:{fontSize:14,fontWeight:600,color:'#172033'}},tooltip:{trigger:'axis'},legend:{top:24,left:75,data:['指数点位',`${data.window}日均线`]},grid:{left:75,right:30,top:65,bottom:48},xAxis:{type:'category',data:dates,axisLabel:{hideOverlap:true}},yAxis:{type:'value',scale:true},dataZoom:[{type:'inside',start:zoomStart,end:zoomEnd},{type:'slider',start:zoomStart,end:zoomEnd,bottom:5}],series:[{name:'指数点位',type:'line',showSymbol:false,data:item.rows.map(r=>r.close)},{name:`${data.window}日均线`,type:'line',showSymbol:false,data:item.rows.map(r=>r.ma)}]},true);
      }
    pointChartA.resize(); pointChartB.resize();
    } else { pointChartA.clear(); pointChartB.clear(); }
    const axisCount = single ? 3 : 1;
    const indices = Array.from({length:axisCount},(_,i)=>i);
    const titles = single ? [
      {text:`${data.indexes[codes[0]].name}：指数点位与${data.window}日均线`,left:75,top:0},
      {text:'相对均线偏离率',left:75,top:'45%'},
      {text:'90日RSI',left:75,top:'70%'}
    ] : [{text:$('comparison').value === 'normalized' ? '双指数归一化全收益对比' : '双指数相对均线偏离率对比',left:75,top:0}];
    titles.forEach(title => { title.textStyle = {fontSize:14,fontWeight:600,color:'#172033'}; });
    const legends = single ? [
      {show:true,top:24,left:75,right:30,type:'scroll',data:['指数点位','长期均线',`均线+${Number(data.upper_pct*100).toFixed(0)}%`,`均线-${Number(data.lower_pct*100).toFixed(0)}%`]},
    ] : [{show:true,top:24,left:75,right:30,type:'scroll',data:series.map(item=>item.name)}];
    const graphic = single ? [
      {type:'text',left:380,top:0,style:{text:'!',font:'bold 13px sans-serif',fill:'#2563eb',backgroundColor:'#eff6ff',borderColor:'#93c5fd',borderWidth:1,borderRadius:10,padding:[2,7]},cursor:'pointer',onclick:()=>showChartInfo(0)},
      {type:'text',left:225,top:'45%',style:{text:'!',font:'bold 13px sans-serif',fill:'#2563eb',backgroundColor:'#eff6ff',borderColor:'#93c5fd',borderWidth:1,borderRadius:10,padding:[2,7]},cursor:'pointer',onclick:()=>showChartInfo(1)},
      {type:'text',left:155,top:'70%',style:{text:'!',font:'bold 13px sans-serif',fill:'#2563eb',backgroundColor:'#eff6ff',borderColor:'#93c5fd',borderWidth:1,borderRadius:10,padding:[2,7]},cursor:'pointer',onclick:()=>showChartInfo(2)}
    ] : [];
    chart.resize();
    chart.setOption({title:titles,graphic,tooltip:{trigger:'axis',formatter:params=>{const i=params[0]?.dataIndex;if(i==null)return '';return [dates[i],...codes.map(code=>{const r=data.indexes[code].rows[i];return `${data.indexes[code].name}<br>点位 ${fmt(r.close)} · 均线 ${fmt(r.ma)}<br>均线+${Number(data.upper_pct*100).toFixed(0)}% ${fmt(r.upper)} · 均线-${Number(data.lower_pct*100).toFixed(0)}% ${fmt(r.lower)}<br>偏离 ${fmt(r.deviation==null?null:r.deviation*100)}% · 90日RSI ${fmt(r.rsi)}<br>质量 ${r.quality} / 来源待核验`;})].join('<br>');}},legend:legends,axisPointer:{link:[{xAxisIndex:'all'}]},grid:single?[{left:75,right:30,top:65,height:'33%'},{left:75,right:30,top:'51%',height:'17%'},{left:75,right:30,top:'75%',height:'13%'}]:[{left:75,right:30,top:65,bottom:95}],xAxis:indices.map(i=>({type:'category',gridIndex:i,data:dates,axisLabel:{show:i===axisCount-1}})),yAxis:indices.map(i=>({type:'value',gridIndex:i,scale:true,axisLabel:{formatter:single ? (i===1?'{value}%':'{value}') : ($('comparison').value==='deviation'?'{value}%':'{value}')}})),dataZoom:[{type:'inside',xAxisIndex:indices,startValue:start,endValue:end},{type:'slider',xAxisIndex:indices,startValue:start,endValue:end,bottom:35}],series},true);
    const last = rows[rows.length-1];
    const statusMessage = view === 'nikkei225'
      ? `日经225指数点位（价格指数，不是日经全收益指数）· Wind中文名称查询临时数据，代码映射待核验 · 最近交易日 ${last.tradeDate} · 点位 ${fmt(last.close)} / ${data.window}日均线 ${fmt(last.ma)} / 偏离 ${fmt(last.deviation == null ? null : last.deviation*100)}% / 90日RSI ${fmt(last.rsi)} · 异常候选 ${data.indexes[codes[0]].anomalies.length} 个`
      : `快照 ${data.snapshot_id} · 更新 ${data.updated_at} · 最近交易日 ${last.tradeDate} · ${single ? `点位 ${fmt(last.close)} / 均线 ${fmt(last.ma)} / 偏离 ${fmt(last.deviation == null ? null : last.deviation*100)}% / 90日RSI ${fmt(last.rsi)}` : `共同基准日 ${data.comparison.baseDate}`} · 历史来源待核验 · 相对快照参考日历 ${data.calendar_reference} 缺失 ${codes.map(c=>data.indexes[c].missing_dates.length).join(' / ')} 个 · 已阻断 ${codes.map(c=>data.indexes[c].blocked_dates.length).join(' / ')} 个 · 未解决质量记录 ${codes.map(c=>data.indexes[c].open_quality_issues.length).join(' / ')} 个 · 异常候选 ${codes.map(c=>data.indexes[c].anomalies.length).join(' / ')} 个`;
    setStatus(statusMessage, 'warning');
    if (!$('anchor-table-region').hidden) renderDataTable();
  }
  async function load() {
    setStatus('正在读取数据…', 'loading');
    try {
      const base = $('base').value.replaceAll('-','');
      const activeView = document.querySelector('.anchor-view-button.active')?.dataset.view || 'H20903';
      const endpointCode = activeView === 'nikkei225' ? 'nikkei225' : 'all';
      const response = await fetch(`/api/anchor/metrics?index_code=${endpointCode}&ma_window=${$('window').value}&base_date=${base}&upper_pct=${Number($('upper').value)/100}&lower_pct=${Number($('lower').value)/100}`);
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '请求参数无效');
      if (!result || typeof result.indexes !== 'object' || result.indexes === null) throw new Error('接口响应缺少指数数据');
      data = result;
      render();
    } catch (error) { data = null; clearCharts(); $('anchor-table').tBodies[0].replaceChildren(); setStatus(`数据不可用：${error.message}`, 'error'); }
  }
  const rangeSelect = $('range');
  $('anchor-table-toggle').addEventListener('click', event => {
    const region = $('anchor-table-region'); region.hidden = !region.hidden;
    event.currentTarget.setAttribute('aria-expanded', String(!region.hidden));
    event.currentTarget.textContent = region.hidden ? '展开交易日数据' : '收起交易日数据';
    if (!region.hidden) renderDataTable();
  });
  const savedRange = localStorage.getItem(RANGE_KEY);
  if (savedRange && [...rangeSelect.options].some(option => option.value === savedRange)) rangeSelect.value = savedRange;
  syncCustomDates();
  for (const button of document.querySelectorAll('.anchor-view-button')) button.addEventListener('click',()=>{document.querySelectorAll('.anchor-view-button').forEach(item=>item.classList.toggle('active',item===button));load()});
  for (const id of ['comparison','start','end']) $(id).addEventListener('change',render);
  rangeSelect.addEventListener('change',()=>{localStorage.setItem(RANGE_KEY,rangeSelect.value);syncCustomDates();if(rangeSelect.value!=='custom')localStorage.removeItem(ZOOM_KEY);render()});
  chart.on('datazoom', event => {
    if ($('range').value !== 'custom' || $('start').value || $('end').value) return;
    const zoom = event.batch?.[0] || event;
    const start = String(zoom.startValue ?? '');
    const end = String(zoom.endValue ?? '');
    if (/^\d{8}$/.test(start) && /^\d{8}$/.test(end)) localStorage.setItem(ZOOM_KEY, JSON.stringify({start,end}));
  });
  for (const id of ['window','base','upper','lower']) $(id).addEventListener('change',load);
  window.addEventListener('resize',()=>{chart.resize();pointChartA.resize();pointChartB.resize()}); load();
})();
