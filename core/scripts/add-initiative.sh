#!/usr/bin/env bash
# The only way a row enters the roadmap. Adds one and proves it.
#
# Usage:  add-initiative.sh <milestone> <slug> <depends|-> "<initiative>"
#
# Exit 0  added (or already present with the same milestone — idempotent)
# Exit 1  error, or the edit changed more than the one line it was allowed to
# Exit 3  the slug is already in the roadmap under a different milestone
#
# The roadmap is the registry everything downstream keys on — /design resolves a slug
# against it, verify-design.sh requires an approved doc to be claimed by it — so a row is
# not a note, it is state. This refuses the ways a row can be wrong that a script can see.
# It is NOT claim.sh: there is no review gate here, for the reason given further down.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
MS="${1:-}"
SLUG="${2:-}"
DEPS="${3:-}"
TEXT="${4:-}"

if [ -z "$MS" ] || [ -z "$SLUG" ] || [ -z "$DEPS" ] || [ -z "$TEXT" ]; then
  echo 'usage: add-initiative.sh <milestone> <slug> <depends|-> "<initiative>"' >&2
  echo '  depends is a comma-separated list of slugs or milestone ids, or - for none' >&2
  exit 1
fi

case "$MS" in
  M[0-9]) ;;
  *) echo "add-initiative.sh: '$MS' is not a milestone id." >&2; exit 1 ;;
esac
case "$SLUG" in
  *[!a-z0-9-]*|-*|*-|*--*) echo "add-initiative.sh: '$SLUG' is not a kebab-case slug." >&2; exit 1 ;;
esac
case "$TEXT" in
  *"|"*) echo "add-initiative.sh: the initiative text cannot contain a pipe." >&2; exit 1 ;;
esac

FILE="$ROOT/docs/roadmap.md"
[ -f "$FILE" ] || { echo "add-initiative.sh: no docs/roadmap.md under $ROOT" >&2; exit 1; }

US=$(printf '\037')
STATE=$("$DIR/roadmap.sh" 2>&1) || {
  echo "add-initiative.sh: the roadmap does not parse. Fix it before adding to it." >&2
  printf '%s\n' "$STATE" | sed 's/^/  /' >&2
  exit 1
}

EXISTING=$(printf '%s\n' "$STATE" | awk -F"$US" -v s="$SLUG" '$1==s {print $2; exit}')
if [ "$EXISTING" = "$MS" ]; then
  echo "add-initiative.sh: '$SLUG' is already in $MS — nothing to do." >&2
  exit 0
fi
if [ -n "$EXISTING" ]; then
  echo "STOP: '$SLUG' already exists, in $EXISTING." >&2
  echo "A slug is an identity. Reusing one makes /design resolve to whichever row the" >&2
  echo "parser reached first." >&2
  exit 3
fi

# The milestone must exist, and must not have shipped: a shipped milestone is a record.
MSTATE=$("$DIR/roadmap.sh" --milestones 2>/dev/null | awk -F"$US" -v m="$MS" '$1==m {print; exit}')
if [ -z "$MSTATE" ]; then
  echo "add-initiative.sh: the roadmap has no milestone $MS." >&2
  exit 1
fi
if [ "$(printf '%s' "$MSTATE" | cut -d"$US" -f2)" = "shipped" ]; then
  echo "STOP: $MS has already shipped. New work belongs in an open milestone, or a new one." >&2
  exit 1
fi

# Every dependency has to resolve now, not at verify time — a row naming nothing is a row
# whose ordering is a guess.
if [ "$DEPS" != "-" ]; then
  # The shape first, then the members. `,` and ` ` both word-split to nothing, so the loop
  # below never ran for them and they reached the writer — one produced a row with an empty
  # dependency cell, the other a row that would not parse at all.
  case "$DEPS" in
    *,,*|,*|*,|*[[:space:]]*)
      echo "add-initiative.sh: '$DEPS' is not a comma-separated list of slugs." >&2
      echo "Use a single '-' for no dependencies." >&2
      exit 1 ;;
  esac
  for d in $(printf '%s' "$DEPS" | tr ',' ' '); do
    printf '%s\n' "$STATE" | cut -d"$US" -f1 | grep -qxF "$d" && continue
    printf '%s' "$d" | grep -qE '^M[0-9]$' && continue
    echo "add-initiative.sh: '$SLUG' would depend on '$d', which is neither a slug nor a milestone." >&2
    exit 1
  done
fi

# No receipt gate here, deliberately — and the reason is worth stating so nobody adds one
# back. claim.sh can demand a receipt because /design writes the design doc first, so the
# reviewed tree contains the thing being claimed. This row is the only artifact a propose
# run produces, and it does not exist until this script writes it. A receipt taken before
# that is a receipt for a tree with nothing of the proposal in it — on a branch freshly cut
# from main it is main's own digest, satisfied by any earlier review, for free, forever.
#
# So the review that matters here is unpinned. What this script does instead is refuse a
# row that is wrong in a way a script can see: a taken slug, a shipped milestone, a
# dependency that resolves to nothing, output that will not parse. The classification —
# the judgement that decides whether this row should exist at all — reaches the human in
# the PR, checked by nobody.

# --- insert the row at the end of its milestone's table --------------------------------
if [ "$DEPS" = "-" ]; then CELL="—"; else
  CELL=$(printf '%s' "$DEPS" | sed 's/,/`, `/g'); CELL="\`$CELL\`"
fi
ROW="| \`$SLUG\` | $TEXT | $CELL | — |"

# Straight after the last row of that milestone's table — not before its "Done when:",
# which would leave a blank line between and split one table into two.
LAST=$(awk -v ms="$MS" '
  /^###[[:space:]]+M[0-9]+([[:space:]]|$)/ { match($0, /M[0-9]+/); cur = substr($0, RSTART, RLENGTH); next }
  /^#{2,3}[[:space:]]/ { cur = ""; next }
  cur == ms && /^\|[[:space:]]*`[a-z0-9-]+`[[:space:]]*\|/ { last = NR }
  END { print last + 0 }
' "$FILE")
if [ "$LAST" = "0" ]; then
  echo "add-initiative.sh: $MS has no initiative table to add a row to." >&2
  exit 1
fi

TMP=$(mktemp)
BACKUP=$(mktemp)
trap 'rm -f "$TMP" "$BACKUP"' EXIT
cp "$FILE" "$BACKUP"

# ROW travels through the environment, not `awk -v`: -v expands backslash escapes, so an
# initiative reading "Escape \n handling in the importer" became two lines and a broken
# table. Prose is data here, not a format string.
ROW="$ROW" awk -v n="$LAST" 'NR == n { print; print ENVIRON["ROW"]; next } { print }' "$FILE" > "$TMP"

# Exactly one line, never a range. A legitimate insert adds one; the only thing a window
# of two ever admitted was a row that had split itself in half.
CHANGED=$(diff "$FILE" "$TMP" | grep -c '^[<>]')
if [ "$CHANGED" -ne 1 ]; then
  echo "add-initiative.sh: the edit would have changed $CHANGED lines, not 1. Aborted." >&2
  exit 1
fi

cat "$TMP" > "$FILE"

# Fail closed on our own output. Restored from a copy taken above, not from git: `git
# checkout -- <path>` reverts the file to the index, which would also throw away whatever
# else was uncommitted in it — and it fails silently outside a repository, leaving the
# broken row in place while claiming otherwise.
#
# Defence in depth, and reached in practice: a dependency list of "," passed the checks
# above until they were tightened, and landed a row the parser refused. Kept, and tested.
if ! "$DIR/roadmap.sh" >/dev/null 2>&1; then
  cp "$BACKUP" "$FILE"
  echo "add-initiative.sh: the row would not parse; the roadmap is unchanged." >&2
  exit 1
fi

echo "added '$SLUG' to $MS in docs/roadmap.md" >&2
