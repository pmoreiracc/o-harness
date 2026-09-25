# Architecture

| Path | Contents |
|---|---|
| `runtime/oh/` | The OH engine: run state, host adapters, checks, reviews, analytics and the dashboard server |
| `plugins/o-harness/` | The plugin both hosts install: skills, the prompt hook and the launcher |
| `workflows/` | Instructions the plugin skills load for each workflow |
| `prompts/` | The shared independent-reviewer prompt |
| `config/` | Default settings and OH's own invariants |
| `dashboard/` | Static dashboard files, no build step |
| `core/` | Bash parsers for projects that plan with numbered design documents |
| `integrations/` | Test and packaging scripts |
| `.claude/`, `.codex/` | Settings for developing OH itself |

## Install layout

A built plugin contains the engine. On the first OH command, the plugin's launcher copies it
to `~/.local/share/o-harness/versions/<commit>` and marks it active when its version is
newer than the active one. Each run records its version and keeps using it until it ends,
so an update never changes a running batch. Both hosts share the installed engine and the
data folder.

## Authority

Only your own typed message approves work. The prompt hook records where to find it, and
OH confirms it in the host's saved transcript before starting. Model output, elapsed time
and restarts never approve anything. Approved scope is fixed when prepared.

The runner keeps a hash-chained journal per run. For each task it picks a model profile,
starts a fresh worker, runs the checks, starts an independent reviewer on the exact tree
and commits only the reviewed tree, with an `OH-Evidence` trailer. `oh pr-summary` checks
that trailer against every commit on the branch.

Workers run through the checked host CLI with API-key variables removed. They can't write
OH state or Git internals; reviewers are read-only. Pause and stop share a lock with commit,
so a stop never leaves a half-recorded task.

## Data

The SQLite analytics database is rebuilt from saved events and never grants anything.
Backup and restore lock the data folder.

## Not yet supported

- One task runs at a time. Parallel tasks are tracked in
  [issue 1](https://github.com/pmoreiracc/o-harness/issues/1).
- Other hosts need a tested adapter first
  ([issue 4](https://github.com/pmoreiracc/o-harness/issues/4)).
