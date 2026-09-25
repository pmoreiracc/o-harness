#!/usr/bin/env bash
# Record one exact host-owned human disposition for the latest semantic review outcome.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 2
. "${OH_HOME:-$ROOT}/core/hooks/lib.sh" || exit 2
. "${OH_HOME:-$ROOT}/core/review-workflow.sh" || exit 2
. "${OH_HOME:-$ROOT}/core/round-ledger.sh" || exit 2
hook_init

ISSUE_URL=""
if [ -n "${CODEX_HOOK:-}" ]; then
  SESSION="${CODEX_SESSION_ID:-$(hook_field '.session_id')}"
  ANSWER=$(hook_field '.prompt')
  case "$ANSWER" in 'route scope to https://'*) ISSUE_URL="${ANSWER#route scope to }" ;; esac
  case "$ANSWER" in
    'fix concerns'|'accept concerns'|'route scope'|'dismiss scope'|\
    'fix concerns and route scope'|'fix concerns and dismiss scope'|\
    'accept concerns and route scope'|'accept concerns and dismiss scope'|\
    'review again'|'take over'|'stop scope routing'|'route scope to https://'*) ;;
    *) exit 0 ;;
  esac
  SOURCE="${CODEX_CHOICE_SOURCE:-codex:$SESSION:$(hook_field '.turn_id')}"
else
  [ "$(hook_field '.tool_name')" = AskUserQuestion ] || exit 0
  # Establish that this is a complete supported menu before reading its answer.
  MENU_OUTCOME=""
  for CANDIDATE in concern scope concern+scope ambiguous; do
    if hook_menu_matches "$(review_choice_labels "$CANDIDATE")"; then MENU_OUTCOME="$CANDIDATE"; break; fi
  done
  DESTINATION_LABEL=$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.questions[0].options[]?.label | select(startswith("Route scope to https://"))' 2>/dev/null)
  if [ -z "$MENU_OUTCOME" ]; then
    [ -n "$DESTINATION_LABEL" ] && hook_menu_matches "$(printf '%s\n' "$DESTINATION_LABEL" 'Stop scope routing')" || exit 0
    MENU_OUTCOME=scope-destination
  fi
  LABEL=$(hook_single_human_answer)
  case "$LABEL" in 'Route scope to https://'*) ISSUE_URL="${LABEL#Route scope to }" ;; esac
  ANSWER=$(printf '%s' "$LABEL" | tr '[:upper:]' '[:lower:]')
  SESSION=$(hook_field '.session_id')
  SOURCE="claude:$SESSION:$(hook_field '.tool_use_id')"
fi

if [ "$ANSWER" = 'stop scope routing' ] && { [ -n "${CODEX_HOOK:-}" ] || [ "$MENU_OUTCOME" = scope-destination ]; }; then
  echo 'review-choice: stopped scope routing; pending findings and work are retained. No completion or PR authorized.' >&2
  exit 0
fi
TREE=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh") || exit 2
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 2
review_detached_context_activate_for_session "$ROOT" "$BRANCH" "$SESSION" 0 || exit 2
KEY=$(round_key_for "$ROOT" "$BRANCH" 2>/dev/null) || exit 2
ATTEMPT=$(review_attempt_latest_for_tree "$ROOT" "$KEY" "$TREE" 2>/dev/null) || {
  echo 'review-choice: no retained review matches this tree; nothing recorded. Inspect round-status.sh and retain pending output or review the current tree before presenting its choices.' >&2
  exit 2
}
OUTCOME=$(jq -r '.outcome' "$ATTEMPT/completion.json" 2>/dev/null) || exit 2
if [ -z "${CODEX_HOOK:-}" ]; then
  [ "$MENU_OUTCOME" = "$OUTCOME" ] || [ "$MENU_OUTCOME" = scope-destination ] || exit 0
  if ! printf '%s' "$PAYLOAD" | jq -e --arg label "$LABEL" \
    '[.tool_input.questions[0].options[].label] | index($label)!=null' >/dev/null 2>&1; then
    echo 'review-choice: the answer was missing, ambiguous, or not one of the offered choices. Nothing recorded; present the same complete single-select gate:' >&2
    printf '%s' "$PAYLOAD" | jq -r '.tool_input.questions[0].options[].label' >&2
    exit 2
  fi
fi
if [ -n "$ISSUE_URL" ]; then
  if [ -z "${CODEX_HOOK:-}" ]; then
    EXPECTED=$(printf '%s\n' "Route scope to $ISSUE_URL" "Stop scope routing" | LC_ALL=C sort)
    OFFERED=$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.questions[0].options[].label' 2>/dev/null | LC_ALL=C sort)
    [ "$OFFERED" = "$EXPECTED" ] || exit 0
  fi
  review_scope_issue_record "$ROOT" "$ATTEMPT" "$ISSUE_URL" "$SOURCE" || {
    echo "review-choice: could not confirm $ISSUE_URL: stale, invalid, conflicting, or a publication failed. Inspect $ATTEMPT/scope-destination.json and scope-transition.json before retrying; preserve any saved route." >&2
    exit 2
  }
  echo "review-choice: linked the retained scope finding to $ISSUE_URL." >&2
  exit 0
fi
CHOICE=$(review_choice_parse "$OUTCOME" "$ANSWER" 2>/dev/null) || {
  echo "review-choice: '$ANSWER' is missing, ambiguous, or not valid for $OUTCOME; nothing recorded." >&2
  review_attempt_summary "$ATTEMPT" >&2
  if [ -n "${CODEX_HOOK:-}" ]; then codex_gate_present review "$OUTCOME" >&2; else review_choice_labels "$OUTCOME" >&2; fi
  exit 2
}

review_resolution_record "$ROOT" "$ATTEMPT" "$CHOICE" "$SOURCE" "$TREE" || {
  echo "review-choice: could not finish '$CHOICE'. Inspect $ATTEMPT/resolution.json before retrying: a choice may already be saved. Preserve it and resume with review-route-scope.sh; present a new decision only if none was saved or it no longer applies." >&2
  exit 2
}
case "$CHOICE" in
  *route-scope*) SCOPE_ACTION=route-scope ;;
  *dismiss-scope*) SCOPE_ACTION=dismiss-scope ;;
  *) SCOPE_ACTION="" ;;
esac
if [ -n "$SCOPE_ACTION" ]; then
  if review_scope_apply "$ROOT" "$ATTEMPT" "$SCOPE_ACTION"; then
    echo "review-choice: recorded '$CHOICE' and applied the generated scope disposition." >&2
  else
    STATUS=$(jq -r '.status' "$ATTEMPT/scope-transition.json" 2>/dev/null || echo failed)
    echo "review-choice: recorded '$CHOICE'; scope routing is pending ($STATUS). Finding retained at $ATTEMPT/raw.md." >&2
    echo 'If no mutable destination exists, prepare a concrete same-repository issue URL and present its confirmation gate. If the generated write failed, repair that cause and rerun review-route-scope.sh; do not ask for the saved choice again.' >&2
    exit 2
  fi
elif [ "$CHOICE" = take-over ]; then
  SERIES=$(jq -r '.seriesId' "$ATTEMPT/start.json") || exit 2
  review_series_close "$ROOT" "$SERIES" take-over || exit 2
  echo "review-choice: recorded human takeover; this attempt does not authorize completion." >&2
else
  echo "review-choice: recorded human choice '$CHOICE' for attempt ${ATTEMPT##*/}." >&2
fi
