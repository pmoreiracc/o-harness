#!/usr/bin/env bash
# GUARDRAIL — every doc carries frontmatter, and it agrees with its lifecycle.
#
# Enforces: docs/README.md, "Every doc carries frontmatter. A doc without one is a doc
# nobody knows how to trust." These docs are read by the agent writing the code, and the
# agent cannot tell a stale doc from a current one — the frontmatter is the only signal
# it has.
#
# Directory indexes (README.md) are exempt: they describe the lifecycle rather than
# participating in it.
#
# Fires on Write only. Edits to an existing doc keep its frontmatter; the CI check that
# lands with the Phase 0 workflow validates every file on every PR regardless.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/hooks/lib.sh is missing or unreadable." >&2
  echo "No operation was inspected. Restore this reviewed harness file in the checkout and retry; do not disable the guardrail." >&2
  exit 2
}
hook_init

FILE=$(hook_field '.tool_input.file_path')
[ -n "$FILE" ] || exit 0

REL=$(repo_rel "$FILE")
case "$REL" in
  docs/*.md|docs/*/*.md) ;;
  *) exit 0 ;;
esac
case "$REL" in
  */README.md|README.md) exit 0 ;;
esac

[ "$(hook_field '.tool_name')" = Write ] || exit 0
[ "$(hook_field '.tool_input.patch_operation')" != delete ] || exit 0
TEXT=$(hook_field '.tool_input.file_text')

FM=$(printf '%s\n' "$TEXT" | frontmatter_text)

fm_get() { printf '%s\n' "$TEXT" | fm_value_text "$1"; }

block() {
  echo "BLOCKED — $REL: $1" >&2
  echo "" >&2
  echo "Required shape (docs/README.md):" >&2
  echo "" >&2
  echo "  ---" >&2
  echo "  type: reference        # decision | reference | plan | design" >&2
  echo "  status: draft          # decision: proposed|accepted|superseded" >&2
  echo "                         # reference/plan: draft|living" >&2
  echo "                         # design: draft|approved|frozen|abandoned" >&2
  echo "  last-verified: YYYY-MM-DD   # decisions carry 'date:' instead" >&2
  echo "  ---" >&2
  echo "" >&2
  echo "last-verified is the honest answer to 'is this still true?' — bump it when you" >&2
  echo "check, not when you edit. This write is rejected; correct the named field and retry in this run." >&2
  exit 2
}

[ -n "$FM" ] || block "no frontmatter block. Every doc carries one."

TYPE=$(fm_get "type")
STATUS=$(fm_get "status")

[ -n "$TYPE" ]   || block "frontmatter has no 'type:'."
[ -n "$STATUS" ] || block "frontmatter has no 'status:'."

case "$TYPE" in
  decision)
    case "$STATUS" in
      proposed|accepted|superseded) ;;
      *) block "status '$STATUS' is not valid for a decision (proposed | accepted | superseded)." ;;
    esac
    [ -n "$(fm_get 'date')" ] || block "a decision needs 'date:' (the day it was made)."
    SUBJECT=$(fm_get 'subject')
    case "$SUBJECT" in
      ""|harness) ;;
      *) block "subject '$SUBJECT' is not valid for a decision (omit it, or use harness)." ;;
    esac
    ;;
  reference|plan)
    case "$STATUS" in
      draft|living) ;;
      *) block "status '$STATUS' is not valid for a $TYPE (draft | living)." ;;
    esac
    [ -n "$(fm_get 'last-verified')" ] || block "a $TYPE doc needs 'last-verified:'."
    ;;
  design)
    case "$STATUS" in
      draft|approved|frozen|abandoned) ;;
      *) block "status '$STATUS' is not valid for a design doc (draft | approved | frozen | abandoned)." ;;
    esac
    [ -n "$(fm_get 'last-verified')" ] || block "a design doc needs 'last-verified:'."
    DELIVERED=$(fm_get 'delivered')
    if [ "$STATUS" = "frozen" ] && [ -z "$DELIVERED" ]; then
      block "a frozen design doc needs 'delivered:' (the milestone that shipped it)."
    fi
    if [ "$STATUS" != "frozen" ] && [ -n "$DELIVERED" ]; then
      block "only a frozen design doc may carry 'delivered:'."
    fi
    ;;
  *)
    block "type '$TYPE' is not one of: decision | reference | plan | design."
    ;;
esac

# Placement: the type must match the directory that owns that lifecycle.
case "$REL:$TYPE" in
  docs/decisions/*:decision|docs/reference/*:reference|docs/design/*:design|docs/roadmap.md:plan) ;;
  docs/decisions/*:*) block "a doc in decisions/ must be type: decision (found '$TYPE')." ;;
  docs/reference/*:*) block "a doc in reference/ must be type: reference (found '$TYPE')." ;;
  docs/design/*:*)    block "a doc in design/ must be type: design (found '$TYPE')." ;;
esac

exit 0
