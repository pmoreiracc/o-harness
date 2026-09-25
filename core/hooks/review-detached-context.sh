#!/usr/bin/env bash
# Bind one explicit detached review context ID to the current host session.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 2
. "${OH_HOME:-$ROOT}/core/hooks/lib.sh" || exit 2
. "${OH_HOME:-$ROOT}/core/review-workflow.sh" || exit 2
hook_init

if [ -n "${CODEX_HOOK:-}" ]; then
  ANSWER=$(hook_field '.prompt')
  case "$ANSWER" in 'stop detached review') echo 'review-context: stopped; retained context unchanged, no review authorized.' >&2; exit 0 ;; 'resume detached review d-'*) ID="${ANSWER#resume detached review }" ;; *) exit 0 ;; esac
  SESSION="${CODEX_SESSION_ID:-$(hook_field '.session_id')}"
  SOURCE="${CODEX_CHOICE_SOURCE:-codex:$SESSION:$(hook_field '.turn_id')}"
else
  [ "$(hook_field '.tool_name')" = AskUserQuestion ] || exit 0
  RESUME_LABEL=$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.questions[0].options[]?.label | select(startswith("Resume detached review d-"))' 2>/dev/null)
  [ -n "$RESUME_LABEL" ] && hook_menu_matches "$(printf '%s\n' "$RESUME_LABEL" 'Stop detached review')" || exit 0
  ANSWER=$(hook_single_human_answer)
  case "$ANSWER" in
    'Stop detached review') echo 'review-context: stopped; retained context unchanged, no review authorized.' >&2; exit 0 ;;
    "$RESUME_LABEL") ID="${ANSWER#Resume detached review }" ;;
    *)
      echo 'review-context: no choice recorded. Present the same single-select gate with these exact options:' >&2
      printf '%s\n' "$RESUME_LABEL" 'Stop detached review' >&2
      exit 2 ;;
  esac
  SESSION=$(hook_field '.session_id')
  SOURCE="claude:$SESSION:$(hook_field '.tool_use_id')"
fi
[ -n "$SESSION" ] || exit 2
review_detached_context_bind_session "$ROOT" "$SESSION" "$ID" "$SOURCE" || {
  echo "review-context: no resume recorded for $ID: stale, wrong repository, or another context is open. Inspect retained contexts and present the exact open ID with Resume / Stop detached review; preserve existing work." >&2
  exit 2
}
echo "review-context: resumed detached review context $ID for this host session." >&2
