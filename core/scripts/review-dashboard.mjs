#!/usr/bin/env node
// Local review-attempt telemetry. Writes only ignored .deliver/dashboard output.
// Nothing here participates in review, task, PR, or merge authority.
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { spawnSync } from 'node:child_process';

function repositoryRoot() {
  if (process.env.CLAUDE_PROJECT_DIR) return path.resolve(process.env.CLAUDE_PROJECT_DIR);
  const result = spawnSync('git', ['rev-parse', '--show-toplevel'], { cwd: process.cwd(), encoding: 'utf8' });
  if (result.status !== 0 || !result.stdout.trim()) throw new Error('review-dashboard: cannot resolve repository root');
  return path.resolve(result.stdout.trim());
}

const root = repositoryRoot();
const reviews = path.join(root, '.deliver', 'reviews');
const outputArg = process.argv.indexOf('--output');
const outDir = outputArg >= 0 ? path.resolve(process.argv[outputArg + 1]) : path.join(root, '.deliver', 'dashboard');
const stdoutOnly = process.argv.includes('--stdout');

function entries(dir, label, missingIsEmpty = true) {
  let stat;
  try { stat = fs.lstatSync(dir); }
  catch (error) {
    if (missingIsEmpty && error?.code === 'ENOENT') return [];
    throw new Error(`review-dashboard: cannot inspect ${label}`, { cause: error });
  }
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error(`review-dashboard: malformed ${label}`);
  try { return fs.readdirSync(dir, { withFileTypes: true }); }
  catch (error) { throw new Error(`review-dashboard: cannot read ${label}`, { cause: error }); }
}

function read(file, required = true) {
  try {
    const stat = fs.lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('not a regular file');
    return fs.readFileSync(file, 'utf8');
  } catch (error) {
    if (!required && error?.code === 'ENOENT') return null;
    throw new Error(`review-dashboard: cannot read ${path.relative(root, file)}`, { cause: error });
  }
}

function jsonFile(file, required = true) {
  const text = read(file, required);
  if (text == null) return null;
  try { return JSON.parse(text); }
  catch (error) { throw new Error(`review-dashboard: malformed ${path.relative(root, file)}`, { cause: error }); }
}

function header(text, key) {
  const before = text.split(/^---\s*$/m, 1)[0];
  const matches = [...before.matchAll(new RegExp(`^${key}: (.*)$`, 'gm'))];
  return matches.length === 1 ? matches[0][1] : null;
}

function severityOutcome(findings, explicitClean = false) {
  const has = (severity) => findings.some((finding) => finding.severity === severity);
  const parts = [];
  if (has('blocking')) parts.push('blocking');
  if (has('concern')) parts.push('concern');
  if (has('scope')) parts.push('scope');
  return parts.join('+') || (explicitClean ? 'clean' : 'ambiguous');
}

function parseAttempt(series, attemptDir) {
  const start = jsonFile(path.join(attemptDir, 'start.json'));
  if (start.seriesId !== series.id || start.id !== path.basename(attemptDir) || !Number.isInteger(start.ordinal)) {
    throw new Error(`review-dashboard: malformed attempt identity ${path.relative(root, attemptDir)}`);
  }
  const completion = jsonFile(path.join(attemptDir, 'completion.json'), false);
  const resolution = jsonFile(path.join(attemptDir, 'resolution.json'), false);
  const scopeTransition = jsonFile(path.join(attemptDir, 'scope-transition.json'), false);
  const scopeDestination = jsonFile(path.join(attemptDir, 'scope-destination.json'), false);
  const raw = path.join(attemptDir, 'raw.md');
  const rawPresent = fs.existsSync(raw);
  const findings = Array.isArray(completion?.findings) ? completion.findings.map((finding) => ({
    severity: finding.severity,
    claim: finding.claim,
    line: finding.line,
    family: null,
    relation: 'unknown',
  })) : [];
  const input = Number.isInteger(completion?.hostTokenUsage?.input) ? completion.hostTokenUsage.input : null;
  const output = Number.isInteger(completion?.hostTokenUsage?.output) ? completion.hostTokenUsage.output : null;
  const completedAt = completion?.completedAt || null;
  const validResolutionId = (value) => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
  const scopeApplied = scopeTransition?.status === 'applied'
    && scopeTransition?.originalTree === start.tree
    && typeof scopeTransition?.resultTree === 'string';
  const scopeRetainedInPr = scopeTransition?.status === 'pr-required'
    && scopeTransition?.originalTree === start.tree
    && scopeTransition?.resultTree === start.tree
    && validResolutionId(scopeTransition?.prResolutionId);
  const scopeRoutedToIssue = scopeTransition?.status === 'human-route-required'
    && scopeTransition?.originalTree === start.tree
    && scopeDestination?.status === 'applied'
    && scopeDestination?.kind === 'github-issue'
    && scopeDestination?.originalTree === start.tree
    && scopeDestination?.resultTree === start.tree
    && /^https:\/\/[^/]+\/.+\/issues\/[1-9][0-9]*$/.test(scopeDestination?.issueUrl || '')
    && validResolutionId(scopeDestination?.prResolutionId);
  const scopeChoice = resolution?.choice?.includes('scope') === true;
  const resolvedAt = !resolution ? null
    : !scopeChoice ? resolution.recordedAt || null
      : scopeRoutedToIssue ? scopeDestination.recordedAt || null
        : scopeApplied || scopeRetainedInPr ? scopeTransition.recordedAt || null
          : null;
  const resolutionSeconds = completedAt && resolvedAt
    ? Math.max(0, Math.round((Date.parse(resolvedAt) - Date.parse(completedAt)) / 1000))
    : null;
  const accepted = completion?.status === 'completed' && completion?.outcome === 'clean'
    ? 'clean'
    : completion?.status === 'completed' && resolution && ['accept-concerns', 'route-scope', 'dismiss-scope',
      'accept-concerns+route-scope', 'accept-concerns+dismiss-scope'].includes(resolution.choice)
      && (!resolution.choice.includes('scope') || scopeApplied || scopeRetainedInPr || scopeRoutedToIssue)
      ? 'human-resolved'
      : 'unresolved';
  return {
    source: 'attempt',
    key: start.roundKey,
    seriesId: start.seriesId,
    attemptId: start.id,
    roundId: start.id,
    ordinal: start.ordinal,
    route: start.roundKey?.startsWith('nd/') ? 'non-delivery' : 'delivery',
    host: start.host,
    tree: start.tree,
    head: start.head,
    startedAt: start.startedAt,
    completedAt,
    elapsedSeconds: Number.isInteger(completion?.elapsedSeconds) ? completion.elapsedSeconds : null,
    status: completion?.status || 'pending',
    outcome: completion?.outcome || 'pending',
    accepted,
    formatAnomalous: completion?.formatAnomalous === true,
    salvaged: completion?.status === 'completed' && completion?.formatAnomalous === true
      && completion?.outcome !== 'ambiguous',
    rawOutput: rawPresent ? path.relative(root, raw) : null,
    findings,
    humanResolution: resolution?.choice || null,
    resolutionSource: resolution?.source || null,
    resolutionSeconds,
    scopeTransition,
    scopeDestination,
    prResolutionId: jsonFile(path.join(attemptDir, 'pr-resolution.json'), false)?.id
      || scopeTransition?.prResolutionId || scopeDestination?.prResolutionId || null,
    hostTokenUsage: { input, output },
    request: fs.existsSync(path.join(attemptDir, 'request.md')) ? path.relative(root, path.join(attemptDir, 'request.md')) : null,
  };
}

function loadAttempts() {
  const seriesRoot = path.join(reviews, 'series');
  const result = [];
  for (const seriesEntry of entries(seriesRoot, 'review series root')) {
    if (!seriesEntry.isDirectory() || seriesEntry.isSymbolicLink() || !/^s-[0-9]{10}-[0-9a-f]{24}$/.test(seriesEntry.name)) {
      throw new Error(`review-dashboard: malformed review series ${seriesEntry.name}`);
    }
    const dir = path.join(seriesRoot, seriesEntry.name);
    const series = jsonFile(path.join(dir, 'series.json'));
    if (series.id !== seriesEntry.name) throw new Error(`review-dashboard: malformed series identity ${seriesEntry.name}`);
    const attemptsDir = path.join(dir, 'attempts');
    for (const attemptEntry of entries(attemptsDir, `attempts for ${series.id}`)) {
      if (!attemptEntry.isDirectory() || attemptEntry.isSymbolicLink() || !/^a-\d{6}$/.test(attemptEntry.name)) {
        throw new Error(`review-dashboard: malformed attempt ${attemptEntry.name}`);
      }
      const attemptDir = path.join(attemptsDir, attemptEntry.name);
      const startFile = path.join(attemptDir, 'start.json');
      let startStat;
      try { startStat = fs.lstatSync(startFile); }
      catch (error) {
        if (error?.code === 'ENOENT') continue;
        throw new Error(`review-dashboard: cannot inspect ${path.relative(root, startFile)}`, { cause: error });
      }
      if (!startStat.isFile() || startStat.isSymbolicLink()) {
        throw new Error(`review-dashboard: malformed attempt start ${path.relative(root, startFile)}`);
      }
      result.push(parseAttempt(series, attemptDir));
    }
  }
  return result;
}

function walkLegacy(dir, found = []) {
  const children = entries(dir, 'accepted-round root');
  const roundChildren = children.filter((entry) => entry.isDirectory() && !entry.isSymbolicLink()
    && /^[0-9a-f]{16}-\d+-[0-9a-f]{16}$/.test(entry.name));
  if (roundChildren.length) {
    for (const entry of children) {
      if (entry.isSymbolicLink() || !entry.isDirectory()
          || !/^[0-9a-f]{16}-\d+-[0-9a-f]{16}$/.test(entry.name)) {
        throw new Error(`review-dashboard: malformed accepted review entry ${path.relative(root, path.join(dir, entry.name))}`);
      }
      found.push(path.join(dir, entry.name, 'review.md'));
    }
    return found;
  }
  for (const entry of children) {
    if (entry.isSymbolicLink()) throw new Error(`review-dashboard: symlink in accepted history: ${entry.name}`);
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) { walkLegacy(full, found); continue; }
    // A path with no syntactically valid retained round is not evidence. Ignore it here;
    // authoritative readers still fail closed when that exact review key is consumed.
  }
  return found;
}

function parseLegacy(file) {
  const text = read(file);
  const roundDir = path.dirname(file);
  const findings = [...text.matchAll(/^\[(BLOCKING|CONCERN|SCOPE)\][ :-]*(.+)$/gmi)]
    .map((match) => ({ severity: match[1].toLowerCase(), claim: match[2], line: null, family: null, relation: 'unknown' }));
  const metadata = [...text.matchAll(/^- Finding (\d+) \| Family: ([a-z0-9][a-z0-9-]*) \| Relation: ([a-z-]+)$/gm)];
  for (const match of metadata) {
    const finding = findings[Number(match[1]) - 1];
    if (finding) Object.assign(finding, { family: match[2], relation: match[3] });
  }
  const explicitClean = /^VERDICT:\s*clean\b/gmi.test(text);
  const elapsed = header(text, 'elapsed-seconds');
  const prior = header(text, 'prior-rounds');
  const key = header(text, 'round-key');
  const roundId = header(text, 'round-id') || path.basename(roundDir);
  if (!key || !roundId) throw new Error(`review-dashboard: malformed accepted receipt ${path.relative(root, file)}`);
  return {
    source: 'legacy-accepted', key, seriesId: null, attemptId: null, roundId,
    ordinal: /^\d+$/.test(prior || '') ? Number(prior) + 1 : null,
    route: key.startsWith('nd/') ? 'non-delivery' : 'delivery', host: null,
    tree: header(text, 'tree'), head: header(text, 'head'), startedAt: null,
    completedAt: header(text, 'at'), elapsedSeconds: /^\d+$/.test(elapsed || '') ? Number(elapsed) : null,
    status: 'completed', outcome: severityOutcome(findings, explicitClean), accepted: explicitClean ? 'clean' : 'legacy-findings',
    formatAnomalous: false, salvaged: false, rawOutput: path.relative(root, file), findings,
    humanResolution: null, resolutionSource: null, resolutionSeconds: null, scopeTransition: null, scopeDestination: null,
    hostTokenUsage: { input: null, output: null },
    request: fs.existsSync(path.join(roundDir, 'request.md')) ? path.relative(root, path.join(roundDir, 'request.md')) : null,
  };
}

function loadLegacy() {
  return walkLegacy(path.join(reviews, 'accepted')).map(parseLegacy);
}

function activeHistoricalCorrectionIds() {
  const active = new Set();
  const inflight = path.join(reviews, 'inflight');
  for (const entry of entries(inflight, 'historical in-flight correction root')) {
    if (!entry.isDirectory() || entry.isSymbolicLink()) {
      throw new Error(`review-dashboard: malformed historical in-flight entry ${entry.name}`);
    }
    const dir = path.join(inflight, entry.name);
    const owner = read(path.join(dir, 'owner')).trim();
    const admission = read(path.join(dir, 'admission')).trimEnd().split('\t');
    if (admission.length !== 10 || !/^[0-9a-f]{16}$/.test(admission[0])
        || !/^\d+$/.test(admission[1]) || !/^[0-9a-f]{24}$/.test(owner)
        || admission[8] !== owner) {
      throw new Error(`review-dashboard: malformed historical in-flight correction ${entry.name}`);
    }
    active.add(`${admission[0]}-${admission[1]}-${owner.slice(0, 16)}`);
  }
  return active;
}

function loadHistoricalCorrections(knownRoundIds, activeRoundIds) {
  const rejectedRoot = path.join(reviews, 'rejected');
  const corrections = [];
  function walk(dir) {
    for (const entry of entries(dir, 'historical correction root')) {
      if (entry.isSymbolicLink()) throw new Error(`review-dashboard: symlink in correction history: ${entry.name}`);
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile() && entry.name.endsWith('.md')) {
        const roundId = path.basename(entry.name, '.md');
        const text = read(full);
        const accepted = knownRoundIds.get(roundId);
        const rejectedAt = header(text, 'at');
        const acceptedAt = accepted?.completedAt || null;
        const turnaroundSeconds = rejectedAt && acceptedAt
          ? Math.max(0, Math.round((Date.parse(acceptedAt) - Date.parse(rejectedAt)) / 1000))
          : null;
        corrections.push({
          path: path.relative(root, full), roundId,
          status: accepted ? 'succeeded' : activeRoundIds.has(roundId) ? 'pending' : 'failed',
          acceptedRound: accepted?.rawOutput || null, turnaroundSeconds,
        });
      } else throw new Error(`review-dashboard: malformed historical correction entry ${path.relative(root, full)}`);
    }
  }
  walk(rejectedRoot);
  return corrections;
}

const rounds = [...loadAttempts(), ...loadLegacy()].sort((a, b) =>
  String(a.startedAt || a.completedAt).localeCompare(String(b.startedAt || b.completedAt))
  || String(a.roundId).localeCompare(String(b.roundId)));
const knownRoundIds = new Map(rounds.map((round) => [round.roundId, round]));
const historicalCorrections = loadHistoricalCorrections(knownRoundIds, activeHistoricalCorrectionIds());
const byKey = new Map();
for (const round of rounds) {
  if (!byKey.has(round.key)) byKey.set(round.key, []);
  byKey.get(round.key).push(round);
}

const tasks = [...byKey].map(([key, keyRounds]) => {
  keyRounds.sort((a, b) => (a.ordinal ?? Number.MAX_SAFE_INTEGER) - (b.ordinal ?? Number.MAX_SAFE_INTEGER));
  const findings = keyRounds.flatMap((round) => round.findings);
  const classified = findings.filter((finding) => finding.relation !== 'unknown').length;
  const relation = (name) => findings.filter((finding) => finding.relation === name).length;
  const knownRelations = classified === findings.length;
  return {
    key,
    route: key.startsWith('nd/') ? 'non-delivery' : 'delivery',
    seriesIds: [...new Set(keyRounds.map((round) => round.seriesId).filter(Boolean))],
    rounds: keyRounds,
    roundsToClean: (keyRounds.findIndex((round) => round.accepted === 'clean') + 1) || null,
    firstRoundClean: keyRounds[0]?.accepted === 'clean',
    findings: findings.length,
    blocking: findings.filter((finding) => finding.severity === 'blocking').length,
    concerns: findings.filter((finding) => finding.severity === 'concern').length,
    scope: findings.filter((finding) => finding.severity === 'scope').length,
    classifiedFindings: classified,
    unknownFindings: findings.length - classified,
    classificationCoverage: findings.length ? classified / findings.length : 1,
    firstRoundEscapes: knownRelations ? relation('first-round-escape') : null,
    repeatFamilies: knownRelations ? relation('repeat-family') : null,
    fixRegressions: knownRelations ? relation('fix-regression') : null,
    newlyExposed: knownRelations ? relation('newly-exposed') : null,
    disputes: keyRounds.filter((round) => round.humanResolution?.includes('accept')).length,
    elapsedSeconds: keyRounds.every((round) => Number.isFinite(round.elapsedSeconds))
      ? keyRounds.reduce((sum, round) => sum + round.elapsedSeconds, 0) : null,
  };
}).sort((a, b) => a.key.localeCompare(b.key));

const knownTokenRounds = rounds.filter((round) => Number.isInteger(round.hostTokenUsage.input) || Number.isInteger(round.hostTokenUsage.output));
const resolutionTimes = rounds.map((round) => round.resolutionSeconds).filter(Number.isFinite);
const correctionTimes = historicalCorrections.map((correction) => correction.turnaroundSeconds).filter(Number.isFinite);
const correctionSummary = {
  attempted: historicalCorrections.length,
  succeeded: historicalCorrections.filter((item) => item.status === 'succeeded').length,
  failed: historicalCorrections.filter((item) => item.status === 'failed').length,
  pending: historicalCorrections.filter((item) => item.status === 'pending').length,
  turnaroundSeconds: correctionTimes.length ? {
    known: correctionTimes.length,
    total: correctionTimes.reduce((sum, value) => sum + value, 0),
    average: correctionTimes.reduce((sum, value) => sum + value, 0) / correctionTimes.length,
  } : null,
};
const summary = {
  tasks: tasks.length,
  subjects: tasks.length,
  rounds: rounds.length,
  attempts: rounds.length,
  deliveryReviews: rounds.filter((round) => round.route === 'delivery').length,
  nonDeliveryReviews: rounds.filter((round) => round.route === 'non-delivery').length,
  pendingAttempts: rounds.filter((round) => round.status === 'pending').length,
  interruptedAttempts: rounds.filter((round) => round.status === 'interrupted').length,
  ambiguousAttempts: rounds.filter((round) => round.outcome === 'ambiguous').length,
  findings: rounds.reduce((sum, round) => sum + round.findings.length, 0),
  firstRoundClean: tasks.filter((task) => task.firstRoundClean).length,
  classifiedFindings: tasks.reduce((sum, task) => sum + task.classifiedFindings, 0),
  unknownFindings: tasks.reduce((sum, task) => sum + task.unknownFindings, 0),
  classificationCoverage: tasks.reduce((sum, task) => sum + task.findings, 0)
    ? tasks.reduce((sum, task) => sum + task.classifiedFindings, 0) / tasks.reduce((sum, task) => sum + task.findings, 0) : 1,
  firstRoundEscapes: tasks.every((task) => task.firstRoundEscapes != null) ? tasks.reduce((sum, task) => sum + task.firstRoundEscapes, 0) : null,
  repeatFamilies: tasks.every((task) => task.repeatFamilies != null) ? tasks.reduce((sum, task) => sum + task.repeatFamilies, 0) : null,
  fixRegressions: tasks.every((task) => task.fixRegressions != null) ? tasks.reduce((sum, task) => sum + task.fixRegressions, 0) : null,
  newlyExposed: tasks.every((task) => task.newlyExposed != null) ? tasks.reduce((sum, task) => sum + task.newlyExposed, 0) : null,
  disputes: tasks.reduce((sum, task) => sum + task.disputes, 0),
  elapsedSeconds: rounds.every((round) => Number.isFinite(round.elapsedSeconds))
    ? rounds.reduce((sum, round) => sum + round.elapsedSeconds, 0) : null,
  formatAnomalousAttempts: rounds.filter((round) => round.formatAnomalous).length,
  reviewsSalvaged: rounds.filter((round) => round.salvaged).length,
  humanResolutions: rounds.filter((round) => round.accepted === 'human-resolved').length,
  resolutionTurnaroundSeconds: resolutionTimes.length ? {
    known: resolutionTimes.length,
    total: resolutionTimes.reduce((sum, value) => sum + value, 0),
    average: resolutionTimes.reduce((sum, value) => sum + value, 0) / resolutionTimes.length,
  } : null,
  corrections: correctionSummary,
  estimatedAvoidedReviewerRuns: rounds.filter((round) => round.salvaged).length + correctionSummary.succeeded,
  hostTokenUsage: knownTokenRounds.length ? {
    knownAttempts: knownTokenRounds.length,
    input: knownTokenRounds.reduce((sum, round) => sum + (round.hostTokenUsage.input || 0), 0),
    output: knownTokenRounds.reduce((sum, round) => sum + (round.hostTokenUsage.output || 0), 0),
  } : null,
  tokenCost: null,
  calibrationCases: entries(path.join(root, '.claude', 'reviewer-calibration', 'cases')).filter((entry) => entry.isDirectory()).length,
  calibrationRecall: null,
};

const report = {
  reportVersion: 2,
  generatedAt: new Date().toISOString(),
  authority: 'telemetry only — review attempts and human resolutions are workflow evidence; human merge remains authoritative',
  tokenCostNote: summary.hostTokenUsage ? 'host token counts are actual where supplied; currency cost is unavailable' : 'host token usage unavailable for retained attempts',
  estimateNote: 'estimated avoided reviewer runs count format-anomalous attempts retained by the semantic parser plus successful historical correction handshakes',
  calibrationNote: 'recall unavailable until confirmed cases are replayed by a comparative reviewer evaluation',
  summary,
  historicalCorrections,
  tasks,
};

const serialized = `${JSON.stringify(report, null, 2)}\n`;
if (stdoutOnly) {
  await new Promise((resolve) => process.stdout.write(serialized, resolve));
  process.exit(0);
}

fs.mkdirSync(outDir, { recursive: true });
const tmpJson = path.join(outDir, `.report.${process.pid}.json`);
fs.writeFileSync(tmpJson, serialized);
fs.renameSync(tmpJson, path.join(outDir, 'report.json'));

const esc = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const cards = [
  ['Attempts', summary.attempts], ['Non-delivery', summary.nonDeliveryReviews], ['Findings', summary.findings],
  ['Salvaged', summary.reviewsSalvaged], ['Human resolutions', summary.humanResolutions],
  ['Pending', summary.pendingAttempts], ['Interrupted', summary.interruptedAttempts],
  ['Corrections', `${summary.corrections.attempted} attempted · ${summary.corrections.succeeded} succeeded · ${summary.corrections.failed} failed · ${summary.corrections.pending} pending`],
  ['Estimated avoided runs', summary.estimatedAvoidedReviewerRuns],
  ['Known token attempts', summary.hostTokenUsage?.knownAttempts ?? 0],
].map(([label, value]) => `<article><small>${esc(label)}</small><strong>${esc(value)}</strong></article>`).join('');
const rows = tasks.map((task) => `<tr><td>${esc(task.key)}</td><td>${esc(task.route)}</td><td>${task.rounds.length}</td><td>${task.roundsToClean ?? '—'}</td><td>${task.findings}</td><td>${task.rounds.filter((round) => round.salvaged).length}</td><td>${task.rounds.filter((round) => round.humanResolution).length}</td><td>${task.elapsedSeconds == null ? '—' : `${task.elapsedSeconds}s`}</td></tr>`).join('');
const html = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Review attempts</title><style>
:root{font-family:ui-sans-serif,system-ui;color:#17212b;background:#f4f7f9}body{max-width:1200px;margin:0 auto;padding:32px}h1{margin-bottom:4px}.note{color:#52606d}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:24px 0}.cards article{background:white;border:1px solid #d9e2ec;border-radius:10px;padding:16px}.cards small{display:block;color:#627d98}.cards strong{font-size:1.65rem}table{width:100%;border-collapse:collapse;background:white;border-radius:10px;overflow:hidden}th,td{text-align:left;padding:12px;border-bottom:1px solid #e6edf2}th{background:#eaf0f5}code{background:#eaf0f5;padding:2px 5px;border-radius:4px}</style><body>
<h1>Invariant review attempts</h1><p class="note">Telemetry only. A dashboard value never authorizes a task, PR, or merge. Generated ${esc(report.generatedAt)}.</p>
<section class="cards">${cards}</section><table><thead><tr><th>Review key</th><th>Route</th><th>Attempts</th><th>Rounds to clean</th><th>Findings</th><th>Salvaged</th><th>Human resolutions</th><th>Review time</th></tr></thead><tbody>${rows}</tbody></table>
<p class="note">Machine-readable data: <code>report.json</code>. ${esc(report.tokenCostNote)}. ${esc(report.estimateNote)}.</p></body></html>`;
const tmpHtml = path.join(outDir, `.index.${process.pid}.html`);
fs.writeFileSync(tmpHtml, html);
fs.renameSync(tmpHtml, path.join(outDir, 'index.html'));
process.stdout.write(`review-dashboard: ${path.relative(root, path.join(outDir, 'index.html'))}\n`);
