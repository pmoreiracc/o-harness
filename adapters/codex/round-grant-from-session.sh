#!/usr/bin/env bash
# Compatibility entry point; all window choices use the shared verified Desktop route.
export DESKTOP_REVIEW_ADAPTER=adapters/codex/round-grant-from-session.sh
exec /bin/bash "$(dirname "${BASH_SOURCE[0]}")/review-choice-from-session.sh" "$@"
