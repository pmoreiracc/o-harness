#!/usr/bin/env bash
# Codex Desktop compatibility adapter for hosts that do not dispatch UserPromptSubmit.
# Direct session evidence supplies the choice; this no-argument command cannot author one.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
if [ -z "$ROOT" ] || [ ! -f "${OH_HOME:-$ROOT}/core/task-ledger.sh" ]; then
  echo 'task-window: repository harness cannot be resolved; no choice was recorded.' >&2
  exit 2
fi
[ "$#" = 0 ] || {
  echo 'task-window: the Desktop adapter accepts no arguments; no choice was recorded.' >&2
  exit 2
}

. "${OH_HOME:-$ROOT}/core/lib.sh" || exit 2
. "${OH_HOME:-$ROOT}/core/task-ledger.sh" || exit 2
. "${OH_HOME:-$ROOT}/adapters/codex/desktop-grant-lib.sh" || exit 2
TASK_US=$(printf '\037')

BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 2
parsed=$(delivery_branch_parse "$BRANCH") || {
  echo 'task-window: no active delivery branch can be derived; no choice was recorded.' >&2
  exit 2
}
DOC="${parsed%%$'\t'*}"
TSV=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/plan.sh" "$DOC" 2>/dev/null) || exit 2
candidate=$(desktop_task_choice_candidate "$ROOT") || {
  echo 'task-window: no exact direct Desktop choice matches this branch and turn.' >&2
  exit 2
}
IFS=$'\t' read -r CHOICE SOURCE_MESSAGE MODE FIRST_CALL_ID <<EOF
$candidate
EOF
case "$CHOICE" in
  continue) LABEL="$TASK_CONTINUE_LABEL" ;;
  pr) LABEL="$TASK_PR_LABEL" ;;
  stop) LABEL="$TASK_STOP_LABEL" ;;
  *) exit 2 ;;
esac
[ -n "$SOURCE_MESSAGE" ] || exit 2

if [ "$MODE" = recovery ]; then
  # A local policy has no immutable historical blob. Without one, unchanged HEAD/tree proves
  # the tracked policy was unchanged across the old formatting-only failure and this retry.
  [ ! -e "${OH_HOME:-$ROOT}/core/delivery-policy.local.json" ] \
    && [ ! -L "${OH_HOME:-$ROOT}/core/delivery-policy.local.json" ] || {
      echo 'task-window: formatting recovery cannot prove an unchanged local policy; ask the human again.' >&2
      exit 2
    }
  task_authority_load "$ROOT" "$BRANCH" "$DOC" "$TSV" || exit 2
  CANDIDATE_LINE=$(task_first_runnable "$TASK_AUTHORITY_TRUSTED_TSV" "$TASK_AUTHORITY_OWNER" "") || exit 2
  CANDIDATE_TASK="${CANDIDATE_LINE%%"$TASK_US"*}"
  task_gate_evaluate "$ROOT" "$BRANCH" "$DOC" "$TSV" "$CANDIDATE_TASK" || exit 2
  case "$TASK_GATE_STATE" in checkpoint|stop) ;; *) exit 2 ;; esac
  RECOVERY_TREE=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh" 2>/dev/null) || exit 2
  RECOVERY_HEAD=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null) || exit 2
  review_policy_load "$ROOT" || exit 2
  [ "$REVIEW_POLICY_SOURCE" = default ] || exit 2
  RECOVERY_POLICY_SHA=$(review_workflow_file_hash "$REVIEW_POLICY_FILE") || exit 2
  RECOVERY_DIR="${OH_STATE_ROOT:-$ROOT/.deliver/reviews}/task-choice-recoveries"
  RECOVERY_KEY=$(review_workflow_hash "$SOURCE_MESSAGE") || exit 2
  RECOVERY_FILE="$RECOVERY_DIR/$RECOVERY_KEY.json"
  mkdir -p "$RECOVERY_DIR" || exit 2
  if [ -e "$RECOVERY_FILE" ] || [ -L "$RECOVERY_FILE" ]; then
    [ -f "$RECOVERY_FILE" ] && [ ! -L "$RECOVERY_FILE" ] \
      && jq -e --arg source "$SOURCE_MESSAGE" --arg call "$FIRST_CALL_ID" --arg choice "$CHOICE" \
        --arg branch "$BRANCH" --arg tree "$RECOVERY_TREE" --arg head "$RECOVERY_HEAD" \
        --arg policy "$RECOVERY_POLICY_SHA" --arg incarnation "$TASK_GATE_INCARNATION" \
        --arg boundaryCommit "$TASK_GATE_BOUNDARY_COMMIT" --arg boundaryTask "$TASK_GATE_BOUNDARY_TASK" '
          .version==1 and .status=="verified-formatting-only-failure" and
          .sourceMessage==$source and .failedCallId==$call and .choice==$choice and
          .branch==$branch and .tree==$tree and .head==$head and .policySource=="default" and
          .policySha256==$policy and .incarnation==$incarnation and
          .boundaryCommit==$boundaryCommit and .boundaryTask==$boundaryTask and
          .authorizesCompletion==false
        ' "$RECOVERY_FILE" >/dev/null 2>&1 || exit 2
  else
    RECOVERY_TMP="$RECOVERY_DIR/.recovery.$$"
    jq -cn --arg source "$SOURCE_MESSAGE" --arg call "$FIRST_CALL_ID" --arg choice "$CHOICE" \
      --arg branch "$BRANCH" --arg tree "$RECOVERY_TREE" --arg head "$RECOVERY_HEAD" \
      --arg policy "$RECOVERY_POLICY_SHA" --arg incarnation "$TASK_GATE_INCARNATION" \
      --arg boundaryCommit "$TASK_GATE_BOUNDARY_COMMIT" --arg boundaryTask "$TASK_GATE_BOUNDARY_TASK" \
      --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
        {version:1,status:"verified-formatting-only-failure",sourceMessage:$source,
         failedCallId:$call,choice:$choice,branch:$branch,tree:$tree,head:$head,
         policySource:"default",policySha256:$policy,incarnation:$incarnation,
         boundaryCommit:$boundaryCommit,boundaryTask:$boundaryTask,
         authorizesCompletion:false,recordedAt:$at}
      ' > "$RECOVERY_TMP" && ln "$RECOVERY_TMP" "$RECOVERY_FILE" 2>/dev/null \
      || { rm -f "$RECOVERY_TMP"; exit 2; }
    rm -f "$RECOVERY_TMP"
  fi
elif [ "$MODE" != direct ] || [ "$FIRST_CALL_ID" != - ]; then
  exit 2
fi

if task_choice_add "$ROOT" "$BRANCH" "$DOC" "$TSV" "$CHOICE" "$LABEL" "$SOURCE_MESSAGE"; then
  echo "task-window: recorded direct Desktop choice '$CHOICE' at the current checkpoint." >&2
  exit 0
fi
echo 'task-window: the direct Desktop choice did not match an uncovered checkpoint.' >&2
exit 2
