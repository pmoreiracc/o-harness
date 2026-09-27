# Using OH

OH does nothing until you invoke one of its commands. An ordinary prompt such as "design a
login page" never starts OH. Claude uses `/`, Codex uses `$`.

## Plan: oh-propose and oh-design

`/oh-propose <idea>` finds where the idea belongs, such as
`/oh-propose search across my notes`. A fresh worker reads your roadmap, designs, decisions
and code and picks one route:

- a new **roadmap row** (and a new milestone, or a proposed decision record when where it
  belongs is genuinely contested);
- a **task** added to an approved design;
- an **improvement** to existing behaviour, which needs no document;
- or **unclear**, with the two readings and the question to answer.

OH writes the row, milestone, decision record or task itself (on a new `propose/<topic>`
branch when you start from `main`), runs your checks and has it reviewed independently. Then
it shows what it understood, the route and why, and exactly what it wrote, and waits for you
to type **approve** (commit it), **refine: <what to change>** (ask again with your words), or
**reconsider** (undo it and write nothing). After approve, **pr** opens the pull request;
merging it approves the plan change.

`/oh-design <slug>` writes the design doc for one row of your roadmap, such as
`/oh-design auth`. A fresh worker writes the design; OH numbers the doc, links it from the
row and checks its task list. An independent reviewer checks the design, and OH commits it
(on a new `design/<slug>` branch; start from `main` or `master`). Type **pr** to open the pull request; merging it approves the
design. When a question has to be answered before the design can be written, OH writes a
proposed decision record instead, with the question, the options and a recommendation, and
leaves the decision to you.

Both need plans in the repository (`plans.location` `repo`); the first time, they ask where
plans live ([configuration](configuration.md)).

## Build: oh-deliver

1. Run `/oh-deliver` and agree on the tasks with the agent.
2. The agent prepares that exact scope and shows you a trigger such as
   `$o-harness:oh-deliver request:<id>`.
3. Type the trigger yourself. That is your approval; the agent cannot approve for you,
   and the approved scope can't grow afterwards.

OH then runs the tasks on a branch (it creates one if you are on `main`). For each task a
fresh worker implements it, your project checks run, an independent reviewer checks the
exact result, blockers get fixed, and the reviewed tree is committed. Workers can't write
OH's state, your settings or Git internals.

A batch has 5 tasks and each task gets up to 3 review rounds by default; change that with
`/oh-config` ([configuration](configuration.md)). If a task still has findings after its review rounds,
OH pauses and lists the choices you can type. At the end of a batch, type **continue**,
**pr** or **stop**. **pr** lets the agent push the branch and open a pull request with the
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

On macOS, `oh service-install` starts the dashboard at <http://localhost:4318> and keeps it
running across logins. Elsewhere, run `oh serve`. See [dashboard and data](analytics.md).
