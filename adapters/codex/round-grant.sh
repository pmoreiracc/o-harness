#!/usr/bin/env bash
# Codex adapter — records a human's renewal of the review-round window (ADR-0044).
#
# Codex exposes the human submission itself through UserPromptSubmit, rather than Claude
# Code's selected AskUserQuestion answer. The raw prompt is recognized as a supported grant
# only when it is the exact canonical label. A substring or flexible regex would turn ordinary prose such
# as "Do not Grant 3 more review rounds" into an approval, which is not invariant 6's
# harness-written record shape.
#
# The event cannot be model-invoked and is not a Bash tool call. The independent task and
# spent-window guards make the phrase harmless outside the checkpoint.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
if [ -z "$ROOT" ] || [ ! -f "${OH_HOME:-$ROOT}/core/hooks/lib.sh" ]; then
  echo "GUARDRAIL CANNOT RUN: the repository root or core/hooks/lib.sh cannot be resolved." >&2
  exit 2
fi

. "${OH_HOME:-$ROOT}/core/hooks/lib.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/hooks/lib.sh is missing or unreadable." >&2
  exit 2
}
hook_init

. "${OH_HOME:-$ROOT}/core/round-ledger.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/round-ledger.sh is missing or unreadable." >&2
  exit 2
}

# The hook sees raw human text, not a structured selected-answer leaf. Let jq compare the
# JSON string directly: a shell command substitution would strip trailing newlines and turn a
# multiline submission into an apparent exact match. The label recorded below is therefore
# precisely what the person submitted.
CODEX_GRANT_COMMAND="$ROUND_GRANT_COMMAND"
PROMPT=$(printf '%s' "$PAYLOAD" | jq -r '.prompt // ""' 2>/dev/null)
ROUND_ACTION=""
case "$PROMPT" in
  "$CODEX_GRANT_COMMAND") ROUND_ACTION=grant ;;
  "$ROUND_STOP_TAKE_OVER_COMMAND") ROUND_ACTION=take-over ;;
  "$ROUND_STOP_ESCALATE_COMMAND") ROUND_ACTION=escalate-pr ;;
esac
EXACT=$(printf '%s' "$PAYLOAD" | jq -r --arg p "$PROMPT" '.prompt == $p')
[ -n "$ROUND_ACTION" ] || EXACT=false

if [ "$EXACT" != "true" ]; then
  # ADR-0046 Decision 3: at the ceiling, an answer matching none of the three checkpoint
  # labels reports the miss instead of failing quietly (the exact incident this covers: a
  # human typing "grant 3 more review rounds" in the wrong case hears nothing back). Every
  # other UserPromptSubmit is ordinary conversation, not a checkpoint answer at all, so this
  # stays far short of a substring or fuzzy match — prose that merely mentions "review
  # rounds" normalizes to nothing close to any label — and only bothers the ledger when the
  # prompt, once trimmed of whitespace/case/newlines, IS one of the three labels exactly.
  norm() {
    printf '%s' "$1" | tr '\n\t' '  ' \
      | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/[[:space:]][[:space:]]*/ /g' \
      | tr '[:upper:]' '[:lower:]'
  }
  NP=$(norm "$PROMPT")
  NEAR=""
  [ "$NP" = "$CODEX_GRANT_COMMAND" ] && NEAR=grant
  [ -n "$NEAR" ] || { [ "$NP" = "$ROUND_STOP_TAKE_OVER_COMMAND" ] && NEAR=stop; }
  [ -n "$NEAR" ] || { [ "$NP" = "$ROUND_STOP_ESCALATE_COMMAND" ] && NEAR=stop; }
  [ -n "$NEAR" ] || exit 0

  BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
  KEY=$(round_key_for "$ROOT" "$BRANCH" 2>/dev/null) || exit 0
  USED=$(round_count "$ROOT" "$KEY") || exit 0
  WINDOW=$(round_window "$ROOT" "$KEY") || exit 0
  if [ -n "$NEAR" ] && [ "$USED" -eq "$WINDOW" ]; then
    SERIES=$(review_series_find_for_key "$ROOT" "$KEY" 2>/dev/null || true)
    if [ -n "$SERIES" ]; then
      DIGEST=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh") || exit 2
      review_window_ready "$ROOT" "$SERIES" "$DIGEST" || exit 2
    fi
    echo "round-grant: the review-round checkpoint for $KEY ($USED used / $WINDOW granted) was" >&2
    echo "answered with a near match, so nothing was recorded." >&2
    codex_gate_present review-window - >&2
  fi
  exit 0
fi

BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
SESSION="${CODEX_SESSION_ID:-$(hook_field '.session_id')}"
review_detached_context_activate_for_session "$ROOT" "$BRANCH" "$SESSION" 0 || exit 0
KEY=$(round_key_for "$ROOT" "$BRANCH" 2>/dev/null) || exit 0

# (c) The task must be exactly at its ceiling. A late grant cannot retroactively authorize a
# review that already crossed the ungranted window.
if ! USED=$(round_count "$ROOT" "$KEY"); then
  echo "round-grant: FAILED to read the review-round ledger for $KEY. No grant was recorded;" >&2
  echo "Preserve the evidence and repair its read failure. Reuse provable unchanged host approval; otherwise present the current gate." >&2
  exit 0
fi
if ! WINDOW=$(round_window "$ROOT" "$KEY"); then
  echo "round-grant: FAILED to read the review-round grant ledger for $KEY. No grant was" >&2
  echo "recorded; preserve the evidence and repair its read failure. Reuse provable unchanged host approval; otherwise present the current gate." >&2
  exit 0
fi
if [ "$USED" -lt "$WINDOW" ] || { [ "$USED" -gt "$WINDOW" ] && [ "$ROUND_ACTION" = grant ]; }; then
  if [ "$USED" -gt "$WINDOW" ]; then
    echo "round-grant: exact grant phrase received for $KEY after its window was already" >&2
    echo "exceeded ($USED used / $WINDOW granted); no late grant can authorize an earlier review." >&2
    exit 0
  fi
  echo "round-grant: exact grant phrase received for $KEY, but round $USED is within the" >&2
  echo "window of $WINDOW — nothing to renew yet, so no grant was recorded." >&2
  exit 0
fi

DIGEST=$("${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh" 2>/dev/null)
[ -n "$DIGEST" ] || {
  echo "round-grant: could not fingerprint the working tree; no grant was recorded." >&2
  exit 0
}

if [ "$ROUND_ACTION" != grant ]; then
  SOURCE="${CODEX_CHOICE_SOURCE:-codex:${CODEX_SESSION_ID:-$(hook_field '.session_id')}:$(hook_field '.turn_id')}"
  if review_series_handoff_record "$ROOT" "$KEY" "$ROUND_ACTION" "$SOURCE" "$DIGEST"; then
    echo "round-grant: recorded '$PROMPT'; it does not authorize completion." >&2
  else
    echo "round-grant: handoff was not saved. Honor the requested stop now; retain the work and report its unsaved status. Inspect round-status.sh before repairing this record." >&2
    exit 2
  fi
  exit 0
fi

SOURCE="${CODEX_CHOICE_SOURCE:-codex:${CODEX_SESSION_ID:-$(hook_field '.session_id')}:$(hook_field '.turn_id')}"
if round_grant_add_v2 "$ROOT" "$KEY" "$DIGEST" "$USED" "$WINDOW" "$SOURCE"; then
  echo "round-grant: recorded a human grant for $KEY — review window $WINDOW → $(round_window "$ROOT" "$KEY")." >&2
else
  echo "round-grant: FAILED to record the human's grant for $KEY. The renewal was not saved;" >&2
  echo "The ceiling still applies. Inspect round-status.sh and repair the publication failure; retry only with provable unchanged host approval, otherwise present the current gate." >&2
  exit 2
fi
exit 0
