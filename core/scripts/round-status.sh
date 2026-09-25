#!/usr/bin/env bash
# The review-round window, read from the ledger (ADR-0044). Read-only: it reports, it never
# grants. The loop consults it after each round to learn whether the NEXT round would cross
# the ceiling and so needs a human grant first, and to confirm a renewal actually landed.
#
# Usage:  round-status.sh <design-doc-number> <task-number>   (a delivery task's window)
#         round-status.sh                                     (the window for HEAD, wherever
#                                                                the run is — ADR-0046
#                                                                Decision 2)
#
# stdout (stable, one key per line, for the loop to read and to show the human):
#   task: <doc>/<task> | <window-key>
#   rounds-used: <N>
#   grants: <G>
#   window: <W>              (3 + 3*G — the highest round number permitted without a new grant)
#   next-round-needs-grant: yes|no
#
# Exit 0 always when the arguments (or their absence) are well-formed; exit 1 on a usage
# error, or when the no-argument form cannot resolve the current branch or HEAD. "No ledger
# yet" is a valid state (zero rounds), not an error — the first round has not been filed.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
DOC="${1:-}"
TASK="${2:-}"

. "$DIR/../round-ledger.sh" || {
  echo "round-status.sh: core/round-ledger.sh is missing or unreadable." >&2
  exit 1
}

if [ -z "$DOC" ] && [ -z "$TASK" ]; then
  BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)
  [ -n "$BRANCH" ] || { echo "round-status.sh: could not resolve the current branch." >&2; exit 1; }
  KEY=$(round_key_for "$ROOT" "$BRANCH") || {
    echo "round-status.sh: could not resolve a review-round window for $BRANCH." >&2
    exit 1
  }
  LABEL="$KEY"
else
  case "$DOC" in ""|*[!0-9]*) echo "usage: round-status.sh [<design-doc-number> <task-number>]" >&2; exit 1 ;; esac
  case "$TASK" in ""|*[!0-9]*) echo "usage: round-status.sh [<design-doc-number> <task-number>]" >&2; exit 1 ;; esac
  KEY=$(round_task_key "$DOC" "$TASK")
  LABEL="$DOC/$TASK"
fi

USED=$(round_count "$ROOT" "$KEY") || {
  echo "round-status.sh: accepted review-round evidence is malformed or unreadable." >&2
  exit 1
}
GRANTS=$(round_grants_count "$ROOT" "$KEY") || {
  echo "round-status.sh: review-grant evidence has an unexpected shape." >&2
  exit 1
}
WINDOW=$(round_window "$ROOT" "$KEY") || exit 1
SERIES=$(review_series_find_for_key "$ROOT" "$KEY" 2>/dev/null || true)
if [ -n "$SERIES" ]; then
  POLICY_SOURCE=$(jq -r '.policySource // "default"' "$(review_series_dir "$ROOT" "$SERIES")/series.json")
  WINDOW_INCREMENT=$(review_series_window "$ROOT" "$SERIES") || exit 1
else
  review_policy_load "$ROOT" || exit 1
  POLICY_SOURCE="$REVIEW_POLICY_SOURCE"
  WINDOW_INCREMENT="$REVIEW_POLICY_ROUNDS"
fi

round_needs_grant "$ROOT" "$KEY" "$USED"; NEEDS_RC=$?
case "$NEEDS_RC" in 0) NEEDS=yes ;; 1) NEEDS=no ;; *) exit 1 ;; esac

echo "task: $LABEL"
echo "rounds-used: $USED"
echo "grants: $GRANTS"
echo "window: $WINDOW"
echo "window-increment: $WINDOW_INCREMENT"
echo "policy-source: $POLICY_SOURCE"
echo "next-round-needs-grant: $NEEDS"
