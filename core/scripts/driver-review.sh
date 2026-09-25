#!/usr/bin/env bash
# Host runner lifecycle bridge; all admission/outcome decisions remain in the shared core.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/../review-request.sh" || exit 2
ROOT="${OH_PROJECT_ROOT:?project root required}"
MODE="${1:?mode required}"
if [ "$MODE" = status ]; then
  BRANCH=$(git -C "$ROOT" branch --show-current) || exit 2
  KEY=$(round_key_for "$ROOT" "$BRANCH") || exit 2
  review_policy_load "$ROOT" || exit 2
  USED=$(round_count "$ROOT" "$KEY"); WINDOW=$(round_window "$ROOT" "$KEY")
  [ "$USED" -lt "$WINDOW" ] || { echo "Review window exhausted" >&2; exit 4; }
  printf '%s\t%s\n' "$USED" "$WINDOW"
elif [ "$MODE" = start ]; then
  HOST="${2:?host required}"; OWNER="${3:?fresh attempt owner required}"; SESSION="${4:?run required}"
  case "$HOST" in codex|claude) ;; *) exit 2 ;; esac
  TREE=$(CLAUDE_PROJECT_DIR="$ROOT" "$DIR/tree-digest.sh") || exit 2
  BRANCH=$(git -C "$ROOT" branch --show-current) || exit 2
  KEY=$(round_key_for "$ROOT" "$BRANCH") || exit 2
  review_policy_load "$ROOT" || exit 2
  USED=$(round_count "$ROOT" "$KEY"); WINDOW=$(round_window "$ROOT" "$KEY")
  [ "$USED" -lt "$WINDOW" ] || { echo "Review window exhausted" >&2; exit 4; }
  REQUEST=$(review_request_path "$ROOT" "$KEY" "$TREE") || exit 2
  review_request_validate_path "$ROOT" "$KEY" "$TREE" "$REQUEST" || exit 2
  SNAPSHOT=$(mktemp)
  trap 'rm -f "$SNAPSHOT"' EXIT
  review_tree_capture "$ROOT" "$TREE" "$SNAPSHOT" || exit 2
  SERIES=$(review_series_ensure "$ROOT" "$BRANCH" "$REVIEW_POLICY_ROUNDS" invariant-reviewer "$KEY") || exit 2
  review_attempt_start "$ROOT" "$SERIES" "$HOST" "$OWNER" "$SESSION" "$TREE" "$BRANCH" "$KEY" "$SNAPSHOT" "$REQUEST"
elif [ "$MODE" = interrupt ]; then
  ATTEMPT="${2:?attempt required}"
  review_attempt_validate_start "$ROOT" "$ATTEMPT" || exit 2
  review_attempt_complete "$ROOT" "$ATTEMPT" interrupted - "" "" true || exit 2
elif [ "$MODE" = finish ]; then
  ATTEMPT="${2:?attempt required}"; RAW="${3:?raw output required}"
  review_attempt_validate_start "$ROOT" "$ATTEMPT" || exit 2
  TREE=$(CLAUDE_PROJECT_DIR="$ROOT" "$DIR/tree-digest.sh") || exit 2
  [ "$(jq -r '.tree' "$ATTEMPT/start.json")" = "$TREE" ] || exit 5
  review_attempt_complete "$ROOT" "$ATTEMPT" completed "$RAW" || exit 2
  jq -r '.outcome' "$ATTEMPT/completion.json"
else exit 2
fi
