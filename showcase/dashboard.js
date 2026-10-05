(() => {
  'use strict';

  const el = id => document.getElementById(id);
  const data = JSON.parse(el('dashboard-data').textContent);
  const numbers = new Intl.NumberFormat('en-US');
  const decimals = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const monthFormatter = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
  const money = value => 'R$ ' + decimals.format(value);
  const percent = value => decimals.format(value) + '%';
  const monthName = month => monthFormatter.format(new Date(month + '-01T00:00:00Z'));
  const compact = value => value >= 1000000 ? (value / 1000000).toFixed(1) + 'M'
    : value >= 1000 ? Math.round(value / 1000) + 'K' : Math.round(value).toString();
  let chartMetric = 'value';
  let selectedMonth = data.months.at(-1);
  let offlineMetric = null;

  // Views retain legacy links, while keeping only one page visible at a time.
  const aliases = { resumen: 'overview', tendencias: 'overview', consultas: 'questions', solucion: 'engineering', metodologia: 'engineering' };
  const views = [...document.querySelectorAll('.view')];
  function showView() {
    const requested = location.hash.slice(1) || 'overview';
    const view = aliases[requested] || requested;
    const active = views.some(section => section.id === view) ? view : 'overview';
    views.forEach(section => { section.hidden = section.id !== active; });
    document.querySelectorAll('.navigation a').forEach(link => {
      if (link.hash === '#' + active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (active === 'overview') renderChart();
  }
  window.addEventListener('hashchange', showView);

  // Query modes follow the WAI-ARIA tab pattern, including keyboard navigation.
  const queryTabs = [...document.querySelectorAll('[role="tab"]')];
  function selectQueryTab(tab) {
    queryTabs.forEach(item => {
      const active = item === tab;
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
      el(item.getAttribute('aria-controls')).hidden = !active;
    });
  }
  queryTabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectQueryTab(tab));
    tab.addEventListener('keydown', event => {
      let target;
      if (event.key === 'ArrowRight') target = queryTabs[(index + 1) % queryTabs.length];
      if (event.key === 'ArrowLeft') target = queryTabs[(index + queryTabs.length - 1) % queryTabs.length];
      if (event.key === 'Home') target = queryTabs[0];
      if (event.key === 'End') target = queryTabs.at(-1);
      if (target) { event.preventDefault(); selectQueryTab(target); target.focus(); }
    });
  });

  function populateMonths(select) {
    for (const month of data.months) {
      const option = document.createElement('option');
      option.value = month.month;
      option.textContent = monthName(month.month);
      select.append(option);
    }
    select.value = selectedMonth.month;
  }

  const svgNS = 'http://www.w3.org/2000/svg';
  function svgNode(name, attrs) {
    const node = document.createElementNS(svgNS, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    return node;
  }

  function renderChart() {
    const root = el('trend-chart');
    if (!root.clientWidth) return;
    root.replaceChildren();
    const width = Math.max(360, root.clientWidth), height = 248;
    const svg = svgNode('svg', { viewBox: `0 0 ${width} ${height}`, 'aria-hidden': 'true' });
    const defs = svgNode('defs', {});
    const gradient = svgNode('linearGradient', { id: 'areaFill', x1: '0', y1: '0', x2: '0', y2: '1' });
    gradient.append(svgNode('stop', { offset: '0%', 'stop-color': '#34b8ac', 'stop-opacity': '.24' }),
      svgNode('stop', { offset: '100%', 'stop-color': '#34b8ac', 'stop-opacity': '0' }));
    defs.append(gradient);
    svg.append(defs);
    const left = 43, right = 15, top = 15, bottom = 32;
    const plotWidth = width - left - right, plotHeight = height - top - bottom;
    const rounding = chartMetric === 'value' ? 100000 : 10;
    const max = Math.ceil(Math.max(...data.months.map(row => row[chartMetric])) * 1.13 / rounding) * rounding;
    for (let i = 0; i <= 4; i++) {
      const y = top + plotHeight * i / 4;
      svg.append(svgNode('line', { x1: left, y1: y, x2: width - right, y2: y, class: 'grid' }));
      const label = svgNode('text', { x: left - 9, y: y + 3, 'text-anchor': 'end', class: 'axis' });
      label.textContent = compact(max * (1 - i / 4));
      svg.append(label);
    }
    const points = data.months.map((row, index) => ({
      x: left + plotWidth * index / (data.months.length - 1),
      y: top + plotHeight * (1 - row[chartMetric] / max), row,
    }));
    const path = points.map((point, index) => (index ? 'L' : 'M') + point.x.toFixed(2) + ' ' + point.y.toFixed(2)).join(' ');
    svg.append(svgNode('path', { d: `${path} L ${points.at(-1).x} ${top + plotHeight} L ${points[0].x} ${top + plotHeight} Z`, class: 'area' }));
    svg.append(svgNode('path', { d: path, class: 'line' }));
    points.forEach((point, index) => {
      const active = point.row.month === selectedMonth.month;
      const circle = svgNode('circle', { cx: point.x, cy: point.y, r: active ? 6 : 4, class: 'point' + (active ? ' selected' : '') });
      circle.addEventListener('click', () => selectChartMonth(point.row.month));
      const title = svgNode('title', {});
      title.textContent = monthName(point.row.month) + ': ' + money(point.row[chartMetric]);
      circle.append(title);
      svg.append(circle);
      const labelInterval = width < 500 ? 6 : 4;
      if (index % labelInterval === 0 || index === points.length - 1) {
        const label = svgNode('text', { x: point.x, y: height - 6, 'text-anchor': 'middle', class: 'axis' });
        label.textContent = point.row.month.slice(5) + '/' + point.row.month.slice(2, 4);
        svg.append(label);
      }
    });
    root.append(svg);
  }

  function renderSelection() {
    el('chart-month').value = selectedMonth.month;
    el('selected-value').textContent = money(selectedMonth[chartMetric]) + (chartMetric === 'aov' ? ' / order' : '');
    el('selected-orders').textContent = numbers.format(selectedMonth.orders) + ' delivered orders';
  }
  function selectChartMonth(month) {
    selectedMonth = data.months.find(row => row.month === month);
    renderChart();
    renderSelection();
  }
  function setChartMetric(metric) {
    chartMetric = metric;
    el('mode-value').setAttribute('aria-pressed', String(metric === 'value'));
    el('mode-aov').setAttribute('aria-pressed', String(metric === 'aov'));
    const title = metric === 'value' ? 'Monthly merchandise value' : 'Monthly average order value';
    el('chart-title').textContent = title;
    el('trend-chart').setAttribute('aria-label', title + ' in BRL, January 2017 through August 2018');
    renderChart();
    renderSelection();
  }

  function renderCategories() {
    const root = el('category-list');
    data.categories.forEach((row, index) => {
      const wrapper = document.createElement('div');
      wrapper.className = 'cat-row';
      const labels = document.createElement('div');
      labels.className = 'cat-label';
      const name = document.createElement('strong');
      name.textContent = String(index + 1).padStart(2, '0') + '  ' + row.name.replaceAll('_', ' ');
      const value = document.createElement('span');
      value.textContent = money(row.value);
      labels.append(name, value);
      const track = document.createElement('div');
      track.className = 'bar-track';
      const bar = document.createElement('div');
      bar.className = 'bar';
      bar.style.width = (100 * row.value / data.categories[0].value).toFixed(1) + '%';
      track.append(bar);
      wrapper.append(labels, track);
      root.append(wrapper);
    });
  }

  function renderOfflineAnswer(kind) {
    offlineMetric = kind;
    const month = data.months.find(row => row.month === el('example-month').value);
    const overall = data.overall;
    const answers = {
      revenue: `${monthName(month.month)}: ${money(month.value)} in delivered merchandise across ${numbers.format(month.orders)} orders. Excludes freight and unobserved refunds. Source: analytics.mart_monthly_metrics.`,
      aov: `AOV in ${monthName(month.month)}: ${money(month.aov)} per delivered order. Merchandise value divided by ${numbers.format(month.orders)} orders. Source: analytics.mart_monthly_metrics.`,
      repeat: `Historical repeat purchase rate: ${percent(overall.repeat_rate)} (${numbers.format(overall.repeat_customers)} of ${numbers.format(overall.customers)} customers with a delivered order). Source: analytics.mart_customer_repeat.`,
      categories: `Top five categories by delivered merchandise value: ${data.categories.slice(0, 5).map(row => row.name.replaceAll('_', ' ') + ' (' + money(row.value) + ')').join(', ')}. Source: analytics.mart_category_metrics.`,
      late: `Late delivery rate: ${percent(overall.late_rate)} (${numbers.format(overall.late_orders)} of ${numbers.format(overall.comparable_orders)} delivered orders with comparable dates). Source: analytics.mart_delivery.`,
    };
    el('guided-answer').textContent = answers[kind] + ' Historical Olist data, 2016–2018.';
    document.querySelectorAll('[data-question]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.question === kind)));
  }

  // Only explicit submits call the local server. Example buttons just fill input.
  async function submitQuery({ path, body, formId, statusId, answerId, boxId, progress, success, timeout }) {
    const status = el(statusId);
    status.classList.remove('error');
    el(boxId).hidden = true;
    if (location.protocol === 'file:') {
      status.textContent = 'This mode needs the local server. Start python showcase_server.py and open http://127.0.0.1:8001/. Offline examples remain available.';
      status.classList.add('error');
      return;
    }
    const buttons = [...el(formId).querySelectorAll('button')];
    buttons.forEach(button => { button.disabled = true; });
    status.textContent = progress;
    try {
      const response = await fetch(path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body), signal: AbortSignal.timeout(timeout),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'Unable to complete the request.');
      el(answerId).textContent = payload.answer;
      el(boxId).hidden = false;
      status.textContent = payload.status === 'ok' ? success : 'Request completed. See the source coverage or supported scope below.';
    } catch (error) {
      status.textContent = error.name === 'TimeoutError' ? 'The request timed out. Try again.'
        : error instanceof TypeError ? 'Unable to reach the local server. Check that it is running.' : error.message;
      status.classList.add('error');
    } finally {
      buttons.forEach(button => { button.disabled = false; });
    }
  }
  const queryRevenue = month => submitQuery({
    path: '/api/revenue', body: { month }, formId: 'revenue-form', statusId: 'revenue-status',
    answerId: 'revenue-answer', boxId: 'revenue-answer-box', progress: 'Looking up the curated monthly value…',
    success: 'MCP lookup complete · no OpenAI credits used.', timeout: 30000,
  });
  el('revenue-form').addEventListener('submit', event => {
    event.preventDefault();
    queryRevenue(el('revenue-month').value.trim());
  });
  el('revenue-latest').addEventListener('click', () => queryRevenue('latest'));
  el('ask-form').addEventListener('submit', event => {
    event.preventDefault();
    const question = el('question-input').value.trim();
    if (!question) return;
    submitQuery({ path: '/api/ask', body: { question }, formId: 'ask-form', statusId: 'ask-status',
      answerId: 'gpt-answer', boxId: 'gpt-answer-box', progress: 'Selecting the metric and querying the curated data…',
      success: 'Answer verified against the curated metric service.', timeout: 60000 });
  });
  document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => {
    el('question-input').value = button.dataset.prompt;
    el('question-input').focus();
  }));
  document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => renderOfflineAnswer(button.dataset.question)));
  el('example-month').addEventListener('change', () => { if (offlineMetric) renderOfflineAnswer(offlineMetric); });

  async function checkConnection() {
    if (location.protocol === 'file:') {
      el('connection-status').textContent = 'Offline page · examples available';
      return;
    }
    try {
      const response = await fetch('/api/status', { signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error('Server unavailable');
      const health = await response.json();
      el('connection-status').textContent = health.gpt_configured ? 'Query service connected · AI available' : 'Query service connected · AI unavailable';
      el('ask-status').textContent = health.gpt_configured ? 'AI queries use OpenAI API credits; limit: 20 requests per day.'
        : 'AI queries require an OpenAI API key. Revenue lookup and offline examples are available.';
    } catch {
      el('connection-status').textContent = 'Query service unavailable · examples available';
    }
  }

  const overall = data.overall;
  el('kpi-value').textContent = money(overall.value);
  el('kpi-orders').textContent = numbers.format(overall.orders);
  el('kpi-aov').textContent = money(overall.aov);
  el('kpi-repeat').textContent = percent(overall.repeat_rate);
  el('late-rate').textContent = percent(overall.late_rate);
  el('late-detail').textContent = numbers.format(overall.late_orders) + ' of ' + numbers.format(overall.comparable_orders) + ' comparable orders';
  el('repeat-count').textContent = numbers.format(overall.repeat_customers);
  el('repeat-detail').textContent = 'Of ' + numbers.format(overall.customers) + ' customers with delivered orders';
  el('source-date').textContent = data.source_date;
  const peak = data.months.reduce((a, b) => a.value > b.value ? a : b);
  el('peak-value').textContent = money(peak.value);
  el('peak-title').textContent = monthName(peak.month);
  populateMonths(el('chart-month'));
  populateMonths(el('example-month'));
  el('chart-month').addEventListener('change', event => selectChartMonth(event.target.value));
  el('mode-value').addEventListener('click', () => setChartMetric('value'));
  el('mode-aov').addEventListener('click', () => setChartMetric('aov'));
  renderSelection();
  renderCategories();
  showView();
  checkConnection();
  window.addEventListener('resize', renderChart);
})();
