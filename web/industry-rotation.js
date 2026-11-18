(function () {
  const $ = id => document.getElementById(id);
  const theme = window.DashboardChartTheme;
  const chartIds = ['industry-main-chart', 'industry-ratio-chart', 'industry-spread-chart', 'industry-rsi-chart'];
  const charts = chartIds.map(id => theme.init($(id)));
  const rangeButtons = [...document.querySelectorAll('[data-industry-range]')];
  const rangeStorageKey = 'industry-rotation-time-range';
  const savedRange = localStorage.getItem(rangeStorageKey);
  let rangeKey = ['6m', '1y', '3y', '5y', 'all'].includes(savedRange) ? savedRange : '1y';
  let payload = null;
  let rows = [];
  let dates = [];
  let returnA = [];
  let returnB = [];
  let requestId = 0;
  let lockedIndex = null;
  let syncing = false;
  let customZoom = null;
  let visibleEnd = 0;

  const dateLabel = key => String(key).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3');
  const totalReturnName = name => name.endsWith('全收益') ? name : `${name}全收益`;
  const percent = value => theme.formatPercent(value);
  const number = (value, digits = 3) => value == null ? '—' : Number(value).toFixed(digits);
  const line = (name, data, color, type = 'solid') => ({
    name, type: 'line', data, showSymbol: false, connectNulls: false,
    lineStyle: { width: 2, color, type }, itemStyle: { color }
  });

  async function get(url) {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    return response.json();
  }

  function chartOption(series, percentAxis = false, rsiAxis = false, slider = false) {
    return {
      animation: false,
      tooltip: { trigger: 'axis', confine: true, axisPointer: { type: 'cross', snap: true } },
      legend: { top: 5, left: 70, type: 'scroll' },
      grid: { left: 70, right: 25, top: 46, bottom: slider ? 76 : 48 },
      xAxis: {
        type: 'category', data: dates, boundaryGap: false,
        axisPointer: { show: true, type: 'line', snap: true },
        axisLabel: { color: '#64748b', hideOverlap: true, formatter: value => dateLabel(value).slice(0, 7) }
      },
      yAxis: {
        type: 'value', scale: !rsiAxis, min: rsiAxis ? 0 : undefined, max: rsiAxis ? 100 : undefined,
        axisLabel: { color: '#64748b', formatter: percentAxis ? value => `${(value * 100).toFixed(0)}%` : '{value}' },
        splitLine: { lineStyle: { color: '#e2e8f0' } }
      },
      dataZoom: [
        { type: 'inside', filterMode: 'none', start: 0, end: 100 },
        ...(slider ? [{ type: 'slider', filterMode: 'none', start: 0, end: 100, bottom: 8, height: 20 }] : [])
      ],
      series
    };
  }

  function snapshot(index) {
    if (!rows.length) return;
    const safe = Math.max(0, Math.min(rows.length - 1, index));
    const row = rows[safe];
    const lead = row.return40Spread == null ? '相对强弱待计算'
      : row.return40Spread > 0 ? `${payload.name}近40日相对占优`
      : row.return40Spread < 0 ? '万得全A近40日相对占优' : '近40日收益持平';
    const observation = $('industry-observation');
    observation.replaceChildren();
    for (const [label, value] of [
      ['当前观察日', dateLabel(row.tradeDate)],
      ['当前研究信号', lead],
      ['40日收益差', percent(row.return40Spread)],
      ['RSI(14)', number(row.rsi14, 1)]
    ]) {
      const cell = document.createElement('div');
      const caption = document.createElement('span');
      const strong = document.createElement('strong');
      caption.textContent = label;
      strong.textContent = value;
      cell.append(caption, strong);
      observation.append(cell);
    }
    const note = document.createElement('small');
    note.textContent = '历史研究观察，不构成交易指令；缺失指标不补值。';
    observation.append(note);
    const metrics = [
      ['交易日', dateLabel(row.tradeDate), 'prism-snapshot-date'],
      [`${payload.name}累计收益`, percent(returnA[safe])],
      ['万得全A累计收益', percent(returnB[safe])],
      ['相对比值', number(row.ratio)],
      ['242日均线', number(row.ratioMa242)],
      ['40日收益差', percent(row.return40Spread)],
      ['RSI(14)', number(row.rsi14, 1)]
    ];
    const container = $('industry-snapshot');
    container.replaceChildren();
    for (const [label, value, extra] of metrics) {
      const cell = document.createElement('div');
      cell.className = `prism-snapshot-item ${extra || ''}`;
      const caption = document.createElement('span');
      const strong = document.createElement('strong');
      caption.textContent = label;
      strong.textContent = value;
      cell.append(caption, strong);
      container.append(cell);
    }
    $('industry-selected-date').textContent = `当前观察日：${dateLabel(row.tradeDate)} · ${lockedIndex == null ? '未锁定' : '已锁定'}`;
    $('industry-unlock').classList.toggle('hidden', lockedIndex == null);
  }

  function syncZoom(start, end, manual = false) {
    if (!dates.length) return;
    const left = Math.max(0, Math.min(100, Number(start) || 0));
    const right = Math.max(left, Math.min(100, end == null ? 100 : Number(end)));
    const first = Math.round(left * (dates.length - 1) / 100);
    const last = Math.round(right * (dates.length - 1) / 100);
    visibleEnd = last;
    syncing = true;
    charts.forEach(chart => chart.dispatchAction({ type: 'dataZoom', start: left, end: right }));
    syncing = false;
    const visible = last - first + 1;
    const monthStep = visible > 1200 ? 6 : visible > 650 ? 3 : visible > 300 ? 2 : 1;
    charts.forEach(chart => chart.setOption({ xAxis: { axisLabel: {
      interval: (index, value) => index === first ||
        (dates[index - 1]?.slice(0, 6) !== String(value).slice(0, 6) &&
          (Number(String(value).slice(4, 6)) - 1) % monthStep === 0)
    } } }));
    $('industry-view-range').textContent = `显示区间：${dateLabel(dates[first])} 至 ${dateLabel(dates[last])}`;
    if (lockedIndex != null && (lockedIndex < first || lockedIndex > last)) unlock();
    if (lockedIndex == null) snapshot(visibleEnd);
    if (manual) { rangeKey = 'custom'; customZoom = { start: left, end: right }; }
    rangeButtons.forEach(button => {
      const active = button.dataset.industryRange === rangeKey;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
  }

  function setRange(key) {
    if (!dates.length) return;
    rangeKey = key;
    customZoom = null;
    localStorage.setItem(rangeStorageKey, key);
    const months = { '6m': 6, '1y': 12, '3y': 36, '5y': 60 }[key];
    let first = 0;
    if (months) {
      const cutoff = new Date(`${dateLabel(dates.at(-1))}T00:00:00Z`);
      cutoff.setUTCMonth(cutoff.getUTCMonth() - months);
      const target = cutoff.toISOString().slice(0, 10).replaceAll('-', '');
      first = Math.max(0, dates.findIndex(date => date >= target));
    }
    syncZoom(first / (dates.length - 1 || 1) * 100, 100);
  }

  function showTips(index) {
    syncing = true;
    charts.forEach(chart => chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: index }));
    syncing = false;
  }

  function hideTips() {
    charts.forEach(chart => chart.dispatchAction({ type: 'hideTip' }));
  }

  function unlock() {
    lockedIndex = null;
    hideTips();
    snapshot(visibleEnd);
  }

  function draw(data) {
    hideTips();
    payload = data;
    rows = data.rows;
    dates = rows.map(row => row.tradeDate);
    const base = rows.find(row => row.values[data.code] > 0 && row.values[data.benchmarkCode] > 0)?.values;
    if (!base) throw Error('行业与万得全A没有共同交易日');
    const cumulative = (row, code) => row.values[code] > 0 ? row.values[code] / base[code] - 1 : null;
    returnA = rows.map(row => cumulative(row, data.code));
    returnB = rows.map(row => cumulative(row, data.benchmarkCode));
    lockedIndex = null;
    const pair = `${data.name}（${data.code}） / 万得全A`;
    $('industry-chart-title').textContent = `${pair}累计收益`;
    $('industry-ratio-title').textContent = `${pair}比值及242日布林线`;
    $('industry-spread-title').textContent = `${pair}的40日收益差及242日均线`;
    $('industry-rsi-title').textContent = `${pair}比值 RSI(14) 及242日均线`;
    $('industry-status').textContent = `数据截至 ${dateLabel(data.latestTradeDate)} · 拖动图表下方滑块可框选时间窗口`;
    $('industry-basis').textContent = data.basisNote;
    charts[0].setOption(chartOption([
      line(`${totalReturnName(data.name)}累计收益`, returnA, '#2c6bed'),
      line('万得全A累计收益', returnB, '#e67e32')
    ], true, false, true), true);
    charts[1].setOption(chartOption([
      line('相对比值', rows.map(row => row.ratio), '#2c6bed'),
      line('242日均线', rows.map(row => row.ratioMa242), '#e67e32', 'dashed'),
      line('上轨（+2σ）', rows.map(row => row.ratioUpper242), '#94a3b8', 'dotted'),
      line('下轨（−2σ）', rows.map(row => row.ratioLower242), '#94a3b8', 'dotted')
    ]), true);
    charts[2].setOption(chartOption([
      line('40日收益差', rows.map(row => row.return40Spread), '#2c6bed'),
      line('242日均线', rows.map(row => row.return40Ma242), '#e67e32', 'dashed')
    ], true), true);
    charts[3].setOption(chartOption([
      line('RSI(14)', rows.map(row => row.rsi14), '#9461c9'),
      line('RSI 242日均线', rows.map(row => row.rsiMa242), '#e67e32', 'dashed'),
      line('RSI 50基准线', rows.map(() => 50), '#94a3b8', 'dashed')
    ], false, true), true);
    if (rangeKey === 'custom' && customZoom) syncZoom(customZoom.start, customZoom.end, true);
    else setRange(rangeKey);
  }

  async function select(code) {
    const current = ++requestId;
    document.querySelectorAll('.industry-tab').forEach(button =>
      button.setAttribute('aria-pressed', String(button.dataset.code === code)));
    const tabs = $('industry-tabs');
    const active = [...tabs.querySelectorAll('.industry-tab')].find(button => button.dataset.code === code);
    if (active) {
      const left = active.getBoundingClientRect().left - tabs.getBoundingClientRect().left + tabs.scrollLeft;
      tabs.scrollTo({ left: left - (tabs.clientWidth - active.clientWidth) / 2, behavior: 'smooth' });
    }
    $('industry-status').textContent = '正在读取三棱镜数据…';
    try {
      const data = await get(`/api/industry-rotation/prism?code=${encodeURIComponent(code)}`);
      if (current !== requestId) return;
      draw(data);
      history.replaceState(null, '', `?code=${encodeURIComponent(code)}`);
    } catch (error) {
      if (current === requestId) $('industry-status').textContent = `数据加载失败：${error.message}`;
    }
  }

  charts.forEach(chart => {
    chart.on('datazoom', () => {
      if (syncing || !dates.length) return;
      const zoom = chart.getOption().dataZoom[0];
      syncZoom(zoom.start, zoom.end, true);
    });
    chart.on('updateAxisPointer', event => {
      if (syncing || lockedIndex != null || !dates.length) return;
      const value = event.axesInfo?.find(axis => axis.axisDim === 'x')?.value;
      const index = typeof value === 'number' ? Math.round(value) : dates.indexOf(String(value));
      if (index >= 0 && index < rows.length) {
        snapshot(index);
        showTips(index);
      }
    });
    chart.on('click', event => {
      if (event.dataIndex == null) return;
      lockedIndex = event.dataIndex;
      snapshot(lockedIndex);
      showTips(lockedIndex);
    });
    chart.on('globalout', () => {
      if (lockedIndex == null && rows.length) {
        hideTips();
        snapshot(visibleEnd);
      }
    });
  });
  rangeButtons.forEach(button => button.addEventListener('click', () => setRange(button.dataset.industryRange)));
  $('industry-unlock').addEventListener('click', unlock);
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && lockedIndex != null) unlock(); });
  window.addEventListener('resize', () => charts.forEach(chart => chart.resize()));

  const guideModal = $('industry-guide-modal');
  const guideContent = $('industry-guide-content');
  const guideClose = $('industry-guide-close');
  let guide = null;
  let guideReturnFocus = null;
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  const guideText = value => escapeHtml(value)
    .replaceAll('{{A_NAME}}', escapeHtml(payload ? totalReturnName(payload.name) : '全收益指数'))
    .replaceAll('{{B_NAME}}', '万得全A');
  const guideFormula = item => `<div class="guide-formula"><div class="guide-formula-label">${guideText(item.label)}</div><div>${guideText(item.formula)}</div>${item.note ? `<p class="guide-note">${guideText(item.note)}</p>` : ''}</div>`;
  function guideSection(section) {
    let body = '';
    if (section.type === 'dynamic-pair' || section.type === 'notice') {
      body = `<div class="${section.type === 'notice' ? 'guide-notice' : 'guide-dynamic-pair'}">${guideText(section.text)}</div>`;
    } else if (section.type === 'uses') {
      body = section.items.map(item => `<article class="guide-use"><div class="guide-use-head"><span class="guide-use-number">${guideText(item.number)}</span><span class="guide-use-tag">${guideText(item.tag)}</span><span class="guide-use-title">${guideText(item.title)}</span></div><p>${guideText(item.text)}</p></article>`).join('');
    } else if (section.type === 'steps') {
      body = `<ol>${section.items.map(item => `<li>${guideText(item)}</li>`).join('')}</ol>`;
    } else {
      body = `${(section.paragraphs || []).map(item => `<p>${guideText(item)}</p>`).join('')}${(section.items || section.formulas || []).map(guideFormula).join('')}`;
    }
    return `<section class="guide-section"><h3>${guideText(section.title)}</h3>${body}</section>`;
  }
  async function openGuide() {
    guideReturnFocus = document.activeElement;
    document.querySelector('main').inert = true;
    document.body.classList.add('industry-guide-open');
    guideModal.classList.remove('hidden');
    guideClose.focus();
    guideContent.textContent = '正在加载策略说明…';
    try {
      if (!guide) guide = (await get('strategy-guides.json')).prism;
      guideContent.innerHTML = `<p class="guide-intro">${guideText(guide.intro)}</p>${guide.sections.map(guideSection).join('')}`;
      if (window.MathJax?.startup?.promise) await window.MathJax.startup.promise;
      if (window.MathJax?.typesetPromise) await window.MathJax.typesetPromise([guideContent]);
    } catch (error) {
      guideContent.textContent = `策略说明加载失败：${error.message}`;
    }
  }
  function closeGuide() {
    guideModal.classList.add('hidden');
    document.body.classList.remove('industry-guide-open');
    document.querySelector('main').inert = false;
    guideReturnFocus?.focus();
    guideReturnFocus = null;
  }
  $('industry-guide-button').addEventListener('click', openGuide);
  guideClose.addEventListener('click', closeGuide);
  guideModal.addEventListener('click', event => { if (event.target.dataset.guideClose === 'true') closeGuide(); });
  document.addEventListener('keydown', event => {
    if (guideModal.classList.contains('hidden')) return;
    if (event.key === 'Escape') { event.preventDefault(); closeGuide(); return; }
    if (event.key !== 'Tab') return;
    const focusable = [...guideModal.querySelectorAll('button:not([disabled]),a[href]')];
    if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable.at(-1).focus(); }
    else if (!event.shiftKey && document.activeElement === focusable.at(-1)) { event.preventDefault(); focusable[0].focus(); }
  });

  get('/api/industry-rotation/catalog').then(data => {
    const tabs = $('industry-tabs');
    tabs.replaceChildren();
    for (const item of data.industries) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'industry-tab';
      button.dataset.code = item.code;
      button.textContent = `${item.name} · ${item.code}`;
      button.setAttribute('aria-pressed', 'false');
      button.addEventListener('click', () => select(item.code));
      tabs.append(button);
    }
    const requested = new URLSearchParams(location.search).get('code');
    if (data.industries.length) select(data.industries.some(item => item.code === requested) ? requested : data.industries[0].code);
    else $('industry-status').textContent = '行业全收益数据尚未入库。';
  }).catch(error => {
    $('industry-tabs').textContent = '行业列表加载失败';
    $('industry-status').textContent = error.message;
  });
})();
