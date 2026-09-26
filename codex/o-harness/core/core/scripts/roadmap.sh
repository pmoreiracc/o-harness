#!/usr/bin/env bash
# Parse the roadmap's initiative tables into machine-readable state.
#
# The roadmap is to /design what a design doc's task list is to /deliver: the registry of
# what may be worked on, and the slug is the argument. This script is the only thing that
# reads it, so nothing else has to interpret a markdown table to answer "is this a real
# initiative, and what does it wait on?"
#
# Usage:  roadmap.sh [--table | --milestones | --delivered | --slug <slug>]
# Output: one record per initiative, fields separated by ASCII Unit Separator (0x1f):
#           slug  milestone  depends  design
#         --table renders it for humans instead.
#         --milestones emits one record per milestone: id  shipped  done-when
#         --delivered emits the frozen-design pointers from collapsed shipped milestones:
#           design  milestone
#         --slug resolves one initiative, and is the gate /design opens with:
#           exit 0  it exists and has no design doc yet. stdout: its record.
#           exit 3  it already has one. Nothing to design.
#           exit 1  no such slug. THIS IS NOT A HINT TO INVENT ONE.
#
# 0x1f rather than tab, for the reason plan.sh gives: tab is IFS whitespace in bash, so
# `read` collapses runs of them and every empty field shifts the rest of the row left.
#
# FAILS CLOSED. A row inside a milestone that does not match the grammar is an error, not
# a skipped initiative: silently dropping one would let /design refuse work that is really
# there, or let a malformed slug become an identity nothing can resolve.
#
# Recognised syntax (strict):
#   ### M3 — Insights engine        a milestone; ✅ in the heading means shipped
#   | Slug | Initiative | ... |     the header row, and its |---|---| separator
#   | `slug` | text | — | — |       an initiative; depends and design are — when absent
#   | `slug` | text | `a`, `b` | [0001](./design/0001-x.md) |
#   Delivered as [0001](./design/0001-x.md).  collapsed pointers; shipped milestones only
#   **Done when:** …                the milestone's acceptance criterion
set -uo pipefail

MODE="${1:-}"
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
FILE="$ROOT/docs/roadmap.md"

if [ ! -f "$FILE" ]; then
  echo "roadmap.sh: no docs/roadmap.md under $ROOT" >&2
  exit 1
fi

TSV=$(awk -v want="${MODE}" '
BEGIN { US = sprintf("%c", 31) }
# A milestone opens a table section. Anything else at ## or ### closes it, so the
# Deliberately-deferred table below is never read as initiatives.
# The id is taken by match, not by field, so "### M2" with no title is still a milestone —
# it used to fall through to the closer below and silently swallow every row under it.
/^###[[:space:]]+M[0-9]+([[:space:]]|$)/ {
  match($0, /M[0-9]+/)
  ms = substr($0, RSTART, RLENGTH)
  order[++mcount] = ms
  shipped[ms] = ($0 ~ /✅/) ? "shipped" : ""
  next
}
/^#{2,3}[[:space:]]/ { ms = ""; next }
ms != "" && /^\*\*Done when:\*\*/ { donewhen[ms] = "done-when"; next }
ms != "" && /^Delivered as / {
  rest = $0
  while (match(rest, /\[[0-9][0-9][0-9][0-9]\]\(\.\/design\/[0-9][0-9][0-9][0-9]-[a-z0-9]+(-[a-z0-9]+)*\.md\)/)) {
    link = substr(rest, RSTART, RLENGTH)
    label = substr(link, 2, 4)
    target = link
    sub(/^.*\.\/design\//, "", target)
    target = substr(target, 1, 4)
    if (label != target) {
      printf "PARSE_ERROR%scollapsed pointer in %s names design %s but links to design %s\n", US, ms, label, target
      bad = 1
    }
    if (shipped[ms] != "shipped") {
      printf "PARSE_ERROR%scollapsed pointer for design %s appears before %s has shipped\n", US, label, ms
      bad = 1
    }
    delivered_doc[++dcount] = label
    delivered_ms[dcount] = ms
    rest = substr(rest, RSTART + RLENGTH)
  }
  if (rest ~ /\]\(\.\/design\//) {
    printf "PARSE_ERROR%sinvalid collapsed design pointer in %s: %s\n", US, ms, $0
    bad = 1
  }
  next
}
ms == "" {
  # An initiative outside every milestone belongs to no table and would vanish. That is
  # the silent drop this parser exists to refuse.
  if ($0 ~ /^\|[[:space:]]*`[a-z0-9-]+`[[:space:]]*\|/) {
    printf "PARSE_ERROR%sinitiative row outside any milestone: %s\n", US, $0
    bad = 1
  }
  next
}
/^\|/ {
  # The header and its separator carry no data.
  if ($0 ~ /^\|[[:space:]]*Slug[[:space:]]*\|/) next
  if ($0 ~ /^\|[[:space:]]*-+[[:space:]]*\|/) next
  # A shipped milestone has collapsed to pointers; keeping even an old initiative row
  # makes the registry claim both "built" and "still backlog" for the same work.
  if (shipped[ms] == "shipped") {
    printf "PARSE_ERROR%sinitiative row remains under shipped milestone %s: %s\n", US, ms, $0
    bad = 1
    next
  }
  if ($0 !~ /^\| `[a-z0-9]+(-[a-z0-9]+)*` \| /) {
    printf "PARSE_ERROR%sunrecognised row in %s: %s\n", US, ms, $0
    bad = 1
    next
  }
  n = split($0, f, "|")
  if (n != 6) {
    printf "PARSE_ERROR%srow in %s has %d cells, expected 4 (an unescaped pipe?): %s\n", US, ms, n - 2, $0
    bad = 1
    next
  }
  slug = f[2]; deps = f[4]; design = f[5]
  gsub(/[` ]/, "", slug)
  gsub(/[` ]/, "", deps)
  if (deps == "—") deps = ""
  # Cell 3 gets the same grammar as cell 1. Unvalidated it reached the verifier as an
  # unquoted word list, where a glob character would expand against the repository.
  if (deps != "") {
    dn = split(deps, dd, ",")
    for (di = 1; di <= dn; di++)
      if (dd[di] !~ /^([a-z0-9]+(-[a-z0-9]+)*|M[0-9]+)$/) {
        printf "PARSE_ERROR%s%s depends on \"%s\", which is not a slug or a milestone id\n", US, slug, dd[di]
        bad = 1
      }
  }
  # [0001](./design/0001-foundation.md) -> 0001. The label and target are one
  # identity: validating each separately would allow [0001](./design/0002-other.md),
  # making /design and link checking answer about different docs.
  gsub(/^[[:space:]]+|[[:space:]]+$/, "", design)
  if (design == "—") design = ""
  else if (design ~ /^\[[0-9][0-9][0-9][0-9]\]\(\.\/design\/[0-9][0-9][0-9][0-9]-[a-z0-9]+(-[a-z0-9]+)*\.md\)$/) {
    label = substr(design, 2, 4)
    target = design
    sub(/^.*\.\/design\//, "", target)
    target = substr(target, 1, 4)
    if (label != target) {
      printf "PARSE_ERROR%s%s names design %s but links to design %s\n", US, slug, label, target
      bad = 1
    }
    design = label
  } else {
    printf "PARSE_ERROR%s%s has an invalid design link: %s\n", US, slug, design
    bad = 1
    design = ""
  }
  if (want != "--milestones" && want != "--delivered")
    printf "%s%s%s%s%s%s%s\n", slug, US, ms, US, deps, US, design
  next
}
END {
  if (want == "--milestones")
    for (i = 1; i <= mcount; i++) {
      m = order[i]
      # A milestone printed twice would be two sections claiming one id; report both so
      # the duplicate check downstream can see it rather than inferring it.
      printf "%s%s%s%s%s\n", m, US, shipped[m], US, donewhen[m]
    }
  if (want == "--delivered")
    for (i = 1; i <= dcount; i++)
      printf "%s%s%s\n", delivered_doc[i], US, delivered_ms[i]
  if (bad) exit 9
}
' "$FILE")

US=$(printf '\037')

if printf '%s' "$TSV" | grep -q '^PARSE_ERROR'; then
  echo "roadmap.sh: cannot parse $FILE — refusing to report a partial registry." >&2
  printf '%s\n' "$TSV" | grep '^PARSE_ERROR' | cut -d"$US" -f2- | sed 's/^/  /' >&2
  exit 1
fi

if [ "$MODE" = "--delivered" ]; then
  printf '%s\n' "$TSV" | sed '/^$/d'
  exit 0
fi

if [ -z "$TSV" ] && ! grep -qE '^###[[:space:]]+M[0-9]+([[:space:]]|$)' "$FILE"; then
  echo "roadmap.sh: $FILE has no milestones. Nothing can be designed from it." >&2
  exit 1
fi

if [ "$MODE" = "--slug" ]; then
  WANT="${2:-}"
  if [ -z "$WANT" ]; then
    echo "usage: roadmap.sh --slug <slug>" >&2
    exit 1
  fi
  ROW=$(printf '%s\n' "$TSV" | awk -F"$US" -v s="$WANT" '$1==s {print; exit}')
  if [ -z "$ROW" ]; then
    echo "roadmap.sh: no initiative '$WANT' in docs/roadmap.md." >&2
    echo "The roadmap is the registry of what may be designed. A slug that is not there is" >&2
    echo "not work yet — it needs a row first, which is a conversation, not a commit." >&2
    echo "Its slugs are:" >&2
    printf '%s\n' "$TSV" | cut -d"$US" -f1 | sed 's/^/  /' >&2
    exit 1
  fi
  HAS=$(printf '%s' "$ROW" | cut -d"$US" -f4)
  if [ -n "$HAS" ]; then
    echo "STOP: '$WANT' is already covered by design doc $HAS." >&2
    echo "A design doc is written once and frozen on delivery. To change what it says," >&2
    echo "correct it during delivery; to replace it, that is a new initiative." >&2
    exit 3
  fi
  printf '%s\n' "$ROW"
  exit 0
fi

if [ "$MODE" = "--table" ]; then
  printf '%-22s %-4s %-8s %s\n' SLUG M DESIGN DEPENDS
  printf '%s\n' "$TSV" | while IFS="$US" read -r s m d g; do
    printf '%-22s %-4s %-8s %s\n' "$s" "$m" "${g:--}" "${d:--}"
  done
else
  printf '%s\n' "$TSV"
fi
