#!/usr/bin/env node
// Codex exposes a whole apply_patch program. The canonical hooks consume Claude's
// per-file Edit/Write payloads, so decompose the patch and invoke them once per change.
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const hookName = process.argv[2];
const root = process.env.CLAUDE_PROJECT_DIR;
let input;
const allowedHooks = new Set([
  'adr-immutability.sh',
  'doc-frontmatter.sh',
  'protect-receipts.sh',
  'protect-local-policy.sh',
  'adr-log-index.sh',
]);

function fail(message, recovery = 'Correct the named patch field and retry apply_patch in this run; inspect the current file first if a previous write may have applied.') {
  process.stderr.write(`GUARDRAIL CANNOT RUN: ${message}\n`);
  process.stderr.write(
    `${input?.hook_event_name === 'PostToolUse' ? 'The edit already ran; inspect its result before correcting it.' : input?.hook_event_name === 'PreToolUse' ? 'This edit is rejected; the run may continue.' : 'Operation not inspected; check the host result before retrying.'} ${recovery}\n`,
  );
  process.exit(2);
}

if (!root || !allowedHooks.has(hookName)) {
  fail('the repository root or target hook is invalid.');
}

try {
  input = JSON.parse(readFileSync(0, 'utf8'));
} catch {
  fail('the hook payload is not valid JSON.');
}

if (input.tool_name !== 'apply_patch' || typeof input.tool_input?.command !== 'string') {
  fail('the edit payload is not a recognised Codex apply_patch call.');
}

function repoPath(raw) {
  if (!raw || raw.includes('\0') || raw.includes('\n'))
    fail('the patch contains an invalid file path.');
  const absolute = path.resolve(root, raw);
  const relative = path.relative(root, absolute);
  if (relative === '' || relative.startsWith(`..${path.sep}`) || relative === '..') {
    fail(`patch path '${raw}' is outside the repository.`, 'Use a destination inside the repository for this task. If external work is necessary, use the supported host permission flow; do not bypass this check through a shell write.');
  }
  return relative.split(path.sep).join('/');
}

function readExisting(raw) {
  try {
    return readFileSync(path.resolve(root, raw), 'utf8');
  } catch {
    fail(`the source of moved file '${raw}' cannot be read.`);
  }
}

function changedText(body, marker) {
  const lines = body.filter(
    (line) => line.startsWith(marker),
  );
  if (lines.length === 0) return '';
  return lines.map((line) => line.slice(1)).join('\n') + '\n';
}

function parsePatch(command) {
  const lines = command.replace(/\r\n/g, '\n').split('\n');
  if (lines.at(-1) === '') lines.pop();
  if (lines[0] !== '*** Begin Patch' || lines.at(-1) !== '*** End Patch') {
    fail('the apply_patch program has no exact Begin Patch / End Patch envelope.');
  }

  const changes = [];
  const fileHeader = /^\*\*\* (Add|Update|Delete) File: (.+)$/;
  let index = 1;

  while (index < lines.length - 1) {
    const header = fileHeader.exec(lines[index]);
    if (!header) fail(`unrecognised patch directive '${lines[index]}'.`);
    const operation = header[1];
    const sourceRaw = header[2];
    index += 1;

    let moveRaw = null;
    if (operation === 'Update' && lines[index]?.startsWith('*** Move to: ')) {
      moveRaw = lines[index].slice('*** Move to: '.length);
      index += 1;
    }

    const body = [];
    while (index < lines.length - 1 && !fileHeader.test(lines[index])) {
      if (lines[index] === '*** End of File') {
        index += 1;
        continue;
      }
      if (lines[index].startsWith('*** ')) fail(`unrecognised patch directive '${lines[index]}'.`);
      body.push(lines[index]);
      index += 1;
    }

    const source = repoPath(sourceRaw);
    if (operation === 'Add') {
      if (body.some((line) => !line.startsWith('+'))) {
        fail(`Add File '${sourceRaw}' does not expose its complete content.`);
      }
      changes.push({
        tool_name: 'Write',
        tool_input: {
          file_path: source,
          patch_operation: 'add',
          file_text: body.length ? body.map((line) => line.slice(1)).join('\n') + '\n' : '',
        },
      });
      continue;
    }

    if (operation === 'Delete') {
      if (body.length !== 0) fail(`Delete File '${sourceRaw}' carries unexpected patch text.`);
      changes.push({ tool_name: 'Write', tool_input: { file_path: source, patch_operation: 'delete', file_text: '' } });
      continue;
    }

    const oldText = changedText(body, '-');
    const newText = changedText(body, '+');
    if (!moveRaw && oldText === '' && newText === '') {
      fail(`Update File '${sourceRaw}' exposes no changed text.`, 'If no change is needed, omit this operation and continue. Otherwise include the intended removed and/or replacement lines, then retry. Empty replacement is valid for deletion.');
    }

    if (moveRaw) {
      const destination = repoPath(moveRaw);
      changes.push({ tool_name: 'Write', tool_input: { file_path: source, patch_operation: 'delete', file_text: '' } });
      if (destination.startsWith('docs/') && (oldText !== '' || newText !== '')) {
        fail(
          `move into '${destination}' also edits content; split the move and edit so frontmatter can be checked exactly.`,
        );
      }
      const contentSource = input.hook_event_name === 'PostToolUse' ? moveRaw : sourceRaw;
      changes.push({
        tool_name: 'Write',
        tool_input: { file_path: destination, file_text: readExisting(contentSource) },
      });
      continue;
    }

    changes.push({
      tool_name: 'Edit',
      tool_input: { file_path: source, old_string: oldText, new_string: newText },
    });
  }

  if (changes.length === 0) fail('the apply_patch program contains no file changes.');
  return changes;
}

const advisoryContexts = [];
for (const change of parsePatch(input.tool_input.command)) {
  const payload = {
    ...input,
    tool_name: change.tool_name,
    tool_input: change.tool_input,
  };
  const result = spawnSync('/bin/bash', [path.join(process.env.OH_HOME || root, 'core/hooks', hookName)], {
    cwd: root,
    env: { ...process.env, CLAUDE_PROJECT_DIR: root, CODEX_HOOK: '1' },
    input: JSON.stringify(payload),
    encoding: 'utf8',
  });
  if (result.stdout) {
    if (hookName === 'adr-log-index.sh') {
      try {
        const context = JSON.parse(result.stdout).hookSpecificOutput.additionalContext;
        if (typeof context !== 'string') throw new Error('missing advisory context');
        advisoryContexts.push(context);
      } catch {
        fail(`${hookName} returned unreadable advisory output.`);
      }
    } else process.stdout.write(result.stdout);
  }
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.error) fail(`${hookName} could not be executed: ${result.error.message}`);
  if (result.status !== 0) process.exit(result.status === 2 ? 2 : 2);
}
if (advisoryContexts.length) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PostToolUse', additionalContext: advisoryContexts.join('\n'),
    },
  }) + '\n');
}
