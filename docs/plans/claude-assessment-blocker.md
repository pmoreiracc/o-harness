# Confirmed Claude assessment blocker

Historical investigation notes, preserved on 2026-10-26. Status and authorization
statements below describe their original investigation stages, not current authority
or current release readiness. The synchronous and background result readers now
contain the described handback and TaskStop handling. See
[the current acceptance summary](release-compatibility.md#checkpoint-status-2026-10-26)
for verification limits; these notes are not proof of native acceptance of the final build.

Read-only investigation of the current native Claude Deliver trial confirmed that the assessment completed before OH first refused retention. The native synchronous Agent result already contained completion status and the handback report. The acknowledged child handback had no outstanding tool calls.

OH recognized completion but its report extraction required a separately forwarded user record. Claude delivered the handback during the existing parent turn through an attachment instead. OH ignored the report already saved in the completed Agent result, repeatedly mislabeled this as delayed saving, and stopped before implementation.

Required correction: accept the bound native Agent completion payload after matching it to the acknowledged terminal child handback, retaining parent/call/child/profile checks and quiescence. Reuse the existing completed assessment and authority. Extend the existing handback regression for synchronous delivery while keeping asynchronous behavior covered. Do not add prose parsing, another runner, replacement assessments, allowance resets or user gates.

Status: diagnosis confirmed; implementation and verification pending. Preserve the other locally authorized fixes. No push or OH dev activation authorized. The GitHub issue comment was not published: automatic approval review rejected it as internal diagnostic information. This local note contains no raw transcript, tokens, saved receipts, session identifiers or consumer paths.

Implementation update: the shared Claude reader now accepts the exact bound Agent completion payload when it matches the acknowledged child handback. It also clears earlier progress text after subsequent child actions. The exact failure was reproduced before the fix; synchronous and asynchronous handback cases, invalid attribution, pending-tool rejection, original-parent transfer, complete Unicode report retention and assessment replay checks pass locally. Syntax and Windows portability checks pass. Full affected-suite verification is in progress. Native Mac snapshot testing and independent review remain pending; no push or dev activation performed.

Final local verification: 184 affected tests across 18 modules were covered, with 12 expected skips. One obsolete idle-preparation expectation in the earlier audit work was corrected to assert preserved history and finite grants, then its full test passed. All other affected tests passed in the broad run. Required syntax, Windows portability and diff checks passed. The Claude source fix is ready locally; the live Mac snapshot is unchanged. Native snapshot testing and fresh independent review remain before publication. No push, dev activation or consumer-run mutation performed.

## Follow-up: background repair recovery after the pushed handback fix

Read-only Mac inspection confirmed the pushed fix was installed and the previous assessment was recovered; the workflow proceeded through implementation and two independent reviews. Repeated blocking families selected the configured complex repair profile (Opus/high), but the coordinator launched Sonnet/medium. The binding guard correctly rejected it, including after the spawn locator was corrected.

Recovery then failed. The native single-agent stop acknowledgement used task_id/task_type fields rather than agentId/status, which the result reader does not recognize. The coordinator subsequently resumed the rejected implementation agent solely to request a final retirement handback. That handback was natively acknowledged and saved as a queued-command attachment absorbed during the parent turn; the reader only accepts top-level peer user messages or completed synchronous Agent handbackReport payloads. The asynchronous launch result remained async_launched. Thus the rejected attempt could not be settled and prevented a replacement repair.

The earlier late-binding message recovered successfully and is not the cause of this later block. The prior synchronous fix did not cover the whole background-delivery family. Required follow-up: use each admitted launch profile; recognize the actual native background handback envelope and applicable cancellation records while retaining child/call attribution, quiescence, failed-attempt history, review allowances and task approval. Do not turn a child statement that it has retired into authority; verify native records. Preserve known host descendant-cancellation limitation #81 and do not accept cancellation as proof that untracked commands have stopped. Existing implementation and two review results remain saved.

Status: diagnosis only; no consumer or source changes, retries or activation performed in this inspection. The Mac connection became unavailable before the final source-agent report could be fetched; the causal records and preliminary conclusion above were returned before disconnection. Any later continuation remains unverified.
