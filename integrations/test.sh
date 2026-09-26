#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_NAMESPACE GIT_PREFIX OH_HOME OH_PROJECT_ROOT OH_POLICY_FILE OH_STATE_ROOT
case "${1:-native}" in
  native) PYTHONPATH=runtime python3 -m unittest discover -s runtime -p 'test_*.py' ;;
  syntax)
    python3 -m compileall -q runtime
    node --check dashboard/app.js
    while IFS= read -r file; do bash -n "$file"; done < <(git ls-files --cached --others --exclude-standard '*.sh')
    ;;
  *) echo 'Unknown verification suite' >&2;exit 2 ;;
esac
