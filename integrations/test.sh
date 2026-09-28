#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# The oh entry runs Python in UTF-8 mode on Windows; tests that import OH directly need it too.
[ "${OS:-}" != Windows_NT ] || export PYTHONUTF8=1
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_NAMESPACE GIT_PREFIX OH_HOME OH_PROJECT_ROOT OH_POLICY_FILE OH_STATE_ROOT XDG_CONFIG_HOME
case "${1:-native}" in
  # Every run lists its slowest tests, so a slow new one is seen in the PR that adds it.
  native) PYTHONPATH=runtime python3 -m unittest discover -s runtime -p 'test_*.py' --durations 15 ;;
  # The tests a PR must pass on Windows (see integrations/select_tests.py); the full suite runs nightly.
  windows)
    tests=$(python3 integrations/select_tests.py "${2:-origin/main}")
    echo "Running $(wc -l <<<"$tests" | tr -d ' ') selected tests"
    # shellcheck disable=SC2086
    PYTHONPATH=runtime python3 -m unittest --durations 15 $tests
    ;;
  syntax)
    python3 integrations/windows_risk.py "${2:-origin/main}"
    python3 -m compileall -q runtime
    node --check dashboard/app.js
    while IFS= read -r file; do bash -n "$file"; done < <(git ls-files --cached --others --exclude-standard '*.sh')
    ;;
  *) echo 'Unknown verification suite' >&2;exit 2 ;;
esac
