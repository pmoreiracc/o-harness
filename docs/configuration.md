# Configuration

The quickest way to see or change a setting is `/oh-config` (Codex: `$oh-config`). With nothing after it, it lists every setting with its value and meaning. Or say what you want:

```text
/oh-config let OH run 15 tasks per batch
```

OH shows the change and applies it. If the request leaves a real choice open, the agent asks.

## Settings file

All settings live in one file outside your repositories:

```text
~/.config/o-harness/settings.json
```

With an absolute `XDG_CONFIG_HOME`, the file is `$XDG_CONFIG_HOME/o-harness/settings.json`. An installation with its own `OH_DATA_HOME` keeps a separate file at `<OH_DATA_HOME>/config/settings.json` and never reads or changes yours. OH creates the file when you register your first project. `oh config open` opens it.

Settings apply in three layers. Each layer overrides the one before it, key by key:

1. OH's defaults (`config/defaults.json` in this repository).
2. Your top-level settings, for every project.
3. The project's section, `projects.<name>`, which also holds its checks.

```json
{
  "$schema": "./settings.schema.json",
  "models": {"claude": {"review": {"effort": "max"}}},
  "projects": {
    "my-app": {
      "tasks_per_batch": 15,
      "review_rounds": 12,
      "checks": [{"name": "tests", "command": ["npm", "test"]}]
    }
  }
}
```

Set only what you want to change. Everything else follows OH's defaults, so improved defaults in a new release reach you automatically. The `$schema` line points to a schema OH writes next to the file for the running version, so VS Code, Cursor and JetBrains editors describe each key, suggest allowed values and flag mistakes.

OH validates the whole file each time it reads it. An unknown key, an invalid value, a duplicate key or broken JSON stops OH with the file and the exact key named, such as `projects.my-app.review_rounds`. OH also records where your settings live. If a process looks somewhere else, for example a host that doesn't see the `XDG_CONFIG_HOME` your shell sets, OH stops and says so instead of falling back to defaults.

## Change settings from the command line

| Command | Effect |
|---|---|
| `oh config` | Lists every setting with its value, source, allowed values and meaning, plus this project's checks |
| `oh config set <key> <value>` | Sets the value for this project |
| `oh config set <key> <value> --global` | Sets the value for every project |
| `oh config unset <key> [--global]` | Returns to the value from the layer below |
| `oh config open` | Opens `settings.json` in your editor |

A value that starts with `@` is read from a file, for example `oh config set checks @checks.json`.

OH captures settings when a run is prepared, so a change applies to the next run you start, including in the same chat. A running batch and its **continue** checkpoints keep the settings the run was approved with.

## Settings reference

| Setting | Default | Allowed values | What it controls |
|---|---|---|---|
| `tasks_per_batch` | `5` | 1–100 | Tasks one approval covers. Each **continue** approves this many more. |
| `review_rounds` | `3` | 1–100 | Review rounds a task may use before OH asks you |
| `base_branch` | empty | branch name | Branch new work starts from and PRs target. Empty detects `origin/HEAD`, then `main`, then `master`. |
| `plans.location` | `ask` | `ask`, `repo`, `private` | Where roadmaps, design docs and decision records live |
| `plans.private_folder` | `~/oh-plans` | absolute or `~/` path | Parent folder for private plans. Each project gets a subfolder named after it. |
| `plans.roadmap` | `docs/roadmap.md` | relative `.md` path | Roadmap file, relative to where plans live |
| `plans.designs` | `docs/design` | relative path | Design docs folder |
| `plans.decisions` | `docs/decisions` | relative path | Decision records (ADRs) folder |
| `models.<host>.<profile>.model` | see [Models](#models) | model name | Model for a profile |
| `models.<host>.<profile>.effort` | see [Models](#models) | see [Models](#models) | Reasoning effort for a profile |
| `context.handoff_chars` | `12000` | 1000–100000 | Maximum task context sent inline to an agent. Full scope and evidence are passed by reference. |
| `context.result_chars` | `4000` | 1000–100000 | Maximum feedback text kept in agent prompts |
| `checks` | none | list | Commands that must pass before OH commits a task. See [Checks](#checks). |

`<host>` is `claude` or `codex`. `<profile>` is `simple`, `standard`, `complex`, `review` or `insights`.

## Models

Before each delivery task, a fresh read-only assessment agent, using the `standard` profile, reads the task and the relevant code and rates it **simple**, **standard** or **complex**. When it's uncertain, it picks complex. The implementation agent then uses that profile's model and effort. The rating carries over to repairs and to resumed work. Reviews use the `review` profile.

| Profile | Used for | Claude | Codex |
|---|---|---|---|
| `simple` | Small, bounded tasks | `haiku` / `high` | `gpt-6-luna` / `high` |
| `standard` | Ordinary tasks, and task assessment | `sonnet` / `medium` | `gpt-6.1-sol` / `medium` |
| `complex` | Cross-cutting or safety-sensitive tasks, and repairs after the same blocking finding appears in two reviews | `opus` / `high` | `gpt-6-astra` / `high` |
| `review` | Independent reviews | `opus` / `high` | `gpt-6.1-sol` / `high` |
| `insights` | Dashboard analysis, which is off in v1.0 | `opus` / `high` | `gpt-6-astra` / `high` |

Effort values are `low`, `medium`, `high`, `xhigh` and `max` for Claude, plus `ultra` for Codex.

These profiles set the agents OH starts. The model of the chat you're talking to stays whatever you selected in your host.

OH checks that the model and effort are available before it starts each agent. If your Codex CLI doesn't list the configured model, OH uses the newest earlier version of the same model family that supports the requested effort, for example `gpt-6-sol` for `gpt-6.1-sol`, and tells you, with the update command and `$oh-config`. Your saved settings don't change. If no compatible model exists, OH stops with a recovery step. It never switches to another model family or to paid API calls.

## Checks

A project's `checks` are the commands that must pass before OH commits a task. Set them with `oh config set checks '<JSON list>'`, which replaces the whole list:

```json
[
  {"name": "tests", "command": ["npm", "test"]},
  {"name": "lint", "command": ["./scripts/lint.sh"], "when": ["src/**"], "timeout_seconds": 300}
]
```

| Field | Required | What it does |
|---|---|---|
| `name` | yes | Name shown in results |
| `command` | yes | Program and arguments, run from the repository root without a shell. `{base}` and `{mode}` are replaced. |
| `when` | no | Runs the check only when a changed path matches one of these patterns |
| `inputs` | no | Repository paths whose contents decide whether a passing result can be reused |
| `toolchain` | no | Version commands whose output also decides reuse, such as `["node", "--version"]` |
| `modes` | no | When the check runs: `review`, `pre-push`, `ci`. All of them by default. |
| `timeout_seconds` | no | Seconds before the check is stopped. 900 by default. |

Leave out `inputs` and `toolchain` if you're unsure. Without `inputs`, OH reuses a passing result only when nothing in the checkout changed.

`oh verify` runs the checks by hand. A cancelled or timed-out check counts as failed even if its cleanup exits with `0`. OH skips the remaining checks, and the task doesn't move on to review or commit. Results keep the real exit code and the reason.

Every check keeps its complete stdout and stderr in OH's data folder under `verification/<project-id>/logs/`, with byte counts and SHA-256 hashes. Agents see a bounded excerpt and a reference to the full log, so a noisy check can't hide its original error. Logs stay after failures, timeouts and cancellations. They can contain source code, so keep them out of public issues and PRs.

A delivery keeps the checks it started with. See [Known limits](known-limits.md) for correcting a check environment mid-delivery.

## Plans

`plans.location` decides where planning documents live:

- `repo` commits them to the repository, through normal branches and PRs.
- `private` keeps them in `~/oh-plans/<project name>/`, outside the checkout. The `plans.roadmap`, `plans.designs` and `plans.decisions` paths apply inside that folder.
- `ask` asks the first time you plan in the project.

| Command | Shows |
|---|---|
| `oh plans path` | Where this project's plans live |
| `oh plans check` | Whether the roadmap and design docs follow their rules |
| `oh plans list` | Each initiative's design and approval status |

Each private folder belongs to one project, including after a rename, and OH won't take over an existing folder it doesn't own. Pick another project name or `plans.private_folder` instead.

`oh backup` covers OH's data, not `~/oh-plans`. Include your private plans folder in your regular backups.

## Projects

A project's section in `projects` is named after the project, as named at `oh init`. Each repository gets its own name, and worktrees of the same repository share their project's section.

- `oh rename <new name>` renames a project and its section. OH refuses a name whose section already holds other settings.
- When `oh init` finds a section left by an earlier project with the same name, it tells you which of its settings apply.
- `oh config` names the project an unregistered checkout would join.

## Share a project setup

```sh
oh profile-export ~/my-app-profile.json
oh profile-import ~/my-app-profile.json --name my-app
```

An export contains the project profile, its effective settings and its check definitions. It never includes sessions, credentials, evidence, approvals or private plan documents. Export to a new file outside the checkout.

Import into an unregistered checkout. OH registers it and keeps only the settings that differ from yours, so your own settings and later defaults still apply.

## Updates and older settings

Updates never rewrite your settings silently. When a release renames or removes a setting, OH moves it once and saves the previous file in `backups/` next to `settings.json`. Settings files from older OH versions (`checks.json`, `config.json`, `config.local.json` and `settings/defaults.json`) move into `settings.json` the same way, and each project keeps its values. If OH can't move a value, it leaves that file in place and stops only the affected project, naming the reason.

Recent moves:

- `models.<host>.orchestrator` became `models.<host>.insights`. The old names still work with `oh config set` and `unset` and in older exported profiles.
- `max_escalations` and `context.compact_at_tokens` were removed. Agent context compaction follows your host's settings.

`oh backup` includes `settings.json`. Use `oh config set` and `unset` for changes; OH's agents are instructed not to edit settings by hand.
