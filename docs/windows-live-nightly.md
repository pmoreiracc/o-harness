# Windows live nightly setup

[Issue #194](https://github.com/pmoreiracc/o-harness/issues/194) moves scheduled real
CLI regression to AI-Server using the private
[OH nightly control repository](https://github.com/pmoreiracc/oh-nightly). Its
dispatch-only workflow is merged. Two manual pilots and one catalog dispatch
have run on Windows. The catalog recorded four passing and four failing main
cases, plus passing external-merge journeys on both native CLIs. The catalog is
not green; scheduling stays disabled.

The control repository owns the workflow, standard repository-scoped self-hosted
Windows runner, native operator instructions, report boundary and Windows setup
guide. Keep that runner off public OH Actions. It tests only fetched merged OH
`main`, using the existing [real CLI fixtures and catalog](cli-acceptance.md) with
separate native subscription profiles. Public PR/fork code must never execute on
the private runner. Public deterministic Linux/Windows nightly coverage is unchanged.

The private [dispatch evidence](https://github.com/pmoreiracc/oh-nightly/blob/main/DISPATCH-PROOF.md)
and [catalog run](https://github.com/pmoreiracc/oh-nightly/actions/runs/43724928472)
retain failed first outcomes, inspected effects and cleanup limits. The separately
authorized [#198 repair](https://github.com/pmoreiracc/o-harness/issues/198)
is merged, and the Actions pilot used trusted main containing it and the Mac
agent's merged #191/#193 fixes. The second pilot reached reviewed completion and
checkpoint Stop on both hosts, while retaining a Codex operator failure. The
catalog also retains operator and product failures despite successful later
recovery. Supplementary native variants are recorded separately at the
maintainer's request; their results must not rewrite the Actions artifact.
These follow-ups retain refused stale discard, actual disclosed restart,
reviewed completion, presentation and interruption evidence, along with native
permission failures and conditional paths whose prerequisites did not occur.
They do not establish a green catalog or authorize shared-runtime repairs.
The completed infrastructure review predates the subsequent
reporting and operator-guidance corrections; those changes were not independently
re-reviewed. The separate design-progress defect in
[#199](https://github.com/pmoreiracc/o-harness/issues/199) remains recorded.

The v0.9.5 [catalog rerun](https://github.com/pmoreiracc/oh-nightly/actions/runs/45264758722)
recorded passing Claude Delivery and quick-fix selection. Planning failed even
though proposal and Design approvals were recorded after assisted recovery. The
CI-repair scenario did not run because its prerequisite failed. Codex was deferred
at its subscription limit. The [v1.0 follow-up](https://github.com/pmoreiracc/oh-nightly/actions/runs/45310473542)
started on the self-hosted runner and ended during the native operator step without
a scenario report. After the listener was restored, the
[retry](https://github.com/pmoreiracc/oh-nightly/actions/runs/45312705279)
stopped before it selected an OH revision because its process could not find
`codex` on PATH. Start the listener in the signed-in PowerShell session after
`Get-Command codex,claude,git,gh,python3` resolves the existing tools. Windows
native workflows remain in preview.

The setup correction was human-merged before the second pilot and catalog.
The trusted catalog source included the merged #191/#193 fixes. The private
result report separates actual decisions, checks and effects from assisted
recovery, failed setup and unavailable prerequisites. Retain unresolved failed
evidence privately and remove only finished task-owned resources. Keep failed
first outcomes and unexercised dependent paths visible. Infrastructure work does
not authorize runtime repairs or repeated product tests until green.

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
