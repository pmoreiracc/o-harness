"""Native questions preserve human provenance without a second OH menu protocol."""
import json
import os
from pathlib import Path
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
        def read(rows):
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows),newline='\n')
            return native_human(self.root,locator,subject=self.subject)
        self.assertEqual(read([initial,call,message(reply)])['prompt'],'Proceed with the task')
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
        def read(values):
            path.write_text(''.join(json.dumps(row)+'\n' for row in values),newline='\n')
            return native_human(self.root,locator,subject=self.subject)
        self.assertEqual(read(rows)['prompt'],'Accept these concerns')
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
