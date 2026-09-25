# Dashboard and data

The localhost dashboard reads SQLite. The runner writes tiny durable event files; a
collector ingests them in batches and advances transcript offsets incrementally.
Opening or refreshing the dashboard never scans all raw conversations and never calls AI.
SQLite uses WAL and indexes; no database container is required.

## Read the numbers

| Measure | What it means |
|---|---|
| Observed tokens | Input plus output reported by hosts during the selected period |
| Cached input | A subset of input, not additional tokens |
| Reasoning | A subset of output where the host reports it; otherwise unknown |
| Tokens per completed task | Costs of the same completed task cohort, including repairs |
| Task time | Elapsed task wall time, grouped by preassigned difficulty |
| Model time | Reported attempt duration, with measurement coverage; not task wall time |
| Reviews per task | Completed-task review counts, including unsuccessful attempts |
| First-review acceptance | Completed tasks whose first review was clean, with known outcomes |
| Autonomous completion | Completed tasks with explicit evidence of no human intervention |
| Operational observations | Verification/reuse, waiting, recurring findings, fix regressions, recovery and observed CI results |

Missing observations show **—**, coverage or a collection warning. A missing start record
cannot silently remove a completed task from the dashboard. Partial token groups are not
presented as complete totals. Coordinator share is unknown until coordinator usage is
observed. Source boundaries stop counting when a run stops or reaches its checkpoint.

Tokens are not a dollar bill or a percentage of your subscription. Host/account limits
may depend on model and other activity. OH does not convert tokens into an unsupported
weekly-limit estimate. Raw spending changes are neutral: doing more tasks is not a regression.

Compare date ranges or harness versions; filter project, kind, difficulty, model and phase.
Task measures use tasks started in the period; spending uses observation time; model time
uses attempts started in the period. Model/phase filters apply to spending and attempt
views, not a relabeling of the full task cohort. Improvement claims use matched difficulty
cohorts with at least ten completed samples per period and show their evidence limits.
They are observations, not proof of causation.

Click a task for its attempts, verification and event timeline. Detailed receipts remain
in local state. CI results are recorded when the coordinator runs `observe-ci` after the
PR checks finish; missing CI data is not a passing result.

## Suggestions

**Analyze my data** explicitly requests one subscription-backed analysis. OH requires at
least ten tasks, at least 80% task usage coverage and a supported signal without known
collection gaps. It saves up to three suggestions and reuses unchanged evidence.

SQL computes the evidence and hypothetical savings ranges. AI ranks supported options;
it does not invent numeric ROI. Each card states assumptions and quality risk. Estimated
token savings are scenarios, not promised subscription savings; effort/payback remains
unknown until measured. Analysis itself is recorded as harness usage. Opening the page
never runs it automatically. Scheduling and realized ROI are [future work](https://github.com/pmoreiracc/o-harness/issues/3).

## Privacy, retention and recovery

The default data home is `~/.local/share/o-harness`, outside product and harness checkouts.
It holds project/run journals, review receipts, raw child outputs, usage source offsets,
retained events, SQLite, verification cache, suggestions, trusted host identities and logs.
Files remain uncommitted. The shared directory makes evidence survive branch deletion,
worktree cleanup and an OH upgrade. Raw output can contain source code or user content;
treat backups as private. There is no automatic retention deletion in this release.

The server binds only to loopback and validates Host/Origin plus a session token for
mutations. It is a local single-user service, not a remotely authenticated team server.
Do not expose it through a public tunnel. Task approvals remain in the native agent
conversation, not in the dashboard.

No historical analytics are imported by default: old logs do not reliably establish all
required identities and coverage. Existing review evidence is preserved separately and
must not be erased merely because analytics starts fresh.

- `oh backup DESTINATION` creates a verified snapshot. Finish active OH work first.
- `oh restore SOURCE` restores into an empty data home after validation. Use
  `OH_DATA_HOME=/new/location oh restore SOURCE` to inspect a recovery safely.
- `oh rebuild` recreates SQLite from retained events and saved suggestions, preserving
  workflow authority and collection-gap evidence. The pre-open SQLite file set, including any WAL/SHM sidecars, is retained in `recovery/`
  for diagnosis before replacement. Rebuild is an explicit recovery operation, not a routine collector step.
- `oh collect` performs one collection pass. The service normally performs this for you.

An earlier isolated measurement was about 0.9 ms per durable event, 315 ms to ingest
1,000 events and 2.6 ms for an overview query. This is a local sample, not a large-history
benchmark or a guarantee. The request path performs no analytics model call. Collection
failures leave task authority intact and are surfaced for reconciliation.
