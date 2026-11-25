# Using OH

This guide covers the full workflow: proposing an idea, designing it, delivering the tasks, handling review findings, pausing and resuming, and publishing the result. For setup, see [Installation and updates](installation.md). For every setting, see [Configuration](configuration.md).

Skills start with `/` in Claude Code and `$` in Codex. The examples below use the Claude form.

| To do this | Run |
|---|---|
| Find ready or saved work | `/oh-start` |
| Propose an idea | `/oh-propose search across my notes` |
| Design a roadmap initiative | `/oh-design auth` |
| Deliver an approved design | `/oh-deliver 0005` |
| Prepare a quick fix | `/oh-deliver fix the sign-in timeout` |
| Review your current changes | `/oh-review changes` |
| See or change settings | `/oh-config` |
| Pause the current run | `/oh-pause` |
| Continue saved work | `/oh-resume` |

## How approvals work

OH asks before it changes your plans, before it writes code, and before it publishes. Each approval covers exactly what it shows you:

- Running `oh-propose` or `oh-design` lets OH draft planning documents. It doesn't let OH write product code.
- Delivery starts only after you approve its scope: an approved design, or the task list of a quick fix.
- Publishing a PR needs its own approval.

Questions appear in your host's native menus, or in chat when a menu isn't available. Only your answer counts as approval. Agent reports and agent text never approve anything.

## Propose an idea

```text
/oh-propose search across my notes
```

`oh-propose` reads your roadmap, designs, decision records and code, explains what it understood, and recommends one route:

- A new roadmap initiative, with its milestone and dependencies.
- A task in an approved design.
- An improvement to existing behavior that needs no planning document.
- A question, when the idea or where it belongs is unclear.

Before it changes any planning document, OH shows the complete additions and where they go. You can approve them, refine them in your own words, or keep the recommendation without saving it. After you approve, OH writes and checks the additions, and a fresh reviewer agent challenges the routing, dependencies and project requirements. OH repairs any blocking finding before it finishes.

An improvement or an open question finishes with the recommendation. It doesn't create a document.

## Design an initiative

```text
/oh-design auth
```

`oh-design` writes the design doc for one roadmap initiative: the approach, numbered tasks in order, their dependencies and acceptance checks. A fresh reviewer agent then challenges the document. Planning checks the documents; it doesn't run your product's tests.

If an open product question would change the approach, OH lays out the alternatives and its recommendation, and the decision stays with you.

The first time you plan in a project, OH asks **Where should OH keep this project's plans?** and shows both paths:

- **Keep plans in the repository** commits roadmaps, designs and decision records to your repo through normal branches and pull requests. A design becomes approved when you merge its PR.
- **Keep plans in the private folder** keeps them in `~/oh-plans/<project name>/`, outside your checkout. You approve a private design directly, with no commit or PR.

OH then continues with the request you started. Any later edit to an approved design gets a fresh review and your approval before delivery uses it. To change the location later, see [Plans](configuration.md#plans).

Running `oh-propose` or `oh-design` with no argument asks for the idea or initiative in chat.

## Deliver an approved design

```text
/oh-deliver 0005
```

The number identifies the design. You can also say "Deliver approved design 0005". Add a track name, as in `/oh-deliver 0005 core`, to deliver only that track.

OH picks the lowest-numbered task that's ready, works through tasks one at a time, and waits for each task's prerequisites. With no argument, `oh-deliver` first shows any unfinished delivery and asks whether to resume it. Otherwise it lists the designs that are ready.

For each task:

1. A fresh assessment agent reads the task and the relevant code and rates it **simple**, **standard** or **complex**. That rating selects the model and effort for the work. See [Models](configuration.md#models).
2. A fresh implementation agent builds the task, updates the documentation it affects, reviews its own work and runs your project's checks. It repairs routine check failures within the same task.
3. A fresh reviewer agent reviews the exact result that passed the checks.
4. Blocking findings go back for repair and another independent review. When the review is clean, OH records the task as done and commits the reviewed code.

The last task's review covers the whole branch, including how its tasks work together. Agents receive the current task and references to earlier evidence, so full transcripts don't pile up in your chat.

Your host keeps control of command permissions, including network and Docker access. Reviewer agents work under a no-edit rule: if the subject changes during a review, the review no longer counts.

## Quick fixes

```text
/oh-deliver fix the sign-in timeout
```

For a change that doesn't need a design, describe it. OH prepares a short task list and shows it with its task and review limits. Approve it where your host shows plans:

- In Claude Code, **Accept** in the plan viewer.
- In Codex Plan mode, **Implement**.
- In a menu or in chat, **Approve fix** (or **Approve N tasks**). **Stop and take over** declines it.

Refine the proposal before you approve if it includes too much or leaves something out. The scope includes any uncommitted edits or unreviewed commits it will finish, and the preview lists them. Edits made by other people are kept as they are.

## Findings and review rounds

The approved scope stays fixed. If fixing a login timeout reveals a logout problem, OH records the logout problem and keeps building only what you approved.

| Finding | What happens |
|---|---|
| Blocking | Repaired, then reviewed again by a fresh reviewer. |
| Concern | You choose **Fix concerns** or **Accept concerns**. |
| Outside the task's scope | Saved as a follow-up in the workflow record. It doesn't block the task. |

When OH reports or continues the work, it shows the saved follow-ups. You can ask the agent to open or link a GitHub issue, keep the follow-up, or add a note to a related design. A note is future work, not a new approved task.

Each task has a set number of review rounds, 3 by default. When a task has used them, OH asks before another review starts, with an option such as **Allow 2 additional review rounds**. Retries, restarts and switching hosts don't add rounds.

If the same blocking problem appears in two independent reviews, OH moves the repair to the **complex** profile.

## Batches

OH works through a batch of tasks, 5 by default, without stopping between them. Each scope preview states what it covers, for example "First batch: 5 tasks. Up to 3 independent reviews per task before human renewal." At the end of each batch, OH shows what was completed and asks what to do next:

- **Start tasks …** runs the next batch.
- **Open PR to `<owner>/<repo>` → `<base>`** publishes the reviewed work.
- **Stop and take over** ends OH's work and leaves your files and commits as they are.

Change the batch size and review rounds with `/oh-config`. A change applies to the next run you start; a running batch keeps the settings it was approved with.

## Ask for a review

```text
/oh-review changes
```

`oh-review` starts a fresh reviewer agent on any of these subjects:

| Subject | Reviews |
|---|---|
| `changes` or `tree` | Your current working tree, including uncommitted changes, against `HEAD` |
| `paths <relative paths>` | Specific files or folders |
| `commit <ref>` | One commit |
| `range <base> <head>` | A range of commits |
| `task <id>` | A completed delivery task that isn't published yet |

Reviewing a commit or range reads that revision without switching your branch. If the review finds something to fix, OH can turn the findings into a quick-fix scope for your approval. Add `--feedback-only` to get the report without a repair offer.

`task <id>` uses the task's saved scope and remaining review rounds. A clean result returns you to the batch decision. Blocking findings go through the normal repair and review cycle and produce a correction commit, and OH waits for that correction before it publishes.

## Pause, stop and resume

`/oh-pause` lets the current step finish, saves its result, and stops before the next one.

To stop immediately, use your host's Stop button. OH stops the commands it started and blocks the stopped agent from running further tools. In Codex, a child agent may keep running until it finishes; see [Known limits](known-limits.md).

To continue, run the same command again in this conversation or a new one, or run `/oh-resume`. Before OH prepares new work, it checks for saved work. When it finds some, it asks whether to resume it, with **Resume saved work**, **Stop and take over** and, when available, **Start fresh**. Nothing continues until you answer. You don't need to repeat your original wording, and a clearly different request never picks up an old task by accident.

Resumed work keeps its original scope, settings, findings and remaining review rounds. You can continue from a new session or the other host, on the same checkout.

When a delivery needs recovery, for example after a stop in the middle of a task, OH names the branch and affected paths and offers three choices:

- **Continue** keeps the existing changes and finishes the approved delivery.
- **Discard local work on `<branch>` and restart at `<base>`** (Start fresh) discards the affected local changes and the branch's unmerged work. It makes no backup.
- **Stop and take over** ends OH's work and leaves the files unchanged.

Review rounds used and findings stay recorded whichever you choose.

## Publication

You decide whether reviewed work is published and where. Publication approval covers the exact reviewed commit and destination. If a PR for the work already exists, OH updates it instead of opening a duplicate.

The result explains what changed, which checks ran, the review rounds and findings, and links the commit, document or PR. After publishing, the agent follows CI on the PR until it has a result. Pending, missing, failed, cancelled or skipped checks don't count as a pass.

When CI fails, the agent reports a short diagnosis and offers to prepare a fix for the same PR (**Approve fix**), to re-run the failed jobs (**Re-run failed checks**) when the evidence supports it, or to stop (**Stop and take over**). A fix goes through its own scope approval, checks and fresh review.

You merge. You can also keep coding, committing and opening PRs without OH.

## Projects and checkouts

The first OH command in a repository registers it with `oh init`. Registration writes nothing to your repository; settings, checks and evidence live in OH's own folders.

| Option | Use it to |
|---|---|
| `oh init --name <name>` | Choose the project name |
| `oh init --attach <project-id>` | Add another worktree of a registered project |
| `oh init --reattach <checkout-id>` | Reconnect a checkout you moved |
| `oh init --replace` | Register a new checkout at an old path, starting fresh |

A registration follows the repository's Git identity, so reboots, commits, branch switches and remote URL changes keep it. Registrations from older OH versions upgrade automatically and keep their IDs, saved work and spent review rounds.

New work starts from the base branch, which OH detects from `origin/HEAD`, then `main`, then `master`. Set another with `oh config set base_branch develop`.

OH keeps work in the checkout you selected and switches branches in that folder. It doesn't create extra worktrees or clones. When it needs to switch, it saves your staged, unstaged and untracked changes in a Git stash labelled `OH workspace`, plus a backup outside the repository, and restores them when you return. It never pops or removes your stashes.

## Command-line helpers

With the `oh` command on your `PATH` (see [Installation](installation.md#install)):

| Command | What it does |
|---|---|
| `oh status` | Shows saved workflow facts without starting an agent |
| `oh verify [base] [review\|pre-push\|ci]` | Runs the project's checks |
| `oh config` | Shows effective settings and where each comes from |
| `oh plans list` | Shows each initiative's design and approval status |

On native Windows, a check registered as bare `bash` runs native Bash, such as Git Bash. Use `wsl` or an explicit interpreter when the check needs it.

The [dashboard](analytics.md) shows scope, tasks, checks, attempts, findings and decisions for every run.
