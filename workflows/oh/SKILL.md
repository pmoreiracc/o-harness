---
name: oh
description: Execute an explicit task manifest with automatic bounded workers and independent reviews. Invoke only when the human asks for OH task execution.
---
The shared runner owns task selection, models, verification, fresh independent reviews,
retries and one commit per task. Keep this conversation as the small coordinator.

For a native `oh start request:HASH` / `$oh request:HASH` / `/oh request:HASH` trigger, run the
project entry point `oh run` (consumer: `.oh/oh run`). The hook captures the trigger;
the runner verifies the native human transcript before granting the configured batch.
If the user described work without a manifest, prepare one from the agreed tasks in
`.oh/runtime/tasks.json`, run `oh prepare .oh/runtime/tasks.json` (consumer: `.oh/oh prepare`), then present
the returned exact request trigger. Preparation seals tasks, checks and effective settings
before the human event. Later file edits never widen that grant. A stale base needs new preparation.
Never fabricate a human event, change configuration to grant more work, or bypass a refusal.

Wait for the running process with the host's event/completion mechanism. Use waits of
up to 60 seconds; report only meaningful progress. Do not repeatedly read full transcripts.
On interruption, run the same command: immutable state determines what resumes.
At a non-final `checkpoint`, show the completed count and exactly `continue`, `pr`, `stop`.
At `completed`, present exactly `pr` and `stop`. Finishing the last task does not authorize publication.
For a spent review window show `grant review` or `stop`. For unresolved findings show
the evidence and `fix findings` or `stop`; preserve the existing review budget.
At `needs_attention`, explain the failure and offer `retry` for one explicit bounded recovery window or `stop`. A stopped native run may use `resume` with its existing allowances.
After a native human choice, run the same runner command to verify and apply it.

For `pr`, verify the branch, push it, open one PR against main (or recover its existing PR),
include the exact `oh pr-summary` output (consumer: `.oh/oh pr-summary`) in the PR body,
and attach its URL to the conversation. The export binds retained review history to every
commit; never hand-edit it or fabricate legacy receipts. Never merge. A `stop` result ends work immediately.
Only load the current task's evidence when diagnosis is needed; full history stays outside
the coordinator context. Codex compacts at the configured threshold; after compaction,
read `oh status` and the user's durable choices, not previous worker transcripts.

After publishing the PR, wait for its checks through the host completion mechanism, then run the project entry point `observe-ci` to retain CI outcomes for the reviewed commit. A failed check remains visible and requires repair and a new review. Never turn a missing CI result into success.
