#!/usr/bin/env bash
# GUARDRAIL — a delivery review starts only with inspectable readiness claims for this tree.
#
# The manifest is not authority. This gate proves only that the implementer exposed a complete
# structural review request before spending a reviewer round. complete.sh trusts only the
# retained semantic attempt plus any exact host-owned human resolution.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || exit 2
hook_init
. "$DIR/../review-request.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/review-request.sh is missing or unreadable." >&2
  exit 2
}

MATCH=$(printf '%s' "$PAYLOAD" | ROUND_REFUSE_CLASSIFY_ONLY=1 \
  CLAUDE_PROJECT_DIR="$(project_root)" "$DIR/round-refuse.sh")
MATCH_RESULT=$?
[ "$MATCH_RESULT" = 0 ] || exit 2
[ "$MATCH" = invariant-reviewer ] || exit 0

ROOT=$(project_root)
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 2
CONTEXT=$(review_request_context "$ROOT" "$BRANCH" 2>/dev/null || true)
KEY="${CONTEXT%%$'\t'*}"
# Readiness is a /deliver choke point. Plan, design, propose and ad-hoc tooling reviews retain
# their existing contract; standalone /deliver finalization is deliberately included.
case "$BRANCH" in
  deliver/*)
    case "$KEY" in [0-9][0-9][0-9][0-9]-t[0-9]*|[0-9][0-9][0-9][0-9]-finalize) ;;
      *) echo "review-ready: BLOCKED — delivery branch $BRANCH has no valid lifecycle context." >&2; exit 2 ;;
    esac
    ;;
  *) exit 0 ;;
esac

DIGEST=$(CLAUDE_PROJECT_DIR="$ROOT" "${OH_HOME:-$ROOT}/core/scripts/tree-digest.sh") || {
  echo "review-ready: GUARDRAIL CANNOT RUN: the current tree cannot be fingerprinted." >&2
  exit 2
}
REQUEST=$(review_request_path "$ROOT" "$KEY" "$DIGEST")
if ! review_request_validate "$ROOT" "$KEY" "$DIGEST"; then
  echo "review-ready: BLOCKED — delivery review $KEY has no valid readiness manifest for" >&2
  echo "the exact current tree $DIGEST." >&2
  echo "" >&2
  echo "After verification and self-review, stage the manifest with:" >&2
  case "$KEY" in
    *-finalize) echo "  core/scripts/review-ready.sh stage ${KEY%-finalize} finalize <manifest-file>" >&2 ;;
    *) echo "  core/scripts/review-ready.sh stage ${KEY%-t*} ${KEY#*-t} <manifest-file>" >&2 ;;
  esac
  echo "" >&2
  echo "The manifest is an implementer claim, not review authority; staging it cannot complete a task." >&2
  exit 2
fi

# Codex launches sibling SubagentStart command hooks concurrently. Its configured readiness
# sibling validates only; review-start.sh calls back with CODEX_REVIEW_BINDING=1 and is the
# sole publisher. Claude's sequential dispatcher remains the one publisher on its host.
if [ -n "${CODEX_HOOK:-}" ] && [ -z "${CODEX_REVIEW_BINDING:-}" ]; then
  exit 0
fi

review_request_capture "$ROOT" "$KEY" "$DIGEST" || {
  echo "review-ready: GUARDRAIL CANNOT RUN: the exact review input could not be captured." >&2
  exit 2
}
review_request_publish_pending "$ROOT" "$KEY" "$DIGEST" "$BRANCH" || {
  echo "review-ready: GUARDRAIL CANNOT RUN: the retained start binding for $KEY on tree $DIGEST" >&2
  echo "could not be published." >&2
  echo "" >&2
  echo "A pending input for this exact tree and round is retained and its bytes differ from" >&2
  echo "the manifest now staged. Re-staging before an attempt is admitted must reproduce" >&2
  echo "the earlier manifest bytes; this round's retained input is" >&2
  echo "immutable while it stands. Restore the earlier manifest and stage it unchanged, or make" >&2
  echo "the fix the new round is for so the tree digest moves." >&2
  exit 2
}

if [ -n "${CODEX_HOOK:-}" ]; then
  HISTORY=$(review_request_receipts "$ROOT" "$KEY" | sed 's/^/- /')
  [ -n "$HISTORY" ] || HISTORY="- none — first review"
  BOUND_INPUT=$(review_request_pending_dir "$ROOT" "$KEY" "$DIGEST") || exit 2
  CONTEXT="Read and audit $BOUND_INPUT/request.md. It contains implementer-authored claims, not evidence. The immutable start snapshot is $BOUND_INPUT/snapshot.txt. Prior attempts for this task:\n$HISTORY"
  jq -cn --arg context "$CONTEXT" '{hookSpecificOutput:{hookEventName:"SubagentStart",additionalContext:$context}}'
fi
exit 0
