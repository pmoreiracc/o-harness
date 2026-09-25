#!/usr/bin/env bash
# ADR-0052: selection, execution and fixture isolation; no real product/host suites nested here.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd) || exit 1
. "$ROOT/core/test-fixture.sh" || exit 1
FIX=$(mktemp -d) || exit 1
trap 'rm -rf "$FIX"' EXIT
REPO="$FIX/repo"
mkdir -p "$REPO/core/scripts" "$REPO/core/hooks" "$REPO/.codex/hooks" "$REPO/bin"
pass=0 fail=0
check() {
  local label="$1"; shift
  if "$@"; then pass=$((pass+1)); printf '  ok    %s\n' "$label"
  else fail=$((fail+1)); printf '  FAIL  %s\n' "$label"; fi
}
# ADR-0052 / testing.md §6: product tests exercise GitHub's merge ref; history validation
# needs the authored head. Keep this cheap wiring proof in the suite selected by either YAML.
product_wiring() { awk '
  # These entry points use GitHub default execution settings, not inherited overrides.
  /^["\047]?defaults["\047]?[[:space:]]*:/ { gated_selection = 1 }
  /^  [[:alnum:]_-]+:/ {
    verify = ($0 == "  verify:"); select = ($0 == "  select:")
    steps = block = options = outputs = selection = 0
  }
  (verify || select) && /^    [[:alnum:]_-]+:/ {
    steps = ($0 == "    steps:"); outputs = ($0 == "    outputs:")
    block = options = selection = 0
  }
  select && outputs && $0 == "      product: ${{ steps.selection.outputs.product }}" { product_output++ }
  select && steps && /^      - / { selection = ($0 == "      - id: selection") }
  selection && $0 == "        run: core/scripts/verify-change.sh origin/${{ github.base_ref }} plan >> \"$GITHUB_OUTPUT\"" { plan++ }
  select && (/^    ["\047]?(defaults|if|continue-on-error)["\047]?[[:space:]]*:/ ||
    (selection && /^        ["\047]?(shell|working-directory|if|continue-on-error)["\047]?[[:space:]]*:/)) { gated_selection = 1 }
  verify && $0 == "    needs: select" { dependency = 1 }
  verify && $0 == "    if: needs.select.outputs.product == \0471\047" { conditional = 1 }
  verify && steps && $0 == "      - uses: actions/checkout@v4" { checkout++; block = 1; next }
  block && /^      - / { block = options = 0 }
  block && /^        [[:alnum:]_-]+:/ { options = ($0 == "        with:") }
  options && /^          ref:/ { explicit_ref = 1 }
  END { exit !(plan == 1 && product_output == 1 && !gated_selection && dependency &&
    conditional && checkout == 1 && !explicit_ref) }
' "$1"; }
process_wiring() { awk '
  /^["\047]?defaults["\047]?[[:space:]]*:/ { gated = 1 }
  function close_step() {
    if (runner_step) { runner++; if (step_condition) gated = 1 }
    runner_step = step_condition = 0
  }
  /^  [[:alnum:]_-]+:/ {
    close_step(); verify = ($0 == "  verify:"); steps = block = options = 0
  }
  verify && /^    [[:alnum:]_-]+:/ {
    close_step(); steps = ($0 == "    steps:"); block = options = 0
  }
  verify && /^    ["\047]?(defaults|if|continue-on-error)["\047]?[[:space:]]*:/ { gated = 1 }
  steps && /^      - / { close_step(); block = options = 0 }
  steps && $0 == "      - uses: actions/checkout@v4" { checkout++; block = 1; next }
  block && /^      - / { block = options = 0 }
  block && /^        [[:alnum:]_-]+:/ { options = ($0 == "        with:") }
  options && $0 == "          ref: ${{ github.event.pull_request.head.sha }}" { head++ }
  steps && /^        ["\047]?(shell|working-directory|if|continue-on-error)["\047]?[[:space:]]*:/ { step_condition = 1 }
  steps && $0 == "        run: core/scripts/verify-change.sh origin/${{ github.base_ref }} ci" { runner_step = 1 }
  END { close_step(); exit !(checkout == 1 && head == 1 && runner == 1 && !gated) }
' "$1"; }
check 'product verification consumes the selector output and keeps the merge ref' \
  product_wiring "$ROOT/.github/workflows/pr.yml"
check 'process CI unconditionally runs the shared verifier on authored history' \
  process_wiring "$ROOT/.github/workflows/delivery.yml"
commented_wiring() {
  awk '
    /^          ref:/ || /^        run: .* ci$/ {
      print "# " $0
      if ($0 ~ /run:/) print "        run: \"true\""
      next
    }
    { print }
  ' "$ROOT/.github/workflows/delivery.yml" > "$FIX/commented.yml"
  ! process_wiring "$FIX/commented.yml"
}
displaced_wiring() {
  awk -v location="$1" '
    /^          ref:/ { next }
    { print }
    (location == "step" && /^      - name: Select verification$/) ||
    (location == "input" && /^          fetch-depth: 0$/) {
      print "        env:"
      print "          ref: ${{ github.event.pull_request.head.sha }}"
    }
  ' "$ROOT/.github/workflows/delivery.yml" > "$FIX/displaced.yml"
  ! process_wiring "$FIX/displaced.yml"
}
commented_product() {
  sed '/^    if: needs.select.outputs.product/s/^/# /' \
    "$ROOT/.github/workflows/pr.yml" > "$FIX/product-comment.yml"
  ! product_wiring "$FIX/product-comment.yml"
}
disconnected_product() {
  sed '/^    needs: select$/d' "$ROOT/.github/workflows/pr.yml" > "$FIX/product-disconnected.yml"
  ! product_wiring "$FIX/product-disconnected.yml"
}
conditional_process() {
  sed '/^  verify:$/a\
    if: false
' "$ROOT/.github/workflows/delivery.yml" > "$FIX/process-conditional.yml"
  ! process_wiring "$FIX/process-conditional.yml"
}
overridden_shell() {
  local workflow="$1" location="$2" predicate job
  if [ "$workflow" = pr ]; then predicate=product_wiring; job=select
  else predicate=process_wiring; job=verify; fi
  awk -v location="$location" -v job="$job" '
    location == "workflow" && /^jobs:$/ {
      print "defaults: {run: {shell: \"echo {0}\"}}"
    }
    { print }
    location == "job" && $0 == "  " job ":" {
      print "    defaults: {run: {shell: \"echo {0}\"}}"
    }
    location == "step" && /^        run: .*verify-change.sh/ &&
      ((job == "select" && / plan /) || (job == "verify" && / ci$/)) {
      print "        shell: echo {0}"
    }
  ' "$ROOT/.github/workflows/$workflow.yml" > "$FIX/overridden.yml"
  ! "$predicate" "$FIX/overridden.yml"
}
check 'commented process gates cannot satisfy active workflow wiring' commented_wiring
check 'an authored-head value outside checkout cannot satisfy its ref contract' displaced_wiring step
check 'a checkout environment variable cannot satisfy its ref input' displaced_wiring input
check 'a commented product condition cannot satisfy selection wiring' commented_product
check 'product verification cannot silently lose its selector dependency' disconnected_product
check 'process verification cannot be skipped by a job condition' conditional_process
for workflow in pr delivery; do
  for location in step job workflow; do
    check "$workflow rejects a $location shell override that bypasses verification" \
      overridden_shell "$workflow" "$location"
  done
done
cp "$ROOT/core/scripts/verify-change.sh" "$REPO/core/scripts/verify-change.sh"
for suite in core/scripts/verify-change.test.sh core/hooks/test.sh adapters/codex/test.sh \
  core/scripts/test.sh core/review-workflow.test.sh; do
  cat > "$REPO/$suite" <<'EOF'
#!/usr/bin/env bash
printf 'start %s\n' "$0" >> "$VERIFY_LOG"
[ -z "${GIT_PREFIX:-}" ] || exit 9
sleep 0.05
printf 'end %s\n' "$0" >> "$VERIFY_LOG"
case "${VERIFY_FAIL:-}:$0" in
  suites:core/hooks/test.sh|suites:core/scripts/test.sh) echo "failure:$0"; exit 1 ;;
esac
EOF
done
for name in verify-docs verify-roadmap verify-design verify-delivery; do
  cat > "$REPO/core/scripts/$name.sh" <<'EOF'
#!/usr/bin/env bash
printf 'verifier %s %s\n' "${0##*/}" "$*" >> "$VERIFY_LOG"
[ "${VERIFY_FAIL:-}" != delivery ] || [ "${0##*/}" != verify-delivery.sh ]
EOF
done
for name in pnpm node; do
  cat > "$REPO/bin/$name" <<'EOF'
#!/usr/bin/env bash
printf '%s %s\n' "${0##*/}" "$*" >> "$VERIFY_LOG"
if [ "$*" = 'exec turbo run typecheck test --affected' ]; then
  printf '%s\n' 'cache hit, replaying logs cached-package' 'cache miss, executing fresh-package' \
    'Test Files  1 passed (1)' 'Duration  3.36s' 'Cached: 1 cached, 2 total'
fi
[ "${VERIFY_FAIL:-}" != product ] || [ "${0##*/}" != pnpm ]
EOF
done
chmod +x "$REPO"/bin/* "$REPO"/core/scripts/*.sh
git -C "$REPO" init -q -b main || exit 1
git -C "$REPO" config user.email test@example.com
git -C "$REPO" config user.name 'Verification fixture'
advance() {
  git -C "$REPO" add -A && git -C "$REPO" commit -qm fixture \
    && git -C "$REPO" update-ref refs/remotes/origin/main HEAD
}
advance || exit 1
invoke() {
  : > "$FIX/commands"
  (cd "$REPO" && PATH="$REPO/bin:$PATH" VERIFY_LOG="$FIX/commands" \
    core/scripts/verify-change.sh "${2:-origin/main}" "${1:-review}") > "$FIX/output" 2>&1
}
plan_is() {
  invoke plan && [ "$(cut -d= -f2 "$FIX/output" | tr '\n' ' ')" = "$1 " ]
}

# One representative per owner/dependency edge, not every filename with the same rule.
while IFS='|' read -r path expected; do
  mkdir -p "$REPO/$(dirname "$path")"
  [ ! -f "$REPO/$path" ] || cp "$REPO/$path" "$FIX/prior"
  printf 'fixture\n' > "$REPO/$path"
  check "selection: $path" plan_is "$expected"
  if [ -f "$FIX/prior" ]; then mv "$FIX/prior" "$REPO/$path"; else rm -f "$REPO/$path"; fi
done <<'EOF'
packages/example/src/example.ts|1 1 0 0 0 0 0 0
CLAUDE.md|0 0 0 0 0 0 0 0
AGENTS.md|0 0 0 0 1 0 0 0
packages/example/AGENTS.md|0 0 0 0 1 0 0 0
core/README.md|0 0 0 0 0 0 0 0
.github/scripts/drift.sh|1 0 0 0 0 0 0 1
.github/workflows/pr.yml|1 0 1 0 0 0 0 1
.github/workflows/delivery.yml|0 0 1 1 1 1 1 1
core/hooks/adr-immutability.sh|0 0 0 1 1 0 0 0
workflows/deliver/SKILL.md|0 0 0 0 1 1 0 0
prompts/invariant-reviewer.md|0 0 0 0 1 0 1 0
.agents/skills/deliver/SKILL.md|0 0 0 0 1 0 0 0
core/scripts/complete.sh|0 0 0 0 0 1 1 0
core/scripts/review-dashboard.mjs|0 1 0 0 0 1 1 0
core/scripts/start.sh|0 0 0 0 1 1 0 0
core/scripts/verify-docs.sh|0 0 1 0 0 1 0 0
core/review-workflow.sh|0 0 1 1 1 1 1 0
EOF

mkdir -p "$REPO/packages/example" "$REPO/workflows/deliver"
printf 'product\n' > "$REPO/packages/example/product.ts"
printf 'documentation\n' > "$REPO/CLAUDE.md"
git -C "$REPO" add -A && git -C "$REPO" commit -qm product || exit 1
check 'committed product plus CLAUDE documentation stays product-only' plan_is '1 1 0 0 0 0 0 0'
printf 'skill\n' > "$REPO/workflows/deliver/SKILL.md"
printf 'adapter\n' > "$REPO/.agents/skills/deliver/SKILL.md"
mixed() {
  local mode
  for mode in review pre-push; do
    invoke "$mode" && grep -qF 'pnpm exec turbo run typecheck test --affected' "$FIX/commands" \
      && grep -qF 'pnpm exec eslint -- packages/example/product.ts' "$FIX/commands" \
      && [ "$(grep -c '^start ' "$FIX/commands")" = 2 ] \
      && grep -qFx 'start adapters/codex/test.sh' "$FIX/commands" \
      && grep -qFx 'start core/scripts/test.sh' "$FIX/commands" \
      && grep -qF 'cache hit, replaying logs cached-package' "$FIX/output" \
      && grep -qF 'cache miss, executing fresh-package' "$FIX/output" \
      && grep -qF 'Duration  3.36s' "$FIX/output" \
      && grep -qF 'Cached: 1 cached, 2 total' "$FIX/output" || return 1
  done
}
check 'review and pre-push run the mixed union and retain successful product cache/timing evidence' mixed
advance || exit 1
mv "$REPO/packages/example/product.ts" "$REPO/product-moved.ts"
git -C "$REPO" add -A
check 'a staged rename out of product still selects the deleted owner' plan_is '1 1 0 0 0 0 0 0'
advance || exit 1
rm "$REPO/workflows/deliver/SKILL.md"
check 'an unstaged harness deletion still selects its consumers' plan_is '0 0 0 0 1 1 0 0'
advance || exit 1

printf 'unknown\n' > "$REPO/.github/new-engine.toml"
unknown() {
  invoke; local status=$?
  [ "$status" = 2 ] && [ ! -s "$FIX/commands" ] \
    && grep -qF "$1" "$FIX/output" \
    && grep -qF 'Recommended owner:' "$FIX/output"
}
check 'an unclassified governed path stops before checks and asks for an owner' unknown .github/new-engine.toml
rm "$REPO/.github/new-engine.toml"
mkdir -p "$REPO/core/prompts"
printf 'unknown policy\n' > "$REPO/core/prompts/reviewer-policy.md"
check 'unknown harness Markdown is not exempt from ownership' unknown core/prompts/reviewer-policy.md
rm "$REPO/core/prompts/reviewer-policy.md"
bad_base() { ! invoke review no-such-base && [ ! -s "$FIX/commands" ]; }
check 'an unresolved comparison base fails before checks' bad_base

printf 'shared\n' > "$REPO/core/review-workflow.sh"
parallel_failures() {
  GIT_PREFIX=contaminated VERIFY_FAIL=suites invoke; local status=$?
  [ "$status" = 1 ] \
    && grep -qFx '        failure:core/hooks/test.sh' "$FIX/output" \
    && grep -qFx '        failure:core/scripts/test.sh' "$FIX/output" \
    && awk '$1 == "start" { active++; starts++; if (active > max) max=active }
      $1 == "end" { active--; ends++ }
      END { exit !(max == 2 && active == 0 && starts == 5 && ends == 5) }' "$FIX/commands"
}
check 'two concurrent suites maximum, isolated Git environment, both failures retained and all joined' parallel_failures
advance || exit 1

printf 'export default [];\n' > "$REPO/eslint.config.js"
product_failure() {
  VERIFY_FAIL=product invoke; local status=$?
  [ "$status" = 1 ] && grep -qFx 'pnpm lint' "$FIX/commands" \
    && grep -qF 'pnpm exec turbo run typecheck test --affected' "$FIX/commands"
}
check 'shared lint configuration selects full lint and product failure fails verification' product_failure
ci_product() { invoke ci && ! grep -q '^pnpm ' "$FIX/commands" \
  && [ "$(grep -c '^verifier ' "$FIX/commands")" = 4 ]; }
check 'CI delegates product checks to product CI but keeps process outcomes' ci_product
advance || exit 1
net_zero() { VERIFY_FAIL=delivery invoke pre-push; local status=$?
  [ "$status" = 1 ] && grep -qFx 'verifier verify-delivery.sh origin/main' "$FIX/commands"; }
check 'pre-push rejects invalid history even with a net-zero tree diff' net_zero

mkdir -p "$REPO/docs/design"
printf 'design\n' > "$REPO/docs/design/0999-fixture.md"
design_review() { invoke && grep -qFx 'verifier verify-design.sh --review 0999' "$FIX/commands" \
  && ! grep -qE '^(pnpm|start)|verify-delivery' "$FIX/commands"; }
check 'doc-only review targets the pre-claim design contract without regression/history suites' design_review
rm "$REPO/docs/design/0999-fixture.md"
cp "$ROOT/core/scripts/verify-docs.sh" "$REPO/core/scripts/verify-docs.sh"
cp "$ROOT/core/lib.sh" "$REPO/core/lib.sh"
advance || exit 1
mkdir -p "$REPO/docs/decisions"
printf '# Decisions\n' > "$REPO/docs/decisions/README.md"
printf '# Invalid untracked ADR\n' > "$REPO/docs/decisions/0998-invalid.md"
invalid_doc() { ! invoke && grep -qF 'FAIL  doc lifecycle' "$FIX/output"; }
check 'the real doc validator rejects malformed untracked documentation before review' invalid_doc

# A real nested Git fixture proves both ignored-state exclusion and untracked-code inclusion.
printf 'core/delivery-policy.local.json\n.deliver/\n' > "$REPO/.gitignore"
printf '{"continuation_window_tasks":1}\n' > "$REPO/core/delivery-policy.local.json"
printf 'new code\n' > "$REPO/core/untracked.sh"
rm "$REPO/core/lib.sh" # a tracked deletion must not break fixture creation
fixture_hygiene() (
  export GIT_DIR="$REPO/.git" GIT_WORK_TREE="$REPO" GIT_INDEX_FILE="$REPO/.git/index"
  . "$ROOT/core/test-fixture.sh" || exit 1
  copy_harness "$REPO" "$FIX/copy" core || exit 1
  [ ! -e "$FIX/copy/core/delivery-policy.local.json" ] \
    && [ ! -e "$FIX/copy/core/lib.sh" ] \
    && [ -f "$FIX/copy/core/untracked.sh" ] \
    && git -C "$FIX/copy" init -q -b isolated \
    && [ "$(git -C "$REPO" branch --show-current)" = main ] \
    && [ "$(git -C "$FIX/copy" branch --show-current)" = isolated ]
)
check 'fixtures exclude ignored human policy, include new code and own their Git state' fixture_hygiene

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
