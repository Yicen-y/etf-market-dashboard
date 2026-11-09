(() => {
  const $ = id => document.getElementById(id);
  const chartIds = ['bond-chart-price', 'bond-chart-pe', 'bond-chart-city', 'bond-chart-spread'];
  const charts = chartIds.map(id => echarts.init($(id)));
  echarts.connect(charts);
  const state = $('bond-status');
  const rangeStorageKey = 'bond-value-time-range';
  let selectedRange = localStorage.getItem(rangeStorageKey) || 'all';
  let applyingRange = false;
  let payload = null;
  let tableRows = [];
  const format = (value, digits=2) => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(digits);
  const dateLabel = value => value ? `${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6,8)}` : '—';
  function renderDataTable() {
    const tbody = $('bond-table').tBodies[0]; tbody.replaceChildren();
    const fragment = document.createDocumentFragment();
    for (const row of tableRows) {
      const tr = document.createElement('tr');
      const values = [dateLabel(row.tradeDate), format(row.close), format(row.pe), format(row.roePct), format(row.cityEarningsRatio), format(row.earningsYieldPct), format(row.bondYieldPct), format(row.equityBondValuePp)];
      for (const value of values) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
      fragment.append(tr);
    }
    tbody.append(fragment);
  }
  $('bond-table-toggle').addEventListener('click', event => {
    const region = $('bond-table-region'); region.hidden = !region.hidden;
    event.currentTarget.setAttribute('aria-expanded', String(!region.hidden));
    event.currentTarget.textContent = region.hidden ? '展开交易日数据' : '收起交易日数据';
    if (!region.hidden) renderDataTable();
  });
  const guide = $('bond-guide');
  $('bond-guide-button').addEventListener('click', async () => {
    guide.showModal();
    if (window.MathJax?.startup?.promise) await window.MathJax.startup.promise;
    if (window.MathJax?.typesetPromise) await window.MathJax.typesetPromise([guide]);
  });
  $('bond-refresh').addEventListener('click', async () => {
    $('bond-refresh').disabled = true;
    state.textContent = '正在通过 Wind MCP 与 AkShare 刷新数据，历史回填可能需要一些时间……';
    try {
      const response = await fetch('/api/bond-value/refresh', {method:'POST'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || '数据刷新失败');
      payload = result;
      render();
    } catch (error) {
      state.textContent = `刷新失败，已保留上次成功数据：${error.message}`;
    } finally { $('bond-refresh').disabled = false; }
  });
  document.querySelectorAll('.bond-value-range-button').forEach(button => button.addEventListener('click', () => {
    selectedRange = button.dataset.range;
    localStorage.setItem(rangeStorageKey, selectedRange);
    render();
  }));
  charts.forEach(chart => chart.on('datazoom', () => {
    if (applyingRange) return;
    selectedRange = 'custom';
    document.querySelectorAll('.bond-value-range-button').forEach(button => {
      button.classList.remove('active');
      button.setAttribute('aria-pressed', 'false');
    });
  }));
  function chartOption(title, rows, field, unit, color, zoom) {
    const dates = rows.map(row => dateLabel(row.tradeDate));
    const values = rows.map(row => row[field]);
    const isSpread = field === 'equityBondValuePp';
    const axisFormatter = isSpread
      ? value => Number(value).toFixed(1)
      : `{value}${unit}`;
    return {animation:false, grid:{left:66,right:28,top:24,bottom:58}, tooltip:{trigger:'axis',confine:true,formatter:items=>{
      const i=items[0]?.dataIndex;if(i==null)return '';const row=rows[i];
      const lines=[dateLabel(row.tradeDate),`${title}：${format(row[field])}${isSpread?'%':unit}`];
      if(field==='cityEarningsRatio') lines.push(`PE ${format(row.pe)} · ROE ${format(row.roePct)}%（${row.roeSource==='WIND'?'Wind':'PE/PB推导'}）`);
      if(field==='equityBondValuePp') lines.push(`盈利收益率 ${format(row.earningsYieldPct)}% · 中债10Y ${format(row.bondYieldPct)}%（${dateLabel(row.bondYieldDate)}）`);
      if(field==='close') lines.push('价格指数收盘点位 · Wind MCP');
      return lines.join('<br>');}}, xAxis:{type:'category',data:dates,boundaryGap:false,axisLabel:{hideOverlap:true}}, yAxis:{type:'value',scale:true,inverse:isSpread,splitNumber:isSpread?5:undefined,axisLabel:{formatter:axisFormatter,showMinLabel:true,showMaxLabel:true,hideOverlap:false},splitLine:{lineStyle:{color:'#e8edf5'}}}, dataZoom:[{type:'inside',start:zoom.start,end:zoom.end},{type:'slider',start:zoom.start,end:zoom.end,height:18,bottom:8}], series:[{name:title,type:'line',data:values,showSymbol:false,connectNulls:false,smooth:false,lineStyle:{width:2,color},itemStyle:{color},areaStyle:isSpread?{color,opacity:.08}:undefined}]};
  }
  function render() {
    if (!payload) return;
    const rowsAll=payload.rows||[];
    if (!rowsAll.length) {
      tableRows = []; renderDataTable();
      charts.forEach(chart=>chart.clear());
      state.textContent='本地尚无股债性价比历史数据。点击“刷新数据”尝试从Wind MCP和AkShare获取；授权或上游不可用时会显示具体错误。';
      $('bond-coverage').textContent='暂无';$('bond-latest').textContent='—';$('bond-roe-source').textContent='—';$('bond-sources').textContent='';return;
    }
    const end=rowsAll[rowsAll.length-1].tradeDate;
    const rangeMonths={'6m':6,'1y':12,'3y':36,'5y':60}[selectedRange];
    let cutoff='00000000';
    if(rangeMonths){const target=new Date(`${dateLabel(end)}T00:00:00Z`);target.setUTCMonth(target.getUTCMonth()-rangeMonths);cutoff=target.toISOString().slice(0,10).replaceAll('-','');}
    const startIndex=Math.max(0,rowsAll.findIndex(row=>row.tradeDate>=cutoff));
    const zoom={start:0,end:100};
    const rows=rowsAll.slice(startIndex);
    tableRows = rows;
    if (!$('bond-table-region').hidden) renderDataTable();
    document.querySelectorAll('.bond-value-range-button').forEach(button=>{
      const active=button.dataset.range===selectedRange;
      button.classList.toggle('active',active);
      button.setAttribute('aria-pressed',String(active));
    });
    applyingRange=true;
    charts.forEach((chart,index)=>chart.setOption([
      chartOption('指数点位',rows,'close','', '#2563eb',zoom),
      chartOption('PE',rows,'pe','倍','#7c3aed',zoom),
      chartOption('市赚率',rows,'cityEarningsRatio','倍','#0f766e',zoom),
      chartOption('股债性价比',rows,'equityBondValuePp','%','#d97706',zoom),
    ][index],true));
    applyingRange=false;
    const first=rowsAll[0],last=rowsAll[rowsAll.length-1];
    const valuationPct=payload.coverage?.valuationCoveragePct;
    $('bond-coverage').textContent=`${dateLabel(first.tradeDate)} — ${dateLabel(last.tradeDate)}（${payload.coverage?.count||rowsAll.length}日，估值覆盖${valuationPct ?? '—'}%）`;
    $('bond-latest').textContent=dateLabel(last.tradeDate);
    $('bond-roe-source').textContent=last.roeSource==='WIND'?'Wind直接ROE':last.roeSource==='PE_PB_IMPLIED'?'PE/PB隐含ROE':'不可用';
    $('bond-sources').textContent=`数据来源：${Object.values(payload.sources||{}).join('；')}。国债收益率按不晚于沪深300交易日的最近可用观测匹配；历史ROE为PE/PB推导隐含值。`;
    state.textContent=`最近行情日 ${dateLabel(last.tradeDate)} · PE/PB有效覆盖${valuationPct ?? '—'}% · Wind行情与估值 / AkShare中债10Y · 刷新时间 ${payload.updatedAt||'—'} · 最近有效ROE来源：${last.roeSource==='WIND'?'Wind直接值':last.roeSource==='PE_PB_IMPLIED'?'PE/PB推导值':'缺失'}`;
  }
  async function load(){
    try { const response=await fetch('/api/bond-value/hs300');payload=await response.json();if(!response.ok)throw new Error(payload.detail||'读取失败');render(); }
    catch(error){state.textContent=`数据读取失败：${error.message}`;charts.forEach(chart=>chart.clear());}
  }
  window.addEventListener('resize',()=>charts.forEach(chart=>chart.resize()));
  load();
})();
