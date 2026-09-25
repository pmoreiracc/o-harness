#!/usr/bin/env bash
# The CI equivalent of the doc-lifecycle hooks, diffed against a base ref.
#
# Hooks are for speed and run on one machine; this runs on a clean checkout and cannot be
# skipped by using a tool the hook does not match. Where the two disagree, this one wins.
#
# Usage:  verify-docs.sh [base-ref]        default: origin/main
set -uo pipefail

BASE="${1:-origin/main}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$(cd "$DIR/.." && pwd)/lib.sh" || { echo "verify-docs: core/lib.sh is missing." >&2; exit 1; }
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
cd "$ROOT" || exit 1

fails=0
fail() { fails=$((fails+1)); echo "FAIL  $1" >&2; }
ok()   { echo "ok    $1"; }

git rev-parse --verify "$BASE" >/dev/null 2>&1 || { echo "verify-docs: unknown base ref '$BASE'" >&2; exit 1; }

# Local before-review verification includes the working tree. Keep tracked and untracked,
# non-ignored docs in the same inventories so a new file cannot trigger this verifier and
# then remain invisible to it. The accepted-ADR check below intentionally stays commit-based.
DOC_FILES=$( {
  git ls-files -- 'docs/**/*.md' 'docs/*.md'
  git ls-files --others --exclude-standard -- 'docs/**/*.md' 'docs/*.md'
} | awk 'NF && !seen[$0]++') || exit 1
ADR_FILES=$( {
  git ls-files -- 'docs/decisions/[0-9]*.md'
  git ls-files --others --exclude-standard -- 'docs/decisions/[0-9]*.md'
} | awk 'NF && !seen[$0]++') || exit 1
LINK_FILES=$( {
  git ls-files -- 'docs/**/*.md' 'docs/*.md' 'core/**/*.md' 'core/*.md' \
                   '.codex/**/*.md' '.codex/*.md' '.agents/**/*.md' '.agents/*.md'
  git ls-files --others --exclude-standard -- 'docs/**/*.md' 'docs/*.md' \
                   'core/**/*.md' 'core/*.md' '.codex/**/*.md' '.codex/*.md' \
                   '.agents/**/*.md' '.agents/*.md'
} | awk 'NF && !seen[$0]++') || exit 1

# --- 1. accepted ADRs are immutable ---------------------------------------------------
CHANGED_ADRS=$(git diff --name-only "$BASE...HEAD" -- 'docs/decisions/[0-9]*.md' 2>/dev/null)
adr_violations=0
for f in $CHANGED_ADRS; do
  git cat-file -e "$BASE:$f" 2>/dev/null || continue          # new ADR — always fine
  STATUS=$(git show "$BASE:$f" 2>/dev/null | fm_value_text status)
  [ "$STATUS" = "accepted" ] || continue
  OFFENDING=$(git diff -U0 "$BASE...HEAD" -- "$f" \
    | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)' \
    | grep -vE '^[+-][[:space:]]*(status|superseded-by):' | head -3)
  if [ -n "$OFFENDING" ]; then
    fail "$f was accepted at $BASE and changed beyond the supersede flip"
    printf '%s\n' "$OFFENDING" | sed 's/^/        /' >&2
    adr_violations=1
  fi
done
[ "$adr_violations" = 0 ] && ok "accepted ADRs unchanged"

# --- 2. every doc carries valid frontmatter -------------------------------------------
fm_bad=0
while IFS= read -r f; do
  case "$f" in */README.md|README.md) continue ;; esac
  [ -f "$f" ] || continue
  FM=$(frontmatter "$f")
  get() { fm_value "$f" "$1"; }
  if [ -z "$FM" ]; then fail "$f has no frontmatter"; fm_bad=1; continue; fi
  TYPE=$(get type); STATUS=$(get status)
  [ -n "$TYPE" ]   || { fail "$f has no 'type:'"; fm_bad=1; continue; }
  [ -n "$STATUS" ] || { fail "$f has no 'status:'"; fm_bad=1; continue; }
  case "$f:$TYPE" in
    docs/decisions/*:decision|docs/reference/*:reference|docs/design/*:design|docs/roadmap.md:plan) ;;
    *) fail "$f: type '$TYPE' does not match the directory that owns that lifecycle"; fm_bad=1; continue ;;
  esac
  case "$TYPE" in
    decision) case "$STATUS" in proposed|accepted|superseded) ;; *) fail "$f: bad decision status '$STATUS'"; fm_bad=1 ;; esac
              [ -n "$(get date)" ] || { fail "$f: a decision needs 'date:'"; fm_bad=1; }
              SUBJECT=$(get subject)
              case "$SUBJECT" in ""|harness) ;; *) fail "$f: bad decision subject '$SUBJECT' (omit it, or use 'harness')"; fm_bad=1 ;; esac ;;
    reference|plan) case "$STATUS" in draft|living) ;; *) fail "$f: bad $TYPE status '$STATUS'"; fm_bad=1 ;; esac
              [ -n "$(get last-verified)" ] || { fail "$f: needs 'last-verified:'"; fm_bad=1; } ;;
    design)   case "$STATUS" in draft|approved|frozen|abandoned) ;; *) fail "$f: bad design status '$STATUS'"; fm_bad=1 ;; esac
              [ -n "$(get last-verified)" ] || { fail "$f: needs 'last-verified:'"; fm_bad=1; }
              DELIVERED=$(get delivered)
              if [ "$STATUS" = "frozen" ] && [ -z "$DELIVERED" ]; then fail "$f: frozen needs 'delivered:'"; fm_bad=1; fi
              if [ "$STATUS" != "frozen" ] && [ -n "$DELIVERED" ]; then fail "$f: only frozen may carry 'delivered:'"; fm_bad=1; fi ;;
  esac
done <<EOF
$DOC_FILES
EOF
[ "$fm_bad" = 0 ] && ok "every doc carries valid frontmatter"

# --- 3. every ADR is in the log -------------------------------------------------------
log_bad=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  b=$(basename "$f")
  grep -qF "$b" docs/decisions/README.md || { fail "$b is not in the log table"; log_bad=1; }
done <<EOF
$ADR_FILES
EOF
[ "$log_bad" = 0 ] && ok "every ADR appears in the log"

# --- 4. internal links resolve --------------------------------------------------------
link_bad=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  d=$(dirname "$f")
  for l in $(awk '/^```/ { inf = !inf; next } !inf { print }' "$f" \
    | grep -oE '\]\(\.[^)#]*\.md' 2>/dev/null | sed 's/^](//'); do
    [ -e "$d/$l" ] || { fail "$f links to a missing file: $l"; link_bad=1; }
  done
done <<EOF
$LINK_FILES
EOF
[ "$link_bad" = 0 ] && ok "internal doc links resolve"

echo
if [ "$fails" -gt 0 ]; then echo "$fails check(s) failed" >&2; exit 1; fi
echo "docs verified against $BASE"
