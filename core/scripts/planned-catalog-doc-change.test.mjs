import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { chmodSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { isCommittedMetadataOnly, isMetadataOnly } from './planned-catalog-doc-change.mjs';

const scripts = dirname(fileURLToPath(import.meta.url));
const path = 'packages/application/src/planned-capabilities.ts';
// Keep fixtures independent of the real catalog's membership: legitimate delivery
// removes those entries as capabilities become live (ADR-0050).
const base = `import type { CapabilityName, EntitlementKey } from './capability-define.js';
export interface PlannedCapability {
  readonly name: CapabilityName;
  readonly mutation: boolean;
  readonly confirmation: boolean;
  readonly entitlement: EntitlementKey;
  readonly initiative: string;
  readonly intent: string;
  readonly notes?: string;
}
export const plannedCapabilities: readonly PlannedCapability[] = [
  {
    name: 'accounts.create',
    mutation: true,
    confirmation: false,
    entitlement: 'ledger.core',
    initiative: 'ledger-core',
    intent: 'Create an account.',
  },
  {
    name: 'accounts.list',
    mutation: false,
    confirmation: false,
    entitlement: 'ledger.core',
    initiative: 'ledger-core',
    intent: 'List accounts.',
    notes: 'A static note.',
  },
];
`;
const replaceIntent = (value) => base.replace(/intent: '[^']*'/u, `intent: ${value}`);
const changed = replaceIntent("'Updated catalog intent'")
  .replace('confirmation: false', 'confirmation: true')
  .replace(
    "intent: 'Updated catalog intent',",
    "intent: 'Updated catalog intent',\n    notes: 'New documentation',",
  );

test('accepts only the editable literal metadata, including optional notes in both directions', () => {
  assert.equal(isMetadataOnly(base, changed), true);
  assert.equal(isMetadataOnly(changed, base), true);
  assert.equal(isMetadataOnly(base, replaceIntent('`Literal \\`quote\\` and \\${text}`')), true);
  assert.equal(isMetadataOnly(base, replaceIntent("'Escaped \\'quote\\' and \\u0041'")), true);
});

test('keeps entry identity, order, membership and module scaffold on the implementation path', () => {
  const first = base.indexOf('  {', base.indexOf('export const'));
  const firstEnd = base.indexOf('  },', first) + 5;
  const secondEnd = base.indexOf('  },', firstEnd) + 5;
  const cases = [
    base.replace("name: 'accounts.create'", "name: 'accounts.changed'"),
    base.replace('mutation: true', 'mutation: false'),
    base.replace("entitlement: 'ledger.core'", "entitlement: 'other.core'"),
    base.replace("initiative: 'ledger-core'", "initiative: 'other-work'"),
    base.slice(0, first) + base.slice(firstEnd),
    base.slice(0, first) + base.slice(first, firstEnd) + base.slice(first),
    base.slice(0, first) +
      base.slice(firstEnd, secondEnd) +
      base.slice(first, firstEnd) +
      base.slice(secondEnd),
    base.replace('readonly intent: string;', 'readonly intent: unknown;'),
    base.replace('import type', 'import'),
    base + '\nexport const extra = true;\n',
  ];
  for (const candidate of cases) assert.equal(isMetadataOnly(base, candidate), false);
});

test('rejects executable, ambiguous and unsupported syntax without evaluating it', () => {
  for (const value of [
    "(() => 'text')()",
    '`Text ${process.exit(99)}`',
    '`Text \\\\${process.exit(99)}`',
    "String('text')",
    "'text' + 'more'",
    "'bad\\xZZ'",
    "'bad\\01'",
    "'unclosed",
    '`unclosed',
    'true',
  ])
    assert.equal(isMetadataOnly(base, replaceIntent(value)), false, value);
  for (const candidate of [
    base.replace('intent:', 'get intent()'),
    base.replace('intent:', '["intent"]:'),
    base.replace('intent:', "intent: 'first', intent:"),
    base.replace('intent:', 'unknownField:'),
    base.replace('intent:', '...extra, intent:'),
    base.replace('confirmation: false', "confirmation: 'false'"),
    base.replace('confirmation: false,', ''),
    base + '\nprocess.exit(99);',
    base + '\n/* unclosed',
  ]) {
    assert.equal(isMetadataOnly(base, candidate), false);
    assert.equal(isMetadataOnly(candidate, changed), false);
  }
});

test('committed delivery classification admits metadata but preserves all implementation refusals', () => {
  const root = mkdtempSync(join(tmpdir(), 'catalog-delivery-proof-'));
  const file = join(root, path);
  const git = (...args) =>
    execFileSync('git', ['-C', root, ...args], { encoding: 'utf8', stdio: 'pipe' });
  const commit = () => {
    git('add', '-A');
    git(
      '-c',
      'user.name=Fixture',
      '-c',
      'user.email=fixture@example.test',
      'commit',
      '-qm',
      'fixture',
    );
  };
  const verify = (extraEnv = {}) =>
    spawnSync('bash', [join(scripts, 'verify-delivery.sh'), 'main'], {
      cwd: root,
      encoding: 'utf8',
      env: { ...process.env, CLAUDE_PROJECT_DIR: root, GITHUB_HEAD_REF: '', ...extraEnv },
    });
  const expectStatus = (want, extraEnv) => {
    const result = verify(extraEnv);
    assert.equal(result.status, want, result.stdout + result.stderr);
  };
  try {
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, base);
    git('init', '-q', '-b', 'main');
    commit();
    git('switch', '-qc', 'documentation');
    writeFileSync(file, changed);
    mkdirSync(join(root, 'docs/reference'), { recursive: true });
    writeFileSync(join(root, 'docs/reference/capabilities.md'), '# Updated human catalog\n');
    commit();
    assert.equal(isCommittedMetadataOnly(root, 'main', 'HEAD'), true);
    expectStatus(0);

    // A dirty source cannot lend its state to the committed classification.
    writeFileSync(file, base + '\nprocess.exit(99);');
    assert.equal(isCommittedMetadataOnly(root, 'main', 'HEAD'), true);
    commit();
    assert.equal(isCommittedMetadataOnly(root, 'main', 'HEAD'), false);
    expectStatus(1);

    writeFileSync(file, changed);
    writeFileSync(join(dirname(file), 'runtime.ts'), 'export const executable = true;\n');
    commit();
    expectStatus(1);
    rmSync(join(dirname(file), 'runtime.ts'));
    chmodSync(file, 0o755);
    commit();
    assert.equal(isCommittedMetadataOnly(root, 'main', 'HEAD'), false);
    expectStatus(1);

    rmSync(file);
    symlinkSync('replacement.ts', file);
    commit();
    expectStatus(1);
    rmSync(file);
    writeFileSync(file, changed);
    commit();
    expectStatus(0);
    assert.equal(isCommittedMetadataOnly(root, 'missing-revision', 'HEAD'), false);

    const fakeBin = join(root, 'fake-bin');
    mkdirSync(fakeBin);
    const realGit = execFileSync('sh', ['-c', 'command -v git'], { encoding: 'utf8' }).trim();
    const quotedGit = "'" + realGit.replaceAll("'", "'\\''") + "'";
    writeFileSync(
      join(fakeBin, 'git'),
      `#!/bin/sh\nfor arg in "$@"; do [ "$arg" = show ] && exit 1; done\nexec ${quotedGit} "$@"\n`,
    );
    chmodSync(join(fakeBin, 'git'), 0o755);
    expectStatus(1, { PATH: `${fakeBin}:${process.env.PATH}` });
    rmSync(fakeBin, { recursive: true });

    git('mv', path, 'packages/application/src/renamed.ts');
    commit();
    assert.equal(isCommittedMetadataOnly(root, 'main', 'HEAD'), false);
    expectStatus(1);
    assert.equal(isCommittedMetadataOnly(root, 'main', 'main'), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
