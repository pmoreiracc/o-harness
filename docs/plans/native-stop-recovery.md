# Native Stop and safe Resume

Approved for local implementation alongside the #105/#120/#122 fixes on 2026-10-20.
The combined snapshot still needs developer host acceptance before independent review
or publication. Local tests and disposable host probes are different evidence.

## Developer experience

Click the native Stop button. OH should stop its owned commands and prevent the old
worker from using more tools. Later, invoke the same work in the same conversation
or a new one, accept the existing Resume question once, and continue. Preserve edits,
scope, findings and remaining allowances. Do not require `/oh-stop`, child IDs or
manual state repair.

Stopping a native model's generation is different from preventing that model from
executing work. OH's revocation receipt asserts the latter, with command/tool cleanup;
it does not assert that Codex terminated the model.

## Evidence already collected

Disposable probes ran on macOS 27.0.1 with ChatGPT Desktop 26.1013.31256 (20586),
bundled Codex CLI 0.163.0-alpha.10.2. Raw evidence remains outside this repository.

- Actual native Stop saved `turn_aborted` while a child command survived.
- Another root task could not interrupt that child through native collaboration
  controls. A separate app-server instance could not control the original runtime.
  Saved interrupted status alone did not establish command termination.
- A trusted native Interrupt hook plus the existing OH process cleanup stopped the
  disposable command group, including a descendant that ignored SIGTERM.
- A second prototype returned cancellation (130), resumed in the **same conversation**,
  stopped again, and recovered in another conversation. Partial edits survived.
  All six owned probe processes ended. Old workers' edit calls were denied after Stop;
  the old parent was also denied after the new conversation took ownership.
- The prototype used an external fixture driver to admit replacement attempts.
  It did **not** exercise real OH scope, allowance or Resume helpers. Fixture tests,
  separately, checked duplicate Stop and competing continuation requests.
- The temporary hooks/trust were removed and both probe tasks archived.

The upstream defect remains tracked in
[openai/codex #55521](https://github.com/openai/codex/issues/55521).
This implementation does not depend on that issue being fixed.

Official contracts consulted:
[Codex hooks](https://learn.chatgpt.com/docs/hooks),
[app-server interruption](https://learn.chatgpt.com/docs/app-server), and
[Claude hooks](https://code.claude.com/docs/en/hooks).
Codex Interrupt is a bounded main-thread callback. Claude's Stop hook does not run
on user interruption; OH reads the saved root interruption record instead.
Neither documentation nor macOS probes prove Linux/Windows or Claude live behavior.

The golden reference `my-geoffrey@harness-before-separation` (`b508bdc`) supplies the
existing durable, evidence-based recovery approach. It has no native Stop solution.
The command/tool revocation boundary is the necessary addition to prevent a surviving
worker from conflicting with resumed work.

## Local implementation

1. **Record interruption.** Native hooks save attributed Stop evidence outside the
   checkout. Tool boundaries and owned command waiters also inspect newly saved
   native records, preserving partial saves for a retry. An idle session or status
   label is never interruption evidence.
2. **Stop owned commands.** Workers use an explicit executable/argument array through
   `owned-command`, invoked by the same native shell tool with its normal permissions.
   Its hook reservation prevents untracked launches. Configured checks reuse their
   existing process groups or Windows jobs. Hooks never approve permissions or rewrite
   tool inputs; focused OH helpers run directly, without nested command groups.
   Worker cleanup receipts live in private temporary folders, so ordinary shell
   commands only read OH’s durable state. Claims and Resume share the existing
   control lock, opened read-only by the worker. A macOS sandbox regression denies
   writes to OH state while exercising real command/descendant cancellation.
3. **Close old tools.** Attempt/owner records reject stopped workers' later calls,
   including after same-conversation Resume. In-flight operations must finish first.
   Missing post-tool callbacks can be reconciled from native tool completion records.
4. **Resume once.** The normal human decision validates the scope and answer. Cleanup
   precedes ownership transfer, and a later Stop defeats an earlier Resume answer.
   Concurrent transfers serialize. A fresh attempt keeps the original budget and
   cannot revive an old worker. A never-launched admission needs a saved parent Stop
   and absence of a matching native launch, not merely an absent binding.
5. **Retain evidence.** Bound workers with observed tool guards and settled commands
   can receive an explicit OH revocation receipt while their model is still generating.
   A late native report is retained on retry under the original cancelled attempt;
   it cannot finish replacement work. Findings and original reports remain available.

`runtime/oh/test_cancellation.py` covers these boundaries with real temporary Git
repositories, fake native provenance, and an actual disposable command/descendant.
Installation tests check each host's hook packaging and Windows launcher selection.
Windows permits locking a handle opened for read access ([LockFileEx contract](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)).
macOS cleanup reads only the owned process group through the native `libproc` API
([Apple source](https://github.com/apple-oss-distributions/xnu/blob/main/libsyscall/wrappers/libproc/libproc.h));
it no longer depends on executing `/bin/ps` inside a sandbox.
These are local regression checks, not live host acceptance.

## Limits that must remain explicit

Native hooks must be available, enabled and trusted through the host. They are not an
OS security sandbox; host callback failures may fail open. Owned commands do not
cancel remote jobs, detached services or unrelated commands. A killed wrapper or an
unresolved in-flight tool can leave cleanup uncertain. OH must preserve that evidence
and refuse a conflicting replacement rather than clear the state or kill guessed PIDs.
Normal interrupt cleanup is handled by the wrapper. Configured-check recovery can
also use a saved kernel process identity after the helper is killed. An unidentified
surviving group and an abruptly killed ordinary command wrapper with no completion
receipt remain blockers; this is not a general process-discovery service.

## Acceptance before review

Rebuild with `oh-dev on` and use a fresh host session for the new snapshot/hooks.
Use disposable work with a visible long-running child command, then:

1. Click native Stop. Verify the command and descendants end and old tools are denied.
2. Invoke the same work in that conversation; accept Resume once. Verify preserved
   edits and allowance, and one fresh worker.
3. Stop again, open another conversation, invoke the same work and accept Resume.
   Verify the old worker cannot edit or run commands alongside the replacement.
4. Complete the work and exercise the earlier retention/review-format fixes in the
   same snapshot. Confirm no repeated approval or duplicate review charge.

Repeat on Claude and supported platform runners. Fix observed behavior before a fresh
immutable-admission invariant review. Human-controlled publication remains separate.

## Integrated test findings, 2026-10-20

The design 0007 test used Desktop 26.1013.40934 (20770), bundled CLI
0.163.0-alpha.10.2, and snapshot `0.7.5-SNAPSHOT.1792511834559540000`.
The earlier native-answer newline correction worked: the saved Resume answer was
accepted and the implementation agent launched. Hooks recorded two owned commands.
Both commands had finished before the user pressed Stop; this run therefore does
not establish cancellation of a running command. Parent and child transcripts both
recorded interruption.

The next human turn could read status, but its second tool was denied. OH had
mistakenly treated all turns observed under a stopped owner as stopped turns.
The local correction checks actual per-turn Stop evidence, while keeping the old
worker revoked. It also observes the proposed recovering conversation before cleanup,
so a Stop there can prevent ownership transfer; that observation grants no authority.

The regression now exercises the packaged hook launcher across discovery, multiple
recovery tools, the real native-answer parser, ownership transfer, replacement work,
checks, a review with a preamble, and completion in a disposable repository. Native
model results remain fixtures. A separate extension reproduces Stop during cleanup
from another conversation. Both failures were reproduced before correction.
The reviewer CLI also accepts a literal draft through `review-check --text`, avoiding
a shell pipe rejected by the command guard or a scratch-file write by a read-only reviewer.
Live acceptance of this corrected snapshot remains pending.

The next design 0007 test used snapshot `0.7.5-SNAPSHOT.1792514660265072000`.
Same-conversation Resume accepted the answer and launched a replacement worker.
During verification, two failed MCP calls completed before Stop; their nested
`item_completed` records had different IDs from the enclosing code-mode output.
OH had ignored those records. A third verification call was interrupted without a
host completion record. Its owned check recorded termination by SIGTERM and the
verification lock was released, but all three tool reservations still blocked
new-conversation Resume.

The local correction reads attributed native completion records for nested MCP,
command and patch tools. A transport error alone does not prove MCP completion.
For a stopped verification helper with no completion callback, recovery uses its
existing execution lock: it must be released, and each owned command must still
have cleanup evidence. Retention holds the workflow control lock, so a queued old
helper cannot pass the Stop guard during transfer. Shell verification also carries
the original attempt ID from its packet, so a delayed invocation cannot select a
replacement author on a host without a caller identity environment variable.
Other unresolved tools remain
blocking. This adds no new runner or cancellation service.

The configured-check regression now includes the native tool reservations,
failed nested-call evidence, Stop during a real check, cleanup still holding the
verification lock, missing command cleanup, and new-conversation Resume with the
same answer. It preserves edits and allowance and rejects the old worker afterward.
The previously passing check test called verification directly and missed this
native-tool bookkeeping layer. A read-only replay of the actual saved run now
settles all three reservations; the consumer's state was not changed. Live recovery
with the rebuilt snapshot remains unverified.

## Claude check interruption corrections

The macOS Claude Desktop 2.1.304 test exposed three separate defects: native shell
termination bypassed the verification helper's cleanup; the prescribed typed Resume
retry superseded its own saved answer and repeated questions could select an older
answer; packaged agents lacked `SendMessage`, so progress stayed in the child.

Verification now handles SIGINT/SIGTERM by unwinding cleanup. Command execution is
gated until its kernel identity is saved. A stopped configured check with no final
receipt can be recovered only after the verification lock is free and the saved
process group/job has been cleaned or proved absent. Real macOS subprocess regressions
exercise SIGTERM, SIGKILL, a descendant ignoring SIGTERM, refusal of a mismatched
identity, and failure to persist identity before execution. Windows jobs are covered
by the platform implementation and still require Windows execution; macOS results
do not establish Windows behavior.

Resume accepts the prescribed exact retry phrase without treating it as a fresh
grant. It still rejects unrelated newer input and a later Stop. Question matching
ignores questions older than the current prepared decision. Native answer-parser
regressions cover those cases. All four Claude roles now expose `SendMessage`, and
the progress contract requires a real message to the native coordinator before checks.

The earlier blocked Claude command predates process-identity recording. Its native
Stop is saved, but its command cleanup is not. OH preserves that uncertainty. A
verified reboot after that command's start is sufficient process-cleanup evidence;
restarting the conversation or merely waiting is not. It does not prove checkout
identity or guarantee Resume. Preserve the checkout and OH evidence in persistent
storage first. On the tested Mac, reboot also changed the filesystem device number,
so normal registration rejected even an unchanged permanent checkout. If that happens,
preserve its registration and report the identity blocker; `init --replace` creates
a fresh registration and cannot recover an active run's original authority. A supported
identity-recovery policy is separate work; this change does not relax that protection.

An automated macOS acceptance run used the exact Claude Desktop 2.1.304 executable
through Anthropic's SDK and the existing subscription. Its native interrupt stopped
two configured checks (both recorded SIGTERM), first followed by same-conversation
Resume and then by new-conversation Resume. The final check passed in 15,175 ms;
one fresh opus/high reviewer returned a clean report with `Review complete.` before
the structured decision. Completion committed the exact reviewed fixture, with a
clean worktree, one unchanged task grant, all tracked operations settled, and no
publication. Real `SendMessage` calls were acknowledged and delivered to the parent.

Initial scope approval and both Resume answers were explicit test fixtures. Agent
execution, native records, hooks, configured commands, interruption, retention,
verification, review and commit were real. This validates the native execution flow,
not new human UI approval or a physical Desktop Stop click. The run also exposed a
duplicate-binding refusal caused solely by newly appended message hashes. The fix
preserves the original binding when its identity, launch and profile are unchanged;
actual saved records and a regression verify the distinction. Unrelated API metadata
without a working directory is not treated as a child execution record.

Windows host acceptance remains deferred at the developer's request. Before the
reboot, the old Claude run's actual saved Resume answer reached the legacy cleanup
refusal. Its checkout and Git history were backed up outside temporary storage.

The subsequent real reboot removed the temporary checkout and ordinary command
receipts. The exact pre-reboot checkout backup was verified before an audited
registration restoration outside the normal recovery helpers. This exceptional,
user-authorized restoration is not proof of automatic recovery after reboot;
normal registration still rejects an identity mismatch.
Reconciliation now records later-kernel-boot cleanup for missing temporary command
receipts as well as configured checks. Missing receipts or a native shell completion
alone remain insufficient. The existing command cancellation regression deletes its
receipt and checks refusal without reboot proof, then recovery with that proof.

Recovery of the original Claude acceptance run subsequently completed using its
actual saved human approval. The configured check ran unchanged for 90,084 ms and
passed; one fresh reviewer returned a clean report with the required preamble.
Completion produced commit `e8449724fa00dc8535d71c4843f40d2e96f055ca` in the
disposable consumer checkout, with a clean worktree, unchanged check/specification,
the original one-task allowance and no publication. The two permission-blocked
diagnostic launches were retained; the corrected runner granted only the exact OH
helper entry needed by the native workers. All 20 affected local test modules and
syntax checks passed for the reboot receipt correction.

## Independent review corrections

The first independent OH review found a missing final Resume ordering check for
Claude's child-only personal Stop. The final transfer now reads the corroborating
child interruption and spawn-linked native metadata for the current owner, including
after retention. An answer before that Stop is rejected in either conversation; an
answer after it is accepted. A correlated successful coordinator `TaskStop` remains
cleanup and does not revoke the answer that authorized recovery. Partially saved
personal Stop evidence waits for its occurrence record instead of granting transfer.

A disposable Claude 2.1.304 `TaskStop` probe saved its successful parent call/result
but neither the personal interruption marker nor `stoppedByUser`. The earlier native
interrupt probe saved both. Read-only replay of those actual records and the focused
continuation regression verify the distinction; this is not a new physical UI ordering
test or a claim about every host version. The same review also identified a finished
failed launch capturing an unrelated `SubagentStart`; finished entries are now excluded,
while genuinely pending launches still receive their native child attribution.

A second review exposed two sibling paths. Successful coordinator messaging or
native child resumption no longer erases a personal Stop when final Resume ordering
is checked. Cleanup is compared with the lifecycle at the Stop occurrence, so older
cleanup cannot hide a newer personal Stop; incomplete occurrence evidence still waits.
This leaves terminal-result lifecycle handling unchanged. Direct-chat Resume answers
now preserve the same narrowly recognized retry phrases as menu answers, on both
hosts. Original attestation and prepared-effect validation still apply, and unrelated
newer input still supersedes the answer. Focused regressions reproduced both failures
before these corrections; these tests are record fixtures, not new physical UI tests.
