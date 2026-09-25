#!/usr/bin/env bash
# GUARDRAIL (advisory) — a new ADR must appear in the log table.
#
# docs/decisions/README.md carries "The log" — the index every reader starts from. An
# ADR that exists but is not listed is an ADR nobody finds.
#
# Advisory, not blocking: the file is already written by the time this runs. It reports
# back so the omission is fixed in the same turn rather than discovered in review.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/hooks/lib.sh is missing or unreadable." >&2
  echo "No operation was inspected. Restore this reviewed harness file in the checkout and retry; do not disable the guardrail." >&2
  exit 2
}
hook_init

FILE=$(hook_field '.tool_input.file_path')
[ -n "$FILE" ] || exit 0

REL=$(repo_rel "$FILE")
case "$REL" in
  docs/decisions/[0-9][0-9][0-9][0-9]-*.md) ;;
  *) exit 0 ;;
esac

BASE=$(basename "$REL")
LOG="${CLAUDE_PROJECT_DIR:-$PWD}/docs/decisions/README.md"
[ -f "$LOG" ] || exit 0

if ! grep -q "$BASE" "$LOG"; then
  NUM=$(printf '%s' "$BASE" | cut -c1-4)
  echo "$BASE is not in the log table in docs/decisions/README.md." >&2
  echo "Add a row: | [$NUM](./$BASE) | <title> | <date> | <status> |" >&2
  echo "If it settles an entry under 'Open — decisions not yet made', remove that row too." >&2
  echo "The ADR write already applied. Add the missing index row, run verify-docs.sh, and continue." >&2
  jq -cn --arg message "$BASE was written but is missing from docs/decisions/README.md. Add its index row, run verify-docs.sh, and continue this run." \
    '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$message}}'
  exit 0
fi

exit 0
