# Saved work and recovery

Read when saved work matches the request, an attempt needs recovery, or Pause/Stop is requested.
Read `workflows/decisions.md` before the Resume question. Prepare `decision-request resume --run ID`
first, present its actual question, and preserve the answer while settling old native work.

Show the selected subject, branch, latest result, next step and remaining allowance.
Prepare the Resume decision for that run before presenting its native question, then
use the returned question and positive option unchanged. Offer the non-granting option
as well. Wait for the actual answer before continuation, legacy adoption or retaining
an old result. A matching invocation is not that answer. Preserve an already-valid
Resume answer through recovery; never ask again merely because a helper failed.

With no subject, show relevant unfinished work first. If several runs plausibly match,
ask which one, then prepare Resume for that run. A clearly different request selects
no unrelated work. Completed work presents its result or remaining publication step.

Read selected facts with `resume --run ID` (Codex `resume` with `run`). After the Resume
answer, inspect pending native attempts. Retain any already-terminal result through
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
or cancelled through its host before replacement; another session or elapsed time is not
proof of termination. Completed reviewers are never resumed. A changed candidate needs
its existing verification/review path, while unchanged work does not need repeated analysis.
A spent allowance, proposal approval, concern acceptance, private approval or publication
still needs its existing human decision; continuation cannot supply it.

Completed work presents its result or outstanding publication/handoff rather than
restarting. An explicit new review after terminal feedback uses a fresh reviewer. For
older scopes without a subject identifier, inspect the original native request and bound
artifacts; ask for selection only if identity is genuinely ambiguous. Preserve useful
and human-authored edits; no reset, stash or regeneration is a recovery shortcut.


## Interruption and recovery

Stop means cancel owned native work before any later phase. Use native cancellation
for known active children/commands and confirm their outcome; interrupting the parent
alone is not proof. Do not claim cancellation until confirmed or start another worker
while old work may run. If the host cannot confirm cancellation, explain the specific
remaining native task and next action. Saved stopped status records the instruction to
launch nothing further; it alone does not prove native cancellation. While a known
check is still executing, report Stop requested; cancellation pending, and use its
native host cancellation. Retaining its eventual check evidence starts no later phase.
Do not build a replacement process supervisor.
Pause lets the current step finish and retains its result before waiting. A bound author
can finish its provisional candidate and checks after Pause; no later agent starts.
Pause and Stop are optional controls, never prerequisites for a future matching work
command. Discovery alone lifts neither. If continuation meets a running check, await
that native step and retry the same still-valid command within existing authority;
do not ask for another confirmation or make the person retype it. A later human
Pause/Stop or other decision must still be respected.

After interruption, inspect status and native work before resuming. Preserve attempts,
findings, settings, scope and spent allowances. Recover a routine helper failure and
retry the valid operation within existing authority. Never discard, stash or commit
another person's edits by assumption. An unavoidable blocker names a concrete remedy;
elapsed time, retries and restarts never create approval.

