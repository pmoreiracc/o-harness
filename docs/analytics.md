# Dashboard and data

The dashboard at <http://localhost:4318> shows recorded deliveries, review rounds, elapsed
task time, agent time and token observations. It reads OH's local analytics index and works
offline.

## Start the dashboard

On macOS and Windows, `oh service-install` starts the dashboard at login and keeps it running.
`oh service-uninstall` removes it. On Linux, run `oh serve`, or run it under your own service
manager. The dashboard service also collects new observations. Run `oh collect` for a single pass.

## Views

| View | Shows |
|---|---|
| **Overview** | Collector health, delivery and review metrics, trends, and the seven most recent indexed tasks in the period |
| **Tasks** | All matching indexed tasks. Open a task to see its available attempts, checks, and review outcomes. Filter by work, difficulty, version, model, or phase and compare deliveries with a previous period, custom dates, or another version. |
| **Data health** | Collector status, last observation, recorded collection gaps, last invalid-record batch, usage coverage, observed CI results, and suggestions saved by earlier versions |

Choose a project and a calendar range from the top bar. Dates are grouped in UTC. Charts group
ranges longer than 45 days by month.

## Measures

| Measure | What it means |
|---|---|
| **Tasks delivered** | Completed tasks among the tasks that started in the selected dates. The delivery chart groups all recorded completions by their finish dates. |
| **Review rounds per task** | Recorded review attempts for delivered tasks with a completion count. |
| **Time per task** | Average elapsed time for timed, delivered tasks. If a recorded duration is unavailable, OH uses the indexed task start and finish. Elapsed time can include time spent waiting for a decision. |
| **Agent time** | Duration recorded for individual attempts, grouped by step and model. Coverage counts identify partially timed groups. |
| **Observed tokens** | Input plus output the host reported. Cached input is part of input. Days with incomplete components are omitted from the stacked usage chart. |
| **Usage coverage** | Share of worker attempts started in the period whose indexed usage observations include input and output. The usage chart groups observations by the day the host reported them. |
| **Delivery token costs** | Indexed delivery runs started in the selected period, with observed worker, coordinator, and publication subtotals. A verified total requires complete native evidence through publication. Older or incomplete runs may show partial observations. |
| **Tokens per delivered task** | Average across delivered tasks started in the period, available when every task has an attributable verified total. Shared costs stay with the delivery. |
| **Live activity and pending decisions** | **Not measured yet.** An open record in the task index can outlast the native session. Use the native host for current progress and decisions. |

Time and review comparisons match difficulty cohorts with at least ten measured tasks per
period. A dash or **Not measured yet** means the index lacks the needed evidence. The
dashboard keeps the last successful view clearly marked as stale when a refresh fails.

The collector recovers difficulty, elapsed task time, review counts, and usage from
saved native runs and their matching host records. It deduplicates responses and keeps
cached input within input and reasoning within output. Rebuilding the index replays
saved observations even when the original host transcript is unavailable.

CI results appear after `oh ci-wait` or `oh observe-ci` records them. New analysis is off in v1.0.
Saved suggestions remain available under Data health and retain their original status.

## Privacy

- OH's records, review results, usage data and the dashboard database stay in `~/.local/share/o-harness`, or your configured data folder. Host transcripts stay in the host's own folder, such as `~/.claude` or `~/.codex`. Both can contain source code; keep them private.
- OH doesn't delete this data automatically.
- The dashboard listens on `127.0.0.1` only and rejects requests from other hosts and origins. Don't expose it through a tunnel.
- The dashboard is read-only for your work. It can't approve, start or control runs.

## Backup and recovery

| Command | What it does |
|---|---|
| `oh backup <folder>` | Saves a verified snapshot of OH's data and `settings.json` to a new folder outside the data folder |
| `oh restore <folder>` | Restores a backup into an empty data folder |
| `oh rebuild` | Rebuilds the dashboard database from saved events, keeping the old files in `recovery/` |

Backup and restore don't run while OH is writing state. If a run is active, they say so; retry once it finishes or you stop it. To inspect a backup without touching your data, restore it into a separate folder:

```sh
OH_DATA_HOME=/tmp/oh-inspect oh restore <folder>
```
