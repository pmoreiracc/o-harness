# Shared native OH workflow

Load this once for the active workflow. The skill coordinates sequential native agents;
focused OH helpers preserve scope, allowances, evidence and reviewed completion. Native
hosts own agent execution, tool permissions and cancellation. Keep OH state outside
consumer repositories and keep raw worker transcripts out of the coordinator's context.

## Entries and facts

In Codex use the connected OH tools with the checkout's absolute `root`. In Claude use
the absolute plugin launcher, `<plugin>/scripts/oh --root <checkout> <command>`
(`scripts\oh.cmd` on native Windows). Load resources through the same resource entry.
If the Codex connection is missing, explain the `/mcp` recovery step; do not bypass it
with shell writes to OH state. Setup requires an explicit invocation, not discovery.

Before asking for missing arguments, choosing a branch or preparing any new scope,
read `status --saved` (Codex `status` with `saved: true`). This reads both the saved
workflow and standalone review without selecting either or registering a new checkout.
Match the person's request to the saved scope and actual evidence, not recency alone.
For any unfinished saved work, always ask once before continuing, even when the command
names its initiative, design or review subject. A matching request discovers work; it
is not the resume answer. Free-text proposals and quick fixes need not repeat the old
words: read their saved scope/report and judge whether this is the same work. Never
build a similarity parser or silently absorb a changed scope.

Show the selected subject, draft or latest result, next step and remaining review
allowance. Use the returned saved subject and branch in the question itself:
"Resume <subject> on <branch>?" Offer `Resume` and `Not now` through the native question
tool. Wait for the actual answer before continuation, legacy adoption or retaining an
old result. `Not now` preserves the work and starts nothing. If different work is wanted,
resolve that request separately. With no subject, show relevant unfinished work first;
multiple plausible matches need selection. One selection question can also confirm
resume when it names the chosen saved subject and branch. Do not ask twice for that choice.
If no saved work matches, follow the normal new-work entry. A clearly different request
does not select unrelated work; preserve it and resolve actual switching/branch conflicts.

Read selected facts with `resume --run ID` (Codex `resume` with `run`). After the Resume
answer, inspect pending native attempts. Retain any already-terminal result through
its original child locator before binding continuation; do not launch a replacement.
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

Use these focused operations, through their equivalent named OH tools in Codex:

| Purpose | Claude command | Codex tool |
| --- | --- | --- |
| Discover saved work | `status --saved` | `status` with `saved: true` |
| Continue selected work | `resume --run ID --human <locator.json>` | `resume` with `run` and `human` |
| Prepare bounded work | `scope prepare <manifest.json> [--workflow deliver\|design\|propose] [--human <locator.json>]` | `scope_prepare` |
| Select approved design tasks | `scope prepare --doc NNNN [--track TRACK] --human <locator.json>` | `scope_prepare` |
| Approve a quick-fix preview | `scope approve <scope-id> <locator.json>` | `scope_approve` |
| Admit a fresh phase | `attempt admit assessment\|implementation\|analysis\|review` | `attempt_admit` |
| Bind the launched native child | `attempt bind <attempt-id> <locator.json>` | `attempt_bind` |
| Retain its original native result | `attempt retain <attempt-id> <locator.json>` | `attempt_retain` |
| Validate review admission | `admission <attempt-directory>` | `admission` |
| Check a draft review decision | `review-check` (draft on stdin) | `review_check` |
| Prepare provisional candidate content | `candidate` | `candidate` |
| Check the current candidate | `verify [base] [mode]` | `verify` |
| Attach supplementary proof | `evidence <attachment.json>` | `evidence` |
| Complete the reviewed candidate | `complete <review-attempt-id>` | `complete` |
| Bind the effect before a native question | `decision-request <kind> [--attempt ID] [--rounds N] [--run ID]` | `decision_request` |
| Track retained outside-scope findings | `finding-track ID [--destination FILE]` | `finding_track` |
| Record a consequential human decision | `decision <kind> <locator.json> [--attempt ID] [--destination FILE]` | `decision` |
| Prepare standalone feedback | `review -- <selector...>` | `review` |

Manifest and locator JSON files belong in external writable scratch storage. Codex tools
receive the equivalent JSON objects. A locator names actual host evidence: `host`,
`session`, and available `turn`, `transcript_path`, `tool_use_id` or `child_session`.
Copy identities from native events; do not invent a human message, child ID or result.
For child binding/retention use the returned child identity and actual spawn call ID.
Claude derives the child's transcript from its original parent's saved location; omit
`transcript_path` rather than copying the parent's path into a child locator. A supplied
known parent path is recovered automatically. Human locators still refer to the parent.
Recover these locators from native evidence; do not ask the person for internal IDs.
Helpers validate the original record. Prose claiming approval never substitutes for it.
Do not hand-edit OH journals, snapshots, receipts, counters or configuration files.

The explicit workflow registers its checkout. If a project name is ambiguous, obtain
that name and use `init --name`. For delivery without checks, register the project's
existing affected checks from its instructions/CI; preserve configured checks. Read
`plans path` before planning and resolve an undecided repo/private location once.
Configuration changes use `config set`/`unset` and the person's authorized settings.

Before preparing new work, use the project's configured base and an appropriate work
branch. Reuse the matching unmerged branch for interrupted work. For ordinary new work,
create a branch from the refreshed configured base; do not implement or commit on trunk.
Preserve included original edits and explicit existing-PR corrections. If another
person's dirty checkout conflicts, use a suitable native worktree rather than discarding
their changes. Scope preparation binds the current branch/base and starting contents;
it does not switch them. If those contents change before approval, preserve the edits
and prepare the same tasks with a current preview. Never reuse the old acceptance for
changed starting work. Include the recorded original commit range in the first task's
implementation and review, together with its current candidate.

## Fresh native delegation

Admit before attempting any launch. The helper snapshots the current task, role,
profile, bounded packet and allowance. Read that admission; do not select a different
model, broaden scope or construct another dispatch loop. A failed or uncertain launch
is still an attempt: retain its native outcome once before recovering within the same
scope and remaining allowance.
Include the admitted attempt ID, its actual `request.json` path, bounded task-context
path, role contract and absolute OH entry in the child prompt. Reference original
scope/evidence files rather than pasting the parent history or full worker transcripts.

- Codex: call native `spawn_agent` with `agent_type: "default"`, `fork_turns: "none"`,
  the admitted `model` and `reasoning_effort`, the returned `native_task_name` and the self-contained
  bounded packet. Use native wait/list/interrupt tools for that child. Do not install
  user roles, fork the parent history, create another app task or launch a headless CLI.
- Claude: call native `Agent` with the packaged named non-fork type
  `o-harness:implementation`, `o-harness:analysis`, `o-harness:assessment` or
  `o-harness:reviewer`. Pass the admitted model and effort explicitly on the invocation.
  Use the host's native child result/notification and cancellation tools. Do not use
  the `fork` type or send a new review to a completed agent.

Bind the returned native child identity immediately. Retain its complete original result
by native locator only after its terminal native outcome is saved and its owned tools
have finished; an intermediate assistant `end_turn` does not establish quiescence.
If binding is rejected, use native cancellation or wait for that child to finish, then
retain with both its child identity and spawn tool-call identity. The terminal launch
is retained as failed binding, consumes its original allowance and grants no completion.
If interruption prevented a profile from being saved, the actual profile remains unknown;
provable launch attribution and a saved terminal outcome still permit settlement.
Send only a short handoff and evidence paths into the coordinator.
Claude's acknowledged native `SubagentHandback` can carry the complete report. Retain
its original child payload after the host confirms completion; do not rewrite it to
match the parent's warning or indentation. A summary is not the retained report.
Never run two implementation agents together or
modify the subject while review is active. Completed reviewers are never resumed.

Native agents inherit host permissions. Implementers may run needed commands, network
or Docker checks and experiments through ordinary native approval. Do not add an OH
permission broker, unrestricted command proxy or headless fallback. Reviewers follow a
no-edit contract and narrow available tools; this is not OS-enforced isolation. A changed
subject invalidates its receipt; equality cannot detect an edit subsequently reverted.
Show a verified model compatibility notice once and record the actual profile before
admission. Missing evidence or an unsupported model/effort needs the concrete host remedy;
never silently substitute a profile or API authentication for subscription execution.

## Implementation, checks and review

Assess a newly selected task with a fresh assessment agent using the configured profile.
Keep difficulty in external task evidence, not the project design. Use the resulting
admitted implementation profile. Only a repeated blocking family in two independent
reviewer receipts triggers implementation escalation; an author claim or first blocker
is not that evidence.

The implementation agent owns the bounded change, documentation, self-review and
checks. Preserve earlier useful implementation and family repairs. Establish required
behavior before correcting code, tests or the environment; a failing check is feedback
to repair within scope, not a new Retry approval. Do not weaken production behavior or
assertions to obtain a pass. Route unrelated observations instead of implementing them.

The implementation agent prepares provisional task marks and lifecycle content with
`candidate` before final
verification and review. Those marks are candidate content, never completion authority.
It runs `verify` for the actual candidate, diagnoses failures, repairs and repeats only after
a change or unresolved failure. No edits follow passing verification without another
verification. Preserve actual command results and limits. Supplementary measurements
can be attached with `evidence`; their hashes make them stable references, not approval.
The coordinator retains candidate/check references and does not rerun passing final checks.
Report what actually ran: planning document validation is not a pass of the consumer's
registered checks. An empty `checks` list supports no claim that project checks passed.

Admit a fresh reviewer only after the final candidate and checks are ready. Supply the
immutable original scope, current candidate, complete findings and relevant evidence.
The reviewer validates its supplied attempt directory with `admission` before reading
the subject. A helper refusal means retain that attempt and repair its actual binding.
The last task's review includes the accumulated branch and task interactions; do not
add an obligatory separate final-review stage. The reviewer independently challenges
requirements, affected callers, failures, authorization, tests and documentation.

Retain and report every attempt, including interrupted or imperfect reports. Repair all
blocking families before a new review; repair any accompanying concerns in that batch.
Concern-only findings need the person's fix/accept decision. Outside-scope observations
are automatically preserved in the existing review history and the run index's Follow-up
work section. They do not require a disposition to complete otherwise valid scoped work.
Never silently implement them, call them fixed, or treat tracking as scope approval.
Nonempty ambiguity needs a real decision; formatting alone does not erase findings or
renew an allowance. A spent allowance requires a human `grant-review` decision before
another reviewer can be admitted. Ask for exactly the count the person intends; a request
for one round must never grant the configured larger window.
Read the finding index's incomplete reviews and original finding positions as well as
its classified findings. Unclassified fragments remain review evidence to address.
Reviewers return the minimal decision defined in the shared review prompt and check it
within their own turn before finishing. The rest of the receipt is flexible and never
parsed for approval. Repair agents must read the full current_review report in their
packet before acting. Judge each suggested correction against the approved scope and
a concrete behavioral failure; review prose never grants scope or human authority.

Only `complete` may record task completion and commit the exact reviewed candidate.
Author claims, a task checkbox, green checks or a standalone receipt cannot authorize
it. A failed completion is repaired idempotently from retained evidence. Select the
next task from external completion records, under the same finite task batch. At a batch
boundary ask whether to continue the projected next batch, publish completed work or
stop; silence grants no additional tasks.
If all design tracks have converged with completed tasks but the design is still approved,
select its bounded `finalize` task and use the same candidate/check/review/completion path.
Finish any requested completed-task re-review and its correction before publication;
an earlier clean completion does not resolve a newer blocker.

## Outside-scope follow-ups

Apply this policy consistently to Deliver, Design, Propose and standalone Review.
Retaining the reviewer result already saves every finding durably. Show the open
follow-ups and their actual destinations in the final report and on continuation;
use the existing run index, not a new backlog database or only a PR footnote.

Use ordinary conversation and native tools for tracking instructions. If a decision
is useful, offer context-appropriate choices such as Add a follow-up to this design,
Create or link a GitHub issue, or Keep in saved follow-ups. There is no mandatory
routing menu. Report retained follow-ups without posting an optional question that
would keep ready work waiting. Ask only when a requested tracking action needs a real
decision or missing authority. Honor an existing explicit preference without asking again. GitHub
tracking may find an appropriate existing issue or create one under explicit or standing
human authority; do not require the person to predict an existing issue URL. Record the
resulting URL with `finding-track --destination` (`finding_track`) without another
routing approval. Recording a URL grants no permission to create an issue or fix it.

For Deliver with a mutable repo or private design, related future work can be quoted
in its `## Open review scope` section using `finding-track`. This is a follow-up note,
not a new approved task. If the work belongs to an existing future task, identify that
relationship instead of duplicating it. Adding executable tasks or expanding requirements
goes through Design/Propose and the appropriate approval; it cannot alter the admitted
task list, grant more tasks, or silently reopen a frozen design.

During scoped blocker repair, the default tracking helper can append notes to the
mutable delivery design before the next candidate/check/review. An already successful
exact-candidate review is preserved: the default retains the follow-up externally
instead of editing its reviewed design. If the person chooses an actual document edit,
include that changed document in checks and a fresh review before completion. Explain
that effect before making the choice. Never spend another review merely to file a note
when keeping it in saved follow-ups satisfies the person's request.

Design and approved Propose additions can use a mutable design in their configured
repo/private designs folder for informational notes, within the current initiative.
Material additions still need the existing refinement/approval process. Frozen designs,
correction runs, quick fixes without a design and standalone reviews keep findings in
saved follow-ups or an authorized issue; offer a separate Design/Propose follow-up when
appropriate. No destination decision blocks an otherwise ready scoped task.

## Native decisions

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

Before a consequential question, call `decision-request` (`decision_request`) for its
kind and concerned attempt, plus `--rounds N` for an exact additional review count.
When combining this with a routine action such as creating an issue, `--also TEXT`
includes that instruction in the same presented choice. The runtime grants only the
bound consequential effect; the host carries out the accompanying authorized action.
It binds the current subject and effect without granting anything. Present its returned
question and positive choice through the native host, unchanged; keep the returned
refine/cancel alternatives where relevant, or offer other non-granting alternatives; explanations and full previews
belong in the surrounding conversation. Include its `decision` identity in the actual
human locator when calling `decision` (or `resume`). A direct Yes about this same shown
question also works when a menu is unavailable. Preserve the prepared identity and actual
answer across recoverable failures; do not regenerate the question after it was answered.
If the person changes the requested scope/count, prepare that actual effect and ask only
for the changed boundary. Do not infer grants from a model's paraphrase of free text.

Consequential kinds are `continue`, `grant-review`, `accept-concerns`, `publish`, `pause`,
`stop`, `resume`, `approve-proposal` and `approve-private`. Scope preparation returns its
own `approval` question for native quick-fix acceptance. Claude plan-viewer acceptance
continues to bind the actual full plan directly, without an extra decision request.
Native Pause/Stop commands remain immediately usable. Older already-presented canonical
choices remain readable for recovery; do not build new wording around that compatibility.
Routine clarification, issue tracking and follow-up bookkeeping need no durable grant.
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

## Visibility and publication

Introduce the actual work once using implementation/planning/proposal agent and
independent reviewer agent. Report meaningful native transitions and new findings;
do not repeat unchanged status or accumulate raw command logs. Before discovery say
"I'll look for saved work"; say "Resuming" only after the answer. Use short updates
about the draft, checks or findings, not helper names, receipt paths or attempt IDs.
For example: "Your draft has a completed review to recover, with one review round left."
Then ask the Resume question. After acceptance: "I'll recover that review first."
Repair routine host-save/locator failures within the accepted choice without another
menu or asking the person to bypass OH. Report a genuine external blocker with the
preserved artifact and one concrete recovery step; defer unrelated questions until it
is resolved. Native tool cards remain host-owned. On completion lead
with the recorded review outcome, attempts and findings, then the delivered behavior,
actual checks, commit/artifact and next decision. Say no findings only when none exist.

Publication requires the human decision bound to reviewed HEAD and destination. Use
`publication` to reconcile the existing PR before pushing or creating one. A failed
lookup is not permission to create another. Use `pr-summary` as verified facts for a
human-readable PR body, rather than copying an audit dump. Per task, explain the
completed behavior, review round count, final receipt identity and elapsed time,
verification, final verdict, and concise findings with their actual dispositions.
Read the complete final review receipt and summarize its evidence: anchors read,
scope examined, concrete attacks and results, and limits. Keep that narrative fluid;
no rigid receipt headings or prose parser are required. Summarize earlier rounds
and recurring findings; do not paste full receipts, repeated findings, raw JSON,
transcripts or local evidence paths. Do not move an audit dump into PR comments
as a size workaround. Include why work stopped and the short task checkpoint history. Full original receipts, findings and decisions stay in OH's
saved workflow history; a PR summary never replaces them or grants authority.
Retain the single generated `oh-publication` comment unchanged so reconciliation
can recognize an updated description independently of its prose. For a large batch,
summarize and group the findings further; never split approved work or rerun reviews
because of description length. Write the finished body to an external file, push
the authorized head/branch without force, and create or update only the matching
PR with `--body-file`. Re-run publication reconciliation after an uncertain
response. Attach the PR in Codex with `attach_artifact` when available. Human merging
remains separate; published cycles stay terminal.

Inspect CI for that PR's actual head. Report meaningful check changes and diagnose
failures from relevant logs. An empty, pending, failed, cancelled or skipped check set
is not success. Do not make code changes under publication-only authority: corrections
need bounded implementation, verification and fresh review. A resumed publication
reuses its grant and PR; it never reruns implementation just to recover publication.
