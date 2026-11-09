(() => {
  const $ = id => document.getElementById(id);
  const names = {DCA_ALWAYS:'持续定投',DCA_ANCHOR:'五年之锚定投',REBAL_CALENDAR:'定期再平衡（现金代理）',REBAL_ANCHOR:'事件再平衡（现金代理）'};
  const chart = echarts.init($('bt-chart'));
  let results = [];
  const percent = n => n == null ? '不可计算' : `${(n*100).toFixed(2)}%`;
  const money = n => Number(n).toFixed(2);
  async function payload() {
    const snapshotResponse = await fetch('/api/snapshot');
    if (!snapshotResponse.ok) throw new Error('无法读取数据快照');
    const snapshot = await snapshotResponse.json();
    return {index_code:$('bt-index').value, strategy_mode:'DCA_ANCHOR', data_snapshot_id:snapshot.snapshot_id, start_date:$('bt-start').value, end_date:$('bt-end').value, asset_mode:'theoretical_index', ma_window:Number($('window').value), upper_pct:Number($('upper').value)/100, lower_pct:Number($('lower').value)/100, contribution:Number($('bt-amount').value), initial_cash:Number($('bt-initial').value), equity_weight:Number($('bt-weight').value)/100, rebalance_frequency:$('bt-frequency').value, commission_rate:Number($('bt-commission').value)/100, slippage_rate:Number($('bt-slippage').value)/100};
  }
  async function post(url, body) {
    const response = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '参数有误，请检查输入');
    return result;
  }
  function showResults() {
    $('bt-results').replaceChildren();
    $('bt-details').replaceChildren();
    const series=[];
    for (const result of results) {
      const tr=document.createElement('tr');
      for (const value of [names[result.strategy],money(result.initialInvestment),money(result.finalValue),percent(result.twr),percent(result.xirr),percent(result.maxDrawdown),money(result.cash),money(result.totalFees),result.tradeCount]) {
        const td=document.createElement('td'); td.textContent=value; tr.appendChild(td);
      }
      $('bt-results').appendChild(tr);
      const detail=document.createElement('p'); detail.textContent=`${names[result.strategy]}：年化TWR ${percent(result.annualizedTwr)}，年化波动 ${percent(result.annualizedVolatility)}，信号 ${result.signalCount} 次，平均权益仓位 ${percent(result.averageEquityWeight)}，滑点成本 ${money(result.totalSlippage)}，最长暂停 ${result.longestPauseTradingDays} 个交易日${result.endingPaused?'（期末仍暂停，暂停长度受回测边界截断）':''}。`; $('bt-details').appendChild(detail);
      for (const [axis,key] of [[0,'unitNav'],[1,'drawdown'],[2,'equityWeight']])
        series.push({name:names[result.strategy],type:'line',xAxisIndex:axis,yAxisIndex:axis,showSymbol:false,connectNulls:false,data:result.valuations.map(r=>key==='unitNav'?r[key]:r[key]*100)});
    }
    const dates=results[0].valuations.map(r=>r.tradeDate);
    chart.setOption({title:[{text:'策略与基准单位净值',left:70,top:0},{text:'回撤对比',left:70,top:'36%'},{text:'权益仓位变化',left:70,top:'62%'}].map(t=>({...t,textStyle:{fontSize:14,fontWeight:600,color:'#172033'}})),tooltip:{trigger:'axis'},legend:{bottom:0},axisPointer:{link:[{xAxisIndex:'all'}]},grid:[{left:70,right:30,top:30,height:'28%'},{left:70,right:30,top:'40%',height:'19%'},{left:70,right:30,top:'66%',height:'19%'}],xAxis:[0,1,2].map(i=>({type:'category',gridIndex:i,data:dates,axisLabel:{show:i===2}})),yAxis:[{type:'value',gridIndex:0,name:'单位净值',scale:true},{type:'value',gridIndex:1,name:'回撤%',scale:true},{type:'value',gridIndex:2,name:'权益仓位%',min:0,max:100}],dataZoom:[{type:'inside',xAxisIndex:[0,1,2]},{type:'slider',xAxisIndex:[0,1,2],bottom:30}],series},true);
    $('download-backtest').disabled=false;
  }
  $('run-backtest').addEventListener('click',async()=>{
    $('bt-status').textContent='正在计算四组理论回测…'; $('run-backtest').disabled=true;
    try {
      const base=await payload();
      results=await Promise.all(Object.keys(names).map(strategy_mode=>post('/api/anchor/backtest',{...base,strategy_mode})));
      showResults(); $('bt-status').textContent=`数据快照 ${base.data_snapshot_id}；理论指数代理、零收益现金、T+1收盘执行；历史来源待核验。定投组与股债组资产暴露不同。`;
    } catch (error) { $('bt-status').textContent=`回测失败：${error.message}`; }
    finally {$('run-backtest').disabled=false;}
  });
  $('run-research').addEventListener('click',async()=>{
    $('bt-status').textContent='正在进行固定阈值与滚动样本外研究…'; $('run-research').disabled=true;
    try {
      const base=await payload();
      const thresholds=$('research-thresholds').value.split(/[,，]/).map(x=>Number(x.trim())/100);
      if (thresholds.some(x=>!Number.isFinite(x))) throw new Error('阈值列表无效');
      const r=await post('/api/anchor/robustness',{backtest:base,thresholds,train_days:Number($('research-train').value),test_days:Number($('research-test').value),quantile_window:Number($('research-quantile').value)});
      const container=$('research-results'); container.replaceChildren();
      const heading=document.createElement('h3'); heading.textContent='阈值研究（理论指数，样本外证据有限）'; container.appendChild(heading);
      for (const item of r.sensitivity) { const p=document.createElement('p'); p.textContent=`暂停阈值 ${percent(item.threshold)}：TWR ${percent(item.twr)}，XIRR ${percent(item.xirr)}，期末现金 ${money(item.cash)}，信号 ${item.signalCount} 次，最长暂停 ${item.longestPauseTradingDays} 个交易日${item.endingPaused?'（期末仍暂停）':''}，成交 ${item.tradeCount} 次`; container.appendChild(p); }
      { const p=document.createElement('p'); const q=r.quantileBacktest; p.textContent=q.status==='READY' ? `滚动80%分位研究（可用区间 ${q.effectiveStart}—${q.end}）：TWR ${percent(q.twr)}，持续定投 ${percent(q.baselineTwr)}，固定阈值策略 ${percent(q.fixedThresholdTwr)}；XIRR ${percent(q.xirr)}，现金 ${money(q.cash)}，成交 ${q.tradeCount} 次` : `滚动分位回测不可用：${q.reason}`; container.appendChild(p); }
      for (const fold of r.walkForward) { const p=document.createElement('p'); p.textContent=`训练 ${fold.trainStart}—${fold.trainEnd}；测试 ${fold.testStart}—${fold.testEnd}；训练选取阈值 ${percent(fold.chosenThreshold)}；测试TWR ${percent(fold.testTwr)}，持续定投 ${percent(fold.benchmarkTwr)}，差 ${percent(fold.excessTwr)}，成交 ${fold.testTrades} 次`; container.appendChild(p); }
      for (const item of r.costStress) { const p=document.createElement('p'); p.textContent=`成本压力 ${item.costMultiplier} 倍：TWR ${percent(item.twr)}，佣金 ${money(item.fees)}，滑点 ${money(item.slippageCost)}`; container.appendChild(p); }
      if (!r.walkForward.length) { const p=document.createElement('p'); p.textContent='样本不足，无法形成样本外区间。'; container.appendChild(p); }
      for (const warning of r.warnings) { const p=document.createElement('p'); p.textContent=warning; container.appendChild(p); }
      $('bt-status').textContent=`研究完成，测试 ${r.thresholdTrials} 个阈值；${r.warnings.join(' ')}`;
    } catch (error) {$('bt-status').textContent=`研究失败：${error.message}`;}
    finally {$('run-research').disabled=false;}
  });
  $('download-backtest').addEventListener('click',()=>{
    const lines=[['策略','类型','日期','信号日','方向/状态','数量','价格','费用','现金','权益市值','总资产','外部流入','单位净值','回撤','权益仓位','原因','滑点成本']];
    for (const result of results) {
      for (const v of result.valuations) lines.push([names[result.strategy],'每日估值',v.tradeDate,'','','','','',v.cash,v.equityValue,v.totalValue,v.externalFlow,v.unitNav,v.drawdown,v.equityWeight]);
      for (const f of result.fills) lines.push([names[result.strategy],'成交',f.date,f.signalDate||'',f.side,f.quantity,f.price,f.fee,'','','','','','','',f.reason,f.slippageCost]);
      for (const o of result.orders) lines.push([names[result.strategy],'订单',o.date,o.signalDate||'',o.status,'','','','','','','','','','',o.reason]);
    }
    const csv='\ufeff'+lines.map(row=>row.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a'); link.href=url; link.download='anchor-backtest.csv'; link.click(); URL.revokeObjectURL(url);
  });
  window.addEventListener('resize',()=>chart.resize());
})();
