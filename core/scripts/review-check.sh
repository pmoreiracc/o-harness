#!/usr/bin/env bash
# Advisory preview of the semantic result the host will retain (ADR-0051).
#
# Reads the draft on stdin and writes nothing under .deliver/: this is not evidence and cannot
# mint, count or satisfy anything (ADR-0047).
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
. "$DIR/../review-receipt.sh" || exit 2

# The Codex reviewer is read-only except for /tmp, so keep the transient draft there.
TMPDIR=/tmp
export TMPDIR

DRAFT=$(mktemp "$TMPDIR/review-draft.XXXXXX") || {
  echo "review-check: no writable scratch space; the draft could not be checked." >&2
  exit 2
}
trap 'rm -f "$DRAFT"' EXIT
cat > "$DRAFT" || exit 2
[ -s "$DRAFT" ] || {
  echo "review-check: the draft is empty; pipe the complete review into this script." >&2
  exit 2
}

RESULT=$(review_semantic_json "$DRAFT") || exit 2
OUTCOME=$(printf '%s' "$RESULT" | jq -r '.outcome')
ANOMALY=$(printf '%s' "$RESULT" | jq -r '.formatAnomalous')
echo "review-output: semantic outcome $OUTCOME"
[ "$ANOMALY" = false ] || echo "review-output: readability warning — noncanonical formatting will still be retained" >&2
[ "$OUTCOME" != ambiguous ] || exit 1
