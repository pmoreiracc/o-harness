<div align="center">

<img src="docs/assets/oh-on-dark.svg" alt="o-harness" width="300">

<h1>o-harness</h1>

<p>In Portuguese, <em>o</em> means <em>the</em>.<br>
<strong>O harness. The harness.</strong><br>
A small Brazilian signature. Call it <strong>“oh.”</strong></p>

</div>

o-harness (OH) is a workflow plugin for Claude Code and Codex. It takes a software idea through planning and into reviewed, committed code, using fresh agents for each step and stopping for your approval at defined points.

## How it works

You start with an idea. `oh-propose` reads your roadmap, designs and code, and recommends where the idea belongs: a new roadmap initiative, a task in an existing design, or a small improvement. Nothing is added to your plans until you approve it.

`oh-design` turns one roadmap initiative into a design doc with the approach, numbered tasks in order, their dependencies and acceptance checks. A fresh reviewer agent challenges the document before you approve it.

`oh-deliver` implements the approved tasks one at a time. A fresh agent builds each task and runs your project's checks, then a separate reviewer agent reviews the result. Blocking findings go back for repair, and only reviewed work is committed.

OH works through a batch of tasks on its own, 5 by default. It stops for you when the scope needs approval, when a finding needs your decision, when a task has used its review rounds (3 by default), and at the end of each batch, where you choose to continue with the next batch, open a PR or stop.

## Requirements

- macOS or Linux. Native Windows 11 (64-bit) is in preview.
- Python 3.12+ and Git.
- Claude Code signed in with a Claude subscription, or Codex signed in with ChatGPT. API-key logins aren't supported.

## Install

**Claude Code**

```sh
claude plugin marketplace add pmoreiracc/o-harness#dist
claude plugin install o-harness@o-harness
```

**Codex**

```sh
codex plugin marketplace add pmoreiracc/o-harness --ref dist
codex plugin add o-harness@o-harness
```

## Quick start

Open a new session in your project and give OH an idea:

```text
/oh-propose Add search to my notes app. Keep it simple.
```

In Codex, skills start with `$` instead of `/`, as in `$oh-propose`. On first use, OH registers your project, asks where your plans should live, and then continues with your request. Building starts when you run `oh-deliver`.

## Skills

| Skill | Claude Code | Codex | What it does |
|---|---|---|---|
| `oh-start` | `/oh-start` | `$oh-start` | Finds ready or saved work and helps you pick the workflow to use next. |
| `oh-propose` | `/oh-propose <idea>` | `$oh-propose <idea>` | Routes an idea to a roadmap initiative, a task in an approved design, or an improvement. |
| `oh-design` | `/oh-design <initiative>` | `$oh-design <initiative>` | Turns one roadmap initiative into a reviewed design doc with numbered tasks. |
| `oh-deliver` | `/oh-deliver 0005` | `$oh-deliver 0005` | Delivers the tasks of an approved design. Given a description instead, such as `fix the sign-in timeout`, it scopes and delivers a quick fix. |
| `oh-review` | `/oh-review changes` | `$oh-review changes` | Runs a fresh, independent review of your changes, a path, a commit, a range or a completed task, and can fix what it finds. |
| `oh-config` | `/oh-config` | `$oh-config` | Shows your settings, or changes one when you say what you want. |
| `oh-pause` | `/oh-pause` | `$oh-pause` | Pauses the current run at the end of its current step, keeping its results. |
| `oh-resume` | `/oh-resume` | `$oh-resume` | Picks up saved work or a pending decision where it left off, in the same session or a new one. |
| `oh-update` | `/oh-update` | `$oh-update` | Updates OH to the latest release in Claude Code and Codex and reports the versions. |

Arguments and full behavior for every skill are in [Using OH](docs/usage.md).

## Configuration

Run `/oh-config` (Codex: `$oh-config`) to see every setting, or say what you want, for example `/oh-config let OH run 15 tasks per batch`. Settings live in `~/.config/o-harness/settings.json`, outside your repository, and can be set for all projects or per project.

| Setting | Default | What it controls |
|---|---|---|
| `tasks_per_batch` | 5 | Tasks approved per batch, and per **continue** (1–100) |
| `review_rounds` | 3 | Review rounds each task may use before OH asks you (1–100) |
| `models.<host>.<profile>` | see docs | Model and effort for `simple`, `standard` and `complex` tasks, and for `review` |
| `plans.location` | ask | Where roadmaps, design docs and decisions live: `repo` or `private` (`~/oh-plans/<project>`) |

OH labels each task simple, standard or complex before it starts and uses that profile's model and effort. See [Configuration](docs/configuration.md) for checks, all settings and the default models.

## Updating

Run `/oh-update` (Codex: `$oh-update`). It updates OH in every installed host and reports the old and new versions. Your saved work and settings carry over, and the new version runs from your next session. In Codex, review and trust the updated OH hooks in `/hooks`. Claude Code auto-update and other options are in [Installation and updates](docs/installation.md#update).

## Known limits

- Native Windows 11 workflows are in preview ([Windows notes](docs/installation.md#windows)).
- In Codex, a child agent that is already running when you stop a run can continue until it finishes ([#81](https://github.com/pmoreiracc/o-harness/issues/81)).
- OH reports the GitHub checks on a published PR. Review threads, including security-app comments, stay on GitHub ([#176](https://github.com/pmoreiracc/o-harness/issues/176)).

The full list is in [Known limits](docs/known-limits.md).

## Documentation

- [Using OH](docs/usage.md): workflows, approvals, findings, pause and resume, publication
- [Installation and updates](docs/installation.md): requirements, Windows, update, uninstall
- [Configuration](docs/configuration.md): settings file, checks, models, plans
- [Known limits](docs/known-limits.md): current host and workflow boundaries
- [Dashboard](docs/analytics.md): local dashboard at `localhost:4318`
- [Architecture](docs/architecture.md): how OH is built
- [Changelog](CHANGELOG.md)

## Contributing

If you build with agents, come build this with me. Open an [issue](https://github.com/pmoreiracc/o-harness/issues) to report a bug or propose a feature; [CONTRIBUTING.md](CONTRIBUTING.md) explains what to include. Report security problems privately through [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
