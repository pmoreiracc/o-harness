# Configuration

Settings live in OH's data folder, never in your repository. Each file below overrides the
one before it, key by key:

1. Built-in defaults (`config/defaults.json` in this repository)
2. `~/.local/share/o-harness/settings/defaults.json`, for all your projects
3. `config.json` in the project's OH folder
4. `config.local.json` in the project's OH folder, for personal overrides

`oh config` prints the effective settings and the project's OH folder. Unknown keys and
out-of-range values are rejected. Set `OH_DATA_HOME` to move the data folder.

Example project `config.json`:

```json
{"tasks_per_batch": 3, "models": {"claude": {"review": {"model": "opus", "effort": "max"}}}}
```

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

Settings are captured when a batch is prepared. Changes apply to the next batch, not to
one already approved.

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
