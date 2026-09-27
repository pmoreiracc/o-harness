#!/bin/sh
# Runs one of OH's Python scripts with a Python 3.11+ that is already on this computer:
# python3, python, py -3, or on Windows the official Python that `oh setup` fetched into OH's folder.
# Usage: python.sh --hook <script> <args> (the prompt hook: a missing Python stays silent, so ordinary
# prompts never fail) or python.sh --launcher <script> <args> (OH's launcher).
mode=${1:-}
shift
data="${OH_DATA_HOME:-$HOME/.local/share/o-harness}"
here=$(dirname "$0")
windows=
[ "${OS:-}" = Windows_NT ] && windows=1
check='import sys; sys.exit(sys.version_info < (3, 11))'
pick() {
  for name in python3 python; do
    if command -v "$name" >/dev/null 2>&1 && "$name" -c "$check" >/dev/null 2>&1; then interpreter=$name; return 0; fi
  done
  if command -v py >/dev/null 2>&1 && py -3 -c "$check" >/dev/null 2>&1; then interpreter=py; flag=-3; return 0; fi
  if [ -n "$windows" ] && "$data/python/python.exe" -c "$check" >/dev/null 2>&1; then interpreter="$data/python/python.exe"; return 0; fi
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
    pick || exit 2
  else
    if [ -n "$windows" ]; then
      echo 'OH needs Python 3.11 or newer. Run this plugin'"'"'s scripts/oh setup: it downloads the official Python from python.org into OH'"'"'s folder, without admin rights or PATH changes.' >&2
    else
      echo 'OH needs Python 3.11 or newer as python3.' >&2
    fi
    exit 2
  fi
fi
utf8=
[ -n "$windows" ] && utf8='-X utf8'
# $flag and $utf8 are split into words on purpose; everything else is passed exactly.
exec "$interpreter" $flag -I $utf8 "$@"
