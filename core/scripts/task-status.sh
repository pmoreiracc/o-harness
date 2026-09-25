#!/usr/bin/env bash
# Read-only task-window status and checkpoint-history renderer (ADR-0045).
# Usage: task-status.sh <design-doc-number> [track] [--history]
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
DOC="${1:-}"; TRACK="${2:-}"; MODE="${3:-}"; REQUESTED_TRACK=""
if [ "$TRACK" = --history ]; then MODE=--history; TRACK=""; fi
case "$DOC" in ""|*[!0-9]*) echo "usage: task-status.sh <design-doc-number> [track] [--history]" >&2; exit 1 ;; esac
. "${OH_HOME:-$ROOT}/core/lib.sh" || exit 1
. "${OH_HOME:-$ROOT}/core/task-ledger.sh" || exit 1
TASK_US=$(printf '\037')
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)
parsed=$(delivery_branch_parse "$BRANCH") || {
  echo "task-status: $BRANCH is not a delivery branch." >&2; exit 1;
}
BDOC="${parsed%%$'\t'*}"
[ "$BDOC" = "$DOC" ] || { echo "task-status: branch $BRANCH belongs to design $BDOC, not $DOC." >&2; exit 1; }
REQUESTED_TRACK="$TRACK"

TSV=$("$DIR/plan.sh" "$DOC") || exit 1
task_authority_load "$ROOT" "$BRANCH" "$DOC" "$TSV" || exit 1
BASE="$TASK_AUTHORITY_BASE"
SELECTION_TSV="$TASK_AUTHORITY_TRUSTED_TSV"
TRACK="$TASK_AUTHORITY_OWNER"
[ -z "$REQUESTED_TRACK" ] || [ "$REQUESTED_TRACK" = "$TRACK" ] || {
  echo "task-status: branch $BRANCH belongs to track '$TRACK', not '$REQUESTED_TRACK'." >&2
  exit 1
}

if [ "$MODE" = --history ]; then
  candidate_line=$(task_first_runnable "$SELECTION_TSV" "$TRACK" "" 2>/dev/null)
  candidate_status=$?
  case "$candidate_status" in 0) ;; 1) candidate_line="" ;; *) exit 1 ;; esac
  candidate="${candidate_line%%"$TASK_US"*}"
  boundary=$(task_boundary "$BASE" "$TASK_AUTHORITY_HISTORY") || exit 1
  if [ -n "$boundary" ]; then
    base="${boundary%%"$TASK_US"*}"; boundary="${boundary#*"$TASK_US"}"
    incarnation="${boundary%%"$TASK_US"*}"; boundary="${boundary#*"$TASK_US"}"
    commit="${boundary%%"$TASK_US"*}"; task="${boundary#*"$TASK_US"}"
    task_records_load "$ROOT" "$BRANCH" "$DOC" "$TRACK" "$SELECTION_TSV" "$base" \
      "$incarnation" "$commit" "$task" "$candidate" "$TASK_AUTHORITY_HISTORY" || exit 1
  fi
  task_history_render "$ROOT" "$BRANCH" || exit 1
  exit 0
fi

candidate_line=$(task_first_runnable "$SELECTION_TSV" "$TRACK" "")
candidate_status=$?
case "$candidate_status" in
  0) ;;
  1) echo "state: no-runnable-task"; exit 0 ;;
  *) echo "task-status: cannot derive the reviewed runnable-task order." >&2; exit 1 ;;
esac
candidate="${candidate_line%%"$TASK_US"*}"
task_gate_evaluate "$ROOT" "$BRANCH" "$DOC" "$TSV" "$candidate" || exit 1
echo "state: $TASK_GATE_STATE"
echo "next-task: $candidate"
echo "next-task-title: ${candidate_line#*"$TASK_US"}"
echo "branch: $BRANCH"
if [ -n "$TASK_GATE_BOUNDARY_TASK" ]; then
  echo "boundary-task: $TASK_GATE_BOUNDARY_TASK"
  echo "boundary-commit: $TASK_GATE_BOUNDARY_COMMIT"
fi
case "$TASK_GATE_STATE" in
  covered) echo "covered-by: $(basename "$TASK_COVERING_RECORD")" ;;
  checkpoint|stop)
    [ "$TASK_GATE_STATE" = stop ] && echo "previous-choice: stop"
    preview_window=$(task_policy_window "$ROOT") || exit 1
    review_policy_load "$ROOT" || exit 1
    preview_ids=$(task_project_ids "$SELECTION_TSV" "$TRACK" "$preview_window") || exit 1
    echo "policy-window: $preview_window"
    echo "policy-source: $REVIEW_POLICY_SOURCE"
    echo "continue-would-permit: ${preview_ids:-none}"
    printf '%s\n' "$SELECTION_TSV" | awk -F"$TASK_US" -v ids=",$preview_ids," 'index(ids, "," $1 ",") {print "  " $1 ". " $6}'
    echo "choice-required: continue | pr | stop" ;;
  pr) echo "previous-choice: pr" ;;
esac
