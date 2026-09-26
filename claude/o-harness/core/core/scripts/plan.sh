#!/usr/bin/env bash
# Parse a design doc's task list into machine-readable state.
#
# The task list in docs/design/ IS the state machine for delivery. This script is the
# only thing that reads it, so the agent never interprets prose to decide what to do next
# — it asks, and gets an exit code.
#
# Usage:  plan.sh <design-doc-number> [--table]
# Output: one record per task, fields separated by ASCII Unit Separator (0x1f):
#           n  status  owner  needs  blocked  title
#         --table renders it for humans instead.
#
# Not tab-separated, deliberately: tab is IFS *whitespace* in bash, so `read` collapses
# runs of them and every empty field silently shifts the rest of the row left. A task
# with no dependencies would come back looking like it depended on its own title. 0x1f
# is not whitespace and cannot occur in a markdown document.
#
# FAILS CLOSED. An unparseable task line — or a dependency written in prose the parser
# cannot read — is an error, never a skipped task: silently dropping either would let
# delivery march past work nobody noticed was missing.
#
# Recognised syntax (strict):
#   ### <Name> track           section heading — sets the owner for the tasks beneath it
#   - [ ] **7.** <title>       a pending task
#   - [x] **7.** <title>       a completed task
#   *Depends on task 2.*       dependency, anywhere in the task's block
#   *Depends on tasks 2, 9.*   several
#   *Blocked on §5.*           blocked on an open question — never runnable until resolved
set -uo pipefail

DOC_NUM="${1:-}"
MODE="${2:-}"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

if [ -z "$DOC_NUM" ]; then
  echo "usage: plan.sh <design-doc-number> [--table]" >&2
  exit 1
fi

FILE=$(ls "$ROOT"/docs/design/"$DOC_NUM"-*.md 2>/dev/null | head -1)
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "plan.sh: no design doc matching docs/design/$DOC_NUM-*.md" >&2
  exit 1
fi

TSV=$(awk '
function flush() {
  if (cur == "") return
  needs = ""; blocked = ""
  # *Depends on task 2.*  /  *Depends on tasks 2, 9.*
  if (match(block, /Depends on tasks?[^.*]*/)) {
    dep = substr(block, RSTART, RLENGTH)
    while (match(dep, /[0-9]+/)) {
      needs = needs (needs == "" ? "" : ",") substr(dep, RSTART, RLENGTH)
      dep = substr(dep, RSTART + RLENGTH)
    }
  }
  # A dependency the parser cannot read is a dependency that does not exist. "Depends on
  # everything above." matches nothing above and would silently report no dependencies at
  # all, which is the failure this script was written to prevent — one level down from the
  # task line itself.
  if (needs == "" && (dp = index(block, "Depends on")) > 0) {
    frag = substr(block, dp)
    if (match(frag, /[.*]/)) frag = substr(frag, 1, RSTART - 1)
    printf "PARSE_ERROR%stask %s says \"%s\" — expected \"Depends on task N\" or \"Depends on tasks N, M\"\n", US, cur, frag
    bad = 1
    cur = ""
    return
  }
  # *Blocked on §5.*  — index/substr rather than a match offset, so a multi-byte
  # character in the reference cannot shift the slice.
  p = index(block, "Blocked on ")
  if (p > 0) {
    b = substr(block, p + 11)
    if (match(b, /[.*]/)) b = substr(b, 1, RSTART - 1)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", b)
    blocked = b
  }
  printf "%s%s%s%s%s%s%s%s%s%s%s\n", cur, US, status, US, owner, US, needs, US, blocked, US, title
  cur = ""
}
BEGIN { US = sprintf("%c", 31) }
# Blank-line tracking, and it must come first: every rule below that calls next would
# otherwise leave the flag stale.
{ was_blank = prev_blank; prev_blank = ($0 ~ /^[[:space:]]*$/) }
/^###[[:space:]]+.*[Tt]rack[[:space:]]*$/ {
  flush()
  o = $2; owner = tolower(o)
  next
}
/^##[^#]/ { flush(); owner = ""; next }
/^-[[:space:]]*\[/ {
  flush()
  if ($0 !~ /^- \[[ x]\] \*\*[0-9]+\.\*\* /) {
    printf "PARSE_ERROR%sunrecognised task line: %s\n", US, $0
    bad = 1
    next
  }
  if (owner == "") {
    printf "PARSE_ERROR%stask outside any \"### <name> track\" section: %s\n", US, $0
    bad = 1
    next
  }
  status = (substr($0, 4, 1) == "x") ? "done" : "pending"
  rest = substr($0, 7)          # "- [ ] " is six characters; the marker starts at 7
  match(rest, /^\*\*[0-9]+\./)
  cur = substr(rest, 3, RLENGTH - 3)
  title = substr(rest, RLENGTH + 3)
  gsub(/[`*]/, "", title)
  gsub(/[[:space:]]+/, " ", title)
  gsub(/^ | $/, "", title)
  if (length(title) > 70) title = substr(title, 1, 67) "..."
  block = $0
  next
}
# Where the block for a task ends. Without this, block absorbs everything after the list, so
# prose following the last task is attributed to it — and prose that happens to say
# "Depends on" fails the whole doc, pointing at a task whose line does not contain it.
#
# The discriminator is a blank line, not column zero. Markdown continues a list item
# through an unindented line ("lazy continuation"), so
#
#     - [ ] **2.** The CI workflow.
#     *Depends on task 1.*
#
# is one task carrying its dependency, and flushing on column zero alone would drop it
# silently — the failure this whole check exists to prevent. Indented lines are always
# continuations, blank or not, so a loose list item keeps its marker too.
/^[^[:space:]]/ {
  if (was_blank) {
    flush()
    # A dependency stranded on the far side of the blank line belongs to no task. It is
    # readable, so the check above never sees it, and dropping it here would be the same
    # silent loss in a different costume.
    if ($0 ~ /Depends on tasks?[[:space:]]+[0-9]/) {
      printf "PARSE_ERROR%sorphan dependency: %s\n", US, $0
      printf "PARSE_ERROR%s  a blank line separates it from any task. Put it on the task line, or indent it.\n", US
      bad = 1
    }
    next
  }
}
{ if (cur != "") block = block " " $0 }
END { flush(); if (bad) exit 9 }
' "$FILE")

US=$(printf '\037')

if printf '%s' "$TSV" | grep -q '^PARSE_ERROR'; then
  echo "plan.sh: cannot parse $FILE — refusing to report a partial task list." >&2
  printf '%s\n' "$TSV" | grep '^PARSE_ERROR' | cut -d"$US" -f2- | sed 's/^/  /' >&2
  exit 1
fi

if [ -z "$TSV" ]; then
  echo "plan.sh: $FILE has no task list. A design doc without tasks cannot be delivered." >&2
  exit 1
fi

DUPES=$(printf '%s\n' "$TSV" | cut -d"$US" -f1 | sort | uniq -d)
if [ -n "$DUPES" ]; then
  echo "plan.sh: duplicate task numbers in $FILE: $(printf '%s' "$DUPES" | tr '\n' ' ')" >&2
  exit 1
fi

if [ "$MODE" = "--table" ]; then
  printf '%-4s %-8s %-7s %-7s %-9s %s\n' N STATUS OWNER NEEDS BLOCKED TITLE
  printf '%s\n' "$TSV" | while IFS="$US" read -r n st ow ne bl ti; do
    printf '%-4s %-8s %-7s %-7s %-9s %s\n' "$n" "$st" "$ow" "${ne:--}" "${bl:--}" "$ti"
  done
else
  printf '%s\n' "$TSV"
fi
