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
For a matching supplied request, report where the work stopped and continue without
another resume question. Free-text proposals and quick fixes need not repeat the old
words: read their saved scope/report and judge whether this is the same work. Never
build a similarity parser or silently absorb a changed scope.

With no subject, show relevant unfinished work and ask once whether to resume it or
choose different work, even if there is only one candidate. Multiple plausible matches
need a selection. If no saved work matches, follow the workflow's normal new-work entry.
The general selector itself grants no execution. A clearly different request does not
select unrelated work; preserve it and resolve actual switching/branch conflicts.

Read selected facts with `resume --run ID` (Codex `resume` with `run`). Once prior native
work is quiescent, bind continuation with `resume --run ID --human <locator.json>`
(Codex `resume` with `run` and `human`). A matching nonempty native workflow invocation
can authorize continuation; an empty invocation requires its actual selection answer.
Plain conversational continuation uses the existing native Resume question/reply.
These helpers preserve the original scope, settings, findings, approvals and remaining
allowances. Do not reprepare free-text scope merely to transfer a session or host.

Resume the actual phase: retain terminal child evidence, continue unfinished authoring,
use valid completed author/check/review evidence, restore the latest proposal preview or
human decision, or finish completion/publication. Read the referenced report and scope;
phase labels are hints, not authority to bypass admission checks. A live child is awaited
or cancelled through its host before replacement; another session or elapsed time is not
proof of termination. Completed reviewers are never resumed. A changed candidate needs
its existing verification/review path, while unchanged work does not need repeated analysis.
A spent allowance, proposal approval, finding decision, private approval or publication
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
| Record a consequential human decision | `decision <kind> <locator.json> [--attempt ID] [--destination FILE]` | `decision` |
| Prepare standalone feedback | `review -- <selector...>` | `review` |

Manifest and locator JSON files belong in external writable scratch storage. Codex tools
receive the equivalent JSON objects. A locator names actual host evidence: `host`,
`session`, and available `turn`, `transcript_path`, `tool_use_id` or `child_session`.
Copy identities from native events; do not invent a human message, child ID or result.
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
A summary is not the retained report. Never run two implementation agents together or
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

Admit a fresh reviewer only after the final candidate and checks are ready. Supply the
immutable original scope, current candidate, complete findings and relevant evidence.
The reviewer validates its supplied attempt directory with `admission` before reading
the subject. A helper refusal means retain that attempt and repair its actual binding.
The last task's review includes the accumulated branch and task interactions; do not
add an obligatory separate final-review stage. The reviewer independently challenges
requirements, affected callers, failures, authorization, tests and documentation.

Retain and report every attempt, including interrupted or imperfect reports. Repair all
blocking families before a new review; repair any accompanying concerns in that batch.
Concern-only findings need the person's fix/accept decision. Outside-scope findings need
a durable route or dismissal, never silent implementation. Combine related choices in
one native question when useful. Nonempty ambiguity needs a real decision; formatting
alone does not erase findings or renew an allowance. A spent allowance requires a human
`grant-review` decision before another review can be admitted.
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

## Native decisions

Use Claude `AskUserQuestion` or Codex's available native question tool directly for real
decisions. Keep choices short and explain their effects in chat. If the available tool
cannot collect that decision or a native menu fails, show the question once and wait for
a direct human reply. Preserve an existing valid answer; do not require exact wording,
repeat a command, poll an OH menu or synthesize an approval in an agent message.

Record consequential choices with `decision` and the actual native human locator:
`continue`, `grant-review`, `accept-concerns`, `route-scope`, `dismiss-scope`, `publish`,
`pause`, `stop`, `resume`, `approve-proposal` or `approve-private`. Include the concerned
attempt/destination where required. Routine clarification needs no durable gate.
The person controls publication and new allowances; reviewer or model prose does not.

Claude quick fixes use the native plan viewer's single Accept. Put the complete bounded
scope preview in the plan file designated by `EnterPlanMode`, then call `ExitPlanMode` without an
extra `AskUserQuestion`. Bind that actual acceptance with `scope approve`. This display
copy is not a consumer design. An edited preview needs refreshed scope and approval;
rejection or interruption grants nothing. If native plan tools are unavailable, show
the preview and obtain a direct human approval in chat. Codex uses a native question
or direct human reply about the same complete scope. Never ask twice for one approval.

For documents, show the actual complete artifact or preview before its question. Native
approval questions identify that artifact's actual path as well as its relevant scope.
Native file display is optional; a failed display falls back to readable chat and a direct
reply. Do not ask someone to create a project or restart their session just to read it.
Repository design approval is human merge; private approval is bound to reviewed contents.

## Interruption and recovery

Stop means cancel owned native work before any later phase. Use native cancellation
for known active children/commands and confirm their outcome; interrupting the parent
alone is not proof. Do not claim cancellation until confirmed or start another worker
while old work may run. If the host cannot confirm cancellation, explain the specific
remaining native task and next action. Do not build a replacement process supervisor.
Pause lets the current step finish and retains its result before waiting.

After interruption, inspect status and native work before resuming. Preserve attempts,
findings, settings, scope and spent allowances. Recover a routine helper failure and
retry the valid operation within existing authority. Never discard, stash or commit
another person's edits by assumption. An unavoidable blocker names a concrete remedy;
elapsed time, retries and restarts never create approval.

## Visibility and publication

Introduce the actual work once using implementation/planning/proposal agent and
independent reviewer agent. Report meaningful native transitions and new findings;
do not repeat unchanged status or accumulate raw command logs. On completion lead
with the recorded review outcome, attempts and findings, then the delivered behavior,
actual checks, commit/artifact and next decision. Say no findings only when none exist.

Publication requires the human decision bound to reviewed HEAD and destination. Use
`publication` to reconcile the existing PR before pushing or creating one. A failed
lookup is not permission to create another. Generate `pr-summary` into an external
file, push the authorized head/branch without force, and create or update only the
matching PR with `--body-file`. Re-run publication reconciliation after an uncertain
response. Attach the PR in Codex with `attach_artifact` when available. Human merging
remains separate; published cycles stay terminal.

Inspect CI for that PR's actual head. Report meaningful check changes and diagnose
failures from relevant logs. An empty, pending, failed, cancelled or skipped check set
is not success. Do not make code changes under publication-only authority: corrections
need bounded implementation, verification and fresh review. A resumed publication
reuses its grant and PR; it never reruns implementation just to recover publication.
