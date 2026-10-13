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
    """Play the Codex host: send `messages`, answer each menu the server opens with `respond`, and hang up once
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
                for m in messages:
                    if m.get('method') == 'elicitation/create' and m['id'] not in answered:
                        answered.add(m['id'])
                        return json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': respond(m)}) + '\n'
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

    def test_tools_cover_everyday_commands_and_nothing_that_changes_what_oh_runs(self):
        names = {t['name'] for t in TOOLS}
        self.assertEqual(names, {'status', 'config', 'init', 'plans', 'resource', 'deliver', 'review', 'prepare', 'prepare_design',
                                 'start', 'run', 'pause', 'resume', 'stop', 'cancel', 'conflict', 'pr_summary', 'publication', 'choose', 'confirm'})
        from .mcp_server import command
        from .storage import Refused
        self.assertEqual(command('publication',{},self.root),['publication'])
        self.assertEqual(command('review',{'arguments':['paths','folder with spaces']},self.root),['review','--','paths','folder with spaces'])
        self.assertEqual(command('publication',{'pr':144},self.root),['publication','--pr','144'])
        for invalid in (0,-1,True,'144'):
            with self.assertRaises(Refused):command('publication',{'pr':invalid},self.root)
        self.assertTrue(next(t for t in TOOLS if t['name'] == 'stop')['annotations']['destructiveHint'])  # a stop is final
        config = next(t for t in TOOLS if t['name'] == 'config')
        self.assertEqual(set(config['inputSchema']['properties']), {'root'})  # reading only: `config set` stays in the shell
        init = next(t for t in TOOLS if t['name'] == 'init')
        self.assertEqual(set(init['inputSchema']['properties']), {'root', 'name'})  # never --replace, --attach or --reattach

    def test_worker_check_tool_runs_only_the_bound_projects_checks(self):
        from .runner import attempt
        from .workflow import start,load_run
        from .worker_checks import serve as check_server,service as native_checks
        self.auto_worker_checks=False
        self.auto_reports=False
        fixtures.configure(self.root,checks=[{'name':'original environment','command':[sys.executable,'-c',
            "import os; assert os.environ['NODE_PATH']=='fixture-only-for-checks'"]}])
        journal,state=start(self.root,{'tasks':self.tasks[:1]},fixtures.WorkflowTest.event(self))
        def worker(*args,**kwargs):
            value=fixtures.WorkflowTest.fake(self,*args,**kwargs)
            def service(stdin,stdout,launcher):check_server(args[5],stdin,stdout)
            messages=[{'id':1,'method':'initialize','params':{}},{'id':2,'method':'tools/list','params':{}},
                      {'id':3,'method':'tools/call','params':{'name':'verify','arguments':{'command':['unsafe']}}},
                      {'id':4,'method':'tools/call','params':{'name':'run','arguments':{}}},
                      {'id':5,'method':'tools/call','params':{'name':'verify','arguments':{}}},
                      {'id':6,'method':'tools/call','params':{'name':'submit_report','arguments':{'report':value['structured']|{'readiness':fixtures.READINESS|{'requirements':[]}}}}},
                      {'id':7,'method':'tools/call','params':{'name':'submit_report','arguments':{'report':value['structured']}}},
                      {'id':8,'method':'tools/call','params':{'name':'submit_report','arguments':{'report':value['structured']}}}]
            with native_checks(args[5]),patch('oh.test_mcp_server.serve',side_effect=service):
                sent=play(messages[:5])
                for message in messages[5:]:sent.extend(play([message]))
                # A real proxy process receives the restricted worker environment. Checks
                # must still execute in the native parent's original environment.
                import subprocess
                from .hosts import subscription_env
                env=subscription_env(self.root)|{'OH_CHILD_ATTEMPT':'fixture-worker'}
                self.assertNotIn('NODE_PATH',env)
                code='import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from oh.worker_checks import proxy;print(json.dumps(proxy(Path(sys.argv[2]))))'
                child=subprocess.run([sys.executable,'-I','-c',code,str(HOME/'runtime'),str(args[5])],
                                     env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(child.returncode,0,child.stderr)
                self.assertTrue(json.loads(child.stdout)['passed'])
            results={m['id']:m['result'] for m in sent if 'result' in m}
            self.assertEqual([t['name'] for t in results[2]['tools']],['verify','submit_report'])
            self.assertTrue(results[3]['isError']);self.assertTrue(results[4]['isError'])
            self.assertTrue(json.loads(results[5]['content'][0]['text'])['passed'])
            self.assertFalse(json.loads(results[6]['content'][0]['text'])['accepted'])
            self.assertTrue(json.loads(results[7]['content'][0]['text'])['accepted'])
            self.assertEqual(results[7],results[8])
            self.assertEqual(len([r for r in journal.records() if r['kind']=='report.submitted']),2)
            return value|{'structured':None,'text':'Final prose is not the report.'}
        with patch.dict(os.environ,{'NODE_PATH':'fixture-only-for-checks'}):
            result=attempt(self.root,journal,state,state['tasks'][0],'implementation',state['config']['models']['codex']['standard'],invoke=worker)
        self.assertEqual(result['outcome'],'implemented')
        records=[r for r in journal.records() if r['kind']=='verification']
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]['data']['attempt'],result['id'])
        self.assertEqual(load_run(self.root)[1]['done'],[])
        def reviewer(*args,**kwargs):
            from .worker_checks import proxy
            from .storage import read_json,atomic_json,Refused
            def service(stdin,stdout,launcher):check_server(args[5],stdin,stdout)
            with native_checks(args[5]),patch('oh.test_mcp_server.serve',side_effect=service):
                sent=play([{'id':1,'method':'initialize','params':{}},{'id':2,'method':'tools/list','params':{}},
                    {'id':3,'method':'tools/call','params':{'name':'verify','arguments':{}}},
                    {'id':4,'method':'tools/call','params':{'name':'admission','arguments':{}}}])
                replies={m['id']:m['result'] for m in sent if 'result' in m}
                self.assertEqual([t['name'] for t in replies[2]['tools']],['admission','submit_report'])
                self.assertTrue(replies[3]['isError'])  # reviewer cannot execute the implementer's checks
                self.assertTrue(json.loads(replies[4]['content'][0]['text'])['valid'])
                packet=args[5]/'task-context.json';original=read_json(packet)
                atomic_json(packet,original|{'task':original['task']|{'title':'tampered scope'}})
                with self.assertRaisesRegex(Refused,'JSON binding changed'):proxy(args[5])
                atomic_json(packet,original)
                (self.root/'output.txt').write_text('later edit')
                with self.assertRaisesRegex(Refused,'no longer matches'):proxy(args[5])
                (self.root/'output.txt').write_text(str(len(self.calls)))
                value=fixtures.WorkflowTest.fake(self,*args,**kwargs)
                self.assertFalse(proxy(args[5],{'report':value['structured']|{'evidence':{}}})['accepted'])
                self.assertTrue(proxy(args[5],{'report':value['structured']})['accepted'])
                # A later invalid submission must invalidate an earlier clean one.
                self.assertFalse(proxy(args[5],{'report':value['structured']|{'evidence':{}}})['accepted'])
                from .worker_checks import returned
                from .hosts import review_result
                self.assertEqual(review_result(returned(args[5],value))[0],'review_incomplete')
                self.assertTrue(proxy(args[5],{'report':value['structured']})['accepted'])
            return value|{'structured':None}
        state=load_run(self.root)[1]
        before=len([r for r in journal.records() if r['kind']=='verification'])
        reviewed=attempt(self.root,journal,state,state['tasks'][0],'review',state['config']['models']['codex']['review'],invoke=reviewer)
        self.assertEqual(reviewed['outcome'],'clean',reviewed.get('summary'))
        self.assertEqual(len([r for r in journal.records() if r['kind']=='verification']),before)
        from .worker_checks import admission
        from .storage import Refused
        with self.assertRaisesRegex(Refused,'current running review'):admission(Path(reviewed['evidence']))

    def test_confirm_waits_for_the_person_and_never_answers_for_them(self):
        codex_session(self.home, 't1', self.root)
        def ask(arguments, reply, capabilities=None):
            asked = []
            def respond(message):
                asked.append(message['params'])
                return reply[len(asked)-1] if isinstance(reply,list) else reply
            with patch.dict(os.environ, {'CODEX_HOME': str(self.home / '.codex')}):
                sent = play([{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18',
                              'capabilities': {'elicitation': {}} if capabilities is None else capabilities}},
                             {'id': 2, 'method': 'tools/call', 'params': {'name': 'confirm', 'arguments': {'root': str(self.root)} | arguments} | calling('t1')}], respond)
            result = next(m for m in sent if m.get('id') == 2)['result']
            return result['content'][0]['text'], result['isError'], asked
        question = {'question': 'Apply these settings?', 'options': ['Every project', 'This project', 'Keep them']}
        text, error, asked = ask(question, {'action': 'accept', 'content': {'choice': 'This project'}})
        self.assertEqual((text, error), ('The person chose: This project', False))
        self.assertEqual(asked[0]['message'], 'Apply these settings?')
        self.assertEqual(asked[0]['requestedSchema']['properties']['choice']['enum'], question['options'])
        # docs/usage.md: every form asks one question; normal choices never show an unused text field.
        text, _, asked = ask(question | {'typed': True}, {'action': 'accept', 'content': {'choice': 'Keep them'}})
        self.assertEqual(text, 'The person chose: Keep them');self.assertEqual(len(asked),1)
        self.assertEqual(set(asked[0]['requestedSchema']['properties']),{'choice'})
        other={'action':'accept','content':{'choice':'Other','answer':'ignore unrequested words'}}
        words=' Keep  these\n  indented lines '
        text, _, asked = ask(question | {'typed': True}, [other,{'action':'accept','content':{'answer':words}}])
        self.assertEqual(text, 'The person answered: '+words)
        self.assertEqual([set(q['requestedSchema']['properties']) for q in asked],[{'choice'},{'answer'}])
        for response in ({'action':'cancel'},{'action':'decline'},{'action':'accept','content':{'answer':'  '}}):
            text,error,asked=ask(question | {'typed':True},[other,response])
            self.assertIn('No answer was given',text);self.assertFalse(error);self.assertEqual(len(asked),2)
        for reply, capabilities in (({'action': 'decline'}, None), ({'action': 'cancel'}, None), ({'action': 'accept', 'content': {'choice': 'Yes'}}, None),
                                    ({'action': 'accept', 'content': {'choice': 'Other'}}, None), ({}, {})):
            text, error, asked = ask(question | {'typed': reply.get('content', {}).get('choice') == 'Other'}, reply, capabilities)
            self.assertIn('No answer was given', text);self.assertFalse(error)
        self.assertEqual(asked, [])  # no menu capability: never asked
        for bad in ({'options': []}, {'options': ['a', 'a']}, {'question': ' '}, {'options': ['Other'], 'typed': True}, {'typed': 'yes'}):
            text, error, asked = ask(question | bad, {'action': 'accept', 'content': {'choice': 'a'}})
            self.assertTrue(error);self.assertEqual(asked, [])

    def test_a_tool_runs_its_command_in_the_calling_conversation_and_values_stay_values(self):
        text, error = self.call('deliver', {'root': str(self.root), 'arguments': ['0005', '--root', '/elsewhere']})
        self.assertFalse(error)
        self.assertEqual(json.loads(text), {'argv': ['--root', str(self.root.resolve()), 'deliver', '--', '0005', '--root', '/elsewhere'], 'thread': 't1'})
        self.assertEqual(json.loads(self.call('init', {'root': str(self.root), 'name': '--replace'})[0])['argv'][-1], '--name=--replace')

    def test_a_real_command_runs_through_the_launcher(self):
        text, error = self.call('config', {'root': str(self.root)}, launcher=HOME / 'oh')
        self.assertFalse(error, text)
        self.assertEqual(json.loads(text)['checks'][0]['name'], 'fixture')
        # The real launcher must recover a selected skill from the current Desktop event, even with an
        # unrelated stopped run in this checkout. A bare proposal stops before any worker or branch work.
        from .workflow import start
        from .controls import request
        start(self.root,{'tasks':self.tasks[:1]},fixtures.WorkflowTest.event(self))
        from .cli import executable_run
        from .storage import Refused
        # Old Codex clients supply the owning thread without a turn ID; both must enforce ownership.
        for turn in ('','turn-1'):
            with patch.dict(os.environ,{'CODEX_THREAD_ID':'s','OH_CODEX_TURN_ID':turn}):
                executable_run(self.root,None)
            with patch.dict(os.environ,{'CODEX_THREAD_ID':'other','OH_CODEX_TURN_ID':turn}),self.assertRaisesRegex(Refused,'another conversation'):
                executable_run(self.root,None)
        request(self.root,'stop')
        with self.assertRaisesRegex(Refused,'earlier run'):
            executable_run(self.root,{'run':'an-earlier-run','status':'running'})
        path=next((self.home/'.codex/sessions').rglob('*t1.jsonl'))
        prompt='[$o-harness:oh-propose](/plugins/oh-propose/SKILL.md)'
        records=[{'type':'session_meta','payload':{'id':'t1','cwd':str(self.root),'source':'vscode','originator':'Codex Desktop'}},
            {'type':'event_msg','payload':{'type':'task_started','turn_id':'turn-1'}},
            {'type':'event_msg','timestamp':'2026-09-30T12:01:00Z','payload':{'type':'item_completed','thread_id':'t1','turn_id':'turn-1',
                'item':{'type':'UserMessage','id':'message-one','content':[{'type':'text','text':prompt}]}}},
            {'type':'response_item','payload':{'role':'user','content':[{'type':'input_text','text':'<skill>instructions</skill>'}]}}]
        path.write_text(''.join(json.dumps(r)+'\n' for r in records),newline='\n')
        # A previous chat may have left its proposal pending on dirty files. The new invocation wins;
        # merely checking that the old chat owns that locator would wedge every later conversation.
        from .authority import stage,used_file
        from .workflow import human_event
        from .storage import read_json
        older={'hook_event_name':'UserPromptSubmit','session_id':'older','turn_id':'older-turn','prompt':'$oh-propose old idea'}
        codex_session(self.home,'older',self.root)
        old_path=next((self.home/'.codex/sessions').rglob('*older.jsonl'))
        with old_path.open('a',newline='\n') as stream:
            for record in ({'type':'event_msg','payload':{'type':'task_started','turn_id':'older-turn'}},
                           {'type':'event_msg','timestamp':'2026-09-30T12:00:00Z','payload':{'type':'user_message','message':older['prompt']}}):
                stream.write(json.dumps(record)+'\n')
        # Deliver the locators backwards: native time, not hook arrival, decides which command wins.
        newer={'hook_event_name':'UserPromptSubmit','session_id':'t1','turn_id':'turn-1','prompt':prompt}
        stage(self.root,'codex',newer)
        stage(self.root,'codex',older)
        self.assertFalse(used_file(self.root,human_event(newer,'codex')).exists())
        old_meta=calling('older');old_meta['_meta']['x-codex-turn-metadata']['turn_id']='older-turn'
        text,error=self.call('run',{'root':str(self.root)},meta=old_meta,launcher=HOME/'oh')
        self.assertTrue(error);self.assertIn('another conversation',text)
        self.assertFalse(used_file(self.root,human_event(newer,'codex')).exists())
        for _ in range(2):
            text,error=self.call('run',{'root':str(self.root)},launcher=HOME/'oh')
            self.assertFalse(error,text)
            self.assertEqual(json.loads(text)['waiting']['command'],'propose')
        self.assertIn('Superseded',read_json(used_file(self.root,human_event(older,'codex')))['refused'])
        text,error=self.call('run',{'root':str(self.root)},meta=old_meta,launcher=HOME/'oh')
        self.assertTrue(error);self.assertIn('Superseded',text)  # retrying the old chat cannot take the request back
        from .authority import drop_waiting
        drop_waiting('t1')
        records[2]['payload']['item']['content'][0]['text']='Discuss something else'
        path.write_text(''.join(json.dumps(r)+'\n' for r in records),newline='\n')
        text,error=self.call('run',{'root':str(self.root)},launcher=HOME/'oh')
        self.assertTrue(error);self.assertIn('No new OH command was recognized',text)

    def test_tools_act_only_on_the_checkout_of_the_conversation_that_calls(self):
        other = Path(self.temp.name) / 'other';other.mkdir()
        self.assertIn('not the root of a Git checkout', self.call('status', {'root': str(other)})[0])
        (self.root / 'docs').mkdir()
        self.assertIn('not the root of a Git checkout', self.call('status', {'root': str(self.root / 'docs')})[0])
        # A conversation in a checkout nested inside this one (a worktree, a submodule) can't act on the outer one.
        nested = self.root / '.claude/worktrees/wt';nested.mkdir(parents=True);(nested / '.git').write_text('gitdir: elsewhere')
        codex_session(self.home, 't2', nested)
        self.assertIn('does not work in', self.call('stop', {'root': str(self.root)}, meta=calling('t2'))[0])
        self.assertIn('does not say which conversation', self.call('status', {'root': str(self.root)}, meta={})[0])
        self.assertIn('saved session', self.call('status', {'root': str(self.root)}, meta=calling('unknown'))[0])
        self.assertIn('absolute path', self.call('status', {'root': 'project'})[0])
        with patch.dict(os.environ, {'OH_CHILD_ATTEMPT': '1'}):
            self.assertIn('workers cannot', self.call('status', {'root': str(self.root)})[0])
        # docs/architecture.md: every tool follows the current checkout, including while Codex saves
        # that move and when a large tool response separates the context from the next human message.
        from .mcp_server import checkout
        from .authority import attest
        from .storage import Refused
        import subprocess
        subprocess.run(['git','init','-q',str(other)],check=True)
        path=next((self.home/'.codex/sessions').rglob('*t1.jsonl'))
        initial=path.read_text()
        context=initial+json.dumps({'type':'turn_context','payload':{'cwd':str(other)}})+'\n'
        for partial in ('',initial[:20],context[:-8]):
            for root in (other,self.root):
                path.write_text(partial,newline='\n')
                with patch('oh.authority.sleep',side_effect=lambda _:path.write_text(context,newline='\n')) as pause:
                    if root==other:self.assertEqual(checkout({'root':str(root)},'t1'),other.resolve())
                    else:
                        with self.assertRaisesRegex(Refused,'does not work in'):
                            checkout({'root':str(root)},'t1')
                    pause.assert_called_once()
        history=[{'type':'event_msg','payload':{'type':'task_started','turn_id':'later'}},
                 {'type':'response_item','payload':{'type':'function_call_output','output':'x'*(8*1024*1024)}},
                 {'type':'event_msg','payload':{'type':'user_message','message':'$oh-propose long chat'}}]
        path.write_text(context+''.join(json.dumps(x)+'\n' for x in history),newline='\n')
        self.assertEqual(checkout({'root':str(other)},'t1'),other.resolve())
        with self.assertRaisesRegex(Refused,'does not work in'):
            checkout({'root':str(self.root)},'t1')
        payload={'hook_event_name':'UserPromptSubmit','session_id':'t1','turn_id':'later',
                 'prompt':'$oh-propose long chat','transcript_path':str(path)}
        self.assertEqual(attest('codex',payload,other)['turn'],'later')

    def test_prepare_saves_the_task_list_where_the_model_cannot_write(self):
        from .storage import project, read_json, state_home
        tasks = [{'id': '1', 'title': 'Fix', 'instructions': 'Fix it'}]
        argv = json.loads(self.call('prepare', {'root': str(self.root), 'tasks': tasks})[0])['argv']
        path = Path(argv[-1])
        self.assertTrue(path.is_relative_to(state_home() / 'projects' / project(self.root)['id']))
        self.assertEqual(read_json(path), {'tasks': tasks})

    def test_commands_get_the_person_s_shell_setup_but_oh_settings_only_from_codex(self):
        os.environ.pop('CLAUDE_CONFIG_DIR', None)  # Codex passes none; the shell's must not stand in for it
        sent = play([{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}}},
                     {'id': 2, 'method': 'tools/call', 'params': {'name': 'run', 'arguments': {'root': str(self.root)}} | calling('t1', progressToken='p')}],
                    launcher=self.launcher)
        seen = json.loads([m for m in sent if m.get('method') == 'notifications/progress'][-1]['params']['message'])
        # Windows passes Codex's environment through, so there is no login shell to read.
        self.assertEqual(seen, {'shell': None if os.name == 'nt' else 'yes', 'data': os.environ['OH_DATA_HOME'], 'claude': None})

    @unittest.skipIf(os.name == 'nt', 'Windows reads no login shell')
    def test_the_server_keeps_answering_while_it_reads_the_shell(self):
        import threading
        from .mcp_server import Server
        server = Server(io.StringIO(), io.StringIO(), self.launcher)
        with patch.dict(os.environ, {'FAKE_SHELL_WAIT': '2'}):
            reading = threading.Thread(target=server.environment, args=('t1',));reading.start()
            time.sleep(0.3)  # the shell is being read
            began = time.monotonic();server.send({'id': 9, 'result': {}})
            self.assertLess(time.monotonic() - began, 1)  # a reply never waits for the shell
            reading.join()

    def test_oh_goes_on_when_nobody_reads_its_output(self):
        from .cli import main
        from .runner import run
        from .workflow import start
        class Gone:
            def write(self, text):raise BrokenPipeError(32, 'Broken pipe')
            def flush(self):raise BrokenPipeError(32, 'Broken pipe')
        fixtures.configure(self.root, tasks_per_batch=1)
        start(self.root, {'tasks': [{'id': '1', 'title': 'One', 'instructions': 'Do it'}]}, fixtures.WorkflowTest.event(self))
        with patch('sys.stdout', Gone()), patch('sys.stderr', Gone()):
            main(['--root', str(self.root), 'config'])  # OH's command entry: its output may be read by nobody
            result = run(self.root, lambda *a, **k: fixtures.WorkflowTest.fake(self, *a, **k))  # progress goes nowhere
        self.assertEqual(result['status'], 'completed')

    def test_the_runner_reports_progress_where_the_server_forwards_it(self):
        import contextlib
        from .runner import run
        from .workflow import start,load_run
        fixtures.configure(self.root, tasks_per_batch=1)
        start(self.root, {'tasks': [{'id': '1', 'title': 'One', 'instructions': 'Do it'}]}, fixtures.WorkflowTest.event(self))
        out, err = io.StringIO(), io.StringIO()
        def worker(*args,**kwargs):
            _,state=load_run(self.root)
            # Progress describes an admitted worker, not a speculative next phase.
            self.assertEqual(state['attempts'][-1]['role'],args[4])
            self.assertTrue(state['attempts'][-1]['request_hash'])
            self.assertEqual(len(err.getvalue().splitlines()),1 if args[4]=='implementation' else 3)
            return fixtures.WorkflowTest.fake(self,*args,**kwargs)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            run(self.root, worker)
        messages=err.getvalue().splitlines()
        self.assertEqual(len(messages),4)  # implementation (including checks) and review start/finish
        self.assertIn('task 1: One',messages[0])
        self.assertIn('no findings',messages[-1])
        with contextlib.redirect_stderr(err):
            run(self.root, lambda *a, **k: fixtures.WorkflowTest.fake(self, *a, **k))
        self.assertEqual(err.getvalue().splitlines(),messages)  # completed batches emit nothing twice
        self.assertEqual(out.getvalue(),'')  # progress stays off the machine-readable result stream

        from .progress import observe,follow
        journal,state=load_run(self.root);before=journal.records()
        result=observe(self.root,state['id'],wait=0)
        self.assertTrue(result['done']);self.assertEqual(journal.records(),before)
        self.assertEqual(observe(self.root,'another-run',wait=0)['status'],'replaced')
        # Watch expiry and focus throttling cannot launch work, renew authority or spend reviews.
        clock=[0.0]
        def snapshot(root,run_id):
            phase='implementation' if clock[0]<20 else 'review'
            focus='first' if clock[0]<5 else 'second' if clock[0]<25 else 'third'
            return {'run':run_id,'status':'running','phase':phase,'attempt':phase,'done':False,
                    'focus':{'id':focus,'message':focus},'message':phase+' '+focus}
        with patch('oh.progress.snapshot',side_effect=snapshot),patch('oh.progress.time') as timer,contextlib.redirect_stdout(io.StringIO()) as observed:
            timer.monotonic.side_effect=lambda:clock[0]
            timer.sleep.side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
            follow(self.root,state['id'],seconds=240)
        rows=[json.loads(line) for line in observed.getvalue().splitlines()]
        self.assertEqual([row.get('message') for row in rows[:-1]],['implementation first','review second','review third'])
        self.assertEqual(rows[-1]['observer'],'expired')
        self.assertEqual(journal.records(),before)
        # A resumed watch ignores the old idle gate, including a fast phase that
        # returns to that same gate before the next poll. Journal revision distinguishes it.
        from .storage import digest
        baseline={'run':state['id'],'status':'checkpoint','phase':'checkpoint','done':True,'revision':'old'}
        clock[0]=0
        def resumed(root,run_id):
            return baseline | {'revision':'old' if clock[0]<3 else 'new'}
        with patch('oh.progress.snapshot',side_effect=resumed),patch('oh.progress.time') as timer,contextlib.redirect_stdout(io.StringIO()) as observed:
            timer.monotonic.side_effect=lambda:clock[0]
            timer.sleep.side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
            follow(self.root,state['id'],after=digest(baseline),seconds=10)
        rows=[json.loads(line) for line in observed.getvalue().splitlines()]
        self.assertEqual([r['revision'] for r in rows],['new'])
        self.assertGreaterEqual(clock[0],3)
        self.assertEqual(journal.records(),before)


    def test_a_cancelled_call_gets_no_reply_and_an_unexpected_error_gets_one(self):
        with patch.dict(os.environ, {'FAKE_WAIT': '0.5'}):
            sent = play([{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}}},
                         {'id': 2, 'method': 'tools/call', 'params': {'name': 'run', 'arguments': {'root': str(self.root)}} | calling('t1', progressToken='p')},
                         {'method': 'notifications/cancelled', 'params': {'requestId': 2}}, {'id': 3, 'method': 'ping'}],
                        launcher=self.launcher, settle=2)  # the stand-in run finishes meanwhile; its reply must not follow
        # The stand-in's last line (its environment) was forwarded, so the run had finished before this check.
        self.assertTrue(any('"shell"' in m['params']['message'] for m in sent if m.get('method') == 'notifications/progress'))
        self.assertFalse(any(m.get('id') == 2 for m in sent))
        with patch('oh.mcp_server.command', side_effect=TypeError('broken')):
            text, error = self.call('status', {'root': str(self.root)})
        self.assertTrue(error);self.assertIn('unexpectedly', text)

    def test_the_tools_exist_before_setup(self):
        import subprocess
        from .installation import build
        plugin = Path(self.temp.name) / 'dist/o-harness';plugin.parent.mkdir()
        build(plugin, 'codex')
        requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}}},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}]
        empty = Path(self.temp.name) / 'no-oh-yet'
        # Started as Codex starts it: the command .mcp.json names, from the plugin folder. On Windows Codex finds the
        # .cmd next to it through PATHEXT.
        server = json.loads((plugin / '.mcp.json').read_text())['mcpServers']['o-harness']
        program = plugin / server['command']
        if os.name == 'nt':program = program.with_name(program.name + '.cmd')
        done = subprocess.run([str(program), *server['args']], cwd=plugin, input=''.join(json.dumps(r) + '\n' for r in requests).encode(),
                              capture_output=True, env=dict(os.environ, OH_DATA_HOME=str(empty)), timeout=60)
        self.assertNotIn(b'\r', done.stdout)  # one message per line on every system
        tools = next(json.loads(line) for line in done.stdout.decode().splitlines() if json.loads(line).get('id') == 2)['result']['tools']
        self.assertIn('run', {t['name'] for t in tools})

    def test_oh_reads_codex_conversations_from_codex_home(self):
        from .authority import attest
        home = Path(self.temp.name) / 'custom-codex'
        path = home / 'sessions/rollout-x-t9.jsonl';path.parent.mkdir(parents=True)
        records = [{'type': 'session_meta', 'payload': {'id': 't9', 'cwd': str(self.root), 'source': 'cli'}},
                   {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn'}},
                   {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'continue'}}]
        path.write_text(''.join(json.dumps(r) + '\n' for r in records), newline='\n')
        payload = {'hook_event_name': 'UserPromptSubmit', 'session_id': 't9', 'turn_id': 'turn', 'prompt': 'continue', 'transcript_path': str(path)}
        with patch.dict(os.environ, {'CODEX_HOME': str(home)}):
            self.assertEqual(attest('codex', payload, self.root)['turn'], 'turn')

    def test_a_long_command_reports_progress_and_the_server_keeps_answering(self):
        with patch.dict(os.environ, {'FAKE_WAIT': '1'}):
            sent = play([{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}}},
                         {'id': 2, 'method': 'tools/call', 'params': {'name': 'run', 'arguments': {'root': str(self.root)}} | calling('t1', progressToken='p')},
                         {'id': 3, 'method': 'ping'}], launcher=self.launcher)
        order = [m.get('id') for m in sent if 'result' in m]
        self.assertLess(order.index(3), order.index(2))  # the ping was answered while the run worked
        progress = next(m for m in sent if m.get('method') == 'notifications/progress')
        self.assertEqual(progress['params'], {'progressToken': 'p', 'progress': 1, 'message': 'OH task 1: implementation'})
        self.assertEqual(len([m for m in sent if m.get('method')=='notifications/progress']),2)
        # The server forwards the launcher's two real events; waiting adds no heartbeat.

    def test_an_oh_refusal_is_the_tool_s_error(self):
        self.assertEqual(self.call('deliver', {'root': str(self.root), 'arguments': ['fail']}), ('OH: nothing to run', True))
