#!/usr/bin/env bash
# GUARDRAIL — accepted ADRs are immutable.
#
# Enforces: docs/decisions/README.md, "This directory is append-only. An ADR is
# immutable once accepted. You do not edit ADR-0007 when you change your mind — you
# write a new ADR that supersedes it."
#
# "Accepted" means accepted on the trunk (ADR-0036). A draft that has not merged is
# editable, whatever its frontmatter says — otherwise a review of a new ADR could never be
# acted on, and the hook would be stricter than the CI check it is a fast copy of.
#
# The single permitted edit to an ADR accepted there is the supersede flip:
#     status: accepted   ->   status: superseded
#                             superseded-by: 00NN
# So this hook allows edits whose changed lines are *only* `status:` / `superseded-by:`,
# and blocks everything else.
#
# Scope: Edit and Write only, inspected exactly. Writes made any other way — sed, a
# script, an editor — are caught after the fact by adr-write-detector.sh, which reads
# `git diff` instead of guessing from a command string. CI is the authority
# (see core/README.md).
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/hooks/lib.sh is missing or unreadable." >&2
  echo "No operation was inspected. Restore this reviewed harness file in the checkout and retry; do not disable the guardrail." >&2
  exit 2
}
hook_init

TOOL=$(hook_field '.tool_name')

block() {
  echo "BLOCKED — accepted ADRs are immutable (docs/decisions/README.md)." >&2
  echo "" >&2
  echo "$1" >&2
  echo "" >&2
  if [ -n "${2:-}" ]; then echo "$2" >&2; exit 2; fi
  echo "This edit was rejected. To change a decision, write a NEW ADR that explicitly" >&2
  echo "narrows or supersedes the relevant decision. For full supersession, flip the" >&2
  echo "old one's frontmatter to 'status: superseded' + 'superseded-by: <n>'. That flip" >&2
  echo "is the only edit this guardrail permits." >&2
  exit 2
}

# ------------------------------------------------------------- Edit / Write: exact check
FILE=$(hook_field '.tool_input.file_path')
[ -n "$FILE" ] || exit 0

REL=$(repo_rel "$FILE")
case "$REL" in
  docs/decisions/[0-9][0-9][0-9][0-9]-*.md) ;;
  *) exit 0 ;;
esac

# Immutability begins at the merge (ADR-0036), so the status comes from the trunk and not
# from the working copy. An ADR with no version on the trunk is a draft however its own
# frontmatter reads — which is what makes a review of a new ADR actionable at all.
if ! STATUS=$(trunk_status "$REL"); then
  block "Cannot resolve $TRUNK_REF, so the trunk status of $REL is unknown.
Run 'git fetch origin main' and retry. The guardrail blocks rather than assume a draft." \
    "Resolve the trunk reference, then retry this edit; no new ADR is required merely for a missing ref."
fi

[ "$STATUS" = "accepted" ] || exit 0

if [ "$TOOL" = "Write" ]; then
  block "Write would replace the whole file: $REL (status: accepted)"
fi

# Edit: permitted only when every changed line is a frontmatter status/superseded-by line.
#
# Two payload shapes are accepted — {edits:[{old_text,new_text}]} and the flat
# {old_string,new_string} — because the guardrail must not fall open if the harness
# changes shape. If NEITHER is present we cannot inspect the change, so we block.
CHANGED=$(printf '%s' "$PAYLOAD" | jq -r '
  [ (.tool_input.edits[]? | .old_text, .new_text),
    .tool_input.old_string?, .tool_input.new_string? ]
  | map(select(. != null))
  | .[]
' 2>/dev/null)

if [ -z "$CHANGED" ]; then
  block "Cannot inspect this Edit to $REL (status: accepted) — the payload carried no
recognisable edit text. The guardrail blocks rather than assume the change is safe." \
    "Include the removed and intended replacement text (empty replacement may mean deletion); if no edit is needed, omit it and continue."
fi

OFFENDING=$(printf '%s\n' "$CHANGED" \
  | grep -v '^[[:space:]]*$' \
  | grep -vE '^[[:space:]]*(status|superseded-by):' \
  | head -5)

if [ -n "$OFFENDING" ]; then
  block "Edit to $REL (status: accepted) changes lines beyond the supersede flip:
$(printf '%s' "$OFFENDING" | sed 's/^/    /')"
fi

exit 0
