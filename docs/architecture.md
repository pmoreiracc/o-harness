# Architecture

OH's native workflow candidate uses skills and focused validation helpers. The host
runs agents and their tools; OH retains scope, allowances and evidence. The observed
Codex parent-Stop limitation is tracked in [issue #81](https://github.com/pmoreiracc/o-harness/issues/81)
and [upstream #55521](https://github.com/openai/codex/issues/55521).
The [native Stop recovery implementation](plans/native-stop-recovery.md) adds tool
revocation and owned command cleanup. Disposable Codex Desktop probes established
the approach; integrated host acceptance remains pending. A stopped parent, revoked
worker and terminated native model are distinct facts.

| Path | Contents |
|---|---|
| `runtime/oh/` | Scope, journals, native provenance, checks, review, completion, publication and analytics |
| `plugins/o-harness/` | Host plugin skills, Claude agent definitions, passive prompt hook, agent launch guard and launchers |
| `workflows/` | Shared native workflow and workflow-specific instructions |
| `prompts/` | Authoring and independent-review contracts |
| `config/` | Defaults and OH's invariants |
| `dashboard/` | Static dashboard assets |
| `integrations/` | Test, packaging and development scripts |
| `.claude/`, `.codex/` | Configuration for developing OH itself |

## Install layout

A built plugin carries the shared core. Its launcher installs a newer version under
`~/.local/share/o-harness/versions/` and records the active runtime. Both hosts use the
same OH data and settings. Current helpers read retained historical evidence rather
than routing requests back to a retired executor. Original admissions, configuration
snapshots, task grants and consumed allowances are not rewritten by an update.

Finish or cancel native work before changing builds. Adoption of unfinished work must
occur at a quiet boundary and preserve its scope, commits, findings and allowances.
A run completed outside OH must not be reopened or relabelled as OH-reviewed. See
[installation](installation.md) and [usage](usage.md).

## Native execution and authority

The coordinating skill selects work and launches one fresh native agent at a time.
Codex uses its default native role with no parent-history fork and explicit model and
reasoning effort. Claude uses packaged named non-fork agents with invocation-specific
model and effort. No OH headless model runner, agent scheduler or permission broker
executes the task.

Claude child reports can arrive through a forwarded native handback or the completed
Agent call's structured handback report. OH matches the original report to the child's
acknowledged terminal handback, preserving its full text. Retention retries reuse the
same completed attempt and do not repeat assessment or consume another allowance.
Native final notices may omit the spawn-call ID; OH still requires the bound parent
and child, current lifecycle and settled owned tools. Interim background-wait notices
cannot finish the attempt. Native system-marked background completions are tool evidence,
never human approval, including when Claude delivers them as user-role messages.
Claude Desktop Stop may leave only the child's native interruption record and
spawn-linked `stoppedByUser` metadata. Together they establish interruption when
no later lifecycle or child activity supersedes them; no parent completion is required.
Both native user-interruption marker variants are recognized, including interruption
during tool use; the marker still needs the associated native cancellation evidence.
An omitted Claude spawn-call ID is recovered only from a unique native launch
result, then checked against the immutable admission as usual.

Claude's Agent and SubagentStop hooks reuse checked binding and retention. A hook is
a wakeup, not proof that the child's tools have settled; delayed evidence is retried
through the same helpers. Codex task paths resolve through native session metadata.
Child admission and author helpers can recover a missed binding on both hosts, preserving
the original profile checks and admission. No hook launches work or grants continuation.
This keeps the golden reference's automatic bookkeeping while checking the delivered
report rather than copying `last_assistant_message`: current Claude can deliver its report
through `SubagentHandback` before Stop, and hooks can precede saved terminal evidence.
See [Claude's lifecycle payloads](https://code.claude.com/docs/en/hooks#subagentstop) and
[Codex's native orchestration](https://learn.chatgpt.com/docs/agent-configuration/subagents#orchestration).

Review decisions may follow a short preamble, but must be unique and outside quoted
examples. The complete receipt is retained. An older missing-header classification can
be corrected from the same native result on the unchanged subject without a new round;
its original result and receipt remain immutable and the correction is journaled separately.

The native host owns tool permissions and agent execution. OH shell wrappers inherit
those permissions and use the existing process cleanup utilities. Reviewers
follow a no-edit contract under inherited host permissions. Candidate mutation
invalidates their receipt; this does not provide a separate filesystem sandbox and
cannot detect an edit subsequently reverted.

The agent launch guard refuses a native agent launch whose model, effort or fresh context
differs from the admission it names, before the child starts; it grants and launches
nothing, and binding still validates every launched child. The prompt hook exposes only a native source locator. It neither classifies replies,
grants work, starts a workflow nor writes a waiting record. Consequential helpers read
the actual native human message or question/plan acceptance and bind its scope,
subject and consumption identity. Agent text, sidechain input, elapsed time, retries
and restarts grant nothing. Trusted native records are accepted under normal host
permissions; custom host software can imitate such records, an explicit limitation
in `config/invariants.json`.

Skills ask real questions directly through native tools or ordinary chat when those
tools are unavailable. `decision-request` binds the precise presented effect and current
subject before a consequential native question. `decision` verifies the actual answer
against that record, including the exact additional review count; it does not classify
arbitrary prose as a grant. Native tools render the question. Ordinary conversation and
tracking instructions stay with the host agent. Older canonical choices remain supported
for recovery, without extending their phrase vocabulary.
At a completed-task checkpoint, the complete native single-select menu and exact chosen
action bind to the prepared work boundary. Introductory question wording is presentation,
as in the golden reference's Claude task checkpoint. Changed work, allowances or destination
still invalidate the decision; incomplete menus and arbitrary Yes replies grant nothing.
Other consequential questions and older prepared records retain their exact context checks.
Claude quick fixes use the native plan viewer's single Accept, bound to the actual
accepted scope. Drafting a design needs no extra scope question. Repository design
approval remains human merge; private design approval binds the reviewed contents.

Outside-scope observations are durable follow-ups in retained reviews and the run index,
not mandatory completion gates. Optional tracking records a real issue URL or a mutable
design note. Notes never extend approved tasks, and changing a reviewed document requires
checks and fresh review. Repo and private plans use the same policy; frozen designs and
work without a design retain follow-ups without forcing an issue destination.

## Focused helpers

`native.py` supplies explicit operations for scope preparation/approval, attempt
admission/binding/retention, candidate preparation, checks, human decisions, reviewed
completion and standalone feedback. `status` returns facts, not an agent dispatch or
generated question. The journal retains each attempt before launch, including failed,
empty and interrupted launches. Native identity and result records bind the agent to
that admission without treating an author summary as completion proof.

Every workflow reads `status --saved` before preparing new work. It reads both checkout
bindings without changing selection; `resume --run` reads a specified journal, while a
verified answer to a Resume question naming the saved subject and branch can transfer
ownership and select it. A matching workflow command alone grants no continuation.
The review binding's
optional `selected` flag preserves unfinished feedback when returning to the ordinary
workflow; old bindings without that flag keep their existing selection behavior.
Phase hints describe retained evidence and pending decisions; admission and completion
remain authoritative. Recovery retention after a valid Resume command does not make
that command stale or replenish its allowance.

The implementer prepares provisional task/lifecycle changes and verifies the final
candidate. A fresh independent reviewer examines that candidate against the immutable
original scope, project contracts and prior findings. Provisional marks are content,
not completion authority. Only completion validates the passing checks, review and
current candidate before recording the task and committing the reviewed tree.
The last task's review includes the accumulated branch and task interactions.

Checks and repairs stay within the approved task. A repeated blocking family in two
independent reviewer receipts triggers implementation escalation. A spent review
allowance requires a verified human grant; retrying or switching hosts does not renew
it. Standalone feedback cannot count as workflow review or authorize repairs.

`handoff.py` retains bounded current packets with immutable scope/evidence references
and complete finding indexes. Full worker transcripts stay outside the mandatory
coordinator context. Original reports are retained without a mandatory prose schema.
Author repair claims and independent reviewer closure remain distinguishable, including
findings from imperfect reports. Supplemental measurements are hashed evidence
references, not approval.

## Host entries

Claude calls the packaged launcher through its ordinary native tools. Codex calls
focused OH operations through the plugin MCP bridge because OH state lives outside
the consumer checkout. The bridge validates the calling native conversation and its
Git root before invoking the corresponding helper. Native child agents can use
candidate/check/admission helpers; child prompts cannot grant scope or publication.

The MCP server does not launch model subprocesses, display questions or accept an
arbitrary command proxy. Project checks use the saved configuration and ordinary
check process utilities. Settings, setup, backups and services remain explicit
commands. A native permission rejection is not bypassed through another entry.

Transport cancellation alone does not establish workflow Stop. `cancellation.py`
records attributed native interruptions outside the consumer checkout. Codex uses
its Interrupt callback; both hosts can recover from saved interruption records.
Tool callbacks block revoked workers. Each native shell command is reserved by its
PreToolUse callback and runs through a literal `owned-command` invocation using the
same shell tool and sandbox. No hook returns permission approval or rewrites inputs.
Worker cleanup receipts use private temporary storage; shell commands only read
OH’s durable state. Configured checks reuse their existing process groups or Windows jobs.
Native SIGINT/SIGTERM unwinds the check helper through command cleanup. Owned command
execution waits until its kernel process identity has been saved; Windows processes
start suspended in a named job that terminates members when its last handle closes.
After a stopped verification helper releases its execution lock, Resume can reconcile
a missing configured-check receipt from that saved identity. Unknown or reused identities
never authorize a signal. Historical receipts without an identity require conclusive
cleanup evidence, such as a kernel boot time later than the command start.

Resume verifies the existing human answer, waits for command/tool cleanup, and then
transfers ownership under the tool-admission lock. Old attempts remain revoked after
same-conversation or cross-conversation continuation. A cleanup receipt does not
claim native model termination. Late reports remain attached to the original attempt
and cannot turn its cancelled outcome into success.
The exact instruction “Retry the same Resume answer now” preserves the existing
answer; it grants nothing independently. Changed instructions or a later Stop still
invalidate continuation. Repeated questions are matched to their prepared decision's
creation time, so an older identical question cannot replace the current answer.

Native hooks are trusted host integrations, not a security sandbox. A missing or
failed callback, a killed wrapper, detached work or an external service can prevent
verified cleanup. OH must retain that uncertainty and refuse overlapping work.
The [evidence and acceptance plan](plans/native-stop-recovery.md) separates live
prototype results from fixture coverage and pending platform tests.

## Git subjects, completion and publication

Git reads and candidate construction preserve the user's configuration, including
line endings, while discarding inherited selectors for a different repository or
index. The explicit checkout is validated before fingerprinting. Candidate trees use
a temporary index; status does not refresh the user's index. Tracked files,
nonignored children, file/folder replacements, gitlinks and conflicts remain part of
the actual subject rather than being hidden by staging differences.

Approved task structure and completed history are checked mechanically. Required
living-document changes remain possible within the original scope; the independent
review assesses semantic scope drift. Native evidence stays outside consumer
repositories and their Git directories.

Publication permission binds the reviewed head and destination. Reconciliation reuses
an existing PR and never treats failed discovery as authority to create a duplicate.
`oh pr-summary` validates retained commit evidence and renders a factual starting
point for the native host's human-readable PR body: task summaries, verification,
final review evidence and verdict, finding dispositions,
and the stop boundary. Full receipts and commit-bound evidence remain in OH's
external saved workflow history; no duplicate JSON journal is embedded in a PR.
A compact publication identifier lets reconciliation recognize a description update
while allowing the host to summarize its prose. That identifier grants no authority;
local evidence and publication approval are still validated against the exact commits.
A successful push is not CI success, and the person merges.

Interrupted completion/publication uses retained evidence without inventing another
grant or repeating already verified work. Historical receipts remain historical; a
new host, snapshot or result view does not change what they reviewed.

## Analytics and limits

The SQLite dashboard index is derived from saved observations and never grants work.
Missing measurements remain unknown and subset counters are not added twice. Dashboard
reads make no model calls. New dashboard analysis is unavailable in this candidate;
saved analytics and suggestions remain readable.

Only sequential task implementation is supported. Additional hosts and platforms need
their own native capability and cancellation validation. See [dashboard and data](analytics.md).
