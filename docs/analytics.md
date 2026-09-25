# Dashboard and data

The dashboard at <http://localhost:4318> shows how OH runs are going. It reads a local
SQLite database and never calls a model. It only counts work done through OH; history
from before you installed OH is not imported.

## The numbers

| Measure | What it means |
|---|---|
| Observed tokens | Input plus output reported by the host in the selected period |
| Cached input | Part of input, not extra tokens |
| Reasoning | Part of output, when the host reports it |
| Tokens per completed task | All tokens of completed tasks, including repairs |
| Task time | Wall time per task, grouped by difficulty |
| Model time | Time the models reported, with how much of it was measured |
| Reviews per task | Review rounds used by completed tasks |
| First-review acceptance | Completed tasks whose first review was clean |
| Autonomous completion | Completed tasks with no human intervention |

A missing value shows **—** or a coverage warning; OH doesn't guess. Tokens are not money
and not a share of your subscription limit.

You can compare periods or OH versions and filter by project, kind, difficulty, model and
phase. Comparisons only use difficulty levels with at least ten completed tasks in both
periods. They show what changed, not why.

Click a task to see its attempts, checks and timeline. CI results appear when the agent
runs `oh observe-ci` after the PR checks finish.

## Suggestions

**Analyze my data** runs one subscription-backed analysis when you click it, never on its
own. It needs at least ten tasks with good usage coverage and saves up to three
suggestions. Savings shown are estimates from your data, not promises.

## Privacy

- All data stays in `~/.local/share/o-harness`: run journals, review evidence, raw worker
  output, usage and the database. Raw output can contain your source code; keep backups
  private.
- Nothing is deleted automatically.
- The dashboard listens only on localhost and rejects other hosts and origins. Don't expose
  it through a tunnel. It can't approve or control runs.

## Backup and recovery

- `oh backup <folder>` saves a verified snapshot. Finish active OH work first.
- `oh restore <folder>` restores into an empty data folder. To inspect a backup safely,
  use `OH_DATA_HOME=/tmp/oh-check oh restore <folder>`.
- `oh rebuild` recreates the database from saved events. The old files are kept in
  `recovery/`.
- `oh collect` runs one collection pass; the dashboard service does this for you.
