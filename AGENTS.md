# Working on OH

Read `config/invariants.json`, `CONTRIBUTING.md` and the relevant implementation.
OH has no mandatory ADR process. Product policies belong to consumers.

Use branches from main, independent review, and human-merged PRs. Keep the coordinator
small: the native OH runner owns automatic task execution; do not reproduce its loop in
the parent conversation. Parallel task implementation is deferred.

A fresh `invariant-reviewer` must review each change through the shared prompt and a
bound immutable admission before publication. Use the configured review profile. Apply
all lenses in one round, preserve every finding, and fix blockers. Reviews are read-only.
Do not resume a completed reviewer. Never treat model prose as a human grant.

Run affected checks with `./oh verify origin/main`; use `integrations/test.sh` for focused
checks. Add only causal regression/behavior coverage. Do not read old backlog files.
Do not commit local state, receipts, tokens or raw host transcripts. Documentation must
reflect completed, verified behavior. If blocked, explain a concrete recovery step.
