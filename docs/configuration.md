# Configuration

OH loads packaged `config/defaults.json`, then external `settings/defaults.json`, then
`projects/<id>/config.json` and `projects/<id>/config.local.json` under the OH data home.
Overrides merge by key; unknown keys and invalid limits are rejected. `oh config` shows
effective values, precedence, version and the external profile directory. No configuration
file is required in a product repository. Settings contain no credentials.

```json
{
  "tasks_per_batch": 5,
  "review_rounds": 3,
  "models": {
    "codex": {
      "simple": {"model": "gpt-5.6-luna", "effort": "high"},
      "standard": {"model": "gpt-5.6-sol", "effort": "medium"},
      "complex": {"model": "gpt-6-astra", "effort": "high"},
      "review": {"model": "gpt-5.6-sol", "effort": "high"},
      "orchestrator": {"model": "gpt-6-astra", "effort": "high"}
    }
  }
}
```

| Setting | Default | Meaning |
|---|---|---|
| `tasks_per_batch` | 5 | Same finite count for the initial batch and each continue |
| `review_rounds` | 3 | Pre-approved independent review rounds per task |
| `max_escalations` | 1 | Bounded worker escalation allowance; not extra task or review authority |
| `context.handoff_chars` | 12000 | Bound for selected task handoff text |
| `context.result_chars` | 4000 | Bound for feedback retained in model prompts |
| `context.compact_at_tokens` | 60000 | Codex compaction threshold configured for fresh Codex workers |

Claude defaults to haiku/high for simple work, sonnet/medium for standard work, and
opus/high for complex work, review and coordination. These are adapter profiles, not
promises that every installed host or subscription offers every model or effort.
Unsupported requests fail visibly. Claude's native compaction remains host-managed;
OH does not claim to enforce the Codex token threshold on Claude.

Difficulty is assigned before execution by a versioned rubric: bounded editorial work is
simple; cross-cutting or safety-sensitive work is complex; other work is standard.
The label and reason are retained. Failures do not relabel tasks to improve metrics.

Preparation snapshots settings. Changes apply to newly prepared work; continue and
resume retain existing allowances. Child models and effort are automatic. The orchestrator
profile describes the desired parent configuration; OH does not change an open conversation's
model. Keep that conversation small by letting the native runner own the task loop.

Required verification belongs in external `projects/<id>/checks.json`: named command
arrays with optional input paths, toolchain probes and affected-path patterns. Commands
run without a shell unless one is explicit. Reuse requires the same inputs, toolchain and
environment. Omit inputs when dependencies are unknown; avoid unjustified narrow caches.

`OH_DATA_HOME` relocates state; the default is `~/.local/share/o-harness`. Upgrades select a
new installed revision for new work. Existing runs keep their recorded revision. Settings,
evidence, host trust and registry are private local data, not files to commit.
