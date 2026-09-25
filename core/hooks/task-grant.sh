#!/usr/bin/env bash
# Records Claude Code's human task-boundary choice (ADR-0045).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || exit 2
hook_init
[ "$(hook_field '.tool_name')" = AskUserQuestion ] || exit 0
ROOT=$(project_root)
. "${OH_HOME:-$ROOT}/core/lib.sh" || exit 2
. "${OH_HOME:-$ROOT}/core/task-ledger.sh" || exit 2
TASK_US=$(printf '\037')

# The selected answer is authoritative only when Claude presented ADR-0045's complete
# single-select menu. A model-authored one-option question must not turn a constrained click
# into approval of a choice the human was never offered.
MENU_VALID=$(printf '%s' "$PAYLOAD" | jq -r \
  --arg c "$TASK_CONTINUE_LABEL" --arg p "$TASK_PR_LABEL" --arg s "$TASK_STOP_LABEL" '
  .tool_input.questions as $questions
  | if ($questions|type)!="array" or ($questions|length)!=1 then false
    else $questions[0] as $q
    | ($q|type)=="object"
      and $q.multiSelect == false
      and ($q.options|type)=="array"
      and ($q.options|length)==3
      and ([$q.options[] | if type=="object" then .label else null end] | sort)
          == ([$c,$p,$s] | sort)
    end
' 2>/dev/null)
[ "$MENU_VALID" = true ] || exit 0

SELECTED=$(hook_single_human_answer)
case "$SELECTED" in
  "$TASK_CONTINUE_LABEL") CHOICE=continue ;;
  "$TASK_PR_LABEL") CHOICE=pr ;;
  "$TASK_STOP_LABEL") CHOICE=stop ;;
  *)
    echo 'task-window: no choice recorded. The answer was missing, ambiguous, or did not match the offered options. Present the same single-select gate:' >&2
    printf '%s\n' "$TASK_CONTINUE_LABEL" "$TASK_PR_LABEL" "$TASK_STOP_LABEL" >&2
    exit 0 ;;
esac

BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
parsed=$(delivery_branch_parse "$BRANCH") || exit 0
DOC="${parsed%%$'\t'*}"
TSV=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/plan.sh" "$DOC" 2>/dev/null) || exit 0
if task_choice_add "$ROOT" "$BRANCH" "$DOC" "$TSV" "$CHOICE" "$SELECTED"; then
  echo "task-window: recorded human choice '$CHOICE' after task $TASK_GATE_BOUNDARY_TASK." >&2
else
  echo "task-window: no uncovered task checkpoint accepted this choice; nothing was recorded. Inspect task-status.sh on the intended branch, preserve dirty lifecycle edits, and present the current gate if needed." >&2
fi
exit 0
