#!/usr/bin/env bash
# Allocate and bind one immutable review attempt before the reviewer reads the tree (ADR-0051).
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || exit 2
hook_init
. "$DIR/../review-workflow.sh" || exit 2
. "$DIR/../round-ledger.sh" || exit 2
. "$DIR/../review-request.sh" || exit 2

ROOT=$(project_root)
TOOL=$(hook_field '.tool_name')
if [ -n "${CODEX_HOOK:-}" ]; then
  AGENT=$(hook_field '.agent_type')
  HOST=codex
  OWNER=$(hook_field '.agent_id')
else
  [ "$TOOL" = Agent ] || exit 0
  AGENT=$(hook_field '.tool_input.subagent_type')
  HOST=claude
  OWNER=claude
fi
[ "$AGENT" = invariant-reviewer ] || exit 0
[ -n "$OWNER" ] || {
  echo "missing fresh-reviewer admission: the reviewer has no host-owned identity." >&2
  exit 2
}
SESSION=$(hook_field '.session_id')
[ -n "$SESSION" ] || SESSION=$(hook_field '.conversation_id')
[ -n "$SESSION" ] || {
  echo "review-start: the host supplied no session identity; attribution would be ambiguous." >&2
  exit 2
}

TREE=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh") || exit 2
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 2
if [ "$BRANCH" = HEAD ]; then
  review_detached_context_activate_for_session "$ROOT" "$BRANCH" "$SESSION" 1 || exit $?
  echo "review-start: detached review context $REVIEW_DETACHED_CONTEXT_ID" >&2
fi
KEY=$(round_key_for "$ROOT" "$BRANCH" 2>/dev/null) || exit 2
review_policy_load "$ROOT" || {
  echo "review-start: delivery policy is invalid; no attempt was allocated." >&2
  exit 2
}
USED=$(round_count "$ROOT" "$KEY") || exit 2
WINDOW=$(round_window "$ROOT" "$KEY") || exit 2
[ "$USED" -lt "$WINDOW" ] || {
  echo "review-start: review window spent ($USED used / $WINDOW granted)." >&2
  exit 2
}

INPUT=-
SNAPSHOT=""
REQUEST=-
case "$BRANCH" in
  deliver/*)
    CONTEXT=$(review_request_context "$ROOT" "$BRANCH" 2>/dev/null) || exit 2
    [ "${CONTEXT%%$'\t'*}" = "$KEY" ] || exit 2
    if [ "$HOST" = codex ]; then
      # Codex runs SubagentStart siblings concurrently. The configured readiness hook is
      # validation-only; this allocator is the sole publisher of the retained input.
      printf '%s' "$PAYLOAD" | CODEX_REVIEW_BINDING=1 "$DIR/review-ready-gate.sh" >/dev/null \
        || exit 2
    fi
    INPUT=$(review_request_pending_dir "$ROOT" "$KEY" "$TREE") || exit 2
    review_request_validate_path "$ROOT" "$KEY" "$TREE" "$INPUT/request.md" \
      && [ -f "$INPUT/snapshot.txt" ] && [ ! -L "$INPUT/snapshot.txt" ] \
      && [ "$(cat "$INPUT/branch" 2>/dev/null)" = "$BRANCH" ] || exit 2
    SNAPSHOT="$INPUT/snapshot.txt"; REQUEST="$INPUT/request.md"
    ;;
  *)
    INPUT="$(review_series_state_root "$ROOT")/start-inputs/$TREE"
    mkdir -p "$INPUT" || exit 2
    SNAPSHOT="$INPUT/snapshot.txt"
    if [ ! -e "$SNAPSHOT" ]; then review_tree_capture "$ROOT" "$TREE" "$SNAPSHOT" || exit 2; fi
    ;;
esac

SERIES=$(review_series_ensure "$ROOT" "$BRANCH" "$REVIEW_POLICY_ROUNDS" invariant-reviewer "$KEY") || {
  echo "review-start: the current review series is unreadable or belongs to another task." >&2
  exit 2
}
case "$KEY" in nd/context-*) KEY="nd/$SERIES" ;; esac
ATTEMPT=$(review_attempt_start "$ROOT" "$SERIES" "$HOST" "$OWNER" "$SESSION" "$TREE" \
  "$BRANCH" "$KEY" "$SNAPSHOT" "$REQUEST") || exit $?
ADMISSION="${ATTEMPT#"$ROOT"/}/start.json"
CONTEXT="HARNESS REVIEW ADMISSION: $ADMISSION
Before inspecting the subject, run \`core/scripts/review-admission-check.sh $ADMISSION\`. If it does not report valid, return only the canonical REVIEW REFUSED message.
Attempt ${ATTEMPT##*/} already consumes its review round; output formatting cannot erase it."
if [ "$REQUEST" != - ]; then
  CONTEXT="$CONTEXT
Read $ADMISSION's sibling request.md and snapshot.txt. Prior attempts stay under the same series."
fi
EVENT=PreToolUse
[ "$HOST" = codex ] && EVENT=SubagentStart
jq -cn --arg event "$EVENT" --arg context "$CONTEXT" \
  '{hookSpecificOutput:{hookEventName:$event,additionalContext:$context}}'
