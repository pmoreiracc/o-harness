#!/usr/bin/env bash
# GUARDRAIL — detect any write to an accepted ADR, however it was made.
#
# Companion to adr-immutability.sh, which blocks Edit and Write before they happen.
# This one runs AFTER a Bash command and inspects what actually changed on disk, so it
# catches every path the pre-check cannot see: sed, python, gh, a script, a rogue editor.
#
# Why outcome-checking rather than command-scanning: the first version of this guard
# pattern-matched the Bash command string for `sed -i`, redirects and `docs/decisions/`.
# It blocked the pull request that introduced it, because the PR body *described* those
# patterns in prose. A heuristic over an arbitrary shell string cannot tell a write from
# a sentence about a write. `git diff` can, exactly.
#
# Detect, not prevent — the write already happened. It reports immediately so it is
# reverted in the same turn, and CI (which diffs against main and cannot be bypassed)
# remains the authority.
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

CHANGED=$(git -C "$ROOT" status --porcelain -- docs/decisions/ 2>/dev/null | cut -c4-)
[ -n "$CHANGED" ] || exit 0

# Something under docs/decisions/ moved, so the trunk status is needed to tell a decision
# from a draft. Unresolvable means unverifiable, and a guardrail that cannot inspect a
# change does not wave it through (ADR-0027).
if ! git -C "$ROOT" rev-parse --verify --quiet "$TRUNK_REF" >/dev/null 2>&1; then
  echo "docs/decisions/ changed, but $TRUNK_REF will not resolve — so whether any of it is" >&2
  echo "an accepted decision or a draft cannot be checked. Run 'git fetch origin main'." >&2
  exit 2
fi

VIOLATIONS=""
OLDIFS=$IFS
IFS='
'
for f in $CHANGED; do
  # Only ADRs accepted on the trunk are immutable (ADR-0036) — an ADR absent from it is a
  # draft, whether it is untracked or merely committed on this branch. Reading the trunk
  # rather than the working copy is also what stops a `status:` flip talking the guardrail
  # out of its job.
  STATUS=$(trunk_status "$f")
  [ "$STATUS" = "accepted" ] || continue

  # The supersede flip is the one permitted change: status / superseded-by lines only.
  #
  # Diffed against the working tree, not against the trunk: this guard reports a write that
  # just happened, while it is still uncommitted and one `git checkout` from gone. The
  # committed case belongs to verify-docs.sh, which diffs `$BASE...HEAD` in CI — diffing the
  # trunk here would re-report the same change on every Bash call until the branch merged.
  OFFENDING=$(git -C "$ROOT" diff -U0 -- "$f" 2>/dev/null \
    | grep -E '^[+-]' \
    | grep -vE '^(\+\+\+|---)' \
    | grep -vE '^[+-][[:space:]]*(status|superseded-by):' \
    | head -3)

  if [ -n "$OFFENDING" ]; then
    VIOLATIONS="$VIOLATIONS
  $f
$(printf '%s' "$OFFENDING" | sed 's/^/      /')"
  fi
done
IFS=$OLDIFS

[ -n "$VIOLATIONS" ] || exit 0

echo "An accepted ADR was modified on disk. Accepted ADRs are immutable" >&2
echo "(docs/decisions/README.md — the directory is append-only)." >&2
echo "$VIOLATIONS" >&2
echo "" >&2
echo "The write already applied. Inspect git diff for each named file and reverse only your prohibited hunks, preserving existing edits; rerun verify-docs.sh." >&2
echo "If ownership is unclear, show the affected hunks and ask before reverting them." >&2
echo "To change a decision, write a NEW ADR that supersedes this one, then flip the old" >&2
echo "one's frontmatter to 'status: superseded' + 'superseded-by: <n>'. That flip is the" >&2
echo "only change permitted to an accepted ADR." >&2
exit 2
