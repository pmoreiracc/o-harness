#!/usr/bin/env bash
# Start the first runnable task on its canonical delivery branch.
#
# This is the sole supported branch-creation path for /deliver. It runs the first-task gate
# on refreshed main, safely retires a local canonical ref only when origin/main has already
# absorbed it, and creates a new local branch incarnation whose reflog proves that fact.
# Compatible with bash 3.2.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
DOC="${1:-}"
OWNER="${2:-}"

case "$DOC" in
  [0-9][0-9][0-9][0-9]) ;;
  *) echo "usage: start.sh <design-doc-number> [track]" >&2; exit 1 ;;
esac

. "$DIR/../lib.sh" || { echo "start.sh: core/lib.sh is missing." >&2; exit 1; }
. "$DIR/../task-ledger.sh" || { echo "start.sh: task-window contract is missing." >&2; exit 1; }

# next.sh owns task admission, approval, track validation, and refreshed-main readiness. Print
# its result unchanged so this command cannot become a second, drifting first-task gate.
if [ -n "$OWNER" ]; then
  CLAUDE_PROJECT_DIR="$ROOT" "$DIR/next.sh" "$DOC" "$OWNER"
  NEXT_STATUS=$?
else
  CLAUDE_PROJECT_DIR="$ROOT" "$DIR/next.sh" "$DOC"
  NEXT_STATUS=$?
fi

case "$NEXT_STATUS" in 0|6) ;; *) exit "$NEXT_STATUS" ;; esac

TSV=$(CLAUDE_PROJECT_DIR="$ROOT" "$DIR/plan.sh" "$DOC") || exit 1
TASK_US=$(printf '\037')
TRACKS=$(printf '%s\n' "$TSV" | cut -d"$TASK_US" -f3 | sort -u) || exit 1
TRACK_COUNT=$(printf '%s\n' "$TRACKS" | awk 'NF {n++} END {print n+0}') || exit 1
[ "$NEXT_STATUS" != 6 ] || TRACK_COUNT=1
case "$TRACK_COUNT" in
  1) BRANCH="deliver/$DOC" ;;
  *) BRANCH="deliver/$DOC-$OWNER" ;;
esac
[ "$NEXT_STATUS" = 6 ] || task_branch_owner "$BRANCH" "$DOC" "$TSV" >/dev/null || {
  echo "start.sh: cannot derive the canonical delivery branch for design $DOC." >&2
  exit 1
}
git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || {
  echo "start.sh: '$BRANCH' is not a valid Git branch name." >&2
  exit 1
}

# Recheck the mutable repository facts immediately before changing refs. next.sh checked the
# same facts before it issued authority; these checks prevent a wrapper or concurrent action
# from moving the command onto a different base between admission and branch creation.
CURRENT=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 1
[ "$CURRENT" = main ] || {
  echo "start.sh: branch creation requires refreshed main; current branch is '$CURRENT'." >&2
  exit 1
}
STATUS=$(git -C "$ROOT" status --porcelain 2>/dev/null) || exit 1
[ -z "$STATUS" ] || {
  echo "start.sh: branch creation requires a clean main branch." >&2
  exit 1
}
HEAD_SHA=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null) || exit 1
TRUNK_SHA=$(git -C "$ROOT" rev-parse origin/main 2>/dev/null) || exit 1
[ "$HEAD_SHA" = "$TRUNK_SHA" ] || {
  echo "start.sh: main moved away from origin/main after task admission; rerun from refreshed main." >&2
  exit 1
}

git -C "$ROOT" show-ref --verify --quiet "refs/heads/$BRANCH"
REF_STATUS=$?
case "$REF_STATUS" in
  0)
    git -C "$ROOT" merge-base --is-ancestor "$BRANCH" origin/main 2>/dev/null
    ANCESTOR_STATUS=$?
    case "$ANCESTOR_STATUS" in
      0)
        # The old local name is recoverable from trunk and cannot represent live unmerged work.
        # Removing it is necessary: switching/resetting it would leave a reset reflog entry and
        # make a spent branch indistinguishable from a fresh delivery incarnation.
        git -C "$ROOT" branch -D "$BRANCH" >/dev/null || exit 1
        echo "start.sh: retired absorbed local branch $BRANCH." >&2
        ;;
      1)
        echo "start.sh: $BRANCH contains work not absorbed by origin/main; resume it instead." >&2
        exit 1
        ;;
      *)
        echo "start.sh: cannot determine whether $BRANCH is absorbed by origin/main." >&2
        exit 1
        ;;
    esac
    ;;
  1) ;;
  *)
    echo "start.sh: cannot inspect the local $BRANCH ref." >&2
    exit 1
    ;;
esac

git -C "$ROOT" switch -c "$BRANCH" >/dev/null || exit 1
task_fresh_branch_incarnation_valid "$ROOT" "$BRANCH" || {
  echo "start.sh: the new $BRANCH ref lacks a canonical creation incarnation." >&2
  exit 1
}
echo "start.sh: created $BRANCH from refreshed origin/main."
