# Dashboard and data

The dashboard at <http://localhost:4318> shows how your OH runs are going: tokens, time, review results and how much work finished without you stepping in. It reads a local SQLite database built from OH's saved records and never calls a model. It counts work done through OH from the moment you install it.

## Start the dashboard

On macOS and Windows, `oh service-install` starts the dashboard at login and keeps it running. `oh service-uninstall` removes it. On Linux, run `oh serve`, or run it under your own service manager.

The dashboard service also collects new observations. To run one collection pass by hand, use `oh collect`.

## Views

| View | Shows |
|---|---|
| **Overview** | Usage over time, effort by difficulty, the models doing the work, agent time by model, quality alongside efficiency, and operations and recovery |
| **Task explorer** | Recent tasks. Select one to see its attempts, checks and timeline. |
| **Improvements** | Suggestions saved by earlier versions |

Filter by **Project**, **Work**, **Difficulty**, **Version**, **Spending model**, **Spending phase** and dates. **Compare with** sets the baseline: the **Previous period** or **Custom dates**. You can also compare OH versions.

## Measures

| Measure | What it means |
|---|---|
| **Observed tokens** | Input plus output tokens the host reported in the selected period. Includes cached input. |
| **Average task time** | Wall-clock time per completed task |
| **Reviews per task** | Review rounds used by completed tasks |
| **Completed autonomously** | Completed tasks that finished without a human intervention |
| **First-review acceptance** | Completed tasks whose first review was clean |
| **Tokens / completed task** | All tokens of completed tasks, including repairs |
| **Cached input share** | The part of input served from cache. Cached tokens still count toward usage. |
| **Agent time by model** | Time the models reported, with how much of it was measured |

When a value wasn't observed, the dashboard shows **—** or a coverage note instead of an estimate. **Recorded task usage coverage** shows how many attempts have usage data. Usage is shown in tokens, not converted to money or to a share of your subscription limit.

Comparisons weight each difficulty level equally in both periods, so a harder mix of work doesn't read as a regression. A change is shown once at least 10 matched completed tasks back it. Comparisons show what changed, not why.

CI results appear when the agent follows a published PR's checks to a result (`oh ci-wait`), or after you run `oh observe-ci` once they finish.

## Improvements

New analysis is off in v1.0: the **Improvements** view shows **Analysis unavailable**, and the button runs nothing. Suggestions saved by earlier versions stay readable. Their savings figures are estimates.

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
