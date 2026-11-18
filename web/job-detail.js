(function(){
  const $=id=>document.getElementById(id);
  const labels={PUBLISHED:"已发布",UPDATED:"已更新",NO_NEW_ROWS:"暂无新记录",FAILED:"失败",SKIPPED:"已跳过",UNKNOWN:"原因未记录",PARTIAL:"部分完成",SUCCEEDED:"成功",RUNNING:"进行中",QUEUED:"排队中",PUBLISHED_WITH_PARTIAL_FAILURE:"快照已发布，部分数据未更新",INDEX_PUBLISHED_ETF_PENDING:"指数已发布，ETF 待审核",INDEX_BEHIND_ETF:"指数日期落后于 ETF，请查看参考核验结果",INDEX_BEHIND_REFERENCE:"指数日期落后于官方参考日期",CNI_ROUTE_PENDING:"国证同日路线证据尚未齐备",FETCH_OK:"采集成功",VERIFIED:"已校验",VALIDATION_FAILED:"校验未通过",VERIFICATION_FAILED:"参考核验未完成",NOT_ATTEMPTED:"未执行",NO_WIND_CREDENTIAL:"未配置 Wind 凭证",UPSTREAM_HTTP_429:"上游返回 HTTP 429（额度或限流）",UPSTREAM_HTTP_403:"上游返回 HTTP 403（访问受限）",UPSTREAM_TIMEOUT:"上游请求超时",NIKKEI_SYNC_ERROR:"日经基准同步失败，具体原因见服务端诊断",NO_BASELINE:"尚无日经基准初始数据",LEGACY_DETAIL_NOT_RECORDED:"旧任务未保存具体失败原因",LEGACY_SUMMARY_ONLY:"旧任务只保存总体发布状态",ETF_REVIEW_REQUIRED:"ETF 候选行情待审核",ETF_SOURCE_QUARANTINED:"ETF 备用来源未通过校核",SOURCE_TRAILING_UNAVAILABLE:"来源尚未返回最新日期",FETCH_OR_VALIDATION_FAILED:"采集或校验失败"};
  const display=value=>value==null||value===""?"—":labels[value]||String(value);
  function pair(root,label,value){const box=document.createElement("div"),name=document.createElement("dt"),content=document.createElement("dd");name.textContent=label;content.textContent=display(value);box.append(name,content);root.append(box)}
  function cell(row,value){const item=document.createElement("td");item.textContent=display(value);row.append(item)}
  function render(job){const summary=$("job-detail-summary");summary.replaceChildren();
    [["任务编号",job.job_id],["状态",job.state],["阶段",job.stage],["开始",job.started_at],["结束",job.finished_at],["快照版本",job.snapshot_id],["采集",job.fetch_status],["校验",job.validation_status],["发布",job.publication_status]].forEach(([name,value])=>pair(summary,name,value));
    const body=$("job-detail-datasets");body.replaceChildren();(job.datasets||[]).forEach(item=>{const row=document.createElement("tr");if(["PARTIAL","FAILED","SKIPPED","UNKNOWN"].includes(item.state))row.className="job-result--attention";
      [item.label,item.state,item.provider,item.latest_date,item.records_added,item.records_revised,item.reason_code,item.error_type].forEach(value=>cell(row,value));body.append(row)});
    if(!body.children.length){const row=document.createElement("tr"),item=document.createElement("td");item.colSpan=8;item.textContent="此任务没有逐数据集记录；旧版任务无法再还原每条来源的具体错误。";row.append(item);body.append(row)}
    $("job-detail-explanation").textContent=job.historical_detail_incomplete?"这条任务生成于逐数据集结果功能上线前。仅能确认任务保存的总体状态和快照版本；逐数据集来源、数量及失败原因没有留证。":"下表来自本任务保存的逐数据集结果；错误信息只展示脱敏类别。";
    const failed=(job.datasets||[]).filter(item=>["PARTIAL","FAILED","SKIPPED","UNKNOWN"].includes(item.state));
    $("job-detail-next").textContent=job.state==="PARTIAL"&&job.snapshot_id?`快照 ${job.snapshot_id} 已发布；${failed.map(item=>item.label).join("、")||"部分数据"}尚未完整更新，请按上表日期和原因复核。`:job.state==="FAILED"?"本次任务未完成发布。请查看上表原因；此前有效快照继续可用。":failed.length?"请复核上表中的跳过或失败项目。":"本任务没有记录待处理的数据集。";
    $("job-detail-message").textContent=`任务 ${job.job_id} · ${display(job.state)}`;
  }
  async function load(){const id=new URLSearchParams(location.search).get("job");if(!id||!/^[a-f0-9]{32}$/.test(id)){$("job-detail-message").textContent="任务编号无效；请从数据中心选择任务。";return}
    try{const response=await fetch(`/api/jobs/${encodeURIComponent(id)}/details`);if(response.status===404){
      const summary=await fetch(`/api/jobs/${encodeURIComponent(id)}`);if(summary.ok){render({...await summary.json(),datasets:[],historical_detail_incomplete:true});
        $("job-detail-message").textContent="服务仍运行旧版：已显示任务概况。重启本地看板后可查看逐数据集明细。";return}}
      if(!response.ok)throw Error(`HTTP ${response.status}`);render(await response.json())}
    catch(error){$("job-detail-message").textContent=`任务详情读取失败：${error.message}`}}
  load();
})();
