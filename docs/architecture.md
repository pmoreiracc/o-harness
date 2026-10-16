# Architecture

OH's native workflow candidate uses skills and focused validation helpers. The host
runs agents and their tools; OH retains scope, allowances and evidence. The observed
Codex parent-Stop limitation is tracked in [issue #81](https://github.com/pmoreiracc/o-harness/issues/81)
and is accepted as non-blocking for activation and release. OH must still distinguish
a stopped parent from active children. This is not a claim of validated cancellation
on other host surfaces; see [the migration plan](plans/native-workflows.md).

| Path | Contents |
|---|---|
| `runtime/oh/` | Scope, journals, native provenance, checks, review, completion, publication and analytics |
| `plugins/o-harness/` | Host plugin skills, Claude agent definitions, passive prompt hook and launchers |
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

The native host owns tool permissions, shell execution and cancellation. Reviewers
follow a no-edit contract under inherited host permissions. Candidate mutation
invalidates their receipt; this does not provide a separate filesystem sandbox and
cannot detect an edit subsequently reverted.

The prompt hook exposes only a native source locator. It neither classifies replies,
grants work, starts a workflow nor writes a waiting record. Consequential helpers read
the actual native human message or question/plan acceptance and bind its scope,
subject and consumption identity. Agent text, sidechain input, elapsed time, retries
and restarts grant nothing. Trusted native records are accepted under normal host
permissions; custom host software can imitate such records, an explicit limitation
in `config/invariants.json`.

Skills ask real questions directly through native tools or ordinary chat when those
tools are unavailable. There is no OH menu engine or exact reply-command protocol.
Claude quick fixes use the native plan viewer's single Accept, bound to the actual
accepted scope. Drafting a design needs no extra scope question. Repository design
approval remains human merge; private design approval binds the reviewed contents.

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

Transport cancellation alone does not establish workflow Stop. The recorded Codex
terminal probe left a delegated command running after parent interruption. Stop must
be confirmed by supported native cancellation before later work or completion. OH
adds no replacement process supervisor. The unresolved host behavior is accepted as
non-blocking and tracked in [issue #81](https://github.com/pmoreiracc/o-harness/issues/81);
see the validation record rather than assuming parent interruption cancels children.

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
`oh pr-summary` validates retained commit evidence and renders actual changes, checks,
findings and decisions. Portable evidence belongs in hidden PR metadata; local reports
retain original references. A successful push is not CI success, and the person merges.

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
