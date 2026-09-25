#!/usr/bin/env bash
# Parent-side fallback when the host did not deliver SubagentStop. Report retention and
# uncertain interruption remain Codex-only; confirmed zero-report termination is host-neutral.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
. "${OH_HOME:-$ROOT}/core/review-workflow.sh" || exit 2
. "${OH_HOME:-$ROOT}/core/round-ledger.sh" || exit 2

case "$#:${1:-}" in
  0:) MODE=completed ;;
  1:--interrupted) MODE=interrupted ;;
  1:--no-result) MODE=no-result ;;
  *) echo "usage: review-retain.sh [--no-result | --interrupted] < REVIEW.md" >&2; exit 2 ;;
esac
RAW=""
if [ "$MODE" = completed ]; then
  RAW=$(mktemp "${TMPDIR:-/tmp}/review-retain.XXXXXX") || exit 2
  trap 'rm -f "$RAW"' EXIT
  cat > "$RAW" || exit 2
  [ -s "$RAW" ] || { echo "review-retain: reviewer output is empty; nothing retained. Wait for a live reviewer. After confirmed non-cancelled zero-output completion use --no-result; otherwise use --interrupted and resolve the human gate." >&2; exit 2; }
fi

BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 2
TREE=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh") || exit 2
SERIES=$(review_series_current "$ROOT" "$BRANCH" 2>/dev/null) || {
  echo "review-retain: no open review series for this branch incarnation." >&2; exit 2;
}
HOSTS=codex
[ "$MODE" != no-result ] || HOSTS="codex claude"
ATTEMPT=""
for HOST in $HOSTS; do
  CANDIDATE=$(review_attempt_pending_for "$ROOT" "$SERIES" "$HOST")
  case $? in
    0) ;;
    1) continue ;;
    *) echo "review-retain: pending reviewer evidence is invalid or ambiguous; preserve it and resolve the lookup error above." >&2; exit 2 ;;
  esac
  [ -z "$ATTEMPT" ] || {
    echo "review-retain: multiple pending reviewers; identify each reviewer's actual outcome before retaining either." >&2
    exit 2
  }
  ATTEMPT="$CANDIDATE"
done
[ -n "$ATTEMPT" ] || {
  echo "review-retain: no unique pending reviewer for this mode ($HOSTS). Inspect round-status.sh and the original host outcome." >&2
  exit 2
}
[ "$(jq -r '.branch' "$ATTEMPT/start.json")" = "$BRANCH" ] \
  && [ "$(jq -r '.tree' "$ATTEMPT/start.json")" = "$TREE" ] || {
    echo "review-retain: the pending attempt is not bound to the current branch and tree." >&2; exit 2;
  }

if [ "$MODE" = no-result ]; then
  # Parent observed termination with zero bytes, unrelated to a user stop/cancellation.
  review_attempt_complete "$ROOT" "$ATTEMPT" empty - "" "" true || exit 2
  echo "review-retain: ended reviewer returned no bytes; attempt retained and still counts."
  echo "Run round-status.sh; admit a fresh reviewer in this series if allowance remains."
elif [ "$MODE" = interrupted ]; then
  # Codex has no later host session whose start can safely distinguish an abandoned
  # attempt. Record the observed fact (zero response bytes) so the ambiguous-outcome
  # human gate is required. Claude's separate session-bound recovery remains interrupted.
  review_attempt_complete "$ROOT" "$ATTEMPT" empty - || exit 2
  printf 'review-retain: recorded %s as empty after the reviewer ended without response bytes.\n' "${ATTEMPT##*/}"
  codex_gate_present review ambiguous
else
  review_attempt_complete "$ROOT" "$ATTEMPT" completed "$RAW" || exit 2
  printf 'review-retain: retained %s as %s.\n' "${ATTEMPT##*/}" "$(jq -r '.outcome' "$ATTEMPT/completion.json")"
fi
