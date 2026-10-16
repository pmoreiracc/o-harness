# Resume saved work across every OH workflow

Approved implementation plan, 2026-10-16. This document tracks development; unchecked
items are acceptance work still required, not claims about released behavior.

## Experience and scope

Propose, Design, Deliver (including quick fixes), standalone Review and the OH
selector inspect saved work before preparing replacements. Continue from the actual
saved phase with the same scope, settings, findings, attempts and remaining allowance.
A developer should not need to reproduce their original words, remember a run ID,
manage abandoned agents or debug OH storage.

A matching supplied request continues without a redundant resume confirmation.
A command with no subject shows relevant unfinished work and asks once whether to
continue it or choose different work. Multiple plausible matches require selection;
recency alone is not intent. Clearly different requests remain different work.
Completed work presents its result or pending publication/handoff. An explicitly
requested new review after completion uses a fresh reviewer.

Golden reference: my-geoffrey tag harness-before-separation (b508bdc). Deliver's
branch inspection and next.sh use durable progress to determine implementation,
checkpoint, finalization and publication. Design prevents duplicate documents but
has no universal interrupted-run recovery; Propose has no general discovery.
Reuse saved-state-first behavior, not its branch conventions, ADR policies or loop.

## Implementation checklist

- [x] Add status --saved and MCP saved input. Read both workflow and standalone
  review bindings without changing them; unregistered discovery registers nothing.
- [x] Return bounded summaries with run/workflow/subject/branch, current phase,
  pending decisions, unfinished attempts, remaining allowance and evidence references.
  Preserve identities/references when shortening descriptions. No history scanner,
  database, global registry, background monitor or extra model call.
- [x] Add resume --run ID and MCP run input. Read selected facts without mutation;
  verify project, checkout, branch and native human authority before ownership or
  selection changes. Recheck under the existing control lock; retries are idempotent.
- [x] Recognize matching nonempty native workflow invocations as continuation.
  Validate structured initiative/design/track/review selectors. Hosts compare free-text
  intent with scope; no fuzzy thresholds or natural-language similarity parser.
  Empty commands require the selected continuation answer. Keep /oh-resume.
- [x] Preserve the ordinary workflow beneath standalone review and prevent live child
  duplication. Repeated matching preparation/review must not create replacement runs.
- [x] Store new Design initiative identity in existing scope metadata. Recover older
  identity from saved invocation/artifacts where possible; ask only for real ambiguity.
- [x] Restore Propose preview/refinement/approval, Design draft/checks/review/approval,
  Deliver assessment/implementation/corrections/checkpoints/publication and unfinished
  Review phases. Never resume a completed reviewer.
- [x] Inspect and retain native terminal results before replacement; a new session or
  elapsed time is not proof of termination. Use existing bounded host-save recovery.
  Explain a concrete external action only when OH cannot settle native ownership.
- [x] Preserve human edits. Reuse passing checks/reviews only for unchanged subjects;
  changed contents follow existing exact-candidate verification/review requirements.
  Continuation never grants scope, more tasks/reviews, finding acceptance or publication.
- [x] Update runtime guidance, all workflow skills and host wrappers together; discovery
  precedes missing-argument prompts. Show meaningful transitions, not repeated status.

## Verification checklist

- [x] Re-entry keeps run/scope, edits, settings, findings, attempts and allowances.
- [x] New-parent continuation works with real-shaped Claude and Codex human events.
- [x] Empty entry asks once without execution; ambiguous/different subjects do not hijack.
- [x] Propose preview, Design draft, quick-fix implementation and Deliver checkpoint
  resume at their correct phases. Review does not hide the underlying workflow.
- [x] Terminal child settles once; live/uncertain child is never duplicated; delayed
  evidence recovers without retyping. Completed reviewers remain terminal.
- [x] Stale candidates cannot borrow checks/reviews; unchanged work avoids repeated work.
- [x] Completed/publication-pending work does not repeat implementation or duplicate PRs.
- [x] Older missing-identity runs remain discoverable when evidence establishes identity.
- [x] CLI/MCP parity, read-only discovery and scope/authority boundaries are covered.
- [x] Run affected tests and syntax/Windows checks; inspect durations and avoid duplicate
  full-run fixtures. Extend existing causal coverage before adding new suites.

## Session-independent continuation follow-up

Saved work belongs to the person across native conversations. An explicit matching
continuation may select a new coordinator while the earlier conversation stays open;
no saved Pause/Stop ceremony is required when no attempt or check is executing.
Discovery changes nothing. The new continuation preserves actual pending decisions,
exact scope/review evidence and remaining allowances. Superseded coordinator helpers
are fenced, and attempts retain their original host/parent even after a host transfer.
Legacy adoption and continuation are recorded together after native human validation.
Recoverable legacy needs_attention continues from existing task/grant facts; pending
approval and publication phases retain their decisions. A consumed command cannot
reselect work over a newer selection, while interrupted selection writes recover
with the same still-valid command. Requested task review remains pending even when
all original implementation tasks are complete.
The existing execution lock protects running checks while Pause/Stop remain available;
a bound author may finish its current candidate/check step after Pause.

This follows the golden reference's durable branch/task progress and preserves OH's
native host execution, without its Geoffrey-specific branch policies. No scheduler,
background runner, expiry lease or new natural-language decision parser is added.
Automated verification is recorded below; live Mac acceptance is still required.

## Delivery and acceptance

- [x] Preserve all eight reviewed fixes on codex/native-workflow-bugfixes.
- [ ] Implement and verify locally, then developer activates candidate. Do not activate
  OH dev or change host settings. Mac launcher must be built on the Mac.
- [ ] Developer exercises both hosts, including the actual interrupted Mac Design run;
  inspect its saved state before promising seamless recovery.
- [ ] After live validation, obtain fresh invariant review with configured profile and
  immutable admission. Earlier review does not approve this change or renew allowance.
  Evaluate findings against concrete failures; no speculative machinery or scope drift.
- [ ] Publish only with applicable validation/review and human publication authority;
  human merges. Never commit local receipts, tokens or raw host transcripts.

No cross-machine state synchronization, cross-checkout grant adoption, background
execution or historical-run browser is included. Execution stays host-owned and
sequential. Explicit matching continuation may lift Pause/Stop; discovery alone cannot.

Acceptance: every work entry discovers relevant saved work before preparation and
continues the correct phase with existing authority, requiring less supervision than
restarting through a simple skill.

## Local verification record

Implementation and automated checks are complete. Live host acceptance, independent
review and publication remain unchecked above. OH dev has not been activated.

- Session-independent continuation follow-up: all controls and native authority tests,
  plus the retained legacy-finding/allowance regression, passed: 18 tests in 424.945
  seconds on Windows. This covers running-work takeover on both hosts, original child
  provenance, live execution exclusion, cooperative Pause, durable Stop intent and
  pending publication/approval phases. The earlier five causal tests passed in
  107.195 seconds. The broader run overlapped the affected suite; its slowest case
  was existing discovery coverage at 62.927 seconds. Git Bash syntax/Windows-risk
  checks and `git diff --check` passed.
- Final parent review corrected recoverable execution-state normalization, pending
  task-review restoration and cross-run stale-command selection while retaining
  interrupted-write recovery. The six final targeted cases passed incrementally:
  the six-case run took 260.653 seconds, with four clean completions and two Windows
  fixture-cleanup errors after their assertions; those two passed cleanly in 75.614
  seconds using an isolated short temporary root outside the watched checkout.
- The follow-up official affected suite selected 16 modules: 14 passed outright;
  three cases in delivery/planning hit the existing 260-character Windows hard-link
  path limit. A separate temporary-file diagnostic reproduced that limit without OH.
  Those three passed with shorter process-local temporary paths. No production
  receipt behavior or test assertion was weakened. The final syntax/Windows-risk
  check and `git diff --check` passed. This is incremental validation, not a single
  final all-green affected invocation. Mac host acceptance remains outstanding.
- Previous resumption implementation: `bash integrations/test.sh affected origin/main`
  (Windows Git Bash) passed all 16 selected
  modules passed. Focused follow-up runs cover the final changes to failed-review
  recovery, terminal Design discovery and phase hints; there are 164 distinct cases
  across the selected modules. This was incremental verification, not one final
  all-cases invocation after every edit.
- `bash integrations/test.sh syntax origin/main` and `git diff --check`: passed.
- Final focused controls/private-Design run: 8 passed, 154.540 seconds. The final
  failed-review/ordinary-workflow handoff rerun: 2 passed, 66.152 seconds.
- The integrated completion/task-window/task-review scenario passed in 115.395 seconds.
  The smallest phase-hint scenario takes about 5 seconds including its Git fixture;
  no repeated full workflow suite was added for each metadata case.
- Failed standalone review recovery was checked at an exhausted one-round allowance:
  repeating the still-valid command keeps the original run and charge, another
  reviewer is refused, and only an actual human review grant adds another round.
- Original Unicode diagnostic messages were verified against the prior committed
  source after correcting Windows-default encoding in a local editing script.

Host smoke scenarios for the developer:

1. In the same Mac project/OH data environment, inspect the saved interrupted Design
   run, install a Mac-built candidate and repeat `/oh-design agent-pipeline`. Verify
   the same run/draft and remaining allowance, with no redundant resume question.
2. Invoke a work command without a subject. It shows saved work and asks once;
   no agent starts before the answer. Repeat with a genuinely different subject.
3. Resume a proposal at its latest preview and a quick fix after author interruption.
   Existing approvals and edits survive; no approval or budget is silently renewed.
4. Re-enter an unfinished task review and select between ordinary work and standalone
   feedback. Existing reports remain readable, live children are not duplicated and
   failed launches retain their original charge. Test on Claude and Codex.
5. Re-enter completed work: private Design shows its artifact; a completed batch
   restores its pending decision/publication rather than rerunning implementation.

A Windows snapshot can test Windows locally. Mac must build from the same candidate
source; Windows-generated launchers are not a portable Mac installation.
