#!/usr/bin/env bash
# Stage and inspect an implementer-authored readiness manifest for a delivery review.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$DIR/../.." && pwd)}"
. "$DIR/../review-request.sh" || exit 1

usage() {
  echo "usage: review-ready.sh stage <doc> <task|finalize> <manifest-file>" >&2
  echo "       review-ready.sh status <doc> <task|finalize>" >&2
  echo "       review-ready.sh history <doc> <task|finalize>" >&2
  exit 1
}

ACTION="${1:-}"
DOC="${2:-}"
TASK="${3:-}"
case "$DOC" in [0-9][0-9][0-9][0-9]) ;; *) usage ;; esac
case "$TASK" in finalize) KEY=$(review_finalize_key "$DOC") ;; ''|*[!0-9]*) usage ;; *) KEY=$(review_request_key "$DOC" "$TASK") ;; esac
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 1
CONTEXT=$(review_request_context "$ROOT" "$BRANCH" 2>/dev/null)
CONTEXT_STATUS=$?
[ "$CONTEXT_STATUS" -eq 0 ] || {
  echo "review-ready: cannot resolve the delivery review context on $BRANCH." >&2
  exit 2
}
CURRENT_KEY="${CONTEXT%%$'\t'*}"
[ "$CURRENT_KEY" = "$KEY" ] || {
  echo "review-ready: $KEY is not the delivery task currently in flight on $BRANCH." >&2
  [ -n "$CURRENT_KEY" ] && echo "Current review key: $CURRENT_KEY" >&2
  exit 2
}
DIGEST=$(CLAUDE_PROJECT_DIR="$ROOT" "$DIR/tree-digest.sh") || exit 1

case "$ACTION" in
  stage)
    MANIFEST="${4:-}"
    [ -n "$MANIFEST" ] || usage
    REASON=$(review_manifest_check "$MANIFEST" "$ROOT" "$KEY") || {
      echo "review-ready: manifest refused: $REASON" >&2
      exit 2
    }
    OUT_DIR=$(review_request_dir "$ROOT" "$KEY" "$DIGEST")
    mkdir -p "$OUT_DIR" || exit 1
    TMP="$OUT_DIR/.request.$$"
    {
      echo "request-version: 1"
      echo "doc: $DOC"
      echo "task: $TASK"
      echo "tree: $DIGEST"
      echo "head: $(git -C "$ROOT" rev-parse HEAD)"
      echo "at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
      echo "authority: implementer claims — never review authority"
      echo "---"
      cat "$MANIFEST"
    } > "$TMP" || { rm -f "$TMP"; exit 1; }
    mv -f "$TMP" "$OUT_DIR/request.md" || exit 1
    echo "review-ready: staged $KEY for tree $DIGEST"
    echo "request: .deliver/review-requests/$KEY/$DIGEST/request.md"
    ;;
  status)
    if review_request_validate "$ROOT" "$KEY" "$DIGEST"; then
      echo "review-ready: yes"
      echo "key: $KEY"
      echo "tree: $DIGEST"
      echo "request: .deliver/review-requests/$KEY/$DIGEST/request.md"
    else
      echo "review-ready: no"
      echo "key: $KEY"
      echo "tree: $DIGEST"
      exit 3
    fi
    ;;
  history)
    review_request_receipts "$ROOT" "$KEY"
    ;;
  *) usage ;;
esac
