# Configuration

The easy way: `/oh-config` (Codex: `$oh-config`). With nothing after it, it lists every
setting with its value and meaning. Or say what you want, for example
`/oh-config let OH run 15 tasks per batch`; it shows the change and asks you to confirm.

## Where settings live

A project keeps its settings in one place:

- **`oh.json` in the repository root**, shared with everyone who works on the repo. Its
  `$schema` line makes VS Code, Cursor and JetBrains explain each key, suggest allowed
  values and underline mistakes. OH uses the version in your last commit, so commit a change
  for it to apply.
- **Or privately**, in `config.json` in the project's OH folder, for repos where you don't
  want OH files.

Each layer below overrides the one before it, key by key:

1. Built-in defaults (`config/defaults.json` in this repository)
2. `~/.local/share/o-harness/settings/defaults.json`, for all your projects
3. The project's settings: the committed `oh.json`, or the private `config.json` (never both)
4. `config.local.json` in the project's OH folder, for personal overrides

For example, to let OH run 15 tasks in a row with up to 12 review rounds each:

```json
{
  "$schema": "https://raw.githubusercontent.com/pmoreiracc/o-harness/main/config/oh.schema.json",
  "tasks_per_batch": 15,
  "review_rounds": 12
}
```

From a terminal:

- `oh config` lists every setting with its value, where it comes from, the allowed values
  and its meaning.
- `oh config set <key> <value>` changes a project setting. It creates `oh.json` if you pass
  `--location repo`, or keeps settings private with `--location private`.
- `oh config unset <key>` goes back to the default.

OH checks every settings file each time it reads it. An unknown key, a bad value or broken
JSON stops OH with the file and key named. Settings are captured when a run is prepared, so
a change applies to the next run you start; **continue** keeps the settings the run was
approved with.

OH never commits a change to `oh.json` as part of a task. If the file in the run's checkout
changes while a task or check runs, OH restores the committed version, keeps a copy with the
attempt's evidence and fails that attempt, whoever made the edit. Between attempts, an edit is
restored the same way without failing anything. So change `oh.json` after a run ends.

| Setting | Default | Meaning |
|---|---|---|
| `tasks_per_batch` | 5 | Tasks approved per batch, and per **continue** (1–100) |
| `review_rounds` | 3 | Review rounds each task may use before OH asks you (1–100) |
| `max_escalations` | 1 | Retries on the complex model after a failed attempt, before OH asks you (0–2) |
| `context.handoff_chars` | 12000 | Maximum task handoff text sent to a worker |
| `context.result_chars` | 4000 | Maximum feedback kept in model prompts |
| `context.compact_at_tokens` | 60000 | Codex worker compaction threshold (Codex only) |

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

A project's `checks.json`, in its OH folder, lists the commands that must pass before OH
commits a task:

```json
[
  {"name": "tests", "command": ["npm", "test"]},
  {"name": "lint", "command": ["./scripts/lint.sh"], "when": ["src/**"], "timeout_seconds": 300}
]
```

Commands run without a shell. `when` limits a check to changes matching those paths.
`inputs` and `toolchain` let OH reuse a passing result when nothing relevant changed; leave
them out if you're unsure.
