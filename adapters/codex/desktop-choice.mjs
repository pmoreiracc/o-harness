// Decode host-owned Desktop history without executing its JavaScript.
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

const [root, family, adapter] = process.argv.slice(2);
const session = process.env.CODEX_SESSION_ID;
const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
const itemId = /^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$/;
if (!uuid.test(session ?? '')) process.exit(1);
const commands = {
  task: ['continue', 'pr', 'stop'],
  round: ['grant next review window', 'stop and take it over', 'stop and escalate to the pr'],
  review: ['fix concerns', 'accept concerns', 'route scope', 'dismiss scope',
    'fix concerns and route scope', 'fix concerns and dismiss scope',
    'accept concerns and route scope', 'accept concerns and dismiss scope',
    'review again', 'take over', 'stop scope routing', 'stop detached review',
    'grant next review window', 'stop and take it over', 'stop and escalate to the pr'],
};
function choice(text) {
  if (typeof text !== 'string') return null;
  const bare = text.endsWith('\n') ? text.slice(0, -1) : text;
  if (commands[family]?.includes(bare)) return bare;
  if (family === 'review' && (/^route scope to https:\/\/[^\s]+\/issues\/[1-9][0-9]*$/.test(bare)
    || /^resume detached review d-[0-9]{10}-[0-9a-f]{24}$/.test(bare))) return bare;
  return null;
}
// One isolated exec_command with scalar literal options, regardless of layout or order.
// Reject computed input, extra calls, shell prefixes and a different working directory.
function invocation(input) {
  if (typeof input !== 'string') return false;
  const literal = '"(?:[^"\\\\]|\\\\.)*"';
  const match = input.trim().match(/^(?:(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*|text\(\s*)?await\s+tools\.exec_command\(\s*(\{[\s\S]*\})\s*\)([\s\S]*)$/);
  if (!match) return false;
  const [, variable, object, tail] = match;
  const trailing = variable
    ? new RegExp(`^\\s*;?(?:\\s*text\\(\\s*${variable.replace(/[$]/g, '\\$')}(?:\\.output)?\\s*\\)\\s*;?)?\\s*$`)
    : input.trim().startsWith('text(') ? /^\s*\)\s*;?\s*$/ : /^\s*;?\s*$/;
  if (!trailing.test(tail)) return false;
  const token = new RegExp(`\\s*(?:(${literal})|([A-Za-z_][A-Za-z_0-9]*))\\s*:\\s*(${literal}|[0-9]+|true|false)\\s*(,|$)`, 'y');
  const body = object.slice(1, -1).trim();
  const args = {};
  while (token.lastIndex < body.length) {
    const property = token.exec(body);
    if (!property) return false;
    const key = property[1] ? JSON.parse(property[1]) : property[2];
    if (Object.hasOwn(args, key)) return false;
    args[key] = JSON.parse(property[3]);
  }
  return args.cmd === adapter && (args.workdir === undefined || args.workdir === root)
    && Object.keys(args).every(key => ['cmd', 'workdir', 'yield_time_ms', 'max_output_tokens'].includes(key));
}
function tool(event) {
  return event.type === 'response_item' && ['custom_tool_call', 'function_call'].includes(event.payload?.type)
    || event.type === 'event_msg' && event.payload?.type === 'item_completed'
      && ['CommandExecution', 'FileChange', 'CollabAgentToolCall'].includes(event.payload.item?.type);
}
function* files(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) yield* files(path.join(dir, entry.name));
    else if (entry.isFile() && entry.name.endsWith('.jsonl')) yield path.join(dir, entry.name);
  }
}
const candidates = [];
const observedMessages = new Set();
try {
  const sessions = path.join(process.env.CODEX_HOME ?? path.join(process.env.HOME, '.codex'), 'sessions');
  for (const file of files(sessions)) {
    let events;
    try { events = readFileSync(file, 'utf8').split('\n').filter(line => line.trim()).map(line => JSON.parse(line)); }
    catch { continue; }
    const meta = events.find(e => e.type === 'session_meta')?.payload;
    if ((meta?.id ?? meta?.session_id) !== session || meta.cwd !== root || !['vscode', 'exec'].includes(meta.source)
      || !['Codex Desktop', 'codex_work_desktop'].includes(meta.originator)) continue;
    const userIndex = events.findLastIndex(e => e.type === 'event_msg' && e.payload?.type === 'item_completed' && e.payload.item?.type === 'UserMessage');
    if (userIndex < 0) continue;
    const user = events[userIndex].payload;
    const content = user.item.content;
    observedMessages.add(JSON.stringify([user.item.id, user.item.client_id, user.turn_id, content]));
    if (typeof user.turn_id !== 'string' || !user.turn_id) continue;
    const answer = choice(typeof content === 'string' ? content : content?.length === 1 && content[0].type === 'text' ? content[0].text : null);
    if (!answer || !itemId.test(user.item.id ?? '') || !itemId.test(user.item.client_id ?? '')) continue;
    const later = events.slice(userIndex + 1);
    const transitions = later.filter(tool);
    const calls = transitions.filter(e => e.type === 'response_item');
    const matches = call => call.type === 'response_item' && call.payload.type === 'custom_tool_call'
      && call.payload.name === 'exec' && call.payload.internal_chat_message_metadata_passthrough?.turn_id === user.turn_id
      && invocation(call.payload.input);
    if (!calls.length || !calls.every(matches)) continue;
    let mode = 'direct', first = '-';
    if (calls.length === 1) {
      if (transitions.length !== 1) continue;
    } else {
      if (family !== 'task' || calls.length !== 2) continue;
      first = calls[0].payload.call_id;
      if (!itemId.test(first ?? '')) continue;
      const between = later.slice(later.indexOf(calls[0]) + 1, later.indexOf(calls[1]));
      // The command completion is the first isolated call's host event, not another
      // agent action. Admit precisely that failed adapter execution and no other tool.
      const completions = transitions.filter(e => e.type !== 'response_item');
      if (completions.length !== 1 || !between.includes(completions[0])) continue;
      const completion = completions[0].payload;
      const item = completion.item;
      if (completion.turn_id !== user.turn_id || item.type !== 'CommandExecution'
        || item.source !== 'unified_exec_startup' || item.status !== 'failed' || item.exit_code !== 2
        || item.cwd !== pathToFileURL(root).href || !Array.isArray(item.command)
        || item.command.length !== 3 || !['-lc', '-c'].includes(item.command[1])
        || item.command[2] !== adapter) continue;
      const outputs = between.filter(e => e.type === 'response_item' && e.payload.type === 'custom_tool_call_output');
      if (outputs.length !== 1 || outputs[0].payload.call_id !== first) continue;
      const output = outputs[0].payload.output;
      const text = typeof output === 'string' ? output : Array.isArray(output) ? output.map(x => typeof x === 'string' ? x : x.text ?? '').join('\n') : '';
      if (!text.includes('task-window: no exact direct Desktop choice matches this branch and turn.')
        || text.includes('recorded direct Desktop choice')) continue;
      mode = 'recovery';
    }
    candidates.push({ answer, source: `codex-desktop:${session}:${user.item.id}:${user.item.client_id}`, mode, first });
  }
} catch { process.exit(1); }
// Conflicting session files are not authority; identical duplicated evidence is harmless.
const unique = [...new Map(candidates.map(c => [JSON.stringify(c), c])).values()];
if (unique.length !== 1 || observedMessages.size !== 1) process.exit(1);
const result = unique[0];
process.stdout.write([result.answer, result.source, result.mode, result.first].join('\t') + '\n');
