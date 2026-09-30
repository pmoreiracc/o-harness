# Using OH

OH does nothing until you invoke one of its commands. An ordinary prompt such as "design a
login page" never starts OH. Claude uses `/`, Codex uses `$`. The first command in a checkout
registers it.

You type a command once. If something is in the way, the agent fixes it and OH carries the
command out, without asking you to type it again. Only choices that are yours reach you, as a
menu: for example, what to do with your own uncommitted changes, or whether to stop a run that
is still open. Answer in the menu: if you type something else instead, OH sets the command
aside and tells you so. A new command replaces one that hasn't run yet.

## Plan: oh-propose and oh-design

`/oh-propose <idea>` finds where the idea belongs, such as
`/oh-propose search across my notes`. A fresh worker reads your roadmap, designs, decisions
and code and picks one route:

- a new **roadmap row** (and a new milestone, or a proposed decision record when where it
  belongs is genuinely contested);
- a **task** added to an approved design;
- an **improvement** to existing behaviour, which needs no document;
- or **unclear**, with the two readings and the question to answer.

Before writing anything, OH shows what it understood, the route and why, and the exact lines it
would write, and waits for **approve**, **refine: <what to change>** (ask again with your words)
or **reconsider** (nothing is written; OH asks what you meant, and your next message is the new
idea). After approve, OH writes the row, milestone, decision record or task itself (on a new
`propose/<topic>` branch from `main`, which OH brings up to date and switches to first), checks
the plan rules and has it reviewed independently, then commits it. You see everything it will
write (the lines, the milestone, a new milestone's "Done when", a task's track, a decision
record's text); if the review would change any of it, OH asks you again first. An improvement or an unclear idea writes
nothing and needs no review. After the commit, **pr** opens the pull request; merging it
approves the plan change. Plans run none of your project's checks: OH checks every plan file
it writes against the plan rules and undoes a write that breaks one.

Typed without its argument, `/oh-propose` asks "What's the idea?" and `/oh-design` lists the
roadmap rows without a design; your next message is the answer. Another OH command replaces
the question, and `/oh-stop` drops it.

With repository plans, `/oh-propose` and `/oh-design` work in the checkout that has `main`; in
another worktree of the project, OH asks you to type the command there.

`/oh-design <slug>` writes the design doc for one row of your roadmap, such as
`/oh-design auth`. A fresh worker writes the design; OH numbers the doc, links it from the
row and checks its task list. An independent reviewer checks the design, and OH commits it
(on a new `design/<slug>` branch from an up-to-date `main`). Type **pr** to open the pull request; merging it approves the
design. When a question has to be answered before the design can be written, OH writes a
proposed decision record instead, with the question, the options and a recommendation, and
leaves the decision to you.

The first time, choose where plans live ([configuration](configuration.md)). The repository
flow above uses pull requests. With `plans.location=private`, documents live outside the
checkout, normally in `~/oh-plans/<project name>/`, with no Git branch or commit. `/oh-propose`
asks before it writes, as above; `/oh-design` waits for **approve**, **refine: <what to change>**,
or **reconsider** after independent review.
Approving a private design records its exact content hash; later edits invalidate approval.
Run `/oh-design <slug>` on an edited private design to review the existing text and approve it
again. `oh plans list` distinguishes approved, draft, and edited-since-approval designs.
A proposed decision document still needs a human decision; approving its saved text does not
choose an option.

## Build: oh-deliver

- `/oh-deliver` lists ready designs and explains why others are unavailable.
- `/oh-deliver 0005` starts the next ready tasks from approved design 0005 immediately.
  Add a track name to select only that track. Repository designs must match their approved
  revision on `origin/main`; private designs must match their saved human approval.
- `/oh-deliver fix the sign-in timeout` proposes a bounded task list. The agent prepares
  it and shows the tasks, limits and a trigger such as `$o-harness:oh-deliver request:<id>`.
  Type that trigger yourself to approve execution. The approved scope cannot grow afterwards.

Ready tasks are selected in dependency order; blocked work stays pending. OH owns task
checkboxes and freezes a design when its last task completes. For private plans, the reviewer
sees the proposed document update alongside the code; OH publishes the update only after the
reviewed code commit, with recovery if saving is interrupted. Private documents stay out of Git.
Private progress also records its code revision: OH continues on the design's delivery branch,
and progress made on any other branch needs that branch merged first. An older private plan with completed tasks but no recorded revision needs
review and reapproval through `/oh-design <slug>` from the checkout containing that completed code.

OH then runs the tasks on `deliver/0005` (`deliver/0005-<track>` for one track), made from
an up-to-date `main`. If that branch still holds unfinished work, from a delivery you stopped,
OH resumes it and merges `main` into it; one pull request then publishes all of it. If `main`
conflicts with that work, you choose: start over from `main` (the branch is discarded), finish
without `main`'s changes (you resolve the conflict when the pull request merges), or let the agent
plan a resolution for you to approve; the next task's review then covers it, as it covers commits of
your own on that branch. A branch that already holds the whole design goes to its pull request: typing the command
again offers **pr** again, even after **stop**, and new tasks for that design come after it merges. Typing the
same command while its run is open continues that run. For each task a
fresh worker implements it, your project checks run, an independent reviewer checks the
exact result, blockers get fixed, and the reviewed tree is committed. Workers can't write
OH's state, your settings or Git internals.

A batch has 5 tasks and each task gets up to 3 review rounds by default; change that with
`/oh-config` ([configuration](configuration.md)). If a task still has findings after its review rounds,
OH pauses and shows the choices. At the end of a batch, choose **continue**, **pr** or
**stop**. The agent shows the choices as a menu where the host can show one: Claude's
question menu, or a Codex pop-up. Menus were checked in the Claude CLI, desktop app and phone
(Remote Control), and in the Codex CLI, desktop app and iPhone. Typing the word always works too,
and is the way to choose where no menu can be shown, such as `codex exec`. At an approval, pick **Other** in Claude,
or **Refine** in Codex, to say what to change. **pr** lets the agent push the branch and open a pull request with the
review summary; you merge it.

You can still code, commit and open PRs without OH at any time.

## Pause, resume and stop

- `/oh-pause` finishes the current step, then waits. The status is PAUSING until it is
  quiet, then PAUSED.
- `/oh-resume` continues the same batch with what is left of its approval.
- `/oh-stop` stops the batch and keeps all files, commits and evidence. A stopped batch
  can't resume; new work needs a new approval.

If the agent is busy, run `oh --root <project> pause` or `oh --root <project> stop` in a
terminal. `oh --root <project> status` shows the current run.

If files change while a batch is paused, OH refuses to resume until you restore them or
stop the batch. It never discards your edits.

## Projects

- `oh init` registers a checkout, named after its repository (`--name` picks another name).
  It grants no work.
- Another worktree of the same project: `oh init` joins that project (or
  `--attach <project-id>`).
- A checkout you moved: `oh init --reattach <checkout-id>`.
- A new checkout at an old path: `oh init --replace`.

To reuse a project's settings and checks elsewhere, run `oh profile-export <file>` and
`oh --root <other-checkout> profile-import <file>` (add `--name <name>` when a project on
that machine already has the name). Exports contain no credentials,
sessions or evidence. Export fails unless every check runs a script tracked in the
repository, such as `["./scripts/check.sh"]`.

## Dashboard

On macOS and Windows, `oh service-install` starts the dashboard at <http://localhost:4318> and keeps it
running across logins. On Linux, run `oh serve`. See [dashboard and data](analytics.md).
