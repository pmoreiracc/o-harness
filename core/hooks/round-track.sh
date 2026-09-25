#!/usr/bin/env bash
# GUARDRAIL support — records every identity a spawned invariant-reviewer is addressable by.
#
# Fires on Claude Code's PostToolUse for the Agent tool. A round is not only obtained by
# spawning invariant-reviewer: SendMessage can resume an already-spawned reviewer for a
# further round without spawning anything, and PreToolUse on Agent — round-refuse.sh's other
# route — never sees that. This hook writes the markers round-refuse.sh reads to close it: a
# SendMessage addressed to an identity recorded here is refused and told to spawn a fresh
# reviewer in the same session.
#
# An anonymous background spawn returns tool_response.agentId; a named one (Agent's `name`
# parameter, which the host's own tool docs recommend for SendMessage addressing) returns
# tool_response.teammate_id instead and is then addressable by the name the caller chose
# (tool_input.name) as well as the id. All three identities are recorded when present, each
# as its own marker — recording only one shape is exactly the gap a round-1 review found: a
# named spawn's SendMessage traffic was invisible to a hook that only read .agentId.
#
# Best-effort by construction: the spawn has already happened by PostToolUse, so this hook
# never blocks anything. An identity this hook fails to record is one round-refuse.sh cannot
# recognise in a SendMessage — the same fail-open exposure as any `invariant-reviewer` agent
# outside this repository's own coverage, not a regression this hook can introduce, since
# nothing enforced this before it existed. Deleting an already-written marker would have the
# same effect. This tracking is best-effort local evidence; the host hook is its supported writer.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/lib.sh" || {
  echo "GUARDRAIL CANNOT RUN: core/hooks/lib.sh is missing or unreadable." >&2
  exit 2
}
hook_init

[ "$(hook_field '.hook_event_name')" = "PostToolUse" ] || exit 0
[ "$(hook_field '.tool_name')" = "Agent" ] || exit 0
[ "$(hook_field '.tool_input.subagent_type')" = "invariant-reviewer" ] || exit 0

ROOT=$(project_root)
DIR_OUT="${OH_STATE_ROOT:-$ROOT/.deliver}/reviewer-agents"
mkdir -p "$DIR_OUT" || {
  echo "round-track: could not create $DIR_OUT; the SendMessage gate will not recognise" >&2
  echo "this reviewer." >&2
  exit 0
}

# Filenames need not derive from the identity: round-refuse.sh matches on file CONTENT, so a
# throwaway unique filename avoids depending on hook_state_key (and its own failure mode)
# just to pick a name. Best-effort by construction (see header) — each failure below is
# reported so a silent gap in coverage is at least a visible one, not a behaviour change.
record_id() {
  local id="$1" f
  [ -n "$id" ] || return 0
  f=$(mktemp "$DIR_OUT/agent.XXXXXX" 2>/dev/null) || {
    echo "round-track: could not create a marker file; the SendMessage gate will not" >&2
    echo "recognise this reviewer." >&2
    return 0
  }
  printf '%s\n' "$id" > "$f" || {
    echo "round-track: could not write the marker at $f; the SendMessage gate will not" >&2
    echo "recognise this reviewer." >&2
    return 0
  }
}

record_id "$(hook_field '.tool_response.agentId')"
record_id "$(hook_field '.tool_response.teammate_id')"
record_id "$(hook_field '.tool_input.name')"
exit 0
