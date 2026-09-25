#!/usr/bin/env bash
# Tests for the delivery pipeline. Run: core/scripts/test.sh
#
# These scripts decide what gets built and when. Untested, they are prose with a shebang.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1
. "$PWD/core/test-fixture.sh" || exit 1
REAL_ROOT="$PWD"
S="$REAL_ROOT/core/scripts"
pass=0; fail=0
TASK_PROMPT_SEQUENCE=0

# Separate fixture submissions represent separate host turns; replay tests reuse a source
# deliberately in the owning host suite.
codex_task_prompt() {
  TASK_PROMPT_SEQUENCE=$((TASK_PROMPT_SEQUENCE + 1))
  jq -cn --arg prompt "$2" --arg turn "$TASK_PROMPT_SEQUENCE" \
    '{hook_event_name:"UserPromptSubmit",session_id:"pipeline-tests",turn_id:$turn,prompt:$prompt}' \
    | CLAUDE_PROJECT_DIR="$1" /bin/bash "$REAL_ROOT/adapters/codex/task-grant.sh" >/dev/null 2>&1
}

ok()   { pass=$((pass+1)); printf '  ok    %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  FAIL  %s — %s\n' "$1" "$2"; }

# run <want-exit> <label> <script> [args...]
run() {
  local want="$1" label="$2"; shift 2
  OUT=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/$1" "${@:2}" 2>&1); local got=$?
  if [ "$got" = "$want" ]; then ok "$label"; else bad "$label" "want exit $want, got $got"; fi
}
# saw <label> <substring> — assert against the last run's output
saw() {
  case "$OUT" in *"$2"*) ok "$1" ;; *) bad "$1" "output lacked '$2'" ;; esac
}
# notsaw <label> <substring> — a green line for a check that did not run, or a diagnosis
# that names the wrong cause, is worse than silence. Some things must NOT be said.
notsaw() {
  case "$OUT" in *"$2"*) bad "$1" "output contained '$2'" ;; *) ok "$1" ;; esac
}

MINT_SEQUENCE=0
mint_at() {   # publish a complete accepted-round fixture for the tree as it stands
  local root="$1" key="${2:-}" verdict="${3:-clean}" d branch head base prior round dir
  local snapshot_sha request_sha relation
  d=$(CLAUDE_PROJECT_DIR="$root" "$S/tree-digest.sh") || return 1
  branch=$(git -C "$root" rev-parse --abbrev-ref HEAD) || return 1
  head=$(git -C "$root" rev-parse HEAD) || return 1
  if [ -z "$key" ]; then
    case "$branch" in
      deliver/*)
        key=$(. "$REAL_ROOT/core/round-ledger.sh"; round_key_for "$root" "$branch") || return 1 ;;
      *) key="nd/$branch/$head" ;;
    esac
  fi
  case "$verdict" in clean|findings) ;; *) return 1 ;; esac
  base="$root/.deliver/reviews/accepted/$key"
  mkdir -p "$base" || return 1
  prior=$(find "$base" -mindepth 1 -maxdepth 1 -type d ! -name '.*' 2>/dev/null | wc -l | tr -d '[:space:]')
  MINT_SEQUENCE=$((MINT_SEQUENCE + 1))
  round="$d-$MINT_SEQUENCE-$(printf '%016x' "$MINT_SEQUENCE")"
  dir="$base/$round"
  mkdir "$dir" || return 1
  printf 'snapshot-version: 2\ntree: %s\nhead: %s\nat: 2026-08-12T00:00:00Z\n---\ntracked-diff-hex: 666978747572650a\nuntracked-count: 0\n' \
    "$d" "$head" > "$dir/snapshot.txt" || return 1
  snapshot_sha=$(shasum -a 256 "$dir/snapshot.txt" | awk '{print $1}')
  case "$key" in
    [0-9][0-9][0-9][0-9]-*)
      printf 'fixture request\n' > "$dir/request.md"
      request_sha=$(shasum -a 256 "$dir/request.md" | awk '{print $1}') ;;
    *) request_sha=- ;;
  esac
  {
    printf 'receipt-version: 3\nagent: invariant-reviewer\ntree: %s\nhead: %s\nat: 2026-08-12T00:00:00Z\nelapsed-seconds: 1\nbranch: %s\nround-key: %s\nround-id: %s\nprior-rounds: %s\n' \
      "$d" "$head" "$branch" "$key" "$round" "$prior"
    case "$key" in [0-9][0-9][0-9][0-9]-*) printf 'request: request.md\nrequest-sha256: %s\n' "$request_sha" ;; *) printf 'request: -\nrequest-sha256: -\n' ;; esac
    printf 'snapshot-sha256: %s\n---\n' "$snapshot_sha"
    if [ "$verdict" = findings ]; then
      printf '[CONCERN] fixture finding\n  Anchor: fixture contract\n  Where: synthetic subject\n  Why: the test needs an unclean accepted round\n  Resolve: replace it with a clean round\n\n'
      [ "$prior" -eq 0 ] && relation=original || relation=repeat-family
      printf '## Review series metadata\n- Finding 1 | Family: fixture-finding | Relation: %s\n\n' "$relation"
    else
      printf '## Review series metadata\n- none — clean review\n\n'
    fi
    printf '## Evidence\n\n### Anchors read\n- canonical reviewer contract.\n\n### Scope examined\n- Lens: task-and-design — fixture task and lifecycle were checked.\n- Lens: invariants-and-decisions — relevant harness decisions were checked.\n- Lens: affected-surfaces-and-negative-space — fixture consumers were traced.\n- Lens: correctness-and-failure-paths — invalid state was considered.\n- Lens: security-authorization-and-concurrency — exact-key behavior was checked.\n- Lens: tests-claims-docs-and-generated-artifacts — fixture claims were compared.\n- Lens: prior-findings-and-family-closure — no prior finding exists.\n\n### Adversarial attacks\n- Attack: bypass hooks. Outcome: blocked.\n- Attack: mutate accepted evidence. Outcome: blocked.\n\n### Limits\n- no runtime code exists.\n\n'
    if [ "$verdict" = findings ]; then
      printf 'VERDICT: findings — 0 blocking, 1 concern, 0 scope\n'
    else
      printf 'VERDICT: clean — no findings.\n'
    fi
  } > "$dir/review.md" || return 1
  : > "$dir/accepted"
}

SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT
mkdir -p "$SANDBOX/docs/design"

doc() { cat > "$SANDBOX/docs/design/$1"; }

doc 0900-good.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-06
---
# 0900 — Good
## 7. Tasks
### Infra track
- [x] **1.** Bring up the database.
- [ ] **2.** Roles and grants.
### Code track
- [ ] **3.** Scaffold the workspace.
- [ ] **4.** The guard test. *Depends on task 2.*
- [ ] **5.** Queue wiring. *Blocked on §5.*
- [ ] **6.** Two deps. *Depends on tasks 2, 3.*
EOF

echo "plan.sh"
run 0 "parses a well-formed task list" plan.sh 0900
saw "reads a ticked box as done"        "$(printf '1\037done\037infra')"
saw "reads the owner from the section"  "$(printf '3\037pending\037code')"
saw "reads a single dependency"         "$(printf '4\037pending\037code\0372')"
saw "reads a blocked marker"            "$(printf '5\037pending\037code\037\037§5')"
saw "reads a multiple dependency"       "$(printf '6\037pending\037code\0372,3')"
run 1 "rejects an unknown design doc"   plan.sh 0999

doc 0901-badline.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-06
---
## 7. Tasks
### Code track
- [ ] 1. Missing the bold marker.
EOF
run 1 "fails closed on an unparseable task line" plan.sh 0901

doc 0909-vaguedep.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] **1.** The workspace.
- [ ] **2.** The CI workflow. *Depends on everything above.*
EOF
run 1 "fails closed on a dependency it cannot read" plan.sh 0909

# Where a task block ends: a blank line, not column zero. One fixture per way of getting
# it wrong — 0910 fails with no rule at all, 0911 fails if the rule flushes on column zero,
# 0912 fails if it flushes on the blank line itself. None may carry an intervening "## …"
# heading, which would flush on its own and make the case vacuous.

# Prose after the list belongs to no task, so "Depends on" down there is not a dependency
# and must not fail the doc on the last task's behalf.
doc 0910-trailing.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] **1.** The workspace.
- [ ] **2.** The CI workflow.

Delivery Depends on the hosting decision landing first.
EOF
run 0 "prose after the task list is not the last task's dependency" plan.sh 0910
saw "and the task keeps an empty needs field" "$(printf '2\037pending\037code\037\037\037')"

# Markdown lazy continuation: an unindented line straight after the task is still part of
# it. Flushing on column zero alone would drop this dependency silently.
doc 0911-lazy.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] **1.** The workspace.
- [ ] **2.** The CI workflow.
*Depends on task 1.*
EOF
run 0 "an unindented continuation still carries its dependency" plan.sh 0911
saw "and the dependency is read"                "$(printf '2\037pending\037code\0371')"

doc 0912-loose.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] **1.** The workspace.
- [ ] **2.** A loose list item.

      *Depends on task 1.*
EOF
run 0 "a blank line before an indented marker does not sever it" plan.sh 0912
saw "the dependency survives the blank line" "$(printf '2\037pending\037code\0371')"

# Readable, and attached to nothing. Dropping it would be the round-2 silent loss wearing
# a different hat, so it is an error rather than prose.
doc 0914-orphan.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] **1.** The workspace.
- [ ] **2.** The CI workflow.

*Depends on task 1.*
EOF
run 1 "fails closed on a dependency stranded past a blank line" plan.sh 0914

doc 0902-noowner.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-06
---
## 7. Tasks
- [ ] **1.** Outside any track section.
EOF
run 1 "fails closed on a task with no track section" plan.sh 0902

doc 0903-dupe.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-06
---
## 7. Tasks
### Code track
- [ ] **1.** One.
- [ ] **1.** Also one.
EOF
run 1 "rejects duplicate task numbers" plan.sh 0903

doc 0904-empty.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-06
---
# Nothing to do here.
EOF
run 1 "rejects a design doc with no tasks" plan.sh 0904

# Specification: docs/design/README.md, "The rule: frozen on delivery".
echo "next.sh"
run 1 "refuses to guess when the doc has two tracks"  next.sh 0900

doc 0908-single.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] **1.** The only kind of work this doc has.
EOF
run 0 "infers the track when the doc has only one"    next.sh 0908
run 0 "returns the lowest runnable task for the owner" next.sh 0900 code
saw "and it is task 3"                     "3"
run 0 "respects a non-default owner"       next.sh 0900 infra
saw "infra's next is task 2"               "2"

doc 0905-blockedonly.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-06
---
## 7. Tasks
### Code track
- [ ] **1.** Queue wiring. *Blocked on §5.*
EOF
run 3 "stops when the only task is blocked"        next.sh 0905 code

doc 0906-waiting.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-06
---
## 7. Tasks
### Infra track
- [ ] **1.** Roles and grants.
### Code track
- [ ] **2.** The guard test. *Depends on task 1.*
EOF
run 3 "stops when the dependency is unticked" next.sh 0906 code

doc 0907-alldone.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-06
---
## 7. Tasks
### Code track
- [x] **1.** Done.
EOF
run 6 "distinguishes a complete but unfinalized design" next.sh 0907

run 1 "rejects a track the doc does not have" next.sh 0900 docs

# Approval is a precondition. Every fixture above is `approved` for exactly this reason —
# without the gate they would all still run, which is what made it worth adding.
n=916
for st in draft; do
  cat > "$SANDBOX/docs/design/0$n-$st.md" <<EOF
---
type: design
status: $st
last-verified: 2026-08-07
delivered: M1
---
## 7. Tasks
### Code track
- [ ] **1.** Work nobody has approved.
EOF
  run 1 "refuses to deliver a '$st' design doc" next.sh "0$n" code
  n=$((n+1))
done

cat > "$SANDBOX/docs/design/0919-nostatus.md" <<'EOF'
---
type: design
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] **1.** A doc with no status at all.
EOF
run 1 "refuses a doc with no status"  next.sh 0919 code

# A doc that cannot be parsed is broken, not unapproved — the parse error has to win, or
# the reader is sent to the wrong problem.
cat > "$SANDBOX/docs/design/0920-draftbad.md" <<'EOF'
---
type: design
status: draft
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] 1. Missing the bold marker.
EOF
run 1 "an unparseable draft reports the parse error, not the status" next.sh 0920 code
saw "the parse failure wins over approval status" "Missing the bold marker"

doc 0913-exhausted.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Infra track
- [x] **1.** Done.
### Code track
- [ ] **2.** Still pending.
EOF
run 3 "stops when this track is finished but others are not" next.sh 0913 infra

# Specification: docs/design/README.md, "The rule: frozen on delivery".
echo "freeze.sh"
FR=$(mktemp -d)
mkdir -p "$FR/docs/design" "$FR/core"
cp "$REAL_ROOT/core/lib.sh" "$FR/core/lib.sh"
cat > "$FR/docs/roadmap.md" <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-13
---
### M1 — First

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `pending` | Still in progress | — | [0910](./design/0910-pending.md) |
| `single` | Complete on one track | — | [0911](./design/0911-single.md) |
| `malformed` | Broken task list | — | [0914](./design/0914-malformed.md) |
| `draft` | Not approved | — | [0915](./design/0915-draft.md) |

**Done when:** x.

### M2 — Second

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `multi` | Complete across tracks | — | [0912](./design/0912-multi.md) |
| `duplicate-a` | First owner | — | [0913](./design/0913-duplicate.md) |
| `duplicate-b` | Second owner | — | [0913](./design/0913-duplicate.md) |
| `mismatch` | Wrong frozen milestone | — | [0917](./design/0917-mismatch.md) |
| `atomic` | Atomic replacement | — | [0921](./design/0921-atomic.md) |

**Done when:** y.

### M3 — Third ✅ 2026-08-13

Delivered as [0922](./design/0922-collapsed.md).
EOF

frdoc() { cat > "$FR/docs/design/$1"; }
frrun() {  # frrun <want-exit> <label> <doc-number>
  local want="$1" label="$2"; shift 2
  mint_at "$FR"
  OUT=$(CLAUDE_PROJECT_DIR="$FR" "$S/freeze.sh" "$1" 2>&1); local got=$?
  if [ "$got" = "$want" ]; then ok "$label"; else bad "$label" "want exit $want, got $got"; fi
}
frdoc 0910-pending.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [x] **1.** Done.
- [ ] **2.** Not done.
EOF
frdoc 0911-single.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [x] **1.** Done.
EOF
frdoc 0912-multi.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Infra track
- [x] **1.** Done.
### Code track
- [x] **2.** Also done.
EOF
frdoc 0913-duplicate.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [x] **1.** Done.
EOF
frdoc 0914-malformed.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [ ] 1. Missing the required task grammar.
EOF
frdoc 0915-draft.md <<'EOF'
---
type: design
status: draft
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [x] **1.** Done but not approved.
EOF
frdoc 0916-unclaimed.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [x] **1.** Done without a roadmap owner.
EOF
frdoc 0917-mismatch.md <<'EOF'
---
type: design
status: frozen
delivered: M1
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [x] **1.** Done.
EOF
frdoc 0921-atomic.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [x] **1.** Done.
EOF
frdoc 0922-collapsed.md <<'EOF'
---
type: design
status: frozen
delivered: M3
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [x] **1.** Done before the milestone table collapsed.
EOF
( cd "$FR" && git init -q -b main . && printf '.deliver/\n' > .gitignore \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm init )
cp "$FR/docs/design/0910-pending.md" "$FR/pending.before"
frrun 0 "leaves an approved design alone while a task remains" 0910
cmp -s "$FR/pending.before" "$FR/docs/design/0910-pending.md" \
  && ok "without changing a byte" || bad "without changing a byte" "pending doc changed"

frrun 0 "freezes a complete single-track design" 0911
grep -q '^status: frozen$' "$FR/docs/design/0911-single.md" \
  && ok "setting its frozen status" || bad "setting its frozen status" "status was not frozen"
grep -q '^delivered: M1$' "$FR/docs/design/0911-single.md" \
  && ok "using the roadmap milestone" || bad "using the roadmap milestone" "milestone was not M1"
grep -q "^last-verified: $(date +%F)$" "$FR/docs/design/0911-single.md" \
  && ok "stamping today's verification date" || bad "stamping today's verification date" "date was not updated"

frrun 0 "freezes a design only after every track is complete" 0912
grep -q '^delivered: M2$' "$FR/docs/design/0912-multi.md" \
  && ok "deriving the multi-track design's milestone" \
  || bad "deriving the multi-track design's milestone" "milestone was not M2"
cp "$FR/docs/design/0912-multi.md" "$FR/multi.after"
frrun 0 "is idempotent for an already-correct frozen design" 0912
cmp -s "$FR/multi.after" "$FR/docs/design/0912-multi.md" \
  && ok "leaving the frozen record byte-identical" \
  || bad "leaving the frozen record byte-identical" "frozen doc changed"

cp "$FR/docs/design/0922-collapsed.md" "$FR/collapsed.before"
frrun 0 "accepts a frozen doc after its milestone table collapses" 0922
cmp -s "$FR/collapsed.before" "$FR/docs/design/0922-collapsed.md" \
  && ok "leaving the collapsed-milestone record byte-identical" \
  || bad "leaving the collapsed-milestone record byte-identical" "frozen doc changed"

FAKE_BIN=$(mktemp -d)
printf '#!/usr/bin/env sh\nexit 1\n' > "$FAKE_BIN/mv"
chmod +x "$FAKE_BIN/mv"
cp "$FR/docs/design/0921-atomic.md" "$FR/atomic.before"
mint_at "$FR"
OUT=$(PATH="$FAKE_BIN:$PATH" CLAUDE_PROJECT_DIR="$FR" "$S/freeze.sh" 0921 2>&1); got=$?
if [ "$got" = 1 ]; then ok "reports an injected atomic-replacement failure"
else bad "reports an injected atomic-replacement failure" "want exit 1, got $got"; fi
cmp -s "$FR/atomic.before" "$FR/docs/design/0921-atomic.md" \
  && ok "an atomic-replacement failure leaves the original byte-identical" \
  || bad "an atomic-replacement failure leaves the original byte-identical" "original changed"
rm -rf "$FAKE_BIN"

FAKE_BIN=$(mktemp -d)
printf '#!/usr/bin/env sh\nexit 2\n' > "$FAKE_BIN/diff"
chmod +x "$FAKE_BIN/diff"
mint_at "$FR"
OUT=$(PATH="$FAKE_BIN:$PATH" CLAUDE_PROJECT_DIR="$FR" "$S/freeze.sh" 0921 2>&1); got=$?
if [ "$got" = 1 ]; then ok "fails closed when lifecycle-diff inspection cannot run"
else bad "fails closed when lifecycle-diff inspection cannot run" "want exit 1, got $got"; fi
cmp -s "$FR/atomic.before" "$FR/docs/design/0921-atomic.md" \
  && ok "a failed lifecycle inspection leaves the original byte-identical" \
  || bad "a failed lifecycle inspection leaves the original byte-identical" "original changed"
rm -rf "$FAKE_BIN"

for n in 0913 0914 0915 0916 0917; do
  cp "$FR/docs/design/$n"-*.md "$FR/$n.before"
done
frrun 1 "refuses ambiguous roadmap ownership" 0913
frrun 1 "refuses a malformed task list" 0914
frrun 1 "refuses to freeze a design that was not approved" 0915
frrun 1 "refuses a complete design with no roadmap owner" 0916
frrun 1 "refuses an already-frozen design with the wrong milestone" 0917
for n in 0913 0914 0915 0916 0917; do
  cmp -s "$FR/$n.before" "$FR/docs/design/$n"-*.md \
    && ok "failure leaves design $n unchanged" \
    || bad "failure leaves design $n unchanged" "file changed"
done
rm -rf "$FR"

echo "complete.sh"
run 1 "rejects an unknown task number"        complete.sh 0900 99
run 1 "rejects the removed --rounds flag"     complete.sh 0900 3 --rounds 4

# complete.sh now requires proof that the reviewer saw this exact tree, so the sandbox
# has to be a real repository with a real receipt.
mkdir -p "$SANDBOX/core/scripts"
cp "$S/tree-digest.sh" "$SANDBOX/core/scripts/"
cp "$REAL_ROOT/core/lib.sh" "$SANDBOX/core/lib.sh"
cp "$REAL_ROOT/core/delivery-policy.json" "$SANDBOX/core/delivery-policy.json"
( cd "$SANDBOX" && git init -q -b main . && printf '.deliver/\n' > .gitignore \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm init )
echo "tree-digest index flags"
DIGEST=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh" 2>/dev/null); got=$?
if [ "$got" = 0 ] && [ -n "$DIGEST" ]; then
  ok "fingerprints an ordinary tracked working tree"
else
  bad "fingerprints an ordinary tracked working tree" "want a digest, got exit $got and '$DIGEST'"
fi
printf 'reviewed deletion\n' > "$SANDBOX/deletion-stability"
git -C "$SANDBOX" add deletion-stability
git -C "$SANDBOX" -c user.email=t@t -c user.name=t commit -qm 'add deletion fixture'
rm "$SANDBOX/deletion-stability"
TD_DELETE_UNSTAGED=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
git -C "$SANDBOX" add -u deletion-stability
TD_DELETE_STAGED=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
[ "$TD_DELETE_UNSTAGED" = "$TD_DELETE_STAGED" ] \
  && ok "staging a reviewed deletion preserves its exact-tree identity" \
  || bad "staging a reviewed deletion preserves its exact-tree identity" "the digest changed without changing working-tree bytes"
git -C "$SANDBOX" restore --source=HEAD --staged --worktree deletion-stability
printf 'reviewed rename\n' > "$SANDBOX/rename-source"
git -C "$SANDBOX" add rename-source
git -C "$SANDBOX" -c user.email=t@t -c user.name=t commit -qm 'add rename fixture'
mv "$SANDBOX/rename-source" "$SANDBOX/rename-target"
TD_RENAME_UNSTAGED=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
git -C "$SANDBOX" add -A
TD_RENAME_STAGED=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
[ "$TD_RENAME_UNSTAGED" = "$TD_RENAME_STAGED" ] \
  && ok "staging a reviewed rename preserves its exact-tree identity" \
  || bad "staging a reviewed rename preserves its exact-tree identity" "the digest changed without changing working-tree bytes"
git -C "$SANDBOX" -c user.email=t@t -c user.name=t commit -qm 'rename fixture'
for INDEX_FLAG in assume-unchanged skip-worktree; do
  git -C "$SANDBOX" update-index "--$INDEX_FLAG" docs/design/0900-good.md
  DIGEST=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh" 2>/dev/null); got=$?
  git -C "$SANDBOX" update-index "--no-$INDEX_FLAG" docs/design/0900-good.md
  if [ "$got" = 1 ] && [ -z "$DIGEST" ]; then
    ok "refuses a $INDEX_FLAG tracked path before emitting a digest"
  else
    bad "refuses a $INDEX_FLAG tracked path before emitting a digest" "want exit 1 with no digest, got exit $got and '$DIGEST'"
  fi
done
for DIGEST_MODE in --check-index digest; do
  if [ "$DIGEST_MODE" = --check-index ]; then
    DIGEST=$( (
      awk() { return 42; }
      export -f awk
      CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh" --check-index
    ) 2>/dev/null ); got=$?
  else
    DIGEST=$( (
      awk() { return 42; }
      export -f awk
      CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh"
    ) 2>/dev/null ); got=$?
  fi
  if [ "$got" = 1 ] && [ -z "$DIGEST" ]; then
    ok "refuses $DIGEST_MODE mode when index-flag classification fails"
  else
    bad "refuses $DIGEST_MODE mode when index-flag classification fails" "want exit 1 with no digest, got exit $got and '$DIGEST'"
  fi
done

TD_TARGET_A=$(mktemp); TD_TARGET_B=$(mktemp)
printf 'same bytes\n' > "$TD_TARGET_A"; printf 'same bytes\n' > "$TD_TARGET_B"
ln -s "$TD_TARGET_A" "$SANDBOX/untracked-link"
TD_LINK_A=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
rm "$SANDBOX/untracked-link"; ln -s "$TD_TARGET_B" "$SANDBOX/untracked-link"
TD_LINK_B=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
[ "$TD_LINK_A" != "$TD_LINK_B" ] && ok "retargeting an untracked symlink changes the exact-tree digest" \
  || bad "retargeting an untracked symlink changes the exact-tree digest" "same-content targets collapsed to one identity"
rm "$SANDBOX/untracked-link" "$TD_TARGET_A" "$TD_TARGET_B"
TD_ODD=$'line\nname'
printf 'one\n' > "$SANDBOX/$TD_ODD"
TD_ODD_A=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
printf 'two\n' > "$SANDBOX/$TD_ODD"
TD_ODD_B=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
[ -n "$TD_ODD_A" ] && [ "$TD_ODD_A" != "$TD_ODD_B" ] \
  && ok "an unusual untracked filename remains a distinct digest input" \
  || bad "an unusual untracked filename remains a distinct digest input" "newline-delimited identity was lost"
rm "$SANDBOX/$TD_ODD"
printf 'one\n' > "$SANDBOX/--stdin"
TD_DASH_A=$(cd "$SANDBOX" && CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
printf 'two\n' > "$SANDBOX/--stdin"
TD_DASH_B=$(cd "$SANDBOX" && CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
[ -n "$TD_DASH_A" ] && [ "$TD_DASH_A" != "$TD_DASH_B" ] \
  && ok "a leading-dash untracked filename is content-bound, not parsed as hash-object input" \
  || bad "a leading-dash untracked filename is content-bound, not parsed as hash-object input" "--stdin content was absent from identity"
rm "$SANDBOX/--stdin"
printf 'X\0untracked-path\0b\0regular\0Y' > "$SANDBOX/a"
TD_BINARY_ONE=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
rm "$SANDBOX/a"; printf 'X' > "$SANDBOX/a"; printf 'Y' > "$SANDBOX/b"
TD_BINARY_TWO=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
[ "$TD_BINARY_ONE" != "$TD_BINARY_TWO" ] \
  && ok "binary content cannot impersonate a second untracked entry" \
  || bad "binary content cannot impersonate a second untracked entry" "record serialization aliased two trees"
rm "$SANDBOX/a" "$SANDBOX/b"
printf '#!/bin/sh\n' > "$SANDBOX/untracked-mode"
chmod 644 "$SANDBOX/untracked-mode"; TD_MODE_A=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
chmod 755 "$SANDBOX/untracked-mode"; TD_MODE_B=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
[ "$TD_MODE_A" != "$TD_MODE_B" ] && ok "an untracked executable-bit change moves the digest" \
  || bad "an untracked executable-bit change moves the digest" "Git mode was absent from identity"
rm "$SANDBOX/untracked-mode"

if ! (
  git() {
    if [ "${1:-}" = ls-files ] && [ "${2:-}" = -z ]; then return 42; fi
    command git "$@"
  }
  export -f git
  CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh"
) >/dev/null 2>&1; then
  ok "a working-tree inventory read failure makes exact-tree fingerprinting fail closed"
else
  bad "a working-tree inventory read failure makes exact-tree fingerprinting fail closed" "the digest omitted the unreadable inventory"
fi

mkfifo "$SANDBOX/untracked-special"
if ! CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh" >/dev/null 2>&1; then
  ok "an unsupported untracked FIFO makes exact-tree fingerprinting fail closed"
else
  bad "an unsupported untracked FIFO makes exact-tree fingerprinting fail closed" "FIFO was serialized as a reusable generic identity"
fi
rm "$SANDBOX/untracked-special"
TD_SOCKET_READY=$(mktemp)
node -e 'const fs=require("fs"),net=require("net"),p=process.argv[1],ready=process.argv[2];try{fs.unlinkSync(p)}catch{};const s=net.createServer();s.listen(p,()=>fs.writeFileSync(ready,"ready"));setTimeout(()=>s.close(),5000)' \
  "$SANDBOX/untracked-special" "$TD_SOCKET_READY" & TD_SOCKET_PID=$!
for _ in 1 2 3 4 5; do [ -S "$SANDBOX/untracked-special" ] && break; sleep 1; done
if [ ! -S "$SANDBOX/untracked-special" ]; then
  wait "$TD_SOCKET_PID" 2>/dev/null || true
  ok "the socket case is covered by the unsupported-node classifier (host forbids socket creation)"
elif ! CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh" >/dev/null 2>&1; then
  ok "a same-path untracked socket also fails closed instead of aliasing the FIFO"
else
  bad "a same-path untracked socket also fails closed instead of aliasing the FIFO" "socket was not rejected"
fi
wait "$TD_SOCKET_PID" 2>/dev/null || true
rm -f "$SANDBOX/untracked-special" "$TD_SOCKET_READY"

mkdir "$SANDBOX/untracked-repo"
git -C "$SANDBOX/untracked-repo" init -q
git -C "$SANDBOX/untracked-repo" config user.email test@example.com
git -C "$SANDBOX/untracked-repo" config user.name Test
printf 'one\n' > "$SANDBOX/untracked-repo/value"
git -C "$SANDBOX/untracked-repo" add value
git -C "$SANDBOX/untracked-repo" commit -qm one
TD_GITLINK_A=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
printf 'two\n' > "$SANDBOX/untracked-repo/value"
git -C "$SANDBOX/untracked-repo" commit -am two -q
TD_GITLINK_B=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
[ "$TD_GITLINK_A" != "$TD_GITLINK_B" ] && ok "an untracked nested repository commit moves the digest" \
  || bad "an untracked nested repository commit moves the digest" "gitlink commit was absent from identity"
rm -rf "$SANDBOX/untracked-repo"

mint_at "$SANDBOX" nd/unrelated/fixture
run 5 "refuses to tick a task with no review of this tree" complete.sh 0900 3
saw "and says the review is what is missing"               "no review of the current tree"
notsaw "and does not attribute unrelated evidence to this task" "changed after review"
rm -rf "$SANDBOX/.deliver/reviews/accepted/nd/unrelated"

mint() { mint_at "$SANDBOX"; }
mint
run 0 "ticks the box once a matching receipt exists" complete.sh 0900 3
saw "and emits the commit trailer"            "Review-Rounds: 1"
grep -qe '- \[x\] \*\*3\.\*\* Scaffold' "$SANDBOX/docs/design/0900-good.md" \
  && ok "the box is actually ticked in the file" \
  || bad "the box is actually ticked in the file" "not found"
grep -ce '- \[x\]' "$SANDBOX/docs/design/0900-good.md" | grep -q '^2$' \
  && ok "exactly one box changed" \
  || bad "exactly one box changed" "wrong count"
run 5 "idempotent recovery still requires review of the changed tree" complete.sh 0900 3
mint
run 0 "is idempotent after the current tree is reviewed" complete.sh 0900 3

echo "the review must match the tree, not merely exist"
mint
printf 'edited after the review\n' > "$SANDBOX/afterwards.txt"
run 5 "a stale receipt does not count"                complete.sh 0900 2
saw "and it says the code moved since the review"     "code changed after review"
mint
run 0 "re-reviewing the new tree unblocks it"         complete.sh 0900 2

# A refused review and a skipped review are different failures, and only one of them is
# fixed by reviewing again. Five rounds were once spent on that confusion: the reviewer ran
# every time, the hook refused every output, and this gate answered "the code changed".
printf 'edited once more\n' > "$SANDBOX/afterwards.txt"
DREJ=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
mkdir -p "$SANDBOX/.deliver/reviews/rejected"
printf 'rejected: "### Adversarial attacks" needs two "- Attack: ... Outcome: ..." entries; it has 1\nreceipt-version: 3\nagent: invariant-reviewer\ntree: %s\n---\n## Evidence\nVERDICT: clean — nothing survived.\n' \
  "$DREJ" > "$SANDBOX/.deliver/reviews/rejected/$DREJ.md"
run 5 "a refused review still refuses the tick"        complete.sh 0900 3
saw "and quotes the requirement that failed"           'needs two "- Attack: ... Outcome: ..." entries'
saw "and points at the review it kept"                 ".deliver/reviews/rejected/$DREJ.md"
notsaw "instead of blaming an edit that never happened" "changed after review"
rm -rf "$SANDBOX/.deliver/reviews/rejected"

mint
run 0 "a fresh review of this tree unblocks it"        complete.sh 0900 3

echo "the round ceiling is a renewable, human-granted window (ADR-0044)"
doc 0930-window.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [ ] **1.** A task whose review took many rounds.
- [ ] **2.** A later task.
EOF
# Four accepted rounds recorded for task 1; the base window is three and no grant covers
# the fourth. The current-tree non-delivery review remains a separate consumer key.
RS="$SANDBOX/.deliver/reviews/round-state"
for _ in 1 2 3 4; do mint_at "$SANDBOX" "0930-t1"; done
run 0 "round-status reports the spent window"             round-status.sh 0930 1
saw "counting the rounds used"                            "rounds-used: 4"
saw "against the base window of three"                    "window: 3"
saw "and that the next round needs a grant"               "next-round-needs-grant: yes"
mint
run 4 "a fourth round with no covering grant cannot tick" complete.sh 0930 1
grep -q '^- \[ \] \*\*1\.\*\*' "$SANDBOX/docs/design/0930-window.md" \
  && ok "the ungranted fourth round leaves the box unticked" \
  || bad "the ungranted fourth round leaves the box unticked" "the box moved"
# Malformation is scoped to the exact accepted key a consumer reads.
printf 'malformed\n' > "$SANDBOX/.deliver/reviews/accepted/0930-t1/not-a-round"
run 1 "round-status refuses malformed accepted task evidence" round-status.sh 0930 1
mint
run 2 "completion diagnoses malformed evidence separately from allowance exhaustion" complete.sh 0930 1
rm -f "$SANDBOX/.deliver/reviews/accepted/0930-t1/not-a-round"
# A canonical recorded grant renews the window (3 -> 6) and the same tree ticks; the derived
# trailer counts every round, not a self-reported number. Use the real host writer so this
# fixture exercises the same fixed-shape workflow record the readers validate.
( . "$REAL_ROOT/core/round-ledger.sh" \
  && round_grant_add "$SANDBOX" "0930-t1" 0000000000000000 3 3 "$ROUND_GRANT_LABEL" )
run 0 "round-status sees the renewed window"             round-status.sh 0930 1
saw "with the grant folded into the window"              "window: 6"
saw "and the next round no longer blocked"               "next-round-needs-grant: no"
run 0 "a granted fourth round ticks"                      complete.sh 0930 1
saw "and the derived trailer counts every round"          "Review-Rounds: 4"
# Ticking task 1 moved the tree; an accepted findings round for the new tree cannot tick.
mint_at "$SANDBOX" "" findings
run 5 "a findings verdict cannot tick"                    complete.sh 0930 2

echo "round-status.sh's no-argument window, off a delivery task (ADR-0046 Decision 2)"
# SANDBOX sits on main, never a delivery branch, so the derived key is branch-and-HEAD.
HEAD_SHA=$(git -C "$SANDBOX" rev-parse HEAD)
NDKEY="nd/main/$HEAD_SHA"
rm -rf "$SANDBOX/.deliver/reviews/accepted/$NDKEY"
for _ in 1 2 3; do mint_at "$SANDBOX" "$NDKEY"; done
run 0 "the no-argument form reports the branch-and-HEAD window" round-status.sh
saw "naming the derived key"                                    "task: $NDKEY"
saw "counting the rounds used"                                  "rounds-used: 3"
saw "against the base window of three"                          "window: 3"
saw "and that the next round needs a grant"                     "next-round-needs-grant: yes"
run 1 "a lone doc argument with no task number is a usage error" round-status.sh 0930
run 1 "a non-numeric doc argument is a usage error"              round-status.sh abc 1
rm -rf "$RS"

cat > "$SANDBOX/docs/roadmap.md" <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-13
---
### M4 — Complete integration

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `complete-integration` | Complete and freeze as one transition | — | [0923](./design/0923-complete-integration.md) |
| `standalone-finalization` | Receipt-bound convergence finalization | — | [0925](./design/0925-standalone-finalization.md) |

**Done when:** the task and lifecycle land together.
EOF
doc 0925-standalone-finalization.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [x] **1.** Work merged from independent tracks.
EOF
cp "$SANDBOX/docs/design/0925-standalone-finalization.md" "$SANDBOX/0925.before"
run 5 "standalone finalization requires review of its exact tree" freeze.sh 0925
cmp -s "$SANDBOX/0925.before" "$SANDBOX/docs/design/0925-standalone-finalization.md" \
  && ok "missing standalone review leaves lifecycle state unchanged" \
  || bad "missing standalone review leaves lifecycle state unchanged" "design changed"

# Finalization asks for a review the same way completion does, so it owes the same answer
# when the reviewer ran and its output was refused.
DFZ=$(CLAUDE_PROJECT_DIR="$SANDBOX" "$S/tree-digest.sh")
mkdir -p "$SANDBOX/.deliver/reviews/rejected"
printf 'rejected: "### Limits" names nothing\ntree: %s\n---\n## Evidence\nVERDICT: clean — nothing survived.\n' \
  "$DFZ" > "$SANDBOX/.deliver/reviews/rejected/$DFZ.md"
run 5 "a refused review does not finalize either"     freeze.sh 0925
saw "and it names the requirement that failed"        '"### Limits" names nothing'
notsaw "rather than only saying to run the reviewer"  "Run invariant-reviewer on this exact tree"
cmp -s "$SANDBOX/0925.before" "$SANDBOX/docs/design/0925-standalone-finalization.md" \
  && ok "and leaves lifecycle state unchanged" \
  || bad "and leaves lifecycle state unchanged" "design changed"
rm -rf "$SANDBOX/.deliver/reviews/rejected"
mint
run 0 "standalone finalization proceeds after exact-tree review" freeze.sh 0925

doc 0923-complete-integration.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Code track
- [ ] **1.** The final task.
EOF
mint
run 0 "freezes the design before completing its final task transition" complete.sh 0923 1
grep -q '^status: frozen$' "$SANDBOX/docs/design/0923-complete-integration.md" \
  && grep -q '^delivered: M4$' "$SANDBOX/docs/design/0923-complete-integration.md" \
  && grep -q '^- \[x\] \*\*1\.\*\*' "$SANDBOX/docs/design/0923-complete-integration.md" \
  && ok "the task tick and frozen frontmatter are present together" \
  || bad "the task tick and frozen frontmatter are present together" "transition was partial"

mint
run 0 "repairs finalization when the final task is already ticked and reviewed" complete.sh 0923 1
( cd "$SANDBOX" && git checkout -qb deliver/0923 )
run 7 "a frozen unmerged delivery branch resumes at Finish" next.sh 0923

echo "independent tracks converge on finalization"
for order in infra-code; do
  CB=$(mktemp -d)
  mkdir -p "$CB/docs/design"
  copy_harness "$REAL_ROOT" "$CB" core || exit 1
  cat > "$CB/docs/roadmap.md" <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-13
---
### M5 — Concurrent tracks

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `concurrent` | Independently mergeable tracks | — | [0924](./design/0924-concurrent.md) |

**Done when:** both tracks merge in either order.
EOF
  cat > "$CB/docs/design/0924-concurrent.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-01
---
## 7. Tasks
### Infra track
- [ ] **1.** Infra work.

Infra notes keep the track edits in separate merge contexts.

### Code track
- [ ] **2.** Code work.
EOF
  first=${order%-*}; second=${order#*-}
  first_branch="deliver/0924-$first"
  second_branch="deliver/0924-$second"
  (
    cd "$CB" || exit 1
    git init -q -b main .
    git config user.email t@t
    git config user.name t
    git add -A && git commit -qm base
    git checkout -qb deliver/0924-infra
    sed 's/- \[ \] \*\*1\.\*\*/- [x] **1.**/' docs/design/0924-concurrent.md > t && mv t docs/design/0924-concurrent.md
    git add -A && git commit -qm infra
    git checkout -q main && git checkout -qb deliver/0924-code
    sed 's/- \[ \] \*\*2\.\*\*/- [x] **2.**/' docs/design/0924-concurrent.md > t && mv t docs/design/0924-concurrent.md
    git add -A && git commit -qm code
    git checkout -q main
    git -c user.email=t@t -c user.name=t merge -q --no-edit "$first_branch"
    git checkout -q "$second_branch"
    git -c user.email=t@t -c user.name=t merge -q --no-edit main
  )
  if [ $? = 0 ]; then ok "the remaining track syncs the first in $order order"
  else bad "the remaining track syncs the first in $order order" "git merge failed"; rm -rf "$CB"; continue; fi

  OUT=$(CLAUDE_PROJECT_DIR="$CB" "$S/next.sh" 0924 2>&1); got=$?
  if [ "$got" = 6 ]; then ok "$order reaches finalization on the remaining delivery branch"
  else bad "$order reaches the distinct finalization state" "want exit 6, got $got"; fi
  case "$OUT" in *"FINALIZE:"*) ok "and the state is named, not treated as a stop" ;;
    *) bad "and the state is named, not treated as a stop" "FINALIZE missing" ;; esac

  OUT=$(CLAUDE_PROJECT_DIR="$CB" "$S/verify-design.sh" 0924 2>&1); got=$?
  if [ "$got" = 1 ]; then ok "$order cannot leave the complete doc approved"
  else bad "$order cannot leave the complete doc approved" "want exit 1, got $got"; fi

  mint_at "$CB"
  OUT=$(CLAUDE_PROJECT_DIR="$CB" "$S/freeze.sh" 0924 2>&1); got=$?
  if [ "$got" = 0 ]; then ok "$order finalizes inside the remaining delivery PR"
  else bad "$order finalizes inside the remaining delivery PR" "want exit 0, got $got: $OUT"; fi
  OUT=$(CLAUDE_PROJECT_DIR="$CB" "$S/verify-design.sh" 0924 2>&1); got=$?
  if [ "$got" = 0 ]; then ok "$order passes after finalization"
  else bad "$order passes after finalization" "$OUT"; fi
  ( cd "$CB" && git add -A && git commit -qm "review: freeze after convergence" )
  OUT=$(CLAUDE_PROJECT_DIR="$CB" "$S/next.sh" 0924 2>&1); got=$?
  if [ "$got" = 7 ]; then ok "$order resumes the frozen unmerged PR at Finish"
  else bad "$order resumes the frozen unmerged PR at Finish" "want exit 7, got $got"; fi
  rm -rf "$CB"
done

echo "verify-delivery.sh"
if node --test "$S/planned-catalog-doc-change.test.mjs"; then
  ok "planned catalog metadata preserves delivery authorization"
else
  bad "planned catalog metadata preserves delivery authorization" "classification proof failed"
fi
# A git sandbox with a base and a branch, because this checks what LANDED, not a doc.
VD=$(mktemp -d)
mkdir -p "$VD/docs/design" "$VD/core/scripts"
cp "$S/plan.sh" "$VD/core/scripts/"
cat > "$VD/docs/design/0900-x.md" <<'DOC'
---
type: design
status: approved
last-verified: 2026-08-06
---
## 7. Tasks
### Infra track
- [ ] **1.** Compose and the database.
- [ ] **3.** Another infra task.
### Code track
- [ ] **2.** The workspace.
DOC
(
  cd "$VD" || exit 1
  git init -q -b main . && git add -A
  git -c user.email=t@t -c user.name=t commit -qm base
  git checkout -q -b work
)
vd() { # vd <want-exit> <label>
  # GITHUB_HEAD_REF is cleared deliberately: the CI runner exports it, and without this
  # every case below would read the real PR branch instead of the sandbox's, so the
  # branch-name checks would test nothing and say ok. vdenv() sets it on purpose.
  OUT=$(cd "$VD" && CLAUDE_PROJECT_DIR="$VD" GITHUB_HEAD_REF= "$S/verify-delivery.sh" main 2>&1); local got=$?
  if [ "$got" = "$1" ]; then ok "$2"; else bad "$2" "want exit $1, got $got"; fi
}

mkdir -p "$VD/infra/db/init"
echo "CREATE ROLE geoffrey_app;" > "$VD/infra/db/init/01-roles.sql"
( cd "$VD" && git add -A && git -c user.email=t@t -c user.name=t commit -qm "task 1: roles" )
vd 1 "infra work that ticks no task fails"

( cd "$VD" && sed -e 's/- \[ \] \*\*1\.\*\*/- [x] **1.**/' docs/design/0900-x.md > t && mv t docs/design/0900-x.md \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm "tick task 1" )
vd 1 "ticking a task cannot authorize implementation on a non-delivery branch"

( cd "$VD" && git checkout -q main && git checkout -q -b readme-only )
echo "# notes" > "$VD/README.md"
( cd "$VD" && git add -A && git -c user.email=t@t -c user.name=t commit -qm "readme" )
vd 0 "a README change alone demands no task"

# Aggregate final tick membership cannot establish historical dependency order. Any
# implementation ref without canonical delivery identity is rejected before that lossy
# fallback can claim that task 2 was runnable merely because task 1 is also finally done.
( cd "$VD" && git checkout -q main )
cat > "$VD/docs/design/0907-order.md" <<'DOC'
---
type: design
status: approved
last-verified: 2026-08-21
---
## 7. Tasks
### Code track
- [ ] **1.** Dependency first.
- [ ] **2.** Dependent second. *Depends on task 1.*
DOC
(
  cd "$VD" || exit 1
  git add docs/design/0907-order.md && git -c user.email=t@t -c user.name=t commit -qm "add ordered fixture"
  git checkout -q -b work-reversed-order
  mkdir -p packages/order && echo reversed > packages/order/index.ts
  perl -pi -e 's/^- \[ \] \*\*2\./- [x] **2./' docs/design/0907-order.md
  git add packages/order/index.ts docs/design/0907-order.md \
    && git -c user.email=t@t -c user.name=t commit -qm "complete task 2 first"
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0907-order.md
  git add docs/design/0907-order.md \
    && git -c user.email=t@t -c user.name=t commit -qm "complete task 1 second"
)
vd 1 "a non-delivery implementation ref cannot launder reversed dependency history"

# next.sh reads the working tree, so writing `status: approved` on your own branch would
# satisfy it. This is the half that cannot be faked from the branch.
echo "approval lives on the trunk"
cat > "$VD/docs/design/0902-z.md" <<'DOC'
---
type: design
status: draft
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] **1.** Work nobody approved.
DOC
( cd "$VD" && git checkout -q main && git add -A \
  && git -c user.email=t@t -c user.name=t commit -qm "add 0902 as a draft" \
  && git checkout -q -b work6 \
  && sed -e 's/status: draft/status: approved/' -e 's/- \[ \] \*\*1\.\*\*/- [x] **1.**/' \
       docs/design/0902-z.md > t && mv t docs/design/0902-z.md \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm "approve and tick" )
vd 1 "approving a doc on the very branch that delivers it fails"

( cd "$VD" && git checkout -q main && git checkout -q -b work7 )
cat > "$VD/docs/design/0903-new.md" <<'DOC'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [x] **1.** Created and delivered in one breath.
DOC
( cd "$VD" && git add -A && git -c user.email=t@t -c user.name=t commit -qm "add and tick" )
vd 1 "creating a design doc and delivering it in one branch fails"
notsaw "without claiming the ticks were checked for runnability" "every ticked task was runnable"

# Every check here is per doc, because `head -1` answered about whichever filename sorted
# first. Both directions of that bug, as one branch each.
echo "each doc is judged on its own status"
( cd "$VD" && git checkout -q main && git checkout -q -b work8 \
  && sed -e 's/- \[ \] \*\*1\.\*\*/- [x] **1.**/' docs/design/0902-z.md > t && mv t docs/design/0902-z.md \
  && printf '\n<!-- touched -->\n' >> docs/design/0900-x.md \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm "tick the draft, touch the approved one" )
vd 1 "ticking a draft doc while touching an approved one still fails"

( cd "$VD" && git checkout -q main && git checkout -q -b work9 \
  && sed -e 's/- \[ \] \*\*1\.\*\*/- [x] **1.**/' docs/design/0900-x.md > t && mv t docs/design/0900-x.md )
cat > "$VD/docs/design/0899-followup.md" <<'DOC'
---
type: design
status: draft
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] **1.** A follow-up nobody has approved yet.
DOC
( cd "$VD" && git add -A && git -c user.email=t@t -c user.name=t commit -qm "deliver 0900, draft a follow-up" )
vd 0 "delivering one doc while drafting an untouched second one passes"

# Check 4 had no cases at all, and this PR rewrote it.
echo "a completed task cannot go back to pending"
( cd "$VD" && git checkout -q main )
cat > "$VD/docs/design/0906-done.md" <<'DOC'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [x] **1.** Finished before this branch existed.
- [ ] **2.** Still open.
DOC
( cd "$VD" && git add -A && git -c user.email=t@t -c user.name=t commit -qm "add 0906 with task 1 done" \
  && git checkout -q -b work10 \
  && sed -e 's/- \[x\] \*\*1\.\*\*/- [ ] **1.**/' docs/design/0906-done.md > t && mv t docs/design/0906-done.md \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm "un-tick task 1" )
vd 1 "un-ticking a completed task fails"

# plan.sh resolves a doc by its four-digit prefix, so a shared prefix used to make the
# regression check compare one doc's past against the other's present.
( cd "$VD" && git checkout -q main )
cat > "$VD/docs/design/0904-alpha.md" <<'DOC'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [x] **1.** Alpha, finished.
DOC
sed 's/Alpha, finished./Beta, finished./' "$VD/docs/design/0904-alpha.md" > "$VD/docs/design/0904-beta.md"
( cd "$VD" && git add -A && git -c user.email=t@t -c user.name=t commit -qm "two docs sharing a prefix" \
  && git checkout -q -b work11 \
  && sed -e 's/- \[x\] \*\*1\.\*\*/- [ ] **1.**/' docs/design/0904-beta.md > t && mv t docs/design/0904-beta.md \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm "un-tick beta" )
vd 1 "a regression in the second of two docs sharing a prefix is still caught"

# A rename hides a doc's history from every check here, so an un-tick alongside one used to
# pass. Refused rather than guessed at.
( cd "$VD" && git checkout -q main && git checkout -q -b work12 \
  && git mv docs/design/0906-done.md docs/design/0906-renamed.md \
  && sed -e 's/- \[x\] \*\*1\.\*\*/- [ ] **1.**/' docs/design/0906-renamed.md > t \
  && mv t docs/design/0906-renamed.md \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm "rename and un-tick" )
vd 1 "renaming a design doc while un-ticking a task fails"

# The renamed doc is skipped, because every per-doc check would describe it wrongly: "not
# on main" about a doc that was there under another name sends the author to the wrong fix.
( cd "$VD" && git checkout -q main && git checkout -q -b work13 \
  && git mv docs/design/0900-x.md docs/design/0900-moved.md \
  && sed -e 's/- \[ \] \*\*1\.\*\*/- [x] **1.**/' docs/design/0900-moved.md > t \
  && mv t docs/design/0900-moved.md \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm "rename and deliver" )
vd 1 "renaming a design doc while delivering a task fails"
notsaw "not misdiagnosed as a doc that never existed" "is not on main"
notsaw "and no claim about ticks it never examined"   "no tasks ticked"

# ADR-0030 — the branch names the track when the doc has several. Cut from main each time,
# so the branch name is the only thing under test: no commits means no shape to fail on.
echo "the delivery branch names its track"
( cd "$VD" && git checkout -q main && git checkout -q -b deliver/0900 )
vd 1 "a two-track doc on a track-less branch fails"

( cd "$VD" && git checkout -q main && git checkout -q -b deliver/0900-code )
vd 0 "the same doc on deliver/0900-code passes"

( cd "$VD" && git checkout -q main && git checkout -q -b deliver/0900-docs )
vd 1 "a suffix that is not one of the doc's tracks fails"

cat > "$VD/docs/design/0901-y.md" <<'DOC'
---
type: design
status: approved
last-verified: 2026-08-07
---
## 7. Tasks
### Code track
- [ ] **1.** The only kind of work this doc has.
DOC
( cd "$VD" && git checkout -q main && git add -A \
  && git -c user.email=t@t -c user.name=t commit -qm "add 0901" \
  && git checkout -q -b deliver/0901 )
vd 0 "a single-track doc needs no suffix"

( cd "$VD" && git checkout -q main && git checkout -q -b deliver/0901-code )
vd 1 "a single-track doc carrying a suffix fails"

( cd "$VD" && git checkout -q main && git checkout -q -B deliver/0901 )
perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' "$VD/docs/design/0901-y.md"
( cd "$VD" && git add -A && git -c user.email=t@t -c user.name=t commit -qm "review: hide task 1 tick" )
vd 1 "CI rejects a task tick hidden in an otherwise allowed review commit"
perl -0pi -e 's/(- \[x\] \*\*1\.\*\* The only kind of work this doc has\.)/$1\n### Infra track\n- [ ] **2.** Routed follow-up./' \
  "$VD/docs/design/0901-y.md"
(
  cd "$VD" || exit 1
  git add docs/design/0901-y.md && git -c user.email=t@t -c user.name=t \
    commit --amend -qm "task 1: complete reviewed work" -m "Review-Rounds: 1"
)
vd 0 "CI keeps the reviewed suffixless branch when a pending SCOPE task adds a track"
( cd "$VD" && git checkout -q -B deliver/0901- )
vd 1 "CI rejects a trailing hyphen instead of treating it as a suffixless branch"
( cd "$VD" && git checkout -q -B deliver/0901-code )
vd 1 "CI rejects a suffix derived only from an unreviewed SCOPE task's new track"

(
  cd "$VD" || exit 1
  git checkout -q main && git checkout -q -B deliver/0900-code
  perl -pi -e 's/^- \[ \] \*\*2\./- [x] **2./' docs/design/0900-x.md
  git add -A && git -c user.email=t@t -c user.name=t \
    commit -qm "task 2: code task" -m "Review-Rounds: 1"
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0900-x.md
  git add -A && git -c user.email=t@t -c user.name=t \
    commit -qm "task 1: infra task" -m "Review-Rounds: 1"
)
vd 1 "CI rejects canonical commits from two tracks on one track branch"

(
  cd "$VD" || exit 1
  git checkout -q main && git checkout -q -B deliver/0900-code
  perl -0pi -e 's/- \[ \] \*\*1\.\*\* Compose and the database\.\n//; s/### Code track\n/### Code track\n- [x] **1.** Compose and the database.\n/' docs/design/0900-x.md
  git add docs/design/0900-x.md && git -c user.email=t@t -c user.name=t \
    commit -qm "task 1: move infra work into code" -m "Review-Rounds: 1"
)
vd 1 "CI rejects branch-local task reassignment into the named track"

(
  cd "$VD" || exit 1
  git checkout -q main && git checkout -q -B deliver/0900-code
  perl -pi -e 's/^- \[ \] \*\*2\./- [x] **2./' docs/design/0900-x.md
  git add docs/design/0900-x.md && git -c user.email=t@t -c user.name=t \
    commit -qm "task 2: branch design" -m "Review-Rounds: 1"
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0901-y.md
  git add docs/design/0901-y.md && git -c user.email=t@t -c user.name=t \
    commit -qm "task 1: other design" -m "Review-Rounds: 1"
)
vd 1 "CI rejects a canonical task commit from a second design"
( cd "$VD" && git -c user.email=t@t -c user.name=t commit --amend -qm "review: hide second-design task" )
vd 1 "CI also rejects a review-hidden task from a second design"

( cd "$VD" && git checkout -q main )
cat > "$VD/docs/design/0905-reset.md" <<'DOC'
---
type: design
status: approved
last-verified: 2026-08-21
---
## 7. Tasks
### Code track
- [ ] **1.** First completed task.
- [ ] **2.** Completion retained after merge.
DOC
(
  cd "$VD" || exit 1
  git add docs/design/0905-reset.md && git -c user.email=t@t -c user.name=t commit -qm "add reset fixture"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q -b deliver/0905
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0905-reset.md
  git add -A && git -c user.email=t@t -c user.name=t commit -qm "task 1: first" -m "Review-Rounds: 1"
  perl -pi -e 's/^- \[ \] \*\*2\./- [x] **2./' docs/design/0905-reset.md
  git add -A && git -c user.email=t@t -c user.name=t commit -qm "task 2: second" -m "Review-Rounds: 1"
  git checkout -q main
  echo advance > unrelated.txt
  git add unrelated.txt && git -c user.email=t@t -c user.name=t commit -qm "advance trunk fixture"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q deliver/0905
  git -c user.email=t@t -c user.name=t merge -q --no-commit main
  perl -pi -e 's/^- \[x\] \*\*1\./- [ ] **1./' docs/design/0905-reset.md
  git add docs/design/0905-reset.md && git -c user.email=t@t -c user.name=t \
    commit -qm "Merge main while resetting task 1"
)
vd 1 "CI rejects a merge that resets a delivered task to trunk's older pending state"

# The outside verifier must surface the same failed history enumeration as the live gate.
# A wrapper targets only task_commits_validate's first-parent enumeration.
mkdir "$VD/failing-git"
VD_REAL_GIT=$(command -v git)
{
  printf '#!/bin/sh\n'
  printf 'case " $* " in *" rev-list --reverse --first-parent "*) exit 1 ;; esac\n'
  printf 'exec "%s" "$@"\n' "$VD_REAL_GIT"
} > "$VD/failing-git/git"
chmod +x "$VD/failing-git/git"
VD_OLD_PATH=$PATH
PATH="$VD/failing-git:$PATH"
vd 1 "CI fails closed when delivery-commit enumeration is unreadable"
PATH=$VD_OLD_PATH
{
  printf '#!/bin/sh\n'
  printf '[ "$1" = diff ] && [ "${2:-}" = --text ] && exit 1\n'
  printf 'exec "%s" "$@"\n' "$VD_REAL_GIT"
} > "$VD/failing-git/git"
PATH="$VD/failing-git:$PATH"
vd 1 "CI fails closed when textual task-transition discovery is unreadable"
PATH=$VD_OLD_PATH

{
  printf '#!/bin/sh\n'
  printf '[ "$1" = diff ] && [ "${2:-}" = --name-only ] && exit 1\n'
  printf 'exec "%s" "$@"\n' "$VD_REAL_GIT"
} > "$VD/failing-git/git"
PATH="$VD/failing-git:$PATH"
vd 1 "CI fails closed when implementation-path discovery is unreadable"
PATH=$VD_OLD_PATH

{
  printf '#!/bin/sh\n'
  printf 'if [ "$1" = diff ] && [ "${2:-}" = --name-only ]; then for arg in "$@"; do [ "$arg" = '\''docs/design/[0-9]*.md'\'' ] && exit 1; done; fi\n'
  printf 'exec "%s" "$@"\n' "$VD_REAL_GIT"
} > "$VD/failing-git/git"
PATH="$VD/failing-git:$PATH"
vd 1 "CI fails closed when design-document discovery is unreadable"
PATH=$VD_OLD_PATH

{
  printf '#!/bin/sh\n'
  printf '[ "$1" = diff ] && [ "${2:-}" = --name-status ] && exit 1\n'
  printf 'exec "%s" "$@"\n' "$VD_REAL_GIT"
} > "$VD/failing-git/git"
PATH="$VD/failing-git:$PATH"
vd 1 "CI fails closed when rename-state discovery is unreadable"
PATH=$VD_OLD_PATH

# A valid delivery branch isolates commit-body and historical parser failures from ordinary
# shape findings, proving each producer is independently required for a green result.
(
  cd "$VD" || exit 1
  git checkout -q main && git checkout -q -B deliver/0901
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0901-y.md
  git add docs/design/0901-y.md && git -c user.email=t@t -c user.name=t \
    commit -qm "task 1: only task" -m "Review-Rounds: 1"
)
vd 0 "the authority-failure fixture starts from a valid delivery history"
{
  printf '#!/bin/sh\n'
  printf 'if [ "$1" = log ]; then for arg in "$@"; do [ "$arg" = --format=%%B ] && exit 1; done; fi\n'
  printf 'exec "%s" "$@"\n' "$VD_REAL_GIT"
} > "$VD/failing-git/git"
PATH="$VD/failing-git:$PATH"
vd 1 "CI fails closed when a task commit body is unreadable"
PATH=$VD_OLD_PATH

{
  printf '#!/bin/sh\n'
  printf 'for arg in "$@"; do case "$arg" in *:docs/design/0901-y.md) printf "- [ ] malformed historical endpoint\\n"; exit 0;; esac; done\n'
  printf 'exec "%s" "$@"\n' "$VD_REAL_GIT"
} > "$VD/failing-git/git"
PATH="$VD/failing-git:$PATH"
vd 1 "CI fails closed when historical plan input cannot be parsed"
PATH=$VD_OLD_PATH

cp "$VD/docs/design/0901-y.md" "$VD/0901.good"
printf '%s\n' '- [ ] malformed current endpoint' > "$VD/docs/design/0901-y.md"
vd 1 "CI fails closed when current plan input cannot be parsed"
mv "$VD/0901.good" "$VD/docs/design/0901-y.md"
rm -rf "$VD/failing-git"

# On a pull_request, actions/checkout leaves HEAD detached at the merge ref, so
# `abbrev-ref HEAD` is the string "HEAD" and every branch-name check silently matches
# nothing. The branch has to come from the environment or the guard only ever runs on the
# machine where --no-verify can skip it.
vdenv() { # vdenv <want-exit> <label> <head-ref>
  OUT=$(cd "$VD" && CLAUDE_PROJECT_DIR="$VD" GITHUB_HEAD_REF="$3" "$S/verify-delivery.sh" main 2>&1); local got=$?
  if [ "$got" = "$1" ]; then ok "$2"; else bad "$2" "want exit $1, got $got"; fi
}
( cd "$VD" && git checkout -q --detach main )
vd 0 "a detached HEAD with nothing to go on checks no branch"
vdenv 1 "a detached HEAD still catches a bad delivery branch" deliver/0900
vdenv 0 "and still passes a good one"                   deliver/0900-code
rm -rf "$VD"

# Collapsed-pointer specification: docs/design/README.md, "The rule: frozen on delivery".
echo "roadmap.sh"
RM=$(mktemp -d)
mkdir -p "$RM/docs/design"
rmdoc() { cat > "$RM/docs/roadmap.md"; }
rmrun() {  # rmrun <want-exit> <label> <script> [args...]
  local want="$1" label="$2"; shift 2
  OUT=$(cd "$RM" && CLAUDE_PROJECT_DIR="$RM" "$S/$1" "${@:2}" 2>&1); local got=$?
  if [ "$got" = "$want" ]; then ok "$label"; else bad "$label" "want exit $want, got $got"; fi
}

roadmap_good() { rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
# Roadmap

### M0 — Spec ✅ 2026-01-01

Shipped, so it needs no bar.

### M1 — First

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | The first thing | — | — |
| `beta` | The second | `alpha` | — |

**Done when:** both work.

## Deliberately deferred

| Thing | Until |
|---|---|
| Something else | Later |
EOF
}
roadmap_good
rmrun 0 "parses a well-formed roadmap"    roadmap.sh
saw "reading a slug with no dependency"   "$(printf 'alpha\037M1\037\037')"
saw "and one with a dependency"           "$(printf 'beta\037M1\037alpha\037')"
notsaw "and does not read the deferred table as initiatives" "Something else"
rmrun 0 "emits milestone state"           roadmap.sh --milestones
saw "marking a shipped milestone"         "$(printf 'M0\037shipped')"
saw "and an open one with its bar"        "$(printf 'M1\037\037done-when')"

printf '%s\n' placeholder > "$RM/docs/design/0001-alpha.md"
printf '%s\n' placeholder > "$RM/docs/design/0002-beta.md"
awk '/^\*\*Done when:/ {print "| `mismatch` | Label and target disagree | — | [0001](./design/0002-beta.md) |"} {print}' \
  "$RM/docs/roadmap.md" > "$RM/t" && mv "$RM/t" "$RM/docs/roadmap.md"
rmrun 1 "rejects a design link whose label and target disagree" roadmap.sh
roadmap_good

rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M3 — Shipped ✅ 2026-08-08

Delivered as [0001](./design/0001-alpha.md).

### M4 — Open

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `future` | Keeps the registry nonempty | — | — |

**Done when:** x.
EOF
rmrun 0 "parses collapsed pointers from a shipped milestone" roadmap.sh --delivered
saw "emitting the design and persisted milestone" "$(printf '0001\037M3')"

sed -i.bak 's/\[0001\]/[0002]/' \
  "$RM/docs/roadmap.md" && rm -f "$RM/docs/roadmap.md.bak"
rmrun 1 "rejects a collapsed pointer whose label and target disagree" roadmap.sh --delivered

sed -i.bak 's/\[0002\]/[0001]/' \
  "$RM/docs/roadmap.md" && rm -f "$RM/docs/roadmap.md.bak"
sed -i.bak 's/^### M3 — Shipped ✅ 2026-08-08$/### M3 — Not shipped/' \
  "$RM/docs/roadmap.md" && rm -f "$RM/docs/roadmap.md.bak"
rmrun 1 "rejects a collapsed pointer before its milestone ships" roadmap.sh --delivered

rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M3 — Everything shipped ✅ 2026-08-08

Delivered as [0001](./design/0001-alpha.md), [0002](./design/0002-beta.md).
EOF
rmrun 0 "accepts a roadmap whose every initiative table has collapsed" roadmap.sh
rmrun 0 "and still exposes its persisted design pointers" roadmap.sh --delivered
saw "including both pointers" "$(printf '0002\037M3')"

# Specification: docs/README.md, roadmap lifecycle; shipped milestones contain only the
# persisted delivery pointer, never a second copy of their expired initiative table.
rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M3 — Hybrid record ✅ 2026-08-08

Delivered as [0001](./design/0001-alpha.md).

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | A row that should have expired | — | [0001](./design/0001-alpha.md) |
EOF
rmrun 1 "rejects initiative rows retained under a shipped milestone" roadmap.sh
roadmap_good

# The registry fails closed for the same reason plan.sh does: a row it cannot read is an
# initiative that silently does not exist, and /design would refuse work that is there.
rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M1 — First
| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `Alpha` | Capitals are not a slug | — | — |
EOF
rmrun 1 "fails closed on a row it cannot read" roadmap.sh

rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M1 — First
| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | A cell with an | unescaped pipe | — | — |
EOF
rmrun 1 "fails closed on a row with the wrong cell count" roadmap.sh

# The depends cell gets the same grammar as the slug cell. Unvalidated it reached the
# verifier as an unquoted word list, where a glob expands against the repository.
rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M1 — First
| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | fine | — | — |
| `beta` | not fine | * | — |
EOF
rmrun 1 "fails closed on a depends cell that is not a slug" roadmap.sh

# "### M2" with no title used to match the section closer instead of the milestone rule,
# so every row beneath it was swallowed without a word.
rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M1 — First
| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | first | — | — |

### M2
| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `beta` | second | — | — |
EOF
rmrun 0 "reads a milestone heading with no title" roadmap.sh
saw "and the rows under it"                       "$(printf 'beta\037M2')"

rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `orphan` | Before any milestone heading | — | — |

### M1 — First
| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | first | — | — |
EOF
rmrun 1 "fails closed on an initiative outside every milestone" roadmap.sh

# The gate /design opens with. Its exit codes are the whole of step 1, so they are what
# stops the skill inventing an initiative or writing a second doc for one.
rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M1 — First

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | Already designed | — | [0001](./design/0001-x.md) |
| `beta` | Not yet | `alpha` | — |

**Done when:** x.
EOF
rmrun 0 "resolves a slug that has no design doc yet" roadmap.sh --slug beta
saw "returning its record"                           "$(printf 'beta\037M1\037alpha\037')"
rmrun 3 "stops on a slug that already has one"       roadmap.sh --slug alpha
rmrun 1 "refuses a slug that is not in the registry" roadmap.sh --slug nonsense
rmrun 1 "requires a slug"                            roadmap.sh --slug

echo "verify-roadmap.sh"
good() {  # the well-formed roadmap, as a baseline every case below mutates
  rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M0 — Spec ✅ 2026-01-01

### M1 — First

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | The first thing | — | — |
| `beta` | The second | `alpha` | — |

**Done when:** both work.
EOF
}
# The verifier requires a real base ref, like its siblings. HEAD holds the baseline; every
# case below mutates the working tree, so check 6 sees exactly what the case added.
good
( cd "$RM" && git init -q -b main . && git add -A \
  && git -c user.email=t@t -c user.name=t commit -qm base )
rmrun 0 "passes a well-formed roadmap" verify-roadmap.sh HEAD

rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M3 — Everything shipped ✅ 2026-08-08

Delivered as [0001](./design/0001-alpha.md), [0002](./design/0002-beta.md).
EOF
rmrun 0 "verifies a roadmap after every milestone table has collapsed" verify-roadmap.sh HEAD
good
rmrun 1 "refuses a base ref that does not exist" verify-roadmap.sh nope/nope

# Check 0 has its own early exit path, which no other case reaches.
good && printf '| `Alpha` | Capitals are not a slug | — | — |\n' >> "$RM/docs/roadmap.md"
rmrun 1 "stops at a roadmap that will not parse" verify-roadmap.sh HEAD

good && printf '\n### M1 — A second section claiming the same id\n\n**Done when:** never.\n' >> "$RM/docs/roadmap.md"
rmrun 1 "rejects a duplicate milestone id" verify-roadmap.sh HEAD

# A milestone id in Depends stands for every slug in it. Unexpanded it blocked nothing, so
# this pair — which can never start — was reported acyclic.
rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M1 — First

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | waits for all of M2 | `M2` | — |

**Done when:** x.

### M2 — Second

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `beta` | waits for alpha | `alpha` | — |

**Done when:** y.
EOF
rmrun 1 "rejects a deadlock reached through a milestone edge" verify-roadmap.sh HEAD

good && printf '| `alpha` | A second row claiming the same identity | — | — |\n' >> "$RM/docs/roadmap.md"
rmrun 1 "rejects a duplicate slug"  verify-roadmap.sh HEAD

good && printf '| `gamma` | Depends on nothing real | `nowhere` | — |\n' >> "$RM/docs/roadmap.md"
rmrun 1 "rejects a dependency that resolves to nothing" verify-roadmap.sh HEAD

good && printf '| `gamma` | Waits on delta | `delta` | — |\n| `delta` | Waits on gamma | `gamma` | — |\n' >> "$RM/docs/roadmap.md"
rmrun 1 "rejects a dependency cycle" verify-roadmap.sh HEAD

good && printf '| `gamma` | Names a design doc that is not there | — | [0099](./design/0099-x.md) |\n' >> "$RM/docs/roadmap.md"
rmrun 1 "rejects a design reference that resolves to nothing" verify-roadmap.sh HEAD

good && printf '\n### M2 — Second\n\n| Slug | Initiative | Depends | Design |\n|---|---|---|---|\n| `gamma` | In a milestone with no bar | — | — |\n' >> "$RM/docs/roadmap.md"
rmrun 1 "rejects a milestone with no 'Done when:'" verify-roadmap.sh HEAD

# A shipped milestone is a pointer, not a backlog. Even a grandfathered row is invalid:
# marking the milestone shipped and collapsing its table are one lifecycle transition.
shipped_base() {
  rmdoc <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M0 — Spec ✅ 2026-01-01

Delivered as the specification reference set.

### M1 — First

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | The first thing | — | — |

**Done when:** it works.
EOF
}
shipped_base
( cd "$RM" && git add -A && git -c user.email=t@t -c user.name=t commit -qm "M0 has shipped" )

# Relocating existing work under a ✅ is rejected by the parser itself.
shipped_base && awk '/^\| `alpha`/ {next} /^Delivered as/ {print; print ""; print "| Slug | Initiative | Depends | Design |"; print "|---|---|---|---|"; print "| `alpha` | Moved under the shipped milestone | — | — |"; next} {print}' \
  "$RM/docs/roadmap.md" > "$RM/t" && mv "$RM/t" "$RM/docs/roadmap.md"
rmrun 1 "rejects an existing initiative relocated into a shipped milestone" verify-roadmap.sh HEAD
shipped_base
awk '/^### M0/ {print; print ""; print "| Slug | Initiative | Depends | Design |"; print "|---|---|---|---|"; print "| `late` | Added to a milestone that shipped | — | — |"; next} {print}' \
  "$RM/docs/roadmap.md" > "$RM/t" && mv "$RM/t" "$RM/docs/roadmap.md"
rmrun 1 "rejects new work added to a shipped milestone" verify-roadmap.sh HEAD

# A slug that is new but lands in an open milestone is ordinary planning, not a finding.
good && printf '| `newcomer` | Added to an open milestone | — | — |\n' >> "$RM/docs/roadmap.md"
rmrun 0 "allows new work in a milestone that has not shipped" verify-roadmap.sh HEAD

rm -rf "$RM"

echo "verify-docs.sh"
DX=$(mktemp -d)
mkdir -p "$DX/docs/design"
cat > "$DX/docs/design/0990-claimed-too-soon.md" <<'EOF'
---
type: design
status: approved
delivered: M1
last-verified: 2026-08-13
---
## 7. Tasks
### Code track
- [ ] **1.** Still pending.
EOF
cat > "$DX/docs/design/README.md" <<'EOF'
# Lifecycle grammar example

```md
Delivered as [9999](./design/9999-example.md).
```
EOF
( cd "$DX" && git init -q -b main . && git add -A \
  && git -c user.email=t@t -c user.name=t commit -qm base )
OUT=$(cd "$DX" && CLAUDE_PROJECT_DIR="$DX" "$S/verify-docs.sh" HEAD 2>&1); got=$?
if [ "$got" = 1 ]; then ok "rejects delivered metadata on a design that is not frozen"
else bad "rejects delivered metadata on a design that is not frozen" "want exit 1, got $got"; fi
sed -i.bak '/^delivered:/d' "$DX/docs/design/0990-claimed-too-soon.md" \
  && rm -f "$DX/docs/design/0990-claimed-too-soon.md.bak"
OUT=$(cd "$DX" && CLAUDE_PROJECT_DIR="$DX" "$S/verify-docs.sh" HEAD 2>&1); got=$?
if [ "$got" = 0 ]; then ok "ignores illustrative links inside fenced code blocks"
else bad "ignores illustrative links inside fenced code blocks" "$OUT"; fi
mkdir -p "$DX/docs/decisions"
cat > "$DX/docs/decisions/0001-invalid-subject.md" <<'EOF'
---
type: decision
status: proposed
subject: product
date: 2026-09-09
---
# Invalid subject fixture
EOF
printf '# Decisions\n\n0001-invalid-subject.md\n' > "$DX/docs/decisions/README.md"
git -C "$DX" add docs/decisions
OUT=$(cd "$DX" && CLAUDE_PROJECT_DIR="$DX" "$S/verify-docs.sh" HEAD 2>&1); got=$?
if [ "$got" = 1 ]; then ok "rejects a decision with an unknown review subject"
else bad "rejects a decision with an unknown review subject" "want exit 1, got $got"; fi
rm -rf "$DX"

echo "verify-design.sh"
DS=$(mktemp -d)
mkdir -p "$DS/docs/design"
dsdoc() { cat > "$DS/docs/design/$1"; }
dsrun() {  # dsrun <want-exit> <label> [args...]
  local want="$1" label="$2"; shift 2
  OUT=$(CLAUDE_PROJECT_DIR="$DS" "$S/verify-design.sh" "$@" 2>&1); local got=$?
  if [ "$got" = "$want" ]; then ok "$label"; else bad "$label" "want exit $want, got $got"; fi
}

dsdoc 0960-good.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 5. Open — settle before task 3

| Question | Why it matters |
|---|---|
| Something | Because |

## 7. Tasks
### Code track
- [ ] **1.** The workspace.
- [ ] **2.** The guard test. *Depends on task 1.*
- [ ] **3.** Queue wiring. *Blocked on §5.*
EOF
dsrun 0 "passes a deliverable design doc"

# next.sh does not fail on this — it reports "Waiting on task 99 ( track):" with an empty
# title and stops, every run, forever. Cheap to catch here.
dsdoc 0961-ghostdep.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] **1.** Waits on a task nobody wrote. *Depends on task 99.*
EOF
dsrun 1 "rejects a dependency on a task that does not exist" 0961

dsdoc 0962-cycle.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] **1.** Waits on two. *Depends on task 2.*
- [ ] **2.** Waits on one. *Depends on task 1.*
EOF
dsrun 1 "rejects a dependency cycle" 0962

dsdoc 0963-ghostsection.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] **1.** Queue wiring. *Blocked on §9.*
EOF
dsrun 1 "rejects a blocked-on marker naming no section" 0963

# plan.sh takes the first "Blocked on " in a task's block, so a title carrying the phrase
# shadows the real marker. The doc is then genuinely ambiguous, and this refuses it rather
# than guessing which one was meant.
dsdoc 0966-shadowed.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 5. Open — settle first

| Question | Why it matters |
|---|---|
| Something | Because |

## 7. Tasks
### Code track
- [ ] **1.** Document what Blocked on means. *Blocked on §5.*
EOF
dsrun 1 "refuses a task whose title shadows its blocked-on marker" 0966

# Requiring every Open section to block a task would fire the moment a question is
# ANSWERED: settling §5 removes the marker, the section stays as the record, and every push
# after that goes red. The check runs the other way for exactly this reason.
dsdoc 0964-settled.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 5. Open — settled during delivery

| Question | Why it matters |
|---|---|
| Something | Because |

## 7. Tasks
### Code track
- [ ] **1.** Nothing waits on the question any more.
EOF
dsrun 0 "allows an open-questions section once nothing waits on it" 0964

dsdoc 0969-complete.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [x] **1.** Everything landed.
EOF
dsrun 1 "rejects a completed design that remains approved" 0969
dsrun 1 "review mode rejects an unclaimed complete design instead of inventing a finalization" --review 0969
rm -f "$DS/docs/design/0969-complete.md"

dsdoc 0967-wrongsection.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 6. Rollout — two tracks

Prose.

## 7. Tasks
### Code track
- [ ] **1.** Waiting on a section that asks nothing. *Blocked on §6.*
EOF
dsrun 1 "rejects a task blocked on a section that is not open questions" 0967

# Headings are read with fenced blocks stripped. Quoted markdown must not forge a section
# that does not exist, nor shadow one that does.
dsdoc 0972-fenceforge.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 1. Example

```md
## 5. Open — quoted, not a real section
```

## 7. Tasks
### Code track
- [ ] **1.** Queue wiring. *Blocked on §5.*
EOF
dsrun 1 "a section quoted inside a fence does not count as one" 0972

dsdoc 0973-fenceshadow.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 1. Example

```md
## 5. Rollout — quoted, not real
```

## 5. Open — must be settled before task 1

| Question | Why it matters |
|---|---|
| Something | Because |

## 7. Tasks
### Code track
- [ ] **1.** Queue wiring. *Blocked on §5.*
EOF
dsrun 0 "and a fenced heading does not shadow the real one" 0973

# `tr -dc '0-9'` mashed "§5 and §7" into "§57" and reported a section nobody wrote.
dsdoc 0974-twosections.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 5. Open — a

## 7. Open — b

## 8. Tasks
### Code track
- [ ] **1.** Waiting on two answers. *Blocked on §5 and §7.*
EOF
dsrun 1 "rejects a marker naming two sections" 0974

# Deliverability only has force at `approved`; a draft is allowed loose ends.
dsdoc 0968-draft.md <<'EOF'
---
type: design
status: draft
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] **1.** Waits on a task nobody has written yet. *Depends on task 99.*
EOF
dsrun 0 "leaves a draft alone" 0968

dsdoc 0965-badparse.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] 1. Missing the bold marker.
EOF
dsrun 1 "reports a doc that will not parse" 0965

# The no-argument, whole-tree form is the only one either caller uses, and every case above
# names a doc. This is the one that proves the loop advances past a failure and keeps count.
rm -rf "$DS" && mkdir -p "$DS/docs/design"
dsdoc 0970-badparse.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] 1. Missing the bold marker.
EOF
dsdoc 0971-ghostdep.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] **1.** Waits on a task nobody wrote. *Depends on task 99.*
EOF
dsrun 1 "checks every doc, not just the first"

rm -rf "$DS" && mkdir -p "$DS/docs/design"
dsrun 0 "says so when there are no design docs at all"

# The registry has to close in both directions, or /design can write a doc nothing points
# at — and then write a second one for the same initiative.
rm -rf "$DS" && mkdir -p "$DS/docs/design"
cat > "$DS/docs/roadmap.md" <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M1 — First

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | Claimed | — | [0980](./design/0980-a.md) |
| `finished` | Already delivered | — | [0982](./design/0982-finished.md) |

**Done when:** x.
EOF
dsdoc 0980-a.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] **1.** Something.
EOF
dsdoc 0982-finished.md <<'EOF'
---
type: design
status: frozen
delivered: M1
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [x] **1.** Something delivered.
EOF
dsrun 0 "passes when every approved doc is claimed and frozen state is valid"

sed -i.bak 's/^- \[ \] \*\*1\.\*\*/- [x] **1.**/' "$DS/docs/design/0980-a.md" \
  && rm -f "$DS/docs/design/0980-a.md.bak"
dsrun 0 "review mode admits a complete approved design with one roadmap owner" --review 0980
sed -i.bak 's/^- \[x\] \*\*1\.\*\*/- [ ] **1.**/' "$DS/docs/design/0980-a.md" \
  && rm -f "$DS/docs/design/0980-a.md.bak"

sed -i.bak 's/^delivered: M1$/delivered: M2/' "$DS/docs/design/0982-finished.md" \
  && rm -f "$DS/docs/design/0982-finished.md.bak"
dsrun 1 "rejects a frozen doc whose milestone disagrees with the roadmap" 0982
sed -i.bak 's/^delivered: M2$/delivered: M1/' "$DS/docs/design/0982-finished.md" \
  && rm -f "$DS/docs/design/0982-finished.md.bak"

sed -i.bak 's/^- \[x\] \*\*1\.\*\*/- [ ] **1.**/' "$DS/docs/design/0982-finished.md" \
  && rm -f "$DS/docs/design/0982-finished.md.bak"
dsrun 1 "rejects a frozen design with pending work" 0982
sed -i.bak 's/^- \[ \] \*\*1\.\*\*/- [x] **1.**/' "$DS/docs/design/0982-finished.md" \
  && rm -f "$DS/docs/design/0982-finished.md.bak"

printf '| `also-finished` | Duplicate owner | — | [0982](./design/0982-finished.md) |\n' \
  >> "$DS/docs/roadmap.md"
dsrun 1 "requires one unique roadmap owner for a frozen design" 0982
sed -i.bak '$d' "$DS/docs/roadmap.md" && rm -f "$DS/docs/roadmap.md.bak"

sed -i.bak '/`finished`/d' "$DS/docs/roadmap.md" && rm -f "$DS/docs/roadmap.md.bak"
sed -i.bak 's/^delivered: M1$/delivered: M2/' "$DS/docs/design/0982-finished.md" \
  && rm -f "$DS/docs/design/0982-finished.md.bak"
cat >> "$DS/docs/roadmap.md" <<'EOF'

### M2 — Shipped ✅ 2026-08-13

Delivered as [0982](./design/0982-finished.md).
EOF
dsrun 0 "accepts a frozen design after its initiative row collapses to a milestone pointer" 0982

sed -i.bak 's/^status: frozen$/status: draft/' "$DS/docs/design/0982-finished.md" \
  && rm -f "$DS/docs/design/0982-finished.md.bak"
dsrun 1 "rejects a collapsed pointer to a design that is not frozen" 0982
sed -i.bak 's/^status: draft$/status: frozen/' "$DS/docs/design/0982-finished.md" \
  && rm -f "$DS/docs/design/0982-finished.md.bak"

dsdoc 0981-orphan.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] **1.** Work no roadmap row points at.
EOF
dsrun 1 "rejects an approved doc no roadmap row names"
dsrun 0 "review mode admits an approved authored doc before claim" --review 0981

# Only `approved` is held to it. A draft has not claimed its row yet — 0001 was written by
# hand over several sittings — and an abandoned doc never will.
for st in draft abandoned; do
  sed -i.bak "s/^status: .*/status: $st/" "$DS/docs/design/0981-orphan.md" && rm -f "$DS/docs/design/0981-orphan.md.bak"
  dsrun 0 "leaves a '$st' doc unclaimed without complaint"
done

rm -f "$DS/docs/design/0981-orphan.md"
dsdoc 0980-b.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] **1.** A second doc claiming number 0980.
EOF
dsrun 1 "rejects two design docs sharing a number"
dsrun 1 "review mode also rejects a target number that resolves to two docs" --review 0980

# The dupe key has to be the four characters every consumer takes. Extracting "all the
# leading digits" would not collide here, while plan.sh would.
rm -f "$DS/docs/design/0980-b.md"
dsdoc 09800-b.md <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-08
---
## 7. Tasks
### Code track
- [ ] **1.** A five-digit name every stage would read as 0980.
EOF
dsrun 1 "rejects a doc whose name is not NNNN-<slug>.md"

# The orphan check leans on the roadmap. When the roadmap is the broken thing, say that,
# not "fill in the design column" of a row that is already correct.
rm -f "$DS/docs/design/09800-b.md"
printf '| `Bad` | Capitals are not a slug | — | — |\n' >> "$DS/docs/roadmap.md"
dsrun 1 "reports a broken roadmap as a broken roadmap"
notsaw "and does not send you to the wrong file" "named by no roadmap row"

rm -f "$DS/docs/design/0982-finished.md"
rm -f "$DS/docs/roadmap.md"
dsrun 0 "skips the claim check when there is no roadmap at all"

# A doc with no leading digits is excluded from the [0-9]* glob every loop uses, so it
# escaped every check and every skip line — invisible rather than merely colliding.
rm -rf "$DS" && mkdir -p "$DS/docs/design"
printf -- '---\ntype: design\nstatus: approved\nlast-verified: 2026-08-08\n---\n## 7. Tasks\n### Code track\n- [ ] **1.** x.\n' > "$DS/docs/design/ledger.md"
dsrun 1 "sees a design doc that is not numbered at all"
notsaw "rather than calling the tree empty" "no design docs yet"
rm -rf "$DS"

echo "add-initiative.sh"
AI=$(mktemp -d)
mkdir -p "$AI/docs/design" "$AI/core/scripts"
cp "$S/tree-digest.sh" "$AI/core/scripts/"
cat > "$AI/docs/roadmap.md" <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M0 — Spec ✅ 2026-01-01

### M1 — First

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | The first thing | — | — |

**Done when:** x.

### M2 — Second

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `beta` | The second thing | `alpha` | — |

**Done when:** y.
EOF
( cd "$AI" && git init -q -b main . && printf '.deliver/\n' > .gitignore \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm base )
airun() {  # airun <want-exit> <label> [args...]
  local want="$1" label="$2"; shift 2
  OUT=$(cd "$AI" && CLAUDE_PROJECT_DIR="$AI" "$S/add-initiative.sh" "$@" 2>&1); local got=$?
  if [ "$got" = "$want" ]; then ok "$label"; else bad "$label" "want exit $want, got $got"; fi
}
airun 0 "adds a row" M2 gamma alpha "A third thing"
grep -qF '| `gamma` | A third thing | `alpha` | — |' "$AI/docs/roadmap.md" \
  && ok "and the row is written" || bad "and the row is written" "not found"
# The row must join the existing table, not start a second one below a blank line.
grep -A1 -F '| `beta` |' "$AI/docs/roadmap.md" | grep -qF '| `gamma` |' \
  && ok "immediately after the last row of its milestone" \
  || bad "immediately after the last row of its milestone" "not adjacent"
OUT=$(cd "$AI" && CLAUDE_PROJECT_DIR="$AI" "$S/roadmap.sh" 2>&1)
case "$OUT" in *"$(printf 'gamma\037M2\037alpha\037')"*) ok "and the parser reads it back" ;;
  *) bad "and the parser reads it back" "not in roadmap.sh output" ;; esac

airun 0 "is idempotent for the same milestone" M2 gamma alpha "A third thing"
airun 3 "refuses to move an existing slug"     M1 gamma - "Somewhere else"
airun 1 "refuses a milestone that has shipped" M0 delta - "Too late"
airun 1 "refuses a dependency that resolves to nothing" M2 delta nowhere "x"
airun 1 "refuses a slug that is not kebab-case" M2 Delta - "x"
airun 1 "refuses a milestone that does not exist" M9 delta - "x"
airun 1 "refuses initiative text containing a pipe" M2 delta - "a | b"
airun 1 "requires all four arguments"           M2 delta

# "," and " " both word-split to nothing, so the member loop never ran for them. One landed
# a row with an empty dependency cell; the other landed one the parser refused outright.
for bad in "," ",," "alpha," ",alpha" " "; do
  airun 1 "refuses a dependency list of '$bad'" M2 delta "$bad" "x"
done
grep -q '`delta`' "$AI/docs/roadmap.md" && bad "and none of them wrote a row" "delta was written" \
  || ok "and none of them wrote a row"

# awk -v expands backslash escapes; a prose title containing \n split the row in two, and
# the old 1..2 window let it through.
airun 0 "keeps a backslash in the title on one line" M2 esc - 'Escape \n handling in the importer'
grep -qF '| `esc` | Escape \n handling in the importer | — | — |' "$AI/docs/roadmap.md" \
  && ok "verbatim, unexpanded" || bad "verbatim, unexpanded" "row not found intact"
grep -c '`esc`' "$AI/docs/roadmap.md" | grep -q '^1$' \
  && ok "as a single row" || bad "as a single row" "wrong count"
rm -rf "$AI"

echo "claim.sh"
CL=$(mktemp -d)
mkdir -p "$CL/docs/design"
copy_harness "$REAL_ROOT" "$CL" core || exit 1
cat > "$CL/docs/roadmap.md" <<'EOF'
---
type: plan
status: living
last-verified: 2026-08-08
---
### M1 — First

| Slug | Initiative | Depends | Design |
|---|---|---|---|
| `alpha` | Already covered | — | [0001](./design/0001-a.md) |
| `beta` | Not yet | `alpha` | — |

**Done when:** x.
EOF
for n in 0001-a 0002-b; do
  printf -- '---\ntype: design\nstatus: approved\nlast-verified: 2026-08-08\n---\n## 7. Tasks\n### Code track\n- [ ] **1.** x.\n' > "$CL/docs/design/$n.md"
done
( cd "$CL" && git init -q -b main . && printf '.deliver/\n' > .gitignore \
  && git add -A && git -c user.email=t@t -c user.name=t commit -qm base )
clrun() {  # clrun <want-exit> <label> [args...]
  local want="$1" label="$2"; shift 2
  OUT=$(cd "$CL" && CLAUDE_PROJECT_DIR="$CL" "$S/claim.sh" "$@" 2>&1); local got=$?
  if [ "$got" = "$want" ]; then ok "$label"; else bad "$label" "want exit $want, got $got"; fi
}
clmint() { mint_at "$CL"; }

mint_at "$CL" nd/unrelated/fixture
clrun 5 "refuses to claim a row with no review of this tree" beta 0002
saw "and says the review is what is missing"                 "no review of the current tree"
notsaw "and does not attribute unrelated evidence to this design" "changed after review"
rm -rf "$CL/.deliver/reviews/accepted/nd/unrelated"

clmint
clrun 0 "claims the row once a matching receipt exists" beta 0002
grep -qF '| `beta` | Not yet | `alpha` | [0002](./design/0002-b.md) |' "$CL/docs/roadmap.md" \
  && ok "and the cell is actually written" || bad "and the cell is actually written" "not found"
grep -c '^| `' "$CL/docs/roadmap.md" | grep -q '^2$' \
  && ok "with no other row touched" || bad "with no other row touched" "row count changed"
clrun 0 "is idempotent — re-running is a no-op" beta 0002

clrun 3 "refuses a row that already names another doc" alpha 0002
clrun 1 "rejects a slug the roadmap does not have"     nonsense 0002
clrun 1 "rejects a doc number with no file"            beta 0009
clrun 1 "rejects a number that is not four digits"     beta 2
rm -rf "$CL"



echo "task-window checkpoint (ADR-0045)"
if printf '{"continuation_window_tasks":2,"review_window_rounds":3}\n' \
  | ( . "$REAL_ROOT/core/task-ledger.sh"; task_policy_parse ) >/dev/null 2>&1; then
  ok "the policy parser accepts a positive integer"
else bad "the policy parser accepts a positive integer" "valid policy was refused"; fi
if printf '{"continuation_window_tasks":0,"review_window_rounds":3}\n' \
  | ( . "$REAL_ROOT/core/task-ledger.sh"; task_policy_parse ) >/dev/null 2>&1; then
  bad "the policy parser rejects a nonpositive window" "zero was accepted"
else ok "the policy parser rejects a nonpositive window"; fi
if printf '{"continuation_window_tasks":1,"review_window_rounds":3,"extra":1}\n' \
  | ( . "$REAL_ROOT/core/task-ledger.sh"; task_policy_parse ) >/dev/null 2>&1; then
  bad "the policy parser rejects an open-ended shape" "an extra field was accepted"
else ok "the policy parser rejects an open-ended shape"; fi
if printf '{"continuation_window_tasks":100000000000000000000.1,"review_window_rounds":3}\n' \
  | ( . "$REAL_ROOT/core/task-ledger.sh"; task_policy_parse ) >/dev/null 2>&1; then
  bad "the policy parser rejects a huge fractional literal" "a rounded fraction was accepted"
else ok "the policy parser rejects a huge fractional literal"; fi
if printf '{"continuation_window_tasks":1.00000000000000000000000000000000000001,"review_window_rounds":3}\n' \
  | ( . "$REAL_ROOT/core/task-ledger.sh"; task_policy_parse ) >/dev/null 2>&1; then
  bad "the policy parser rejects a tiny fractional tail" "a rounded fraction was accepted"
else ok "the policy parser rejects a tiny fractional tail"; fi
if printf '{"continuation_window_tasks":1,"continuation_window_tasks":2,"review_window_rounds":3}\n' \
  | ( . "$REAL_ROOT/core/task-ledger.sh"; task_policy_parse ) >/dev/null 2>&1; then
  bad "the policy parser rejects duplicate keys" "duplicate authority was accepted"
else ok "the policy parser rejects duplicate keys"; fi
OUT=$(printf '{"continuation_window_tasks":1e100,"review_window_rounds":3}\n' \
  | ( . "$REAL_ROOT/core/task-ledger.sh"; task_policy_parse ) 2>/dev/null)
[ "$OUT" = 1e100 ] && ok "the policy parser preserves an exponent-form integer snapshot" \
  || bad "the policy parser preserves an exponent-form integer snapshot" "got '$OUT'"
OUT=$(printf '{"continuation_window_tasks":9223372036854775808,"review_window_rounds":3}\n' \
  | ( . "$REAL_ROOT/core/task-ledger.sh"; task_policy_parse ) 2>/dev/null)
[ "$OUT" = 9223372036854775808 ] && ok "the policy parser preserves an integer beyond Bash range" \
  || bad "the policy parser preserves an integer beyond Bash range" "got '$OUT'"
TW=$(mktemp -d)
copy_harness "$REAL_ROOT" "$TW" core || exit 1
mkdir -p "$TW/docs/design"
cat > "$TW/docs/design/0950-window.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-21
---
## 7. Tasks
### Infra track
- [ ] **8.** Independent upstream task.
- [ ] **9.** External dependency.
### Code track
- [ ] **1.** First task.
- [ ] **2.** Lower blocked task. *Depends on task 9.*
- [ ] **3.** Later independent task.
- [ ] **4.** Follows the independent task. *Depends on task 3.*
- [ ] **5.** Last independent task.
EOF
cat > "$TW/docs/design/0952-other.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-21
---
## 7. Tasks
### Code track
- [ ] **1.** Task from another design.
EOF
printf 'docs/design/0952-other.md -diff\n' > "$TW/.gitattributes"
(
  cd "$TW" || exit 1
  git init -q -b main . && printf '.deliver/\n' > .gitignore
  git add -A && git -c user.email=t@t -c user.name=t commit -qm init
  git update-ref refs/remotes/origin/main HEAD
)
tw_run() {
  local want="$1" label="$2"; shift 2
  OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/$1" "${@:2}" 2>&1); local got=$?
  if [ "$got" = "$want" ]; then ok "$label"; else bad "$label" "want exit $want, got $got: $OUT"; fi
}
tw_tick() {
  local n="$1" title="$2"
  perl -pi -e "s/^- \[ \] \*\*$n\./- [x] **$n./" "$TW/docs/design/0950-window.md"
  ( cd "$TW" && git add -A && git -c user.email=t@t -c user.name=t \
      commit -qm "task $n: $title" -m "Review-Rounds: 1" )
}
tw_prompt() {
  codex_task_prompt "$TW" "$1"
}
tw_claude_prompt() {
  jq -cn '{hook_event_name:"PostToolUse",tool_name:"AskUserQuestion",
    tool_input:{questions:[{question:"Continue this run?",header:"Task window",multiSelect:false,
      options:[{label:"Continue with next task window",description:"Continue."},
        {label:"Open PR with completed tasks",description:"Open PR."},
        {label:"Stop without opening a PR",description:"Stop."}]}]},
    tool_response:{answers:{"Continue this run?":"Continue with next task window"}}}' \
    | CLAUDE_PROJECT_DIR="$TW" /bin/bash "$TW/core/hooks/task-grant.sh" >/dev/null 2>&1
}
tw_choices() {
  local incarnation
  incarnation=$(git -C "$TW" log --reverse --format=%H origin/main..HEAD --grep='^task [0-9].*: ' | head -1)
  printf '%s/.deliver/reviews/task-state/0950-code/%s' "$TW" "$incarnation"
}
tw_choice_count() {
  local dir
  dir=$(tw_choices)
  [ -d "$dir" ] || { printf '0'; return 0; }
  find "$dir" -type f -name '*.choice' | awk 'END {print NR+0}'
}
tw_mint() { mint_at "$TW"; }

tw_run 0 "refreshed main may discover a fresh run's first task" next.sh 0950 code
saw "and receives the canonical first runnable task" "1"
for INDEX_FLAG in assume-unchanged skip-worktree; do
  git -C "$TW" update-index "--$INDEX_FLAG" docs/design/0950-window.md
  tw_run 1 "next.sh refuses a $INDEX_FLAG design doc" next.sh 0950 code
  git -C "$TW" update-index "--no-$INDEX_FLAG" docs/design/0950-window.md
done
TW_REAL_GIT=$(command -v git)
mkdir "$TW/fail-status-bin"
{
  printf '#!/usr/bin/env bash\n'
  printf 'case "$*" in *" status --porcelain"*) exit 71 ;; esac\n'
  printf 'exec "%s" "$@"\n' "$TW_REAL_GIT"
} > "$TW/fail-status-bin/git"
chmod +x "$TW/fail-status-bin/git"
OUT=$(PATH="$TW/fail-status-bin:$PATH" CLAUDE_PROJECT_DIR="$TW" "$S/next.sh" 0950 code 2>&1); got=$?
[ "$got" = 1 ] && ok "first-task discovery fails closed when main cleanliness cannot be inspected" \
  || bad "first-task discovery fails closed when main cleanliness cannot be inspected" \
  "want exit 1, got $got: $OUT"
rm -rf "$TW/fail-status-bin"
( cd "$TW" && git checkout -q -b deliver/0950-code )
tw_prompt continue
[ ! -d "$(tw_choices)" ] && ok "a choice before any committed boundary records nothing" \
  || bad "a choice before any committed boundary records nothing" "a record appeared"

# `fresh` authority means "this delivery branch carries no task commit yet", which is only
# safe while HEAD is still the branch point. A non-task commit ahead of it must not be
# waved through as fresh — on either path into the gate.
(
  cd "$TW" || exit 1
  git branch pre-prefix-commit
  echo prefix > prefix.txt
  git add prefix.txt && git -c user.email=t@t -c user.name=t \
    commit -qm "chore: unrelated pre-task commit"
)
tw_mint
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/complete.sh" 0950 1 2>&1); got=$?
[ "$got" = 1 ] && ok "a pre-task commit revokes fresh authority on the pending path" \
  || bad "a pre-task commit revokes fresh authority on the pending path" "want exit 1, got $got: $OUT"
case "$OUT" in *"fresh task authority requires a newly created dirty delivery branch at refreshed trunk"*)
  ok "and says the branch has moved off its branch point" ;;
  *) bad "and says the branch has moved off its branch point" "$OUT" ;;
esac
perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' "$TW/docs/design/0950-window.md"
tw_mint
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/complete.sh" 0950 1 2>&1); got=$?
[ "$got" = 1 ] && ok "a pre-task commit revokes fresh authority on the recovery path too" \
  || bad "a pre-task commit revokes fresh authority on the recovery path too" "want exit 1, got $got: $OUT"
case "$OUT" in *"fresh task recovery requires a newly created dirty delivery branch at refreshed trunk"*)
  ok "and distinguishes the recovery refusal from the pending one" ;;
  *) bad "and distinguishes the recovery refusal from the pending one" "$OUT" ;;
esac
( cd "$TW" && git reset -q --hard pre-prefix-commit && git branch -D pre-prefix-commit >/dev/null )
perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' "$TW/docs/design/0950-window.md"
tw_run 1 "an uncommitted completion cannot become next-task authority" next.sh 0950 code
( cd "$TW" && git add -A && git -c user.email=t@t -c user.name=t \
    commit -qm "task 1: first task" -m "Review-Rounds: 1" )
CODEX_HOOK=1 tw_run 8 "the first committed task reaches a human checkpoint" next.sh 0950 code
if printf '%s\n' "$OUT" | grep -qFx continue \
  && printf '%s\n' "$OUT" | grep -qFx pr \
  && printf '%s\n' "$OUT" | grep -qFx stop; then
  ok "the task checkpoint includes the current host's executable choices"
else
  bad "the task checkpoint includes the current host's executable choices" "$OUT"
fi

# Runnable ordering is consequential authority shared by live discovery, completion,
# history, and both human-grant adapters. A failed sort must propagate through every public
# route; neither hook may turn the empty projection into a record.
mkdir "$TW/failing-sort"
TW_REAL_SORT=$(command -v sort)
{
  printf '#!/bin/sh\n'
  printf 'case "${1:-}" in -t*) exit 1 ;; esac\n'
  printf 'exec "%s" "$@"\n' "$TW_REAL_SORT"
} > "$TW/failing-sort/sort"
chmod +x "$TW/failing-sort/sort"
TW_OLD_PATH=$PATH
PATH="$TW/failing-sort:$PATH"
OUT=$( {
  TASK_US=$(printf '\037')
  . "$REAL_ROOT/core/task-ledger.sh"
  TSV=$(CLAUDE_PROJECT_DIR="$TW" "$S/plan.sh" 0950)
  task_first_runnable "$TSV" code ""
  exit $?
} 2>&1); got=$?
[ "$got" = 2 ] && ok "the shared runnable selector exposes a failed ordering producer" \
  || bad "the shared runnable selector exposes a failed ordering producer" "want exit 2, got $got: $OUT"
tw_run 1 "next.sh fails closed when runnable ordering is unreadable" next.sh 0950 code
tw_run 1 "task-status history fails closed when runnable ordering is unreadable" \
  task-status.sh 0950 code --history
mint_at "$TW" 0950-t3
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/complete.sh" 0950 3 2>&1); got=$?
[ "$got" = 5 ] && ok "complete.sh fails closed when runnable ordering is unreadable" \
  || bad "complete.sh fails closed when runnable ordering is unreadable" "want exit 5, got $got: $OUT"
case "$OUT" in *"cannot resolve the review key for the current delivery authority"*)
  ok "and completion names the unreadable review-key authority" ;;
  *) bad "and completion names the unreadable review-key authority" "$OUT" ;; esac
CHOICES_BEFORE=$(tw_choice_count)
tw_prompt continue
CHOICES_AFTER_CODEX=$(tw_choice_count)
tw_claude_prompt
CHOICES_AFTER_CLAUDE=$(tw_choice_count)
if [ "$CHOICES_BEFORE" = "$CHOICES_AFTER_CODEX" ] \
   && [ "$CHOICES_BEFORE" = "$CHOICES_AFTER_CLAUDE" ]; then
  ok "both human-grant projections record nothing when runnable ordering is unreadable"
else
  bad "both human-grant projections record nothing when runnable ordering is unreadable" \
    "counts $CHOICES_BEFORE -> $CHOICES_AFTER_CODEX -> $CHOICES_AFTER_CLAUDE"
fi
PATH=$TW_OLD_PATH
rm -rf "$TW/failing-sort"

# The canonical history manifest is a separate producer from runnable ordering. Failed
# first-parent enumeration must make --history fail, not render an authoritative boundary.
mkdir "$TW/failing-history"
TW_REAL_GIT=$(command -v git)
{
  printf '#!/bin/sh\n'
  printf 'case " $* " in *" rev-list --reverse --first-parent "*) exit 1 ;; esac\n'
  printf 'exec "%s" "$@"\n' "$TW_REAL_GIT"
} > "$TW/failing-history/git"
chmod +x "$TW/failing-history/git"
PATH="$TW/failing-history:$PATH"
tw_run 1 "task-status history fails closed when boundary history is unreadable" \
  task-status.sh 0950 code --history
PATH=$TW_OLD_PATH
rm -rf "$TW/failing-history"

# A gate may consume only the exact current-task projection whose complete authority
# traversal succeeded. Reusing a valid loaded manifest with a different projection must
# fail before the candidate or persisted choices are interpreted.
OUT=$( {
  TASK_US=$(printf '\037')
  . "$REAL_ROOT/core/lib.sh"
  . "$REAL_ROOT/core/task-ledger.sh"
  TSV=$(CLAUDE_PROJECT_DIR="$TW" "$S/plan.sh" 0950)
  BRANCH=$(git -C "$TW" branch --show-current)
  task_authority_load "$TW" "$BRANCH" 0950 "$TSV" || exit $?
  ALTERED_TSV="$TSV
mismatch"
  task_gate_evaluate "$TW" "$BRANCH" 0950 "$ALTERED_TSV" 3
} 2>&1); got=$?
[ "$got" = 1 ] && ok "core/README.md: the task gate rejects a different projection after authority validation" \
  || bad "core/README.md: the task gate rejects a different projection after authority validation" \
    "want exit 1, got $got: $OUT"
case "$OUT" in *"no matching validated authority context is loaded"*)
  ok "and the mismatched authority context is diagnosed explicitly" ;;
  *) bad "and the mismatched authority context is diagnosed explicitly" "$OUT" ;; esac

# The Codex hook reaches task_choice_add directly, rather than through next.sh. An index
# flag must therefore reject the human choice at that lower authority boundary too.
git -C "$TW" update-index --assume-unchanged docs/design/0950-window.md
tw_prompt continue
[ ! -d "$(tw_choices)" ] && ok "a Codex task choice cannot mint authority under assume-unchanged" \
  || bad "a Codex task choice cannot mint authority under assume-unchanged" "a record appeared"
git -C "$TW" update-index --no-assume-unchanged docs/design/0950-window.md

# complete.sh must refuse the exact same uncovered checkpoint next.sh just reported, on
# both the pending path and the interrupted-completion recovery path, with its own exit 8 —
# not merely a nonzero exit indistinguishable from "wrong task" (exit 1).
tw_mint
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/complete.sh" 0950 3 2>&1); got=$?
[ "$got" = 8 ] && ok "complete.sh exit-codes an uncovered checkpoint as 8 on the pending path" \
  || bad "complete.sh exit-codes an uncovered checkpoint as 8 on the pending path" "exit $got: $OUT"
perl -pi -e 's/^- \[ \] \*\*3\./- [x] **3./' "$TW/docs/design/0950-window.md"
tw_mint
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/complete.sh" 0950 3 2>&1); got=$?
[ "$got" = 8 ] && ok "complete.sh exit-codes an uncovered checkpoint as 8 on the recovery path too" \
  || bad "complete.sh exit-codes an uncovered checkpoint as 8 on the recovery path too" "exit $got: $OUT"
# Native design-runner tests cover fresh readiness on every review; no skill-prose assertion.

# A checkpoint answered while the doc still carries this task's uncommitted tick must not
# mint a grant: task_project_ids would read the dirty tree and permit the task after this
# one instead, wedging the run behind a "covered" status that names the wrong next task.
tw_prompt continue
[ ! -d "$(tw_choices)" ] && ok "a checkpoint choice over an uncommitted tick records nothing" \
  || bad "a checkpoint choice over an uncommitted tick records nothing" "a record appeared"
( cd "$TW" && git checkout -q -- docs/design/0950-window.md )
(
  cd "$TW" || exit 1
  git -c user.email=t@t -c user.name=t commit --amend -qm "chore: disguise task completion"
)
tw_run 1 "a tick hidden in a non-task commit cannot regain fresh authority" next.sh 0950 code
(
  cd "$TW" || exit 1
  git -c user.email=t@t -c user.name=t commit --amend -qm "task 1: first task" -m "Review-Rounds: 1"
)
(
  cd "$TW" || exit 1
  git checkout -q -b renamed-boundary
)
tw_run 1 "renaming a boundary onto a non-delivery branch cannot bypass the checkpoint" next.sh 0950 code
( cd "$TW" && git checkout -q deliver/0950-code && git branch -D renamed-boundary >/dev/null )
(
  cd "$TW" || exit 1
  git branch pre-cross-doc
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0952-other.md
  git add docs/design/0952-other.md && git -c user.email=t@t -c user.name=t \
    commit -qm "task 1: other design" -m "Review-Rounds: 1"
)
# The committed-history caller must propagate endpoint-parser failure rather than treating
# it as an empty cross-design transition set.
OUT=$(
  {
    git() {
      if [ "${3:-}" = show ] && [ "${4##*:}" = docs/design/0952-other.md ]; then
        printf '%s\n' '- [ ] malformed task endpoint'
        return 0
      fi
      command git "$@"
    }
    TASK_US=$(printf '\037')
    . "$REAL_ROOT/core/task-ledger.sh"
    TSV=$(CLAUDE_PROJECT_DIR="$TW" "$S/plan.sh" 0950)
    BASE=$(task_branch_point "$TW")
    task_commits_validate "$TW" 0950 code "$TSV" "$BASE"
  } 2>&1
); got=$?
[ "$got" = 1 ] && ok "committed endpoint-parser failure stops the live gate" \
  || bad "committed endpoint-parser failure stops the live gate" "want exit 1, got $got: $OUT"
tw_run 1 "a canonical task commit from another design is rejected live" next.sh 0950 code
(
  cd "$TW" || exit 1
  git -c user.email=t@t -c user.name=t commit --amend -qm "review: hide another design's task"
)
tw_run 1 "a review-hidden task from another design is also rejected live" next.sh 0950 code
(
  cd "$TW" || exit 1
  git branch -m bad-cross-doc
  git checkout -q pre-cross-doc
  git branch -m deliver/0950-code
  git branch -D bad-cross-doc >/dev/null
)
# A failed primary-design endpoint read must stop validation rather than erase its state.
OUT=$(
  {
    TARGET_SHA=$(command git -C "$TW" rev-parse HEAD)
    git() {
      if [ "${3:-}" = show ] && [ "${4:-}" = "$TARGET_SHA:docs/design/0950-window.md" ]; then return 1; fi
      command git "$@"
    }
    TASK_US=$(printf '\037')
    . "$REAL_ROOT/core/task-ledger.sh"
    TSV=$(CLAUDE_PROJECT_DIR="$TW" "$S/plan.sh" 0950)
    BASE=$(task_branch_point "$TW")
    task_commits_validate "$TW" 0950 code "$TSV" "$BASE"
  } 2>&1
); got=$?
[ "$got" = 1 ] && ok "a primary-design endpoint read failure stops committed-history validation" \
  || bad "a primary-design endpoint read failure stops committed-history validation" \
  "want exit 1, got $got: $OUT"
# Commit and changed-path enumeration are authority reads too. A failed loop producer must
# not look like a successfully validated empty history.
for FAILURE in commits parents paths; do
  OUT=$(
    {
      git() {
        if [ "$FAILURE" = commits ] && [ "${3:-}" = rev-list ] && [ "${4:-}" = --reverse ]; then return 1; fi
        if [ "$FAILURE" = parents ] && [ "${3:-}" = rev-list ] && [ "${4:-}" = --parents ]; then return 1; fi
        if [ "$FAILURE" = paths ] && [ "${3:-}" = diff ] && [ "${4:-}" = --name-only ]; then return 1; fi
        command git "$@"
      }
      TASK_US=$(printf '\037')
      . "$REAL_ROOT/core/task-ledger.sh"
      TSV=$(CLAUDE_PROJECT_DIR="$TW" "$S/plan.sh" 0950)
      BASE=$(task_branch_point "$TW")
      task_commits_validate "$TW" 0950 code "$TSV" "$BASE"
    } 2>&1
  ); got=$?
  [ "$got" = 1 ] && ok "$FAILURE enumeration failure stops committed-history validation" \
    || bad "$FAILURE enumeration failure stops committed-history validation" \
    "want exit 1, got $got: $OUT"
done
# The per-endpoint reviewed-authority lookup added for refreshed-main history is itself an
# authority read. If its merge-base cannot be resolved, the validator must not fall back to
# the latest moving base or treat the commit as having no reviewed tasks.
OUT=$(
  {
    BASE=$(command git -C "$TW" merge-base origin/main HEAD)
    git() {
      if [ "${3:-}" = merge-base ] && [ "${4:-}" != --is-ancestor ]; then return 1; fi
      command git "$@"
    }
    TASK_US=$(printf '\037')
    . "$REAL_ROOT/core/task-ledger.sh"
    TSV=$(CLAUDE_PROJECT_DIR="$TW" "$S/plan.sh" 0950)
    task_commits_validate "$TW" 0950 code "$TSV" "$BASE"
  } 2>&1
); got=$?
[ "$got" = 1 ] && ok "reviewed-authority resolution failure stops committed-history validation" \
  || bad "reviewed-authority resolution failure stops committed-history validation" \
  "want exit 1, got $got: $OUT"
case "$OUT" in *"cannot resolve reviewed authority"*)
  ok "and the validator names the unreadable historical authority" ;;
  *) bad "and the validator names the unreadable historical authority" "$OUT" ;;
esac
# A task cannot disappear in one allowed review commit and reappear done in another. Parsed
# endpoint state must reject the first identity break, and the outside verifier must surface
# the same failure even though the aggregate diff looks like an ordinary completed task.
(
  cd "$TW" || exit 1
  git branch pre-split-task
  perl -0pi -e 's/^- \[ \] \*\*3\.\*\* Later independent task\.\n//m' docs/design/0950-window.md
  git add docs/design/0950-window.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: temporarily remove task 3"
  perl -0pi -e 's/^- \[ \] \*\*4\./- [x] **3.** Later independent task.\n- [ ] **4./m' \
    docs/design/0950-window.md
  git add docs/design/0950-window.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: restore task 3 as done"
)
tw_run 1 "a task tick split across two review commits fails the live gate" next.sh 0950 code
OUT=$(cd "$TW" && CLAUDE_PROJECT_DIR="$TW" GITHUB_HEAD_REF=deliver/0950-code \
  "$S/verify-delivery.sh" origin/main 2>&1); got=$?
[ "$got" = 1 ] && ok "CI rejects a task tick split across two review commits" \
  || bad "CI rejects a task tick split across two review commits" "want exit 1, got $got: $OUT"
(
  cd "$TW" || exit 1
  git branch -m bad-split-task
  git checkout -q pre-split-task
  git branch -m deliver/0950-code
  git branch -D bad-split-task >/dev/null
)
# A routed identity is permitted only as pending history. Completing it and reopening it
# before the final tree cannot hide the unauthorized task behind a later reviewed tick.
(
  cd "$TW" || exit 1
  git branch pre-routed-state
  printf '%s\n' '- [ ] **99.** Routed pending follow-up.' >> docs/design/0950-window.md
  git add docs/design/0950-window.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: route task 99"
  perl -pi -e 's/^- \[ \] \*\*99\./- [x] **99./' docs/design/0950-window.md
  echo unauthorized > unauthorized-task.txt
  git add docs/design/0950-window.md unauthorized-task.txt \
    && git -c user.email=t@t -c user.name=t commit -qm "task 99: unauthorized routed work" \
      -m "Review-Rounds: 1"
  perl -pi -e 's/^- \[x\] \*\*99\./- [ ] **99./' docs/design/0950-window.md
  git add docs/design/0950-window.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: reopen task 99"
)
tw_tick 3 "later independent task"
tw_run 1 "a routed task completed and reopened across commits fails the live gate" next.sh 0950 code
OUT=$(cd "$TW" && CLAUDE_PROJECT_DIR="$TW" GITHUB_HEAD_REF=deliver/0950-code \
  "$S/verify-delivery.sh" origin/main 2>&1); got=$?
[ "$got" = 1 ] && ok "CI rejects a routed task completed and reopened across commits" \
  || bad "CI rejects a routed task completed and reopened across commits" \
  "want exit 1, got $got: $OUT"
case "$OUT" in *"unreviewed task 99 is removed or completed"*)
  ok "and CI reports the unauthorized routed-task transition" ;;
  *) bad "and CI reports the unauthorized routed-task transition" "$OUT" ;;
esac
(
  cd "$TW" || exit 1
  git branch -m bad-routed-state
  git checkout -q pre-routed-state
  git branch -m deliver/0950-code
  git branch -D bad-routed-state >/dev/null
)
(
  cd "$TW" || exit 1
  git branch pre-cross-track
  perl -pi -e 's/^- \[ \] \*\*9\./- [x] **9./' docs/design/0950-window.md
  git add -A && git -c user.email=t@t -c user.name=t \
    commit -qm "task 9: cross-track task" -m "Review-Rounds: 1"
)
tw_run 1 "a canonical task commit from another track is rejected live" next.sh 0950 code
(
  cd "$TW" || exit 1
  git branch -m cross-track-task
  git checkout -q pre-cross-track
  git branch -m deliver/0950-code
  git branch -D cross-track-task >/dev/null
)
(
  cd "$TW" || exit 1
  git branch pre-owner-move
  perl -0pi -e 's/- \[ \] \*\*9\.\*\* External dependency\.\n//; s/### Code track\n/### Code track\n- [x] **9.** External dependency.\n/' docs/design/0950-window.md
  git add docs/design/0950-window.md && git -c user.email=t@t -c user.name=t \
    commit -qm "task 9: reassign and complete" -m "Review-Rounds: 1"
)
tw_run 1 "moving a task into the branch track cannot change its reviewed owner" next.sh 0950 code
(
  cd "$TW" || exit 1
  git branch -m bad-owner-move
  git checkout -q pre-owner-move
  git branch -m deliver/0950-code
  git branch -D bad-owner-move >/dev/null
)
(
  cd "$TW" || exit 1
  git branch -m deliver/0950
)
tw_run 1 "a multi-track delivery branch without its track suffix is rejected live" next.sh 0950 code
( cd "$TW" && git branch -m deliver/0950-code )
(
  cd "$TW" || exit 1
  git branch -m deliver/0950-
)
tw_run 1 "the live gate rejects a trailing-hyphen delivery branch" next.sh 0950 code
( cd "$TW" && git branch -m deliver/0950-code )
OUT=$(
  TASK_US=$(printf '\037')
  . "$REAL_ROOT/core/task-ledger.sh"
  TSV=$(CLAUDE_PROJECT_DIR="$TW" "$S/plan.sh" 0950)
  task_project_ids "$TSV" code 1e100
)
[ "$OUT" = 3,4,5 ] && ok "a huge valid window projects only the finite runnable task set" \
  || bad "a huge valid window projects only the finite runnable task set" "got '$OUT'"

cp "$TW/core/delivery-policy.json" "$TW/policy.good"
rm "$TW/core/delivery-policy.json"
tw_prompt continue
[ ! -d "$(tw_choices)" ] && ok "a missing policy cannot mint a continue record" \
  || bad "a missing policy cannot mint a continue record" "a record appeared"
printf '{"continuation_window_tasks":0,"review_window_rounds":3}\n' > "$TW/core/delivery-policy.json"
tw_prompt continue
[ ! -d "$(tw_choices)" ] && ok "a nonpositive policy cannot mint a continue record" \
  || bad "a nonpositive policy cannot mint a continue record" "a record appeared"
printf '{"continuation_window_tasks":1,"review_window_rounds":3,"extra":1}\n' > "$TW/core/delivery-policy.json"
tw_prompt continue
[ ! -d "$(tw_choices)" ] && ok "an open-ended policy shape fails closed" \
  || bad "an open-ended policy shape fails closed" "a record appeared"
mv "$TW/policy.good" "$TW/core/delivery-policy.json"

(
  cd "$TW" || exit 1
  printf '{"continuation_window_tasks":1e100,"review_window_rounds":3}\n' > core/delivery-policy.json
  git add core/delivery-policy.json && git -c user.email=t@t -c user.name=t \
    commit -qm "review: inflate policy only on delivery branch"
)
tw_prompt continue
[ ! -d "$(tw_choices)" ] && ok "an unmerged branch-local policy cannot enlarge a grant" \
  || bad "an unmerged branch-local policy cannot enlarge a grant" "a record appeared"
(
  cd "$TW" || exit 1
  git -c user.email=t@t -c user.name=t revert --no-edit HEAD >/dev/null
  git -c user.email=t@t -c user.name=t commit --amend -qm "review: restore reviewed policy"
)

(
  cd "$TW" || exit 1
  git checkout -q -b reviewed-policy origin/main
  printf '{"continuation_window_tasks":2,"review_window_rounds":3}\n' > core/delivery-policy.json
  git add core/delivery-policy.json && git -c user.email=t@t -c user.name=t \
    commit -qm "review: set task-window policy fixture"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q deliver/0950-code
  git -c user.email=t@t -c user.name=t merge -q --no-edit reviewed-policy
)
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/task-status.sh" 0950 code 2>&1)
case "$OUT" in *"policy-window: 2"*"continue-would-permit: 3,4"*)
  ok "the checkpoint shows the reviewed policy and exact projected task IDs" ;;
  *) bad "the checkpoint shows the reviewed policy and exact projected task IDs" "$OUT" ;;
esac
# Ordering metadata for reviewed tasks is branch-point authority. Model-writable prose may
# describe work, but cannot block the canonical task or erase another task's dependency to
# steer checkpoint/status projection.
perl -0pi -e 's/(- \[ \] \*\*3\.\*\* Later independent task\.)/$1\n  *Blocked on §2.*/; s/(\*\*4\.\*\* Follows the independent task\.) \*Depends on task 3\.\*/$1/' \
  "$TW/docs/design/0950-window.md"
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/task-status.sh" 0950 code 2>&1)
case "$OUT" in *"continue-would-permit: 3,4"*)
  ok "branch-local dependency and blocking prose cannot steer task-status projection" ;;
  *) bad "branch-local dependency and blocking prose cannot steer task-status projection" "$OUT" ;;
esac
tw_run 8 "branch-local ordering prose cannot steer the live checkpoint candidate" next.sh 0950 code
( cd "$TW" && git checkout -q -- docs/design/0950-window.md )
tw_prompt continue
CHOICE_DIR=$(tw_choices)
if grep -q '^permitted-tasks: 3,4$' "$CHOICE_DIR/000001.choice"; then
  ok "a window repeatedly applies the canonical runnable selection"
else bad "a window repeatedly applies the canonical runnable selection" "expected exact tasks 3,4"; fi
if grep -q '^choice-version: 4$' "$CHOICE_DIR/000001.choice" \
   && grep -q '^policy-source: default$' "$CHOICE_DIR/000001.choice" \
   && grep -Eq '^policy-blob: [0-9a-f]{40,64}$' "$CHOICE_DIR/000001.choice" \
   && grep -Eq '^policy-sha256: [0-9a-f]{64}$' "$CHOICE_DIR/000001.choice" \
   && grep -Eq '^tree: [0-9a-f]{16}$' "$CHOICE_DIR/000001.choice" \
   && grep -Eq '^head: [0-9a-f]{40,64}$' "$CHOICE_DIR/000001.choice" \
   && grep -Eq '^record-sha256: [0-9a-f]{64}$' "$CHOICE_DIR/000001.choice"; then
  ok "the task choice binds its policy, exact tree, HEAD, and canonical record bytes"
else bad "the task choice binds its policy, exact tree, HEAD, and canonical record bytes" "v4 bindings missing"; fi

# The writer publishes by hard-linking its provisional dot-file, then unlinks that provisional
# name. A reader in between those operations, or after an interrupted unlink, must see only the
# canonical visible record.
ln "$CHOICE_DIR/000001.choice" "$CHOICE_DIR/.choice-1.123"
tw_run 0 "a task-choice provisional file is inert during or after atomic publication" next.sh 0950 code
rm "$CHOICE_DIR/.choice-1.123"

cp "$CHOICE_DIR/000001.choice" "$TW/choice.good"
perl -pi -e 's/^policy-blob: .*/policy-blob: malformed/' "$CHOICE_DIR/000001.choice"
tw_run 1 "a malformed task-choice policy snapshot fails the exact series closed" next.sh 0950 code
mv "$TW/choice.good" "$CHOICE_DIR/000001.choice"

cp "$CHOICE_DIR/000001.choice" "$TW/choice.good"
perl -pi -e 's/^tree: .*/tree: malformed/' "$CHOICE_DIR/000001.choice"
tw_run 1 "a malformed task-choice tree digest fails the exact series closed" next.sh 0950 code
mv "$TW/choice.good" "$CHOICE_DIR/000001.choice"

cp "$CHOICE_DIR/000001.choice" "$TW/choice.good"
perl -pi -e 's/^head: ([0-9a-f]{8}).*/head: $1/' "$CHOICE_DIR/000001.choice"
tw_run 1 "an abbreviated task-choice HEAD is not a full binding" next.sh 0950 code
mv "$TW/choice.good" "$CHOICE_DIR/000001.choice"

cp "$CHOICE_DIR/000001.choice" "$TW/choice.good"
perl -pi -e 's/^chosen-by: .*/chosen-by: maybe a human/' "$CHOICE_DIR/000001.choice"
tw_run 1 "malformed task-choice provenance fails the exact series closed" next.sh 0950 code
mv "$TW/choice.good" "$CHOICE_DIR/000001.choice"

cp "$CHOICE_DIR/000001.choice" "$TW/choice.good"
perl -pi -e 's/^permitted-tasks: .*/permitted-tasks: 3,4,5/' "$CHOICE_DIR/000001.choice"
tw_run 1 "widening same-track coverage without the host checksum fails closed" next.sh 0950 code
mv "$TW/choice.good" "$CHOICE_DIR/000001.choice"

cp "$CHOICE_DIR/000001.choice" "$CHOICE_DIR/1.choice"
tw_run 1 "a noncanonical task-choice filename fails the exact series closed" next.sh 0950 code
rm "$CHOICE_DIR/1.choice"
ln -s 000001.choice "$CHOICE_DIR/000002.choice"
tw_run 1 "a symlinked task-choice record fails the exact series closed" next.sh 0950 code
rm "$CHOICE_DIR/000002.choice"

# The canonical-order guard runs before the window is even consulted: completing an
# independent later task directly is refused for being out of order, not for being
# ungranted — window coverage is exercised separately by the exit-8 cases above.
tw_mint
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/complete.sh" 0950 5 2>&1); got=$?
[ "$got" = 1 ] && ok "complete.sh refuses a task the gate did not select, before the window is consulted" \
  || bad "complete.sh refuses a task the gate did not select, before the window is consulted" "want exit 1, got $got: $OUT"

# The pending completion path consumes the same trusted task record. Blocking task 3 and
# removing task 4's dependency in the working tree must not turn covered task 4 into the
# canonical candidate.
perl -0pi -e 's/(- \[ \] \*\*3\.\*\* Later independent task\.)/$1\n  *Blocked on §2.*/; s/(\*\*4\.\*\* Follows the independent task\.) \*Depends on task 3\.\*/$1/' \
  "$TW/docs/design/0950-window.md"
tw_mint
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/complete.sh" 0950 4 2>&1); got=$?
[ "$got" = 1 ] && ok "pending completion takes ordering metadata from the branch point" \
  || bad "pending completion takes ordering metadata from the branch point" "want exit 1, got $got: $OUT"
( cd "$TW" && git checkout -q -- docs/design/0950-window.md )

# Interrupted-completion recovery (already-done-on-disk, uncommitted) must not let a
# granted task stand in for whichever task the gate actually selects: task 4 depends on
# task 3 at the branch point. The working tree tries both sides of the known steering family:
# it blocks task 3 and erases task 4's dependency before ticking 4.
perl -0pi -e 's/(- \[ \] \*\*3\.\*\* Later independent task\.)/$1\n  *Blocked on §2.*/; s/(\*\*4\.\*\* Follows the independent task\.) \*Depends on task 3\.\*/$1/; s/^- \[ \] \*\*4\./- [x] **4./m' \
  "$TW/docs/design/0950-window.md"
# A failed recovery-boundary inspection is not the ordinary "no recovery transition" case.
# Round attribution must stop instead of falling through to the next runnable task's key.
REAL_SED=$(command -v sed)
sed() {
  local input
  input=$(cat)
  case "$input" in
    *"Follows the independent task"*) return 1 ;;
  esac
  printf '%s\n' "$input" | "$REAL_SED" "$@"
}
OUT=$(
  {
    . "$REAL_ROOT/core/round-ledger.sh"
    round_current_key "$TW" deliver/0950-code
  } 2>&1
); got=$?
unset -f sed
[ "$got" = 2 ] && ok "recovery inspection failure has a distinct authority-error status" \
  || bad "recovery inspection failure stops review-round attribution" \
  "want exit 2, got $got: $OUT"

# The public round-status route must preserve a failed recovery-owner producer all the way
# through round_current_key and round_key_for. It may not mint an unrelated nd/<branch>/<HEAD>
# identity after the task-key authority read failed.
TW_REAL_AWK=$(command -v awk)
mkdir "$TW/fail-owner-bin"
{
  printf '#!/usr/bin/env bash\n'
  printf 'for arg in "$@"; do [ "$arg" = '\''$1==n {print $3; exit}'\'' ] && exit 71; done\n'
  printf 'exec "%s" "$@"\n' "$TW_REAL_AWK"
} > "$TW/fail-owner-bin/awk"
chmod +x "$TW/fail-owner-bin/awk"
OUT=$(PATH="$TW/fail-owner-bin:$PATH" CLAUDE_PROJECT_DIR="$TW" "$S/round-status.sh" 2>&1); got=$?
[ "$got" = 1 ] && ok "round-status fails closed when recovery ownership cannot be inspected" \
  || bad "round-status fails closed when recovery ownership cannot be inspected" \
  "want exit 1, got $got: $OUT"
case "$OUT" in *"could not resolve a review-round window for deliver/0950-code"*)
  ok "and the public route does not fall back to a non-delivery key" ;;
  *) bad "and the public route does not fall back to a non-delivery key" "$OUT" ;; esac
rm -rf "$TW/fail-owner-bin"

OUT=$(
  . "$REAL_ROOT/core/round-ledger.sh"
  round_current_key() { return 2; }
  round_key_for "$TW" deliver/0950-code
); got=$?
[ "$got" = 1 ] && [ -z "$OUT" ] \
  && ok "round-key selection propagates a current-key authority failure" \
  || bad "round-key selection propagates a current-key authority failure" \
  "want exit 1 with no fallback key, got $got: $OUT"
tw_mint
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/complete.sh" 0950 4 2>&1); got=$?
[ "$got" -ne 0 ] && ok "recovery still requires the ticked task to be the canonical first runnable task" \
  || bad "recovery still requires the ticked task to be the canonical first runnable task" \
  "task 4 recovered ahead of task 3"
( cd "$TW" && git checkout -q -- docs/design/0950-window.md )

# The same interrupted transition on the canonical task recovers cleanly: this is the
# idempotent path an interrupted completion run resumes into. Renew the review window first;
# the task-window assertions below are intentionally independent of the round ceiling.
( . "$REAL_ROOT/core/round-ledger.sh" \
  && round_grant_add "$TW" "0950-t3" "$(CLAUDE_PROJECT_DIR="$TW" "$S/tree-digest.sh")" 3 3 "$ROUND_GRANT_LABEL" )
perl -0pi -e 's/^- \[ \] \*\*3\./- [x] **3./m; s/Follows the independent task\./Follows the independent task, reworded during recovery./' \
  "$TW/docs/design/0950-window.md"
OUT=$(
  . "$REAL_ROOT/core/round-ledger.sh"
  round_current_key "$TW" deliver/0950-code
); got=$?
[ "$got" = 0 ] && [ "$OUT" = 0950-t3 ] \
  && ok "wording another pending task keeps recovery review attribution on the interrupted task" \
  || bad "wording another pending task keeps recovery review attribution on the interrupted task" \
  "want 0950-t3, got exit $got: $OUT"
tw_mint
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/complete.sh" 0950 3 2>&1); got=$?
[ "$got" = 0 ] && ok "recovery admits the canonical tick beside another task's wording edit" \
  || bad "recovery admits the canonical first runnable task's interrupted tick" "exit $got: $OUT"
( cd "$TW" && git checkout -q -- docs/design/0950-window.md )

# Recovery is scoped to the single interrupted transition it claims to be. An uncommitted
# edit that also ticks a second task is a different edit, and is refused here rather than
# left to the commit-time validator downstream.
perl -pi -e 's/^- \[ \] \*\*3\./- [x] **3./; s/^- \[ \] \*\*5\./- [x] **5./' \
  "$TW/docs/design/0950-window.md"
tw_mint
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/complete.sh" 0950 3 2>&1); got=$?
[ "$got" = 1 ] && ok "recovery refuses an uncommitted edit that ticks a second task" \
  || bad "recovery refuses an uncommitted edit that ticks a second task" "want exit 1, got $got: $OUT"
( cd "$TW" && git checkout -q -- docs/design/0950-window.md )

# A normal delivery sync changes merge-base. It must not change the branch incarnation or
# hide the human authority/history already recorded for this still-unmerged task sequence.
OLD_CHOICE_DIR="$CHOICE_DIR"
(
  cd "$TW" || exit 1
  git checkout -q -b upstream-sync origin/main
  perl -pi -e 's/^- \[ \] \*\*8\./- [x] **8./' docs/design/0950-window.md
  perl -0pi -e 's/(- \[ \] \*\*9\.\*\* External dependency\.\n)/$1- [ ] **10.** Pending task routed on refreshed trunk.\n/' \
    docs/design/0950-window.md
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0952-other.md
  echo sync > upstream.txt
  git add docs/design/0950-window.md docs/design/0952-other.md upstream.txt \
    && git -c user.email=t@t -c user.name=t commit -qm "task 8: upstream infra task" -m "Review-Rounds: 1"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q deliver/0950-code
  git branch pre-reset-merge
  git -c user.email=t@t -c user.name=t merge -q --no-commit upstream-sync
  perl -pi -e 's/^- \[x\] \*\*1\./- [ ] **1./' docs/design/0950-window.md
  git add docs/design/0950-window.md && git -c user.email=t@t -c user.name=t \
    commit -qm "Merge refreshed main with a bad task reset"
)
tw_run 1 "a main merge cannot reset a branch-completed task to trunk's pending state" next.sh 0950 code
(
  cd "$TW" || exit 1
  git branch -m bad-reset-merge
  git checkout -q pre-reset-merge
  git branch -m deliver/0950-code
  git branch -D bad-reset-merge >/dev/null
  # A branch-local routed identity cannot be laundered into task authority merely because
  # refreshed trunk later introduces the same id. Exact inheritance requires the branch
  # parent still to match the common ancestor for that identity.
  git branch pre-authority-collision
  perl -0pi -e 's/(- \[ \] \*\*9\.\*\* External dependency\.\n)/$1- [ ] **10.** Pending task routed on refreshed trunk.\n/' \
    docs/design/0950-window.md
  git add docs/design/0950-window.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: preempt trunk task identity"
  git -c user.email=t@t -c user.name=t merge -q --no-edit upstream-sync
)
tw_run 1 "a branch-local task id cannot collide into refreshed-trunk authority" next.sh 0950 code
OUT=$(cd "$TW" && CLAUDE_PROJECT_DIR="$TW" GITHUB_HEAD_REF=deliver/0950-code \
  "$S/verify-delivery.sh" origin/main 2>&1); got=$?
[ "$got" = 1 ] && ok "CI rejects a branch-local identity collision with refreshed trunk" \
  || bad "CI rejects a branch-local identity collision with refreshed trunk" \
  "want exit 1, got $got: $OUT"
case "$OUT" in *"reviewed task 10 is introduced outside an exact trunk merge"*)
  ok "and CI reports the inexact authority introduction" ;;
  *) bad "and CI reports the inexact authority introduction" "$OUT" ;;
esac
(
  cd "$TW" || exit 1
  git branch -m bad-authority-collision
  git checkout -q pre-authority-collision
  git branch -m deliver/0950-code
  git branch -D bad-authority-collision >/dev/null
  git -c user.email=t@t -c user.name=t merge -q --no-edit upstream-sync
)
CHOICE_DIR=$(tw_choices)
[ "$CHOICE_DIR" = "$OLD_CHOICE_DIR" ] \
  && ok "merging refreshed main preserves the delivery incarnation" \
  || bad "merging refreshed main preserves the delivery incarnation" "ledger path changed"

# Once origin/main exists it is reviewed authority. A failed merge-base lookup cannot fall
# back to the deliberately stale local main left behind by this refreshed-authority merge.
mkdir "$TW/fail-remote-branch-point"
TW_REAL_GIT=$(command -v git)
{
  printf '#!/usr/bin/env bash\n'
  printf 'case " $* " in *" merge-base origin/main HEAD "*) exit 71 ;; esac\n'
  printf 'exec "%s" "$@"\n' "$TW_REAL_GIT"
} > "$TW/fail-remote-branch-point/git"
chmod +x "$TW/fail-remote-branch-point/git"
OUT=$(PATH="$TW/fail-remote-branch-point:$PATH" CLAUDE_PROJECT_DIR="$TW" \
  "$S/next.sh" 0950 code 2>&1); got=$?
[ "$got" = 1 ] && ok "refreshed task discovery fails closed when origin/main branch-point authority is unreadable" \
  || bad "refreshed task discovery fails closed when origin/main branch-point authority is unreadable" \
  "want exit 1, got $got: $OUT"
case "$OUT" in 3*"Must reach the new incarnation's checkpoint"*)
  bad "and stale local main cannot replace failed remote authority" "$OUT" ;;
  *) ok "and stale local main cannot replace failed remote authority" ;; esac

{
  printf '#!/usr/bin/env bash\n'
  printf 'case " $* " in *" show-ref --verify --quiet refs/remotes/origin/main "*) exit 71 ;; esac\n'
  printf 'exec "%s" "$@"\n' "$TW_REAL_GIT"
} > "$TW/fail-remote-branch-point/git"
OUT=$(PATH="$TW/fail-remote-branch-point:$PATH" CLAUDE_PROJECT_DIR="$TW" \
  "$S/next.sh" 0950 code 2>&1); got=$?
[ "$got" = 1 ] && ok "refreshed task discovery fails closed when remote-ref existence cannot be inspected" \
  || bad "refreshed task discovery fails closed when remote-ref existence cannot be inspected" \
  "want exit 1, got $got: $OUT"
case "$OUT" in 3*"Must reach the new incarnation's checkpoint"*)
  bad "and an existence-probe error cannot masquerade as confirmed remote absence" "$OUT" ;;
  *) ok "and an existence-probe error cannot masquerade as confirmed remote absence" ;; esac

# Git before 2.43 rejects `show-ref --exists`. Task authority must remain available on that
# established baseline without weakening the missing-only fallback contract above.
{
  printf '#!/usr/bin/env bash\n'
  printf 'case " $* " in *" show-ref --exists "*) exit 129 ;; esac\n'
  printf 'exec "%s" "$@"\n' "$TW_REAL_GIT"
} > "$TW/fail-remote-branch-point/git"
OUT=$(PATH="$TW/fail-remote-branch-point:$PATH" CLAUDE_PROJECT_DIR="$TW" \
  "$S/next.sh" 0950 code 2>&1); got=$?
[ "$got" = 0 ] && ok "refreshed task discovery supports Git versions without show-ref --exists" \
  || bad "refreshed task discovery supports Git versions without show-ref --exists" \
  "want exit 0, got $got: $OUT"
rm -rf "$TW/fail-remote-branch-point"

TW_REMOTE_MAIN=$(git -C "$TW" rev-parse refs/remotes/origin/main)
git -C "$TW" update-ref -d refs/remotes/origin/main
git -C "$TW" symbolic-ref refs/remotes/origin/main refs/remotes/origin/missing-authority
tw_run 1 "a non-resolving symbolic origin/main cannot masquerade as remote absence" next.sh 0950 code
git -C "$TW" symbolic-ref --delete refs/remotes/origin/main
git -C "$TW" update-ref refs/remotes/origin/main "$TW_REMOTE_MAIN"

tw_run 0 "an inherited other-track task preserves this branch's continue admission" next.sh 0950 code
OUT=$(cd "$TW" && CLAUDE_PROJECT_DIR="$TW" GITHUB_HEAD_REF=deliver/0950-code \
  "$S/verify-delivery.sh" origin/main 2>&1); got=$?
[ "$got" = 0 ] && ok "a refreshed-main pending task is not required in earlier branch commits" \
  || bad "a refreshed-main pending task is not required in earlier branch commits" \
  "want exit 0, got $got: $OUT"
case "$OUT" in *"every task transition belongs to its matching task commit"*)
  ok "and CI accepts the exact pending-task inheritance" ;;
  *) bad "and CI accepts the exact pending-task inheritance" "$OUT" ;;
esac
# An inherited cross-design transition is ignored only after both tree entries are read and
# proven identical. A failed lookup must stop rather than becoming "absent == absent".
OUT=$(
  {
    git() {
      [ "${3:-}" = ls-tree ] && return 1
      command git "$@"
    }
    TASK_US=$(printf '\037')
    . "$REAL_ROOT/core/task-ledger.sh"
    TSV=$(CLAUDE_PROJECT_DIR="$TW" "$S/plan.sh" 0950)
    BASE=$(task_branch_point "$TW")
    task_commits_validate "$TW" 0950 code "$TSV" "$BASE"
  } 2>&1
); got=$?
[ "$got" = 1 ] && ok "a failed inherited tree-entry lookup stops committed-history validation" \
  || bad "a failed inherited tree-entry lookup stops committed-history validation" \
  "want exit 1, got $got: $OUT"
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/task-status.sh" 0950 code --history 2>&1)
case "$OUT" in *"after task 1: continue; policy window 2; permitted tasks 3,4"*)
  ok "and the recorded continue history survives the main merge" ;;
  *) bad "and the recorded continue history survives the main merge" "$OUT" ;;
esac
perl -pi -e 's/^- \[ \] \*\*3\./- [x] **3./' "$TW/docs/design/0950-window.md"
(
  cd "$TW" || exit 1
  git add -A && git -c user.email=t@t -c user.name=t commit -qm "review: hide task 3 tick"
)
tw_run 1 "a later granted task hidden in a review commit cannot expose another task" next.sh 0950 code
(
  cd "$TW" || exit 1
  perl -0pi -e 's/(- \[ \] \*\*5\.\*\* Last independent task\.)/$1\n- [ ] **6.** Routed SCOPE follow-up./' \
    docs/design/0950-window.md
  git add docs/design/0950-window.md
  git -c user.email=t@t -c user.name=t commit --amend -qm "task 3: later independent task" -m "Review-Rounds: 1"
)
tw_run 0 "the second exact task is admitted while a newly routed task stays outside the run" next.sh 0950 code
tw_tick 4 "dependent task"
printf '{"continuation_window_tasks":5,"review_window_rounds":3}\n' > "$TW/core/delivery-policy.json"
tw_run 8 "a consumed two-task window stops before an unlisted task" next.sh 0950 code
grep -q '^window-tasks: 2$' "$CHOICE_DIR/000001.choice" \
  && ok "a later policy increase cannot enlarge an existing grant" \
  || bad "a later policy increase cannot enlarge an existing grant" "the snapshot changed"
printf '{"continuation_window_tasks":2,"review_window_rounds":3}\n' > "$TW/core/delivery-policy.json"

tw_prompt stop
tw_run 8 "a stop choice remains a checkpoint on resume" next.sh 0950 code
tw_prompt continue
tw_run 0 "a later human continue supersedes stop for work admission" next.sh 0950 code
if grep -q '^permitted-tasks: 5$' "$CHOICE_DIR/000003.choice"; then
  ok "a fresh grant excludes a pending SCOPE task added on this delivery branch"
else bad "a fresh grant excludes a pending SCOPE task added on this delivery branch" \
  "expected only reviewed task 5"; fi

rm -rf "$TW/.deliver/reviews/task-state"
tw_prompt pr
tw_run 9 "a pr choice is terminal on the existing branch" next.sh 0950 code
(
  cd "$TW" || exit 1
  git checkout -q -b upstream-after-pr origin/main
  echo sync-again >> upstream.txt
  git add upstream.txt && git -c user.email=t@t -c user.name=t commit -qm "chore: advance main again"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q deliver/0950-code
  git -c user.email=t@t -c user.name=t merge -q --no-edit upstream-after-pr
)
tw_run 9 "a terminal pr and its history survive a later main merge" next.sh 0950 code
OUT=$(CLAUDE_PROJECT_DIR="$TW" "$S/task-status.sh" 0950 code --history 2>&1)
case "$OUT" in *"after task 4: pr; policy window 2; permitted tasks none"*)
  ok "checkpoint history remains bound to its branch incarnation and boundary" ;;
  *) bad "checkpoint history remains bound to its branch incarnation and boundary" "$OUT" ;;
esac

cp "$CHOICE_DIR/000001.choice" "$TW/choice.good"
perl -pi -e 's/^branch: .*/branch: deliver\/9999/' "$CHOICE_DIR/000001.choice"
tw_run 1 "a branch-mismatched choice record fails closed" next.sh 0950 code
mv "$TW/choice.good" "$CHOICE_DIR/000001.choice"

perl -pi -e 's/^boundary-commit: .*/boundary-commit: 0000000000000000000000000000000000000000/' \
  "$CHOICE_DIR/000001.choice"
tw_run 1 "a stale record whose boundary commit left history fails closed" next.sh 0950 code
rm -rf "$TW"

MG=$(mktemp -d)
copy_harness "$REAL_ROOT" "$MG" core || exit 1
mkdir -p "$MG/docs/design"
cat > "$MG/docs/design/0951-merged.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-21
---
## 7. Tasks
### Code track
- [ ] **1.** First run.
- [ ] **2.** First task after merge.
### Code track
- [ ] **3.** Must reach the new incarnation's checkpoint.
EOF
printf 'docs/design/0951-merged.md -diff\n' > "$MG/.gitattributes"
(
  cd "$MG" || exit 1
  git init -q -b main . && printf '.deliver/\n' > .gitignore
  git add -A && git -c user.email=t@t -c user.name=t commit -qm init
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q -b deliver/0951
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0951-merged.md
  git add -A && git -c user.email=t@t -c user.name=t commit -qm "task 1: first run" -m "Review-Rounds: 1"
)
mg_prompt() {
  codex_task_prompt "$MG" "$1"
}
mg_prompt pr
(
  cd "$MG" || exit 1
  git branch -m deliver/0951-code
)
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 1 ] && ok "a single-track suffixed branch is rejected by the live gate" \
  || bad "a single-track suffixed branch is rejected by the live gate" "want exit 1, got $got: $OUT"
case "$OUT" in *"not the canonical branch"*) ok "and identifies its canonical-branch violation" ;;
  *) bad "and identifies its canonical-branch violation" "$OUT" ;; esac
( cd "$MG" && git branch -m deliver/0951 )
git -C "$MG" update-ref refs/remotes/origin/main "$(git -C "$MG" rev-parse HEAD)"
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 1 ] && ok "an already-merged local delivery branch cannot regain fresh authority" \
  || bad "an already-merged local delivery branch cannot regain fresh authority" "want exit 1, got $got"
printf 'dirty absorbed work\n' > "$MG/absorbed-dirty.txt"
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 1 ] && ok "dirty work cannot revive an already-absorbed delivery branch" \
  || bad "dirty work cannot revive an already-absorbed delivery branch" "want exit 1, got $got: $OUT"
mint_at "$MG"
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/complete.sh" 0951 2 2>&1); got=$?
[ "$got" = 1 ] && ok "pending completion cannot revive a dirty absorbed delivery branch" \
  || bad "pending completion cannot revive a dirty absorbed delivery branch" "want exit 1, got $got: $OUT"
case "$OUT" in *"fresh task authority requires a newly created dirty delivery branch at refreshed trunk"*)
  ok "and pending completion names the missing fresh incarnation" ;;
  *) bad "and pending completion names the missing fresh incarnation" "$OUT" ;; esac
perl -pi -e 's/^- \[ \] \*\*2\./- [x] **2./' "$MG/docs/design/0951-merged.md"
mint_at "$MG"
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/complete.sh" 0951 2 2>&1); got=$?
[ "$got" = 1 ] && ok "interrupted-tick recovery cannot revive a dirty absorbed delivery branch" \
  || bad "interrupted-tick recovery cannot revive a dirty absorbed delivery branch" "want exit 1, got $got: $OUT"
case "$OUT" in *"fresh task recovery requires a newly created dirty delivery branch at refreshed trunk"*)
  ok "and recovery names the missing fresh incarnation" ;;
  *) bad "and recovery names the missing fresh incarnation" "$OUT" ;; esac
( cd "$MG" && git checkout -q -- docs/design/0951-merged.md )
rm "$MG/absorbed-dirty.txt"
(
  cd "$MG" || exit 1
  git checkout -q main
  git -c user.email=t@t -c user.name=t merge -q --ff-only deliver/0951
)
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 0 ] && ok "refreshed main supplies fresh authority for the later run" \
  || bad "refreshed main supplies fresh authority for the later run" "want exit 0, got $got: $OUT"
(
  cd "$MG" || exit 1
  git branch -D deliver/0951 >/dev/null
  git checkout -q -b deliver/0951
  echo in-flight > implementation.txt
  perl -0pi -e 's/(- \[ \] \*\*2\.\*\* First task after merge\.)/- [ ] **2.** First task after merge, with clarified wording.\n  *Depends on task 3.*\n  *Blocked on §9.*/; s/(- \[ \] \*\*3\.\*\* Must reach the new incarnation.s checkpoint\.)/$1\n- [ ] **4.** Routed pending follow-up./' \
    docs/design/0951-merged.md
)
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 0 ] && ok "a dirty canonical branch resumes through routed pending and wording edits" \
  || bad "a dirty canonical branch at refreshed trunk resumes its first task" "want exit 0, got $got: $OUT"
case "$OUT" in 2*"First task after merge, with clarified wording"*)
  ok "and branch-point ordering still selects the original first task" ;;
  *) bad "and branch-point ordering still selects the original first task" "$OUT" ;;
esac
perl -pi -e 's/^- \[ \] \*\*2\./- [x] **2./' "$MG/docs/design/0951-merged.md"
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 1 ] && ok "an interrupted tick remains a completed-task boundary despite routed edits" \
  || bad "an interrupted tick remains a completed-task boundary despite routed edits" "want exit 1, got $got: $OUT"
mkdir "$MG/failing-normalizer"
printf '#!/bin/sh\nexit 1\n' > "$MG/failing-normalizer/tr"
chmod +x "$MG/failing-normalizer/tr"
OUT=$(PATH="$MG/failing-normalizer:$PATH" CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 1 ] && ok "a failed legacy tr normalizer cannot hide a real worktree transition" \
  || bad "a failed legacy tr normalizer cannot hide a real worktree transition" \
  "want exit 1, got $got: $OUT"
case "$OUT" in *"design task state differs from HEAD"*)
  ok "and transition pairing no longer depends on tr" ;;
  *) bad "and transition pairing no longer depends on tr" "$OUT" ;;
esac
rm -rf "$MG/failing-normalizer"
perl -pi -e 's/^- \[x\] \*\*2\./- [ ] **2./' "$MG/docs/design/0951-merged.md"
mkdir "$MG/failing-path"
printf '#!/bin/sh\nexit 1\n' > "$MG/failing-path/sed"
chmod +x "$MG/failing-path/sed"
OUT=$(PATH="$MG/failing-path:$PATH" CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 1 ] && ok "worktree transition extraction failure stops fresh resume" \
  || bad "worktree transition extraction failure stops fresh resume" "want exit 1, got $got: $OUT"
case "$OUT" in *"cannot compare the working-tree task state with HEAD"*)
  ok "and fresh resume distinguishes unreadable extraction from no transition" ;;
  *) bad "and fresh resume distinguishes unreadable extraction from no transition" "$OUT" ;;
esac
rm -rf "$MG/failing-path"
if (
  TASK_US=$(printf '\037')
  . "$REAL_ROOT/core/task-ledger.sh"
  task_transition_ids_between "$MG" refs/heads/does-not-exist HEAD docs/design/0951-merged.md
) >/dev/null 2>&1; then
  bad "an unreadable task comparison fails closed" "a missing ref looked like no transition"
else
  ok "an unreadable task comparison fails closed"
fi
mint_at "$MG"
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/complete.sh" 0951 2 2>&1); got=$?
[ "$got" = 0 ] && ok "pending completion accepts the same fresh dirty branch incarnation" \
  || bad "pending completion accepts the same fresh dirty branch incarnation" "want exit 0, got $got: $OUT"
( cd "$MG" && git checkout -q -- docs/design/0951-merged.md )
(
  cd "$MG" || exit 1
  git branch -m deliver/0951-code
)
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 1 ] && ok "dirty exact-trunk work on a noncanonical branch is still rejected" \
  || bad "dirty exact-trunk work on a noncanonical branch is still rejected" "want exit 1, got $got: $OUT"
case "$OUT" in *"not the canonical branch"*) ok "and names the canonical-branch violation" ;;
  *) bad "and names the canonical-branch violation" "$OUT" ;; esac
(
  cd "$MG" || exit 1
  git branch -m deliver/0951
  old_trunk=$(git rev-parse origin/main)
  new_trunk=$(printf 'fixture: advance refreshed trunk\n' \
    | git -c user.email=t@t -c user.name=t commit-tree "$(git rev-parse origin/main^{tree})" -p origin/main)
  git update-ref refs/remotes/origin/main "$new_trunk"
  printf '%s\n' "$old_trunk" > old-trunk
)
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 1 ] && ok "dirty work on a delivery branch behind refreshed trunk is rejected" \
  || bad "dirty work on a delivery branch behind refreshed trunk is rejected" "want exit 1, got $got: $OUT"
(
  cd "$MG" || exit 1
  git update-ref refs/remotes/origin/main "$(cat old-trunk)"
  rm old-trunk
  rm implementation.txt
  perl -pi -e 's/^- \[ \] \*\*2\./- [x] **2./' docs/design/0951-merged.md
  git add -A && git -c user.email=t@t -c user.name=t commit -qm "task 2: later run" -m "Review-Rounds: 1"
)
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 8 ] && ok "old terminal records do not cross a reused branch name's new incarnation" \
  || bad "old terminal records do not cross a reused branch name's new incarnation" "want exit 8, got $got: $OUT"
MGP=$(mktemp -d)
cp -R "$MG/." "$MGP"
MGO=$(mktemp -d)
cp -R "$MG/." "$MGO"
MGO_SAME_ORIGINAL=$(mktemp -d)
cp -R "$MG/." "$MGO_SAME_ORIGINAL"
mg_prompt stop
mg_prompt continue
(
  cd "$MG" || exit 1
  git checkout -q -b upstream-new-track origin/main
  # The first repeated Code section owns the completed boundary task; moving only that
  # heading changes its reviewed owner without moving the still-runnable task 3.
  perl -0pi -e 's/### Code track/### Infra track/; s/(- \[ \] \*\*2\.\*\* First task after merge\.)/$1\n  *Depends on task 4.*\n  *Blocked on §9.*/' \
    docs/design/0951-merged.md
  printf '%s\n' '### Infra track' '- [ ] **4.** Pending task on a newly reviewed track.' \
    >> docs/design/0951-merged.md
  git add docs/design/0951-merged.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: move old metadata and add a second delivery track"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q deliver/0951
  if ! git -c user.email=t@t -c user.name=t merge -q --no-commit upstream-new-track; then
    # Resolve the expected checkbox/metadata overlap: retain the completed branch state
    # while accepting trunk's reviewed owner, dependency, blocker, and new task.
    git checkout -q --theirs docs/design/0951-merged.md
    perl -pi -e 's/^- \[ \] \*\*2\./- [x] **2./' docs/design/0951-merged.md
    git add docs/design/0951-merged.md
  fi
  git -c user.email=t@t -c user.name=t commit -qm "Merge refreshed main with reviewed metadata"
)
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 0 ] && ok "a running single-track branch survives an exact new-track trunk merge" \
  || bad "a running single-track branch survives an exact new-track trunk merge" \
  "want exit 0, got $got: $OUT"
case "$OUT" in 3*"Must reach the new incarnation's checkpoint"*"(track: code)"*)
  ok "and selection stays on the incarnation's original track" ;;
  *) bad "and selection stays on the incarnation's original track" "$OUT" ;;
esac
OUT=$(
  . "$REAL_ROOT/core/round-ledger.sh"
  round_current_key "$MG" deliver/0951
); got=$?
[ "$got" = 0 ] && [ "$OUT" = 0951-t3 ] \
  && ok "new-track synchronization preserves review attribution" \
  || bad "new-track synchronization preserves review attribution" "want 0951-t3, got exit $got: $OUT"
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/task-status.sh" 0951 --history 2>&1); got=$?
[ "$got" = 0 ] && ok "new-track synchronization preserves checkpoint history rendering" \
  || bad "new-track synchronization preserves checkpoint history rendering" "exit $got: $OUT"
case "$OUT" in *"after task 2: stop"*"after task 2: continue"*"permitted tasks 3"*)
  ok "and stop/continue history retains the boundary's original branch, owner, and projection" ;;
  *) bad "and stop/continue history retains the boundary's original branch, owner, and projection" "$OUT" ;;
esac
OUT=$(cd "$MG" && CLAUDE_PROJECT_DIR="$MG" GITHUB_HEAD_REF=deliver/0951 \
  "$S/verify-delivery.sh" origin/main 2>&1); got=$?
[ "$got" = 0 ] && ok "CI preserves the original single-track branch shape after a new track merges" \
  || bad "CI preserves the original single-track branch shape after a new track merges" \
  "want exit 0, got $got: $OUT"
case "$OUT" in *"every ticked task was runnable under its reviewed authority"*)
  ok "and later blocker, dependency, and owner metadata do not rewrite earlier CI runnability" ;;
  *) bad "and later blocker, dependency, and owner metadata do not rewrite earlier CI runnability" "$OUT" ;;
esac
mint_at "$MG"
OUT=$(CLAUDE_PROJECT_DIR="$MG" "$S/complete.sh" 0951 3 2>&1); got=$?
[ "$got" = 0 ] && ok "completion uses the preserved delivery-incarnation owner" \
  || bad "completion uses the preserved delivery-incarnation owner" "exit $got: $OUT"
( cd "$MG" && git checkout -q -- docs/design/0951-merged.md )
rm -rf "$MG"

# A choice written after refreshed trunk moves the completed boundary's owner must retain
# the owner reviewed at that task commit while projecting future work from current trunk.
# Continue exercises the shared boundary binding plus task projection. Terminal PR
# history is checked below; the ordinary choice tests own the continue/pr/stop mapping.
mgo_prompt() {
  codex_task_prompt "$1" "$2"
}

# A canonical task merge is judged against its first parent. If that same merge inherits a
# reviewed owner move, checkpoint reconstruction must use the same pre-commit authority,
# not the merge result's new owner. Exercise an identity present at incarnation start.
mgo_prompt "$MGO_SAME_ORIGINAL" continue
(
  cd "$MGO_SAME_ORIGINAL" || exit 1
  git checkout -q -b upstream-same-merge-original origin/main
  perl -0pi -e 's/### Code track\n(- \[ \] \*\*3\.)/### Infra track\n$1/' \
    docs/design/0951-merged.md
  printf '%s\n' '### Code track' '- [ ] **4.** Task after the same-merge boundary.' \
    >> docs/design/0951-merged.md
  git add docs/design/0951-merged.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: move task 3 while it remains pending"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q deliver/0951
  if ! git -c user.email=t@t -c user.name=t merge -q --no-commit upstream-same-merge-original; then
    git checkout -q --theirs docs/design/0951-merged.md
    perl -pi -e 's/^- \[ \] \*\*([1-2])\./- [x] **$1./' docs/design/0951-merged.md
  fi
  perl -pi -e 's/^- \[ \] \*\*3\./- [x] **3./' docs/design/0951-merged.md
  git add docs/design/0951-merged.md
  git -c user.email=t@t -c user.name=t commit -qm \
    "task 3: complete while its reviewed owner moves" -m "Review-Rounds: 1"
)
OUT=$(CLAUDE_PROJECT_DIR="$MGO_SAME_ORIGINAL" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 8 ] && ok "core/README.md: a same-merge owner move retains an original task boundary" \
  || bad "core/README.md: a same-merge owner move retains an original task boundary" \
    "want exit 8, got $got: $OUT"
case "$OUT" in *"task 3 is committed and task 4 is runnable"*)
  ok "and the original boundary uses its pre-merge reviewed owner" ;;
  *) bad "and the original boundary uses its pre-merge reviewed owner" "$OUT" ;; esac
mgo_prompt "$MGO_SAME_ORIGINAL" continue
OUT=$(CLAUDE_PROJECT_DIR="$MGO_SAME_ORIGINAL" "$S/next.sh" 0951 2>&1); got=$?
case "$OUT" in 4*)
  [ "$got" = 0 ] && ok "an original same-merge boundary choice reloads" \
    || bad "an original same-merge boundary choice reloads" "want exit 0, got $got: $OUT" ;;
  *) bad "an original same-merge boundary choice reloads" "$OUT" ;; esac
OUT=$(CLAUDE_PROJECT_DIR="$MGO_SAME_ORIGINAL" "$S/task-status.sh" 0951 --history 2>&1); got=$?
case "$OUT" in *"after task 3: continue"*)
  [ "$got" = 0 ] && ok "and original same-merge history stays on task 3" \
    || bad "and original same-merge history stays on task 3" "exit $got: $OUT" ;;
  *) bad "and original same-merge history stays on task 3" "$OUT" ;; esac
OUT=$(cd "$MGO_SAME_ORIGINAL" && CLAUDE_PROJECT_DIR="$MGO_SAME_ORIGINAL" \
  GITHUB_HEAD_REF=deliver/0951 "$S/verify-delivery.sh" origin/main 2>&1); got=$?
[ "$got" = 0 ] && ok "CI consumes the original same-merge authority manifest" \
  || bad "CI consumes the original same-merge authority manifest" "want exit 0, got $got: $OUT"

mgo_prompt "$MGO" stop
(
  cd "$MGO" || exit 1
  git checkout -q -b upstream-post-stop-owner-move origin/main
  perl -0pi -e 's/### Code track/### Infra track/' docs/design/0951-merged.md
  printf '%s\n' '### Code track' \
    '- [ ] **4.** First same-track task reviewed after incarnation start.' \
    '### Code track' \
    '- [ ] **5.** Second same-track task reviewed after incarnation start.' \
    '- [ ] **6.** Remaining same-track task.' \
    >> docs/design/0951-merged.md
  git add docs/design/0951-merged.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: move the stopped boundary owner"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q deliver/0951
  git -c user.email=t@t -c user.name=t merge -q --no-edit upstream-post-stop-owner-move
)

mgo_prompt "$MGO" continue
OUT=$(CLAUDE_PROJECT_DIR="$MGO" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 0 ] && ok "a post-owner-move continue remains usable after it is recorded" \
  || bad "a post-owner-move continue remains usable after it is recorded" "want exit 0, got $got: $OUT"
OUT=$(CLAUDE_PROJECT_DIR="$MGO" "$S/task-status.sh" 0951 --history 2>&1); got=$?
case "$OUT" in *"after task 2: stop"*"after task 2: continue"*)
  [ "$got" = 0 ] && ok "and status retains both pre-merge stop and post-merge continue" \
    || bad "and status retains both pre-merge stop and post-merge continue" "exit $got: $OUT" ;;
  *) bad "and status retains both pre-merge stop and post-merge continue" "$OUT" ;;
esac
mint_at "$MGO"
OUT=$(CLAUDE_PROJECT_DIR="$MGO" "$S/complete.sh" 0951 3 2>&1); got=$?
[ "$got" = 0 ] && ok "completion consumes a valid post-owner-move continuation" \
  || bad "completion consumes a valid post-owner-move continuation" "want exit 0, got $got: $OUT"


# Advance the continued copy until a task introduced by refreshed main is itself the
# completed boundary. Its choices must consume the validated task-commit history because
# the original incarnation shape cannot contain an identity that did not exist yet.
(
  cd "$MGO" || exit 1
  git add docs/design/0951-merged.md
  git -c user.email=t@t -c user.name=t commit -qm "task 3: original-shape task" -m "Review-Rounds: 1"
)
mgo_prompt "$MGO" continue
OUT=$(CLAUDE_PROJECT_DIR="$MGO" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 0 ] && ok "a renewed window admits its first newly reviewed same-track task" \
  || bad "a renewed window admits its first newly reviewed same-track task" "want exit 0, got $got: $OUT"
MGO_SAME_ADDED=$(mktemp -d)
cp -R "$MGO/." "$MGO_SAME_ADDED"
(
  cd "$MGO_SAME_ADDED" || exit 1
  git checkout -q -b upstream-same-merge-added origin/main
  perl -0pi -e 's/### Code track\n(- \[ \] \*\*4\.)/### Infra track\n$1/' \
    docs/design/0951-merged.md
  git add docs/design/0951-merged.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: move added task 4 while it remains pending"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q deliver/0951
  if ! git -c user.email=t@t -c user.name=t merge -q --no-commit upstream-same-merge-added; then
    git checkout -q --theirs docs/design/0951-merged.md
    perl -pi -e 's/^- \[ \] \*\*([1-3])\./- [x] **$1./' docs/design/0951-merged.md
  fi
  perl -pi -e 's/^- \[ \] \*\*4\./- [x] **4./' docs/design/0951-merged.md
  git add docs/design/0951-merged.md
  git -c user.email=t@t -c user.name=t commit -qm \
    "task 4: complete added task while its reviewed owner moves" -m "Review-Rounds: 1"
)
OUT=$(CLAUDE_PROJECT_DIR="$MGO_SAME_ADDED" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 8 ] && ok "core/README.md: a same-merge owner move retains a post-incarnation task boundary" \
  || bad "core/README.md: a same-merge owner move retains a post-incarnation task boundary" \
  "want exit 8, got $got: $OUT"
case "$OUT" in *"task 4 is committed and task 5 is runnable"*)
  ok "and the post-incarnation boundary uses its pre-merge reviewed owner" ;;
  *) bad "and the post-incarnation boundary uses its pre-merge reviewed owner" "$OUT" ;; esac
mgo_prompt "$MGO_SAME_ADDED" continue
OUT=$(CLAUDE_PROJECT_DIR="$MGO_SAME_ADDED" "$S/next.sh" 0951 2>&1); got=$?
case "$OUT" in 5*)
  [ "$got" = 0 ] && ok "a post-incarnation same-merge boundary choice reloads" \
    || bad "a post-incarnation same-merge boundary choice reloads" "want exit 0, got $got: $OUT" ;;
  *) bad "a post-incarnation same-merge boundary choice reloads" "$OUT" ;; esac
OUT=$(CLAUDE_PROJECT_DIR="$MGO_SAME_ADDED" "$S/task-status.sh" 0951 --history 2>&1); got=$?
case "$OUT" in *"after task 4: continue"*)
  [ "$got" = 0 ] && ok "and post-incarnation same-merge history stays on task 4" \
    || bad "and post-incarnation same-merge history stays on task 4" "exit $got: $OUT" ;;
  *) bad "and post-incarnation same-merge history stays on task 4" "$OUT" ;; esac
OUT=$(cd "$MGO_SAME_ADDED" && CLAUDE_PROJECT_DIR="$MGO_SAME_ADDED" \
  GITHUB_HEAD_REF=deliver/0951 "$S/verify-delivery.sh" origin/main 2>&1); got=$?
[ "$got" = 0 ] && ok "CI consumes the post-incarnation same-merge authority manifest" \
  || bad "CI consumes the post-incarnation same-merge authority manifest" \
  "want exit 0, got $got: $OUT"
mint_at "$MGO"
OUT=$(CLAUDE_PROJECT_DIR="$MGO" "$S/complete.sh" 0951 4 2>&1); got=$?
[ "$got" = 0 ] && ok "completion accepts a newly reviewed task within the retained window" \
  || bad "completion accepts a newly reviewed task within the retained window" "want exit 0, got $got: $OUT"
(
  cd "$MGO" || exit 1
  git add docs/design/0951-merged.md
  git -c user.email=t@t -c user.name=t commit -qm "task 4: post-incarnation task" -m "Review-Rounds: 1"
)
mgo_prompt "$MGO" stop

mgo_move_added_owner() {
  (
    cd "$1" || exit 1
    git checkout -q -b upstream-added-boundary-owner origin/main
    perl -0pi -e 's/### Code track\n(- \[ \] \*\*4\.)/### Infra track\n$1/' \
      docs/design/0951-merged.md
    git add docs/design/0951-merged.md && git -c user.email=t@t -c user.name=t \
      commit -qm "review: move the post-incarnation boundary owner"
    git update-ref refs/remotes/origin/main HEAD
    git checkout -q deliver/0951
    if ! git -c user.email=t@t -c user.name=t merge -q --no-commit upstream-added-boundary-owner; then
      git checkout -q --theirs docs/design/0951-merged.md
      perl -pi -e 's/^- \[ \] \*\*([1-4])\./- [x] **$1./' docs/design/0951-merged.md
      git add docs/design/0951-merged.md
    fi
    git -c user.email=t@t -c user.name=t commit -qm "Merge refreshed main after moving task 4"
  )
}
mgo_move_added_owner "$MGO"

OUT=$(CLAUDE_PROJECT_DIR="$MGO" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 8 ] && ok "a pre-move stop remains the latest post-incarnation checkpoint" \
  || bad "a pre-move stop remains the latest post-incarnation checkpoint" "want exit 8, got $got: $OUT"
case "$OUT" in *"previous choice after task 4 was stop"*)
  ok "and the live boundary does not roll back after the owner move" ;;
  *) bad "and the live boundary does not roll back after the owner move" "$OUT" ;;
esac

# A new continuation must bind the same historical boundary, not the latest owner projection.
mgo_prompt "$MGO" continue
OUT=$(CLAUDE_PROJECT_DIR="$MGO" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 0 ] && ok "a post-move continue remains on the post-incarnation boundary" \
  || bad "a post-move continue remains on the post-incarnation boundary" "want exit 0, got $got: $OUT"
OUT=$(CLAUDE_PROJECT_DIR="$MGO" "$S/task-status.sh" 0951 --history 2>&1); got=$?
case "$OUT" in *"after task 4: stop"*"after task 4: continue"*"permitted tasks 5"*)
  [ "$got" = 0 ] && ok "and status renders both task-4 choices across the owner move" \
    || bad "and status renders both task-4 choices across the owner move" "exit $got: $OUT" ;;
  *) bad "and status renders both task-4 choices across the owner move" "$OUT" ;;
esac
mint_at "$MGO"
OUT=$(CLAUDE_PROJECT_DIR="$MGO" "$S/complete.sh" 0951 5 2>&1); got=$?
[ "$got" = 0 ] && ok "completion consumes the post-move task-4 continuation" \
  || bad "completion consumes the post-move task-4 continuation" "want exit 0, got $got: $OUT"

rm -rf "$MGO" "$MGO_SAME_ORIGINAL" "$MGO_SAME_ADDED"

# A terminal PR record is just as historical as stop/continue: a later reviewed owner move
# cannot invalidate its original boundary owner or resurrect the branch.
(
  codex_task_prompt "$MGP" pr
  cd "$MGP" || exit 1
  git checkout -q -b upstream-owner-move origin/main
  perl -0pi -e 's/### Code track/### Infra track/' docs/design/0951-merged.md
  git add docs/design/0951-merged.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: move the completed boundary task"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q deliver/0951
  git -c user.email=t@t -c user.name=t merge -q --no-edit upstream-owner-move
)
OUT=$(CLAUDE_PROJECT_DIR="$MGP" "$S/next.sh" 0951 2>&1); got=$?
[ "$got" = 9 ] && ok "a terminal pr survives a later reviewed owner move" \
  || bad "a terminal pr survives a later reviewed owner move" "want exit 9, got $got: $OUT"
OUT=$(CLAUDE_PROJECT_DIR="$MGP" "$S/task-status.sh" 0951 --history 2>&1); got=$?
case "$OUT" in *"after task 2: pr"*)
  [ "$got" = 0 ] && ok "and pr history retains the recorded boundary owner" \
    || bad "and pr history retains the recorded boundary owner" "exit $got: $OUT" ;;
  *) bad "and pr history retains the recorded boundary owner" "$OUT" ;;
esac
rm -rf "$MGP"

# CI must judge a task by metadata in force when its task commit was made. Removing an
# historical blocker/dependency on refreshed trunk cannot launder a task the gate could not
# have admitted at that earlier endpoint.
HM=$(mktemp -d)
copy_harness "$REAL_ROOT" "$HM" core || exit 1
mkdir -p "$HM/docs/design"
cat > "$HM/docs/design/0952-history.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-09-01
---
## 7. Tasks
### Code track
- [ ] **1.** Historically blocked task.
  *Depends on task 2.*
  *Blocked on §9.*
- [ ] **2.** Independent runnable task.
EOF
(
  cd "$HM" || exit 1
  git init -q -b main . && printf '.deliver/\n' > .gitignore
  git add -A && git -c user.email=t@t -c user.name=t commit -qm init
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q -b deliver/0952
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0952-history.md
  git add -A && git -c user.email=t@t -c user.name=t \
    commit -qm "task 1: bypass historical runnability" -m "Review-Rounds: 1"
  git checkout -q -b upstream-unblock origin/main
  perl -0pi -e 's/  \*Depends on task 2\.\*\n  \*Blocked on §9\.\*\n//' docs/design/0952-history.md
  git add docs/design/0952-history.md && git -c user.email=t@t -c user.name=t \
    commit -qm "review: remove the old blocker"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q deliver/0952
  if ! git -c user.email=t@t -c user.name=t merge -q --no-commit upstream-unblock; then
    git checkout -q --theirs docs/design/0952-history.md
    perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0952-history.md
    git add docs/design/0952-history.md
  fi
  git -c user.email=t@t -c user.name=t commit -qm "Merge refreshed main after removing old metadata"
)
OUT=$(CLAUDE_PROJECT_DIR="$HM" "$S/next.sh" 0952 2>&1); got=$?
[ "$got" = 1 ] && ok "later reviewed metadata cannot legalize an historically blocked task commit" \
  || bad "later reviewed metadata cannot legalize an historically blocked task commit" "want exit 1, got $got: $OUT"
case "$OUT" in *"task 1 was not the next runnable task under reviewed authority"*)
  ok "and the live gate names the historical canonical task mismatch" ;;
  *) bad "and the live gate names the historical canonical task mismatch" "$OUT" ;;
esac
OUT=$(cd "$HM" && CLAUDE_PROJECT_DIR="$HM" GITHUB_HEAD_REF=deliver/0952 \
  "$S/verify-delivery.sh" origin/main 2>&1); got=$?
[ "$got" = 1 ] && ok "CI rejects the same refreshed-trunk metadata laundering" \
  || bad "CI rejects the same refreshed-trunk metadata laundering" "want exit 1, got $got: $OUT"
case "$OUT" in *"not the next runnable task under reviewed authority"*)
  ok "and CI reports authority from the task commit's historical endpoint" ;;
  *) bad "and CI reports authority from the task commit's historical endpoint" "$OUT" ;;
esac
rm -rf "$HM"

echo "delivery branch start"
BS=$(mktemp -d)
mkdir -p "$BS/docs/design"
cat > "$BS/docs/design/0989-start.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-09-01
---
## 7. Tasks
### Code track
- [ ] **1.** Previously delivered task.
- [ ] **2.** Next delivery task. *Depends on task 1.*
EOF
cat > "$BS/docs/design/0988-live.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-09-01
---
## 7. Tasks
### Code track
- [ ] **1.** Preserve live branch work.
EOF
cat > "$BS/docs/design/0987-multi.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-09-01
---
## 7. Tasks
### Web track
- [ ] **1.** Start the web track.
### API track
- [ ] **2.** Start the API track.
EOF
(
  cd "$BS" || exit 1
  git init -q -b main . && printf '.deliver/\n' > .gitignore
  git add -A && git -c user.email=t@t -c user.name=t commit -qm init
  git checkout -q -b deliver/0989
  perl -pi -e 's/^- \[ \] \*\*1\./- [x] **1./' docs/design/0989-start.md
  git add docs/design/0989-start.md && git -c user.email=t@t -c user.name=t \
    commit -qm "task 1: previously delivered" -m "Review-Rounds: 1"
  git checkout -q main
  git merge -q --ff-only deliver/0989
  git update-ref refs/remotes/origin/main HEAD
)
OUT=$(CLAUDE_PROJECT_DIR="$BS" "$S/start.sh" 0989 2>&1); got=$?
BS_BRANCH=$(git -C "$BS" rev-parse --abbrev-ref HEAD 2>/dev/null)
BS_REFLOG=$(git -C "$BS" reflog show --format='%gs' -n 1 refs/heads/deliver/0989 2>/dev/null)
if [ "$got" = 0 ] && [ "$BS_BRANCH" = deliver/0989 ] \
   && case "$BS_REFLOG" in branch:\ Created\ from\ *) true ;; *) false ;; esac; then
  ok "start retires an absorbed local name and creates a fresh delivery incarnation"
else
  bad "start retires an absorbed local name and creates a fresh delivery incarnation" \
    "exit $got, branch '$BS_BRANCH', reflog '$BS_REFLOG': $OUT"
fi
case "$OUT" in *"2  Next delivery task"*"retired absorbed local branch deliver/0989"*)
  ok "start preserves next.sh admission output and reports the absorbed ref retirement" ;;
  *) bad "start preserves next.sh admission output and reports the absorbed ref retirement" "$OUT" ;;
esac
(
  cd "$BS" || exit 1
  git checkout -q main
  git checkout -q -b deliver/0988
  printf 'unmerged\n' > live-work.txt
  git add live-work.txt && git -c user.email=t@t -c user.name=t commit -qm "live delivery work"
  git checkout -q main
)
BS_LIVE_BEFORE=$(git -C "$BS" rev-parse deliver/0988)
OUT=$(CLAUDE_PROJECT_DIR="$BS" "$S/start.sh" 0988 2>&1); got=$?
BS_LIVE_AFTER=$(git -C "$BS" rev-parse deliver/0988)
BS_BRANCH=$(git -C "$BS" rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ "$got" = 1 ] && [ "$BS_LIVE_BEFORE" = "$BS_LIVE_AFTER" ] && [ "$BS_BRANCH" = main ]; then
  ok "start refuses and preserves an unmerged same-name delivery branch"
else
  bad "start refuses and preserves an unmerged same-name delivery branch" \
    "exit $got, before $BS_LIVE_BEFORE, after $BS_LIVE_AFTER, branch $BS_BRANCH: $OUT"
fi
OUT=$(CLAUDE_PROJECT_DIR="$BS" "$S/start.sh" 0987 web 2>&1); got=$?
BS_BRANCH=$(git -C "$BS" rev-parse --abbrev-ref HEAD 2>/dev/null)
[ "$got" = 0 ] && [ "$BS_BRANCH" = deliver/0987-web ] \
  && ok "start derives the canonical track-suffixed branch from reviewed task shape" \
  || bad "start derives the canonical track-suffixed branch from reviewed task shape" \
    "exit $got, branch '$BS_BRANCH': $OUT"
# The external design integration test exercises the new runner calling start.sh.
rm -rf "$BS"

echo "review readiness, convergence report, and calibration telemetry"
RR=$(mktemp -d)
mkdir -p "$RR/docs/design"
copy_harness "$REAL_ROOT" "$RR" core || exit 1
cat > "$RR/docs/design/0990-review.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-08-27
---
## 7. Tasks
### Code track
- [ ] **1.** Review-ready task.
- [ ] **2.** Later task. *Depends on task 1.*
EOF
(
  cd "$RR" || exit 1
  git init -q -b main . && printf '.deliver/\n' > .gitignore
  git add -A && git -c user.email=t@t -c user.name=t commit -qm init
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q -b deliver/0990
)
RRM=$(mktemp)
cat > "$RRM" <<'EOF'
## Requirements covered
- Task requirement maps to the readiness fixture.
## Rules checked
- Review evidence stays separate from the human PR authority.
## Affected surfaces
- Stage, status and stale-tree paths.
## Claims and proof
- Each claim names this causal test.
## Adversarial self-review
- Wrong task and stale tree are attempted.
## Defect-family closure
- The task/tree mismatch family is covered together.
## Prior finding dispositions
- none — first review
## Verification
- The real staging script is executed.
## Limits
- Reviewer behavior is not invoked by this shell test.
EOF
OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-ready.sh" stage 0990 1 "$RRM" 2>&1); got=$?
[ "$got" = 0 ] && ok "a complete manifest stages for the exact current task" \
  || bad "a complete manifest stages for the exact current task" "$OUT"
OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-ready.sh" status 0990 1 2>&1); got=$?
[ "$got" = 0 ] && ok "the staged manifest validates against the current tree" \
  || bad "the staged manifest validates against the current tree" "$OUT"

# A reset/reused ref at the refreshed trunk SHA used to survive every check until complete.sh,
# after all review rounds had already been spent. The review context now consumes the same
# branch-incarnation proof as next.sh and complete.sh, so this class stops before staging.
RI=$(mktemp -d)
mkdir -p "$RI/docs/design"
copy_harness "$REAL_ROOT" "$RI" core || exit 1
cat > "$RI/docs/design/0986-incarnation.md" <<'EOF'
---
type: design
status: approved
last-verified: 2026-09-01
---
## 7. Tasks
### Code track
- [ ] **1.** Reject a reused delivery incarnation before review.
EOF
(
  cd "$RI" || exit 1
  git init -q -b main . && printf '.deliver/\n' > .gitignore
  git add -A && git -c user.email=t@t -c user.name=t commit -qm init
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q -b deliver/0986
  printf 'temporary ref movement\n' > moved.txt
  git add moved.txt && git -c user.email=t@t -c user.name=t commit -qm moved
  git reset -q --hard origin/main
  printf 'actual implementation\n' > implementation.txt
)
OUT=$(CLAUDE_PROJECT_DIR="$RI" "$S/review-ready.sh" stage 0986 1 "$RRM" 2>&1); got=$?
[ "$got" = 2 ] && ok "a reused trunk-equal delivery incarnation is refused before review staging" \
  || bad "a reused trunk-equal delivery incarnation is refused before review staging" \
    "want exit 2, got $got: $OUT"
case "$OUT" in *"cannot resolve the delivery review context"*)
  ok "the early incarnation refusal identifies review-context resolution" ;;
  *) bad "the early incarnation refusal identifies review-context resolution" "$OUT" ;;
esac
rm -rf "$RI"
RR_CAPTURE_DIGEST=$(CLAUDE_PROJECT_DIR="$RR" "$S/tree-digest.sh")
. "$RR/core/review-request.sh"
RR_PENDING=$(review_request_pending_dir "$RR" 0990-t1 "$RR_CAPTURE_DIGEST")
RR_LIVE_SNAPSHOT="$(review_request_dir "$RR" 0990-t1 "$RR_CAPTURE_DIGEST")/snapshot.txt"

# The readiness gate re-captures before every reviewer start, and `review_tree_capture`
# restamps `at:` on every call. Two captures of one unchanged tree are therefore never
# byte-equal, so a whole-file comparison sent the second reviewer spawn for a tree down the
# "already published" refusal and wedged the round: no reviewer could ever be admitted twice.
# The stamp is forced here rather than waiting on the clock, so the case is exercised whether
# or not two real captures land in the same wall-clock second.
if review_request_capture "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" \
   && review_request_publish_pending "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" deliver/0990; then
  RR_RETAINED=$(mktemp)
  cp "$RR_PENDING/snapshot.txt" "$RR_RETAINED"
  sed '4s/^at: .*/at: 2000-01-01T00:00:00Z/' "$RR_LIVE_SNAPSHOT" > "$RR_LIVE_SNAPSHOT.restamped" \
    && mv "$RR_LIVE_SNAPSHOT.restamped" "$RR_LIVE_SNAPSHOT"
  if ! cmp -s "$RR_LIVE_SNAPSHOT" "$RR_RETAINED" \
     && review_request_publish_pending "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" deliver/0990 \
     && cmp -s "$RR_PENDING/snapshot.txt" "$RR_RETAINED"; then
    ok "a same-tree re-review reuses its retained input across a restamped capture"
  else
    bad "a same-tree re-review reuses its retained input across a restamped capture" \
      "a re-stamped capture of the same tree did not reuse the retained input"
  fi
  # Only the stamp is exempt. A live capture whose body differs is a different input.
  printf 'untracked: 6578747261\t%s\tregular\t100644\t%s\t2d\n' \
    "$(printf '%040d' 0)" "$(printf '%040d' 0)" >> "$RR_LIVE_SNAPSHOT"
  if ! review_request_publish_pending "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" deliver/0990; then
    ok "pending-input reuse still refuses a capture whose body differs"
  else
    bad "pending-input reuse still refuses a capture whose body differs" \
      "a changed capture body was accepted as the retained input"
  fi
  cp "$RR_RETAINED" "$RR_LIVE_SNAPSHOT"
  rm -f "$RR_RETAINED"
fi

# `review-ready.sh stage` restamps the request header's `at:` line on every call, exactly as
# `review_tree_capture` restamps the snapshot. A same-tree re-stage after a round that left
# the pending input in place — an interrupted or refused reviewer with no receipt — must reuse
# the retained request, not wedge the readiness gate on the changed stamp. The stamp is forced
# here rather than waiting on the clock.
RR_LIVE_REQUEST="$(review_request_dir "$RR" 0990-t1 "$RR_CAPTURE_DIGEST")/request.md"
if [ -d "$RR_PENDING" ]; then
  RR_REQ_PRISTINE=$(mktemp); cp "$RR_LIVE_REQUEST" "$RR_REQ_PRISTINE"
  RR_REQ_RETAINED=$(mktemp); cp "$RR_PENDING/request.md" "$RR_REQ_RETAINED"
  sed '6s/^at: .*/at: 2000-01-01T00:00:00Z/' "$RR_LIVE_REQUEST" > "$RR_LIVE_REQUEST.restamped" \
    && mv "$RR_LIVE_REQUEST.restamped" "$RR_LIVE_REQUEST"
  if ! cmp -s "$RR_LIVE_REQUEST" "$RR_REQ_RETAINED" \
     && review_request_capture "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" \
     && review_request_publish_pending "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" deliver/0990 \
     && cmp -s "$RR_PENDING/request.md" "$RR_REQ_RETAINED"; then
    ok "a same-tree re-review reuses its retained input across a restamped request stage"
  else
    bad "a same-tree re-review reuses its retained input across a restamped request stage" \
      "a re-stamped request stage of the same tree did not reuse the retained input"
  fi
  # Only the stamp is exempt. A request whose body differs is a different input, still refused.
  sed 's/^- The real staging script is executed\.$/- The real staging script is executed twice./' \
    "$RR_LIVE_REQUEST" > "$RR_LIVE_REQUEST.bodydiff" && mv "$RR_LIVE_REQUEST.bodydiff" "$RR_LIVE_REQUEST"
  if ! cmp -s "$RR_LIVE_REQUEST" "$RR_REQ_RETAINED" \
     && ! review_request_publish_pending "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" deliver/0990; then
    ok "pending-input reuse still refuses a request whose body differs"
  else
    bad "pending-input reuse still refuses a request whose body differs" \
      "a changed request body was accepted as the retained input"
  fi
  cp "$RR_REQ_PRISTINE" "$RR_LIVE_REQUEST"
  rm -f "$RR_REQ_RETAINED" "$RR_REQ_PRISTINE"
fi
if review_request_capture "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" \
   && review_request_publish_pending "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" deliver/0990; then
  printf 'mutated ignored snapshot\n' >> "$RR_PENDING/snapshot.txt"
  if ! review_request_publish_pending "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" deliver/0990; then
    ok "pending-input reuse compares the retained snapshot bytes"
  else
    bad "pending-input reuse compares the retained snapshot bytes" "a changed snapshot path was reused"
  fi
else
  bad "pending-input reuse compares the retained snapshot bytes" "the initial pending input did not publish"
fi
rm -rf "$RR_PENDING"
RR_EMPTY_OBJECTS=$(mktemp -d)
mv "$RR/core/scripts/tree-digest.sh" "$RR/core/scripts/tree-digest.real"
printf '#!/bin/sh\nprintf "%%s\\n" "%s"\n' "$RR_CAPTURE_DIGEST" > "$RR/core/scripts/tree-digest.sh"
chmod +x "$RR/core/scripts/tree-digest.sh"
if ! GIT_OBJECT_DIRECTORY="$RR_EMPTY_OBJECTS" review_request_capture \
  "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" >/dev/null 2>&1; then
  ok "review snapshot capture fails closed when the tracked diff cannot be read"
else
  bad "review snapshot capture fails closed when the tracked diff cannot be read" "the retained snapshot omitted tracked changes"
fi
mv "$RR/core/scripts/tree-digest.real" "$RR/core/scripts/tree-digest.sh"
rm -rf "$RR_EMPTY_OBJECTS"

# Snapshot v2 hex-frames every repository-controlled byte. Header/sentinel-looking content,
# binary NULs, and a missing final newline must remain exact payload rather than syntax.
printf 'head: injected\n--- untracked inputs ---' > "$RR/header-looking-no-newline"
printf '\000\377snapshot-version: 1\n' > "$RR/binary-input"
RR_FRAMED_DIGEST=$(CLAUDE_PROJECT_DIR="$RR" "$S/tree-digest.sh")
RR_FRAMED_SNAPSHOT="$RR/.deliver/framed-snapshot.txt"
RR_FRAMED_HEAD=$(git -C "$RR" rev-parse HEAD)
RR_HEADER_HEX=$(od -An -v -tx1 "$RR/header-looking-no-newline" | tr -d ' \n')
RR_BINARY_HEX=$(od -An -v -tx1 "$RR/binary-input" | tr -d ' \n')
if review_tree_capture "$RR" "$RR_FRAMED_DIGEST" "$RR_FRAMED_SNAPSHOT" \
   && accepted_snapshot_validate "$RR_FRAMED_SNAPSHOT" "$RR_FRAMED_DIGEST" "$RR_FRAMED_HEAD" \
   && grep -q '^snapshot-version: 2$' "$RR_FRAMED_SNAPSHOT" \
   && grep -qF "$RR_HEADER_HEX" "$RR_FRAMED_SNAPSHOT" \
   && grep -qF "$RR_BINARY_HEX" "$RR_FRAMED_SNAPSHOT"; then
  ok "snapshot framing retains header-looking, binary, and no-final-newline bytes injectively"
else
  bad "snapshot framing retains header-looking, binary, and no-final-newline bytes injectively" \
    "the v2 snapshot was malformed or did not retain exact payload hex"
fi
cp "$RR_FRAMED_SNAPSHOT" "$RR_FRAMED_SNAPSHOT.bad"
printf 'untracked: malformed\n' >> "$RR_FRAMED_SNAPSHOT.bad"
if ! accepted_snapshot_validate "$RR_FRAMED_SNAPSHOT.bad" "$RR_FRAMED_DIGEST" "$RR_FRAMED_HEAD"; then
  ok "completed snapshot validation rejects bytes outside the declared frame"
else
  bad "completed snapshot validation rejects bytes outside the declared frame" "an extra record was accepted"
fi

# Retained v1 rounds are historical series evidence. Parse their fixed structural prefix so
# raw payload that repeats headers or sentinels cannot poison counting, without allowing the
# old raw format to be emitted by the current writer.
RR_HIST_KEY=nd/historical/v1
mint_at "$RR" "$RR_HIST_KEY"
RR_HIST_ROUND=$(accepted_rounds_list "$RR" "$RR_HIST_KEY")
RR_HIST_DIR="$(accepted_rounds_root "$RR" "$RR_HIST_KEY")/$RR_HIST_ROUND"
printf 'snapshot-version: 1\ntree: %s\nhead: %s\nat: 2026-08-12T00:00:00Z\n--- tracked diff (binary-safe patch) ---\nfixture\n--- untracked inputs ---\nhead: injected\nsnapshot-version: 9\n--- tracked diff (binary-safe patch) ---\n--- untracked inputs ---' \
  "$RR_FRAMED_DIGEST" "$RR_FRAMED_HEAD" > "$RR_HIST_DIR/snapshot.txt"
RR_HIST_SHA=$(review_sha256_file "$RR_HIST_DIR/snapshot.txt")
perl -pi -e "s/^snapshot-sha256: .*/snapshot-sha256: $RR_HIST_SHA/" "$RR_HIST_DIR/review.md"
if [ "$(accepted_rounds_list "$RR" "$RR_HIST_KEY")" = "$RR_HIST_ROUND" ]; then
  ok "historical v1 accepted rounds remain countable with hostile raw payload lines"
else
  bad "historical v1 accepted rounds remain countable with hostile raw payload lines" \
    "the historical series was poisoned or disappeared"
fi
rm -rf "$(accepted_rounds_root "$RR" "$RR_HIST_KEY")"

rm -f "$RR/header-looking-no-newline" "$RR/binary-input" \
  "$RR_FRAMED_SNAPSHOT" "$RR_FRAMED_SNAPSHOT.bad"

mkfifo "$RR/untracked-special"
if ! review_request_capture "$RR" 0990-t1 "$RR_CAPTURE_DIGEST" >/dev/null 2>&1; then
  ok "review snapshot capture fails closed on an unsupported untracked node"
else
  bad "review snapshot capture fails closed on an unsupported untracked node" "FIFO received a generic snapshot identity"
fi
rm "$RR/untracked-special"
OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-ready.sh" stage 0990 2 "$RRM" 2>&1); got=$?
[ "$got" = 2 ] && ok "a manifest cannot be staged for a different task" \
  || bad "a manifest cannot be staged for a different task" "$OUT"

RRBAD=$(mktemp)
sed '/## Limits/,$d' "$RRM" > "$RRBAD"
OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-ready.sh" stage 0990 1 "$RRBAD" 2>&1); got=$?
[ "$got" = 2 ] && ok "an incomplete readiness schema is refused before review" \
  || bad "an incomplete readiness schema is refused before review" "$OUT"
printf '\nChanged after staging.\n' >> "$RR/docs/design/0990-review.md"
OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-ready.sh" status 0990 1 2>&1); got=$?
[ "$got" = 3 ] && ok "a tree edit makes the staged request stale" \
  || bad "a tree edit makes the staged request stale" "$OUT"
( cd "$RR" && git checkout -q -- docs/design/0990-review.md )

# Accepted-round consumers share one canonical series: readiness history, dashboard
# telemetry, and calibration all read the same directory and reject malformed evidence.
rr_case_hash() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'
  fi
}
rr_rebind_round() {
  local dir="$1" request_sha snapshot_sha tmp
  request_sha=$(rr_case_hash "$dir/request.md") || return 1
  snapshot_sha=$(rr_case_hash "$dir/snapshot.txt") || return 1
  tmp="$dir/review.bind"
  awk -v request_sha="$request_sha" -v snapshot_sha="$snapshot_sha" '
    /^request-sha256: / { print "request-sha256: " request_sha; next }
    /^snapshot-sha256: / { print "snapshot-sha256: " snapshot_sha; next }
    { print }
  ' "$dir/review.md" > "$tmp" && mv "$tmp" "$dir/review.md"
}

mint_at "$RR" "0990-t1" findings
R1=$(. "$RR/core/accepted-rounds.sh"; accepted_rounds_list "$RR" 0990-t1)
D1=${R1%%-*}
RR_SOURCE="$RR/.deliver/reviews/accepted/0990-t1/$R1"
RR_HEAD=$(git -C "$RR" rev-parse HEAD)
{
  printf 'request-version: 1\ndoc: 0990\ntask: 1\ntree: %s\nhead: %s\n---\n' "$D1" "$RR_HEAD"
  cat "$RRM"
} > "$RR_SOURCE/request.md"
rr_rebind_round "$RR_SOURCE"

OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-ready.sh" stage 0990 1 "$RRM" 2>&1); got=$?
[ "$got" = 2 ] && ok "a later request cannot claim it is the first review" \
  || bad "a later request cannot claim it is the first review" "$OUT"
RR_NEXT=$(mktemp)
sed "s/- none — first review/- $R1#1 | fixed | the complete fixture family is closed/" "$RRM" > "$RR_NEXT"
OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-ready.sh" stage 0990 1 "$RR_NEXT" 2>&1); got=$?
[ "$got" = 0 ] && ok "a later request accounts for every accepted prior finding" \
  || bad "a later request accounts for every accepted prior finding" "$OUT"

CLAUDE_PROJECT_DIR="$RR" node "$S/review-dashboard.mjs" --output "$RR/dashboard" >/dev/null 2>&1
if jq -e --arg round "$R1" '.summary.tasks == 1 and .summary.rounds == 1 and .summary.findings == 1 and .summary.unknownFindings == 0 and .summary.classifiedFindings == 1 and .summary.tokenCost == null and .summary.calibrationRecall == null and .tasks[0].key == "0990-t1" and .tasks[0].rounds[0].roundId == $round' "$RR/dashboard/report.json" >/dev/null; then
  ok "the dashboard derives convergence metrics from accepted rounds only"
else
  bad "the dashboard derives convergence metrics from accepted rounds only" "$(cat "$RR/dashboard/report.json" 2>/dev/null)"
fi
[ -f "$RR/dashboard/index.html" ] && ok "the local dashboard renders a static HTML surface" \
  || bad "the local dashboard renders a static HTML surface" "index.html missing"

# --stdout has to survive a pipe. Node's stdout is asynchronous when it is a pipe, so a report
# larger than the pipe buffer was truncated mid-write by the exit that followed it — and the
# truncation parsed as valid JSON up to the cut, so it read as a smaller report rather than a
# broken one. Every other check here redirects to a file or /dev/null, both synchronous, which
# is exactly why it went unseen. Pad one finding past the buffer and compare the two routes.
RR_REVIEW="$RR_SOURCE/review.md"
cp "$RR_REVIEW" "$RR/review.unpadded"
RR_PAD=$(awk 'BEGIN { while (i++ < 4000) printf "padding-past-the-pipe-buffer " }')
awk -v pad="$RR_PAD" '/^\[(BLOCKING|CONCERN|SCOPE)\] / && !done { print $0 " " pad; done=1; next } { print }' \
  "$RR/review.unpadded" > "$RR_REVIEW"
RR_PIPED=$(CLAUDE_PROJECT_DIR="$RR" node "$S/review-dashboard.mjs" --stdout 2>/dev/null | cat)
RR_BYTES=$(printf '%s' "$RR_PIPED" | wc -c | tr -d '[:space:]')
if [ "$RR_BYTES" -gt 65536 ] \
   && printf '%s' "$RR_PIPED" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{JSON.parse(s)})' 2>/dev/null; then
  ok "a report larger than the pipe buffer reaches stdout whole"
else
  bad "a report larger than the pipe buffer reaches stdout whole" "piped $RR_BYTES bytes, truncated or unparseable"
fi
mv "$RR/review.unpadded" "$RR_REVIEW"

printf 'malformed\n' > "$RR/.deliver/reviews/accepted/0990-t1/not-a-round"
CLAUDE_PROJECT_DIR="$RR" node "$S/review-dashboard.mjs" --stdout >/dev/null 2>&1; got=$?
[ "$got" != 0 ] && ok "dashboard telemetry rejects malformed evidence for the consumed key" \
  || bad "dashboard telemetry rejects malformed evidence for the consumed key" "malformed round was skipped"
review_request_receipts "$RR" 0990-t1 >/dev/null 2>&1; got=$?
[ "$got" = 1 ] && ok "readiness history rejects the same malformed accepted series" \
  || bad "readiness history rejects the same malformed accepted series" "exit $got"
rm "$RR/.deliver/reviews/accepted/0990-t1/not-a-round"

mkdir -p "$RR/.deliver/reviews/accepted/nd/main/broken"
printf 'diagnostic\n' > "$RR/.deliver/reviews/accepted/nd/main/broken/not-a-round"
CLAUDE_PROJECT_DIR="$RR" node "$S/review-dashboard.mjs" --stdout >/dev/null 2>&1; got=$?
[ "$got" = 0 ] && ok "dashboard corruption is scoped away from unrelated non-delivery keys" \
  || bad "dashboard corruption is scoped away from unrelated non-delivery keys" "unrelated evidence blocked telemetry"

mv "$RR/.deliver/reviews/accepted" "$RR/.deliver/reviews/accepted-real"
ln -s accepted-real "$RR/.deliver/reviews/accepted"
CLAUDE_PROJECT_DIR="$RR" node "$S/review-dashboard.mjs" --stdout >/dev/null 2>&1; got=$?
[ "$got" != 0 ] && ok "the dashboard rejects a symlinked accepted-round root" \
  || bad "the dashboard rejects a symlinked accepted-round root" "accepted series disappeared"
rm "$RR/.deliver/reviews/accepted"
mv "$RR/.deliver/reviews/accepted-real" "$RR/.deliver/reviews/accepted"

mkdir -p "$RR/nested/path"
( cd "$RR/nested/path" && node "$RR/core/scripts/review-dashboard.mjs" --output "$RR/dashboard-subdir" >/dev/null 2>&1 )
jq -e '.summary.rounds == 1' "$RR/dashboard-subdir/report.json" >/dev/null \
  && ok "the dashboard resolves accepted history from a repository subdirectory" \
  || bad "the dashboard resolves accepted history from a repository subdirectory" "subdirectory report diverged"

RR_FAILURE=$(mktemp); printf 'family: fixture-finding\nfailure-scenario: sibling input reaches the wrong outcome.\n' > "$RR_FAILURE"
OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-calibration.sh" candidate fixture-case 0990-t1 "$R1" fixture-finding "$RR_FAILURE" 2>&1); got=$?
[ "$got" = 0 ] && ok "a preserved review can become an ignored calibration candidate" \
  || bad "a preserved review can become an ignored calibration candidate" "$OUT"
OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-calibration.sh" verify-candidate "$RR/.deliver/calibration-candidates/fixture-case" 2>&1); got=$?
[ "$got" = 0 ] && ok "the calibration case schema is machine-checkable" \
  || bad "the calibration case schema is machine-checkable" "$OUT"
RR_CLEAN_CHECKOUT=$(mktemp -d)
cp -R "$RR/core" "$RR_CLEAN_CHECKOUT/core"
cp -R "$RR/.deliver/calibration-candidates/fixture-case" "$RR_CLEAN_CHECKOUT/fixture-case"
rr_case_hash_file="$RR_CLEAN_CHECKOUT/fixture-case/case.json"
jq '.status="confirmed-human-reviewed"' "$rr_case_hash_file" > "$rr_case_hash_file.tmp" && mv "$rr_case_hash_file.tmp" "$rr_case_hash_file"
OUT=$(CLAUDE_PROJECT_DIR="$RR_CLEAN_CHECKOUT" "$RR_CLEAN_CHECKOUT/core/scripts/review-calibration.sh" verify-case "$RR_CLEAN_CHECKOUT/fixture-case" 2>&1); got=$?
[ "$got" = 0 ] && ok "a promoted calibration case verifies without ignored source history" \
  || bad "a promoted calibration case verifies without ignored source history" "$OUT"
rm -rf "$RR_CLEAN_CHECKOUT"
case "$(cat "$RR/.deliver/calibration-candidates/fixture-case/case.json")" in
  *candidate-human-confirmation-required*) ok "candidate creation cannot claim human promotion" ;;
  *) bad "candidate creation cannot claim human promotion" "missing candidate status" ;;
esac
for MUTATION in directory tree request snapshot review expected request-body snapshot-body relation sequence status; do
  RR_MUT="$RR/.deliver/calibration-candidates/mutated-$MUTATION"
  cp -R "$RR/.deliver/calibration-candidates/fixture-case" "$RR_MUT"
  if [ "$MUTATION" != directory ]; then
    jq --arg id "mutated-$MUTATION" '.id=$id' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" \
      && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json"
  fi
  case "$MUTATION" in
    directory) ;;
    tree) jq '.source.tree="aaaaaaaaaaaaaaaa"' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json" ;;
    request) sed -i.bak 's/^tree: .*/tree: aaaaaaaaaaaaaaaa/' "$RR_MUT/request.md"; rm "$RR_MUT/request.md.bak"; RR_SHA=$(rr_case_hash "$RR_MUT/request.md"); jq --arg s "$RR_SHA" '.artifacts.requestSha256=$s' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json" ;;
    snapshot) sed -i.bak 's/^head: .*/head: wrong/' "$RR_MUT/snapshot.txt"; rm "$RR_MUT/snapshot.txt.bak"; RR_SHA=$(rr_case_hash "$RR_MUT/snapshot.txt"); jq --arg s "$RR_SHA" '.artifacts.snapshotSha256=$s' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json" ;;
    review) sed -i.bak 's/Family: fixture-finding/Family: other-family/' "$RR_MUT/review.md"; rm "$RR_MUT/review.md.bak"; RR_SHA=$(rr_case_hash "$RR_MUT/review.md"); jq --arg s "$RR_SHA" '.artifacts.reviewSha256=$s' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json" ;;
    expected) sed -i.bak 's/^family: .*/family: other-family/' "$RR_MUT/expected.md"; rm "$RR_MUT/expected.md.bak"; RR_SHA=$(rr_case_hash "$RR_MUT/expected.md"); jq --arg s "$RR_SHA" '.artifacts.expectedSha256=$s' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json" ;;
    request-body) sed -n '1,/^---$/p' "$RR_MUT/request.md" > "$RR_MUT/body.tmp" && mv "$RR_MUT/body.tmp" "$RR_MUT/request.md"; RR_SHA=$(rr_case_hash "$RR_MUT/request.md"); jq --arg s "$RR_SHA" '.artifacts.requestSha256=$s' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json" ;;
    snapshot-body) sed -n '1,/^at: /p' "$RR_MUT/snapshot.txt" > "$RR_MUT/body.tmp" && mv "$RR_MUT/body.tmp" "$RR_MUT/snapshot.txt"; RR_SHA=$(rr_case_hash "$RR_MUT/snapshot.txt"); jq --arg s "$RR_SHA" '.artifacts.snapshotSha256=$s' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json" ;;
    relation) sed -i.bak 's/Relation: original/Relation: invented/' "$RR_MUT/review.md"; rm "$RR_MUT/review.md.bak"; RR_SHA=$(rr_case_hash "$RR_MUT/review.md"); jq --arg s "$RR_SHA" '.artifacts.reviewSha256=$s' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json" ;;
    sequence) sed -i.bak 's/^prior-rounds: 0$/prior-rounds: 99/' "$RR_MUT/review.md"; rm "$RR_MUT/review.md.bak"; RR_SHA=$(rr_case_hash "$RR_MUT/review.md"); jq --arg s "$RR_SHA" '.source.priorRounds=99 | .artifacts.reviewSha256=$s' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json" ;;
    status) jq '.status="promoted-without-human"' "$RR_MUT/case.json" > "$RR_MUT/case.tmp" && mv "$RR_MUT/case.tmp" "$RR_MUT/case.json" ;;
  esac
  OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-calibration.sh" verify-candidate "$RR_MUT" 2>&1); got=$?
  [ "$got" = 2 ] && ok "calibration verification rejects a mismatched $MUTATION relation" \
    || bad "calibration verification rejects a mismatched $MUTATION relation" "$OUT"
done
OUT=$(CLAUDE_PROJECT_DIR="$RR" "$S/review-calibration.sh" candidate a 0990-t1 "$R1" fixture-finding "$RR_FAILURE" 2>&1); got=$?
[ "$got" = 1 ] && [ ! -e "$RR/.deliver/calibration-candidates/a" ] \
  && ok "an invalid calibration id leaves no poisoned partial candidate" \
  || bad "an invalid calibration id leaves no poisoned partial candidate" "$OUT"
RC1=$(mktemp); RC2=$(mktemp)
( CLAUDE_PROJECT_DIR="$RR" "$S/review-calibration.sh" candidate race-case 0990-t1 "$R1" fixture-finding "$RR_FAILURE" >/dev/null 2>&1; echo $? > "$RC1" ) & P1=$!
( CLAUDE_PROJECT_DIR="$RR" "$S/review-calibration.sh" candidate race-case 0990-t1 "$R1" fixture-finding "$RR_FAILURE" >/dev/null 2>&1; echo $? > "$RC2" ) & P2=$!
wait "$P1"; wait "$P2"
RACE_CODES="$(cat "$RC1") $(cat "$RC2")"
case "$RACE_CODES" in "0 2"|"2 0")
  if [ -f "$RR/.deliver/calibration-candidates/race-case/case.json" ] \
     && [ "$(find "$RR/.deliver/calibration-candidates/race-case" -mindepth 1 -type d | wc -l | tr -d ' ')" = 0 ]; then
    ok "two candidate writers publish once without nesting or clobbering"
  else bad "two candidate writers publish once without nesting or clobbering" "published shape was not singular"; fi ;;
  *) bad "two candidate writers publish once without nesting or clobbering" "exit codes were $RACE_CODES" ;;
esac
rm -f "$RC1" "$RC2"

CALIBRATION_CASES_OK=1
for CALIBRATION_CASE in "$REAL_ROOT/core/reviewer-calibration/cases"/*; do
  [ -e "$CALIBRATION_CASE" ] || continue
  CLAUDE_PROJECT_DIR="$REAL_ROOT" "$S/review-calibration.sh" verify-case "$CALIBRATION_CASE" >/dev/null 2>&1 \
    || CALIBRATION_CASES_OK=0
done
[ "$CALIBRATION_CASES_OK" = 1 ] && ok "every committed calibration case satisfies the confirmed lifecycle contract" \
  || bad "every committed calibration case satisfies the confirmed lifecycle contract" "a committed case failed verification"
rm -f "$RRM" "$RRBAD" "$RR_NEXT" "$RR_FAILURE"
rm -rf "$RR"


echo
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
