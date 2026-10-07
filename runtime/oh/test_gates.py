import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from . import test_workflow as fixtures
from .authority import materialize
from .config import HOME
from .gates import ask, current, pick
from .runner import run
from .storage import Refused
from .workflow import choose, human_event, load_run, start


def clear(folder):
    """Remove a test folder, including Git's read-only object files on Windows."""
    shutil.rmtree(folder, onexc=lambda remove, name, _: (os.chmod(name, stat.S_IWRITE), remove(name)))


def native_question_records(root,question,answer,turn,displayed=None,title=None,injected=False,cwd=None):
    from datetime import datetime,timedelta,timezone
    call='call-'+turn
    at=datetime.now(timezone.utc)+timedelta(seconds=1)
    shown={'type':'event_msg','timestamp':at.isoformat(),'payload':{'type':'item_completed','thread_id':'s','turn_id':turn,
        'item':{'type':'AgentMessage','id':call,'delivery':'async','questions':[displayed or question]}}}
    text='<send_user_message_question_reply>\n'+json.dumps([{'questionItemId':json.dumps(['request_user_input_async',call,0]),
        'question':title or question['title'],'answer':answer}])+'\n</send_user_message_question_reply>'
    human={'type':'event_msg','timestamp':(at+timedelta(milliseconds=1)).isoformat(),'payload':{
        'type':'item_completed','thread_id':'s','turn_id':turn,
        'item':{'type':'UserMessage','id':'message-'+turn,'content':[{'type':'text','text':text}]}}}
    requested={'type':'response_item','timestamp':at.isoformat(),'payload':{'type':'function_call',
        'name':'request_user_input_async','call_id':call,'arguments':json.dumps({'questions':[displayed or question]})}}
    return [{'type':'turn_context','payload':{'cwd':str(cwd or root)}},requested,shown,
                    {'type':'response_item','payload':{'role':'user','content':text}} if injected else human]


class GateTest(unittest.TestCase):
    setUp_workflow = fixtures.WorkflowTest.setUp
    git = fixtures.WorkflowTest.git
    fake = fixtures.WorkflowTest.fake

    @classmethod
    def setUpClass(cls):
        # Every test works in the same folder, so a run started once per host can be copied back to the same paths.
        cls.work = Path(tempfile.mkdtemp()).resolve();cls.addClassCleanup(clear, cls.work)
        cls.started = {}

    def setUp(self):
        folder = self.work / 'test'
        if folder.exists():clear(folder)
        folder.mkdir()
        with patch.object(fixtures.tempfile, 'TemporaryDirectory', return_value=SimpleNamespace(name=str(folder), cleanup=lambda: None)):
            self.setUp_workflow()
        self.home = folder / 'home'
        patcher = patch('pathlib.Path.home', return_value=self.home);patcher.start();self.addCleanup(patcher.stop)
        self.transcript = self.home / '.claude/projects/p/s.jsonl';self.transcript.parent.mkdir(parents=True)
        self.records = []
        # A menu needs only one finished task and one left: every task a batch runs costs seconds of Git work.
        fixtures.configure(self.root, tasks_per_batch=1);self.tasks = self.tasks[:2]

    def begin(self, host, fresh=False):
        """Start a run owned by conversation `s` and run it to its first menu. The first test per host does the
        work; later tests get a copy of that project and OH state at the same paths, which is much faster. A test
        that runs more tasks needs its own run (`fresh`): OH refuses a branch whose Git history was copied."""
        folder, saved = self.work / 'test', self.work / ('started-' + host)
        if host in self.started and not fresh:
            clear(folder);shutil.copytree(saved, folder, symlinks=True)
            # OH ties a checkout to its folder's file identity, which a copy changes: record the copy's, as reattaching does.
            from .registry import identity, index_path
            from .storage import atomic_json, read_json
            atomic_json(index_path(self.root), read_json(index_path(self.root)) | {'identity': identity(self.root)})
            return json.loads(self.started[host])
        prompt = 'oh start .oh/tasks.json'
        start(self.root, {'tasks': self.tasks}, human_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': '1', 'prompt': prompt}, host))
        result = run(self.root, self.fake)
        if host not in self.started:
            shutil.copytree(folder, saved, symlinks=True);type(self).started[host] = json.dumps(result)
        return result

    def click(self, question, answer, use='toolu_1', session='s', prefilled=None, questions=None, extra=None, raw=None, cwd=None, apply=True):
        """Save a question-tool call and the host's answer in the owner's transcript, as Claude does, then run OH."""
        from .storage import now
        time.sleep(0.01)  # a person answers later than OH's own records, never within the same millisecond
        request = {'questions': questions or [question]} | ({'answers': prefilled} if prefilled is not None else {}) | (extra or {})
        where = str(cwd or self.root)
        self.records += [
            {'type': 'assistant', 'sessionId': session, 'cwd': where, **({'wireToolInputs': {use: raw}} if raw else {}),
             'message': {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': use, 'name': 'AskUserQuestion', 'input': request}]}},
            {'type': 'user', 'sessionId': session, 'cwd': where, 'timestamp': now(),
             'toolUseResult': {'questions': request['questions'], 'answers': {question['question']: answer}},
             'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': use, 'content': 'answered'}]}}]
        self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records), newline='\n')
        return materialize(self.root) if apply else None

    def test_checkpoint_offers_its_choices_as_a_menu_that_expires_when_the_run_moves(self):
        result = self.begin('claude', fresh=True)
        self.assertEqual(result['gate']['choices'], ['continue', 'pr', 'stop'])
        question = result['gate']['ask']['questions'][0]
        self.assertEqual([o['label'] for o in question['options']], ['Continue', 'Open a PR', 'Stop and take over'])
        self.assertNotIn('Branch work.',question['question'])
        self.assertIn('Completed: 1. Pending: 2:',result['gate']['details'])
        self.assertIn('Checks:',result['gate']['details'])
        self.assertLess(len(question['question']),400)
        self.assertEqual(question['options'][0]['description'],'Run the next 1 task, up to 3 reviews each.')
        self.assertIn('AskUserQuestion', result['gate']['how'])
        choose(self.root, 'continue', human_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': '2', 'prompt': 'continue'}, 'claude'))
        self.assertIsNone(current(self.root))  # running: nothing to choose
        after = run(self.root, self.fake)
        self.assertEqual(after['gate']['choices'], ['pr', 'stop'])
        self.assertEqual(after['gate']['ask']['questions'][0]['options'][1]['label'],'Finish without a PR')
        self.assertNotEqual(after['gate']['id'], result['gate']['id'])

    def prepare_menu(self,host):
        from .prepared import prepare,directory
        from .storage import atomic_json,now
        self.git('switch','main')
        prompt='/oh-deliver fix the sign-in timeout'
        if host=='claude':self.typed(prompt,'prepare')
        else:
            from .test_mcp_server import codex_session
            codex_session(self.home,'s',self.root)
            path=next((self.home/'.codex/sessions').rglob('*s.jsonl'))
            # Codex's MCP path has no prompt hook: discover the current UserMessage itself.
            records=[{'type':'session_meta','payload':{'id':'s','cwd':str(self.root),'source':'vscode','originator':'Codex Desktop'}},
                {'type':'event_msg','payload':{'type':'task_started','turn_id':'prepare'}},
                {'type':'event_msg','timestamp':now(),'payload':{'type':'item_completed','thread_id':'s','turn_id':'prepare',
                    'item':{'type':'UserMessage','id':'prepare-message','content':[{'type':'text',
                        'text':'[$o-harness:oh-deliver](/plugins/oh-deliver/SKILL.md) fix the sign-in timeout'}]}}}]
            path.write_text(''.join(json.dumps(r)+'\n' for r in records),newline='\n')
        manifest=directory(self.root).parent/'tasks.json';atomic_json(manifest,{'tasks':self.tasks})
        with patch.dict(os.environ,{'CODEX_HOME':str(self.home/'.codex'),'CODEX_THREAD_ID':'s' if host=='codex' else ''}):result=prepare(self.root,str(manifest))
        return result,manifest

    def test_prepared_claude_menu_binds_scope_limits_and_expires(self):
        """docs/usage.md: prepared approval grants only the shown snapshot, in its owning conversation."""
        from .prepared import prepare
        from .storage import atomic_json
        self.git('switch','main')
        base=self.git('rev-parse','HEAD')
        origin=Path(self.temp.name)/'origin.git'
        subprocess.run(['git','clone','-q','--bare',str(self.root),str(origin)],check=True)
        self.git('remote','add','origin',str(origin))
        def advance_main(message):
            # A remote merge happened while local main and the old delivery checkout stayed behind.
            previous=self.git('rev-parse','main')
            self.git('commit','--allow-empty','-qm',message)
            latest=self.git('rev-parse','HEAD');self.git('push','-q','origin','main')
            self.git('reset','-q','--hard',previous)
            self.git('update-ref','refs/remotes/origin/main',previous)
            return latest
        latest=advance_main('merged delivery')
        self.git('switch','-qc','deliver/old')
        result,manifest=self.prepare_menu('claude')
        first_run=load_run(self.root)[1]['id']
        self.assertEqual(load_run(self.root)[1]['base'],latest)
        self.assertEqual(self.git('rev-parse','main'),latest)
        self.assertEqual(self.git('rev-parse','deliver/old'),base)  # retained, not reused or erased
        question=result['gate']['ask']['questions'][0]
        self.assertEqual(result['gate']['choices'],['approve','refine','cancel'])
        self.assertIn('Implement behavior',Path(result['gate']['preview']).read_text())
        self.assertNotIn('Implement behavior',question['question'])
        self.assertEqual(run(self.root,self.fake)['status'],'prepared_checkpoint')
        self.assertEqual(self.calls,[]);self.assertEqual(self.git('branch','--show-current'),'main')
        self.assertIsNone(self.click(question,'Approve',session='other'))
        revised_base=advance_main('another merge before refinement')
        # Refine on Claude consumes ordinary native chat text; revised scope still needs approval.
        followup=self.click(question,'Refine',use='refine-menu')
        self.assertIn('waiting',followup);self.assertNotIn('gate',followup)
        self.assertIsNone(current(self.root));self.assertEqual(load_run(self.root)[1]['granted'],[])
        words='Keep all tests in one Python file.'
        self.typed(words,'refinement',hook=False)  # Claude's narrow prompt hook skips ordinary chat
        feedback=materialize(self.root)
        self.assertTrue(feedback['prepare']);self.assertEqual(feedback['feedback'],words)
        self.assertNotIn('gate',feedback);self.assertEqual(load_run(self.root)[1]['granted'],[])
        with self.assertRaisesRegex(Refused,'Revise the unapproved task list'):
            choose(self.root,'approve',human_event({'hook_event_name':'UserPromptSubmit','session_id':'s','turn_id':'premature','prompt':'approve'},'claude'))
        atomic_json(manifest,{'tasks':[self.tasks[0]|{'instructions':words},self.tasks[1]]})
        newer=prepare(self.root,str(manifest))['gate']['ask']['questions'][0]
        self.assertEqual(load_run(self.root)[1]['base'],revised_base)
        self.assertEqual(self.git('rev-parse','main'),revised_base)
        self.assertIn(words,load_run(self.root)[1]['tasks'][0]['instructions'])
        self.assertEqual(load_run(self.root)[1]['granted'],[])
        self.assertNotEqual(newer['question'],question['question'])
        self.assertIsNone(self.click(question,'Approve',use='old-menu'))
        atomic_json(manifest,{'tasks':self.tasks+[{'id':'extra','title':'Not shown','instructions':'Do not grant'}]})
        fixtures.configure(self.root,tasks_per_batch=99,review_rounds=99)
        self.git('branch','deliver/task-1/old')
        self.git('update-ref','refs/remotes/origin/deliver/Task-1-2',revised_base)
        from . import prepared
        original=prepared.git
        def interrupted(root,*args):
            result=original(root,*args)
            if args[0]=='switch':raise OSError('interrupted after branch switch')
            return result
        with patch('oh.prepared.git',side_effect=interrupted):
            with self.assertRaisesRegex(OSError,'interrupted after branch switch'):
                self.click(newer,'Approve',use='current-menu')
        self.assertEqual(current(self.root)['question'],newer['question'])
        self.assertEqual(materialize(self.root)['status'],'running')  # same actual answer, no second approval
        state=load_run(self.root)[1]
        self.assertEqual([t['id'] for t in state['tasks']],['1','2']);self.assertEqual(state['granted'],['1'])
        self.assertEqual(state['config']['review_rounds'],3)
        self.assertEqual(state['branch'],'deliver/task-1-3')
        self.assertEqual(self.git('rev-parse','deliver/task-1/old'),revised_base)
        self.assertEqual(self.git('rev-parse','HEAD'),revised_base)
        self.assertIsNone(materialize(self.root))  # the saved click cannot grant again
        # Publish one completed task. Even an older/stale main reference must not export main's commits.
        result=run(self.root,self.fake)
        completed=self.git('rev-parse','HEAD')
        self.click(result['gate']['ask']['questions'][0],'Open a PR',use='publish-menu')
        self.git('update-ref','refs/remotes/origin/main',base)
        import contextlib
        from .cli import main
        with contextlib.redirect_stdout(io.StringIO()) as output:
            main(['--root',str(self.root),'pr-summary'])
        packet=json.loads(output.getvalue().split('```json\n')[1].split('\n```')[0])
        self.assertEqual([r['commit'] for r in packet['records']],[completed])
        self.assertEqual(self.git('rev-parse','origin/main'),revised_base)
        self.assertEqual(len(self.calls),2)  # no repeated work or review at publication
        from .telemetry import collect,connect
        collect()
        with connect() as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?',(first_run,)).fetchone()[0],'stopped')
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?',(state['id'],)).fetchone()[0],'pr')

    def test_prepared_codex_menu_uses_native_click_and_can_stop(self):
        self.tasks[0]['title']='Sign-in [form]'
        self.tasks[0]['instructions']='Update [the login form](login.tsx). Check [ ] timeout.'
        result,_=self.prepare_menu('codex')
        self.assertIn('Approve',result['gate']['native_ask']['questions'][0]['title'])
        self.assertIn('conversation that started this run',self.server(self.root,{'action':'accept','content':{'choice':'approve'}},thread='other')[1])
        sent,text=self.server(self.root,{'action':'accept','content':{'choice':'cancel'}})
        self.assertIn('nothing left to run',text)
        message=next(m for m in sent if m.get('method')=='elicitation/create')['params']['message']
        for detail in ('Sign-in [form]','[the login form](login.tsx)','[ ] timeout','Task 2:'):
            self.assertIn(detail,Path(result['gate']['preview']).read_text())
            self.assertNotIn(detail,message)
        self.assertIn('Approve this task list?',message)
        self.assertIn('Runs 1 of 2 tasks',Path(result['gate']['preview']).read_text())  # the full approval copy binds the finite grant
        self.assertEqual(next(m for m in sent if m.get('method')=='elicitation/create')['params']['requestedSchema']['properties']['choice']['enumNames'],['Approve','Refine','Cancel'])
        for internal in (str(self.root),result['gate']['preview'],'Project:','Full preview:','- Approve','- Refine'):
            self.assertNotIn(internal,message)
        self.assertNotIn('[OH gate ',message)
        self.assertEqual(load_run(self.root)[1]['granted'],[])
        self.assertEqual(self.git('branch','--show-current'),'main')

    def test_codex_native_question_binds_preview_and_preserves_the_human_answer(self):
        """docs/usage.md: a side-panel review and a native question share one approval subject."""
        from .authority import desktop_answer
        result,_=self.prepare_menu('codex');gate=result['gate'];question=gate['native_ask']['questions'][0]
        path=next((self.home/'.codex/sessions').rglob('*s.jsonl'))
        records=[json.loads(line) for line in path.read_text().splitlines()]
        def reply(answer,displayed=None,title=None,injected=False,cwd=None,legacy=False):
            turn='answer-'+str(len(records))
            added=native_question_records(self.root,question,answer,turn,displayed,title,injected,cwd)
            records.extend(r for r in added if not legacy or (r.get('payload',{}).get('item') or {}).get('type')!='AgentMessage')
            path.write_text(''.join(json.dumps(r)+'\n' for r in records),newline='\n')
            return desktop_answer(self.root)
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'s','CODEX_HOME':str(self.home/'.codex'),'OH_CODEX_TURN_ID':''}):
            approve=question['options'][0]
            self.assertIsNone(reply(approve,injected=True))
            with self.assertRaisesRegex(Refused,'displayed question'):
                reply(approve,displayed=question|{'options':['Approve']})
            self.assertIsNone(reply(approve,title='An older preview'))
            with self.assertRaisesRegex(Refused,'another project checkout'):reply(approve,cwd=self.home)
            preview=Path(gate['preview']);original=preview.read_bytes();preview.write_bytes(original+b'Changed scope\n')
            with self.assertRaisesRegex(Refused,'preview was edited'):reply(approve)
            preview.write_bytes(original)
            self.assertIsNone(desktop_answer(self.root))  # restoring the file does not revive the refused approval
            self.assertEqual(load_run(self.root)[1]['granted'],[])
            from . import prepared
            original=prepared.git
            def interrupted(root,*args):
                result=original(root,*args)
                if args[0]=='update-ref':raise OSError('interrupted after branch creation')
                return result
            with patch('oh.prepared.git',side_effect=interrupted):
                with self.assertRaisesRegex(OSError,'interrupted after branch creation'):
                    reply(approve,legacy=True)  # the tool call proves the question without a UI event
            applied=desktop_answer(self.root)  # preserve the actual approval while recovering the owned ref
            self.assertEqual(applied['status'],'running')
            journal,state=load_run(self.root)
            self.assertEqual(state['granted'],['1'])
            count=len(journal.records())
            source=next(r['data']['source'] for r in reversed(journal.records()) if r['kind']=='transition')
            from .storage import state_home
            receipt=state_home()/'projects'/state['project']/'human-events'/(source['native_reply']+'.json')
            receipt.unlink()  # simulate a crash after the grant was saved but before its receipt
            self.assertEqual(desktop_answer(self.root)['status'],'running')
            self.assertIsNone(desktop_answer(self.root))
            self.assertEqual(len(load_run(self.root)[0].records()),count)

    def test_large_menus_bound_the_handoff_and_preserve_complete_details(self):
        """docs/usage.md: long approval and recovery menus link complete retained reports."""
        from .config import load
        from .gates import describe,review_history,summary
        from .storage import digest,read_json
        from .workflow import validate_tasks
        tasks=validate_tasks([{'id':str(i),'title':'Task '+str(i),'instructions':'x'*1000} for i in range(1000)])
        journal=SimpleNamespace(path=Path(self.temp.name)/'menu-evidence',records=lambda:[{'hash':'head'}])
        state={'id':'run','host':'claude','branch':'work','tasks':tasks,'done':[],
               'attempts':[],'config':load(self.root),'status':'prepared_checkpoint'}
        scope={'severity':'scope','description':'Future work','path':'','family':'future'}
        bug={'severity':'blocking','description':'Fix timeout','path':'','family':'timeout'}
        for status in ('prepared_checkpoint','checkpoint','completed','review_checkpoint','findings_checkpoint','needs_attention','paused'):
            state['status']=status
            bug['severity']='concern' if status=='findings_checkpoint' else 'blocking'
            state['attempts']=[{'id':'r','task':'0','role':'review','outcome':'blocking','findings':[bug,scope],
                                'summary':'raw protocol','human_summary':'Timeout remains'}]
            state['scope_records']={'r':{'action':'route','destination':{'design':'design.md'},'findings':[scope]}}
            state['granted']=['0'];state['summaries']=[{'commit':'completed-task'}]
            gate=describe(journal,state)
            self.assertLessEqual(len(summary(state)),8000)
            self.assertLess(len(json.dumps(ask(gate)))+len(gate['summary']),state['config']['context']['handoff_chars'])
            self.assertLess(len(gate['question']),400)
            if status!='prepared_checkpoint':
                self.assertNotIn('preview',gate)  # decisions and renewals stay in chat, never a side panel
                self.assertNotIn('Timeout remains',gate['question'])
                self.assertNotIn('raw protocol',gate['question'])
            if status=='review_checkpoint':
                self.assertEqual([o['choice'] for o in gate['options']],['grant review','stop','handoff pr'])
                private=describe(journal,state|{'workflow':'design','plans':{'location':'private'}})
                self.assertEqual([o['choice'] for o in private['options']],['grant review','stop'])
                self.assertIn('3 more reviews',gate['options'][0]['label'])
            if status=='prepared_checkpoint':saved={'report':Path(gate['preview']).read_text()}
            else:
                path=Path(gate['details'].split('Complete details: ',1)[1].split('\n',1)[0])
                saved=read_json(path)
                self.assertEqual(path.stem,digest(saved))
            self.assertIn('999: Task 999',saved['report'])
            if status=='prepared_checkpoint':
                self.assertIn('of 1000 tasks',Path(gate['preview']).read_text())
                self.assertIn('Task 999: Task 999\n\n'+'x'*1000,saved['report'])
                self.assertLess(len(gate['question']),250)
            if status in ('review_checkpoint','findings_checkpoint','needs_attention'):
                self.assertIn('Timeout remains',saved['report']);self.assertNotIn('raw protocol',saved['report'])
            self.assertEqual(describe(journal,state),gate)  # an unchanged report keeps the same immutable reference
        for action in ('route','dismiss'):
            state['scope_records']['r']['action']=action
            history='\n'.join(review_history(state,'0'))
            self.assertIn('Scope: '+action+'; design: design.md',history)
            self.assertIn('scope: Future work',history)
            self.assertEqual(history.split('Open findings: ')[1],'blocking: Fix timeout')

    def test_a_click_on_claude_is_read_from_its_transcript_and_applied(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.assertEqual(self.click(question, 'Continue')['status'], 'running')
        _, state = load_run(self.root)
        self.assertEqual(state['granted'][-1], '2')
        self.delayed_menu_commands(superseded=True)


    def test_model_written_or_altered_or_foreign_answers_choose_nothing(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        cases = [('prefilled', {'prefilled': {question['question']: 'Continue'}}),
                 ('another conversation', {'session': 'other'}),
                 ('altered menu', {'questions': [question | {'options': question['options'][:1] + [{'label': 'Stop', 'description': 'x'}]}]}),
                 ('mixed with another question', {'questions': [question, {'question': 'Also?'}]}),
                 ('extra input', {'extra': {'metadata': {'source': 'model'}}}),
                 ('raw input differs', {'raw': {'questions': [question], 'answers': {question['question']: 'Continue'}}})]
        for index, (name, change) in enumerate(cases):
            with self.subTest(name):
                self.assertIsNone(self.click(question, 'Continue', use=f'toolu_{index + 2}', **change))
                self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        with self.assertRaises(Refused):self.click(question, 'Just keep going', use='toolu_9')  # free text is no choice here
        self.assertIsNone(materialize(self.root))  # said once, then set aside
        self.assertEqual(self.click(question, 'Continue', use='toolu_10')['status'], 'running')

    def test_stop_on_a_finished_run_closes_its_menu(self):
        question = self.begin('claude', fresh=True)['gate']['ask']['questions'][0]
        choose(self.root, 'continue', human_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': '2', 'prompt': 'continue'}, 'claude'))
        question = run(self.root, self.fake)['gate']['ask']['questions'][0]
        after = self.click(question, 'Stop', use='toolu_stop')
        self.assertEqual((after['status'], after.get('gate')), ('stopped', None))
        self.delayed_menu_commands(superseded=False)

    def test_only_the_latest_click_on_the_current_menu_counts(self):
        question = self.begin('claude', fresh=True)['gate']['ask']['questions'][0]
        self.records += [
            {'type': 'assistant', 'sessionId': 's', 'cwd': str(self.root), 'message': {'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': 'toolu_first', 'name': 'AskUserQuestion', 'input': {'questions': [question]}}]}},
            {'type': 'user', 'sessionId': 's', 'cwd': str(self.root), 'toolUseResult': {'answers': {question['question']: 'Stop'}},
             'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'toolu_first', 'content': 'x'}]}}]
        self.assertEqual(self.click(question, 'Continue', use='toolu_latest')['status'], 'running')  # the person changed their mind
        self.assertIsNone(materialize(self.root))  # the earlier Stop is on an older menu now: nothing re-applies it
        run(self.root, self.fake)
        self.assertEqual(load_run(self.root)[1]['status'], 'completed')

    def test_a_click_counts_from_a_subfolder_of_the_checkout(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        (self.root / 'docs').mkdir()
        self.assertEqual(self.click(question, 'Continue', cwd=self.root / 'docs')['status'], 'running')

    def test_an_older_click_never_displaces_a_newer_typed_choice(self):
        from .authority import pending_file, stage
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.click(question, 'Continue', apply=False)  # clicked, but OH didn't run yet
        stage(self.root, 'claude', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt_id': 'later', 'prompt': 'stop'})
        with self.assertRaises(Refused):materialize(self.root)  # the typed stop isn't saved yet: nothing happens
        self.assertTrue(pending_file(self.root).exists())
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')

    def typed(self, prompt, turn, cwd=None, save=True, extra=None, hook=True):
        """The person types a choice: the prompt hook stages it, and Claude saves the turn."""
        from .authority import stage
        from .storage import now
        time.sleep(0.01)
        if hook:stage(self.root, 'claude', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt_id': turn, 'prompt': prompt,
                                    'transcript_path': str(self.transcript)})
        if save:
            self.records.append({'type': 'user', 'sessionId': 's', 'promptId': turn, 'cwd': str(cwd or self.root), 'timestamp': now(),
                                 'message': {'role': 'user', 'content': prompt}} | (extra or {}))
            self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records), newline='\n')

    def activity(self):
        """Claude saves something later in the conversation, such as the agent's next tool call."""
        from .storage import now
        self.records.append({'type': 'assistant', 'sessionId': 's', 'cwd': str(self.root), 'timestamp': now(), 'message': {'role': 'assistant', 'content': []}})
        self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records), newline='\n')

    def test_the_latest_answer_wins_typed_or_clicked(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.typed('continue', 'typed-1')
        self.assertEqual(self.click(question, 'Stop', use='toolu_later')['status'], 'stopped')  # the click came after the typing
        self.assertIsNone(materialize(self.root))  # the typed continue is spent, never replayed

    def test_a_typed_choice_after_a_click_wins(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.click(question, 'Stop', apply=False)
        self.typed('continue', 'typed-2')
        self.assertEqual(materialize(self.root)['status'], 'running')

    def test_a_typed_choice_that_cannot_be_read_applies_nothing_older(self):
        from .authority import pending_file
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.click(question, 'Stop', apply=False)
        self.typed('continue', 'unread', save=False)  # typed after the click, but not saved where OH reads
        with self.assertRaises(Refused):materialize(self.root)  # Claude might still be saving it
        self.activity()  # the conversation moved on without it
        with self.assertRaisesRegex(Refused, 'could not read your typed choice'):materialize(self.root)
        self.assertFalse(pending_file(self.root).exists())
        self.assertIsNone(materialize(self.root))  # the older Stop click is set aside, never applied
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        self.assertEqual(self.click(question, 'Stop', use='toolu_again')['status'], 'stopped')  # choosing again works

    def test_typed_choices_count_as_saved_by_the_desktop_app_but_not_from_other_senders(self):
        desktop = {'origin': {'kind': 'human'}, 'turnOrigin': 'human', 'promptSource': 'sdk', 'entrypoint': 'claude-desktop'}
        self.begin('claude')
        for name, extra in (('another agent', {'origin': {'kind': 'peer'}}), ('a notification', {'promptSource': 'system'}),
                            ('an automated caller', {'entrypoint': 'sdk-cli'})):
            with self.subTest(name):
                self.typed('continue', 'from-' + name.split()[-1], extra=extra)
                with self.assertRaisesRegex(Refused, 'could not read'):materialize(self.root)
                self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        self.typed('continue', 'desktop', extra=desktop)
        self.assertEqual(materialize(self.root)['status'], 'running')

    def test_a_refused_latest_answer_never_lets_an_older_one_apply(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.click(question, 'Continue', apply=False)
        self.typed('retry', 'typed-4')  # the person's latest answer, which this checkpoint refuses
        with self.assertRaises(Refused):materialize(self.root)
        self.assertIsNone(materialize(self.root))  # the older Continue click never takes its place
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')

    def test_answers_from_a_checkout_nested_inside_do_not_count(self):
        from .authority import within
        self.begin('claude')
        nested = self.root / '.claude/worktrees/other';nested.mkdir(parents=True);(nested / '.git').write_text('gitdir: elsewhere')
        self.assertFalse(within(nested, self.root));self.assertTrue(within(self.root / 'docs', self.root))
        self.typed('continue', 'typed-5', cwd=nested)
        with self.assertRaisesRegex(Refused, 'could not read'):materialize(self.root)  # said, never applied
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')

    def test_a_typed_choice_from_a_subfolder_verifies(self):
        self.begin('claude')
        (self.root / 'docs').mkdir()
        self.typed('continue', 'typed-3', cwd=self.root / 'docs')
        self.assertEqual(materialize(self.root)['status'], 'running')

    def test_a_refused_command_never_holds_up_the_open_menu(self):
        from .authority import pending_file, stage
        from .storage import now
        question = self.begin('claude')['gate']['ask']['questions'][0]
        # While the run waits at its menu, the person types another delivery: refused, and kept for later.
        self.records.append({'type': 'user', 'sessionId': 's', 'promptId': 'p2', 'cwd': str(self.root), 'timestamp':now(), 'message': {'role': 'user', 'content': '/oh-deliver 0006'}})
        self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records), newline='\n')
        stage(self.root, 'claude', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt_id': 'p2', 'prompt': '/oh-deliver 0006'})
        with self.assertRaisesRegex(Refused, 'still working on'):materialize(self.root)
        self.assertEqual(self.click(question, 'Continue')['status'], 'running')  # the click still counts
        self.assertFalse(pending_file(self.root).exists())  # and it is the person's latest act

    def waiting_command(self, prompt='/oh-deliver 0006', first=None, tagged=False):
        """The person types another command while the run waits at its menu: OH refuses it and keeps it. `first`
        is what they did before typing it. `tagged` saves it as Claude saves a typed slash command."""
        from .authority import stage
        from .storage import now
        question = self.begin('claude')['gate']['ask']['questions'][0]
        if first:first(question)
        time.sleep(0.01)
        name, _, args = prompt.partition(' ')
        content = f'<command-message>{name[1:]}</command-message>\n<command-name>{name}</command-name>\n<command-args>{args}</command-args>' if tagged else prompt
        self.records.append({'type': 'user', 'sessionId': 's', 'promptId': 'p2', 'uuid': 'u2', 'cwd': str(self.root), 'timestamp': now(), 'message': {'role': 'user', 'content': content}})
        if tagged:  # the skill Claude expanded from that very record
            self.records.append({'type': 'user', 'sessionId': 's', 'promptId': 'p2', 'cwd': str(self.root), 'isMeta': True, 'parentUuid': 'u2',
                                 'message': {'role': 'user', 'content': [{'type': 'text', 'text': f'Base directory for this skill: /x/o-harness/skills/{name[1:]}'}]}})
        self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records), newline='\n')
        stage(self.root, 'claude', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt_id': 'p2', 'prompt': prompt})
        with self.assertRaisesRegex(Refused, 'stop it and start this command .*or keep it and cancel'):materialize(self.root)
        return question

    def test_cancelling_the_waiting_command_keeps_the_open_run(self):
        from .authority import cancel, pending_file, stage
        from .controls import request
        from .storage import now
        self.waiting_command(tagged=True)
        pending=[self.staged_conversation('claude',session,at=now())[0] for session in ('cancel-a','cancel-b')]
        original={'hook_event_name':'UserPromptSubmit','session_id':'s','prompt_id':'p2','prompt':'/oh-deliver 0006'}
        stage(self.root,'claude',original)  # delayed older delivery must not hide the other waiting requests
        with patch.dict(os.environ, {'OH_CHILD_ATTEMPT': 'a'}), self.assertRaises(Refused):cancel(self.root)  # never a worker's call
        self.assertEqual(cancel(self.root)['cancelled'], '/oh-deliver 0006')
        self.assertFalse(pending_file(self.root).exists())
        self.assertIsNone(materialize(self.root))  # nothing waits: `run` carries on with the open run
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        # The cancelled turn never comes back, however it is spelled: here Claude saved it as command tags.
        request(self.root, 'stop')
        for payload in [original,*pending]:
            stage(self.root,'claude',payload)
            with self.assertRaisesRegex(Refused,'Cancelled by the person'):materialize(self.root)

    def test_stopping_the_open_run_starts_the_waiting_command(self):
        from .authority import pending_file
        from .controls import request
        self.waiting_command()
        self.assertEqual(request(self.root, 'stop')['status'], 'stopped')
        # Past the open run, the same typed command is carried out: here it needs a setting first, and still waits.
        with self.assertRaisesRegex(Refused, 'Choose where plans live'):materialize(self.root)
        self.assertTrue(pending_file(self.root).exists())

    def test_a_menu_answer_counts_over_a_waiting_command_only_when_given_after_it(self):
        from .authority import pending_file,used_file
        from .storage import now,read_json
        # Clicked before typing the command (the agent never ran OH after the click): the command is the latest act.
        self.waiting_command(first=lambda question: self.click(question, 'Continue', apply=False))
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        self.assertTrue(pending_file(self.root).exists())
        # Answered after typing it: the answer counts, and OH says it set the command aside, also where the agent
        # runs the typed delivery itself.
        from contextlib import redirect_stdout
        from .cli import main
        question = self.waiting_command()
        other=self.staged_conversation('codex','other-host',at=now())[0]
        self.click(question, 'Continue', use='toolu_2', apply=False)
        out = io.StringIO()
        with redirect_stdout(out):main(['--root', str(self.root), 'deliver', '0006'])
        self.assertIn('so OH set that command aside', out.getvalue())
        self.assertEqual(load_run(self.root)[1]['status'], 'running')
        self.assertFalse(pending_file(self.root).exists())
        self.assertIn('Superseded',read_json(used_file(self.root,human_event(other,'codex')))['refused'])

    def test_a_refused_choice_is_said_once_and_never_holds_up_the_run(self):
        from .authority import pending_file
        from .runner import apply_pending
        self.begin('claude')
        self.typed('/oh-resume', 'p2')  # nothing is paused: refused, and not kept
        with self.assertRaises(Refused):materialize(self.root)
        self.assertFalse(pending_file(self.root).exists())
        self.assertIsNone(materialize(self.root))
        # A command that starts other work waits for the agent's next `run`, never stopping the run's own steps.
        self.waiting_command()
        apply_pending(self.root)
        self.assertTrue(pending_file(self.root).exists())

    def test_typing_something_else_sets_the_waiting_command_aside_once(self):
        from .authority import pending_file
        self.waiting_command()
        self.records.append({'type': 'user', 'sessionId': 's', 'promptId': 'p3', 'cwd': str(self.root), 'message': {'role': 'user', 'content': 'what is left?'}})
        self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records), newline='\n')
        with self.assertRaisesRegex(Refused, 'You typed something after /oh-deliver 0006, so OH set it aside'):materialize(self.root)
        self.assertFalse(pending_file(self.root).exists())
        self.assertIsNone(materialize(self.root))  # said once
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')

    def test_a_forged_typed_choice_grants_nothing(self):
        from .authority import stage
        question = self.begin('claude')['gate']['ask']['questions'][0]
        stage(self.root, 'claude', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt_id': 'forged', 'prompt': 'continue'})
        with self.assertRaises(Refused):self.click(question, 'Stop')  # the forged turn never verifies, so nothing applies
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        self.assertEqual(self.click(question, 'Stop', use='toolu_again')['status'], 'stopped')

    def test_an_applied_answer_counts_the_owner_conversation(self):
        from .storage import digest, read_json, state_home
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.assertEqual(self.click(question, 'Continue')['status'], 'running')
        source = read_json(state_home() / 'sources' / (digest({'host': 'claude', 'session': 's'}) + '.json'))
        self.assertEqual((source['run'], source['path']), (load_run(self.root)[1]['id'], str(self.transcript)))

    def test_free_text_is_a_change_request_only_where_one_is_allowed(self):
        gate = {'options': [{'choice': 'approve', 'label': 'Approve'}, {'choice': 'cancel', 'label': 'Cancel'}], 'words': True}
        self.assertEqual(pick(gate, 'approve'), 'approve')
        self.assertEqual(pick(gate, 'Make the title shorter'), 'refine: Make the title shorter')
        self.assertEqual(pick(gate, 'refine: shorter title'), 'refine: shorter title')
        for command in ('stop', 'Stop', 'pause', 'continue', '/oh-stop', '$oh-deliver 0001'):
            with self.subTest(command), self.assertRaises(Refused):pick(gate, command)  # a command, never a change request
        with self.assertRaises(Refused):pick(gate | {'words': False}, 'Make the title shorter')

    def test_the_hook_refuses_prefilled_answers_on_oh_menus_only(self):
        script = HOME / 'plugins/o-harness/scripts/gate-hook.py'
        def pre(question, **extra):
            payload = {'hook_event_name': 'PreToolUse', 'tool_input': {'questions': [{'question': question}]} | extra}
            return subprocess.run([sys.executable, str(script), 'pre'], input=json.dumps(payload), capture_output=True, text=True).stdout
        self.assertIn('deny', pre('Continue? [OH gate abc]', answers={'Continue? [OH gate abc]': 'Continue'}))
        self.assertEqual(pre('Continue? [OH gate abc]'), '')
        self.assertEqual(pre('Pick a colour', answers={'Pick a colour': 'Red'}), '')
        payload = {'hook_event_name': 'PreToolUse', 'tool_input': {'questions': [{'question': 'Continue? [OH gate abc]'}, {'question': 'Also?'}]}}
        self.assertIn('one question on its own', subprocess.run([sys.executable, str(script), 'pre'], input=json.dumps(payload), capture_output=True, text=True).stdout)

    def server(self, root, reply, capabilities=None, while_open=None, thread='s'):
        """Play the Codex host in conversation `thread`: answer the menu the server opens with `reply`."""
        from .test_mcp_server import calling, codex_session, play
        codex_session(self.home, thread, self.root)
        def respond(_):
            if while_open:while_open()
            return reply
        with patch.dict(os.environ, {'CODEX_HOME': str(self.home / '.codex')}):
            sent = play([{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18',
                          'capabilities': {'elicitation': {}} if capabilities is None else capabilities}},
                         {'id': 2, 'method': 'tools/call', 'params': {'name': 'choose', 'arguments': {'root': str(root)}} | calling(thread)}], respond)
        return sent, next(m for m in sent if m.get('id') == 2)['result']['content'][0]['text']

    def staged_conversation(self,host,session,at='2020-01-01T00:00:00Z',partial=False):
        """A competing native command, in its own conversation, while the current menu is open."""
        from .authority import stage
        prompt=('$' if host=='codex' else '/')+'oh-propose '+session
        path=self.home/('.codex/sessions' if host=='codex' else '.claude/projects')/(session+'.jsonl')
        path.parent.mkdir(parents=True,exist_ok=True)
        records=([{'type':'session_meta','payload':{'id':session,'cwd':str(self.root),'source':'cli'}},
                  {'type':'event_msg','payload':{'type':'task_started','turn_id':'1'}},
                  {'type':'event_msg','timestamp':at,'payload':{'type':'user_message','message':prompt}}] if host=='codex' else
                 [{'type':'user','timestamp':at,'sessionId':session,'promptId':'1','cwd':str(self.root),
                   'message':{'role':'user','content':prompt}}])
        text=''.join(json.dumps(r)+'\n' for r in records)
        path.write_text(text[:-8] if partial else text,newline='\n')
        payload={'hook_event_name':'UserPromptSubmit','session_id':session,'turn_id':'1','prompt':prompt,'transcript_path':str(path)}
        stage(self.root,host,payload)
        return payload,path,text

    def test_codex_menu_records_the_click_itself(self):
        from .authority import used_file
        from .storage import read_json
        self.begin('codex')
        pending=[(host,self.staged_conversation(host,session)[0]) for host,session in
                 (('codex','a'),('claude','other-host'),('codex','b'))]
        sent, text = self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}})
        asked = next(m for m in sent if m.get('method') == 'elicitation/create')
        self.assertEqual(asked['params']['requestedSchema']['properties']['choice']['enum'], ['continue', 'pr', 'stop'])
        self.assertIn('Recorded', text)
        self.assertNotIn('Project:',asked['params']['message'])
        self.assertLess(len(asked['params']['message']),400)
        self.assertNotIn(' · run ', asked['params']['message'])
        self.assertNotIn('Run the next',asked['params']['message'])
        self.assertEqual(asked['params']['requestedSchema']['properties']['choice']['enumNames'][0],'Continue')
        _, state = load_run(self.root)
        self.assertEqual((state['status'], state['granted'][-1]), ('running', '2'))
        for host,payload in pending:
            self.assertIn('Superseded',read_json(used_file(self.root,human_event(payload,host)))['refused'])
        self.delayed_menu_commands(superseded=True)

        # Publication is a handoff to push/PR, not another execution of the task runner.
        self.begin('codex')
        self.git('remote','add','origin','https://user:secret@github.com/example/product.git?token=private')
        with patch('oh.branches.fetched',return_value='main'):  # display fixture URLs, never contact GitHub
            sent,text=self.server(self.root,{'action':'accept','content':{'choice':'pr'}})
        shown=next(m for m in sent if m.get('method')=='elicitation/create')['params']
        question=shown['message']
        publication=json.loads(text)['publication']
        offered=' '.join(shown['requestedSchema']['properties']['choice']['enumNames'])
        self.assertNotIn(publication['head'][:12],question)
        self.assertNotIn(publication['head'][:12],offered)
        self.assertEqual(shown['requestedSchema']['properties']['choice']['enumNames'],['Continue','Open a PR','Stop and take over'])
        self.assertNotIn('.git',offered);self.assertNotIn('secret',offered);self.assertNotIn('private',offered)
        self.assertIn('Execution is finished',publication['next'])
        self.assertNotIn('Call `run`',text)
        self.assertEqual(load_run(self.root)[1]['status'],'pr')

        # Short native labels still bind the actual human click to the exact saved publication scope.
        self.begin('codex')
        self.git('remote','add','origin','git@github.com:example/product.git')
        from .workflow import checkpoint
        gate=checkpoint(self.root)['gate'];question=gate['native_ask']['questions'][0]
        self.assertIn('request_user_input_async',gate['how'])
        self.assertNotIn('right panel',gate['how'])
        self.assertNotIn('github.com',question['title'])
        self.assertEqual(question['options'],['Continue','Open a PR','Stop and take over'])
        from .test_mcp_server import codex_session
        codex_session(self.home,'s',self.root)
        path=next((self.home/'.codex/sessions').rglob('*s.jsonl'))
        stale=native_question_records(self.root,question,question['options'][1],'old-pr-answer')
        for record in stale:
            if record.get('payload',{}).get('type')!='item_completed' or (record['payload'].get('item') or {}).get('type')!='UserMessage':
                record['timestamp']='2000-01-01T00:00:00+00:00'
        with path.open('a',newline='\n') as stream:
            for record in stale:stream.write(json.dumps(record)+'\n')
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'s','CODEX_HOME':str(self.home/'.codex'),'OH_CODEX_TURN_ID':''}):
            with self.assertRaisesRegex(Refused,'displayed question'):materialize(self.root)
        self.assertNotEqual(load_run(self.root)[1]['status'],'pr')
        with path.open('a',newline='\n') as stream:
            for record in native_question_records(self.root,question,question['options'][1],'pr-answer'):
                stream.write(json.dumps(record)+'\n')
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'s','CODEX_HOME':str(self.home/'.codex'),'OH_CODEX_TURN_ID':''}), patch('oh.branches.fetched',return_value='main'):
            self.assertEqual(materialize(self.root)['status'],'pr')
        self.assertEqual(checkpoint(self.root)['publication']['head'],self.git('rev-parse','HEAD'))

    def delayed_menu_commands(self,superseded):
        """A native command predates the menu click, but reaches OH only after its cleanup finished."""
        for host in ('codex','claude'):
            with self.subTest(delayed_host=host):
                self.staged_conversation(host,'delayed-'+host)
                with patch('oh.cli.host_hook',return_value={'waiting':{'command':'propose'}}) as apply:
                    if superseded:
                        with self.assertRaisesRegex(Refused,'Superseded'):materialize(self.root)
                        apply.assert_not_called()
                    else:
                        materialize(self.root)
                        apply.assert_called_once()

    def test_codex_stop_needs_no_further_run(self):
        self.begin('codex')
        text = self.server(self.root, {'action': 'accept', 'content': {'choice': 'stop'}})[1]
        self.assertIn('nothing left to run', text);self.assertNotIn('`run`', text)
        self.assertEqual(load_run(self.root)[1]['status'], 'stopped')
        self.delayed_menu_commands(superseded=False)

    def test_codex_latest_answer_wins_between_typing_and_the_menu(self):
        from .authority import Saving,desktop_pending,pending_file,stage,supersede,used_file
        from .storage import read_json
        self.begin('codex')
        typed = {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': 't1', 'prompt': 'stop'}
        stage(self.root, 'codex', typed)
        self.assertIn('already typed a choice', self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}})[1])
        pending_file(self.root).unlink()
        def typing():
            path=next((self.home/'.codex/sessions').rglob('*s.jsonl'))
            with path.open('a',newline='\n') as stream:
                for record in ({'type':'event_msg','payload':{'type':'task_started','turn_id':'t2'}},
                               {'type':'event_msg','timestamp':'2020-01-01T00:00:00Z','payload':{'type':'user_message','message':'stop'}}):
                    stream.write(json.dumps(record)+'\n')
            stage(self.root,'codex',typed|{'turn_id':'t2'})
        sent, text = self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}},while_open=typing)
        self.assertIn('Recorded', text)  # typed while the menu was open, so older than the click
        self.assertFalse(pending_file(self.root).exists())
        self.assertEqual(load_run(self.root)[1]['status'], 'running')
        # The click is newer than the still-current UserMessage; no repeated command is needed to continue.
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'s','CODEX_HOME':str(self.home/'.codex')}):
            self.assertEqual(desktop_pending(self.root)['run'],load_run(self.root)[1]['id'])
        # A newer request arriving during menu application stays; a still-saving older one is retained
        # with the menu's cutoff, then retired when its native evidence becomes readable.
        from datetime import datetime,timedelta
        journal,_=load_run(self.root)
        click=[r['data']['source'] for r in journal.records() if r['kind']=='transition'][-1]
        later=(datetime.fromisoformat(click['at'])+timedelta(seconds=1)).isoformat()
        for host in ('codex','claude'):
            saving,path,complete=self.staged_conversation(host,'saving-'+host,partial=True)
            newer,_,_=self.staged_conversation(host,'newer-'+host,at=later)
            supersede(self.root,'codex',click)
            with patch('oh.authority.sleep'),patch('oh.cli.host_hook') as apply:
                with self.assertRaises(Saving):materialize(self.root)
                apply.assert_not_called()
            self.assertFalse(used_file(self.root,human_event(saving,host)).exists())
            self.assertFalse(used_file(self.root,human_event(newer,host)).exists())
            path.write_text(complete,newline='\n')
            with patch('oh.cli.host_hook',return_value={'waiting':{'command':'propose'}}) as apply:
                materialize(self.root)
                self.assertEqual(apply.call_args.kwargs['verified']['prompt'],newer['prompt'])
            self.assertIn('Superseded',read_json(used_file(self.root,human_event(saving,host)))['refused'])

    def test_codex_menu_falls_back_to_typing_when_it_cannot_be_shown(self):
        self.begin('codex')
        for reply, capabilities in (({'action': 'decline'}, None), ({'action': 'cancel'}, None), ({}, {})):
            sent, text = self.server(self.root, reply, capabilities)
            self.assertIn('type one of: continue, pr, stop', text)
            self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        self.assertFalse(any(m.get('method') == 'elicitation/create' for m in sent))  # no capability: never asked

    def test_codex_menu_refuses_a_claude_run_and_a_relative_root(self):
        self.begin('claude')
        self.assertIn('belongs to Claude', self.server(self.root, {})[1])
        self.assertIn('absolute path', self.server(Path('project'), {})[1])

    def test_codex_menu_answers_only_in_the_conversation_that_started_the_run(self):
        self.begin('codex')
        self.assertIn('conversation that started this run', self.server(self.root, {'action': 'accept', 'content': {'choice': 'stop'}}, thread='other')[1])
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')

    def test_no_oh_command_reaches_the_tool_server(self):
        from .cli import main
        for argv in (['mcp-server'], ['--', 'mcp-server'], ['--root', str(self.root), '--', 'mcp-server']):
            with self.subTest(argv), patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):main(argv)

    def test_codex_menu_is_never_shown_to_workers_or_by_a_different_runtime(self):
        self.begin('codex')
        with patch.dict(os.environ, {'OH_CHILD_ATTEMPT': '1'}):
            self.assertIn('workers cannot', self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}})[1])
        with patch('oh.config.version', return_value='another-revision'):
            sent, text = self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}})
        self.assertIn('updated after this run started', text)
        self.assertFalse(any(m.get('method') == 'elicitation/create' for m in sent))
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        from .hosts import command
        config = self.home / 'codex-home/config.toml';config.parent.mkdir(parents=True)
        config.write_text('[plugins."o-harness@o-harness"]\nenabled = true\n[plugins."other@x"]\nenabled = true\n', newline='\n')
        with patch('oh.hosts.executable', return_value='codex'), patch.dict(os.environ, {'CODEX_HOME': str(config.parent)}):
            args = command('codex', {'model': 'm', 'effort': 'low'}, self.root, 'implementation', None, 1000)
        self.assertIn('plugins."o-harness@o-harness".enabled=false', args)
        self.assertFalse(any('other@x' in a for a in args))

    def test_each_host_gets_its_own_menu_mechanism(self):
        from .installation import build
        with tempfile.TemporaryDirectory() as name:
            for host in ('claude', 'codex'):
                plugin = Path(name) / host / 'o-harness';plugin.parent.mkdir()
                build(plugin, host)
                hooks = json.loads((plugin / 'hooks/hooks.json').read_text())['hooks']
                self.assertFalse((plugin / 'codex-mcp.json').exists())
                self.assertEqual((plugin / '.mcp.json').exists(), host == 'codex')
                self.assertEqual('PreToolUse' in hooks and 'PostToolUse' in hooks, host == 'claude')
                manifest = json.loads((plugin / '.codex-plugin/plugin.json').read_text())
                self.assertEqual(manifest.get('mcpServers'), './.mcp.json' if host == 'codex' else None)
                if host == 'codex':  # Codex clears a server's environment: OH's worker marker and data home are passed on
                    server = json.loads((plugin / '.mcp.json').read_text())['mcpServers']['o-harness']
                    self.assertEqual(server['env_vars'][:2], ['OH_CHILD_ATTEMPT', 'OH_DATA_HOME'])
                    self.assertEqual((server['command'], server['args']), ('./scripts/mcp-server', []))  # mcp-server.cmd on Windows
                    self.assertEqual(server['cwd'], '.')  # Codex resolves it from the plugin folder and expands no variables
