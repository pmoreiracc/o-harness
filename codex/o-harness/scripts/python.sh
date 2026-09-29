#!/bin/sh
# Runs one of OH's Python scripts: on Windows with the official Python that OH fetched into its folder when there is
# one, otherwise with a Python 3.12+ already on this computer (python3, python, py -3).
# Usage: python.sh --hook <script> <args> (the prompt hook: a missing Python stays silent, so ordinary
# prompts never fail) or python.sh --launcher <script> <args> (OH's launcher).
mode=${1:-}
shift
here=$(dirname "$0")
windows=
[ "${OS:-}" = Windows_NT ] && windows=1
home=$HOME
# On Windows OH's folder is under USERPROFILE, whatever HOME a Git Bash user set.
[ -n "$windows" ] && [ -n "${USERPROFILE:-}" ] && home=$(cygpath -u "$USERPROFILE" 2>/dev/null || printf '%s' "$USERPROFILE")
data="${OH_DATA_HOME:-$home/.local/share/o-harness}"
check='import sys; sys.exit(sys.version_info < (3, 12))'
pick() {
  # On Windows OH's own Python comes first: checking it costs one start, where python3 may be a Store placeholder.
  own="$data/python/$(cat "$data/python/current" 2>/dev/null)/python.exe"
  if [ -n "$windows" ] && [ -f "$own" ] && "$own" -I -c "$check" >/dev/null 2>&1; then interpreter=$own; return 0; fi
  for name in python3 python; do
    if command -v "$name" >/dev/null 2>&1 && "$name" -I -c "$check" >/dev/null 2>&1; then interpreter=$name; return 0; fi
  done
  if command -v py >/dev/null 2>&1 && py -3 -I -c "$check" >/dev/null 2>&1; then interpreter=py; flag=-3; return 0; fi
  return 1
}
interpreter= flag=
if ! pick; then
  [ "$mode" = --launcher ] || exit 0
  # The OH command after the script and its --root option.
  command=
  skip=
  for argument in "$@"; do
    [ -z "$command$skip" ] && [ "$argument" = "$1" ] && skip=script && continue
    if [ "$skip" = root ]; then skip=script; continue; fi
    case "$argument" in --root) skip=root ;; --root=*) ;; *) command=$argument; break ;; esac
  done
  if [ -n "$windows" ] && [ "$command" = setup ]; then
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$here/get-python.ps1" || exit 2
    pick || { echo "OH downloaded Python but can't find it in $data/python. Run setup again." >&2; exit 2; }
  else
    if [ -n "$windows" ]; then
      echo 'OH needs Python 3.12 or newer. Run this plugin'"'"'s scripts/oh setup: it downloads the official Python from python.org into OH'"'"'s folder, without admin rights or PATH changes.' >&2
    else
      echo 'OH needs Python 3.12 or newer as python3.' >&2
    fi
    exit 2
  fi
fi
utf8=
[ -n "$windows" ] && utf8='-X utf8'
# $flag and $utf8 are split into words on purpose; everything else is passed exactly.
exec "$interpreter" $flag -I $utf8 "$@"
