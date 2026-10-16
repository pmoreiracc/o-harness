"""Native questions preserve human provenance without a second OH menu protocol."""
import json
import os
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch
from .authority import native_human
from .storage import Refused


class GateTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.root=self.home/'project';self.root.mkdir()
        home=patch('pathlib.Path.home',return_value=self.home);home.start();self.addCleanup(home.stop)
        env=patch.dict(os.environ,{'CODEX_THREAD_ID':'','CODEX_HOME':str(self.home/'.codex')});env.start();self.addCleanup(env.stop)
        delay=patch('oh.authority.sleep');delay.start();self.addCleanup(delay.stop)
        self.subject=self.home/'approved scope.md';self.subject.write_text('One bounded task.',newline='\n')

    def test_codex_question_reply_belongs_to_the_exact_native_call(self):
        from copy import deepcopy
        path=self.home/'.codex/sessions/s.jsonl';path.parent.mkdir(parents=True)
        question={'title':'Proceed with the scope in '+str(self.subject)+'?',
                  'options':['Proceed with the task','Keep planning']}
        call={'type':'response_item','timestamp':'2026-10-15T12:00:01Z','payload':{
            'type':'function_call','name':'request_user_input_async','call_id':'current',
            'arguments':json.dumps({'questions':[question]})}}
        reply=[{'questionItemId':json.dumps(['request_user_input_async','current',0]),
                'question':question['title'],'answer':'Proceed with the task'}]
        def message(answers):
            text='<send_user_message_question_reply>\n'+json.dumps(answers)+'\n</send_user_message_question_reply>'
            return {'type':'event_msg','timestamp':'2026-10-15T12:00:02Z','payload':{
                'type':'item_completed','thread_id':'s','turn_id':'reply',
                'item':{'type':'UserMessage','id':'human-reply','content':[{'type':'text','text':text}]}}}
        initial={'type':'session_meta','payload':{'id':'s','cwd':str(self.root),'source':'vscode'}}
        locator={'host':'codex','session':'s','tool_use_id':'current','transcript_path':str(path)}
        def read(rows,subject=None):
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows),newline='\n')
            return native_human(self.root,locator,subject=self.subject if subject is None else subject)
        # Submission acknowledgement and a quiet native wait leave the question
        # unanswered. Ending the turn after posting is not a human choice either.
        submitted={'type':'response_item','payload':{'type':'function_call_output',
                   'call_id':'current','output':json.dumps({'accepted':True})}}
        waiting={'type':'response_item','payload':{'type':'function_call','name':'clock.sleep',
                 'call_id':'wait','arguments':json.dumps({'duration_ms':30000})}}
        finished={'type':'event_msg','payload':{'type':'task_complete','last_agent_message':'Select a choice.'}}
        for pending in ([submitted,waiting],[submitted,finished]):
            with self.subTest(pending=pending[-1]['type']),self.assertRaises(Refused):read([initial,call,*pending])
        approved=read([initial,call,submitted,waiting,message(reply)])
        self.assertEqual(approved['prompt'],'Proceed with the task')
        # If the submitted menu is invisible, the same shown question can be
        # answered directly in chat, still bound to its actual artifact context.
        context={'type':'response_item','timestamp':'2026-10-15T12:00:02Z','payload':{
            'type':'message','role':'assistant','content':[{'type':'output_text','text':question['title']+' Reply here if no menu is visible.'}]}}
        typed={'type':'event_msg','timestamp':'2026-10-15T12:00:03Z','payload':{
            'type':'user_message','turn_id':'typed','message':'Keep planning'}}
        path.write_text(''.join(json.dumps(row)+'\n' for row in [initial,call,submitted,context,typed]),newline='\n')
        fallback=native_human(self.root,{'host':'codex','session':'s','turn':'typed','transcript_path':str(path)},subject=self.subject)
        self.assertEqual(fallback['prompt'],'Keep planning')
        self.assertEqual(fallback['question'],context['payload']['content'][0]['text'])
        cancellation={'type':'event_msg','timestamp':'2026-10-15T12:00:03Z','payload':{
            'type':'user_message','turn_id':'cancel','message':'No. Cancel that scope; do not implement it.'}}
        with self.assertRaises(Refused):read([initial,call,message(reply),cancellation])
        self.assertEqual(native_human(self.root,locator,subject=self.subject,latest=False),approved)
        with self.assertRaises(Refused):read([initial,call,cancellation,message(reply)])
        for wrong in ('old','future'):
            answers=deepcopy(reply);answers[0]['questionItemId']=json.dumps(['request_user_input_async',wrong,0])
            with self.subTest(call=wrong),self.assertRaises(Refused):read([initial,call,message(answers)])
        foreign=deepcopy(initial);foreign['payload']['id']='other'
        with self.assertRaises(Refused):read([foreign,call,message(reply)])
        with self.assertRaises(Refused):read([initial,call,{'type':'response_item','payload':{
            'type':'function_call_output','call_id':'current','output':json.dumps(reply)}}])
        with self.assertRaises(Refused):
            path.write_text(''.join(json.dumps(row)+'\n' for row in [initial,call,message(reply)]),newline='\n')
            native_human(self.root,locator,since='2026-10-15T12:00:03Z',subject=self.subject)
        for subject in (self.subject,PureWindowsPath(r'C:\Users\Developer\approved scope.md')):
            with self.subTest(subject=str(subject)):
                requested=deepcopy(question);requested['title']='Proceed with the scope in '+str(subject)+'?'
                selected=deepcopy(reply);selected[0]['question']=requested['title']
                current=deepcopy(call);current['payload']['arguments']=json.dumps({'questions':[requested]})
                self.assertEqual(read([initial,current,message(selected)],subject)['prompt'],'Proceed with the task')
                for hidden_in in ('options','metadata'):
                    hidden=deepcopy(current);generic=deepcopy(requested);generic['title']='Proceed with this task?'
                    if hidden_in=='options':generic['options'][0]+=' '+str(subject)
                    arguments={'questions':[generic]}
                    if hidden_in=='metadata':arguments['artifact']=str(subject)
                    hidden['payload']['arguments']=json.dumps(arguments)
                    with self.subTest(hidden_in=hidden_in),self.assertRaises(Refused):
                        read([initial,hidden,message(selected)],subject)

    def test_claude_question_retains_the_actual_answer_and_rejects_model_or_foreign_text(self):
        from copy import deepcopy
        path=self.home/'.claude/projects/s.jsonl';path.parent.mkdir(parents=True)
        question='Accept the concerns for '+str(self.subject)+'?'
        common={'sessionId':'s','cwd':str(self.root),'timestamp':'2026-10-15T12:00:01Z'}
        rows=[common|{'type':'assistant','message':{'content':[{'type':'tool_use','id':'ask','name':'AskUserQuestion',
                    'input':{'questions':[{'question':question,'options':[{'label':'Accept these concerns'},{'label':'Repair them'}]}]}}]}},
              common|{'type':'user','toolUseResult':{'answers':{question:'Accept these concerns'}},
                      'message':{'content':[{'type':'tool_result','tool_use_id':'ask','content':'The user answered.'}]}}]
        locator={'host':'claude','session':'s','tool_use_id':'ask','transcript_path':str(path)}
        def read(values,subject=None):
            path.write_text(''.join(json.dumps(row)+'\n' for row in values),newline='\n')
            return native_human(self.root,locator,subject=self.subject if subject is None else subject)
        approved=read(rows)
        self.assertEqual(approved['prompt'],'Accept these concerns')
        cancellation=common|{'type':'user','promptId':'cancel','entrypoint':'cli','timestamp':'2026-10-15T12:00:03Z',
                            'message':{'role':'user','content':'No. Cancel that decision; repair the concerns.'}}
        with self.assertRaises(Refused):read(rows+[cancellation])
        self.assertEqual(native_human(self.root,locator,subject=self.subject,latest=False),approved)
        with self.assertRaises(Refused):read([rows[0],cancellation,rows[1]])
        for label in ('model claim','foreign','notification','cancelled'):
            wrong=deepcopy(rows)
            if label=='model claim':wrong[-1].pop('toolUseResult')
            elif label=='foreign':wrong[-1]['sessionId']='other'
            elif label=='notification':wrong[-1]['origin']={'kind':'task-notification'}
            else:wrong[-1]['message']['content'][0]['is_error']=True
            with self.subTest(label=label),self.assertRaises(Refused):read(wrong)
        with self.assertRaises(Refused):
            read(rows)
            native_human(self.root,locator,subject=self.home/'different scope.md')
        for subject in (self.subject,PureWindowsPath(r'C:\Users\Developer\approved scope.md')):
            with self.subTest(subject=str(subject)):
                values=deepcopy(rows);requested='Accept the concerns for '+str(subject)+'?'
                arguments=values[0]['message']['content'][0]['input']
                arguments['questions'][0]['question']=requested
                values[1]['toolUseResult']['answers']={requested:'Accept these concerns'}
                self.assertEqual(read(values,subject)['prompt'],'Accept these concerns')
                for hidden_in in ('options','metadata'):
                    hidden=deepcopy(values);arguments=hidden[0]['message']['content'][0]['input']
                    arguments['questions'][0]['question']='Accept these concerns?'
                    if hidden_in=='options':arguments['questions'][0]['options'][0]['label']+=' '+str(subject)
                    if hidden_in=='metadata':arguments['artifact']=str(subject)
                    hidden[1]['toolUseResult']['answers']={'Accept these concerns?':'Accept these concerns'}
                    with self.subTest(hidden_in=hidden_in),self.assertRaises(Refused):read(hidden,subject)
