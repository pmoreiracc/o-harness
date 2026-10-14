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
