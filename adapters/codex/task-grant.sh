#!/usr/bin/env bash
# Records Codex's exact bare human task-boundary choice (ADR-0045).
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$ROOT" ] || exit 2
. "${OH_HOME:-$ROOT}/core/lib.sh" || exit 2
. "${OH_HOME:-$ROOT}/core/task-ledger.sh" || exit 2
TASK_US=$(printf '\037')
PAYLOAD=$(cat)
CHOICE=$(printf '%s' "$PAYLOAD" | jq -r '
  if .prompt == "continue" then "continue"
  elif .prompt == "pr" then "pr"
  elif .prompt == "stop" then "stop"
  else empty end
' 2>/dev/null)
case "$CHOICE" in
  continue) LABEL="$TASK_CONTINUE_LABEL" ;;
  pr) LABEL="$TASK_PR_LABEL" ;;
  stop) LABEL="$TASK_STOP_LABEL" ;;
  *) exit 0 ;;
esac
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
parsed=$(delivery_branch_parse "$BRANCH") || {
  echo "task-window: no choice recorded: $BRANCH is not a delivery branch. Inspect next.sh on the intended branch; a stop still ends agent work without authorizing a push or PR." >&2
  exit 2
}
DOC="${parsed%%$'\t'*}"
TSV=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/plan.sh" "$DOC" 2>/dev/null) || exit 0
SOURCE="codex:$(printf '%s' "$PAYLOAD" | jq -r '.session_id // "unknown"'):$(printf '%s' "$PAYLOAD" | jq -r '.turn_id // "unknown"')"
if task_choice_add "$ROOT" "$BRANCH" "$DOC" "$TSV" "$CHOICE" "$LABEL" "$SOURCE"; then
  echo "task-window: recorded human choice '$CHOICE' after task $TASK_GATE_BOUNDARY_TASK." >&2
else
  echo "task-window: no uncovered task checkpoint accepted this choice; nothing was recorded. Inspect task-status.sh for this design, preserve any dirty lifecycle edits, and present the current gate if needed." >&2
  exit 2
fi
exit 0
