#!/usr/bin/env bash
# Thin Codex-to-Claude hook dispatcher. The canonical controls stay under core/;
# this file supplies the environment and payload translation Codex requires.
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
if [ -z "$ROOT" ] || [ ! -d "${OH_HOME:-$ROOT}/core/hooks" ]; then
  echo "GUARDRAIL CANNOT RUN: the repository root or core/hooks cannot be resolved." >&2
  echo "No operation was inspected. Resolve the repository root and restore its reviewed adapter; retry here if the host can load it. Restart only if cached runner/trust cannot reload." >&2
  exit 2
fi

export CLAUDE_PROJECT_DIR="$ROOT"
export CODEX_HOOK=1

MODE="${1:-}"
shift || true

if [ "$MODE" = "edit" ]; then
  HOOK="${1:-}"
  case "$HOOK" in
    adr-immutability.sh|doc-frontmatter.sh|protect-receipts.sh|protect-local-policy.sh|adr-log-index.sh) ;;
    *) echo "GUARDRAIL CANNOT RUN: unknown Codex edit hook '$HOOK'. No edit inspected; correct the hooks.json target to a supported entry and retry." >&2; exit 2 ;;
  esac
  command -v node >/dev/null 2>&1 || {
    echo "GUARDRAIL CANNOT RUN: Node.js is required to inspect a Codex patch." >&2
    echo "The edit is rejected. Install/restore Node 22 on the runner PATH and retry this edit; independent work can continue." >&2
    exit 2
  }
  exec node "${OH_HOME:-$ROOT}/adapters/codex/translate-edit.mjs" "$HOOK"
fi

case "$MODE" in
  adr-write-detector.sh|main-branch-detector.sh|review-ready-gate.sh|review-start.sh|review-receipt.sh|review-pending-output.sh|review-choice.sh|review-detached-context.sh|enable-githooks.sh|round-grant.sh|task-grant.sh|round-refuse.sh|user-prompt-submit.sh) ;;
  *) echo "GUARDRAIL CANNOT RUN: unknown Codex hook '$MODE'. Correct the hooks.json target to a supported entry and retry the operation." >&2; exit 2 ;;
esac

# Older active sessions may still hold the former matcher-split UserPromptSubmit registry.
# Route every one of those stable, already-trusted entry points through the same exact prompt
# dispatcher. Its per-turn claim makes concurrent legacy handlers one direct host transition.
case "$MODE" in
  round-grant.sh|task-grant.sh|review-choice.sh|review-detached-context.sh|user-prompt-submit.sh)
    exec /bin/bash "${OH_HOME:-$ROOT}/adapters/codex/user-prompt-submit.sh"
    ;;
esac

exec /bin/bash "${OH_HOME:-$ROOT}/core/hooks/$MODE"
