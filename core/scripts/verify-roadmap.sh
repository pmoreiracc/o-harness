#!/usr/bin/env bash
# The roadmap is a registry, so it gets checked like one.
#
# The rules live in docs/roadmap.md, "How to read a table". This enforces the mechanical
# half of them; whether a dependency is a *hard* edge, and whether a row is really an
# initiative, are judgement and stay with the reviewer.
#
# A slug is an identity: /design takes it, a design doc's frontmatter will carry it, and
# `depends` edges point at it. An identity that is duplicated, unreachable, or names work
# in a milestone that already shipped is worse than no registry at all — it looks like
# state and answers wrongly.
#
# Usage:  verify-roadmap.sh [base-ref]        default: origin/main
set -uo pipefail

BASE="${1:-origin/main}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
cd "$ROOT" || exit 1

fails=0
fail() { fails=$((fails+1)); echo "FAIL  $1" >&2; }
ok()   { echo "ok    $1"; }
# A check that did not run gets its own channel. On the ok channel it reads as a check
# that passed, which is the thing this file exists to stop other people doing.
US=$(printf '\037')

# Same guard as verify-docs and verify-delivery. Without it, a mis-set ref — `origin/`,
# which is what github.base_ref yields outside a pull_request — skipped check 6 and still
# printed "roadmap verified against origin/". A green line for a check that did not run.
git rev-parse --verify "$BASE" >/dev/null 2>&1 \
  || { echo "verify-roadmap: unknown base ref '$BASE'" >&2; exit 1; }

# --- 0. it parses at all --------------------------------------------------------------
STATE=$("$DIR/roadmap.sh" 2>&1)
if [ $? -ne 0 ]; then
  echo "FAIL  the roadmap does not parse" >&2
  printf '%s\n' "$STATE" | sed 's/^/      /' >&2
  echo >&2
  echo "1 check(s) failed" >&2
  exit 1
fi
ok "the roadmap parses"

MILESTONES=$("$DIR/roadmap.sh" --milestones 2>/dev/null)
SLUGS=$(printf '%s\n' "$STATE" | cut -d"$US" -f1)

# --- 1. slugs are unique --------------------------------------------------------------
DUPES=$(printf '%s\n' "$SLUGS" | sort | uniq -d)
if [ -n "$DUPES" ]; then
  fail "duplicate slugs: $(printf '%s' "$DUPES" | tr '\n' ' ')"
  echo "        A slug is an identity. Two rows sharing one means /design resolves to" >&2
  echo "        whichever the parser reached first." >&2
else
  ok "every slug is unique"
fi

# --- 2. milestone ids are unique, and every unshipped one states its bar ---------------
MDUPES=$(printf '%s\n' "$MILESTONES" | cut -d"$US" -f1 | sort | uniq -d)
[ -n "$MDUPES" ] && fail "duplicate milestone ids: $(printf '%s' "$MDUPES" | tr '\n' ' ')"

nobar=""
while IFS="$US" read -r m shipped dw; do
  [ -n "$m" ] || continue
  [ "$shipped" = "shipped" ] && continue
  [ "$dw" = "done-when" ] || nobar="$nobar $m"
done <<EOF
$MILESTONES
EOF
if [ -n "$nobar" ]; then
  fail "milestone(s) with no 'Done when:':$nobar"
  echo "        A milestone with no acceptance criterion cannot be checked off, only" >&2
  echo "        declared finished." >&2
elif [ -z "$MDUPES" ]; then
  ok "milestone ids are unique and every unshipped one states its bar"
fi

# --- 3. every dependency resolves -----------------------------------------------------
dep_bad=0
while IFS="$US" read -r slug ms deps design; do
  [ -n "$slug" ] || continue
  [ -n "$deps" ] || continue
  for d in $(printf '%s' "$deps" | tr ',' ' '); do
    printf '%s\n' "$SLUGS" | grep -qxF "$d" && continue
    printf '%s\n' "$MILESTONES" | cut -d"$US" -f1 | grep -qxF "$d" && continue
    fail "$slug depends on '$d', which is neither a slug nor a milestone"
    dep_bad=1
  done
done <<EOF
$STATE
EOF
[ "$dep_bad" = 0 ] && ok "every dependency resolves to a slug or a milestone"

# --- 4. the dependency graph is acyclic -----------------------------------------------
# Kahn: strip anything whose dependencies are all already stripped. Whatever will not
# strip is in a cycle. Checked properly rather than by row order, because row order is a
# reading convenience and a reorder must not silently turn into a cycle.
#
# A milestone id stands for every slug in it. Left unexpanded it matched nothing in the
# frontier and so never blocked, and this pair reported "acyclic" while deadlocking:
#   M1 | `alpha` | … | `M2`    — waits for all of M2
#   M2 | `beta`  | … | `alpha` — is in M2, waits for alpha
expand_deps() {
  local out="" d
  for d in $(printf '%s' "$1" | tr ',' ' '); do
    if printf '%s\n' "$SLUGS" | grep -qxF "$d"; then
      out="$out $d"
    else
      out="$out $(printf '%s\n' "$STATE" | awk -F"$US" -v m="$d" '$2==m {print $1}' | tr '\n' ' ')"
    fi
  done
  printf '%s' "$out"
}

if [ "$dep_bad" = 0 ]; then
  REMAIN=$(printf '%s\n' "$SLUGS")
  while :; do
    [ -n "$REMAIN" ] || break
    NEXT=""; moved=0
    for s in $REMAIN; do
      deps=$(printf '%s\n' "$STATE" | awk -F"$US" -v s="$s" '$1==s {print $3; exit}')
      blocked=0
      for d in $(expand_deps "$deps"); do
        printf '%s\n' "$REMAIN" | grep -qxF "$d" && { blocked=1; break; }
      done
      if [ "$blocked" = 1 ]; then NEXT="$NEXT$s
"; else moved=1; fi
    done
    REMAIN=$(printf '%s' "$NEXT" | grep -v '^$')
    [ "$moved" = 1 ] || break
  done
  if [ -n "$REMAIN" ]; then
    fail "dependency cycle among: $(printf '%s' "$REMAIN" | tr '\n' ' ')"
  else
    ok "the dependency graph is acyclic"
  fi
fi

# --- 5. every design reference resolves -----------------------------------------------
design_bad=0
while IFS="$US" read -r slug ms deps design; do
  [ -n "$design" ] || continue
  F=$(ls "docs/design/$design"-*.md 2>/dev/null | head -1)
  if [ -z "$F" ]; then
    fail "$slug names design doc $design, which does not exist"
    design_bad=1
  fi
done <<EOF
$STATE
EOF
[ "$design_bad" = 0 ] && ok "every design reference resolves"

echo
if [ "$fails" -gt 0 ]; then echo "$fails check(s) failed" >&2; exit 1; fi
echo "roadmap verified against $BASE"
