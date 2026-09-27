# Configuration

The easy way: `/oh-config` (Codex: `$oh-config`). With nothing after it, it lists every
setting with its value and meaning. Or say what you want, for example
`/oh-config let OH run 15 tasks per batch`; it shows the change and asks you to confirm.

## Your settings file

All your settings live in one file that belongs to you: `~/.config/o-harness/settings.json`
(or `$XDG_CONFIG_HOME/o-harness/settings.json`). OH creates it when you register a project,
and never puts anything in your repositories. `oh config open` opens it. If you run OH with
its own data folder (`OH_DATA_HOME`), that folder keeps its own settings in
`<OH_DATA_HOME>/config/settings.json`, so it never reads or changes yours.

OH remembers where your settings are. If a process looks elsewhere, for example a host that
doesn't see the `XDG_CONFIG_HOME` your shell sets, or the file disappears, OH stops and says
so instead of using its defaults. `oh config open` or `oh config set` starts a new file.

Top-level values apply to every project. A project's section under `projects`, named as you
named the project at `oh init`, overrides them for that project and holds its checks:

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

Leave out anything you don't want to change: OH's defaults fill the rest, so a better
default in a new release still reaches you. The `$schema` line makes VS Code, Cursor and
JetBrains explain each key, suggest allowed values and underline mistakes.

Each layer overrides the one before it, key by key:

1. OH's defaults (`config/defaults.json` in this repository)
2. Your top-level settings, for every project
3. The project's section, `projects.<name>`

A section belongs to one project, so two projects can't have the same name: `oh init` asks
for another one, except in a checkout of that project's Git repository (a worktree, or a
worktree recreated at its old path with `--replace`), which joins that project; `oh config`
in an unregistered checkout names the project it would join. A registration whose checkout
was deleted, recreated or restored from a copy doesn't hold its name.
`oh rename <new name>` renames a project and its section; it refuses a name whose section
already holds other settings. If a section is left from an earlier project with that name,
`oh init` says which settings in it apply.

## Changing settings

- `oh config` lists every setting with its value, where it comes from, the allowed values
  and its meaning, plus this project's checks.
- `oh config set <key> <value>` changes this project's value; add `--global` to change it
  for every project.
- `oh config unset <key>` (optionally `--global`) goes back to the value from the layer before.
- `oh config open` opens the file, if you prefer to edit it yourself.

OH checks the whole file each time it reads it. An unknown key, a bad value, a key written
twice or broken JSON stops OH with the file and the exact key named, such as
`projects.my-app.review_rounds`.
Settings are captured when a run is prepared, so a change applies to the next run you start;
**continue** keeps the settings the run was approved with. Each prepared approval and each
**continue** checkpoint repeats the numbers it covers, for example "Runs 5 of 12 tasks, then
asks you to continue, up to 3 review rounds each".

Updates never rewrite your settings. If a release renames or removes a setting, OH moves it
for you once and keeps the previous file in `backups/` next to `settings.json`. Settings
files from older versions of OH (`checks.json`, `config.json` and `config.local.json` in a
project's OH folder, and `settings/defaults.json`) are moved into `settings.json` the same
way, and each project keeps the values it had. A file OH can't move (a value it doesn't
accept, or a value its section already sets differently) stays where it is and stops only
its own project (the shared `settings/defaults.json` stops every project), with the reason
named. Projects registered under the same name before this version stop until you give one
of them another name with `oh rename`. Files of registrations that were replaced, or of
deleted checkouts whose name another project now uses, are kept in `backups/` without being
applied.

Workers can't write the settings folder. `oh backup` includes `settings.json`.

| Setting | Default | Meaning |
|---|---|---|
| `tasks_per_batch` | 5 | Tasks approved per batch, and per **continue** (1–100) |
| `review_rounds` | 3 | Review rounds each task may use before OH asks you (1–100) |
| `max_escalations` | 1 | Retries on the complex model after a failed attempt, before OH asks you (0–2) |
| `context.handoff_chars` | 12000 | Maximum task handoff text sent to a worker |
| `context.result_chars` | 4000 | Maximum feedback kept in model prompts |
| `context.compact_at_tokens` | 60000 | Codex worker compaction threshold (Codex only) |
| `plans.location` | ask | Where roadmaps, design docs and decisions live: `repo` (committed in the repository) or `private` (OH's folder) |
| `plans.private_folder` | ~/oh-plans | Parent of visible private project plan folders; absolute or home-relative |
| `plans.roadmap` | docs/roadmap.md | Roadmap file, relative to where plans live |
| `plans.designs` | docs/design | Design docs folder |
| `plans.decisions` | docs/decisions | Decision records (ADRs) folder |

`oh plans path` shows where a project's plans live; `oh plans check` checks the roadmap and
design docs against their rules. `oh plans list` shows each initiative's design and approval
status. New private plans live at `~/oh-plans/<project name>/`; the relative document paths
above apply inside that folder. Renaming a project preserves its existing document folder.
Private plans from older installations remain at their existing OH state path; `plans path`
is authoritative. `init --replace` preserves that document location but creates fresh checkout
authority. Profile export excludes private documents and approvals explicitly; copy those
documents separately when moving machines and review them again. `oh backup` covers OH state,
not the external `~/oh-plans` folder: include your visible plan folder in your regular backups.

## Models

OH labels each task **simple**, **standard** or **complex** before it starts, then picks
that profile's model. Reviews and the coordinating session have their own profiles.

| Profile | Claude | Codex |
|---|---|---|
| simple | haiku / high | gpt-5.6-luna / high |
| standard | sonnet / medium | gpt-5.6-sol / medium |
| complex | opus / high | gpt-6-astra / high |
| review | opus / high | gpt-5.6-sol / high |
| orchestrator | opus / high | gpt-6-astra / high |

If your subscription doesn't offer a model or effort, the task fails with a clear error;
OH never switches to paid API calls. OH doesn't change the model of the session you are
talking to; the orchestrator profile is only a recommendation for it.

## Checks

A project's `checks` list the commands that must pass before OH commits a task. Set them
with `oh config set checks '<JSON list>'`, which replaces the whole list:

```json
[
  {"name": "tests", "command": ["npm", "test"]},
  {"name": "lint", "command": ["./scripts/lint.sh"], "when": ["src/**"], "timeout_seconds": 300}
]
```

Commands run without a shell. `when` limits a check to changes matching those paths.
`inputs` and `toolchain` let OH reuse a passing result when nothing relevant changed; leave
them out if you're unsure. `modes` picks when a check runs (`review`, `pre-push`, `ci`).
