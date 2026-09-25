#!/usr/bin/env bash
# GUARDRAIL — records a human's renewal of the review-round window (ADR-0044).
#
# Fires on PostToolUse for AskUserQuestion. When the human selected the renewal option at the
# round-ceiling checkpoint, this writes the grant artifact that complete.sh and the loop read.
#
# Why this is the strong link, exactly as review-receipt.sh is for the reviewer: the grant is
# written by the harness in response to the human's real selection, not by the model narrating
# that the human said yes. The model cannot fabricate the answer, and it cannot write the grant
# by hand through supported Edit/Write tools (protect-receipts.sh blocks .deliver/). So
# "the human renewed the window" becomes
# a recorded fact — invariant 6 applied to the harness — instead of a line of prose.
#
# The honest limit is the same one the attempt hook carries: this stops the loop from silently
# continuing past its snapshotted window, not a model determined to trick a human into renewal.
# The fixed-shape summary is shown to the human, and the verdict trend lands in the PR, which
# is where that defence lives.
#
# Triple-guarded against a spurious grant: it writes only when (a) a review-round window can
# be resolved for the current delivery task or explicit non-delivery series, (b) the human's
# *selected* answer matches the
# renewal label, and (c) the window is exactly at its ceiling (used == window). A renewal is
# meaningless before the window is spent, and a late grant cannot retroactively authorize a
# review that already crossed it, so both cases are ignored.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/hooks/lib.sh is missing or unreadable." >&2
  echo "No operation was inspected. Restore this reviewed harness file in the checkout and retry; do not disable the guardrail." >&2
  exit 2
}
hook_init

. "$DIR/../round-ledger.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/round-ledger.sh is missing or unreadable." >&2
  exit 2
}

[ "$(hook_field '.tool_name')" = AskUserQuestion ] || exit 0
ROOT=$(project_root)

# Ignore unrelated or incomplete menus before interpreting their selected answer.
FULL_MENU=$(printf '%s\n' "$ROUND_GRANT_LABEL" "$ROUND_STOP_TAKE_OVER_LABEL" "$ROUND_STOP_ESCALATE_LABEL")
STOP_MENU=$(printf '%s\n' "$ROUND_STOP_TAKE_OVER_LABEL" "$ROUND_STOP_ESCALATE_LABEL")
if hook_menu_matches "$FULL_MENU"; then MENU=full
elif hook_menu_matches "$STOP_MENU"; then MENU=exceeded
else exit 0
fi
ANSWER=$(hook_single_human_answer)
EXACT_GRANT=1
ROUND_ACTION=""
case "$ANSWER" in
  "$ROUND_GRANT_LABEL") ROUND_ACTION=grant ;;
  "$ROUND_STOP_TAKE_OVER_LABEL") ROUND_ACTION=take-over ;;
  "$ROUND_STOP_ESCALATE_LABEL") ROUND_ACTION=escalate-pr ;;
  *) EXACT_GRANT=0 ;;
esac

BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
SESSION=$(hook_field '.session_id')
review_detached_context_activate_for_session "$ROOT" "$BRANCH" "$SESSION" 0 || exit 0
KEY=$(round_key_for "$ROOT" "$BRANCH" 2>/dev/null) || exit 0

# Read the validated evidence ledger only after establishing that this event is the exact grant or a
# genuine review-round checkpoint near miss. Most AskUserQuestion events are unrelated; a
# damaged review ledger must not turn every one of them into a false review warning. An exact
# human grant is different: silently discarding it would make the person believe the window
# was renewed when no durable grant evidence exists, so diagnose the failure and require a re-ask.
if ! USED=$(round_count "$ROOT" "$KEY"); then
  [ "$EXACT_GRANT" = 1 ] || exit 0
  echo "round-grant: FAILED to read the review-round ledger for $KEY. No grant was recorded;" >&2
  echo "preserve the evidence and repair its read failure. Reuse the original host answer only if its unchanged binding is provable; otherwise present the current gate." >&2
  exit 0
fi
if ! WINDOW=$(round_window "$ROOT" "$KEY"); then
  [ "$EXACT_GRANT" = 1 ] || exit 0
  echo "round-grant: FAILED to read the review-round grant ledger for $KEY. No grant was" >&2
  echo "recorded; preserve the evidence and repair its read failure. Reuse the original host answer only if its unchanged binding is provable; otherwise present the current gate." >&2
  exit 0
fi

# Match the applicable menu, including the no-late-renewal overrun case.
if [ "$USED" -gt "$WINDOW" ]; then [ "$MENU" = exceeded ] || exit 0
else [ "$MENU" = full ] || exit 0
fi
SERIES=$(review_series_find_for_key "$ROOT" "$KEY" 2>/dev/null || true)
if [ -n "$SERIES" ]; then
  DIGEST=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh") || exit 0
  review_window_ready "$ROOT" "$SERIES" "$DIGEST" || {
    if [ "$ROUND_ACTION" = take-over ] || [ "$ROUND_ACTION" = escalate-pr ]; then
      echo 'Honor the requested stop now. The findings remain unresolved; no window handoff or completion was recorded.' >&2
    fi
    exit 0
  }
fi
if [ "$EXACT_GRANT" = 0 ]; then
  [ "$USED" -ge "$WINDOW" ] || exit 0
  echo "round-grant: the checkpoint answer was missing, ambiguous, or did not match its options. Nothing recorded. Present the same single-select gate:" >&2
  if [ "$MENU" = full ]; then printf '%s\n' "$FULL_MENU" >&2
  else printf '%s\n' "$STOP_MENU" >&2
  fi
  exit 0
fi

# (c) The task must be exactly at its ceiling. A grant after the ceiling was already crossed
# would retroactively authorize the fourth (or later) review, contrary to ADR-0044.
if [ "$USED" -lt "$WINDOW" ] || { [ "$USED" -gt "$WINDOW" ] && [ "$ROUND_ACTION" = grant ]; }; then
  if [ "$USED" -gt "$WINDOW" ]; then
    echo "round-grant: renewal selected for $KEY after its window was already exceeded" >&2
    echo "($USED used / $WINDOW granted); no late grant can authorize an earlier review." >&2
    exit 0
  fi
  echo "round-grant: renewal selected for $KEY, but round $USED is within the window of" >&2
  echo "$WINDOW — nothing to renew yet, so no grant was recorded." >&2
  exit 0
fi

DIGEST=$("${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh")
[ -n "$DIGEST" ] || {
  echo "round-grant: could not fingerprint the working tree; no grant was recorded." >&2
  exit 0
}

if [ "$ROUND_ACTION" != grant ]; then
  SOURCE="claude:$(hook_field '.session_id'):$(hook_field '.tool_use_id')"
  if review_series_handoff_record "$ROOT" "$KEY" "$ROUND_ACTION" "$SOURCE" "$DIGEST"; then
    echo "round-grant: recorded '$ANSWER'; it does not authorize completion." >&2
  else
    echo "round-grant: Handoff not saved. Honor the requested stop now; preserve work and report the unsaved record. Inspect round-status.sh before repairing." >&2
  fi
  exit 0
fi

if round_grant_add "$ROOT" "$KEY" "$DIGEST" "$USED" "$WINDOW" "$ROUND_GRANT_LABEL"; then
  echo "round-grant: recorded a human grant for $KEY — review window $WINDOW → $(round_window "$ROOT" "$KEY")." >&2
else
  echo "round-grant: FAILED to record the human's grant for $KEY. The renewal was not saved;" >&2
  echo "The ceiling still applies. Repair the publication failure and confirm round-status.sh; reuse provable unchanged host approval, otherwise present the current gate." >&2
fi
exit 0
