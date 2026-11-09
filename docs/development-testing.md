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

## Choosing coverage for a change

For every fix or feature, name the behavior a user or caller relies on and the
observable result that would distinguish success from the bug or a partial implementation.
Find the existing tests and live scenario for that behavior before editing. Extend them
where coverage is missing. For a bug, reproduce the wrong result first when possible
and run the same case on the fix. For a feature, exercise its normal entry point and
any consequential boundary it introduces, such as declining an approval.

| What needs proof? | Test to use | Where it belongs |
| --- | --- | --- |
| A rule with controlled inputs, such as whether a stale decision matches | Unit test calling the rule directly | The existing behavior-specific `runtime/oh/test_*.py` module |
| A handoff between components, such as a decision changing saved run state | Deterministic integration test using the real components and a minimal temporary project | The module covering the workflow, such as `runtime/oh/test_recovery.py`. Create a new test module only for distinct behavior without an existing home. |
| Behavior a person experiences through an installed skill, including menus, prompts and host hooks | Real CLI E2E on both Mac hosts. Drive the actual input and inspect the effect. | Extend the corresponding scenario in [CLI acceptance](cli-acceptance.md). Change `integrations/e2e_fixture.py` only when the scenario needs different setup. |

Use the layers that expose distinct risks. For example, a deterministic case can
prove a stale answer grants nothing. A live quick-fix scenario can prove that the
user sees a readable choice, answers Stop once, and gets the promised handoff with
no workers or edits. Unchanged files alone would also occur if OH rejected the answer.
An existing case that already distinguishes the outcomes is sufficient. For an edit
limited to contributor prose, verify its instructions, paths and examples.

**Choose when the case runs.** A focused case runs during development even if its
permanent home is nightly. For deterministic tests, confirm the owning module appears
in `bash integrations/test.sh pr origin/main --list` for the change. Update the
[selector](../integrations/select_tests.py) if the changed surface lacks coverage in
that selection. Reserve the always-run deterministic core for cheap checks of behavior
many changes can break. For live E2E, extend **sanity** when failure would break a
fundamental journey such as entering a skill, accepting, declining, resuming or
delivering reviewed work. Cover additional variants and injected failures in the
**nightly catalog**. For a new fundamental journey, include it in both suites.

In the PR, name the tests or scenarios used, what they proved, and why any new case
belongs in its chosen suite. Include the measured cost of additions to the core or live suites.

## Feedback during development

- `bash integrations/test.sh core` runs a small deterministic core using existing tests.
  It is not live host acceptance. Aim for a 1–2 minute local feedback loop; report measured
  time and improve slow fixtures rather than deleting unique protection to meet a number.
- Run the specific causal tests for the edit using `PYTHONPATH=runtime python3 -m unittest
  oh.test_MODULE.Class.test_case`. Use `affected` to inspect broader impact, not after every edit.
- Exercise affected workflow paths on both Mac CLIs, including the relevant entry,
  handoff or recovery step. Use the [scenario catalog and disposable fixtures](cli-acceptance.md).
  Run full live sanity after the independent review as described under Final verification and CI.

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

1. During repairs, rerun the causal deterministic cases and affected live paths. Once focused live
   testing has stabilized the candidate and the single review and its repairs are complete,
   run `bash integrations/test.sh pr origin/main` and `bash integrations/test.sh syntax` on the final candidate.
   Repeat broad checks only when subsequent edits invalidate their evidence. PR selection is the deterministic core plus affected modules.
   Known runner changes exercise their own selection tests and the core. Unknown impact triggers full discovery.
2. After the single review, run full [live sanity](cli-acceptance.md#live-sanity) on
   both Mac CLIs. Record candidate, outcomes, any recovery and wall time per host. An
   unfinished path remains untested. After a repair repeat the evidence it invalidated.
3. For host-interaction changes offer one personal snapshot trial with both results.
   Keep the snapshot available and wait for the developer's reply before opening the PR. If they choose the trial, wait for their verdict.
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
