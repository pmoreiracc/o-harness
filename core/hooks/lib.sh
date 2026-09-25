#!/usr/bin/env bash
# Shared helpers for the guardrail hooks. Sourced, never executed directly.
#
# Posture: guardrails FAIL CLOSED. A control that looks present and is not is worse
# than none (ADR-0020's own reasoning, applied to the tooling that guards it).
# If a hook cannot run, it blocks and says why.
#
# Compatible with bash 3.2 (the macOS default) — no associative arrays, no ${x,,}.

# frontmatter() and fm_value() live one level up: the delivery pipeline reads the same
# fields, and two parsers would be two answers to "is this doc approved?".
#
# Guarded, because sourcing a missing file is NOT fatal on its own: the hook would run on
# with fm_value undefined, the `command not found` would go to stderr, and it would exit 0
# — waving through the write it was there to block. Same fail-closed rule as jq (ADR-0027).
. "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/lib.sh is missing or unreadable." >&2
  echo "It carries the frontmatter parser every doc guardrail depends on. Failing closed." >&2
  exit 2
}

# Reads the hook payload from stdin into $PAYLOAD, and requires jq.
hook_init() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "GUARDRAIL CANNOT RUN: jq is not installed." >&2
    echo "Install it (brew install jq) and retry. The guardrail fails closed by design;" >&2
    echo "it does not wave changes through when it cannot inspect them." >&2
    exit 2
  fi
  PAYLOAD=$(cat)
  printf '%s' "$PAYLOAD" | jq -e 'type=="object"' >/dev/null 2>&1 || {
    echo 'GUARDRAIL CANNOT RUN: expected a JSON object from the host. Operation not inspected; repair the host payload/adapter and retry the operation in this run.' >&2
    exit 2
  }
}

# hook_field <jq-path> — read a field from the payload, empty string if absent.
hook_field() {
  printf '%s' "$PAYLOAD" | jq -r "$1 // \"\""
}

# One strict human-answer extractor shared by the Claude human-choice hooks.
# It accepts the two host-supported response shapes (structured answers or one rendered
# `"question"="answer"` pair) and returns a value only when there is exactly one scalar answer.
hook_single_human_answer() {
  printf '%s' "$PAYLOAD" | jq -r '
    def selected_answers:
      .tool_response as $response
      | if ($response | type) != "object" then []
        else
          ($response | has("answers")) as $has_direct
          | ($response.data? // null) as $data
          | (if ($data | type) == "object" then ($data | has("answers")) else false end) as $has_nested
          | if $has_direct and $has_nested then []
            else (if $has_direct then $response.answers
                  elif $has_nested then $data.answers
                  else null end) as $answers
            | if $answers == null then []
              elif ($answers | type) == "object" then [$answers[]]
              elif ($answers | type) == "array" then $answers
              else [$answers] end
            end
        end
      | map(
          if type != "object" then .
          elif has("answer") and has("value") then null
          elif has("answer") then .answer
          elif has("value") then .value
          else null end
        );
    def rendered_answers:
      if (.tool_response? | type) != "string" then []
      else try [(.tool_response | capture("^\\\"[^\\\"]+\\\"=\\\"(?<answer>[^\\\"]*)\\\"$").answer)] catch [] end;
    (selected_answers + rendered_answers) as $answers
    | if ($answers | length) == 1 and ($answers[0] | type) == "string"
      then $answers[0] else empty end
  ' 2>/dev/null
}

# project_root — prefer the explicit compatibility variable, then the host payload's cwd,
# then git. Codex sends `cwd`; Claude Code supplies CLAUDE_PROJECT_DIR. The scripts below
# keep one name so the existing Claude entry points do not move.
project_root() {
  local root
  root="${CLAUDE_PROJECT_DIR:-}"
  [ -n "$root" ] || root=$(hook_field '.cwd')
  [ -n "$root" ] || root=$(git rev-parse --show-toplevel 2>/dev/null)
  [ -n "$root" ] || root="$PWD"
  printf '%s' "$root"
}

# A complete single-select menu, independent of the answer it returned.
hook_menu_matches() {
  printf '%s' "$PAYLOAD" | jq -e --arg labels "$1" '
    .tool_input.questions as $q
    | ($q|type)=="array" and ($q|length)==1 and $q[0].multiSelect==false
      and ($q[0].options|type)=="array"
      and ([$q[0].options[].label] | sort)==($labels | split("\n") | sort)
  ' >/dev/null 2>&1
}

# hook_state_key <text> — filesystem-safe stable key for host-provided identifiers.
hook_state_key() {
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 | cut -c1-24
  elif command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | cut -c1-24
  else
    echo "GUARDRAIL CANNOT RUN: no shasum or sha256sum is available." >&2
    return 1
  fi
}

# repo_rel <abs-or-rel-path> — path relative to the project root, no leading ./
repo_rel() {
  local root
  root=$(project_root)
  printf '%s' "${1#"$root"/}"
}

# The ref a decision must have reached before it is immutable (ADR-0036). Same default
# verify-docs.sh uses, because one rule with two readings is what ADR-0036 exists to end.
TRUNK_REF="origin/main"

# trunk_status <repo-relative-path> — the doc's `status` as committed on the trunk.
#
# Empty output means the file is not on the trunk: a draft, whatever its frontmatter says,
# and therefore editable. Exit 1 means the trunk ref would not resolve — the caller cannot
# tell a draft from a decision and must fail closed rather than guess.
#
# Reading the trunk rather than the working copy is also what closes the two-edit hole:
# flipping a file's own `status:` to `proposed` cannot talk a guardrail out of its job.
trunk_status() {
  local root rel="$1" out
  root=$(project_root)
  git -C "$root" rev-parse --verify --quiet "$TRUNK_REF" >/dev/null 2>&1 || return 1
  git -C "$root" cat-file -e "$TRUNK_REF:$rel" 2>/dev/null || return 0
  # The result is captured before returning so that the unresolvable ref above is the only
  # thing that can produce a non-zero exit. fm_value_text stops reading at the closing
  # `---`, so on a doc bigger than the pipe buffer `git show` takes SIGPIPE and the
  # pipeline exits 141 with the right answer already on stdout — under `pipefail` that
  # would reach the caller as "the ref would not resolve" and block an editable draft.
  out=$(git -C "$root" show "$TRUNK_REF:$rel" 2>/dev/null | fm_value_text status) || true
  printf '%s' "$out"
}
