(() => {
  const detail = document.querySelector('#detail');
  if (!detail) return;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));

  function draw(canvas, rows, current) {
    const ready = rows.filter(row => row.status === 'READY' && Number.isFinite(Number(row.value_pct)));
    if (!ready.length) return;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 640, height = 220;
    canvas.width = width * ratio; canvas.height = height * ratio;
    const ctx = canvas.getContext('2d'); ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const values = ready.map(row => Number(row.value_pct));
    const min = Math.min(...values, Number(current)), max = Math.max(...values, Number(current));
    const span = max - min || 1;
    const x = i => 24 + i * (width - 40) / Math.max(1, ready.length - 1);
    const y = value => height - 24 - (value - min) / span * (height - 48);
    ctx.strokeStyle = '#2c6bed'; ctx.lineWidth = 2; ctx.beginPath();
    ready.forEach((row, i) => i ? ctx.lineTo(x(i), y(Number(row.value_pct))) : ctx.moveTo(x(i), y(Number(row.value_pct))));
    ctx.stroke();
    if (Number.isFinite(Number(current))) {
      ctx.strokeStyle = '#d64545'; ctx.setLineDash([6, 4]); ctx.beginPath();
      ctx.moveTo(24, y(Number(current))); ctx.lineTo(width - 16, y(Number(current))); ctx.stroke(); ctx.setLineDash([]);
    }
    ctx.fillStyle = '#64748b'; ctx.font = '12px sans-serif';
    ctx.fillText(`${ready[0].trade_date} — ${ready[ready.length - 1].trade_date}`, 24, 16);
    ctx.fillText(`${min.toFixed(2)}% — ${max.toFixed(2)}%`, 24, height - 6);
  }

  async function loadHistory(securityId) {
    try {
      const response = await fetch(`/api/dividend/provider-yields/${encodeURIComponent(securityId)}/history`);
      if (!response.ok) return;
      const data = await response.json();
      if (data.security?.security_type !== 'STOCK') return;
      if (detail.classList.contains('hidden')) return;
      detail.querySelector('.dividend-provider-history')?.remove();
      const summary = data.summary || {};
      const section = document.createElement('section');
      section.className = 'dividend-provider-history';
      section.innerHTML = `<h3>Wind历史股息率与历史百分位</h3>
        <p class="dividend-muted">口径：${esc(data.metric_label)}；缺失和失败日期不参与统计。</p>
        <div class="dividend-grid dividend-history-stats">
          <div class="dividend-card">当前股息率<strong>${esc(data.current_value_pct ?? '—')}${data.current_value_pct == null ? '' : '%'}</strong></div>
          <div class="dividend-card">历史百分位<strong>${esc(summary.percentile ?? '—')}${summary.percentile == null ? '' : '%'}</strong></div>
          <div class="dividend-card">历史均值 / 中位数<strong>${esc(summary.mean ?? '—')}% / ${esc(summary.median ?? '—')}%</strong></div>
          <div class="dividend-card">历史最低 / 最高<strong>${esc(summary.minimum ?? '—')}% / ${esc(summary.maximum ?? '—')}%</strong></div>
        </div>
        <canvas class="dividend-provider-history-chart" aria-label="Wind历史股息率走势图"></canvas>
        <p class="dividend-muted">有效样本 ${esc(summary.sample_count ?? 0)} 条；历史区间 ${esc(data.rows?.[0]?.trade_date || '—')} 至 ${esc(data.rows?.[data.rows.length - 1]?.trade_date || '—')}；失败/缺失 ${esc(data.missing_dates?.length || 0)} 天。</p>`;
      detail.appendChild(section);
      draw(section.querySelector('canvas'), data.rows || [], data.current_value_pct);
    } catch (_) {
      // The existing detail remains usable when the optional history query fails.
    }
  }

  document.addEventListener('click', event => {
    const target = event.target.closest('[data-view]');
    if (!target) return;
    const id = target.dataset.view;
    let attempts = 0;
    const retry = () => {
      if (!detail.classList.contains('hidden')) return loadHistory(id);
      if (++attempts < 10) window.setTimeout(retry, 250);
    };
    window.setTimeout(retry, 250);
  });
})();
