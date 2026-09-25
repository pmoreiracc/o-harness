// ADR-0050: prove a documentation-only change without executing either Git revision.
import { execFileSync } from 'node:child_process';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

const catalogPath = 'packages/application/src/planned-capabilities.ts';
const header = `import type { CapabilityName, EntitlementKey } from './capability-define.js';
export interface PlannedCapability {
  readonly name: CapabilityName;
  readonly mutation: boolean;
  readonly confirmation: boolean;
  readonly entitlement: EntitlementKey;
  readonly initiative: string;
  readonly intent: string;
  readonly notes?: string;
}
export const plannedCapabilities: readonly PlannedCapability[] =`;
const required = ['name', 'mutation', 'confirmation', 'entitlement', 'initiative', 'intent'];
const protectedKeys = ['name', 'mutation', 'entitlement', 'initiative'];

// This is deliberately not a general TypeScript parser. Unsupported syntax stays on
// the ordinary implementation path, including interpolation inside template literals.
function tokenize(source) {
  const tokens = [];
  let at = 0;
  while (at < source.length) {
    if (/\s/u.test(source[at])) {
      at++;
      continue;
    }
    if (source.startsWith('//', at)) {
      while (at < source.length && !/[\n\r\u2028\u2029]/u.test(source[at])) at++;
      continue;
    }
    if (source.startsWith('/*', at)) {
      const end = source.indexOf('*/', at + 2);
      if (end < 0) throw new Error('Unclosed comment');
      at = end + 2;
      continue;
    }
    const start = at;
    const quote = source[at];
    if (quote === "'" || quote === '"' || quote === '`') {
      at++;
      let closed = false;
      while (at < source.length) {
        const char = source[at++];
        if (char === quote) {
          closed = true;
          break;
        }
        if (char === '\\') {
          const escape = source[at++];
          if (escape === undefined) throw new Error('Incomplete escape');
          if (escape === 'x' || escape === 'u') {
            const length = escape === 'x' ? 2 : 4;
            const digits = source.slice(at, at + length);
            if (digits.length !== length || !/^[0-9a-f]+$/iu.test(digits)) {
              throw new Error('Unsupported escape');
            }
            at += length;
          } else if (
            !'\'"`\\$nrtbfv0'.includes(escape) ||
            (escape === '0' && /[0-9]/u.test(source[at] ?? ''))
          ) {
            throw new Error('Unsupported escape');
          }
        } else if (
          (quote !== '`' && /[\n\r\u2028\u2029]/u.test(char)) ||
          (quote === '`' && char === '$' && source[at] === '{')
        ) {
          throw new Error('Not a plain string literal');
        }
      }
      if (!closed) throw new Error('Unclosed string');
      tokens.push({ raw: source.slice(start, at), kind: 'string', start, end: at });
      continue;
    }
    const identifier = /^[A-Za-z_$][A-Za-z0-9_$]*/u.exec(source.slice(at));
    if (identifier) at += identifier[0].length;
    else if ('{}[]:;?,='.includes(source[at])) at++;
    else throw new Error('Unsupported token');
    tokens.push({ raw: source.slice(start, at), kind: 'syntax', start, end: at });
  }
  return tokens;
}

const headerTokens = tokenize(header);

function parse(source) {
  const tokens = tokenize(source);
  let at = 0;
  const expect = (raw) => {
    const token = tokens[at++];
    if (token?.raw !== raw) throw new Error('Unsupported module shape');
    return token;
  };
  for (const token of headerTokens) expect(token.raw);
  const arrayStart = expect('[').start;
  const entries = [];
  const names = new Set();
  while (tokens[at]?.raw !== ']') {
    expect('{');
    const entry = Object.create(null);
    while (tokens[at]?.raw !== '}') {
      const key = tokens[at++]?.raw;
      if ((!required.includes(key) && key !== 'notes') || Object.hasOwn(entry, key)) {
        throw new Error('Unknown or duplicate field');
      }
      expect(':');
      const value = tokens[at++];
      const boolean = key === 'mutation' || key === 'confirmation';
      if (boolean ? !['true', 'false'].includes(value?.raw) : value?.kind !== 'string') {
        throw new Error('Nonliteral field');
      }
      entry[key] = value.raw;
      if (tokens[at]?.raw !== '}') expect(',');
    }
    expect('}');
    if (required.some((key) => !Object.hasOwn(entry, key)) || names.has(entry.name)) {
      throw new Error('Missing field or duplicate entry');
    }
    names.add(entry.name);
    entries.push(protectedKeys.map((key) => entry[key]));
    if (tokens[at]?.raw !== ']') expect(',');
  }
  const arrayEnd = expect(']').end;
  expect(';');
  if (at !== tokens.length) throw new Error('Additional module content');
  return { before: source.slice(0, arrayStart), entries, after: source.slice(arrayEnd) };
}

export function isMetadataOnly(before, after) {
  try {
    return JSON.stringify(parse(before)) === JSON.stringify(parse(after));
  } catch {
    return false;
  }
}

export function isCommittedMetadataOnly(root, base, head) {
  const git = (...args) =>
    execFileSync('git', ['-C', root, ...args], {
      encoding: 'utf8',
      maxBuffer: 8 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  try {
    if (
      git('diff', '--no-renames', '--name-status', base, head, '--', catalogPath).trim() !==
      `M\t${catalogPath}`
    )
      return false;
    const source = (revision) => {
      const tree = git('ls-tree', '-z', revision, '--', catalogPath);
      if (
        !/^100644 blob [0-9a-f]+\t/u.test(tree) ||
        tree.slice(tree.indexOf('\t') + 1) !== `${catalogPath}\0`
      ) {
        throw new Error('Not an existing ordinary file');
      }
      return git('show', `${revision}:${catalogPath}`);
    };
    return isMetadataOnly(source(base), source(head));
  } catch {
    return false;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode =
    process.argv.length === 5 && isCommittedMetadataOnly(...process.argv.slice(2)) ? 0 : 1;
}
