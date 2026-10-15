# Independent review and the quick-fix handoff

Approved 2026-10-13. Implementation stays on `codex/harness-refactor`.

## Decisions

- Independent review accepts manual work, revisions/ranges, code areas and documents; it does not require a design, implementer report or test configuration.
- Fresh reviewer, configured review profile, immutable admission and complete receipts use the shared native execution path.
- New admissions identify `standalone` versus `workflow`. A source receipt can inform a repair, never count as its workflow round or authorize completion.
- Feedback ends the operation. Later standalone reviews have no automatic prior-finding history.
- Findings feed the existing quick-fix preview: Approve fixes / Refine / Keep as feedback. Arbitrary choices remain text in the approved tasks.
- Existing-work approval includes the person's original reviewed edits in the final commit (explicitly confirmed). Bind branch, HEAD and contents; never silently absorb unrelated edits, stash, reset or refresh this work from main.
- Re-review of completed unpublished Deliver work retains the task's scope, earlier completions and allowances. Clean produces no commit; blockers require reviewed correction commits before publication. Published work receives standalone feedback.
- No redesign classifier, new consumer configuration, historical rewrite, second repair engine or continuing feedback tracker.

## Ordered tasks and completion evidence

- [x] 1. Share native review execution and expose independent Review, preserving active delivery state, exact subjects and Stop ownership.
- [x] 2. Bind receipt purpose and identity; exclude standalone evidence from workflow rounds, escalation and completion.
- [x] 3. Connect findings to existing quick-fix preparation, refinement and human approval.
- [x] 4. Safely admit existing manual work and retain original edits through normal Deliver completion.
- [x] 5. Add explicit re-review and correction completion for unpublished Deliver tasks without changing consumer task marks or erasing evidence.
- [x] 6. Extend causal fixtures; run affected and syntax/platform checks; update verified documentation.
- [ ] 7. Developer snapshot trial on both hosts, then fresh independent review and publication.

Tasks 3–5 depend on 1–2. Task 6 is applied throughout. Task 7 remains pending the developer's actual host trial.

## Coverage map

| Fixture | Protection / disposition |
| --- | --- |
| Existing authority, controls and plugin fixtures | Retained: native human proof, session transfer, cancellation and launcher behavior. |
| Existing checkpoint/native-menu fixtures | Retained original publication choices; free-text review requests grant no task/publication; stale replies cannot authorize inspection; replay does not consume a second review. |
| Existing failed-review and escalation fixtures | Extended: inspection failures retain the same window without rerunning implementation; escalation needs an intervening author repair. |
| Existing PR/scope fixtures | Extended: original implementation summary, all later reviews shown once, correction history does not inflate completed-task counts; scope decisions preserve completed documents. |
| New standalone workflow case | Current/historical subjects, fresh independent receipts, untouched saved delivery, Stop and cross-host continuation. |
| New completed-task workflow case | Clean re-review creates no commit; blockers enter normal repairs; original completion/allowances retained. |
| New manual-work gate case | Actual conversational entry; staged, unstaged and committed originals; stale-preview refusal; refine/approve; interrupted branch activation; portable publication proof. |
| New design correction case | Actual repository design and immutable receipts; corrections preserve approved scope and task marks. |
| Existing installation, MCP and platform fixtures | Updated discovery/menu expectations, retained packaging and platform checks. |

Only four new behavioral cases; existing fixtures cover the remaining paths. No full-suite run or speculative test deletion.

Acceptance: no-doc review; feedback termination and fresh follow-up; invalid/incomplete reports; source receipts cannot affect workflow counts or authorize completion; historical fixes against current code; staged/unstaged/unrelated changes; stale approval; clean re-review without commit; blocking correction with unchanged task marks; Stop and cross-host/session continuation; ordinary Deliver/quick-fix/publication regressions.

## Validation record

The golden reference at `harness-before-separation` supports independent inspection and
explicit approved repairs. OH keeps that separation while reusing its shared native runner,
existing task preview, checks, report validation, Stop and publication paths. It does not copy
Geoffrey's project policies or add an ongoing standalone finding tracker.

Implementation decisions:

- A foreground review pointer preserves the canonical delivery journal. Standalone admissions,
  results and readable receipts identify their purpose and exact subject; legacy receipts default
  to workflow. Exported historical source is content-bound and never checked out over manual work.
- Source receipts are references in a new repair packet, never inserted into its attempts. Existing
  edits and unreviewed commits are explicitly included in one coherent repair task, because native
  completion commits the whole reviewed tree. The existing reviewed-ancestry proof covers those
  commits. An already-published source branch receives a new repair branch.
- Additional task reviews retain their source event and consume the saved review window. An
  explicit request adds one review only when that window is already spent. A repeated request
  cannot add another attempt. Corrections append their own commit intent and completion while
  preserving original task marks and evidence. Request, optional grant and running status use
  the existing atomic transition record, so an interrupted response cannot lose that decision.
- Natural-language input is a passive locator; ordinary conversation never starts or stops OH.
  The Review tool revalidates native human evidence. Native menu Other can preserve a requested
  inspection without becoming a task or publication grant. Existing refinement text keeps its
  existing meaning in task previews.

Automated evidence (local macOS, isolated repositories):

- The initial affected selection covered 16 modules. Twelve passed immediately. The remaining
  failures exposed stale menu/tool expectations, required skill icons and an unregistered fixture
  path; these were fixed, retaining the original coverage.
- Installation and focused host/gate checks: 13 passed in 35.14s. Authority, plugin, gate, MCP,
  publication and correction checks: 73 passed in 189.79s.
- Manual existing-work handoff through publication, correction history and native PR evidence:
  3 passed in 29.41s. Failed-extra-review retention and correction: 2 passed in 21.12s.
- Final gate module plus native Stop/resume entry: 39 passed in 111.79s. Interrupted review
  decisions, allowance retention and menu replay: 3 passed in 32.88s. The stop fixture uses the
  host entry handler and proves it cannot resume the underlying unrelated delivery.
- Claude and Codex plugin packaging passed, including the new skill and its assets; skill
  validation, syntax and Windows-risk checks pass. Native Linux/Windows execution remains for CI; local platform fixtures
  do not claim validation on those operating systems.

Real reviewer calibration used the configured subscription profiles and immutable native
admissions on two isolated no-design fixtures per host. Both reviewers caught the planted
contract violation and accepted the compliant control, with no report-format issues or
checkout changes. These are four standalone inspections, not a review of OH's implementation,
Desktop UI testing, repeated task-delivery trials or a claim of token savings. Cached input is
a subset of input, never an additional charge in these totals.

| Host / case | Seconds | Input | Output | Cached input subset |
| --- | ---: | ---: | ---: | ---: |
| Claude / defective | 50.34 | 212692 | 4857 | 176776 |
| Claude / clean | 39.05 | 178141 | 3457 | 148875 |
| Codex / defective | 101.17 | 229949 | 2590 | 200576 |
| Codex / clean | 93.99 | 240716 | 1859 | 217344 |

Profiles: Claude opus/high; Codex gpt-6.1-sol/high. The reviewed runtime snapshot was
`89074c3e3f774f79461ab0833807c577b393c690+worktree.49dba5d17b0a8279`; later changes concern
entry handling, repair/publication evidence and presentation. Logs and original receipts stay
outside Git under `/tmp/oh-independent-review-*`.

## Developer host trial before independent OH review

Scope correction after the first host trial: the added Review again menu shortcut was not
approved. Restore the original checkpoint/publication menus. Explicit review requests and
`oh-review task <id>` retain the approved capability. Reuse the existing menu and replay
fixtures to verify this correction; no additional workflow or test case is needed.
Validation: the three existing Claude/Codex menu and fallback cases passed in 20.83s,
including explicit re-review and replay protection. Syntax and Windows-risk checks passed.

Run `oh-dev on`, then start fresh Claude and Codex sessions in disposable consumer checkouts.

1. Ask for a review of manual changes without a design. Inspect the Standalone label. Choose
   Keep as feedback; ask again and confirm the second review is independent.
2. Review a defect, refine its fix list, then approve. Confirm the preview includes original
   changes and the usual checks/review/commit flow runs; publication remains your decision.
3. At an unpublished Deliver boundary, request another invariant review (including menu Other).
   A clean outcome returns to the gate without a commit; a blocker is repaired and independently
   reviewed without changing old completion marks or resetting the review allowance.
4. Stop during inspection and resume from the other host. Confirm the retained interrupted
   result appears and no new inspection or unrelated delivery starts silently.

After these trials pass, request a fresh OH invariant review through a bound immutable
admission. Fix any blockers before preparing publication. Task 7 remains unchecked.

## Follow-up from the completed-task host trial

Approved scope: restore full-task correction coverage, reconcile contradictory instructions,
repair read-only progress observation and receipt/decision presentation. Family-wide repair
already exists; no new repair brief, model policy, menu choice or authority mechanism.

- [x] Preserve original comparison base through correction and resume; extend existing correction fixture.
- [x] Honor observation cursors and wait past unchanged idle baselines; extend observer fixture.
- [x] Derive finding closure from valid review and exact-tree scope resolution; preserve immutable reports.
- [x] Reconcile entry/review instructions; show current decision context and concise correction summaries.
- [x] Run affected checks, syntax and scope self-review; record evidence before developer host trial.

The golden reference retains complete task coverage and family closure across rounds. We retain
those rules; fixes address their inconsistent delivery, not a new quality workflow.


### Follow-up verification and scope review

Existing fixtures were extended; no new test cases or test modules were added. The correction
fixture now preserves an original, untouched task surface through repair and the allowance
boundary, checks the actual commit parent, and retains the complete original report while
shortening its visible correction summary. The receipt fixture checks unresolved, exact-tree
resolved, stale, incomplete and accepted-concern cases. The observer fixture covers unchanged
idle startup, cursor renewal, fast completion returning to the same status, focus throttling and
unchanged journals. Existing Claude/Codex gate fixtures retain menu binding and original choices.

- Initial targeted run: 65 of 66 passed in 166.06s. The extended receipt fixture had inconsistent
  synthetic finding positions; fixing that fixture preserved production validation.
- Final receipt, observer and gate cases passed (6.86s, 4.46s, 0.21s). The older scope fixture
  needed its saved-run read stubbed after a previous resume-path change; it passes in 0.04s.
- Final correction, portable PR evidence and both-host packaging: 3 passed in 22.09s.
  Across these runs, all 69 distinct selected cases passed. No full suite was run.
- Syntax, Windows-risk scan and diff whitespace checks passed. Actual Windows/Linux execution
  and native host interaction remain for CI and the developer trial.
- The generic skill validator rejects the pre-existing Claude `disable-model-invocation` key.
  That supported host field was retained; OH's two-host packaging check passed instead.

Self-review: the review comparison base changes, but the immutable reviewed tree and correction
commit parent do not. Receipt closure reuses existing publication evidence validation, cannot
accept stale human dispositions, and never rewrites reports. Observation remains read-only and
its expiry grants nothing. PR decision history comes from existing journals; unavailable history
is labelled. No family mechanism, menu choice, model policy, approval, consumer change or
production service was added. Earlier model misses remain a quality limitation, not proof that
this coverage fix guarantees defect detection.

Next developer trial (`oh-dev on`, fresh host session): request a completed-task review that
requires a small repair; confirm the following review still covers the whole original task.
During a long phase, confirm observation waits through startup and renews without repeating
unchanged updates. Check current findings in the decision question and repair/allowance choices
in the final PR preview. Fresh independent OH review remains after this trial, before publication.


## Verification sequencing and bounded quality follow-up

Approved after the task-11 Desktop trial. The scheduled monitor is paused. Work remains on
`codex/harness-refactor`; consumer repositories and active snapshots are unchanged.

- [x] Correct implementer/tool sequencing: focused checks during development, self-review and
  generated/reference edits before final verification, no simultaneous edits, then submit.
- [x] Compare a replacement family/self-review paragraph on the observed mutable-rule and
  mixed-deletion risks in disposable fixtures. Retain only supported guidance; do not add a
  report field, reviewer pass, model call, gate or generic mandatory test matrix.
- [x] Keep owning unchanged reference checks bounded to the affected operation, within the
  same self-review. Run causal existing tests, compare prompt size and record trial limits.
- [x] Challenge the final diff against scope and record the result before snapshot activation.

Evidence motivating this work: the task-11 run had four passing but stale verification runs
(7.5 minutes of configured checks), one repeated duplicate family and late documentation
findings. The golden reference also says verify then self-review, but invalidates its readiness
manifest after edits; this is a concrete reason to improve that ordering rather than copy it.
Its review-ready.sh retains exact-tree evidence; OH keeps its equivalent protection unchanged.
Evaluation cost is temporary: compare current/candidate guidance on each host's standard
profile with the same bounded fixture and checks; no extra evaluation agent enters production.


### Calibration result and retained change

Only final-verification sequencing, its tool feedback and bounded owning-reference guidance
are retained. The candidate family paragraph was reverted: both baseline and candidate solved
all six fixture outcomes (unchanged/changed/removed merchant rules, distinct source facts,
mixed deletion failures and owning route prose), and preserved the original commit. Existing
family/permission/replay requirements remain unchanged. This avoids shipping a rewrite without
an observed quality benefit.

The isolated four-call trial used the configured standard subscription profiles. Both variants
received the same approved fixture and checks. A synthetic read-only assessment held selection
constant, so no assessment tokens or reviewer calls were incurred. Existing native immutable
admissions, report submission and verification were used; no commits or publication occurred.

| Host / variant | Seconds | Input tokens | Output tokens | Cached subset of input | Verification calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| Codex / baseline | 159.36 | 185245 | 4910 | 161664 | 1 |
| Codex / candidate | 132.21 | 173149 | 4254 | 150912 | 1 |
| Claude / baseline | 24.70 | 64044 | 2258 | 46198 | 1 |
| Claude / candidate | 37.02 | 140068 | 3850 | 125217 | 2 |

No variant produced stale verification. Claude's candidate first ran the original failing
regression, then verified the repair; its second call was useful failure reproduction, not a
redundant passing run. Both hosts completed with an accepted report. One paired fixture per
host cannot establish production token savings or guarantee closure on a large task. It does
not measure total delivery cost including assessment, repair/review rounds or host interaction.
The table describes the tested candidate; its unproven family rewrite is not in the final diff.
Temporary fixtures, original evidence and the comparison script remain outside Git under
`/tmp/oh-sequencing-*`. No model, effort, tool, report field or agent was added to production.

Automated validation: the existing final-tree fixture now also rejects a passing command whose
checkout changes during execution, then accepts fresh unchanged evidence. That fixture and
both-host unfinished-work continuation passed in 15.24s. No new test case or module was added.
The generic golden-reference order was intentionally changed because the native final-tree
contract exposed four stale passing runs in the real trial; final evidence protection is retained.

Final validation: existing family-receipt, batch/phase-boundary and Stop-during-review cases
passed (3 tests, 63.38s); five targeted automated cases passed overall. Syntax, Windows-risk
and diff whitespace checks pass. No full-suite run or new test module was needed.

Final scope self-review: runtime changes are instruction strings only. Check selection,
execution, before/after fingerprints, report validation, authority, review allowances,
escalation, models, Stop/resume and publication paths are unchanged. Code/test claims still
require opening their sources; owning-reference guidance supplements rather than replaces
that requirement. The implementer paragraph is 523 words versus 514 before (+9); there are
no added mandatory calls or report sections. Actual per-task token impact remains to be
measured on a production-sized trial; neither prompt length nor this small calibration proves
savings. The installed development snapshot is unchanged. Fresh independent review and
publication remain subject to the established development workflow.
