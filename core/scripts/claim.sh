#!/usr/bin/env bash
# The only way a roadmap row acquires its design doc. Writes one cell and proves it.
#
# Usage:  claim.sh <slug> <design-doc-number>
#
# Exit 0  claimed (or already claimed by this doc — idempotent on purpose)
# Exit 1  error, or the edit changed more than the one line it was allowed to
# Exit 3  the row already names a different doc
# Exit 5  no review of this tree
#
# This is /design's complete.sh. A design run ticks no task box, so without it the run has
# no state transition at all — and a review nothing gates is a paragraph. Claiming the row
# is the one thing /design changes about the registry, so that is what review authority buys.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
. "${OH_HOME:-$ROOT}/core/review-receipt.sh" || {
  echo "claim.sh: shared review receipt contract is missing or unreadable." >&2
  exit 1
}
SLUG="${1:-}"
NUM="${2:-}"

case "$SLUG$NUM" in
  ""|*" "*) echo "usage: claim.sh <slug> <design-doc-number>" >&2; exit 1 ;;
esac
case "$NUM" in
  [0-9][0-9][0-9][0-9]) ;;
  *) echo "claim.sh: '$NUM' is not a four-digit design doc number." >&2; exit 1 ;;
esac

FILE="$ROOT/docs/roadmap.md"
[ -f "$FILE" ] || { echo "claim.sh: no docs/roadmap.md under $ROOT" >&2; exit 1; }

DOC=$(ls "$ROOT/docs/design/$NUM"-*.md 2>/dev/null | head -1)
if [ -z "$DOC" ]; then
  echo "claim.sh: no design doc matching docs/design/$NUM-*.md." >&2
  echo "Write the doc first; the row points at something that exists." >&2
  exit 1
fi
BN=$(basename "$DOC")

RECOVERY_OUTPUT=$(review_consumption_recover_current "$ROOT" "claim:$SLUG:$NUM" "$FILE" 2>/dev/null)
if [ $? -eq 0 ]; then
  echo "claim.sh: recovered the already-applied roadmap claim and closed its review series." >&2
  exit 0
fi

US=$(printf '\037')
ROW=$("$DIR/roadmap.sh" 2>/dev/null | awk -F"$US" -v s="$SLUG" '$1==s {print; exit}')
if [ -z "$ROW" ]; then
  echo "claim.sh: no initiative '$SLUG' in the roadmap." >&2
  exit 1
fi
HAS=$(printf '%s' "$ROW" | cut -d"$US" -f4)
if [ "$HAS" = "$NUM" ]; then
  echo "claim.sh: '$SLUG' already names $NUM — nothing to do." >&2
  exit 0
fi
if [ -n "$HAS" ]; then
  echo "STOP: '$SLUG' already names design doc $HAS, not $NUM." >&2
  echo "A row covers one initiative and one doc. Two docs for one row means the roadmap" >&2
  echo "was two initiatives." >&2
  exit 3
fi

# --- the review must have seen THIS tree ----------------------------------------------
# Same chain complete.sh uses: the attempt is written by host hooks, not by the model, and any
# edit after review moves the digest.
DIGEST=$("$DIR/tree-digest.sh")
if [ -z "$DIGEST" ]; then
  echo "STOP: cannot fingerprint the working tree, so the review cannot be verified." >&2
  echo "claim.sh runs inside a git repository. Failing closed." >&2
  exit 5
fi
REVIEW_KEY=$(review_current_key "$ROOT" 2>/dev/null || true)
if ! review_receipt_validate "$ROOT" "$DIGEST"; then
  echo "STOP: no review of the current tree (digest $DIGEST)." >&2
  echo "" >&2
  if review_rejection_note "$ROOT" "$DIGEST" >&2; then
    exit 5
  fi
  echo "Delegate the design doc to the invariant-reviewer subagent — the decomposition," >&2
  echo "not a diff. Its attempt is written by the hooks, not by you." >&2
  echo "" >&2
  if [ -n "$REVIEW_KEY" ] && review_key_has_history "$ROOT" "$REVIEW_KEY"; then
    echo "There are attempts for earlier trees of this review key, so the doc changed after review." >&2
    echo "Re-review: whatever was written afterwards has not been looked at." >&2
  fi
  exit 5
fi
if ! review_completion_authorized "$ROOT" "$DIGEST"; then
  echo "REFUSED: the current review does not authorize this claim; no claim applied." >&2
  review_completion_diagnose "$ROOT"
  exit 5
fi
AUTH_ATTEMPT=$(review_receipt_attempt "$ROOT" "$DIGEST" 2>/dev/null || true)

# --- write the one cell ---------------------------------------------------------------
mkdir -p "$ROOT/.deliver/transitions" || exit 1
TMP=$(mktemp "$ROOT/.deliver/transitions/.claim.XXXXXX") || exit 1
trap 'rm -f "${TMP:-}"' EXIT
cp -p "$FILE" "$TMP" || exit 1
awk -v slug="$SLUG" -v link="[$NUM](./design/$BN)" '
  $0 ~ "^\\| `" slug "` \\|" {
    n = split($0, f, "|")
    if (n == 6 && f[5] ~ /^[[:space:]]*—[[:space:]]*$/) {
      printf "|%s|%s|%s| %s |\n", f[2], f[3], f[4], link
      next
    }
  }
  { print }
' "$FILE" > "$TMP"

CHANGED=$(diff "$FILE" "$TMP" | grep -c '^[<>]')
if [ "$CHANGED" -ne 2 ]; then
  rm -f "$TMP"
  echo "claim.sh: the edit would have changed $((CHANGED / 2)) lines, not 1. Aborted." >&2
  exit 1
fi

if [ -n "$AUTH_ATTEMPT" ]; then
  review_consumption_intent_start "$ROOT" "$AUTH_ATTEMPT" "claim:$SLUG:$NUM" "$FILE" "$TMP" "" || {
    echo "claim.sh: could not publish the recoverable claim intent. The roadmap is unchanged." >&2
    exit 1
  }
fi
mv "$TMP" "$FILE" || { echo "claim.sh: could not atomically replace docs/roadmap.md." >&2; exit 1; }
TMP=""
if [ -n "$AUTH_ATTEMPT" ]; then
  review_consumption_recover "$ROOT" "$AUTH_ATTEMPT" "claim:$SLUG:$NUM" "$FILE" >/dev/null || {
    echo "claim.sh: roadmap changed, but its recoverable transition could not be completed." >&2
    exit 1
  }
else
  review_completion_close "$ROOT" "$DIGEST" "$REVIEW_KEY" || {
    echo "claim.sh: roadmap changed, but the consumed review series could not be closed." >&2
    exit 1
  }
fi
echo "claimed '$SLUG' for design doc $NUM in docs/roadmap.md" >&2
