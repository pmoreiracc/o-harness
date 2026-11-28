'use strict';

const $ = id => document.getElementById(id);
const html = (id, value) => { $(id).innerHTML = value; };
const label = (id, value) => { $(id).textContent = value; };
const escape = value => String(value ?? '').replace(/[&<>"']/g, char =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[char]);
const unavailable = 'Not measured yet';
const dash = '<span aria-label="Not measured yet" title="Not measured yet">—</span>';
const dayMs = 86400000;
const isoDay = time => new Date(time).toISOString().slice(0, 10);
const today = () => isoDay(Date.now());
const dayTime = day => Date.parse(day + 'T00:00:00Z');
const dateLabel = new Intl.DateTimeFormat('en', {month: 'short', day: 'numeric', timeZone: 'UTC'});
const monthLabel = new Intl.DateTimeFormat('en', {month: 'short', year: '2-digit', timeZone: 'UTC'});
const number = new Intl.NumberFormat('en');
const compact = value => value == null ? '—' :
  new Intl.NumberFormat('en', {notation: 'compact', maximumFractionDigits: 1}).format(value);
const plural = (count, word) => count + ' ' + word + (count === 1 ? '' : 's');
const percent = ratio => Math.round(ratio * 100) + '%';
const cap = value => value ? value[0].toUpperCase() + value.slice(1) : '';
const sum = (rows, key) => rows.reduce((total, row) => total + (row[key] ?? 0), 0);
const difficulty = [['simple', 'Simple', 'teal'], ['standard', 'Standard', 'blue'],
  ['complex', 'Complex', 'purple'], ['unrated', 'Unrated', 'muted']];
const usageTypes = [['cached', 'Cached input', 'dark-blue'], ['fresh', 'Fresh input', 'blue'],
  ['output', 'Output', 'purple']];
const advanced = ['kind', 'difficulty', 'version', 'model', 'phase'];
const state = {view: 'overview', days: 14, custom: null, offset: 0, data: null, health: null,
  request: null, detail: null, lastRefresh: null, error: null};

function duration(ms) {
  if (ms == null) return '—';
  if (ms < 60000) return Math.round(ms / 1000) + 's';
  if (ms < 3600000) return Math.round(ms / 60000) + ' min';
  if (ms < dayMs) return (ms / 3600000).toFixed(1) + ' h';
  return (ms / dayMs).toFixed(1) + ' d';
}

function relative(at) {
  const elapsed = Math.floor((Date.now() - new Date(at).getTime()) / 1000);
  if (!at || !Number.isFinite(elapsed)) return '—';
  if (elapsed < 10) return 'just now';
  if (elapsed < 60) return elapsed + 's ago';
  if (elapsed < 3600) return Math.floor(elapsed / 60) + ' min ago';
  if (elapsed < 86400) return Math.floor(elapsed / 3600) + ' h ago';
  if (elapsed < 172800) return 'yesterday';
  return Math.floor(elapsed / 86400) + ' days ago';
}

function dates() {
  return state.custom ?? [isoDay(dayTime(today()) - (state.days - 1) * dayMs), today()];
}

function addBounds(params, endpoints, prefix = '') {
  params.set(prefix + 'from', endpoints[0] + 'T00:00:00Z');
  params.set(prefix + 'to', isoDay(dayTime(endpoints[1]) + dayMs) + 'T00:00:00Z');
}

function query() {
  const params = new URLSearchParams();
  addBounds(params, dates());
  if ($('project').value) params.set('project', $('project').value);
  if (state.view === 'tasks') {
    params.set('offset', state.offset);
    for (const key of advanced) if ($(key).value) params.set(key, $(key).value);
    const comparison = $('comparison').value;
    if (comparison.startsWith('version:')) params.set('baseline_version', comparison.slice(8));
    if (comparison === 'custom' && state.baseline) {
      addBounds(params, state.baseline, 'baseline_');
    }
  }
  return params;
}

function swatch(color, kind = '') {
  return '<i class="swatch ' + kind + '" style="--tone:var(--' + color + ')" aria-hidden="true"></i>';
}

function legend(entries) {
  return entries.map(([text, color, kind]) => '<span>' + swatch(color, kind) + escape(text) + '</span>').join('');
}

function empty(text, reason = '') {
  return '<div class="empty"><div><strong>' + escape(text) + '</strong>' +
    (reason ? '<p>' + escape(reason) + '</p>' : '') + '</div></div>';
}

function delta(value, comparison, upIsGood) {
  if (value == null) return 'No baseline yet';
  const tone = value === 0 ? '' : ((value > 0) === upIsGood ? 'good' : 'bad');
  const arrow = value > 0 ? '↑ ' : value < 0 ? '↓ ' : '';
  return '<span class="change ' + tone + '">' + arrow + percent(Math.abs(value)) + '</span> ' + escape(comparison);
}

function metric({title, hint, value, suffix = '', note, bottom = ''}) {
  const className = value == null ? ' class="unavailable"' : '';
  return '<div class="metric-head"><h3>' + title + '</h3><span>' + hint + '</span></div>' +
    '<div class="metric-main"><strong' + className + '>' + (value ?? unavailable) + '</strong>' +
    '<span>' + suffix + '</span></div><p class="metric-note">' + note + '</p>' +
    '<div class="metric-bottom">' + bottom + '</div>';
}

// Longer ranges are grouped by calendar month to keep the charts readable.
function buckets(range) {
  const first = dayTime(range.from.slice(0, 10));
  const last = dayTime(range.to.slice(0, 10));
  const monthly = (last - first) / dayMs > 45;
  const results = [];
  for (let time = first; time < last;) {
    const date = new Date(time);
    const next = monthly ? date.setUTCMonth(date.getUTCMonth() + 1, 1) : time + dayMs;
    const label = monthly ? monthLabel.format(time) : isoDay(time) === today() ? 'Today' : dateLabel.format(time);
    results.push({start: isoDay(time), end: isoDay(next), label});
    time = next;
  }
  return results;
}

function chartData(days, entries, getValues, zeroWhenEmpty) {
  return days.map(day => {
    const values = getValues(day);
    return {...day, values: values ?? (zeroWhenEmpty ? entries.map(() => 0) : null)};
  });
}

const chartObserver = new ResizeObserver(entries => {
  for (const {target} of entries) target.drawChart?.();
});

function chart(id, items, types, title, isCount) {
  const target = $(id);
  chartObserver.unobserve(target);
  target.drawChart = () => {
    const max = Math.max(1, ...items.map(item => item.values?.reduce((a, b) => a + b, 0) ?? 0));
    const roughStep = max / 4;
    const unit = 10 ** Math.floor(Math.log10(roughStep));
    const step = Math.max(isCount ? 1 : 0, Math.ceil(roughStep / unit) * unit);
    const ceiling = 4 * step;
    const minStep = items.length === 14 ? 2 : 1;
    const labelEvery = Math.max(minStep, Math.ceil(items.length / Math.max(2, Math.floor(target.clientWidth / 54))));
    const format = value => isCount ? number.format(value) : compact(value);
    const grid = Array.from({length: 5}, (_, i) =>
      '<div class="gridline" style="bottom:' + i * 25 + '%"><span>' + format(i * step) + '</span></div>').join('');
    const columns = items.map((item, index) => {
      const segments = (item.values ?? []).map((value, n) => value > 0 ?
        '<i style="--tone:var(--' + types[n][2] + ');height:' + value / ceiling * 100 + '%"></i>' : '').join('');
      const summary = item.values ? item.values.map((value, n) => types[n][1] + ' ' + number.format(value)).join(' · ') : unavailable;
      const showLabel = index === items.length - 1 || index % labelEvery === 0 &&
        (labelEvery === 1 || index < items.length - Math.ceil(labelEvery / 2));
      return '<div class="bucket" title="' + escape(item.label + ' · ' + summary) + '"><div class="stack">' + segments + '</div>' +
        (showLabel ? '<span class="bucket-label">' + escape(item.label) + '</span>' : '') + '</div>';
    }).join('');
    const tableRows = items.map(item => '<tr><th scope="row">' + escape(item.label) + '</th>' +
      (item.values ?? types.map(() => null)).map(value => '<td>' + (value == null ? unavailable : number.format(value)) + '</td>').join('') + '</tr>').join('');
    target.innerHTML = '<div class="chart-inner" role="img" aria-label="' + title + '">' + grid +
      '<div class="chart-columns">' + columns + '</div></div>' +
      '<div class="sr-only"><table class="chart-table"><caption>' + title + '</caption><thead><tr><th scope="col">Date</th>' +
      types.map(t => '<th scope="col">' + t[1] + '</th>').join('') + '</tr></thead><tbody>' + tableRows + '</tbody></table></div>';
  };
  target.drawChart();
  chartObserver.observe(target);
}

function emptyChart(id, text, reason) {
  const node = $(id);
  chartObserver.unobserve(node);
  node.drawChart = null;
  node.innerHTML = empty(text, reason);
}

const sparkObserver = new ResizeObserver(entries => entries.forEach(({target}) => target.drawSpark?.()));

function spark(id, values, tone) {
  const canvas = document.querySelector('#' + id + ' canvas');
  if (!canvas || !values.some(value => value != null)) return;
  canvas.drawSpark = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    const context = canvas.getContext('2d');
    const scale = window.devicePixelRatio;
    canvas.width = w * scale;
    canvas.height = h * scale;
    context.scale(scale, scale);
    const color = getComputedStyle(canvas).getPropertyValue('--' + tone).trim();
    const max = Math.max(...values.filter(value => value != null), 1);
    for (let i = 0; i < values.length;) {
      if (values[i] == null) { i++; continue; }
      const points = [];
      while (i < values.length && values[i] != null) {
        points.push([i * w / Math.max(values.length - 1, 1), 6 + (1 - values[i] / max) * (h - 12)]);
        i++;
      }
      context.beginPath();
      points.forEach(([x, y], n) => n === 0 ? context.moveTo(x, y) : context.lineTo(x, y));
      context.lineWidth = 1.75;
      context.strokeStyle = color;
      if (points.length === 1) {
        context.fillStyle = color;
        context.fillRect(points[0][0] - 1, points[0][1], 3, 2);
      } else {
        context.stroke();
        context.lineTo(points.at(-1)[0], h);
        context.lineTo(points[0][0], h);
        context.closePath();
        const gradient = context.createLinearGradient(0, 0, 0, h);
        gradient.addColorStop(0, color + '55');
        gradient.addColorStop(1, color + '00');
        context.fillStyle = gradient;
        context.fill();
      }
    }
  };
  canvas.drawSpark();
  sparkObserver.observe(canvas);
}

function inBucket(rows, bucket) {
  return rows.filter(row => row.day >= bucket.start && row.day < bucket.end);
}

function renderOverview(data) {
  for (const canvas of document.querySelectorAll('canvas.spark')) sparkObserver.unobserve(canvas);
  const days = buckets(data.range);
  const monthly = (dayTime(data.range.to.slice(0, 10)) - dayTime(data.range.from.slice(0, 10))) / dayMs > 45;
  label('delivery-trend-title', monthly ? 'Delivered tasks per month' : 'Delivered tasks per day');
  label('usage-trend-title', monthly ? 'Tokens per month' : 'Tokens per day');
  const custom = state.custom != null;
  const daysCount = (dayTime(data.range.to.slice(0, 10)) - dayTime(data.range.from.slice(0, 10))) / dayMs;
  const scope = custom ? 'Selected dates' : 'Last ' + daysCount + ' days';
  const period = 'vs previous ' + plural(daysCount, 'day');
  label('performance-heading', 'Performance · ' + scope);
  const {delivered, started, previous_delivered: previous, delivery, cohort, usage, coverage} = data;
  const {reviews_change: reviewsChange, time_change: timeChange} = data.delivery_samples;
  const progression = reviewsChange == null || reviewsChange === 0 ? '' :
    ', with ' + (reviewsChange < 0 ? 'fewer' : 'more') + ' review rounds than the previous period';
  label('delivery-summary', started ? delivered + ' of ' + started + ' tasks delivered ' +
    (custom ? 'for the selected dates' : 'in the last ' + daysCount + ' days') + progression + '.' :
    data.has_runs ? 'No tasks started in this period.' : 'Recorded task activity will appear here after your first run.');
  const levels = difficulty.filter(([key]) => key !== 'unrated' || delivery.some(r => !difficulty.slice(0, 3).some(d => d[0] === r.difficulty)));
  const deliveredPoints = chartData(days, levels, bucket => {
    const rows = inBucket(delivery, bucket);
    return levels.map(([key]) => sum(rows.filter(row => key === 'unrated' ?
      !difficulty.slice(0, 3).some(d => d[0] === row.difficulty) : row.difficulty === key), 'delivered'));
  }, true);
  html('delivery-legend', legend(levels.map(([, name, color], n) =>
    [name + ' ' + deliveredPoints.reduce((total, item) => total + item.values[n], 0), color])));
  if (delivery.length) chart('delivery-chart', deliveredPoints, levels, monthly ? 'Delivered tasks per month' : 'Delivered tasks per day', true);
  else emptyChart('delivery-chart', 'No deliveries in this period');

  const usableDays = usage.filter(row => row.stacked === row.records);
  const usagePoints = chartData(days, usageTypes, bucket => {
    const all = inBucket(usage, bucket);
    return all.length && all.every(row => row.stacked === row.records) ?
      usageTypes.map(([key]) => sum(all, key)) : null;
  }, false);
  html('usage-legend', legend(usageTypes.map(([, name, color]) => [name, color])));
  if (usagePoints.some(item => item.values)) chart('usage-chart', usagePoints, usageTypes, monthly ? 'Tokens per month' : 'Tokens per day', false);
  else emptyChart('usage-chart', unavailable, usage.length ?
    'The host usage reports lack one or more token components.' : 'No token usage observed in this period.');
  const coverageRatio = coverage.attempts ? coverage.measured / coverage.attempts : null;
  const coverageText = coverageRatio == null ? 'Attempt coverage unavailable' :
    'Measured on ' + percent(coverageRatio) + ' of worker attempts';
  const tokenTotal = usage.some(row => row.tokens != null) ? compact(sum(usage, 'tokens')) + ' observed tokens' : unavailable;
  const incomplete = usage.length - usableDays.length;
  const chartedDays = usableDays.filter(row => usagePoints.some(bucket =>
    bucket.values && row.day >= bucket.start && row.day < bucket.end));
  const cache = sum(chartedDays, 'cached'), input = cache + sum(chartedDays, 'fresh');
  const cacheShare = input ? ' · ' + percent(cache / input) + ' of charted input served from cache' : '';
  const coverageNote = incomplete ? plural(incomplete, 'day') + ' with incomplete reports · ' : '';
  html('usage-summary', '<span>' + tokenTotal + cacheShare + '</span><span>' + coverageNote + coverageText + '</span>');

  const measuredReviews = sum(cohort, 'reviewed');
  const timed = sum(cohort, 'timed');
  const roundCounts = [
    ['1 round', 'green', sum(cohort, 'one_round')],
    ['2', 'amber', sum(cohort, 'two_rounds')],
    ['3+', 'red', sum(cohort, 'more_rounds')],
  ];
  const noRounds = measuredReviews - roundCounts.reduce((total, row) => total + row[2], 0);
  if (noRounds) roundCounts.unshift(['0 rounds', 'muted', noRounds]);
  const rounds = measuredReviews ? '<div class="round-track" aria-hidden="true">' +
    roundCounts.filter(row => row[2] > 0).map(([, color, count]) =>
      '<span style="--tone:var(--' + color + ');width:' + count / measuredReviews * 100 + '%"></span>').join('') +
    '</div><div class="legend">' + legend(roundCounts.map(([text, color, count]) => [text + ' · ' + count, color])) + '</div>' : '';
  const sparkline = '<canvas class="spark" aria-hidden="true"></canvas>';
  html('delivered-metric', metric({title: 'Tasks delivered', hint: 'completed',
    value: started ? number.format(delivered) : null, suffix: started ? 'of ' + number.format(started) + ' started' : '',
    note: delta(started && previous >= 10 ? delivered / previous - 1 : null, period, true), bottom: sparkline}));
  html('review-metric', metric({title: 'Review rounds per task', hint: 'lower is better',
    value: measuredReviews ? (sum(cohort, 'reviews') / measuredReviews).toFixed(1) : null,
    note: delta(reviewsChange, 'same difficulty mix', false) +
      (measuredReviews && measuredReviews < delivered ? ' · ' + measuredReviews + '/' + delivered + ' measured' : ''), bottom: rounds}));
  const wall = timed ? duration(sum(cohort, 'elapsed_ms') / timed).split(' ') : [];
  html('time-metric', metric({title: 'Time per task', hint: 'elapsed, delivered',
    value: wall[0], suffix: wall[1] ?? '', note: delta(timeChange, 'same difficulty mix', false) +
      (timed && timed < delivered ? ' · ' + timed + '/' + delivered + ' timed' : ''), bottom: sparkline}));
  const taskCost = data.task_cost;
  const attributed = delivered ? taskCost.measured / delivered : 0;
  const taskCoverage = delivered ? '<div class="coverage"><span class="coverage-track" aria-hidden="true"><span style="width:' +
    percent(attributed) + '"></span></span>' + taskCost.measured + '/' + delivered + ' tasks fully measured</div>' : '';
  const taskCostNote = taskCost.average != null ? 'Includes coordination and publication' :
    delivered ? 'Full cost must be attributable to each task' : 'No deliveries in this period';
  html('token-metric', metric({title: 'Tokens per delivered task', hint: 'average',
    value: taskCost.average == null ? null : compact(taskCost.average),
    note: taskCostNote, bottom: taskCoverage}));
  spark('delivered-metric', delivery.length ? deliveredPoints.map(item => item.values.reduce((a, b) => a + b, 0)) : [], 'teal');
  spark('time-metric', days.map(day => {
    const rows = inBucket(cohort, day), count = sum(rows, 'timed');
    return count ? sum(rows, 'elapsed_ms') / count : null;
  }), 'blue');
  renderAgentTime(data);
  renderDeliveryCosts(data.delivery_costs, data.projects);
}

function renderDeliveryCosts(costs, projects) {
  const more = $('more-delivery-costs');
  const summaryFocused = more?.firstElementChild === document.activeElement;
  if (!costs.length) {
    html('delivery-costs', '<p class="delivery-cost-empty"><strong>' + unavailable +
      '</strong> · No delivery token records in this selection.</p>');
    return;
  }
  const projectNames = new Map(projects.map(project => [project.id, project.name]));
  const ordered = [...costs.filter(cost => cost.total_tokens != null), ...costs.filter(cost => cost.total_tokens == null)];
  function render(cost) {
    const verified = cost.total_tokens != null;
    const project = projectNames.get(cost.project) || cost.name;
    const title = cost.task_title || cost.name || project || 'Delivery';
    const host = {codex: 'Codex', claude: 'Claude'}[cost.host];
    const metadata = [project !== title ? project : null, host, taskDateFormat.format(Date.parse(cost.started)),
      verified ? null : 'Observed tokens only'];
    const components = [
      ['Workers', cost.observed_worker_tokens], ['Coordinator', cost.observed_coordinator_tokens],
      ['Publication', cost.observed_publication_tokens], [verified ? 'Verified total' : 'Full cost', cost.total_tokens],
    ];
    return '<article class="delivery-cost-row"><div><h3>' + escape(title) + '</h3><p>' +
      escape(metadata.filter(Boolean).join(' · ')) +
      '</p></div><dl>' + components.map(([name, amount], i) =>
      '<div' + (i === 3 && verified ? ' class="verified-cost"' : '') + '><dt>' + name + '</dt><dd' +
      (amount == null ? ' class="missing-cost">' + unavailable : '>' + number.format(amount)) +
      '</dd></div>').join('') + '</dl></article>';
  }
  const rest = ordered.slice(4);
  html('delivery-costs', ordered.slice(0, 4).map(render).join('') + (rest.length ?
    '<details id="more-delivery-costs"' + (more?.open ? ' open' : '') + '><summary>' +
      rest.length + (rest.length === 1 ? ' more delivery' : ' more deliveries') + '</summary>' +
      rest.map(render).join('') + '</details>' : ''));
  if (summaryFocused) $('more-delivery-costs')?.firstElementChild.focus({preventScroll: true});
}

function renderAgentTime({phases, models}) {
  const total = sum(phases, 'agent_ms'), max = Math.max(1, ...phases.map(phase => phase.agent_ms ?? 0));
  const attempts = sum(phases, 'attempts'), timed = sum(phases, 'timed');
  label('phase-summary', timed ? duration(total) + ' of observed agent time, by step' +
    (timed < attempts ? ' · ' + timed + '/' + attempts + ' timed' : '') : 'Observed agent time, by step');
  html('phases', [['Implementation', 'blue'], ['Review', 'purple'], ['Assessment', 'teal'], ['Coordination', 'muted']]
    .map(([step, color]) => {
      const phase = phases.find(row => row.phase === step.toLowerCase());
      const time = phase?.agent_ms;
      return '<div class="phase"><span>' + step + '</span><div class="phase-meter" aria-hidden="true">' +
        (time == null ? '' : '<i style="--tone:var(--' + color + ');width:' + time / max * 100 + '%"></i>') +
        '</div><div class="phase-values">' + (time == null ? '<small>' + unavailable + '</small>' :
          '<strong>' + duration(time) + '</strong><small>' + (total ? percent(time / total) : '—') + '</small>') + '</div></div>';
    }).join(''));
  html('models', models.length ? models.map(model => {
    const steps = model.phases?.split(',').sort().join(' / ') ?? 'Unknown step';
    const usage = model.measured === model.attempts ? compact(model.tokens) : dash;
    return '<div class="model"><div><strong class="mono">' + escape(model.model) + '</strong><small>' +
      escape(steps) + ' · ' + plural(model.attempts, 'attempt') + '</small></div>' +
      '<div class="model-stat"><strong>' + duration(model.agent_ms) + '</strong><small>' +
      (model.timed < model.attempts ? model.timed + '/' + model.attempts + ' timed' : 'agent time') + '</small></div>' +
      '<div class="model-stat"><strong>' + usage + '</strong><small>tokens</small></div></div>';
  }).join('') : empty(unavailable, 'No model durations were recorded in this period.'));
}

const reviewLegend = [['Clean', 'green', 'round'], ['Had findings', 'amber', 'round'],
  ['Outcome unavailable', 'muted', 'round']];
const reviewResult = outcome => outcome === 'clean' ? reviewLegend[0] :
  ['blocking', 'needs_resolution'].includes(outcome) ? reviewLegend[1] : reviewLegend[2];

function taskStatus(task) {
  if (task.status === 'completed') return ['✓ Delivered', 'delivered'];
  if (task.status === 'feedback') return ['Review only', 'neutral'];
  if (task.run_status === 'stopped') return ['Stopped', 'neutral'];
  if (task.run_status === 'failed') return ['Failed', 'neutral'];
  // A missing finish in the index cannot establish that a native process is still running.
  if (task.status === 'running') return ['Open in index', 'neutral'];
  return ['Unknown', 'neutral'];
}

function renderTasks(data) {
  const overview = state.view === 'overview';
  const list = overview ? data.tasks.slice(0, 7) : data.tasks;
  const focused = document.activeElement.closest('.task-button')?.dataset;
  html('review-legend', legend(reviewLegend));
  label('all-tasks', 'All ' + plural(data.task_count, 'task') + ' →');
  html('rows', list.length ? list.map(task => {
    const [status, tone] = taskStatus(task);
    const level = difficulty.find(row => row[0] === task.difficulty);
    const rounds = task.expected_reviews ?? (task.review_outcomes.length || null);
    const results = task.review_outcomes.map(reviewResult);
    const markers = results.slice(0, 12).map(([, color]) => swatch(color, 'round')).join('');
    const description = results.length ? ' · ' + results.map(([text]) => text.toLowerCase()).join(', ') : '';
    const pill = '<span class="pill ' + tone + '">' + escape(status) + '</span>';
    return '<tr role="row" class="task-row"><td class="task-status">' + pill + '</td><td class="task-name"><button type="button" class="task-button" data-run="' +
      escape(task.run) + '" data-task="' + escape(task.id) + '">' + escape(task.title || 'Untitled task') +
      '</button><small class="task-label"><span class="mono">' + escape(task.name || task.run) +
      '</span> · task ' + escape(task.id) + '</small></td><td class="task-difficulty">' +
      (level ? swatch(level[2]) + level[0] : dash) + '</td><td class="task-reviews"><span aria-label="' +
      escape((rounds == null ? unavailable : plural(rounds, 'review round')) + description) + '"><span class="review-dots" aria-hidden="true">' +
      markers + '</span><span aria-hidden="true">' + (rounds ?? '—') + '</span></span></td><td class="task-time">' +
      (task.agent_ms == null ? dash : duration(task.agent_ms)) + '</td><td class="task-tokens">' +
      (task.observed_tokens == null ? '<span aria-label="Not all attempts reported usage" title="Not all attempts reported usage">—</span>' :
        compact(task.observed_tokens)) + '</td><td class="task-started">' +
      (task.started ? '<time datetime="' + escape(task.started) + '" title="' + escape(task.started) + '">' +
        relative(task.started) + '</time>' : dash) + '</td></tr>';
  }).join('') : '<tr><td class="table-empty" colspan="7">' +
    (data.task_count ? 'This page is empty. Go back to see earlier tasks.' : 'No tasks in this period. Try 30d or a different filter.') +
    '</td></tr>');
  if (focused) {
    const button = [...document.querySelectorAll('.task-button')].find(element =>
      element.dataset.run === focused.run && element.dataset.task === focused.task);
    (button ?? $('rows').closest('.table-wrap')).focus({preventScroll: true});
  }
  $('pagination').hidden = overview || (!data.offset && data.task_count <= data.page_size);
  $('prev-page').disabled = !data.offset;
  $('next-page').disabled = data.offset + data.page_size >= data.task_count;
  label('page-status', list.length ? (data.offset + 1) + '–' + (data.offset + list.length) + ' of ' + data.task_count : 'No tasks on this page');
  const compare = $('comparison').selectedOptions[0].textContent;
  const showComparison = $('comparison').value !== 'custom' || state.baseline != null;
  label('task-comparison', showComparison ? plural(data.delivered, 'delivery') + ' · ' + data.previous_delivered +
    ' in ' + compare : 'Choose baseline dates to compare deliveries.');
}

function options(id, items) {
  const select = $(id), current = select.value;
  const expected = JSON.stringify(items);
  if (select.dataset.options === expected) return;
  select.dataset.options = expected;
  select.replaceChildren(select.options[0], ...items.map(([id, name]) => new Option(name, id)));
  select.value = [...select.options].some(option => option.value === current) ? current : '';
}

function renderOptions(data) {
  options('project', data.projects.map(project => [project.id, project.name]));
  for (const key of advanced) options(key, data.options[key].map(value => [value, key === 'model' ? value : cap(value)]));
  options('comparison', [['custom', 'Custom dates'], ...data.options.version.map(v => ['version:' + v, 'Version ' + v])]);
  if (!$('comparison').value) $('comparison').value = 'previous';
}

const healthDate = new Intl.DateTimeFormat('en', {dateStyle:'medium', timeZone:'UTC'});

function coverageRow(name, measured, total, unit) {
  const ratio = total ? measured / total : 0;
  const rounded = Math.round(ratio * 100);
  const value = !total ? 'No records' : measured > 0 && rounded === 0 ? '<1%' :
    measured < total && rounded === 100 ? '<100%' : rounded + '%';
  const tone = !total ? 'neutral' : measured === total ? 'delivered' : 'finding';
  const count = total ? number.format(measured) + ' of ' + number.format(total) + ' ' + unit :
    'No records in this selection';
  const bar = total ? '<div class="health-meter" aria-hidden="true"><i style="width:' +
    ratio * 100 + '%"></i></div>' : '';
  return '<li><div><strong>' + name + '</strong><span class="pill ' + tone + '">' + escape(value) +
    '</span></div><p>' + count + '</p>' + bar + '</li>';
}

function healthVerdict(data, failed, delayed, incomplete) {
  if (failed) return ['bad', 'The dashboard couldn’t refresh',
    data ? 'The measurements below are from the last successful refresh.' : 'Retry to reconnect to the local dashboard.'];
  if (!data) return ['neutral', 'Checking the local index…', ''];
  if (delayed) return ['warn', 'The collector is delayed',
    'New observations may take longer to appear. The coverage below reflects the index as recorded.'];
  if (incomplete) return ['warn', 'Some collection records need attention',
    'Review the collection diagnostics below. Dashboard measurements reflect the data available in the index.'];
  const {attempts, measured} = data.coverage;
  if (!attempts) return ['neutral', 'No indexed attempts in this selection',
    'Choose a wider date range or a different project to look for recorded activity.'];
  if (!measured) return ['warn', 'No complete token records',
    'Attempts in this selection lack complete input and output records. Deliveries, reviews and recorded agent timings are still available when indexed.'];
  if (measured < attempts) return ['warn', 'Token usage is partially recorded',
    'The usage charts reflect observed tokens. Use the coverage below to see how much of the selected activity reported usage.'];
  return ['good', 'Every selected worker attempt has token records',
    'Full delivery costs also require verified coordination and publication usage.'];
}

function renderDataHealth(data, {failed, delayed, incomplete, collector, heartbeat}) {
  const [tone, title, message] = healthVerdict(data, failed, delayed, incomplete);
  $('health-summary').dataset.tone = tone;
  label('data-health-title', title);
  label('data-health-message', message);
  const serviceTone = failed ? 'red' : delayed || !heartbeat ? 'amber' : 'green';
  html('data-health-collector', '<i class="dot ' + serviceTone + '" aria-hidden="true"></i>' +
    escape(failed ? 'Status unavailable' : collector));
  const metrics = data?.health;
  label('data-health-observation', metrics?.freshness ? relative(metrics.freshness) : 'None recorded');
  $('health-measurement').hidden = !data;
  $('health-secondary').hidden = !data;
  if (!data) return;

  const {attempts, measured} = data.coverage;
  const project = data.projects.find(item => item.id === data.range.project)?.name;
  const from = healthDate.format(Date.parse(data.range.from));
  const through = healthDate.format(Date.parse(data.range.to) - 1);
  label('coverage-selection', (project || (data.range.project ? 'Selected project' : 'All projects')) +
    ' · ' + (from === through ? from : from + ' – ' + through) + ' · UTC');

  const rated = sum(data.cohort.filter(row => difficulty.slice(0,3).some(([level]) => level === row.difficulty)), 'delivered');
  const timed = sum(data.phases, 'timed');
  const runningSteps = sum(data.phases, 'attempts');
  html('health-coverage', [
    coverageRow('Worker token usage', measured, attempts, 'worker attempts started in the period'),
    coverageRow('Full task token cost', data.task_cost.measured, data.delivered, 'delivered tasks with a verified and attributable cost'),
    coverageRow('Agent time', timed, runningSteps, 'assessment, implementation and review attempts'),
    coverageRow('Difficulty ratings', rated, data.delivered, 'delivered tasks started in the period'),
    coverageRow('Review-round counts', sum(data.cohort, 'reviewed'), data.delivered, 'delivered tasks started in the period'),
  ].join(''));

  const limits = [
    ['Shared delivery costs', 'The Overview shows verified totals by delivery. Costs shared by several tasks stay with the delivery.'],
    ['Live progress and pending decisions', 'Check Codex or Claude for live progress and choices awaiting an answer.'],
    ['Coordination time', 'Time spent coordinating a run is not measured yet.'],
  ];
  html('health-limits', limits.map(([name, description]) => '<li><strong>' + name + '</strong><p>' + description + '</p></li>').join(''));

  const gaps = metrics.gaps;
  const invalid = metrics.invalid_records;
  const lastBatch = metrics.last_ingested;
  const diagnostics = [
    ['Last indexed batch', lastBatch ? relative(lastBatch) : 'None recorded'],
    ['Collection gaps', number.format(gaps.length)],
    ['Invalid records', invalid == null ? 'Count unavailable' : invalid ? number.format(invalid) + ' in the last recorded invalid batch' : 'No invalid batch recorded'],
  ];
  html('health-diagnostics', diagnostics.map(([name,value]) =>
    '<div><dt>' + name + '</dt><dd>' + escape(value) + '</dd></div>').join(''));
  $('gap-list').hidden = !gaps.length;
  html('gap-list', gaps.map(gap => {
    let message = gap;
    try { message = JSON.parse(gap)?.reason ?? gap; } catch { /* Legacy gaps are plain text. */ }
    return '<li>' + escape(message) + '</li>';
  }).join(''));
  $('health-recovery').hidden = !incomplete;

  const ci = metrics.ci;
  $('health-ci').hidden = !ci.ci_completed;
  if (ci.ci_completed) label('health-ci', number.format(ci.ci_failures) + ' of ' +
    plural(ci.ci_completed, 'recorded CI result') + ' failed after review in this selection.');
  $('suggestions-panel').hidden = !metrics.suggestions.length;
  html('saved-suggestions', metrics.suggestions.map(item => '<article><strong>' +
    escape(item.title) + '</strong><p>' + escape(item.explanation) + '</p>' +
    '<small>' + escape(item.status) + '</small></article>').join(''));
}

function renderHealth() {
  const {data, health, error, lastRefresh} = state;
  const metrics = data?.health;
  const freshness = metrics?.freshness;
  const heartbeat = health?.collector_checked;
  const delayed = heartbeat && Date.now() - Date.parse(heartbeat) > 15000;
  const failed = error || health?.collector_error;
  const gaps = metrics?.gaps.length;
  const invalid = metrics?.invalid_records;
  const incomplete = gaps > 0 || invalid > 0 || (metrics && invalid == null);
  const tone = failed ? 'bad' : incomplete || delayed || !heartbeat ? 'warn' : 'good';
  const collector = failed ? 'Collector unavailable' : delayed ? 'Collector delayed' :
    heartbeat ? 'Collector running' : 'Collector starting';
  const verdict = failed ? 'Collector stopped' : incomplete ? 'Data incomplete' :
    delayed ? 'Collection delayed' : heartbeat ? 'Healthy' : 'Connecting';
  const live = failed ? 'Unavailable' : delayed ? 'Delayed' : !heartbeat ? 'Connecting' :
    freshness ? 'Live · updated ' + relative(freshness) : 'Live · awaiting data';
  label('freshness', live);
  for (const id of ['live-dot', 'collector-dot']) $(id).className = 'dot ' +
    (failed ? 'red' : delayed || !heartbeat ? 'amber' : 'green');
  $('vision').classList.toggle('has-failure', Boolean(failed));
  $('vision').classList.toggle('has-warning', !failed && tone === 'warn');
  const last = lastRefresh?.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  const healthText = failed && last ? 'Last known · ' + last : verdict;
  const healthLabel = $('health-label');
  healthLabel.className = 'health-label ' + tone;
  if (healthLabel.textContent !== healthText) html('health-label', '<i class="dot" aria-hidden="true"></i>' + escape(healthText));
  const title = !data ? 'Loading recorded activity…' : !data.has_runs ? 'No runs yet' :
    incomplete ? 'Some observations are missing.' : 'Current run activity is not measured yet.';
  if ($('hero-title').textContent !== title) label('hero-title', title);
  $('empty-start').hidden = !data || data.has_runs;
  $('dashboard-data').classList.toggle('first-run', Boolean(data && !data.has_runs));
  label('collector-status', collector);
  label('gap-count', gaps ?? '—');
  label('footer-gaps', gaps ?? '—');
  label('invalid-records', invalid ?? '—');
  label('last-observation', relative(freshness));
  const coverage = data?.coverage;
  const attempts = coverage?.attempts ?? 0;
  const coverageLabel = attempts ? percent(coverage.measured / attempts) : '—';
  html('footer-coverage', coverageLabel + (attempts ? ' <span class="muted">of worker attempts</span>' : ''));
  const issueCount = (gaps ?? 0) + (invalid ?? (metrics ? 1 : 0)) + (failed ? 1 : 0);
  label('health-count', issueCount ? compact(issueCount) : '');
  $('health-count').hidden = !issueCount;
  $('stale-tag').hidden = !failed || !data;
  $('dashboard-data').classList.toggle('stale', Boolean(failed && data));
  if (state.view === 'data-health') renderDataHealth(data, {failed, delayed, incomplete, collector, heartbeat});
}

function render() {
  const {data, health} = state;
  if (health) {
    const mode = health.mode === 'development' ? 'Dev' : 'Release';
    const identity = mode + ' · ' + (health.version || 'Version unavailable');
    label('environment', identity);
    $('environment').title = identity;
    $('environment').dataset.mode = health.mode;
  }
  if (data) {
    renderOptions(data);
    label('nav-count', data.task_count);
    $('nav-count').hidden = false;
    if (state.view === 'overview') renderOverview(data);
    if (state.view !== 'data-health') renderTasks(data);
  }
  renderHealth();
}

async function get(url, signal) {
  const response = await fetch(url, {signal, cache: 'no-store'});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The dashboard could not refresh.');
  return result;
}

function showError(message) {
  const panel = $('error');
  panel.hidden = !message;
  if (message) label('error-message', message);
}

async function refresh() {
  state.request?.abort();
  const request = new AbortController();
  state.request = request;
  $('refresh').setAttribute('aria-busy', 'true');
  try {
    const [health, data] = await Promise.all([
      get('/api/health', request.signal), get('/api/dashboard?' + query(), request.signal),
    ]);
    if (state.request !== request) return;
    state.health = health;
    state.data = data;
    state.lastRefresh = new Date();
    state.error = null;
    showError(health.collector_error);
    render();
  } catch (error) {
    if (state.request !== request) return;
    state.error = error.message;
    showError(error.message);
    renderHealth();
  } finally {
    if (state.request === request) {
      state.request = null;
      $('refresh').removeAttribute('aria-busy');
      $('dashboard-data').classList.remove('loading');
    }
  }
}

function showView() {
  const hash = location.hash.slice(1);
  const view = ['overview', 'tasks', 'data-health'].includes(hash) ? hash : 'overview';
  const moved = view !== state.view;
  const followLink = document.activeElement.closest('main a');
  state.view = view;
  state.offset = 0;
  const name = view === 'data-health' ? 'Data health' : cap(view);
  label('view-heading', name);
  document.title = 'OH · ' + name;
  for (const link of document.querySelectorAll('nav [data-view]')) {
    if (link.dataset.view === view) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  for (const element of document.querySelectorAll('[data-views]')) element.hidden = !element.dataset.views.split(' ').includes(view);
  $('drill-label').hidden = view !== 'overview';
  $('task-filters').hidden = view !== 'tasks';
  $('all-tasks').hidden = view !== 'overview';
  document.querySelector('.task-section').classList.toggle('full-view', view === 'tasks');
  label('tasks-heading', view === 'tasks' ? 'Tasks' : 'Recent tasks');
  if (state.data && view === 'overview' && !advanced.some(key => state.data.range[key]) && !state.data.offset) {
    renderOverview(state.data);
    renderTasks(state.data);
  }
  if (moved) {
    window.scrollTo(0, 0);
    if (followLink) $('content').focus({preventScroll:true});
  }
  refresh();
}

const taskDateFormat = new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});

function taskDate(value) {
  const date = new Date(value);
  return value && Number.isFinite(date.getTime()) ? taskDateFormat.format(date) : '';
}

function taskTime(value) {
  const formatted = taskDate(value);
  return formatted ? '<time datetime="' + escape(value) + '" title="' + escape(value) + '">' + escape(formatted) + '</time>' : '';
}

function taskSnapshot(task) {
  const [text, tone] = taskStatus(task);
  const feedback = task.status === 'feedback';
  const message = {
    'Stopped': 'The indexed run was stopped.',
    'Failed': 'The indexed run ended in failure.',
    'Open in index': 'No completion is recorded. Check your host for the current state.',
    'Unknown': 'The index has no confirmed task status.',
  };
  label('task-detail-project', (task.name || 'Unknown project') + ' · ' + (feedback ? 'Standalone review' : 'Task ' + task.id));
  label('task-detail-title', feedback ? 'Review details' : 'Task details');
  label('task-detail-subject', task.title || (feedback ? 'Untitled review' : 'Untitled task'));
  const started = taskTime(task.started);
  html('task-detail-start', started ? 'Started ' + started : '');
  label('task-detail-status', text);
  $('task-detail-status').className = 'pill ' + tone;
  label('task-detail-status-note', message[text] ?? '');

  const level = difficulty.find(([key]) => key === task.difficulty);
  const reviewRounds = task.expected_reviews ?? (task.review_outcomes.length || null);
  const measures = [['Difficulty', level ? swatch(level[2]) + level[1] : 'Unrated']];
  if (reviewRounds != null) measures.push(['Review rounds', reviewRounds]);
  if (task.agent_ms != null) measures.push(['Agent time', duration(task.agent_ms)]);
  if (task.observed_tokens != null) measures.push(['Observed tokens', compact(task.observed_tokens)]);
  html('task-detail-measures', measures.map(([name,value]) => '<div><dt>' + name + '</dt><dd>' + value + '</dd></div>').join(''));
}

function attemptStatus(attempt) {
  const outcome = attempt.outcome;
  if (outcome === 'clean') return ['Clean', 'delivered'];
  if (outcome === 'blocking') return ['Blocking findings', 'finding'];
  if (outcome === 'needs_resolution') return ['Findings recorded', 'finding'];
  if (outcome === 'review_incomplete') return ['Review incomplete', 'neutral'];
  if (outcome === 'assessed') return ['Assessed', 'neutral'];
  if (['reported','completed','implemented'].includes(outcome)) return ['Result recorded', 'neutral'];
  if (['cancelled','abandoned','interrupted','failed','unfinished','blocked'].includes(outcome)) return [cap(outcome), 'neutral'];
  return ['Outcome unavailable', 'neutral'];
}

function attemptMeta(attempt) {
  const parts = [
    attempt.model ? '<span>' + escape(attempt.model) + '</span>' : '',
    attempt.duration_ms == null ? '' : '<span>' + duration(attempt.duration_ms) + '</span>',
    attempt.observed_tokens == null ? '' : '<span>' + compact(attempt.observed_tokens) + ' observed tokens</span>',
    taskTime(attempt.started),
  ].filter(Boolean);
  return parts.length ? '<div class="history-meta">' + parts.join('') + '</div>' : '';
}

function historyEntry(title, attempt) {
  const [outcome, tone] = attemptStatus(attempt);
  const routine = ['assessed','reported','completed','implemented'].includes(attempt.outcome);
  const badge = routine ? '' : '<span class="pill ' + tone + '">' + outcome + '</span>';
  return '<li><div class="history-entry-title"><strong>' + escape(title) + '</strong>' +
    badge + '</div>' + attemptMeta(attempt) + '</li>';
}

function implementationAttempt(attempt) {
  return attempt.role === 'implementation' ||
    (attempt.role !== 'review' && ['implementation','repair'].includes(attempt.phase));
}

function activityHistory(task, attempts, checks) {
  const implementations = attempts.filter(implementationAttempt).length;
  const reviewCount = attempts.filter(attempt => attempt.role === 'review').length;
  let implementationIndex = 0, reviewIndex = 0;
  const timeline = attempts.map(attempt => {
    if (attempt.role === 'review') return historyEntry('Review ' + ++reviewIndex, attempt);
    if (implementationAttempt(attempt)) return historyEntry('Implementation attempt ' + ++implementationIndex, attempt);
    return historyEntry(cap(attempt.phase || attempt.role || 'Unknown step'), attempt);
  });
  const count = implementations ? plural(implementations, 'implementation attempt') :
    reviewCount ? plural(reviewCount, 'review') : plural(attempts.length, 'recorded attempt');
  const historyCount = attempts.length ? '<small>' + count + '</small>' : '';
  const note = implementations > 1
    ? '<p>Implementation attempts are separate passes on the same task.</p>' : '';
  const checksList = checks.length ? '<ul class="history-list">' + checks.map(check => {
    const parts = [taskTime(check.started), check.duration_ms == null ? '' : '<span>' + duration(check.duration_ms) + '</span>',
      check.reused == null ? '' : '<span>' + plural(check.reused, 'reused check') + '</span>'].filter(Boolean);
    return '<li><strong>Verification recorded</strong>' +
      (parts.length ? '<div class="history-meta">' + parts.join('') + '</div>' : '') + '</li>';
  }).join('') + '</ul>' : '';
  const gaps = [
    task.agent_ms == null ? 'agent time' : '',
    task.observed_tokens == null ? 'token usage' : '',
  ].filter(Boolean);
  const notes = (checks.length ? '' : '<p>No check results are recorded here.</p>') +
    (gaps.length ? '<p>Complete totals for ' + gaps.join(' and ') + ' are unavailable.</p>' : '');
  return '<details class="activity-history"><summary><span class="activity-summary">' +
    '<span>Activity history</span>' + historyCount + '</span></summary><div class="activity-body">' + note +
    (timeline.length ? '<ol class="history-list">' + timeline.join('') + '</ol>' : '<p>No work attempts are recorded here.</p>') +
    (notes ? '<div class="activity-notes">' + notes + '</div>' : '') +
    (checks.length ? '<section class="activity-checks"><h3>Verification</h3>' + checksList + '</section>' : '') +
    '</div></details>';
}

function taskHistory(task, data) {
  const latest = data.attempts.findLast(attempt => attempt.role === 'review');
  const checks = data.verification.filter(check => check.phase === 'verification');
  const latestCopy = {
    blocking: 'Open the review in your host to see the blocking findings.',
    needs_resolution: 'Open the review in your host to see the findings.',
    review_incomplete: 'This attempt has no complete review result.',
  };
  const latestNote = latest && Object.hasOwn(latestCopy, latest.outcome) ? '<p>' + latestCopy[latest.outcome] + '</p>' : '';
  const latestReview = latest
    ? '<div class="latest-review"><strong>' + attemptStatus(latest)[0] + '</strong>' + latestNote + '</div>'
    : '<p class="history-empty">No review result is recorded here.</p>';
  html('detail-content', '<section class="task-history-section"><h3>Latest review</h3>' + latestReview + '</section>' +
    activityHistory(task, data.attempts, checks));
}

async function loadTaskHistory(detailState) {
  detailState.request?.abort();
  const request = new AbortController();
  detailState.request = request;
  $('task-detail-error').hidden = true;
  $('detail-content').hidden = true;
  $('download-task-history').disabled = true;
  label('task-detail-loading', 'Loading task history…');
  $('task-detail-loading').hidden = false;
  try {
    const {task} = detailState;
    const data = await get('/api/task?' + new URLSearchParams({run: task.run, task: task.id}), request.signal);
    if (state.detail !== detailState || detailState.request !== request || !$('detail').open) return;
    taskHistory(task, data);
    const lastFinish = detailState.task.status === 'completed' ? data.events.findLast(event => event.kind === 'task.finished') : null;
    const finishedAt = lastFinish && taskTime(lastFinish.at);
    if (finishedAt) html('task-detail-status-note', 'Completed ' + finishedAt);
    detailState.data = data;
    $('detail-content').hidden = false;
    $('download-task-history').disabled = !data.attempts.length && !data.events.length && !data.verification.length;
  } catch (error) {
    if (state.detail === detailState && detailState.request === request && error.name !== 'AbortError') {
      $('task-detail-error').hidden = false;
    }
  } finally {
    if (state.detail === detailState && detailState.request === request) $('task-detail-loading').hidden = true;
  }
}

function detail(trigger) {
  const dialog = $('detail');
  if (dialog.open) return;
  const {run,task:taskId} = trigger.dataset;
  const task = state.data?.tasks.find(task => task.run === run && task.id === taskId);
  if (!task) return;
  state.detail?.request?.abort();
  const detailState = {task, trigger};
  state.detail = detailState;
  taskSnapshot(task);
  trigger.focus({preventScroll:true});
  dialog.showModal();
  dialog.querySelector('.task-detail-scroll').scrollTop = 0;
  loadTaskHistory(detailState);
}

function downloadTaskHistory() {
  const {task, data} = state.detail ?? {};
  if (!data || !$('detail').open) return;
  const content = {
    task: {run: task.run, id: task.id, title: task.title, project: task.name},
    attempts: data.attempts, verification: data.verification, events: data.events,
    event_limit: 300,
  };
  const blob = new Blob([JSON.stringify(content, null, 2) + '\n'], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  const id = [task.run,task.id].join('-').replace(/[^a-z0-9_-]/gi,'-').slice(0,100);
  link.href = url;
  link.download = 'oh-task-history-' + id + '.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function selectRange() {
  for (const button of document.querySelectorAll('.range button')) {
    button.setAttribute('aria-pressed', String(state.custom ? button.id === 'custom' : +button.dataset.days === state.days));
  }
  state.offset = 0;
  refresh();
}

function openDates(mode) {
  const dialog = $('date-dialog');
  dialog.dataset.mode = mode;
  label('date-title', mode === 'baseline' ? 'Comparison dates' : 'Custom date range');
  const current = mode === 'baseline' && state.baseline ? state.baseline : dates();
  $('date-from').value = current[0];
  $('date-to').value = current[1];
  $('date-to').setCustomValidity('');
  dialog.showModal();
}

$('detail').addEventListener('close', () => {
  if ($('detail').open) return;
  const detailState = state.detail;
  state.detail = null;
  detailState?.request?.abort();
  if (detailState) {
    const {run, id} = detailState.task;
    const target = detailState.trigger.isConnected ? detailState.trigger :
      [...$('rows').querySelectorAll('.task-button')].find(button => button.dataset.run === run && button.dataset.task === id);
    (target ?? $('rows').closest('.table-wrap')).focus({preventScroll:true});
  }
});
$('retry-task-history').addEventListener('click', () => {
  if (!state.detail) return;
  $('detail').querySelector('.task-detail-scroll').focus({preventScroll:true});
  loadTaskHistory(state.detail);
});
$('download-task-history').addEventListener('click', downloadTaskHistory);
$('rows').addEventListener('click', event => {
  const button = event.target.closest('tr')?.querySelector('.task-button');
  if (button) detail(button);
});
$('prev-page').addEventListener('click', () => { state.offset -= state.data.page_size; refresh(); });
$('next-page').addEventListener('click', () => { state.offset += state.data.page_size; refresh(); });
for (const button of document.querySelectorAll('[data-days]')) button.addEventListener('click', () => {
  state.days = Number(button.dataset.days);
  state.custom = null;
  selectRange();
});
for (const key of ['project', ...advanced]) $(key).addEventListener('change', () => { state.offset = 0; refresh(); });
$('comparison').addEventListener('change', () => {
  if ($('comparison').value === 'custom') openDates('baseline');
  else { state.offset = 0; refresh(); }
});
$('edit-baseline').addEventListener('click', () => openDates('baseline'));
$('custom').addEventListener('click', () => openDates('range'));
for (const id of ['date-from', 'date-to']) $(id).addEventListener('input', () => $('date-to').setCustomValidity(''));
$('date-form').addEventListener('submit', event => {
  if (event.submitter?.value === 'cancel') {
    if ($('date-dialog').dataset.mode === 'baseline' && !state.baseline) $('comparison').value = 'previous';
    return;
  }
  event.preventDefault();
  const endpoints = [$('date-from').value, $('date-to').value];
  const span = (dayTime(endpoints[1]) - dayTime(endpoints[0])) / dayMs;
  if (span < 0 || span >= 3660) {
    $('date-to').setCustomValidity('Choose an end date within ten years of the start date.');
    $('date-to').reportValidity();
    return;
  }
  if ($('date-dialog').dataset.mode === 'baseline') state.baseline = endpoints;
  else state.custom = endpoints;
  $('date-dialog').close('apply');
  selectRange();
});
$('date-dialog').addEventListener('close', () => {
  if ($('date-dialog').dataset.mode === 'baseline' && !state.baseline) $('comparison').value = 'previous';
  $('edit-baseline').hidden = $('comparison').value !== 'custom';
});
$('comparison').addEventListener('change', () => { $('edit-baseline').hidden = $('comparison').value !== 'custom'; });
$('refresh').addEventListener('click', refresh);
$('retry').addEventListener('click', refresh);
document.querySelector('.skip').addEventListener('click', event => {
  event.preventDefault();
  $('content').focus();
});
window.addEventListener('hashchange', showView);
const themeMedia = window.matchMedia('(prefers-color-scheme: light)');
const themeKey = 'oh-dashboard-theme';
const themeUrl = new URL(location.href);
const requestedTheme = themeUrl.searchParams.get('theme');
let themePreference;
try {
  themePreference = localStorage.getItem(themeKey);
} catch {
  // The theme still works when browser storage is unavailable.
}

function applyTheme(preference) {
  if (preference === 'light' || preference === 'dark') {
    themePreference = preference;
    try { localStorage.setItem(themeKey, preference); } catch { /* Optional persistence. */ }
  }
  const dark = themePreference === 'dark' || (themePreference !== 'light' && !themeMedia.matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  $('theme').setAttribute('aria-pressed', String(dark));
  for (const canvas of document.querySelectorAll('canvas.spark')) canvas.drawSpark?.();
}

applyTheme(requestedTheme);
if (requestedTheme === 'dark' || requestedTheme === 'light') {
  themeUrl.searchParams.delete('theme');
  history.replaceState(history.state, '', themeUrl);
}
$('theme').addEventListener('click', () => {
  applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
});
themeMedia.addEventListener('change', () => applyTheme());
setInterval(() => {
  if (!document.hidden && !state.request && !document.querySelector('dialog[open]')) refresh();
}, 12000);
showView();
