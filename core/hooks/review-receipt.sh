#!/usr/bin/env bash
# Append raw reviewer output and its computed semantic outcome to the admitted attempt.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || exit 2
hook_init
. "$DIR/../review-workflow.sh" || exit 2
. "$DIR/../round-ledger.sh" || exit 2

AGENT=$(hook_field '.agent_type')
[ "$AGENT" = invariant-reviewer ] || exit 0
ROOT=$(project_root)
SESSION=$(hook_field '.session_id'); [ -n "$SESSION" ] || SESSION=$(hook_field '.conversation_id')
RAW=$(mktemp "${TMPDIR:-/tmp}/review-output.XXXXXX") || exit 2
trap 'rm -f "$RAW"' EXIT
printf '%s' "$PAYLOAD" | jq -j '.last_assistant_message // ""' > "$RAW" || exit 2

if [ -n "${CODEX_HOOK:-}" ]; then
  HOST=codex; OWNER=$(hook_field '.agent_id')
  [ -n "$OWNER" ] || exit 2
  ATTEMPT=$(review_attempt_find_owner "$ROOT" codex "$OWNER" 2>/dev/null)
else
  HOST=claude; OWNER=claude
  BRANCH_NOW=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 2
  review_detached_context_activate_for_session "$ROOT" "$BRANCH_NOW" "$SESSION" 0 || exit 2
  SERIES=$(review_series_current "$ROOT" "$BRANCH_NOW" 2>/dev/null) || SERIES=""
  if [ -n "$SERIES" ]; then ATTEMPT=$(review_attempt_pending_for "$ROOT" "$SERIES" claude 2>/dev/null); else ATTEMPT=""; fi
  if [ -n "$ATTEMPT" ] && [ "$(jq -r '.session' "$ATTEMPT/start.json")" != "$SESSION" ]; then ATTEMPT=""; fi
fi

if [ -z "${ATTEMPT:-}" ]; then
  DIAG=$(review_unattributed_retain "$ROOT" "$HOST" "$OWNER" "${SESSION:-unknown}" "$RAW" \
    missing-fresh-reviewer-admission 2>/dev/null || true)
  echo "review-receipt: missing fresh-reviewer admission; the output was retained as" >&2
  echo "${DIAG#"$ROOT"/}. Spawn a new invariant reviewer in this session." >&2
  exit 1
fi
review_attempt_validate_start "$ROOT" "$ATTEMPT" || exit 2

TREE=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh") || exit 2
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 2
if [ "$BRANCH" = HEAD ] && [ -z "${REVIEW_DETACHED_CONTEXT_ID:-}" ]; then
  review_detached_context_activate_for_session "$ROOT" "$BRANCH" "$SESSION" 0 || exit 2
fi
KEY=$(round_key_for "$ROOT" "$BRANCH" 2>/dev/null) || exit 2
START_TREE=$(jq -r '.tree' "$ATTEMPT/start.json")
START_BRANCH=$(jq -r '.branch' "$ATTEMPT/start.json")
START_KEY=$(jq -r '.roundKey' "$ATTEMPT/start.json")

INPUT_TOKENS=$(hook_field '.usage.input_tokens')
OUTPUT_TOKENS=$(hook_field '.usage.output_tokens')
if [ "$TREE" != "$START_TREE" ] || [ "$BRANCH" != "$START_BRANCH" ] || [ "$KEY" != "$START_KEY" ]; then
  review_attempt_complete "$ROOT" "$ATTEMPT" binding-failed "$RAW" "$INPUT_TOKENS" "$OUTPUT_TOKENS" || exit 2
  echo "review-receipt: tree, branch, or series changed; raw output retained as binding-failed." >&2
  exit 1
fi

NO_RESULT=false
if [ ! -s "$RAW" ]; then
  STATUS=empty
  # A stop event proves the reviewer ended. Explicit cancellation/interruption is not an
  # automatic retry. Parent instructions also honor a user stop even if the host omits it.
  if printf '%s' "$PAYLOAD" | jq -e '(.last_assistant_message | type)=="string" and (.cancelled // false)==false and
      (.interrupted // false)==false and ((.stop_reason // .reason // "completed") |
      .=="completed" or .=="end_turn")' >/dev/null; then NO_RESULT=true; fi
else STATUS=completed; fi
if ! review_attempt_complete "$ROOT" "$ATTEMPT" "$STATUS" "$RAW" "$INPUT_TOKENS" "$OUTPUT_TOKENS" "$NO_RESULT"; then
  DIAG=$(review_unattributed_retain "$ROOT" "$HOST" "$OWNER" "${SESSION:-unknown}" "$RAW" \
    completion-conflict "$ATTEMPT" 2>/dev/null || true)
  echo "review-receipt: the attempt was already completed with different immutable evidence;" >&2
  echo "the late output was retained as attributed diagnostics at ${DIAG#"$ROOT"/}." >&2
  exit 1
fi
OUTCOME=$(jq -r '.outcome' "$ATTEMPT/completion.json")
COUNTS=$(jq -r '"\(.counts.blocking) blocking, \(.counts.concern) concerns, \(.counts.scope) scope"' "$ATTEMPT/completion.json")
echo "review-receipt: retained attempt ${ATTEMPT##*/} — $OUTCOME ($COUNTS)." >&2
if [ "$NO_RESULT" = true ]; then
  echo "No response bytes; this attempt still counts. Check round-status.sh and admit a fresh reviewer in the same series within its window." >&2
else
  review_attempt_summary "$ATTEMPT" >&2
fi
if [ -n "${CODEX_HOOK:-}" ]; then printf '%s\n' '{"continue":true,"suppressOutput":false}'; fi
