#!/usr/bin/env bash
# Claude Code reaches the shared attempt allocator after readiness and window checks.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec /bin/bash "$DIR/review-start.sh"
