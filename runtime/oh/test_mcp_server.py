import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from . import test_workflow as fixtures
from .config import HOME
from .mcp_server import TOOLS, serve


def play(messages, respond=None, launcher=None, settle=0):
    """Play the Codex host: send `messages` and hang up once
    every request it did not cancel has its response. Returns everything the server sent, in order."""
    output, pending, answered = io.StringIO(), list(messages), set()
    cancelled = {m['params']['requestId'] for m in messages if m.get('method') == 'notifications/cancelled'}
    wanted = {m['id'] for m in messages if 'method' in m and 'id' in m} - cancelled
    def sent():
        return [json.loads(line) for line in output.getvalue().split('\n')[:-1]]  # whole lines only
    class Host:
        def readline(self):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if pending:return json.dumps({'jsonrpc': '2.0'} | pending.pop(0)) + '\n'
                messages = sent()
                if wanted <= {m.get('id') for m in messages if 'method' not in m}:return ''
                time.sleep(0.01)
            return ''
    serve(Host(), output, launcher)
    time.sleep(settle)  # anything the server still sends after the host hung up
    return sent()


def codex_session(home, thread, cwd):
    """The session Codex saves for a conversation, which names the folder it works in."""
    path = home / '.codex/sessions/2026/09/28' / f'rollout-2026-09-28T00-00-00-{thread}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': thread, 'cwd': str(cwd), 'source': 'cli'}}) + '\n', newline='\n')


def calling(thread, **extra):
    return {'_meta': {'x-codex-turn-metadata': {'thread_id': thread, 'turn_id': 'turn-1'}} | extra}


class CodexToolsTest(unittest.TestCase):
    setUp_workflow = fixtures.WorkflowTest.setUp
    git = fixtures.WorkflowTest.git

    def setUp(self):
        self.setUp_workflow()
        self.home = Path(self.temp.name).resolve() / 'home'
        patcher = patch('pathlib.Path.home', return_value=self.home);patcher.start();self.addCleanup(patcher.stop)
        # The person's shell, as the server reads it once: it adds a value Codex does not pass.
        shell = Path(self.temp.name) / 'shell'
        script = ('#!/bin/sh\nsleep "${FAKE_SHELL_WAIT:-0}"\nprintf __OH_SHELL_ENVIRONMENT__\n'
                  'FROM_SHELL=yes OH_DATA_HOME=/wrong CLAUDE_CONFIG_DIR=/wrong env -0\n')
        shell.write_text(script, newline='\n');shell.chmod(0o755)
        environment = patch.dict(os.environ, {'CODEX_HOME': str(self.home / '.codex'), 'SHELL': str(shell)});environment.start();self.addCleanup(environment.stop)
        codex_session(self.home, 't1', self.root)
        # A stand-in launcher that reports what it was asked to run, from which conversation.
        self.launcher = Path(self.temp.name) / 'oh-launcher'
        self.launcher.write_text(
            'import json,os,sys,time\n'
            'print("OH task 1: implementation", file=sys.stderr, flush=True)\n'
            'time.sleep(float(os.environ.get("FAKE_WAIT", "0")))\n'
            'if "fail" in sys.argv:print("OH: nothing to run", file=sys.stderr);sys.exit(2)\n'
            'print(json.dumps({"argv": sys.argv[1:], "thread": os.environ.get("CODEX_THREAD_ID")}))\n'
            'print(json.dumps({"shell": os.environ.get("FROM_SHELL"), "data": os.environ.get("OH_DATA_HOME"), '
            '"claude": os.environ.get("CLAUDE_CONFIG_DIR")}), file=sys.stderr)\n', newline='\n')

    def call(self, name, arguments, meta=None, launcher=None, ident=2):
        sent = play([{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}}},
                     {'id': ident, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments} | (calling('t1') if meta is None else meta)}],
                    launcher=launcher or self.launcher)
        result = next(m for m in sent if m.get('id') == ident)['result']
        return result['content'][0]['text'], result['isError']

    def test_tools_are_focused_helpers_without_an_execution_or_menu_engine(self):
        names={tool['name'] for tool in TOOLS}
        self.assertEqual(names,{'status','resume','config','init','plans','resource','scope_prepare','scope_approve',
            'attempt_admit','attempt_bind','attempt_retain','candidate','verify','evidence','complete','decision',
            'review','pr_summary','publication','admission','review_check'})
        self.assertFalse(names & {'run','start','choose','confirm'})
        for tool in TOOLS:
            self.assertFalse(tool['inputSchema']['additionalProperties'])
            self.assertIn('root',tool['inputSchema']['required'])
        config=next(tool for tool in TOOLS if tool['name']=='config')
        self.assertEqual(set(config['inputSchema']['properties']),{'root'})

    def test_focused_commands_keep_values_literal_and_payloads_external(self):
        from .mcp_server import command
        from .storage import read_json, Refused
        human={'host':'codex','session':'t1','turn':'turn-1','prompt':'Approve these bounded changes.'}
        values={
            'scope_approve':({'scope':'approved scope','human':human},['scope','approve','--','approved scope']),
            'attempt_bind':({'attempt':'attempt','source':{'child_session':'child'}},['attempt','bind','--','attempt']),
            'decision':({'kind':'accept concerns','human':human,'attempt':'review'},['decision','--attempt','review','--','accept concerns']),
        }
        for name,(arguments,prefix) in values.items():
            actual=command(name,arguments,self.root)
            self.assertEqual(actual[:-1],prefix)
            payload=Path(actual[-1]);self.assertFalse(payload.is_relative_to(self.root))
            self.assertEqual(read_json(payload),arguments.get('human',arguments.get('source')))
            self.assertEqual(command(name,arguments,self.root),actual)
        self.assertEqual(command('review',{'arguments':['paths','folder with spaces']},self.root),
                         ['review','--','paths','folder with spaces'])
        self.assertEqual(command('resource',{'path':'$(touch sentinel)'},self.root),['resource','--','$(touch sentinel)'])
        self.assertEqual(command('admission',{'attempt_directory':'folder with spaces'},self.root),
                         ['admission','--','folder with spaces'])
        checked=command('review_check',{'report':'OH-REVIEW-DECISION: {}\nFree text $(literal)'},self.root)
        self.assertEqual(checked[:2],['review-check','--'])
        self.assertFalse(Path(checked[-1]).is_relative_to(self.root))
        self.assertEqual(read_json(checked[-1])['report'],'OH-REVIEW-DECISION: {}\nFree text $(literal)')
        resumed=command('resume',{'human':human},self.root)
        self.assertEqual(resumed[:2],['resume','--human'])
        self.assertEqual(read_json(resumed[-1]),human)
        self.assertEqual(command('status',{'saved':True},self.root),['status','--saved'])
        selected=command('resume',{'run':'saved-run','human':human},self.root)
        self.assertEqual(selected[:3],['resume','--run','saved-run'])
        self.assertEqual(read_json(selected[-1]),human)
        with self.assertRaises(Refused):command('status',{'saved':'true'},self.root)
        for name,arguments in (('attempt_admit',{'role':'shell'}),('scope_approve',{'scope':'s','human':'model says yes'}),
                               ('attempt_bind',{'attempt':'a','source':[]}),('evidence',{'attachment':{'text':'x'*1048577}}),
                               ('review',{'arguments':[1]}),('verify',{'mode':'ci'}),('publication',{'pr':True})):
            with self.subTest(name=name),self.assertRaises(Refused):command(name,arguments,self.root)

    def test_native_child_resolves_its_checkout_but_cannot_supply_a_human_grant(self):
        from .mcp_server import checkout
        from .authority import attest
        from .storage import Refused
        path=self.home/'.codex/sessions/child.jsonl'
        records=[{'type':'session_meta','payload':{'id':'child','cwd':str(self.root),
                  'source':{'subagent':{'thread_spawn':{'parent_thread_id':'t1'}}}}},
                 {'type':'event_msg','payload':{'type':'user_message','turn_id':'child-turn','message':'approve'}}]
        path.write_text(''.join(json.dumps(row)+'\n' for row in records),newline='\n')
        self.assertEqual(checkout({'root':str(self.root)},'child'),self.root.resolve())
        with self.assertRaises(Refused):
            attest('codex',{'hook_event_name':'UserPromptSubmit','session_id':'child','turn_id':'child-turn',
                           'prompt':'approve','transcript_path':str(path)},self.root)

    def test_tools_act_only_on_the_current_native_checkout(self):
        from .mcp_server import checkout
        from .storage import Refused
        import subprocess
        other=Path(self.temp.name)/'other';other.mkdir();subprocess.run(['git','init','-q',str(other)],check=True)
        self.assertIn('does not work in',self.call('status',{'root':str(other)})[0])
        self.assertIn('does not say which conversation',self.call('status',{'root':str(self.root)},meta={})[0])
        self.assertIn('absolute path',self.call('status',{'root':'project'})[0])
        nested=self.root/'vendor';nested.mkdir();(nested/'.git').write_text('gitdir: elsewhere',newline='\n')
        codex_session(self.home,'nested',nested)
        with self.assertRaisesRegex(Refused,'does not work in'):
            checkout({'root':str(self.root)},'nested')
        path=next((self.home/'.codex/sessions').rglob('*t1.jsonl'))
        path.write_text(path.read_text()+json.dumps({'type':'turn_context','payload':{'cwd':str(other)}})+'\n',newline='\n')
        self.assertEqual(checkout({'root':str(other)},'t1'),other.resolve())
        with self.assertRaisesRegex(Refused,'does not work in'):
            checkout({'root':str(self.root)},'t1')

    def test_commands_preserve_native_conversation_and_forwarded_settings(self):
        text,error=self.call('status',{'root':str(self.root)})
        self.assertFalse(error,text)
        records=[json.loads(line) for line in text.splitlines()]
        self.assertEqual(records[0],{'argv':['--root',str(self.root.resolve()),'status'],'thread':'t1'})
        text,error=self.call('config',{'root':str(self.root)})
        self.assertFalse(error,text)
        self.assertEqual(json.loads(text)['thread'],'t1')
        # The command's environment is checked directly because stderr is not a progress protocol.
        from .mcp_server import Server
        server=Server(None,None);server.shell={'FROM_SHELL':'yes','OH_DATA_HOME':'wrong'}
        environment=server.environment('t1','turn-1')
        self.assertEqual(environment['FROM_SHELL'],'yes')
        self.assertEqual(environment['OH_DATA_HOME'],os.environ['OH_DATA_HOME'])
        self.assertEqual(environment['OH_CODEX_TURN_ID'],'turn-1')

    def test_configured_check_does_not_block_transport_and_cancellation_grants_nothing(self):
        messages=[{'id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},
                  {'id':2,'method':'tools/call','params':{'name':'verify','arguments':{'root':str(self.root)}}|calling('t1')},
                  {'id':3,'method':'ping'}]
        with patch.dict(os.environ,{'FAKE_WAIT':'0.1'}):sent=play(messages,launcher=self.launcher)
        order=[row.get('id') for row in sent if 'result' in row]
        self.assertLess(order.index(3),order.index(2))
        self.assertFalse(any(row.get('method') in ('elicitation/create','notifications/progress') for row in sent))
        cancelled=[*messages[:2],{'method':'notifications/cancelled','params':{'requestId':2}},messages[-1]]
        with patch.dict(os.environ,{'FAKE_WAIT':'0.05'}):sent=play(cancelled,launcher=self.launcher,settle=.1)
        self.assertFalse(any(row.get('id')==2 for row in sent))
        with patch('oh.mcp_server.command',side_effect=TypeError('broken')):
            text,error=self.call('status',{'root':str(self.root)})
        self.assertTrue(error);self.assertIn('unexpectedly',text)
        self.assertEqual(self.call('resource',{'root':str(self.root),'path':'fail'}),('OH: nothing to run',True))

    def test_the_tools_exist_before_setup(self):
        import subprocess
        from .installation import build
        plugin=Path(self.temp.name)/'dist/o-harness';plugin.parent.mkdir()
        build(plugin,'codex')
        requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'}]
        server=json.loads((plugin/'.mcp.json').read_text())['mcpServers']['o-harness']
        program=plugin/server['command']
        if os.name=='nt':program=program.with_name(program.name+'.cmd')
        done=subprocess.run([str(program),*server['args']],cwd=plugin,
            input=''.join(json.dumps(row)+'\n' for row in requests).encode(),capture_output=True,
            env=dict(os.environ,OH_DATA_HOME=str(Path(self.temp.name)/'not-installed')),timeout=60)
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertNotIn(b'\r',done.stdout)
        tools=next(json.loads(line) for line in done.stdout.decode().splitlines() if json.loads(line).get('id')==2)['result']['tools']
        self.assertIn('attempt_admit',{tool['name'] for tool in tools})
        self.assertNotIn('run',{tool['name'] for tool in tools})
