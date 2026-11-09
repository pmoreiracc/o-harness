# Saved work and recovery

Before current recovery/readiness advice, read `workflows/entry.md` and reconcile
saved/local/origin facts. Preserve local work while gathering information. Delivery
recovery questions report their observed base freshness separately from the selected
discard/continuation effect; a cached base is not verified current origin.

If entry reports a merged batch, use its next-task guidance. A stale unpublished checkpoint does not require Resume when its completed batch is on the refreshed base and its saved branch has no additional work. Read the approved plan on that base and use the current invocation with scope prepare. Preserve the old journal as history.

## Idle history and selection

Discovery and selected reads use the same `status` and `execution` facts. Workflow
disposition, native interruption and unsettled execution are different facts. A pending
result is not proof that a child is still running; an idle workflow is not automatically
complete. Reconcile the saved scope, reports and findings against the current approved
documents and Git before saying work remains. A missing historical branch or nested
worktree alone does not establish unfinished edits in the current checkout.

For genuinely different work, normal new-scope approval or a verified Resume decision
selects the checkout once native attempts and owned commands/checks are settled. No Stop of an idle
record is required. New work, Resume and standalone-review repairs share that cleanup
protection. Historical grants, spent allowances and findings stay with their original
run; new selection does not resolve findings, fabricate completion or authorize loss
of manual edits. Preserve local work in the selected checkout or include it in an
explicit approved preview; never create or move to a parallel checkout to recover. Use
the single-folder `workspace` path in `workflows/entry.md` for new branch choices. A
verified Resume/Continue automatically saves current edits and restores the saved
branch and staged state. Reuse that same answer after a recoverable failure; do not
make the person switch branches, pop stashes or approve preservation separately.
Resolve real branch/content conflicts here. Reconcile the `retained_work`
references when reviewing included changes.
Worker lifecycle and owned-process evidence establish settlement before selection.
Missing ordinary-tool callbacks do not block a settled worker; old tool rows remain
historical observations, not outstanding cleanup obligations.
An older approval cannot reclaim a newer selection; resuming that history needs its
current native continuation decision.
If retained idle work has reviewed commits on the same branch, the current exact-range
publication choice can include them without stopping its pending tasks. Their original
commit/review evidence, unresolved correction checks and native cleanup still apply.
An exact current choice covering the whole reviewed range governs that handoff; earlier
PR choices remain historical, including when Resume returns to an earlier run.
Before admitting committed work, use an execution branch. An unapproved preview on
the base reports `execution_branch_required`; default preparation can safely select
a branch, while `--keep-checkout` also preserves trunk. Reprepare after a deliberate
branch choice. A lossless branch change preserves standalone feedback eligibility
when HEAD and working contents remain exact; changed contents still need current
feedback. The repair scope binds its new branch and needs its own approval and review.

## Preserve a request across its prerequisite

Avoid a prerequisite question when the only issue is an idle status label. When a real
recovery/continuation/disposition decision is necessary before the requested work,
prepare it with `decision-request ... --request <original-native-locator.json>`
(Codex `decision_request` with `request`). Its question names both the existing effect
and the initiating request. Bind the actual answer normally. Then retry `scope prepare`
with the original request as `human` and `--after <that-decision-id>` (Codex `after`).
For an already accepted quick-fix preview blocked on cleanup, retry `scope approve`
with that original approval locator and the same `after` identity instead.

Only that accepted, recorded prerequisite permits this carry-over, in the original
conversation. Another prerequisite can retain the same request with `request` plus
the prior `after` identity. The latest actual answer is reverified; later cancellation,
changed instructions or another selection supersedes it. This grants only the original
request/preview, not more tasks, reviews, publication or disposal of unseen changes.
Changed preview contents still need their existing approval. Preserve the prepared
decision, original locator and accepted answer through retries; never relabel an answer
such as Stop as a Deliver command or make the person invoke Deliver again.

## A native command has no reservation

Preserve the failed attempt and diagnose the callback before retrying it. In Codex,
inspect the current hook definitions through the native CLI: open Terminal in the
project, run `codex`, then enter `/hooks`. A plugin can be enabled while its changed
control hooks are skipped because their saved trust belongs to an older definition.
If that is the observed cause, show the exact changed hooks for human review and
trust; never write trust hashes or infer approval from a plugin's enabled state.
Use the same approved scope and remaining allowance after repairing the prerequisite.
A missing reservation alone does not prove a trust problem: when hooks are trusted,
inspect callback errors, actor identity and the exact formatted command instead.

## Delivery entry and recovery

This entry decision is for selecting saved work in a new invocation or ownership
transfer. An already-authorized coordinator handling its own pending attempt first
retains the original native result and continues the same phase. Do not turn a
normal handback, cleanup continuation or delayed result into another Continue gate.

For an unfinished delivery, use `decision-request recover --run ID` (Codex
`decision_request` with kind `recover`). It inspects Git and prepares one native
question. Explain the effects in plain language, including the affected paths or inspection link before a discard. Then ask its short question with its
short buttons: **Continue**, **Start fresh**, **Stop and take over**. Present only
the returned options with Claude `AskUserQuestion` or Codex Default mode
`functions.request_user_input_async`, following the shared waiting and fallback rules.
If a required input is missing, explain the reason returned with the question. If only
Stop is available, ask only in ordinary chat and bind the explicit answer.

Bind the chosen action from the returned `actions` map with `decision` and that
same human locator, including its decision ID. Continue uses `resume`, Start fresh
uses `restart`, and Stop and take over uses `stop`. The helper retains available
results, revokes old execution, checks tracked operation cleanup and binds the new
owner. A deleted chat does not require recreating its transcript: missing results
are abandoned, never counted as successful. Preserve the answer through bounded
cleanup retries; do not ask again or make the person manage worker IDs.

Continue preserves approved supporting repairs, existing changes and usable evidence, including checkpoint commits
and writes that finish during cleanup. Keep the same Resume answer for that work;
changed files require current checks and review, not another continuation approval.
Missing current review proof calls for fresh review within the existing allowance,
not manual repair of OH records. Missing optional historical archives are labelled
unavailable and do not prevent a fresh review of the current candidate. The next review includes unreviewed branch commits.
When the old branch is
already merged and has no extra changes, it starts from the refreshed base on the
delivery branch. Start fresh discards precisely the changes and branch work shown
in the disclosure, starts from its displayed base, and authorizes the displayed
bounded task batch. No backup is made; ignored files and other branches are not
discarded. Repair approvals for restarted tasks are discarded with that work; their
history, existing review usage and findings remain. Stop and take over revokes
OH execution and leaves files untouched. For Start fresh, if files changed after the question,
inspect those changes before presenting the updated effect; the old answer cannot
authorize discarding unseen work.

After Continue or Start fresh, read the returned phase and finish its remaining
assessment, implementation, checks, independent review and completion. Do not
reprepare the same scope or reset allowances. Missing credentials, required project
checks, scope changes and operations whose cleanup is unverified still need their
specific remedy; recovery does not bypass these prerequisites.

An author result marked `reported` means the native agent returned its report;
it does not establish successful implementation. Older `implemented` labels also
need candidate, check and review evidence. Historical reports describe their own
attempts. After recovery or a runtime update, recheck a reported execution failure
through the newly admitted worker before claiming it still blocks the current run.

For new design delivery, `scope prepare --doc` refreshes the base, checks actual
Git ancestry, selects approved pending work and creates its delivery branch. It
preserves unmerged work instead of replacing it. Do not prepare new work on a
merged branch merely because it was already open. Dirty unrelated work requires
an explicit scope/ownership decision; never discard it as routine entry cleanup.

## Planning, review and previously presented Resume decisions

Read when saved work matches the request, an attempt needs recovery, or Pause/Stop is requested.
Read `workflows/decisions.md` before the Resume question. Prepare `decision-request resume --run ID`
first, present its actual question, and preserve the answer while settling old native work.

Show the selected subject, branch, latest result, next step and remaining allowance.
Prepare the Resume decision for that run before presenting its native question, then
call Claude `AskUserQuestion` or Codex Default mode `functions.request_user_input_async`
with the returned question and both choices. Bind Stop and take over with
`decision stop` for the same run and decision ID. It settles the run's old native
work and preserves its files. Wait for the actual answer before continuation,
legacy adoption or retaining an old result. A matching invocation is not that
answer. If old operations or native saves are still settling, retry the same
Resume or Stop answer after a short wait.

With no subject, show relevant unfinished work first. If several runs plausibly match,
use Claude `AskUserQuestion` or Codex Default mode `functions.request_user_input_async`
to identify the intended run, then prepare its Resume decision. A clearly different request selects
no unrelated work. Completed work presents its result or remaining publication step.

Read selected facts with `resume --run ID` (Codex `resume` with `run`). After the Resume
answer, call Resume with that same answer. For recorded native interruptions it
settles revoked attempts after owned command and check cleanup. If cleanup or native
saves are pending, wait briefly and retry the same answer; never ask again.
For other pending native attempts, retain any already-terminal result through
its original child locator before binding continuation; do not launch a replacement.
`binding_status: unbound` means only that OH has no accepted child binding; it never
means the attempt was not launched. `execution_status: not_checked` means status has
not inspected live host records. Use the pending attempt's `parent` and `request`
references to find its original launch and result, including after a rejected binding.
Do not pass the current Resume answer as a child locator, invent an unlaunched outcome,
or describe the run as blocked before checking those records. A bound child may also
have finished without its result being retained; inspect its latest native outcome.
If the host is still saving it, recover and retry using the same answer. Once prior
native work is quiescent and settled, bind continuation with `resume --run ID --human <locator.json>`
(Codex `resume` with `run` and `human`). Use the actual answer to the subject-and-branch
Resume question, including when entering through `oh-resume`. A workflow invocation
alone cannot authorize continuation. If native questions are unavailable, ask the same
question in chat and bind its direct human reply.
These helpers preserve the original scope, settings, findings, approvals and remaining
allowances. Saved work belongs to the person across sessions: an old conversation can
stay open, and its saved status need not say paused or stopped when no attempt or check
is executing. Do not ask for Stop or Pause before continuation. The accepted continuation
selects the current coordinator; a superseded coordinator must launch no further OH
operations on this work. Attempts retain their actual original host and native parent.
Do not reprepare free-text scope merely to transfer a session or host.

Resume the actual phase: retain terminal child evidence, continue unfinished authoring,
use valid completed author/check/review evidence, restore the latest proposal preview or
human decision, or finish completion/publication. Read the referenced report and scope;
phase labels are hints, not authority to bypass admission checks. A live child is awaited
or cancelled through its host before replacement, unless OH has verified its Stop
revocation and its owned commands and checks are settled. Revocation blocks its
future tools; it does not claim the host has stopped model generation. Another
session or elapsed time is never proof of cleanup. Completed reviewers are never resumed. A changed candidate needs
its existing verification/review path, while unchanged work does not need repeated analysis.
Claude Desktop Stop can leave child-local interruption evidence without a parent
completion notification. Pass the original child identity to retention; OH checks its
native stop metadata and transcript. A missing spawn-call ID can be recovered from the
unique native launch result. Do not require a stopped child to produce a final report,
or offer a new scope/reassessment to bypass an unresolved old attempt. Preserve the
Resume answer and existing allowance while diagnosing or repairing retention.
A spent allowance, proposal approval, concern acceptance, private approval or publication
still needs its existing human decision; continuation cannot supply it.

If an older review was retained as incomplete solely because its decision followed a
preamble, retry retention or completion on that same attempt before requesting another
reviewer. OH rechecks the original native result and unchanged admitted subject, then
records the recovered decision separately. Original reports, findings and charged rounds
remain saved. A changed candidate, ambiguous decisions or later attempt cannot use this
repair to bypass fresh review. Never resume a completed reviewer to reformat its result.

Completed work presents its result or outstanding publication/handoff rather than
restarting. An explicit new review after terminal feedback uses a fresh reviewer. For
older scopes without a subject identifier, inspect the original native request and bound
artifacts; ask for selection only if identity is genuinely ambiguous. Preserve useful
and human-authored edits. Use the retained `workspace` path for branch preservation;
an unmanaged stash, reset or regeneration must not bypass recovery checks.


## Interruption and recovery

The native Stop button is the intended control; do not ask the person to run
`oh-stop` or manage child IDs afterward. Codex's Interrupt hook records the stop;
OH also reads saved native interruption records, including Claude's root interruption
markers. Commands admitted through `owned-command` and configured checks use the
existing process-group/job cleanup. Tool guards refuse later calls from the revoked
worker, including after Resume in the same conversation.
A stopped turn does not retire its conversation. A later human turn can inspect
saved work, prepare the Resume question and bind its answer there. These recovery
tools grant no authoring authority before cleanup and the accepted ownership transfer.
If Stop is pressed during that recovery, it cancels the recovery turn too, including
when recovery is taking place in another conversation.

After the existing Resume answer, OH waits for tracked commands and in-flight tools
to finish before transferring ownership. A revoked attempt can be retained without
a final model report only when its native identity is bound and cleanup is verified.
That receipt is explicitly OH revocation, not evidence of native model termination.
Preserve any later native report under its original attempt; it cannot finish a new
attempt. Retrying retention saves that report without reviving the old worker.
Late reports remain labelled diagnostics; they cannot overwrite the original
completion or inherit dispositions attached to its findings. Retry partial evidence
writes with the same attempt and answer. Do not delete evidence files to clear a
conflict or ask the person to reconstruct a report.

An unresolved launch, failed cleanup, unavailable hook or lost command wrapper must
not be cleared by hand or relabelled as stopped. Keep the valid Resume answer and
inspect the original native records and retained operation. Retry after the host
has saved the evidence or the original operation has finished; if it cannot be
verified, report that exact blocker and a concrete recovery action. Never claim
that external services or detached processes were cancelled by a local process group.

Pause lets the current step finish and retains its result before waiting. A bound author
can finish its provisional candidate and checks after Pause; no later agent starts.
Pause and Stop are optional controls, never prerequisites for a future matching work
command. Discovery alone lifts neither. If continuation meets a running check, await
that native step and retry the same still-valid command within existing authority;
do not ask for another confirmation or make the person retype it. A later human
Pause/Stop or other decision must still be respected.

After interruption, inspect status and native work before resuming. Preserve attempts,
findings, settings, scope and spent allowances. Recover a routine helper failure and
retry the valid operation within existing authority. Use `workspace` for lossless branch
preservation under the initiating request. Never discard or commit another person's
edits by assumption. An unavoidable blocker names a concrete remedy;
elapsed time, retries and restarts never create approval.

