# Quick-fix approval and existing-PR corrections

Approved scope: restore visible previews on the current Claude host, accept typed
choices consistently, retain an explicitly requested PR branch during preparation,
and publish its reviewed correction to that same PR. No new gates, agents, review
policy, consumer configuration or changes to the stopped consumer run.

The golden reference (`my-geoffrey`, `harness-before-separation`) keeps useful
unmerged work on its delivery branch and finishes that branch through one PR.
OH retains its existing fresh-worker execution and immutable evidence. A correction
after publication is a new approved scope, not a reopening of the published run.

## Ordered work

- [x] Support the actual Claude file-display capability and a complete chat fallback;
  preserve the native question payload and existing Codex presentation.
- [x] Normalize recognized typed choices at the prompt filter and native-answer
  dispatch; preserve original human evidence and stale/foreign/replay rejection.
- [x] Add an explicit PR selection to preparation on both host entry paths. Defer
  quick-fix branch switching until preparation resolves its target. Bind the PR,
  destination, branch and starting head to the existing immutable prepared record;
  retain that selection through refinement and resume.
- [x] Recognize the selected PR awaiting a reviewed update. Preserve the publication
  approval across push/body-update interruptions; record completion only once the
  reviewed head and updated review summary are present. Never force-push, create a
  competing PR, or rewrite earlier receipts.
- [x] Extend existing behavioral fixtures, run affected checks and syntax, and
  challenge the final diff against scope and authority boundaries.
- [ ] Developer snapshot trial: visible preview, typed Approve, correct branch,
  Stop/resume and one update-PR approval. Independent review/publication follows
  the host trial, as AGENTS.md requires.

## Coverage and decisions

Reuse `test_gates` preparation/refinement and typed-answer fixtures;
`test_installation` prompt-hook fixture; `test_mcp_server` preparation forwarding;
`test_workflow` publication recovery and evidence fixtures. Add one integrated
existing-PR correction scenario because no current fixture covers that transition.
Keep current normal-new-work, review-derived repair, old receipt, Stop/resume,
stale scope and foreign approval coverage. Replace pane-name assertions with
checks of the supported host instructions; real rendering still needs a host trial.

PR selection is optional, runtime-owned and explicit. Normal new work retains its
base-branch policy. The selected PR must be open in the configured origin repository,
with the configured base; forks and changed identities are refused with a remedy.
Changed local work is preserved. Existing saved preparations/receipts retain their
old meaning when the optional target is absent.

## Validation evidence

Before implementation: disposable reproductions confirmed both forced-main paths,
case-sensitive approval rejection and rejection of an existing PR before pushing
its correction. Thirteen existing boundary tests passed. A disposable feasibility
probe confirmed the existing runner can retain old evidence and summarize both runs.
Implementation validation and actual host trial results will be recorded below.

The integrated existing-PR fixture passes (18.9 seconds on the final source): unchanged old receipts,
new bounded implementation/review, refinement retaining its target, stale preview
and changed PR rejection, typed `Approve` applied once, cross-host publication resume,
push/body interruption recovery and idempotent completion. Prompt-hook casing,
native typed-answer provenance and Codex preparation forwarding fixtures also pass.
Syntax, Windows-risk checks and the skill validator pass. The affected run exercised
22 modules: 20 passed outright; Delivery and Workflow exposed fixture issues described
below. Every failing scenario was corrected and rerun successfully; unchanged passing
cases were not repeated. These are local macOS runs, including compatibility fixtures,
not a claim of live Windows/Linux or Claude UI execution.
The first affected run exposed stale assertions in two Delivery tests expecting
`review again`, already removed by `e9ddaa7`. Those assertions now match the existing
approved menus. The direct quick-fix entry assertion now checks deferred branch
selection. All three adjusted scenarios pass (81.8 seconds, including same-host and
cross-host resume subcases). No production menu option was added or removed here.
The cancelled-check fixture now supplies the review ID required by the existing
native receipt schema; its failure-reporting assertions pass (3.1 seconds). This
changes test input only, not cancellation handling or historical receipt readers.

Self-review: new-PR discovery, numbered delivery, independent review, allowances,
escalation and the worker loop are unchanged. Existing PR selection remains optional
and inside the prepared scope/recorded publication grant. Refinement cannot silently
change the repository or PR identity. Approval rechecks the selected head. Publication
accepts only its original head or the newly approved head and handles CRLF in the PR
description. Original receipts are immutable; pending-update status is not saved as
a completion receipt. Tests use synthetic workers and GitHub responses in temporary
repositories; live UI rendering and remote publication remain host-trial checks.

## Developer trial

Run `oh-dev on`, then start a fresh Claude session with the original bounded quick-fix
request explicitly targeting its existing PR and branch. Keep the incorrectly based
old run stopped. Expect the full preview before approval, the intended PR/branch in
that preview, and typed `Approve` accepted once. Stop and resume the new correction
in a fresh session to check preserved scope and allowances. At completion choose
`Update PR #number`; expect the same PR with its new review summary and current-head
CI result, without another OH push decision. Do not reset the old stopped branch.

### First host trial

The existing-PR preparation selected the correct branch and saved its target. Preview
delivery failed: this Claude session had `SendUserFile`, but the host could not deliver
files outside a project thread. Claude batched display and the approval question in
one response, opening the modal before receiving that failure. The instructions now
require a separate completed display call; on failure they use the complete chat
preview and existing typed choices, without opening another modal. This introduces
no approval type or authority change. Repeat the host trial to verify the fallback.

### Native Claude quick-fix plan approval

The real Desktop trial disproved the file-display approach: file cards and option
previews did not reliably show the document. A separate native plan-viewer trial
rendered the complete document in a scrollable side panel. A harmless Accept trial
produced a structured host result containing the exact approved plan and request ID;
Reject produced an error result. Neither diagnostic approved the consumer task.

The golden reference's relevant principle is one decision over the shown scope,
followed by its existing execution machinery. OH needs a host-specific receipt
reader because it delegates execution to its runner. No new gate, service or grant
type is needed. Limit this change to Claude prepared quick fixes (including review
repairs); other workflow approvals and Codex keep their current paths.

- [x] Read native plan acceptance through existing authority, binding the exact
  document and current gate; reject stale, changed, foreign and agent receipts.
- [x] Replace the quick-fix display instructions with native Plan mode and
  ExitPlanMode. Accept is the single scope approval; OH run consumes it. Rejection
  grants nothing. A changed plan must be prepared and shown again, never executed.
- [x] Extend existing authority and prepared-gate fixtures for the new receipt,
  interruption/replay and unchanged old menu/typed/Codex behavior; run affected
  checks and syntax, then self-review scope and authority.
- [x] Enable the development snapshot on both hosts for a fresh Claude trial.
  Independent review/publication remains after that developer trial.

Implementation evidence: the reader recognized the saved, real Desktop diagnostic
acceptance without modifying its transcript or OH state. It ignored the rejection.
The existing prepared-gate fixture now uses a native receipt and passes edited-plan
refusal, once-only approval, interruption during branch activation, recovery without
another decision, and ordinary publication (11.9 seconds). The focused authority
and gate checks passed (7 tests, 19.6 seconds before the added refusal assertion).
One small table-driven authority case covers source, exact content, gate freshness,
request/result pairing, main-agent status, rejection, changed content and CRLF.
No new workflow fixture or production record type was added. The 15 affected modules
were selected against this change. Fourteen passed on the first affected run.
The gate module detected a source-version change because implementation was still
being edited during that run; its production version guard was retained. All 39
gate tests then passed on stable final source (143.0 seconds), including legacy
questions/typed replies, Codex Stop, publication, refinements and exact native-plan
activation. The public-handoff fixture assembles its copy only from fields actually
returned to the coordinator; that targeted run passed (2 tests, 11.8 seconds).
Syntax/Windows-risk checks and the Deliver skill validator passed. These are local
macOS tests with platform fixtures, not live Windows/Linux host trials. No remaining
affected-test failure is unresolved.

Self-review: only Claude prepared-scope gates select the native viewer. Original
preview files and journals stay unchanged. The returned native plan and checkpoint
must match, and the model's original tool arguments must be empty; model prose does
not grant work. Reading the native display file later is never used as approval.
Edits request a new preparation; rejection leaves work pending and grants nothing.
Existing typed choices, ordinary native menus, Codex, review allowances and final
publication retain their current authority paths. Host permission modes remain
host-owned. The earlier quick-fix file-card display approach is superseded here;
other document workflows retain it and are outside this change.

Development snapshot `0.6.0-SNAPSHOT.1791941857442304000` is enabled for Claude and
Codex. Both packaged authority/gate modules and shared/Deliver instructions match
the validated source byte-for-byte. The fresh-session user trial is still pending:
send the original full quick-fix request, read the native side-panel plan and choose
Accept once; OH should begin through its runner without another scope question.

### Fresh-session entry correction

The fresh-session trial exposed an entry failure, not a failed native receipt:
status presented the previous session's unapproved gate before consuming the new
command, then intake treated that unused preview as active work. No worker had
started. Fix the entry rather than asking the developer to stop old runs.

- [x] Suppress an old prepared gate while a different native work command awaits
  verification; return the existing run-command instruction, without mutating state.
- [x] Let a verified newer quick-fix request retire an unused preparation under
  the existing control lock. Preserve its evidence; never replace granted work,
  attempts, or interrupted activation. Prepare the new scope before one approval.
- [x] Route unused preparations to the current installed runtime after upgrades;
  keep interrupted activation and active work pinned to their retained runtime.
- [x] Reproduce two sessions and an older snapshot through the actual entry,
  status, preparation, native approval and execution paths. Check rejected stale
  receipts and protection for already authorized work. Complete the authorized
  live-host check if available before enabling dev; report its exact limits.
- [x] Run affected checks on stable final source, then enable and verify both hosts.

Validation: a new fixture uses the CLI's actual status/run/prepare entrypoints with
an older prepared snapshot and a fresh native session. It proves status does not
expose the old gate, newer verified intake retires only an unused preview, original
records stay unchanged, telemetry reports the old run stopped, an old gate cannot
approve the replacement, and one native acceptance enters the runner. It also
checks that granted work and interrupted activation cannot be replaced. Existing
launcher coverage now checks unused-preparation upgrades and activation pinning.

The affected selector ran 16 modules. Fifteen passed; Gate exposed two refinement
regressions because the pending-command hint also matched refinement feedback.
The hint now excludes that existing feedback path. The final authority, gate and
plugin-transition run passed all 57 tests (189.4 seconds); the other passing modules
were not repeated. Syntax/Windows-risk checks passed. No test assertion or authority
guard was weakened. Local macOS coverage includes platform fixtures, not live
Windows/Linux sessions.

Live validation used a disposable fixture repository and actual Claude Remote
Control sessions, native Plan panels and ordinary Accept. A real old-snapshot
session left an unapproved plan. A fresh candidate session automatically retired
that unused preparation, showed its own exact bound plan, accepted once, and ran
real assessment/implementation/review agents through a passing check and a reviewed
local commit. The final corrected build repeated that scenario successfully:
`0.6.0-SNAPSHOT.1791943622452858000`. Each fresh trial had one ExitPlanMode and one
scope grant, without an AskUserQuestion scope/cleanup menu. No test publication was
performed, and my-geoffrey was untouched. The initial test launch inherited Codex
session identifiers; removing those from the test process environment corrected
the setup without relaxing OH's host-identity guard.

Host limits: ordinary Accept selected Manual command permissions, requiring normal
Claude command approvals in the fixture. In the first trial, Claude's permission
classifier subsequently denied recording the optional final stop decision after
the task had completed; its reviewed local commit remained unpublished. This was
not bypassed. The final trial also successfully recorded Finish without a PR after
its reviewed commit, using a one-time native command permission. OH's scope approval
and the host's command permissions remain distinct.

Enabled the exact final live-tested build on both hosts:
`0.6.0-SNAPSHOT.1791943622452858000`. Its runtime and workflow instructions match
the final source. Reusing the live-tested build initially exposed one extra generated
Python bytecode cache file; all manifested files were unchanged. Removed only that
generated file, verified both original package inventories, and activated the same
build without relaxing integrity checks or changing its code. Fresh consumer sessions
can send the original request; no manual old-run cleanup is required.
