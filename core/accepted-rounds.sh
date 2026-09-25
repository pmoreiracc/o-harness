#!/usr/bin/env bash
# Strict reader for atomically published, append-only accepted review rounds (ADR-0047).

ACCEPTED_ROUNDS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$ACCEPTED_ROUNDS_DIR/review-receipt.sh" || return 1 2>/dev/null || exit 1

accepted_header() { review_header "$1" "$2"; }

accepted_rounds_root() {
  printf '%s/accepted/%s' "${OH_STATE_ROOT:-$1/.deliver/reviews}" "$2"
}

accepted_key_valid() {
  [ -n "$1" ] || return 1
  case "$1" in /*) return 1 ;; esac
  ! printf '%s\n' "$1" | grep -Eq '(^|/)\.\.?(/|$)'
}

accepted_snapshot_validate() {
  local file="$1" tree="$2" head="$3" version
  [ -f "$file" ] && [ ! -L "$file" ] && [ -r "$file" ] || return 1
  version=$(sed -n '1s/^snapshot-version: //p' "$file" 2>/dev/null) || return 1
  case "$version" in
    1) accepted_snapshot_validate_v1 "$file" "$tree" "$head" ;;
    2) accepted_snapshot_validate_v2 "$file" "$tree" "$head" ;;
    *) return 1 ;;
  esac
}

# Historical v1 rounds remain countable, but the writer no longer emits this raw format.
# Parse only its fixed prefix and first structural boundary so content-looking lines cannot
# poison old evidence merely by repeating a header or sentinel.
accepted_snapshot_validate_v1() {
  local file="$1" tree="$2" head="$3" l1 l2 l3 l4 l5 at
  {
    IFS= read -r l1 && IFS= read -r l2 && IFS= read -r l3 \
      && IFS= read -r l4 && IFS= read -r l5
  } < "$file" || return 1
  at="${l4#at: }"
  [ "$l1" = 'snapshot-version: 1' ] \
    && [ "$l2" = "tree: $tree" ] \
    && [ "$l3" = "head: $head" ] \
    && [ "$l4" = "at: $at" ] \
    && printf '%s\n' "$at" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' \
    && [ "$l5" = '--- tracked diff (binary-safe patch) ---' ] \
    && awk 'NR > 5 && $0 == "--- untracked inputs ---" { found=1; exit } END { exit !found }' "$file"
}

# v2 encodes every repository-controlled byte as lowercase hex. The fixed seven-line prefix
# plus an exact entry count makes the framing injective for binary files and missing newlines;
# content can never be reinterpreted as a snapshot header or section delimiter.
accepted_snapshot_validate_v2() {
  local file="$1" tree="$2" head="$3" l1 l2 l3 l4 l5 l6 l7 at count lines
  {
    IFS= read -r l1 && IFS= read -r l2 && IFS= read -r l3 \
      && IFS= read -r l4 && IFS= read -r l5 && IFS= read -r l6 \
      && IFS= read -r l7
  } < "$file" || return 1
  at="${l4#at: }"; count="${l7#untracked-count: }"
  [ "$l1" = 'snapshot-version: 2' ] \
    && [ "$l2" = "tree: $tree" ] \
    && [ "$l3" = "head: $head" ] \
    && [ "$l4" = "at: $at" ] \
    && printf '%s\n' "$at" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' \
    && [ "$l5" = '---' ] \
    && printf '%s\n' "$l6" | grep -Eq '^tracked-diff-hex: ([0-9a-f]{2})*$' \
    || return 1
  case "$count" in ''|*[!0-9]*) return 1 ;; esac
  [ "$l7" = "untracked-count: $count" ] || return 1
  lines=$(wc -l < "$file" 2>/dev/null | tr -d '[:space:]') || return 1
  [ "$lines" = "$((7 + count))" ] || return 1
  tail -n +8 "$file" | awk -F '\t' '
    function evenhex(s) { return s == "-" || (s ~ /^([0-9a-f][0-9a-f])+$/) }
    {
      if (NF != 6 || $1 !~ /^untracked: ([0-9a-f][0-9a-f])+$/) exit 1
      if ($2 !~ /^[0-9a-f]{40}([0-9a-f]{24})?$/) exit 1
      if ($5 !~ /^[0-9a-f]{40}([0-9a-f]{24})?$/ || !evenhex($6)) exit 1
      if ($3 == "regular") { if ($4 != "100644" && $4 != "100755") exit 1 }
      else if ($3 == "symlink") { if ($4 != "120000") exit 1 }
      else if ($3 == "gitlink") { if ($4 != "160000" || $6 != "-") exit 1 }
      else exit 1
    }
  '
}

# accepted_round_validate <root> <key> <round-dir> <expected-prior>
accepted_round_validate() {
  local root="$1" key="$2" entry="$3" expected="$4" name tree started nonce
  local review snapshot marker request head request_ref request_sha snapshot_sha file
  local at elapsed branch delivery=0
  accepted_key_valid "$key" || return 1
  [ -d "$entry" ] && [ ! -L "$entry" ] && [ -r "$entry" ] && [ -x "$entry" ] || return 1
  name="${entry##*/}"
  printf '%s\n' "$name" | grep -Eq '^[0-9a-f]{16}-[0-9]+-[0-9a-f]{16}$' || return 1
  tree="${name%%-*}"; started="${name#*-}"; started="${started%%-*}"; nonce="${name##*-}"
  case "$started" in ''|*[!0-9]*) return 1 ;; esac
  [ "${#nonce}" = 16 ] || return 1
  review="$entry/review.md"; snapshot="$entry/snapshot.txt"; marker="$entry/accepted"
  for file in "$review" "$snapshot" "$marker"; do
    [ -f "$file" ] && [ ! -L "$file" ] && [ -r "$file" ] || return 1
  done
  [ ! -s "$marker" ] || return 1
  for file in "$entry"/*; do
    [ -e "$file" ] || [ -L "$file" ] || continue
    case "${file##*/}" in accepted|review.md|snapshot.txt|request.md) ;; *) return 1 ;; esac
  done
  [ "$(accepted_header "$review" receipt-version)" = 3 ] \
    && [ "$(accepted_header "$review" agent)" = invariant-reviewer ] \
    && [ "$(accepted_header "$review" tree)" = "$tree" ] \
    && [ "$(accepted_header "$review" round-key)" = "$key" ] \
    && [ "$(accepted_header "$review" round-id)" = "$name" ] \
    && [ "$(accepted_header "$review" prior-rounds)" = "$expected" ] || return 1
  at=$(accepted_header "$review" at) || return 1
  printf '%s\n' "$at" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' || return 1
  elapsed=$(accepted_header "$review" elapsed-seconds) || return 1
  case "$elapsed" in ''|*[!0-9]*) return 1 ;; esac
  branch=$(accepted_header "$review" branch) || return 1
  [ "$branch" = HEAD ] || git check-ref-format --branch "$branch" >/dev/null 2>&1 || return 1
  head=$(accepted_header "$review" head) || return 1
  printf '%s\n' "$head" | grep -Eq '^[0-9a-f]{40,64}$' || return 1
  snapshot_sha=$(accepted_header "$review" snapshot-sha256) || return 1
  accepted_snapshot_validate "$snapshot" "$tree" "$head" \
    && [ "$(review_sha256_file "$snapshot")" = "$snapshot_sha" ] || return 1
  request_ref=$(accepted_header "$review" request) || return 1
  request_sha=$(accepted_header "$review" request-sha256) || return 1
  case "$key" in
    [0-9][0-9][0-9][0-9]-t[0-9]*|[0-9][0-9][0-9][0-9]-finalize)
      delivery=1
      request="$entry/request.md"
      [ "$request_ref" = request.md ] && [ -f "$request" ] && [ ! -L "$request" ] \
        && [ "$(review_sha256_file "$request")" = "$request_sha" ] || return 1
      ;;
    *) [ "$request_ref" = - ] && [ "$request_sha" = - ] && [ ! -e "$entry/request.md" ] || return 1 ;;
  esac
  review_output_check "$review" >/dev/null || return 1
  if [ "$delivery" -eq 1 ]; then
    if [ "$expected" -eq 0 ]; then review_series_output_check "$review" 0 >/dev/null
    else review_series_output_check "$review" 1 >/dev/null
    fi
  fi
}

# Print round ids in canonical series order. Any malformed entry corrupts only this key.
accepted_rounds_list() {
  local root="$1" key="$2" base entry review prior name records="" tab sorted expected=0
  local round_branch series_branch=""
  accepted_key_valid "$key" || return 1
  base=$(accepted_rounds_root "$root" "$key")
  [ -e "$base" ] || [ -L "$base" ] || return 0
  [ -d "$base" ] && [ ! -L "$base" ] && [ -r "$base" ] && [ -x "$base" ] || return 1
  tab=$(printf '\t')
  for entry in "$base"/*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    [ -d "$entry" ] && [ ! -L "$entry" ] || return 1
    review="$entry/review.md"
    prior=$(accepted_header "$review" prior-rounds 2>/dev/null) || return 1
    case "$prior" in ''|*[!0-9]*) return 1 ;; esac
    name="${entry##*/}"
    records="${records}${prior}${tab}${name}
"
  done
  [ -n "$records" ] || return 0
  sorted=$(printf '%s' "$records" | LC_ALL=C sort -n -k1,1 -k2,2) || return 1
  while IFS="$tab" read -r prior name; do
    [ "$prior" = "$expected" ] || return 1
    accepted_round_validate "$root" "$key" "$base/$name" "$expected" || return 1
    round_branch=$(accepted_header "$base/$name/review.md" branch) || return 1
    if [ "$expected" -eq 0 ]; then
      series_branch="$round_branch"
    else
      [ "$round_branch" = "$series_branch" ] || return 1
    fi
    printf '%s\n' "$name"
    expected=$((expected + 1))
  done <<EOF
$sorted
EOF
}

accepted_round_latest_for_tree() {
  local root="$1" key="$2" tree="$3" rounds round latest=""
  rounds=$(accepted_rounds_list "$root" "$key") || return 1
  while IFS= read -r round; do
    [ -n "$round" ] || continue
    [ "${round%%-*}" = "$tree" ] && latest="$round"
  done <<EOF
$rounds
EOF
  [ -n "$latest" ] || return 1
  printf '%s/%s' "$(accepted_rounds_root "$root" "$key")" "$latest"
}
