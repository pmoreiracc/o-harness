# Windows live nightly setup

[Issue #194](https://github.com/pmoreiracc/o-harness/issues/194) moves scheduled real
CLI regression to AI-Server using the private
[OH nightly control repository](https://github.com/pmoreiracc/oh-nightly). Its
dispatch-only bootstrap is under preparation; this document does not claim live
acceptance or an enabled Windows schedule.

The control repository owns the workflow, standard repository-scoped self-hosted
Windows runner, native operator instructions, report boundary and Windows setup
guide. Keep that runner off public OH Actions. It tests only fetched merged OH
`main`, using the existing [real CLI fixtures and catalog](cli-acceptance.md) with
separate native subscription profiles. Public PR/fork code must never execute on
the private runner. Public deterministic Linux/Windows nightly coverage is unchanged.

The private [control PR and its resume runbook](https://github.com/pmoreiracc/oh-nightly/pull/1)
records the verified local Windows Codex pilot and the pending infrastructure
review, maintainer merge, manual dispatch and catalog prerequisites. Claude's
allowance returned and the merged fixture memory fix was verified, but its
dedicated-profile pilot is blocked by the native-history resolution defect
tracked in [#198](https://github.com/pmoreiracc/o-harness/issues/198). No task grant
or worker was created; the native refusal was preserved.
The local Codex pass does not substitute for a two-host Actions dispatch.

The maintainer merges the private dispatch bootstrap before the first manual run;
GitHub requires the workflow on the default branch. First prove one installed-skill
delivery on Windows Codex and Claude, including actual decisions, checks, fresh
consumer review, completion and cleanup. Fetch the Mac agent's merged #191/#193
fixes before the one explicit P/D/Q/C catalog qualification. Keep failed first
outcomes and unexercised dependent paths visible. Infrastructure work does not
authorize runtime repairs or repeated product tests until green.

Enable 03:00 `America/Sao_Paulo` scheduling only after manual dispatch proof and
catalog qualification, through a separate reviewed control PR. Keep the Mac
`oh-nightly-live-cli-regression` automation paused. Windows evidence is acceptance
for this infrastructure slice; ordinary macOS development acceptance stays on Mac.

Actions serializes control runs without cancelling active work. A host lease and
native acceptance-profile ownership checks protect ongoing trials. A busy profile
means deferred, never replacement. Setup failures must name the supported recovery
step. Preserve normal profiles, checkouts, active snapshots, services and deliveries.
No custom agent loop, terminal driver, permission broker, API fallback or native
trust bypass belongs in the setup.

Results belong to the private workflow run's sanitized artifact. Raw transcripts,
state and credentials stay off Git and artifacts. Retain failed evidence locally
until diagnosis; clean only task-owned resources. Native logins persist for future
runs. See the private control README for verified host commands and current status.
