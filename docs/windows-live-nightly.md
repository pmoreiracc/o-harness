# Windows live nightly setup

[Issue #194](https://github.com/pmoreiracc/o-harness/issues/194) moves scheduled real
CLI regression to AI-Server using the private
[OH nightly control repository](https://github.com/pmoreiracc/oh-nightly). Its
dispatch-only bootstrap is merged. The first manual Actions pilot ran and failed
qualification; live acceptance remains pending and scheduling stays disabled.

The control repository owns the workflow, standard repository-scoped self-hosted
Windows runner, native operator instructions, report boundary and Windows setup
guide. Keep that runner off public OH Actions. It tests only fetched merged OH
`main`, using the existing [real CLI fixtures and catalog](cli-acceptance.md) with
separate native subscription profiles. Public PR/fork code must never execute on
the private runner. Public deterministic Linux/Windows nightly coverage is unchanged.

The private [dispatch evidence and operator corrections](https://github.com/pmoreiracc/oh-nightly/pull/6)
retain the failed first outcomes, inspected effects, cleanup limits and ordered
resume steps. The separately authorized [#198 repair](https://github.com/pmoreiracc/o-harness/issues/198)
is merged, and the Actions pilot used trusted main containing it and the Mac
agent's merged #191/#193 fixes. Passing two-host pilot and catalog qualification
remain pending. The completed infrastructure review predates the subsequent
reporting and operator-guidance corrections; those changes were not independently
re-reviewed. The separate design-progress defect in
[#199](https://github.com/pmoreiracc/o-harness/issues/199) remains recorded.

The maintainer merges supporting operator corrections before another manual run.
First prove one installed-skill
delivery on Windows Codex and Claude, including actual decisions, checks, fresh
consumer review, completion and cleanup. Fetch the Mac agent's merged #191/#193
fixes before the one explicit P/D/Q/C catalog qualification. Keep failed first
outcomes and unexercised dependent paths visible. Infrastructure work does not
authorize runtime repairs or repeated product tests until green.

Keep scheduling disabled under the current maintainer instruction. Any future
03:00 `America/Sao_Paulo` schedule requires a new maintainer request, completed
manual dispatch proof and catalog qualification, and a separate control PR. Keep the Mac
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
