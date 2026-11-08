# Shared native OH workflow

Load this once for the active workflow. The skill coordinates sequential native agents;
focused OH helpers preserve scope, allowances, evidence and reviewed completion. Native
hosts own agent execution and tool permissions. OH records native Stop and cancels
owned commands through the existing process utilities. Keep OH state outside
consumer repositories and keep raw worker transcripts out of the coordinator's context.

Repository work stays in the checkout selected by the person. Never create another
worktree, clone or repository copy for task execution, inside or outside that checkout,
or move the task to another existing checkout. Launch native agents in the same root
without host worktree isolation. Branches provide separation within this checkout;
unfinished work is preserved and reconciled here. This does not change the external
locations for OH evidence, scratch artifacts or configured private plans.

## Entries and facts

In Codex call the connected `mcp__o_harness__<operation>` tool with the checkout's
absolute `root`; the operation names are in the table below. For example, load a
workflow with `mcp__o_harness__resource` and read saved work with
`mcp__o_harness__status` using `saved: true`. In code mode invoke the same tools
through `text(await tools.mcp__o_harness__<operation>(arguments))` inside `functions.exec`.
In Claude use the absolute plugin launcher,
`<plugin>/scripts/oh --root <checkout> <command>` (`scripts\oh.cmd` on native Windows).

OH's `resource` is a tool. MCP resource/template listings do not discover OH tools
or establish connection health. If tool lookup is needed, match `mcp__o_harness__`
in the available tool inventory. A failed text search is not a connection failure.
Retry a failed read once using the actual tool. For an uncertain state-changing call,
inspect its saved outcome before retrying with the same inputs. Preserve the current
request and approvals through recovery. Diagnose a connection failure from the actual
OH tool error; report an unavoidable host action only after supported recovery fails.
Follow the host's actual connection controls; `/mcp` availability depends on the
interface. Setup requires an explicit invocation. Native scope, ownership and
permission requirements still apply during recovery.

Before asking for missing arguments, choosing a branch or preparing any new scope,
read `status --saved` (Codex `status` with `saved: true`). This reads both the saved
workflow and standalone review without selecting either or registering a new checkout.
For current planning/delivery readiness, listing or recovery advice, read
`workflows/entry.md` and call `entry` first; it includes saved-work discovery and
fetches base facts without changing the checkout. Reconcile material saved/local/base
differences before choosing a path or reporting blockers. Standalone review of an
explicit immutable subject needs no unrelated origin refresh.
Match the person's request to the saved scope and actual evidence, not recency alone.
`status` is the retained workflow disposition; `execution` separately reports native
interruption, pending results and unsettled operations. `running` does not establish
live execution, and an interrupted turn does not complete or terminally stop a workflow.
Recorded remaining tasks need reconciliation with current Git and approved documents.
Idle history alone does not reserve the checkout. Different requested work can select
it through its own normal scope authority without Stop/Pause of the old record.
Preserve the old grants, attempts, findings and any real local/unmerged work; inspect
`retained_work` references where they affect the new candidate. Merged output does not
create missing completion or review evidence.
When actually continuing an unfinished saved scope, always ask once, even when the command
names its initiative, design or review subject. A matching request discovers work; it
is not the resume answer. Free-text proposals and quick fixes need not repeat the old
words: read their saved scope/report and judge whether this is the same work. Never
build a similarity parser or silently absorb a changed scope.

For a matching saved run, read `workflows/recovery.md` and `workflows/decisions.md`
before the first question. Delivery uses `decision-request recover` and its Continue,
Start fresh, Stop and take over choices; bind its returned action with `decision`.
Other workflows use Resume. Call Claude `AskUserQuestion` or Codex Default mode
`functions.request_user_input_async` at these questions. Settle prior native work,
then bind the same answer;
continue its actual phase without new scope, repeated questions or renewed allowances.
For new work, follow the selected workflow's ordered steps below the shared protocol.
If a real prerequisite question intervenes, retain its initiating request with
`decision-request --request <native-locator.json>` (Codex `request`). After binding
the answer, use the original locator and that decision ID as `scope prepare --after`
or `scope approve --after` (Codex `after`). Read `workflows/recovery.md` for this path;
never pass a Stop answer as though it were a Deliver invocation or scope approval.

## Read only the procedure needed now

Load these through the same OH `resource` entry; paths are relative to the packaged OH root.
Do not load every reference at entry. If a tool truncates a required resource, read the
remaining content from its saved output before acting on it.

| Situation | Required reference |
| --- | --- |
| Any human question that grants scope, continuation, allowance, acceptance or publication | `workflows/decisions.md`, before preparing or displaying the question |
| Current planning/delivery readiness, listing or recovery advice | `workflows/entry.md`, before choosing a path or claiming current tasks/blockers |
| Resume, missing child binding, rejected launch, interrupted work, Pause or Stop | `workflows/recovery.md` |
| Outside-scope findings or requested tracking | `workflows/findings.md` |
| Publish, reconcile an existing PR, or inspect its CI | `workflows/publication.md` |

## Operations and evidence

Call dependent state-changing helpers separately and inspect each returned outcome
before the next step. Do not pipe admissions or failures through `head`, `grep` or a
success-only formatter that hides the actual result. Keep complete output externally
when large; read the needed fields and referenced artifacts rather than guessing them.

Use these focused operations, through their equivalent named OH tools in Codex:

| Purpose | Claude command | Codex tool |
| --- | --- | --- |
| Discover saved work | `status --saved` | `status` with `saved: true` |
| Reconcile saved/local/origin entry facts | `entry` | `entry` |
| Save, switch and restore in this checkout | `workspace <branch> --human <locator.json> [--base REF] [--after ID]` | `workspace` with `branch`, `human`, optional `base` and `after` |
| Read a workflow or role contract | `resource <path>` | `resource` with `path` |
| Locate, validate or list plans | `plans path\|check\|list` | `plans` with `action` |
| Continue selected work | `resume --run ID --human <locator.json>` | `resume` with `run` and `human` |
| Prepare bounded work | `scope prepare <manifest.json> [--workflow deliver\|design\|propose] [--human <locator.json>]` | `scope_prepare` |
| Select approved design tasks | `scope prepare --doc NNNN [--track TRACK] --human <locator.json>` | `scope_prepare` |
| Bind a quick-fix scope choice | `scope approve <scope-id> <locator.json>` | `scope_approve` |
| Admit a fresh phase | `attempt admit assessment\|implementation\|analysis\|review` | `attempt_admit` |
| Bind the launched native child | `attempt bind <attempt-id> <locator.json>` | `attempt_bind` |
| Retain its original native result | `attempt retain <attempt-id> <locator.json>` | `attempt_retain` |
| Validate review admission | `admission <attempt-directory>` | `admission` |
| Format a worker command without executing it | `command-format ID --argv <JSON array>` | `command_format` with `attempt` and `argv` |
| Check a draft review decision | `review-check --text <quoted-draft>` | `review_check` |
| Prepare provisional candidate content | `candidate` | `candidate` |
| Check the current candidate | `verify [base] [mode]` | `verify` |
| Attach historical diagnostics | `evidence <attachment.json>` | `evidence` |
| Complete the reviewed candidate | `complete <review-attempt-id>` | `complete` |
| Bind the effect before a native question | `decision-request <kind> [--attempt ID] [--rounds N] [--run ID]` | `decision_request` |
| Track retained outside-scope findings | `finding-track ID [--destination URL_OR_FILE]` | `finding_track` |
| Record a consequential human decision | `decision <kind> <locator.json> [--attempt ID] [--destination FILE]` | `decision` |
| Prepare standalone feedback | `review -- <selector...>` | `review` |
| Reconcile the approved PR | `publication [--pr N]` | `publication` |
| Read publication evidence | `pr-summary [base]` | `pr_summary` |
| Follow the published PR's CI | `ci-wait [--pr N] [--timeout SECONDS]` | `ci_wait` |

Manifest JSON files belong in external writable scratch storage. Pass a locator either
as one inline JSON argument or as such a file; never edit locator text with shell tools.

Supplementary evidence preserves attachment-time file hashes and observations. Referenced
source files may change during authorized repairs, and temporary logs may disappear.
Packets label their availability and changes at admission; these references are historical
context, not current verification or authority. Recheck relevant inputs when using them.
Current candidate checks and fresh independent review remain required for completion.
Codex tools receive the equivalent JSON objects. A locator names actual host evidence: `host`,
`session`, and available `turn`, `transcript_path`, `tool_use_id` or `child_session`.
Copy identities from native events; do not invent a human message, child ID or result.
For an answer to a prepared decision, pass the current conversation locator (Claude: the
one in OH's hook context; Codex: `host` and `session`) with its `decision` identity. OH
finds the native question by its prepared text or complete completed-task menu and
validates its saved answer against the same decision;
add `tool_use_id` only when you already have it.
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
`plans path` before planning. If the repo/private location is undecided, call Claude
`AskUserQuestion` or Codex Default mode `functions.request_user_input_async` once.
Configuration changes use `config set`/`unset` and the person's authorized settings.

Before preparing new work, use the project's configured base and an appropriate work
branch. Reuse the matching unmerged branch for interrupted work. For ordinary new work,
create a branch from the refreshed configured base; do not implement or commit on trunk.
Preserve included original edits and explicit existing-PR corrections. If local work
conflicts, inspect ownership and use `workspace` to save unrelated edits, switch and
restore in this checkout under `workflows/entry.md`. This lossless preparation uses the
initiating native request without an extra permission question. Never use another
folder to bypass that conflict. Scope preparation binds branch/base
and starting contents. Its default delivery entry can safely update/select a branch;
`--keep-checkout` preserves a checkout
the agent deliberately reconciled under `workflows/entry.md`. If contents change before approval, preserve the edits
and prepare the same tasks with a current preview. Never reuse the old acceptance for
changed starting work. Include the recorded original commit range in the first task's
implementation and review, together with its current candidate.

## Execute one phase at a time

1. **Establish authority.** Discover saved work, select its actual phase, and obtain only
   the approval that phase requires. Prepare consequential questions before displaying them.
2. **Admit, then launch.** Call `attempt admit <role>`, read the returned profile and
   packet, and launch exactly that fresh native agent. Do not copy settings from an earlier attempt.
3. **Bind immediately.** Save the returned child identity with its actual spawn call ID.
   A rejected binding enters recovery; it does not authorize another launch.
4. **Await, then retain.** Keep the coordinator available for progress and human controls.
   Retain the terminal native result before interpreting its outcome or starting another agent.
5. **Take the outcome's next step.** Authors produce the final candidate and checks;
   the invariant reviewer agent independently reviews that exact candidate. Repair scoped
   blockers, resolve real decisions and repeat review within the remaining allowance.
6. **Complete, then advance.** Use `complete` only with valid check/review evidence and
   required approval. Continue within the finite task batch or present the actual next boundary.
   Standalone review ends with feedback, not `complete` or implementation.

The coordinator owns scope, native launch/bind/retain, questions, progress, completion
and publication. Each author owns its assigned artifact, self-review, `candidate` and
`verify`; the invariant reviewer agent owns independent inspection and its full report.
Do not have the coordinator rerun passing author checks or implement alongside a child.

## Fresh native delegation

Use these stable names in chat; native admission roles and tool identifiers stay unchanged.

| Work | Chat name | Admission role | Shared contract supplied to the child |
| --- | --- | --- | --- |
| Task difficulty | assessment agent | `assessment` | `prompts/assessment.md` |
| Proposal analysis or approved additions | proposal agent | `analysis` | `prompts/analysis.md`, `prompts/propose.md`, `prompts/proposal-routing.md` |
| Design drafting or repair | design agent | `analysis` | `prompts/analysis.md`, `prompts/design.md` |
| Code implementation or repair | implementation agent | `implementation` | `prompts/implementation.md` |
| Independent review in any workflow | invariant reviewer agent | `review` | `prompts/invariant-reviewer.md` |

Load the relevant contract through OH's resource entry and include its resource path
in the child's bounded prompt. Codex default agents do not inherit Claude's named-agent
files. Include `prompts/progress.md` for author/assessment progress. Review updates
describe coverage underway, never an interim verdict.

Admit before attempting any launch. The helper snapshots the current task, role,
profile, bounded packet and allowance. Read that admission; do not select a different
model, broaden scope or construct another dispatch loop. A failed or uncertain launch
is still an attempt: retain its native outcome once before recovering within the same
scope and remaining allowance.
Include the admitted attempt ID, its actual `request.json` path, bounded task-context
path, role contract and absolute OH entry in the child prompt. Reference original
scope/evidence files rather than pasting the parent history or full worker transcripts.
Require admission validation before the first working tool. Every role follows the
packet’s `native_commands`. Copy the returned `admission_command` unchanged into the
child's launch prompt as its first command; the child cannot read the packet before
validation. Do not substitute the coordinator's plugin launcher. The admission result includes the verified, bounded
`task_context`; read it directly instead of bootstrapping another shell read. In Codex,
use `command_format` with the executable/argument array and run its returned command
unchanged through the corresponding native shell tool. The formatter executes nothing
and grants no permissions. Native shell commands use the literal `owned-command`
invocation with an explicit executable/argument array; focused OH helpers run directly.
Pass an explicit shell inside that array when shell syntax is needed. Never append
outer shell operators, nest OH helpers in the wrapper, or bypass a refused tool.
The wrapper inherits the native tool’s permissions; it grants no permission. Do not
launch detached services or use another execution tool to escape owned cleanup.
A Stop refusal or exit 130 ends this worker. The coordinator can admit a fresh one
only after the existing Resume decision and cleanup.

- Codex: call native `spawn_agent` with `agent_type: "default"`, `fork_turns: "none"`,
  the admitted `model` and `reasoning_effort`, the returned `native_task_name` and the self-contained
  bounded packet. Use native wait/list/interrupt tools for that child. Do not install
  user roles, fork the parent history, create another app task or launch a headless CLI.
- Claude: call native `Agent` with the packaged named non-fork type
  `o-harness:implementation`, `o-harness:analysis`, `o-harness:assessment` or
  `o-harness:reviewer`. Pass the admitted model and effort explicitly on the invocation.
  Set its native `name` to the admitted `native_task_name` so the host supplies the
  messaging roster. The child uses `SendMessage` to the native `main` coordinator
  for meaningful progress, including immediately before configured verification.
  Use the host's native child result/notification and cancellation tools. Do not use
  the `fork` type or send a new review to a completed agent.

OH's launch guard checks each native agent launch against the admission it names. When
the model, effort or fresh context differs, the host refuses the launch before any child
starts and names the required settings. Launch that same admission again with exactly
those settings; nothing ran, so there is no attempt to retain or recover.

Prefer a native background/asynchronous launch when supported so the coordinator can
bind promptly, handle human controls and report progress. Await through native host tools;
do not block on a foreground launch and leave a long-running child unable to use its
binding-dependent helpers. If a child reaches `candidate`, `verify` or `admission` before
the binding is saved, bind promptly and retry that same operation after the short host-save
delay. This is not a new attempt, model selection or approval.

Bind the returned native child identity immediately. Retain its complete original result
by native locator only after its terminal native outcome is saved and its owned commands
and checks have finished; an intermediate assistant `end_turn` does not establish completion.
Ordinary tool failures belong to the worker's execution: diagnose and recover within
the approved work. Their individual callbacks are not additional OH handoff requirements.
Claude's lifecycle hooks attempt the same checked binding and retention automatically.
They never launch agents or continue a task. If a hook ran before the host saved its
evidence, retry the existing helper after the native result arrives. Both hosts' child
admission and candidate helpers recover an omitted binding from a unique native launch.
Codex task paths are resolved to their native session IDs; missing IDs can be recovered
with an empty locator object. Ambiguous launches still require the actual original ID.
If binding is rejected, read `workflows/recovery.md`: cancel or await the child, retain
its actual terminal outcome with the original child and spawn identities, then recover
within existing scope and remaining allowance. A cancelled child needs no final report;
never resume it to manufacture one. A completion without a report is unfinished.
Read every new admission's profile, including repairs; escalation can change it.
If interruption prevented a profile from being saved, the actual profile remains unknown;
provable launch attribution and a saved terminal outcome still permit settlement.
Send only a short handoff and evidence paths into the coordinator.
Claude's acknowledged native `SubagentHandback` can carry the complete report. Retain
its original child payload after the host confirms completion; do not rewrite it to
match the parent's warning or indentation. A summary is not the retained report.
Native task notifications can establish completion even when the parent absorbs the
handback message mid-turn. Keep the original spawn locator after a native continuation;
OH follows its attributed latest outcome and refuses stale completion/cancellation.
The same authorized coordinator retains settled work and continues its remaining
phase without another Continue question. Native saving or cleanup is a retry of
that operation, not a new ownership decision. A new invocation or owner still uses
the saved-work recovery decision.

An acknowledged report remains historical evidence when the child continues for
cleanup. Later closing text cannot replace it. If retention returns unfinished,
admit a fresh author to assess the existing candidate and supply its current report;
reuse verification only when its actual inputs still match. Read relevant available diagnostics and retained findings; unavailable optional
archives do not prevent fresh assessment of the current candidate. Never restart implementation just to obtain a report.
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

For Deliver, assess each newly selected task with a fresh assessment agent using the configured profile.
Propose and Design use their analysis role directly; do not insert a delivery assessment.
Keep difficulty in external task evidence, not the project design. Use the resulting
admitted implementation profile. Only a repeated blocking family in two independent
reviewer receipts triggers implementation escalation; an author claim or first blocker
is not that evidence.

### Failed required checks

The implementation agent owns implementation, documentation, self-review and checks,
including diagnosis and repairs covered by the approved task. Preserve useful earlier
work. A failed check is feedback to investigate, not a new Retry or scope approval.

1. Read the failure and relevant callers, test setup and execution environment. Separate
   observed facts from suspected causes. An unchanged file, a timeout or the absence of
   a direct call to changed code does not establish which repair is necessary.
2. Choose the smallest useful diagnostic that answers a concrete unresolved question.
   Use focused reproduction, timing, environment inspection or a baseline comparison
   when it distinguishes plausible causes; none is mandatory for every failure.
   Reuse retained evidence. Do not repeat a full suite unchanged merely because another
   author started, or keep investigating without a useful next experiment.
3. Repair regressions and verification problems needed to deliver the approved outcome,
   including supporting test and environment corrections allowed by the project and
   existing authorization. Scope follows the outcome, not a list of edited files or
   whether a defect predates this task. Baseline reproduction informs diagnosis; it does
   not decide authority or end the work. Preserve acceptance coverage and project rules;
   do not weaken assertions, skip checks or hide a failure by merely raising deadlines.
4. Continue while useful authorized diagnosis or repair remains. If a necessary repair
   exceeds the task, report the evidence, smallest justified change and specific scope
   boundary. If further progress needs permission or an external prerequisite, name it
   and its remedy. If no useful authorized diagnostic remains, state what is known and
   unknown and offer a handoff; do not invent a repair or claim certainty to obtain approval.

The coordinator follows the additional-repair decision in the deliver skill
at a real boundary. A possible repair is not proof that a new scope is needed. These
steps do not grant additional scope, change required checks or renew review allowances.

### Candidate verification and review

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
If an author finishes without the required candidate or passing verification, retain its
terminal result. If useful authorized diagnosis or repair remains, admit a fresh author
with that specific next step and the retained evidence; otherwise handle the concrete
boundary above instead of launching another unchanged attempt. Preserve its
draft/implementation. Do not give missing checks to the coordinator,
reuse the completed admission, or launch the invariant reviewer agent prematurely.

Admit a fresh reviewer only after the final candidate and checks are ready. Supply the
immutable original scope and any verified approved repairs, current candidate, complete
findings and relevant evidence.
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
renew an allowance. A spent allowance requires a human `grant-review` decision before another reviewer can
be admitted. Normally renew the run's snapshotted review window: call `decision-request
grant-review` without `--rounds` (Codex: omit `rounds`). Do not choose one round because
only one more review seems necessary. Override the count only when the person explicitly
requests a different count; never enlarge a one-round request to the configured window.
Read `workflows/decisions.md` before calling Claude `AskUserQuestion` or Codex
Default mode `functions.request_user_input_async` for that question.
When the last available review leaves findings needing another round, obtain that renewal
before starting the next repair/review cycle. Retain an already-running step before asking;
an allowance question neither cancels that step nor authorizes out-of-scope repairs.
Read the finding index's incomplete reviews and historical diagnostic references,
including original report-local positions. Investigate relevant retained claims on the
current candidate. Unclassified fragments remain context, not a synthetic verdict.
Reviewers return the minimal decision defined in the shared review prompt and check it
within their own turn before finishing. The rest of the receipt is flexible and never
parsed for approval. Repair agents read available current_review details in their packet; if archived
details are unavailable, investigate the retained claims against current code and state
any concrete verification limit. Judge each suggested correction against the approved scope and
a concrete behavioral failure; review prose never grants scope or human authority.

Only `complete` may record task completion and commit the exact reviewed candidate.
Author claims, a task checkbox, green checks or a standalone receipt cannot authorize
it. A failed completion is repaired idempotently from retained evidence. Select the
next task from external completion records, under the same finite task batch. At a batch
boundary ask whether to continue the projected next batch, publish completed work or
stop through the completed-task checkpoint in `workflows/decisions.md`. Present every
returned option with Claude `AskUserQuestion` or Codex Default mode
`functions.request_user_input_async`, or use the shared direct-reply path. Bind the
chosen action from that same question; silence grants nothing.
Follow the `next_action` in the returned `continuation`: use `decision-request continue`
when a completed batch leaves tasks pending, or `decision-request publish` when all tasks
are complete. Preparing that question does not publish anything. A request not to push
or publish, or a checkout without a remote, still permits the final handoff choices.
Do not end with only a commit summary while this checkpoint is pending. This applies to
fresh and resumed work; private planning completion and standalone feedback retain their
own endings, and a recorded Stop must not reopen the checkpoint automatically.
If all design tracks have converged with completed tasks but the design is still approved,
select its bounded `finalize` task and use the same candidate/check/review/completion path.
Finish any requested completed-task re-review and its correction before publication;
an earlier clean completion does not resolve a newer blocker.

## Keep the person oriented

Use the chat names in the role table consistently. Keep native agent IDs, tool-call IDs,
receipt paths and helper names out of routine updates; use artifact names and observable
behavior. Model/effort details belong in a compatibility notice or diagnosis when relevant.
Use the same full role name in launch, progress, repair and completion messages. Repairs
remain the implementation agent's work (or the proposal/design agent's work for planning),
not a newly named “repair agent.” Use “invariant reviewer agent” rather than switching
between “reviewer,” “round-7 reviewer” and “independent agent.” Native tool IDs stay unchanged.

At selection, say what work is selected, the next phase and what follows it. During
discovery say “I’ll check the saved work”; say “Resuming” only after the answer is bound.
After a launch is confirmed, name the active agent and its assignment. Do not describe
an admission as a running child, a missing binding as an unlaunched attempt, a repair
claim as a closed finding, or a passing check as reviewed completion.
Address the person in chat; do not expose self-instructions such as “Clean review. Retain
it and complete the task.” Retain first, inspect the actual outcome and findings, then
report the result and next step. For example: “The invariant reviewer agent found no
in-scope blockers. One outside-scope follow-up remains. I’ll record task completion next.”

During Propose, Design and Deliver, report meaningful transitions promptly: authoring
started, checks running or completed, findings retained, repairs underway, independent
review started, completion recorded, or a real decision needed. While an agent is working,
aim for an update about every two to three minutes when useful information is available.
Use a compact native progress/status summary or the child's nonterminal update, never
its full transcript or private reasoning. Relay the current concrete subtask, why it
matters and the next step in one or two sentences. For example:

- “The proposal agent is checking existing roadmap entries so this addition fits without duplicating work. Next I’ll show the proposed route.”
- “The design agent is defining the retry acceptance checks so implementation has a testable boundary. Independent review follows the draft checks.”
- “The implementation agent is fixing cancellation cleanup so interrupted requests release their resources. It will then run the affected checks.”
- “The invariant reviewer agent is checking failure and recovery paths against the approved scope. I’ll report its findings when the review finishes.”

These are examples, not a fixed message template. Use them only when the activity is
observed. If the host provides no useful detail, stay quiet or send a brief generic update
such as “The implementation agent is still working.” Do not explain internal visibility
limitations, invent a subtask, repeat a stale detailed update, estimate a percentage or
promise an ETA without evidence. A time interval alone is not a reason to manufacture news.

Keep the coordinator available while native work is active. Use native wait/status tools
with bounded waits (normally at most 60 seconds per call when supported), respecting
host notifications and human interruptions. Continue automatically on completion within
existing authority. If the host requires yielding to receive a completion notification,
use that native mechanism; do not create a scheduler or promise updates it cannot deliver.
Do not repeatedly message children for progress, read raw transcripts to fill silence,
or resume a completed agent. Routine progress is separate from approval questions.

For recoverable failures, briefly explain the observed problem and the repair/retry
underway when that helps the person understand a delay. For a real blocker, give the
evidence, preserved work, concrete remedy and next action; do not ask the person to debug
internal IDs. A consequential question states the current result, decision, recommended
option and effects, then follows `workflows/decisions.md` without a second confirmation.

At handoff, state what was delivered or remains pending, actual checks and review outcome,
review rounds used/allowed, unresolved findings or follow-ups with their destinations,
the artifact/commit/PR and what happens next. Distinguish author completion, reviewed
completion and publication. Do not end with “done” while an agent or required check is
still active, or call a renewed allowance the “final round” unless that is the actual limit.
Use “clean review” or “no findings” only when the retained review is complete and has no
findings. With only scope findings, say “no in-scope blockers; N outside-scope follow-ups
remain.” With accepted concerns, name them as accepted and still unfixed. An incomplete
review has no successful verdict even if its classified findings list is empty. A task
can be ready while a follow-up remains; report both facts without implying that the
follow-up was fixed. Before the final checkpoint, give this short completion summary,
the completed task(s), next task(s) and each available choice's effect.
