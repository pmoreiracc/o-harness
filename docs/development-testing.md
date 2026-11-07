# Developing and testing OH

OH development uses native tools, small changes and one independent review. Candidate
OH runs in disposable consumer projects. These rules govern OH contributors, not the
review policy of projects using OH.

## A finite change

State the user outcome, scope boundaries and acceptance scenarios before editing. Trace
the next workflow transition as well as the reported failure. Fix necessary supporting
defects; record unrelated work separately. A finding is evidence to evaluate, not an
instruction to add machinery. Prefer removing an unnecessary dependency when that preserves
the approved guarantees. Do not promise exhaustive protection against every host behavior.

## Feedback during development

- `bash integrations/test.sh core` runs a small deterministic core using existing tests.
  It is not live host acceptance. Aim for a 1–2 minute local feedback loop; report measured
  time and improve slow fixtures rather than deleting unique protection to meet a number.
- Run the specific causal tests for the edit using `PYTHONPATH=runtime python3 -m unittest
  oh.test_MODULE.Class.test_case`. Use `affected` to inspect broader impact, not after every edit.
- Exercise the changed behavior through a real Claude or Codex CLI. Exercise the affected sanity paths on both hosts. Use the [scenario catalog and disposable fixtures](cli-acceptance.md).
- After changing shared entry, handoff or control behavior, run live sanity: skill entry,
  actual approval, a tiny delivered task and its checkpoint, plus Stop/resume when affected.

Real AI runs have variable duration and subscription usage. Measure both where available;
unknown usage remains unknown. The scheduled live catalog is a separate subscription run on the authenticated Mac. Use no API fallback,
automatic review renewal or retry-until-green. A failure remains evidence even if a later trial passes.

## One review

After focused checks, launch one fresh independent native reviewer with the configured
profile. Supply the approved outcome, boundaries, Git base/candidate, relevant instructions
and verification evidence. It reads the complete change and affected callers. It must not
edit or launch another reviewer. OH's own admission/retention workflow is not required to
repair OH; native agent isolation and explicit Git identities identify this review.

The review brief is: identify concrete failures in the approved behavior, introduced
regressions and missing evidence required by a meaningful guarantee. State the trigger,
wrong outcome, source location and smallest correction. Investigate material uncertainty;
label what remains unknown rather than defaulting to a violation. An unproved required
approval, Stop or publication guarantee can still block readiness. Naming preferences,
speculative combinations and optional architecture improvements cannot expand this change.

Preserve every finding. For a real bug in scope, show the failure on the reviewed candidate
before editing it, then prove the same behavior passes after repair. Prefer extending an
existing scenario. Use deterministic and/or live coverage appropriate to the failure;
host claims require live CLI evidence. If faithful reproduction is intermittent, keep the
original observation and state which part the repeatable regression proves. Classify each
new E2E as fundamental (sanity and nightly) or extended (nightly); explain why. No second review round. If proof cannot be
established, stop publication with a concrete remedy; a round limit never turns a failure
into success. The PR identifies the reviewed candidate and summarizes post-review repairs
and their evidence. It must not claim independent review of the final repaired tree.
Record pre-existing failures outside the change as failed scenarios with issue links;
never relabel them as passes or silently expand implementation to fix them. Distinguish
whether they prevent proving this change's approved outcome from a separate product defect.

## Final verification and CI

1. Run `bash integrations/test.sh pr origin/main` and `bash integrations/test.sh syntax` on
   the final candidate. PR selection is the deterministic core plus affected modules.
   Known runner changes exercise their own selection tests and the core. Unknown impact triggers full discovery.
2. After the single review, run full [live sanity](cli-acceptance.md#live-sanity) on
   both Mac CLIs. Record candidate, outcomes, any recovery and wall time per host. An
   unfinished path remains untested. After a repair repeat the evidence it invalidated.
3. For host-interaction changes offer one personal snapshot trial with both results.
4. Open the PR and follow CI. Aim for nine minutes of deterministic CI and roughly ten
   minutes of full live sanity wall time. These are targets for improving fixtures and
   scheduling. Keep valuable coverage if its best measured implementation runs longer;
   report why. Time alone does not determine the verdict.
5. Nightly runs the full deterministic suites and the full live catalog, independently
   of PRs and releases. Release keeps candidate-specific package/install checks on all
   supported OSes. Triage relevant nightly failures before shipping.

For focused development, list affected modules with `bash integrations/test.sh affected
origin/main --list` and choose the causal cases. The PR selector conservatively expands
unknown impact to full discovery. Inspect `bash integrations/test.sh pr origin/main --list`
and CI durations before pruning any check. Optimize expensive setup or move redundant
broad coverage to nightly once its unique risks still have a regression.

## What live acceptance proves

Use tiny tasks and the actual packaged skill, native agents and native decisions. Inspect
actual files, checks, commits, saved grants and PR head/result, not a model's success claim.
Assert necessary approval ordering and effects, not an exact incidental tool sequence.
Inspect questions for understandable scope, correct available choices, valid dismissal and
unnecessary repeat approvals. CLI output does not prove desktop layout or a physical click.

Keep fixtures and native transcripts outside the checkout. Codex uses the dedicated acceptance login. Each
trial starts isolated. After a failure, preserve that trial for diagnosis; retry explicitly
with its outcome recorded. Do not weaken a production guard to make the fixture pass.

After acceptance, stop owned processes, close test PRs without merging, and delete the
task's disposable repositories, sessions, state and temporary credentials. Retain the dedicated Codex acceptance login. Preserve
only a concise sanitized report (source/snapshot, hosts, scenarios, outcomes, duration,
usage if known and limitations). Failed evidence is removed after diagnosis, not hidden.
Normal host configuration, active snapshots and unrelated projects/drafts are preserved.
