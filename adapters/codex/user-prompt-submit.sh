#!/usr/bin/env bash
# Route one Codex UserPromptSubmit event by its exact host-provided prompt.
#
# Codex does not apply matcher expressions to UserPromptSubmit. Keep one unconditional
# event handler in hooks.json and perform the exact-value dispatch here so every accepted
# human command reaches exactly one canonical recorder.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
if [ -z "$ROOT" ] || [ ! -f "${OH_HOME:-$ROOT}/core/hooks/lib.sh" ]; then
  echo "GUARDRAIL CANNOT RUN: the repository root or core/hooks/lib.sh cannot be resolved." >&2
  exit 2
fi

PAYLOAD=$(cat)
EVENT=$(printf '%s' "$PAYLOAD" | jq -r '.hook_event_name // ""' 2>/dev/null)
PROMPT=$(printf '%s' "$PAYLOAD" | jq -r '.prompt // ""' 2>/dev/null)
[ "$EVENT" = UserPromptSubmit ] || exit 0

TARGET=""
NORMALIZED=$(printf '%s' "$PROMPT" | tr '\n\t' '  ' \
  | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/[[:space:]][[:space:]]*/ /g' \
  | tr '[:upper:]' '[:lower:]')
case "$NORMALIZED" in
  'grant next review window'|'stop and take it over'|'stop and escalate to the pr')
    TARGET="${OH_HOME:-$ROOT}/adapters/codex/round-grant.sh"
    ;;
esac

# Recognizable formatting mistakes are feedback, never authorization. Compare the original
# JSON string so shell command substitution cannot erase a trailing newline into approval.
case "$NORMALIZED" in
  continue|pr|stop|'fix concerns'|'accept concerns'|'route scope'|'dismiss scope'|\
  'fix concerns and route scope'|'fix concerns and dismiss scope'|\
  'accept concerns and route scope'|'accept concerns and dismiss scope'|\
  'review again'|'take over'|'stop scope routing'|'stop detached review')
    if [ "$PROMPT" != "$NORMALIZED" ] || ! printf '%s' "$PAYLOAD" | jq -e --arg p "$PROMPT" '.prompt==$p' >/dev/null; then
      echo 'gate: recognizable but nonexact answer; nothing recorded. Present the current gate and its exact command lines again.' >&2
      exit 0
    fi ;;
esac

case "$PROMPT" in
  'grant next review window'|'stop and take it over'|'stop and escalate to the pr')
    TARGET="${OH_HOME:-$ROOT}/adapters/codex/round-grant.sh"
    ;;
  'continue'|'pr'|'stop')
    TARGET="${OH_HOME:-$ROOT}/adapters/codex/task-grant.sh"
    ;;
  'fix concerns'|'accept concerns'|'route scope'|'dismiss scope'|\
  'fix concerns and route scope'|'fix concerns and dismiss scope'|\
  'accept concerns and route scope'|'accept concerns and dismiss scope'|\
  'review again'|'take over'|'stop scope routing'|'route scope to https://'*)
    TARGET="${OH_HOME:-$ROOT}/core/hooks/review-choice.sh"
    ;;
  'stop detached review'|'resume detached review d-'*)
    TARGET="${OH_HOME:-$ROOT}/core/hooks/review-detached-context.sh"
    ;;
  *) ;;
esac
[ -n "$TARGET" ] || exit 0
if ! printf '%s' "$PAYLOAD" | jq -e --arg p "$PROMPT" '.prompt==$p' >/dev/null; then
  echo 'gate: extra line breaks are not an exact answer; nothing recorded. Present the current copy-safe choices.' >&2
  exit 0
fi

# Matcher-split definitions from an already-running session can invoke more than one legacy
# entry point for the same host event. Claim the host-owned session/turn once before writing,
# so the migration itself cannot duplicate a grant or resolution.
SESSION=$(printf '%s' "$PAYLOAD" | jq -r '.session_id // ""' 2>/dev/null)
TURN=$(printf '%s' "$PAYLOAD" | jq -r '.turn_id // ""' 2>/dev/null)
case "$SESSION:$TURN" in
  *[!A-Za-z0-9:_-]*|:|*:|:*)
    echo "GUARDRAIL CANNOT RUN: UserPromptSubmit has no valid host session/turn identity." >&2
    exit 2
    ;;
esac
CLAIMS="${OH_STATE_ROOT:-$ROOT/.deliver}/hook-events/user-prompt-submit"
mkdir -p "$CLAIMS" || exit 2
CLAIM="$CLAIMS/$SESSION-$TURN"
mkdir "$CLAIM" 2>/dev/null || {
  echo 'gate: this host answer is already being processed or was recorded; inspect the current task/review status before continuing.' >&2
  exit 0
}

printf '%s' "$PAYLOAD" | /bin/bash "$TARGET"
RC=$?
# Canonical recorders are idempotent. A failed dispatch must not consume an unsaved answer.
[ "$RC" = 0 ] || rmdir "$CLAIM" 2>/dev/null || true
# A failed recorder must not swallow the user's message (especially an explicit stop).
# Desktop callers receive a command failure; native UserPromptSubmit still delivers input.
if [ -n "${CODEX_CHOICE_SOURCE:-}" ]; then exit "$RC"; fi
exit 0
