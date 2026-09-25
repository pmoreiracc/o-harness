#!/usr/bin/env bash
# The only way a task changes state. Ticks exactly one box and proves it.
#
# Usage:  complete.sh <design-doc-number> <task-number>
#
# Exit 0  ticked, or already ticked with the tick still uncommitted — the interrupted-
#         completion recovery path, admitted only when it is still the canonical task
# Exit 1  error, or the edit changed more than the one line it was allowed to
# Exit 4  the rounds used exceed the window and no human grant covers them (ADR-0044)
# Exit 5  no exact-tree attempt, or its semantic outcome is not yet authorized
# Exit 8  the task-window gate does not admit this task on a delivery branch (ADR-0045).
#         On the pending path: not covered by a recorded continue grant — present the task
#         checkpoint; or the boundary's recorded choice is a terminal `pr` — re-run next.sh,
#         which routes exit 9 to Finish with PR instead. During recovery: restore the
#         doc's uncommitted tick before presenting the checkpoint — a grant recorded over it
#         would project from the dirty tree and cover the wrong task; task_choice_add
#         (task-ledger.sh) refuses to record any choice while the doc is dirty, for the
#         same reason.
#
# stdout on success: the commit trailer to carry into the task's commit message. The round
# count in it is derived from immutable starts (plus historical rounds), never self-reported.
#
# Why a script rather than an edit: a state transition made by a model is a state
# transition that can be creative. This one changes three characters or fails.
set -uo pipefail

DOC_NUM="${1:-}"
TASK="${2:-}"

shift 2 2>/dev/null || true
while [ $# -gt 0 ]; do
  case "$1" in
    *) echo "complete.sh: unknown argument '$1' (--rounds was removed; the count is derived from review evidence — ADR-0044)." >&2; exit 1 ;;
  esac
done

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
. "$(cd "$DIR/.." && pwd)/review-receipt.sh" || {
  echo "complete.sh: shared review receipt contract is missing or unreadable." >&2
  exit 1
}
. "$(cd "$DIR/.." && pwd)/round-ledger.sh" || {
  echo "complete.sh: round-window contract is missing or unreadable." >&2
  exit 1
}
. "$DIR/freeze.sh" || {
  echo "complete.sh: freeze transition is missing or unreadable." >&2
  exit 1
}
. "$(cd "$DIR/.." && pwd)/lib.sh" || {
  echo "complete.sh: core/lib.sh is missing or unreadable." >&2
  exit 1
}
. "$(cd "$DIR/.." && pwd)/task-ledger.sh" || {
  echo "complete.sh: task-window contract is missing or unreadable." >&2
  exit 1
}

case "$DOC_NUM$TASK" in
  *[!0-9]*|"") echo "usage: complete.sh <design-doc-number> <task-number>" >&2; exit 1 ;;
esac

FILE=$(task_design_file "$ROOT" "$DOC_NUM") || {
  echo "complete.sh: no design doc matching docs/design/$DOC_NUM-*.md" >&2
  exit 1
}

# -e on every grep below: these patterns start with "-", and BSD grep parses a leading
# dash as an option. Without it the script reports "no such task" for every task.
PENDING="- [ ] **$TASK.**"
DONE="- [x] **$TASK.**"

if ! grep -qFe "$PENDING" "$FILE" && ! grep -qFe "$DONE" "$FILE"; then
  echo "complete.sh: no task $TASK in $FILE." >&2
  exit 1
fi

# A prior invocation may have replaced the lifecycle doc and then stopped before closing the
# consumed series. The immutable pre-mutation intent proves that exact interrupted transition.
RECOVERY_OUTPUT=$(review_consumption_recover_current "$ROOT" "complete:$DOC_NUM:$TASK" "$FILE" 2>/dev/null)
if [ $? -eq 0 ]; then
  echo "complete.sh: recovered the already-applied task transition and closed its review series." >&2
  printf '%s\n' "$RECOVERY_OUTPUT"
  exit 0
fi

# --- the review must have seen THIS tree -------------------------------------------
# Not "was a review mentioned" but "does a retained attempt cover the working tree as it
# stands". Any edit after the review moves the digest and invalidates authority, so
# fixing something post-review and quietly ticking the box is not reachable from here.
DIGEST=$("$DIR/tree-digest.sh")
if [ -z "$DIGEST" ]; then
  echo "STOP: cannot fingerprint the working tree, so the review cannot be verified." >&2
  echo "complete.sh runs inside a git repository. Failing closed." >&2
  exit 5
fi
REVIEW_KEY=$(review_current_key "$ROOT" 2>/dev/null)
REVIEW_KEY_STATUS=$?
if [ "$REVIEW_KEY_STATUS" -ne 0 ]; then
  echo "STOP: cannot resolve the review key for the current delivery authority." >&2
  echo "No review attempt can be selected safely until that authority input is readable." >&2
  exit 5
fi

if ! review_receipt_validate "$ROOT" "$DIGEST"; then
  echo "STOP: no review of the current tree (digest $DIGEST)." >&2
  echo "" >&2
  # Preserve a precise diagnostic for strict-format evidence created before ADR-0051.
  if review_rejection_note "$ROOT" "$DIGEST" >&2; then
    exit 5
  fi
  echo "Delegate the diff to a newly spawned invariant-reviewer. Its attempt is written by" >&2
  echo "the host hooks, not by you, which is the whole point — a review that was" >&2
  echo "skipped and a review that was described are indistinguishable in prose." >&2
  echo "" >&2
  # Only validated history for this exact task key can explain a stale review. Evidence for
  # another branch/task says nothing about this subject (ADR-0047).
  if [ -n "$REVIEW_KEY" ] && review_key_has_history "$ROOT" "$REVIEW_KEY"; then
    echo "There are review attempts for earlier trees of this task, so its code changed after review." >&2
    echo "Re-review: whatever was fixed afterwards has not been looked at." >&2
  fi
  exit 5
fi

# --- the semantic outcome must authorize this exact tree ------------------------------------
# Clean attempts authorize directly. A host-written exact-tree human resolution may authorize
# concerns and mechanically completed scope disposition, but no record can waive a blocker.
AUTH_ATTEMPT=$(review_receipt_attempt "$ROOT" "$DIGEST" 2>/dev/null || true)
if ! review_completion_authorized "$ROOT" "$DIGEST"; then
  if [ -n "$AUTH_ATTEMPT" ]; then
    OUTCOME=$(jq -r '.outcome' "$AUTH_ATTEMPT/completion.json" 2>/dev/null || echo ambiguous)
    TRANSITION=$(review_required_transition "$OUTCOME" 2>/dev/null || echo human-ambiguous)
    echo "STOP: review attempt ${AUTH_ATTEMPT##*/} does not authorize completion." >&2
    echo "Semantic outcome: $OUTCOME. Required transition: $TRANSITION." >&2
    review_completion_diagnose "$ROOT"
  else
    echo "STOP: the historical review of this tree is not clean and does not authorize completion." >&2
  fi
  exit 5
fi

# The configured series window is renewable by a recorded human grant. The count is derived
# from attempt starts plus historical rounds, never from a number the model reports. Valid
# exact-tree review evidence exists above, so at least one round
# happened; floor the count there in the rare case the ledger did not capture it.
KEY=$(round_task_key "$DOC_NUM" "$TASK")
ROUNDS=$(round_count "$ROOT" "$KEY") || {
  echo "REFUSED: review-attempt evidence is malformed or unreadable; no completion applied. Inspect round-status.sh and repair the named prerequisite through supported tooling; do not replace evidence or infer zero rounds." >&2
  exit 2
}
[ "$ROUNDS" -ge 1 ] || ROUNDS=1
WINDOW=$(round_window "$ROOT" "$KEY") || {
  echo "REFUSED: review-grant evidence is malformed or unreadable; no completion applied. Inspect round-status.sh and preserve the existing evidence while diagnosing; request external repair if needed." >&2
  exit 2
}
if [ "$ROUNDS" -gt "$WINDOW" ]; then
  echo "STOP: task $TASK used $ROUNDS review rounds; the window is $WINDOW and no human grant" >&2
  echo "covers the rest. No task was completed. A late grant cannot authorize past attempts." >&2
  echo "Retain the work and findings. Offer human takeover or an explicitly authorized unresolved PR handoff; do not present renewal as a repair." >&2
  if [ -n "${CODEX_SESSION_ID:-}${CODEX_HOOK:-}" ]; then codex_gate_present review-window exceeded >&2
  else printf '%s\n' "$ROUND_STOP_TAKE_OVER_LABEL" "$ROUND_STOP_ESCALATE_LABEL" >&2; fi
  exit 4
fi

# Render the task tick and, when it is the last one, frozen lifecycle metadata together.
# The shared renderer cannot write. This review-authorized wrapper inspects its exact diff and
# atomically replaces the doc once, so there is no interruption point between the final
# tick and freeze and no exported mutation primitive around the ADR-0047 workflow gate.
WAS_PENDING=0
OLD_TASK_LINE=""
NEW_TASK_LINE=""
if grep -qFe "$PENDING" "$FILE"; then
  COUNT=$(grep -cFe "$PENDING" "$FILE") || {
    echo "complete.sh: cannot count task $TASK in $FILE." >&2
    exit 1
  }
  if [ "$COUNT" -ne 1 ]; then
    echo "complete.sh: task $TASK appears $COUNT times in $FILE. Refusing to guess." >&2
    exit 1
  fi
  WAS_PENDING=1
  OLD_TASK_LINE=$(grep -Fe "$PENDING" "$FILE") || {
    echo "complete.sh: cannot read task $TASK in $FILE." >&2
    exit 1
  }
  NEW_TASK_LINE="$DONE${OLD_TASK_LINE#"$PENDING"}"
fi

# A task-window grant is an admission token, not merely a hint printed by next.sh. Check
# pending transitions against the committed boundary before editing the design doc. An
# already-done, still-uncommitted task is the documented recovery path after an interrupted
# tick, but recovery is not exempt from the gate: it reconstructs the pre-tick state and
# runs the same canonical-first-runnable and window-admission checks the pending path does,
# below, before proceeding to the receipt/freeze checks.
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || {
  echo "complete.sh: cannot resolve the current branch." >&2
  exit 1
}
case "$BRANCH" in
  deliver/*)
    TASK_US=$(printf '\037')
    TSV=$("$DIR/plan.sh" "$DOC_NUM") || exit 1
    if [ "$WAS_PENDING" = 1 ]; then
      task_authority_load "$ROOT" "$BRANCH" "$DOC_NUM" "$TSV" || exit 1
      TRUSTED_TSV="$TASK_AUTHORITY_TRUSTED_TSV"
      OWNER="$TASK_AUTHORITY_OWNER"
      CANDIDATE_LINE=$(task_first_runnable "$TRUSTED_TSV" "$OWNER" "")
      CANDIDATE_STATUS=$?
      case "$CANDIDATE_STATUS" in
        0) ;;
        1) echo "complete.sh: task $TASK is not the next runnable task for track '$OWNER'." >&2; exit 1 ;;
        *) echo "complete.sh: cannot derive the reviewed runnable-task order." >&2; exit 1 ;;
      esac
      CANDIDATE=${CANDIDATE_LINE%%"$TASK_US"*}
      if [ "$CANDIDATE" != "$TASK" ]; then
        echo "complete.sh: task $TASK is not the next runnable task (the gate selects $CANDIDATE)." >&2
        exit 1
      fi
      task_gate_evaluate "$ROOT" "$BRANCH" "$DOC_NUM" "$TSV" "$TASK" || exit 1
      case "$TASK_GATE_STATE" in
        fresh)
          task_fresh_branch_resume_valid "$ROOT" "$BRANCH" || {
            echo "complete.sh: fresh task authority requires a newly created dirty delivery branch at refreshed trunk." >&2
            exit 1
          }
          ;;
        covered) ;;
        checkpoint|stop|pr)
          echo "complete.sh: task $TASK is not admitted by the current task window (state: $TASK_GATE_STATE)." >&2
          exit 8 ;;
        *) echo "complete.sh: task-window state is unreadable." >&2; exit 1 ;;
      esac
    else
      # Recovery is valid only for the exact interrupted transition: after wording-only
      # edits cancel, the working tree must contain exactly this task's pending->done change
      # and no other checkbox transition in either direction. Reconstruct the pre-transition
      # TSV before evaluating the gate.
      DIFF=$(git -C "$ROOT" diff --text --unified=0 --no-ext-diff HEAD -- "${FILE#"$ROOT"/}" 2>/dev/null) || exit 1
      TRANSITIONS=$(task_transition_records_from_diff "$DIFF") || exit 1
      [ "$TRANSITIONS" = "done"$'\t'"$TASK" ] || {
        echo "complete.sh: already-done recovery requires exactly one uncommitted pending-to-done transition for task $TASK." >&2
        exit 1
      }
      PRE_TSV=$(printf '%s\n' "$TSV" | awk -F"$TASK_US" -v OFS="$TASK_US" -v n="$TASK" \
        '{ if ($1 == n) $2 = "pending"; print }') || exit 1
      task_authority_load "$ROOT" "$BRANCH" "$DOC_NUM" "$PRE_TSV" || exit 1
      PRE_TRUSTED_TSV="$TASK_AUTHORITY_TRUSTED_TSV"
      OWNER="$TASK_AUTHORITY_OWNER"
      CANDIDATE_LINE=$(task_first_runnable "$PRE_TRUSTED_TSV" "$OWNER" "")
      CANDIDATE_STATUS=$?
      case "$CANDIDATE_STATUS" in
        0) ;;
        1) echo "complete.sh: task $TASK is not the next runnable task for track '$OWNER'." >&2; exit 1 ;;
        *) echo "complete.sh: cannot derive the reviewed runnable-task order." >&2; exit 1 ;;
      esac
      CANDIDATE=${CANDIDATE_LINE%%"$TASK_US"*}
      if [ "$CANDIDATE" != "$TASK" ]; then
        echo "complete.sh: task $TASK is not the next runnable task (the gate selects $CANDIDATE)." >&2
        exit 1
      fi
      task_gate_evaluate "$ROOT" "$BRANCH" "$DOC_NUM" "$PRE_TSV" "$TASK" || exit 1
      case "$TASK_GATE_STATE" in
        fresh)
          task_fresh_branch_resume_valid "$ROOT" "$BRANCH" || {
            echo "complete.sh: fresh task recovery requires a newly created dirty delivery branch at refreshed trunk." >&2
            exit 1
          }
          ;;
        covered) ;;
        *)
          echo "complete.sh: task $TASK is not admitted by the current task window (state: $TASK_GATE_STATE)." >&2
          echo "The design doc still has this task's uncommitted tick. Inspect $FILE and reverse only" >&2
          echo "the attributable tick/lifecycle transition, preserving other edits, before the checkpoint so a continue grant" >&2
          echo "is projected from HEAD and covers this task, not the one after it." >&2
          exit 8
          ;;
      esac
    fi
    ;;
  *)
    # Minimal isolated callers used by the receipt-contract tests do not carry the
    # task-window module; preserve their pre-window checks. A real checkout always has it,
    # and then every non-delivery ref (including detached HEAD) fails closed.
    if [ -f "${OH_HOME:-$ROOT}/core/task-ledger.sh" ]; then
      echo "complete.sh: task completion requires the canonical delivery branch; current branch is '$BRANCH'." >&2
      exit 1
    fi
    ;;
esac

OLD_STATUS=$(fm_value "$FILE" status) || exit 1
DOC_DIR=$(dirname "$FILE")
mkdir -p "$ROOT/.deliver/transitions" || exit 1
TMP=$(mktemp "$ROOT/.deliver/transitions/.complete.XXXXXX") || {
  echo "complete.sh: could not create an ignored replacement file." >&2
  exit 1
}
trap 'rm -f "${TMP:-}"' EXIT
cp -p "$FILE" "$TMP" || {
  echo "complete.sh: could not preserve the design doc's file mode. Aborted." >&2
  exit 1
}
if ! freeze_render "$DOC_NUM" "$TASK" > "$TMP"; then exit 1; fi
freeze_diff_validate "$FILE" "$TMP" "$OLD_TASK_LINE" "$NEW_TASK_LINE" || exit 1
if [ "$(grep -cFe "$DONE" "$TMP")" -ne 1 ]; then
  echo "complete.sh: proposed replacement did not complete exactly task $TASK. Aborted." >&2
  exit 1
fi
NEW_STATUS=$(fm_value "$TMP" status) || exit 1
DELIVERED=$(fm_value "$TMP" delivered) || exit 1
TRAILERS="Review-Rounds: $ROUNDS"
if [ -n "$AUTH_ATTEMPT" ]; then
  PR_RESOLUTION=$(review_attempt_pr_resolution_id "$ROOT" "$AUTH_ATTEMPT" 2>/dev/null || true)
fi
if [ -n "${PR_RESOLUTION:-}" ]; then
  TRAILERS="$TRAILERS
Review-Resolution: $PR_RESOLUTION"
fi

if cmp -s "$FILE" "$TMP"; then
  if [ "$OLD_STATUS" = frozen ]; then
    echo "freeze.sh: design doc $DOC_NUM is already frozen in $DELIVERED — nothing to do." >&2
  fi
else
  if [ -n "$AUTH_ATTEMPT" ]; then
    review_consumption_intent_start "$ROOT" "$AUTH_ATTEMPT" "complete:$DOC_NUM:$TASK" \
      "$FILE" "$TMP" "$TRAILERS" || {
      echo "complete.sh: could not publish the recoverable transition intent. The design is unchanged." >&2
      exit 1
    }
  fi
  if ! mv "$TMP" "$FILE"; then
    echo "complete.sh: could not atomically replace $(basename "$FILE"). The original is unchanged." >&2
    exit 1
  fi
  TMP=""
fi
if [ -n "$AUTH_ATTEMPT" ] && [ -f "$AUTH_ATTEMPT/consumption-intent/intent.json" ]; then
  RECOVERY_OUTPUT=$(review_consumption_recover "$ROOT" "$AUTH_ATTEMPT" "complete:$DOC_NUM:$TASK" "$FILE") || {
    echo "complete.sh: task changed, but its recoverable transition could not be completed." >&2
    exit 1
  }
else
  review_completion_close "$ROOT" "$DIGEST" "$REVIEW_KEY" || {
    echo "complete.sh: task changed, but the consumed review series could not be closed." >&2
    exit 1
  }
  RECOVERY_OUTPUT="$TRAILERS"
fi
if [ "$OLD_STATUS" != frozen ] && [ "$NEW_STATUS" = frozen ]; then
  echo "froze design doc $DOC_NUM in $DELIVERED" >&2
fi
if [ "$WAS_PENDING" = 1 ]; then
  echo "ticked task $TASK in $(basename "$FILE")" >&2
else
  echo "task $TASK in $DOC_NUM is already complete — nothing to do." >&2
fi
printf '%s\n' "$RECOVERY_OUTPUT"
# ^ derived from receipts (ADR-0044), so the trailer commit-msg and verify-delivery still
# require carries a fact, not a self-reported number.
