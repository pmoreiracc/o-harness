# Dashboard and data

The dashboard at <http://localhost:4318> shows how OH runs are going. It reads a local
SQLite database and never calls a model. It only counts work done through OH; history
from before you installed OH is not imported.

Development snapshots use separate data under `~/.local/share/oh-dev/data`; their runs do
not appear in the normal dashboard. `oh-dev on` starts or refreshes the development dashboard
at <http://localhost:4319> using the selected snapshot and opens it in your browser. Its
collector indexes queued development events. `oh-dev off` returns to the release dashboard
at <http://localhost:4318>; development stays running if another host still uses it.
The dashboard identifies its environment and serving version. Existing released dashboards
gain this label when upgraded. No development OS service is installed.

`oh-dev dashboard --host codex` reopens or retries the dashboard for that host without
rebuilding or switching plugins. Dashboard/browser failures do not undo a plugin switch.
`oh-dev exec serve` defaults to development port 4319; an explicit `--port` still works.

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
suggestions. Savings shown are estimates from your data, not promises. Python computes
the candidates, explanations and estimates; the requested model ranks the candidates.
The dashboard uses `models.codex.insights`; `oh suggest --host claude` uses
`models.claude.insights`. Viewing or switching dashboards never requests model analysis.
Global profile selection and standalone host launches are covered by
`test_requested_insights_uses_global_profile_without_registering_the_engine`.

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
