from .registry import register, profile_path
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .authority import attest
from .storage import Refused

class AuthorityTest(unittest.TestCase):
    def test_native_transcript_binds_host_turn_text_and_checkout(self):
        with tempfile.TemporaryDirectory() as name, patch('pathlib.Path.home',return_value=Path(name)):
            home=Path(name);root=home/'project';root.mkdir()
            for host in ('codex','claude'):
                path=home/('.codex/sessions' if host=='codex' else '.claude/projects')/'session.jsonl'
                path.parent.mkdir(parents=True)
                payload={'hook_event_name':'UserPromptSubmit','session_id':'session','turn_id':'turn','prompt':'continue','transcript_path':str(path)}
                if host=='codex':
                    records=[{'type':'session_meta','payload':{'id':'session','cwd':str(root),'source':'cli'}},
                      {'type':'event_msg','payload':{'type':'task_started','turn_id':'turn'}},
                      {'type':'response_item','payload':{'role':'user','content':[{'type':'input_text','text':'continue'}]}}]
                else:
                    records=[{'type':'user','sessionId':'session','promptId':'turn','cwd':str(root),'message':{'role':'user','content':'continue'}}]
                def save():path.write_text(''.join(json.dumps(r)+'\n' for r in records))
                save();self.assertEqual(attest(host,payload,root)['turn'],'turn')
                with self.assertRaises(Refused):attest(host,payload|{'prompt':'grant review'},root)
                with self.assertRaises(Refused):attest(host,payload|{'turn_id':'other'},root)
                with self.assertRaises(Refused):attest(host,payload,home/'other-project')
                if host=='codex':records[0]['payload']['source']={'subagent':{}}
                else:records[0]['promptSource']='sdk'
                save()
                with self.assertRaises(Refused):attest(host,payload,root)
                path.write_text('')
                with self.assertRaises(Refused):attest(host,payload,root)

    def test_desktop_fallback_uses_only_current_native_human_turn(self):
        import os
        from .authority import desktop_pending,pending_file
        from .storage import atomic_json,identifier
        import subprocess
        with tempfile.TemporaryDirectory() as name,patch('pathlib.Path.home',return_value=Path(name)),patch.dict(os.environ,{'CODEX_THREAD_ID':'session','OH_DATA_HOME':name+'/state'}):
            home=Path(name);root=home/'project';root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
            register(root,'fixture')
            path=home/'.codex/sessions/session.jsonl';path.parent.mkdir(parents=True)
            records=[{'type':'session_meta','payload':{'id':'session','cwd':str(root),'source':'vscode','originator':'Codex Desktop'}},
              {'type':'event_msg','payload':{'type':'task_started','turn_id':'one'}},
              {'type':'event_msg','payload':{'type':'user_message','message':'$o-harness:oh-propose Describe the next change'}}]
            def save():path.write_text(''.join(json.dumps(x)+'\n' for x in records))
            records[-1]['payload']['message']='$o-harness:oh-deliver implement a new idea'
            save();desktop_pending(root);self.assertFalse(pending_file(root).exists())
            records[-1]['payload']['message']='$o-harness:oh-propose Describe the next change'
            save();desktop_pending(root);self.assertTrue(pending_file(root).exists());pending_file(root).unlink()
            records += [{'type':'event_msg','payload':{'type':'task_started','turn_id':'two'}},{'type':'event_msg','payload':{'type':'user_message','message':'Discuss a different subject'}}]
            save();desktop_pending(root);self.assertFalse(pending_file(root).exists())
            records[0]['payload']['source']='exec';records[-1]['payload']['message']='continue'
            save();desktop_pending(root);self.assertFalse(pending_file(root).exists())

    def test_prepared_scope_cannot_be_widened_after_human_trigger(self):
        import os,subprocess
        from datetime import datetime,timedelta,timezone
        from .prepared import prepare,resolve,directory
        from .storage import atomic_json,identifier,read_json
        from .cli import host_hook
        from .workflow import load_run
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
            root=Path(tmp)/'consumer';root.mkdir()
            for args in [('init','-qb','main'),('config','user.name','Fixture'),('config','user.email','fixture@example.invalid')]:subprocess.run(['git','-C',str(root),*args],check=True)
            register(root,'Fixture')
            (root/'product.txt').write_text('fixture')
            from .test_workflow import configure
            configure(root,checks=[{'name':'check','command':['true']}])
            subprocess.run(['git','-C',str(root),'add','.'],check=True);subprocess.run(['git','-C',str(root),'commit','-qm','base'],check=True)
            tasks={'tasks':[{'id':'1','title':'Fix','instructions':'Fix agreed behavior'}],'checks':[]}
            atomic_json(profile_path(root).parent/'tasks.json',tasks)
            request=prepare(root,str(profile_path(root).parent/'tasks.json'))
            event={'host':'codex','session':'s','turn':'t','prompt':request['trigger'],'at':(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()}
            atomic_json(profile_path(root).parent/'tasks.json',{'tasks':tasks['tasks']+[{'id':'2','title':'Extra','instructions':'Unapproved'}]})
            configure(root,tasks_per_batch=99,review_rounds=99)
            with self.assertRaises(Refused):resolve(root,'request:'+request['request'],event|{'at':'2000-01-01T00:00:00+00:00'},'tasks')
            host_hook(root,'codex',{'prompt':request['trigger']},verified=event)
            _,run=load_run(root);self.assertEqual(len(run['tasks']),1);self.assertEqual(run['config']['tasks_per_batch'],5);self.assertEqual(run['config']['review_rounds'],3)
            prepared=directory(root)/(request['request']+'.json');data=read_json(prepared);data['manifest']['tasks'].append({'id':'2'})
            prepared.write_text(json.dumps(data))
            with self.assertRaises(Refused):resolve(root,'request:'+request['request'],event,'tasks')
