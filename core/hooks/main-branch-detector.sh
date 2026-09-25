#!/usr/bin/env bash
# GUARDRAIL — nothing is committed straight to main.
#
# Trunk-based means short-lived branches merged fast (operations.md §7), not commits
# landing on the trunk directly.
#
# Detects rather than blocks, deliberately. A pre-check would have to guess from a Bash
# command string whether it commits — the exact mistake ADR-0027 records, where a
# heuristic over an arbitrary shell string blocked a PR for *describing* the pattern.
# Whether HEAD moved on main is not a guess: git knows.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/hooks/lib.sh is missing or unreadable." >&2
  echo "No operation was inspected. Restore this reviewed harness file in the checkout and retry; do not disable the guardrail." >&2
  exit 2
}
hook_init

ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || exit 0

BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)
case "$BRANCH" in
  main|master) ;;
  *) exit 0 ;;
esac

UPSTREAM="origin/$BRANCH"
git -C "$ROOT" rev-parse --verify "$UPSTREAM" >/dev/null 2>&1 || exit 0

AHEAD=$(git -C "$ROOT" rev-list --count "$UPSTREAM..HEAD" 2>/dev/null)
[ "${AHEAD:-0}" -gt 0 ] || exit 0

echo "$AHEAD commit(s) now sit on $BRANCH that are not on $UPSTREAM." >&2
git -C "$ROOT" log --oneline "$UPSTREAM..HEAD" | sed 's/^/  /' >&2
echo "" >&2
echo "These commits already exist. Preserve them and any uncommitted work on a new branch:" >&2
echo "  git switch -c <unused-branch-name>" >&2
echo "Inspect git status and the commits first. Continue the authorized review there; do not reset --hard or discard work to repair the branch." >&2
exit 2
