# Using OH

This guide describes the native workflow candidate. **Known limitation:** in the tested
Codex Desktop and CLI paths, stopping the parent did not cancel its native child.
The Desktop child continued to its natural deadline, 168.7 seconds after parent Stop.
This does not block activation or release; it is tracked in [issue #81](https://github.com/pmoreiracc/o-harness/issues/81).
Do not assume an idle parent means its children have stopped. OH adds no cancellation
supervisor or fallback runner. Claude's successful bounded terminal probe does not
establish Remote Control or detached-command behavior. See the
[implementation and validation record](plans/native-workflows.md).

OH skills coordinate fresh agents in Claude or Codex. Your host runs their tools and
handles permissions; OH's focused helpers retain approved scope, checks, review and
completion evidence. Configuration and evidence live outside your repository.

Use `/` in Claude and `$` in Codex. For example:

| Work | Claude | Codex |
| --- | --- | --- |
| Propose an idea | `/oh-propose search across my notes` | `$oh-propose search across my notes` |
| Design an initiative | `/oh-design auth` | `$oh-design auth` |
| Deliver an approved design | `/oh-deliver 0005` | `$oh-deliver 0005` |
| Prepare a bounded fix | `/oh-deliver fix the sign-in timeout` | `$oh-deliver fix the sign-in timeout` |
| Review current edits | `/oh-review changes` | `$oh-review changes` |
| Inspect settings | `/oh-config` | `$oh-config` |

`oh-start` helps select a workflow when the intended work is missing. Starting a
proposal or design authorizes that planning work; it does not authorize product
implementation. A quick fix needs approval of its actual task scope. Questions and
agent reports never substitute for your approval.

## Propose an idea

`oh-propose` examines the relevant roadmap, designs, decisions and code, then explains
what it understood and recommends one route:

- A roadmap initiative, with its milestone and hard dependencies.
- A task in an approved design.
- An improvement to existing behavior that needs no planning document.
- A question when the idea or its destination is unclear.

Before changing planning documents, OH shows the complete proposed additions and their
destinations. Approve them, refine them in your own words, or keep the recommendation
without saving it. A changed route or materially changed additions need approval of
those changes. No exact command wording or extra confirmation is required.

Approved additions are written and checked, then a fresh independent reviewer agent
challenges the routing, dependencies and project requirements. Blockers are repaired
before completion. An improvement or unclear route can finish with its recommendation
or question; it does not need an artificial document or review.

## Design an initiative

`oh-design <slug>` drafts a plan for one roadmap initiative. It defines the approach,
ordered tasks, dependencies and acceptance checks. The request authorizes drafting
directly. A fresh independent reviewer agent then challenges the actual document.
Planning validates documents rather than running product tests.

An open product question that changes the approach remains yours to decide. OH can
prepare its alternatives and recommendation without choosing for you. Approving the
text of a proposed decision record does not decide the underlying question.

The first planning workflow asks where plans live; see [configuration](configuration.md).
Repository plans use ordinary work branches and pull requests. A repository design
becomes approved through your merge. Private plans normally live in
`~/oh-plans/<project name>/`, outside the checkout. A private design needs your native
acceptance of its reviewed contents and no Git commit or PR. Later edits require
review and approval of the changed design before delivery.

Invoking Propose or Design without an argument asks for the missing idea or initiative
in ordinary conversation. It does not start an empty run or invent the selection.

## Deliver code

`oh-deliver` without arguments first shows unfinished delivery work, when present,
and asks once whether to resume it or choose different work. Otherwise it lists ready
designs and explains unavailable work.
`oh-deliver 0005` selects approved design 0005; add a track when needed. Tasks follow
their dependencies, and blocked work stays pending. The number names a design, not an
individual task. An empty ready list does not resume unrelated old work.

For a quick fix, such as `oh-deliver fix the sign-in timeout`, OH prepares a bounded
ordered task list and shows its task and review limits. In Claude, the native plan
viewer's **Accept** is the single scope approval. Codex uses its available native
question surface. When that surface is unavailable, read the complete preview and
reply directly in chat. Refine the proposal before approving if it includes too much
or omits work. Rejecting or cancelling grants nothing.

The scope includes any original manual edits or unreviewed commits that will be
completed with the fix. An existing dirty change stays one coherent repair task;
it is not split across partially completed tasks. Other people's edits are preserved.
An explicit correction to an existing PR keeps that destination.
The preview identifies included starting edits and original branch commits. If starting
contents change before acceptance, OH preserves them and requires a current preview;
replaying an already consumed approval grants no additional work.

For each admitted task:

1. A fresh assessment selects its configured difficulty profile. Difficulty, model
   and effort stay in OH evidence, outside the project design.
2. A fresh implementation agent implements the task, updates required documentation,
   reviews its own work and runs the configured checks. Routine failures are repaired
   within the same scope, without a Retry approval.
3. The final candidate includes provisional task and lifecycle updates. Its passing
   checks and a fresh independent review must cover that exact candidate. Provisional
   checkboxes are not completion authority.
4. Blocking findings are repaired as defect families and independently reviewed again.
   Only reviewed completion records the task as done and commits the reviewed tree.

The last task's review covers the accumulated branch and interactions among its tasks.
There is no obligatory extra final-review stage. Tasks execute sequentially. Agents
receive bounded current context and evidence references; full transcripts do not
accumulate in the coordinating chat.

Your native host controls command permissions, including network, Docker and additional
experiments. OH does not replace those controls or remove the shell from Windows agents.
Reviewers are instructed not to edit and a changed subject invalidates their receipt.
This is a behavioral restriction, not a separate operating-system sandbox; equality
checks cannot detect an edit subsequently reverted.

## Findings, limits and decisions

The approved scope stays fixed. For example, fixing a login timeout may reveal a logout
problem; that observation does not authorize building a second feature.

Blocking findings must be repaired. Concern-only findings let you choose whether to fix
or accept the concern. Outside-scope findings need a durable destination or an explicit
dismissal. Creating an external issue still needs the appropriate authorization.
Original findings remain available alongside author repair claims and later reviewer
closure; a formatting problem does not erase an attempt or its findings. Reviewers
provide a small structured decision (verdict, finding severities, claims and stable
family identifiers), check it before finishing, and keep the full receipt flexible.
The implementation agent reads that full receipt before judging and repairing findings;
OH does not interpret Markdown wording as approval or a new defect family.

By default a batch covers five tasks and each task has three review rounds. `oh-config`
shows the actual project settings. When the task batch ends, choose whether to continue
the next finite batch, publish completed work, or stop. A spent review allowance needs
your grant before another review starts. Failed and interrupted launches are retained;
waiting, retries and restarts do not replenish an allowance. A repeated blocking family
in two independent reviewer receipts triggers implementation escalation. A first blocker
or a missing check tool does not.
When separately delivered tracks converge with every task done, OH selects one bounded
finalization task to check, review and freeze the complete design. It does not rerun the
completed implementation tasks.

Questions use the host's native controls, with a direct chat reply when needed. The
agent explains the subject and effects; there is no separate OH menu engine, exact
reply command or approval the agent can write for you. If the host is still saving a
valid answer, OH can retry that evidence read briefly without asking you to repeat it.
An unresolved obstacle should name what happened and the concrete next step.

## Independent feedback

Ask OH to review a specific subject, or use `oh-review` with `changes`, `tree`,
`paths <relative paths>`, `commit <ref>` or `range <base> <head>`. Historical review
reads that revision without switching your branch. Feedback does not require an
author report, design document or product test run unless the project or subject
actually requires one.

Each standalone request starts a fresh independent reviewer agent. Its receipt is
feedback on that subject, not a delivery review round or permission to implement,
complete or publish work. A clean or explicitly feedback-only review ends with its
report. Add `--feedback-only` when you want no repair offer.

Applicable findings can become a bounded quick-fix preview. Approve that scope once
before repairs; otherwise keep the report as feedback. The original receipt is repair
input, not proof that the repaired change passed review. A later standalone request
does not automatically import old finding history.

For completed unpublished delivery work, `oh-review task <id>` uses that task's saved
scope and remaining review allowance. A clean result returns to the existing decision
without another commit. Blockers enter its scoped repair/review cycle and produce a
correction commit, preserving original completion and review history. Reviewing
published work produces standalone feedback.
Publication waits until the requested task review and any correction are complete;
the earlier clean commit cannot override a newly discovered blocker.

## Pause, Stop and resume

`oh-pause` requests a cooperative pause: the current native step finishes and its
result is retained before another phase starts. `oh-stop` requests cancellation of
owned native work and preserves edits and evidence. Stopped is reported only after
native cancellation is confirmed; a parent interruption or saved stopped status
alone is not that proof. If a known native check remains live, OH reports Stop
requested; cancellation pending, cancels it through the host and starts no later phase.
The native parent-Stop limitation is tracked in [issue #81](https://github.com/pmoreiracc/o-harness/issues/81).
It does not block release. There is no OH process supervisor workaround.

Every work entry checks saved work before preparing a new scope. For example, repeat
`oh-design agent-pipeline` in the same checkout to continue its interrupted draft or
pending decision. Propose and quick fixes compare the requested outcome with saved
scope; you do not need to reproduce the original wording. With no subject, OH shows
relevant unfinished work and asks once whether to resume it or choose different work.
A clearly different request does not silently select an old task.

`status --saved` lists both saved workflow and standalone review facts without changing
selection. `resume --run ID` reads one run; adding `--human` binds an actual native human
continuation. Codex exposes the equivalent `status` (`saved`) and `resume` (`run`, `human`)
inputs. These are focused helpers, not another agent runner.

After native work is quiet, `oh-resume` continues the saved task or decision with its
original scope, settings, findings and remaining allowances. A new session or host
can continue even while the old conversation remains open; no prior Pause or Stop
is needed when no attempt or check is executing. The new coordinator continues the
same work and the superseded coordinator launches nothing further. Existing attempts
keep their original native parents. If a check is still executing, OH waits for that
step before retrying the valid continuation. A new session must not start another
agent while an old child may still be running. Discovery alone does not lift a saved
Pause or Stop; a later explicit matching continuation can. Resume does not
renew a spent review allowance, accept findings or widen scope. This uses the same
checkout and OH data, not migration to another computer.

A completed batch resumes its pending decision or publication; it does not rerun
implementation. An interrupted publication reuses the existing PR and grant. Work
completed outside OH is not reopened or relabelled as independently reviewed.

## Publication

You control whether reviewed work is published and what ships. Publication approval
binds the reviewed head and destination. OH reconciles an existing PR before creating
one; a failed lookup does not authorize a duplicate. A correction updates its existing
PR. Your merge remains separate from the agent's work.

The result should explain what changed, actual checks, review rounds and findings,
then link the commit, document or PR. CI is checked for that PR's actual head. Pending,
missing, failed, cancelled or skipped checks are not a pass. Publication permission
alone does not authorize further code edits; corrections need scoped implementation,
checks and fresh review.

You can still code, commit and open PRs without OH.

## Projects, checks and visibility

Register a checkout with `oh init`; registration grants no work. Use `--name` to choose
a project name, `--attach <project-id>` for another worktree, `--reattach <checkout-id>`
for a moved checkout, and `--replace` for a new checkout at an old path. Configuration,
checks and evidence stay outside consumer repositories.

`oh config` shows the effective settings and their sources. The base branch is detected
from `origin/HEAD`, then `main`, then `master`; `oh config set base_branch develop`
selects another existing branch. New work uses an appropriate work branch from that
base, while interrupted work preserves its matching branch and useful draft.
`oh verify` runs the project's registered checks; an explicit comparison base overrides
the default. A missing tool needs restoration, not weaker tests or a new task grant.
On native Windows, a registered bare `bash` uses native Bash, such as Git for Windows;
use `wsl` or an explicit interpreter when that is what the check requires.
See [configuration](configuration.md) for check definitions and profile import/export.

`oh status` shows saved workflow facts without launching an agent. The dashboard and
retained receipts help inspect scope, tasks, checks, attempts, findings and decisions;
observations never grant authority. Missing usage observations remain unknown.
See [dashboard and data](analytics.md) and [installation](installation.md).
