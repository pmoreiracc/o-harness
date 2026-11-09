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
Keep the returned decision ID in tool calls. Tell the person what has finished,
what needs deciding, and what each available action will do. Write the introduction
and question in your own words. Keep the returned action labels so a click or
typed answer identifies the effect. Arrange them in the order that best suits
the choice; put the relevant task, destination, scope or cost in each description.
For Codex menus with string options, include essential context in the question.
A person reading just the menu should understand the decision. Never show an
internal decision ID or fingerprint. Leave lists and supporting detail in chat or
the supplied details link. For destructive restart, show the branch, restart
base and discarded paths or their link before asking. For a reviewed proposal,
plan, scope or repair, show the actual material to be approved. Put the supplied Markdown preview or review link in a short chat message before opening the menu. Use its readable link title. A named design or proposal action identifies the reviewed subject without requiring a link in the menu. Native menu titles and descriptions are plain text: keep raw URLs, absolute paths and internal IDs out of them. If the work changes during discussion, prepare the revised choice before asking.
Use the actual preparation result in this conversation before asking.
When handling a pending offer from an older installed version, preserve its
original binding and never silently replace a valid answer.

**One option means ordinary chat only on both hosts.** Show the disclosure, ask
the returned question with its single action, end the turn and bind the actual
reply. Never add a synonym or a second button to satisfy a host's menu minimum.
For multiple options use the host control below when available.

Use the chosen label in `actions` with the original decision ID. Stop on a saved
run binds `decision stop` for that run and preserves local work and grants.
For a prepared scope, bind approval with `scope approve` (Codex `scope_approve`).
For a refusal use `decision stop` with the original scope decision ID and no run
argument; it records the refusal without entering that scope. Dismissal and legacy **Not now** leave the choice
unresolved. Supply the decision identity in the actual native human locator.
Reuse that identity and answer on technical retries.
If the person changes the requested scope/count, prepare that actual effect and ask only
for the changed boundary. Do not infer grants from a model's paraphrase of free text.

## Delivery recovery

Use `decision-request recover --run ID` for an unfinished delivery. Show its returned disclosure with the affected paths or their inspection link.
For multiple choices call Claude `AskUserQuestion` or Codex Default mode
`functions.request_user_input_async` with all returned actions, including the explicit discard action when available. Use the returned `actions` map with `decision`;
the existing `continue` action is a task-batch grant, not this recovery's Continue.
Recovery's Continue maps to `resume`, Start fresh to `restart`, and Stop to `stop`.
Use the exact selected label if answered in ordinary chat; a bare Yes does not
choose among these different effects. Missing old transcripts never supply a
successful result. The verified new decision authorizes retirement and recovery
only after old execution is revoked and tracked operations are settled.

## Completed-task checkpoint

After a completed batch, call `decision-request continue` when tasks remain, or
`decision-request publish` when all selected tasks are complete. At this boundary the helper
returns one question with an `actions` map and all available choices:

- **Start task …** authorizes only the listed next task IDs.
- **Open PR to …** publishes the reviewed completed work to the shown
  repository/base/HEAD through existing PR reconciliation.
- **Stop and take over** stops OH and preserves local work and commits; it does not push,
  publish or grant another task.

Introduce the completed work and describe the next authorized task and PR destination in the menu. Show all available actions. For
multiple options use Claude `AskUserQuestion` or Codex Default mode
`functions.request_user_input_async`. For one option use only chat. Both hosts use the
same decision validator. If publication is unavailable, report the helper's actual
prerequisite while retaining Continue/Stop as applicable. All-tasks-complete checkpoints
omit Continue; private planning completion needs no PR checkpoint. Selected work being
complete does not mean the whole design is complete. The disclosure explains
pending tasks from the saved starting design, their blockers/dependencies and other
tracks. Excluded tasks gain no authority. Resolve open design decisions through Design,
get the revised design approved, then re-enter Deliver against that revision, preserving
completed evidence and using normal publication to carry completed code forward.
For a plain-chat checkpoint, show the same actions with their consequences and wait.

After the native answer, use its label in the returned `actions` map to select the
existing `decision` kind (`continue`, `publish` or `stop`). Bind the same decision ID
and actual native answer once. Preserve a valid answer through retries. Do not
prepare a separate publish/stop question or ask
for another Yes: the selected checkpoint option already names that effect. A generic
Yes, cancellation, silence or several selected actions grants nothing at this menu.
If the person supplies an ambiguous free-text answer, clarify the intended action;
never interpret Continue as publication authority or Not now as Stop.

Checkpoint and recovery menus bind the actual human selection to its saved effect. Wording and option order may vary. For historical offers, use their original question
and receipt. A changed candidate, task window or publication destination needs a new question
before approval. Stop still applies to the same saved run and preserves its current
files. Preserve prior answers as history.
If a missing candidate prerequisite prevents preparing a menu, explain the prerequisite
and use `decision-request stop --run ID` to offer the bound Stop action in chat.

Call Claude `AskUserQuestion` or Codex Default mode `functions.request_user_input_async` as applicable for existing separate decisions.
Use the existing native control when it supplies the required approval, such as
Claude plan acceptance, and bind its actual result. Keep choices short and explain their effects in chat. Ask each decision when
it is actually needed. Defer finding-disposition questions until the current review
and approved repairs are retained, rather than asking while that work is in progress.

State the question and short choices in ordinary chat before posting its native menu,
including the actual artifact preview when approving contents. Say the person can also reply
in chat. These are two presentations of one decision, never two approvals. Submission
success establishes no menu visibility. If the person reports a missing menu, use the
readable chat question and their direct reply; do not just repost a popup or keep
sleeping on the assumption that it is visible. Preserve the same scope and allowance.

In Codex Default mode, `functions.request_user_input_async` posts a question and returns immediately. An
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
`stop`, `resume`, `approve-repair`, `approve-proposal` and `approve-private`. Use
`approve-repair` with a bounded `--repair` description only when additional authority
is needed for a supporting repair in the unfinished delivery task. Approval continues that task. Stop and take over stops the run and preserves its work. Follow the deliver skill for the complete path.
Scope preparation returns its
own `approval` question for native quick-fix acceptance. Claude plan-viewer acceptance
continues to bind the actual full plan directly, without an extra decision request.
Native Pause/Stop commands remain immediately usable. Older already-presented canonical
choices remain readable for recovery; do not build new wording around that compatibility.
Routine clarification, issue tracking and follow-up bookkeeping need no durable grant.
For concern-only reviews, call Claude `AskUserQuestion` or Codex Default mode
`functions.request_user_input_async` with the returned subject-specific **Accept concerns / Fix concerns** choices. Fix concerns continues the existing scoped repair, verification and fresh-review
path within the remaining allowance; it does not accept the findings or renew that allowance.
Do not submit that choice as `accept-concerns`. A dismissal or a legacy Not now answer
alone does not request repairs; follow the person's actual choice without inventing one.
A dismissed or rejected native plan remains unapproved. End the handoff on an explicit Stop in plan feedback; the native plan rejection already records that no plan was accepted. Do not invent a menu receipt for it.
An instruction to create an issue and allow another review needs only the review allowance
recorded as a grant; recording the authorized issue URL does not consume the human answer
or require a second confirmation. The person controls publication, scope and allowances.

Claude quick fixes use the native plan viewer's single Accept. Copy the returned scope
preview unchanged into the plan file designated by `EnterPlanMode`; do not rewrite its
heading, scope identity, instructions or limits, or append workflow commentary. Explain
execution in chat.
Then call `ExitPlanMode` without an
extra `AskUserQuestion`. Bind that actual acceptance with `scope approve` using the same
conversation locator; OH resolves the saved plan acceptance. If supplying `tool_use_id`,
use the `ExitPlanMode` call ID, not a human turn or result UUID. This display
copy is not a consumer design. If the native host denies the binding command after
acceptance, follow the command-specific permission recovery in `workflows/recovery.md`;
do not treat it as an OH rejection or request the same scope acceptance again.
An edited preview needs refreshed scope and approval;
rejection or interruption grants nothing. If native plan tools are unavailable, show
its returned disclosure, short approval question and options in chat, then bind the direct reply
using that same decision ID.

When Codex is in native Plan mode, present the complete unchanged scope preview in
its native proposed plan. The person can choose **Yes, implement this plan** in the
same conversation. Bind its actual reply with `scope approve`; OH checks the saved
Plan item and the human request to implement it. Use the same conversation rather
than the host option that clears context, since approval needs the original preview.
In Codex Default mode, use `functions.request_user_input_async` for the prepared scope
question or use the shared direct-reply path. Never ask twice for one approval.

For documents, show the actual complete artifact or preview before its bound question.
Use readable artifact names and explain their relevant scope; internal result.json paths
are not part of the person's approval vocabulary.
Native file display is optional; a failed display falls back to readable chat and a direct
reply. Do not ask someone to create a project or restart their session just to read it.
Repository design approval is human merge; private approval is bound to reviewed contents.

