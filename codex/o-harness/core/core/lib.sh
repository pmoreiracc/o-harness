#!/usr/bin/env bash
# Helpers shared by the guardrail hooks and the delivery pipeline. Sourced, never executed.
#
# Frontmatter is the machine-readable state of every doc in this repository — a doc's type,
# its status, whether a design doc has been approved. Both halves of the tooling read it, so
# it is parsed by one grammar with two entry points: from a file, and from stdin (a git blob
# or a tool payload). A second reader that disagreed about what `approved` looks like would
# be a second answer to whether work may start.
#
# No jq, deliberately: the pipeline scripts run in CI stages that have no reason to install
# it, and these functions need nothing but awk.
#
# Compatible with bash 3.2 (the macOS default) — no associative arrays, no ${x,,}.

# delivery_branch_parse <branch> — echo "<doc>\t<track>" for a canonical delivery
# branch. The track is empty for a single-track design. One grammar is shared by the
# review-round and task-window ledgers.
delivery_branch_parse() {
  local branch="$1" rest doc track
  case "$branch" in deliver/*) rest="${branch#deliver/}" ;; *) return 1 ;; esac
  case "$rest" in
    [0-9][0-9][0-9][0-9]) doc="$rest"; track="" ;;
    [0-9][0-9][0-9][0-9]-) return 1 ;;
    [0-9][0-9][0-9][0-9]-*) doc="${rest%%-*}"; track="${rest#????-}" ;;
    *) return 1 ;;
  esac
  printf '%s\t%s' "$doc" "$track"
}

# frontmatter_text — the YAML block between the first two --- lines, read from stdin.
frontmatter_text() {
  awk 'NR==1 && $0!="---" {exit} NR==1 {next} /^---[[:space:]]*$/ {exit} {print}'
}

# fm_value_text <key> — value of a frontmatter key, trimmed, read from stdin.
fm_value_text() {
  frontmatter_text | awk -v k="$1" '
    $0 ~ "^"k":" {
      sub("^"k":[[:space:]]*", "")
      sub("[[:space:]]*$", "")
      print
      exit
    }'
}

# frontmatter <file> — as above, from a file. Empty if the file does not exist.
frontmatter() {
  [ -f "$1" ] || return 0
  frontmatter_text < "$1"
}

# fm_value <file> <key> — as above, from a file. Empty if absent.
fm_value() {
  [ -f "$1" ] || return 0
  fm_value_text "$2" < "$1"
}
