# Configuration

OH loads `config/defaults.json`, then the consumer's `.oh/config.json`, then ignored
`.oh/config.local.json`. Overrides merge by key; unknown keys and invalid limits are
rejected. Run `.oh/oh config` to inspect the effective values. Settings contain no secrets.

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
| `context.compact_at_tokens` | 60000 | Codex compaction threshold configured by discovery/worker adapter |

Claude defaults to haiku/high for simple work, sonnet/medium for standard work, and
opus/high for complex work, review and coordination. These are adapter profiles, not
promises that every installed host or subscription offers every model or effort.
Unsupported requests fail visibly. Claude's native compaction remains host-managed;
OH does not claim to enforce the Codex token threshold on Claude.

Difficulty is assigned before execution by a versioned rubric: bounded editorial work is
simple; cross-cutting or safety-sensitive work is complex; other work is standard.
The label and reason are retained. Failures do not relabel tasks to improve metrics.

Preparation snapshots settings. Changes apply to a newly prepared run, not to an existing
human grant. Continue uses the retained batch count. Run `configure-hosts` when changing
coordinator/reviewer discovery defaults; an already open host conversation may retain its
current settings until restarted. Child profiles come from the run snapshot.

Required verification belongs in `.oh/checks.json`: a list of named command arrays with
optional input paths, toolchain probes and affected-path patterns. Commands run without a
shell unless an explicit shell is in the array. Successful checks are reused only for the
same declared inputs and environment fingerprint. Unknown dependencies should use `.`.
Do not select a narrow input set merely to gain cache hits.

`OH_DATA_HOME` can relocate local state; the default is `~/.local/share/o-harness`.
`OH_HOME` is an optional installation override, still checked against the exact clean
committed pin. Neither variable grants task authority.
