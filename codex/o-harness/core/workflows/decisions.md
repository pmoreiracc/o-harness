# Native decisions

Read before presenting a consequential question. The order is **prepare effect → show
context and question → wait for the answer → bind that same answer**. Never prepare a
different effect after the person has answered and ask them to repeat it.

Before a consequential question, call `decision-request` (`decision_request`) for its
kind and concerned attempt. At an exhausted review window, omit `--rounds` (Codex:
omit `rounds`) to renew the run's configured window. For a three-round window, propose
three additional rounds. Supply `--rounds N` only when the person explicitly asks for
that different count, never because the agent predicts that one more will suffice.
When combining this with a routine action such as creating an issue, `--also TEXT`
includes that instruction in the same presented choice. The runtime grants only the
bound consequential effect; the host carries out the accompanying authorized action.
It binds the current subject and effect without granting anything. Present its returned
question and positive choice through the native host, unchanged except for the
completed-task checkpoint presentation described below; keep the returned
refine/cancel alternatives where relevant, or offer other non-granting alternatives; explanations and full previews
belong in the surrounding conversation. Include its `decision` identity in the actual
human locator when calling `decision` (or `resume`); OH locates the native question that
showed it, so the conversation locator is enough. A direct Yes about this same shown
question also works when a menu is unavailable. Preserve the prepared identity and actual
answer across recoverable failures; do not regenerate the question after it was answered.
If the person changes the requested scope/count, prepare that actual effect and ask only
for the changed boundary. Do not infer grants from a model's paraphrase of free text.

## Delivery recovery

Use `decision-request recover --run ID` for an unfinished delivery. Show its Git
context and discard effect, then its native single-select question with Continue,
Start fresh and Stop and take over. Use the returned `actions` map with `decision`;
the existing `continue` action is a task-batch grant, not this recovery's Continue.
Recovery's Continue maps to `resume`, Start fresh to `restart`, and Stop to `stop`.
Use the exact selected label if answered in ordinary chat; a bare Yes does not
choose among these different effects. Missing old transcripts never supply a
successful result. The verified new decision authorizes retirement and recovery
only after old execution is revoked and tracked operations are settled.

## Completed-task checkpoint

After a completed batch, call `decision-request continue` when tasks remain, or
`decision-request publish` when all tasks are complete. At this boundary the helper
returns one question with an `actions` map and all available choices:

- **Continue with the next task batch** authorizes only the listed next task IDs.
- **Open PR with completed tasks** publishes the reviewed completed work to the shown
  repository/base/HEAD through existing PR reconciliation.
- **Stop and take over** stops OH and preserves local work and commits; it does not push,
  publish or grant another task.

Show the completed work, next authorized task IDs, branch and publication destination
in the surrounding conversation. Present every returned option unchanged in one native
single-select question. The question's introductory prose may be concise: this checkpoint
binds the complete native menu and selected action to the prepared saved-work boundary,
not the wording of that introduction. This follows the golden reference's Claude task
checkpoint without its post-answer grant hook. Both hosts use the same existing OH
decision validator; no new menu or presentation guard is involved. Do not reduce this checkpoint to Continue/Not now or put PR
only in explanatory prose. If publication is unavailable, report the helper's actual
prerequisite while retaining Continue/Stop as applicable. All-tasks-complete checkpoints
omit Continue; private planning completion needs no PR checkpoint.

After the native answer, use its label in the returned `actions` map to select the
existing `decision` kind (`continue`, `publish` or `stop`). Bind the same decision ID
and actual native answer once. If the introduction was reworded, preserve that answer
and retry with its prepared decision identity; do not ask the person again. Do not
prepare a separate publish/stop question or ask
for another Yes: the selected checkpoint option already names that effect. A generic
Yes, cancellation, silence or several selected actions grants nothing at this menu.
If the person supplies an ambiguous free-text answer, clarify the intended action;
never interpret Continue as publication authority or Not now as Stop.

Only newly prepared completed-task checkpoints use complete-menu binding. Earlier
prepared records, scope approval, review renewal and other consequential questions
keep their original exact presentation checks. Ordinary-chat answers still require
the complete prepared context, because they carry no native menu evidence.
A changed candidate, task window or publication destination needs
a new accurately bound question; preserve the prior answer as history.

Use Claude `AskUserQuestion` or Codex's available native question tool directly for real
decisions. Keep choices short and explain their effects in chat. Ask each decision when
it is actually needed. Defer finding-disposition questions until the current review
and approved repairs are retained, rather than asking while that work is in progress.

State the question and short choices in ordinary chat before posting its native menu,
including the actual artifact preview when approving contents. Say the person can also reply
in chat. These are two presentations of one decision, never two approvals. Submission
success establishes no menu visibility. If the person reports a missing menu, use the
readable chat question and their direct reply; do not just repost a popup or keep
sleeping on the assumption that it is visible. Preserve the same scope and allowance.

In Codex, `request_user_input_async` posts a question and returns immediately. An
`accepted: true` result only acknowledges submission; it is not the person's answer.
Use it only when a native interruptible wait tool is also available. After posting,
keep the turn open and wait quietly with `clock.sleep` (at most 60 seconds per call),
or the host's equivalent interruptible wait, until the actual human reply arrives.
Do not send a final response while the question is pending: completing the turn can
dismiss its menu before the person clicks. Do not post a second question, start the
selected work or infer a choice from silence, elapsed time or tool success. This
applies to Resume and every other native decision, including scope, findings,
allowances, document approval and publication.

If the host has a blocking native question tool, its actual returned human answer
can be used directly. If an asynchronous question cannot be kept open, use the
blocking tool when available; otherwise ask once in plain chat and end with that
question, then wait for the person's next message. Do not post an asynchronous menu
and immediately end the turn with instructions to click it. Claude AskUserQuestion
waits for its native answer; never supply an `answers` field on the person's behalf.

If a menu disappears or is closed without an answer, preserve the unresolved decision
and show that same question again through the available native surface, keeping an
asynchronous question open as above. Fall back to plain chat when necessary. Never
make the person restart the work or repeat their command to restore a missing menu.
Preserve an existing valid answer; do not require exact wording, poll an OH menu or
synthesize an approval in an agent message.

Consequential kinds are `continue`, `grant-review`, `accept-concerns`, `publish`, `pause`,
`stop`, `resume`, `approve-proposal` and `approve-private`. Scope preparation returns its
own `approval` question for native quick-fix acceptance. Claude plan-viewer acceptance
continues to bind the actual full plan directly, without an extra decision request.
Native Pause/Stop commands remain immediately usable. Older already-presented canonical
choices remain readable for recovery; do not build new wording around that compatibility.
Routine clarification, issue tracking and follow-up bookkeeping need no durable grant.
For concern-only reviews, present the returned **Accept these concerns / Fix concerns**
choices. Fix concerns continues the existing scoped repair, verification and fresh-review
path within the remaining allowance; it does not accept the findings or renew that allowance.
Do not submit that choice as `accept-concerns`. A dismissal or a legacy Not now answer
alone does not request repairs; follow the person's actual choice without inventing one.
An instruction to create an issue and allow another review needs only the review allowance
recorded as a grant; recording the authorized issue URL does not consume the human answer
or require a second confirmation. The person controls publication, scope and allowances.

Claude quick fixes use the native plan viewer's single Accept. Put the complete bounded
scope preview in the plan file designated by `EnterPlanMode`, then call `ExitPlanMode` without an
extra `AskUserQuestion`. Bind that actual acceptance with `scope approve`. This display
copy is not a consumer design. An edited preview needs refreshed scope and approval;
rejection or interruption grants nothing. If native plan tools are unavailable, show
the preview and obtain a direct human approval in chat. Codex uses a native question
or direct human reply about the same complete scope. Never ask twice for one approval.

For documents, show the actual complete artifact or preview before its bound question.
Use readable artifact names and explain their relevant scope; internal result.json paths
are not part of the person's approval vocabulary.
Native file display is optional; a failed display falls back to readable chat and a direct
reply. Do not ask someone to create a project or restart their session just to read it.
Repository design approval is human merge; private approval is bound to reviewed contents.

