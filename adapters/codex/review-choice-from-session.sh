#!/usr/bin/env bash
# No prompt arguments: the current direct Desktop response supplies the choice.
set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ "$#" = 0 ] && [ -n "$ROOT" ] || {
  echo 'review-choice: run this no-argument adapter inside the repository; nothing recorded.' >&2; exit 2;
}
. "${OH_HOME:-$ROOT}/adapters/codex/desktop-grant-lib.sh" || exit 2
ADAPTER="${DESKTOP_REVIEW_ADAPTER:-adapters/codex/review-choice-from-session.sh}"
FAMILY=review
[ "$ADAPTER" != adapters/codex/round-grant-from-session.sh ] || FAMILY=round
CANDIDATE=$(desktop_choice_candidate "$ROOT" "$FAMILY" "$ADAPTER") || {
  echo 'review-choice: no exact direct Desktop answer precedes this isolated adapter call. Nothing recorded.' >&2
  echo 'Use this adapter as the first tool call after the gate answer. If state changed, show the current gate and request a new answer.' >&2
  exit 2
}
IFS=$'\t' read -r ANSWER SOURCE MODE FIRST <<EOF_CHOICE
$CANDIDATE
EOF_CHOICE
export CODEX_HOOK=1 CODEX_CHOICE_SOURCE="$SOURCE"
jq -cn --arg prompt "$ANSWER" --arg session "$CODEX_SESSION_ID" --arg turn "${SOURCE#codex-desktop:}" \
  '{hook_event_name:"UserPromptSubmit",prompt:$prompt,session_id:$session,turn_id:$turn}' \
  | /bin/bash "${OH_HOME:-$ROOT}/adapters/codex/user-prompt-submit.sh"
