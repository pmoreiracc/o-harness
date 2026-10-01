from .registry import register, profile_path
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .authority import Expired, attest
from .storage import Refused

class AuthorityTest(unittest.TestCase):
    def setUp(self):
        context=patch.dict(os.environ,{'CODEX_THREAD_ID':'','CODEX_SESSION_ID':'','OH_CODEX_TURN_ID':''})
        context.start();self.addCleanup(context.stop)
        # Evidence-delay tests advance the saved transcript, not the wall clock.
        delay=patch('oh.authority.sleep');delay.start();self.addCleanup(delay.stop)

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
                      {'type':'event_msg','payload':{'type':'user_message','message':'continue'}}]
                else:
                    records=[{'type':'user','sessionId':'session','promptId':'turn','cwd':str(root),'message':{'role':'user','content':'continue'}}]
                def save(*extra):path.write_text(''.join(json.dumps(r)+'\n' for r in records+list(extra)),newline='\n')
                save();self.assertEqual(attest(host,payload,root)['turn'],'turn')
                # A notification in its own turn changes nothing; once the person types something newer, this turn
                # is no longer what they asked for.
                if host=='claude':
                    note={'type':'user','sessionId':'session','promptId':'later','cwd':str(root),'origin':{'kind':'task-notification'},'message':{'role':'user','content':'done'}}
                    save(note);self.assertEqual(attest(host,payload,root)['turn'],'turn')
                    save(note,{'type':'user','sessionId':'session','promptId':'later','cwd':str(root),'message':{'role':'user','content':'never mind'}})
                else:  # Codex may add user-role items of its own; only what the person typed moves it on
                    later={'type':'event_msg','payload':{'type':'task_started','turn_id':'later'}}
                    save(later,{'type':'response_item','payload':{'role':'user','content':[{'type':'input_text','text':'<environment_context>'}]}})
                    self.assertEqual(attest(host,payload,root)['turn'],'turn')
                    # Current Desktop records can arrive within the same turn as a previous message.
                    for next_turn in ('later','turn'):
                        save({'type':'event_msg','payload':{'type':'item_completed','turn_id':next_turn,
                            'item':{'type':'UserMessage','id':'new-message','content':[{'type':'text','text':'never mind'}]}}})
                        with self.assertRaises(Expired):attest(host,payload,root)
                    save(later,{'type':'event_msg','payload':{'type':'user_message','message':'never mind'}})
                with self.assertRaises(Expired):attest(host,payload,root)
                save()
                if host=='claude':  # the desktop app saves a typed turn as from a person, with its SDK marker
                    records[0]|={'origin':{'kind':'human'},'turnOrigin':'human','promptSource':'sdk','entrypoint':'claude-desktop'}
                    save();self.assertEqual(attest(host,payload,root)['turn'],'turn')
                    records[0]['origin']={'kind':'peer'}  # another agent's message is never the person's
                    save()
                    with self.assertRaises(Refused):attest(host,payload,root)
                    for key in ('origin','turnOrigin','promptSource','entrypoint'):del records[0][key]
                    save()
                with self.assertRaises(Refused):attest(host,payload|{'prompt':'grant review'},root)
                with self.assertRaises(Refused):attest(host,payload|{'turn_id':'other'},root)
                with self.assertRaises(Refused):attest(host,payload,home/'other-project')
                if host=='codex':records[0]['payload']['source']={'subagent':{}}
                else:records[0]['promptSource']='sdk'
                save()
                with self.assertRaises(Refused):attest(host,payload,root)
                path.write_text('')
                with patch('oh.authority.sleep') as pause:
                    with self.assertRaises(Refused):attest(host,payload,root)
                    self.assertEqual(pause.call_count,4)
                # A host still saving its evidence is recovered internally on either host.
                records[0] = ({'type':'session_meta','payload':{'id':'session','cwd':str(root),'source':'cli'}} if host=='codex'
                    else {'type':'user','sessionId':'session','promptId':'turn','cwd':str(root),'message':{'role':'user','content':'continue'}})
                with patch('oh.authority.sleep',side_effect=lambda _:save()) as pause:
                    self.assertEqual(attest(host,payload,root)['turn'],'turn')
                    pause.assert_called_once()
                # docs/usage.md: saving may append the new turn after older complete history, not just to an empty file.
                for older_turn in (('older','turn') if host=='codex' else ('older',)):
                    older=([records[0],{'type':'event_msg','payload':{'type':'task_started','turn_id':older_turn}},
                            {'type':'event_msg','payload':{'type':'user_message','message':'Earlier request'}}] if host=='codex' else
                           [{'type':'user','sessionId':'session','promptId':older_turn,'cwd':str(root),'message':{'role':'user','content':'Earlier request'}}])
                    current=([{'type':'event_msg','payload':{'type':'item_completed','turn_id':'turn',
                        'item':{'type':'UserMessage','id':'current','content':[{'type':'text','text':'continue'}]}}}] if host=='codex' else records)
                    complete=''.join(json.dumps(r)+'\n' for r in older+current)
                    path.write_text(complete[:-8],newline='\n')  # the current record is still being appended
                    with patch('oh.authority.sleep',side_effect=lambda _:path.write_text(complete,newline='\n')) as pause:
                        self.assertEqual(attest(host,payload,root)['turn'],'turn')
                        pause.assert_called_once()
                    # Do not apply the earlier command while a later message is only partly visible.
                    path.write_text(complete[:-8],newline='\n')
                    with patch('oh.authority.sleep',side_effect=lambda _:path.write_text(complete,newline='\n')) as pause:
                        with self.assertRaises(Expired):attest(host,payload|{'turn_id':older_turn,'prompt':'Earlier request'},root)
                        pause.assert_called_once()
                with patch('oh.authority.sleep') as pause,self.assertRaises(Refused):
                    attest(host,payload|{'prompt':'A different request'},root)
                pause.assert_not_called()  # a fully saved mismatch is not a timing failure
                if host=='codex':
                    for turn in ('','current'):
                        with patch.dict(os.environ,{'CODEX_THREAD_ID':'another-session','OH_CODEX_TURN_ID':turn}),self.assertRaisesRegex(Refused,'another conversation'):
                            attest(host,payload,root)
                    # Injected user-role items alone are never a native human grant.
                    records[-1]={'type':'response_item','payload':{'role':'user','content':[{'type':'input_text','text':'continue'}]}}
                    save()
                    with patch('oh.authority.sleep'),self.assertRaises(Refused):attest(host,payload,root)

    def test_claude_slash_command_is_read_from_the_tags_claude_saves(self):
        with tempfile.TemporaryDirectory() as name, patch('pathlib.Path.home',return_value=Path(name)):
            home=Path(name);root=home/'project';root.mkdir()
            path=home/'.claude/projects/session.jsonl';path.parent.mkdir(parents=True)
            payload={'hook_event_name':'UserPromptSubmit','session_id':'session','turn_id':'turn','transcript_path':str(path),
                     'prompt':'/o-harness:oh-propose  Add a <confirm> tool\nfor Codex'}
            def save(content,skill='oh-propose',**expansion):
                typed={'type':'user','sessionId':'session','promptId':'turn','cwd':str(root),'uuid':'u1',
                    'origin':{'kind':'human'},'turnOrigin':'human','message':{'role':'user','content':content}}
                expanded={'type':'user','sessionId':'session','promptId':'turn','cwd':str(root),'isMeta':True,'parentUuid':'u1'}|expansion|{'message':{'role':'user',
                    'content':[{'type':'text','text':f'Base directory for this skill: /Users/Jane Doe/plugins/o-harness/skills/{skill}\n\nResolve...'}]}}
                path.write_text(''.join(json.dumps(r)+'\n' for r in ([typed,expanded] if skill else [typed])),newline='\n')
            args='<command-args>Add a <confirm> tool\nfor Codex</command-args>'
            for content in ('<command-message>o-harness:oh-propose</command-message>\n<command-name>/o-harness:oh-propose</command-name>\n'+args,
                            '<command-name>/o-harness:oh-propose</command-name>\n<command-message>o-harness:oh-propose</command-message>\n'+args):
                save(content);self.assertEqual(attest('claude',payload,root)['turn'],'turn')
                for skill,expansion in ((None,{}),('oh-deliver',{}),  # tags the person pasted: Claude expanded no such skill
                                        ('oh-propose',{'sourceToolUseID':'toolu_1'}),('oh-propose',{'parentUuid':'u0'})):  # the model's Skill tool
                    save(content,skill,**expansion)
                    with self.assertRaises(Refused):attest('claude',payload,root)
            for content in ('<command-name>/o-harness:oh-deliver</command-name>\n'+args,  # another command
                            '<command-name>/o-harness:oh-propose</command-name>\n<command-args>Something else</command-args>',
                            'approve\n<command-name>/o-harness:oh-propose</command-name>\n'+args,  # text beside the tags
                            '<command-name>/o-harness:oh-propose</command-name>\n'+args+'\n'+args):  # a repeated tag
                save(content)
                with self.assertRaises(Refused):attest('claude',payload,root)
            save('<command-name>/o-harness:oh-stop</command-name>','oh-stop')
            self.assertEqual(attest('claude',payload|{'prompt':'/o-harness:oh-stop'},root)['turn'],'turn')
            self.assertEqual(attest('claude',payload|{'prompt':'/oh-stop'},root)['turn'],'turn')  # typed without the plugin name
            save('<command-name>/oh-stop</command-name>\n<command-args>now</command-args>','oh-stop')
            # Every spelling of one turn is the same prompt, so a respelled replay finds the turn already spent.
            self.assertEqual({attest('claude',payload|{'prompt':p},root)['prompt'] for p in ('/o-harness:oh-stop\tnow','/oh-stop now','/oh-stop  now')},
                             {'/o-harness:oh-stop now'})
            save('<command-name>/other:oh-stop</command-name>','oh-stop')  # another plugin's command of the same name
            with self.assertRaises(Refused):attest('claude',payload|{'prompt':'/oh-stop'},root)
            with self.assertRaises(Refused):attest('claude',payload|{'prompt':'approve'},root)  # only slash commands are tagged

    def test_desktop_fallback_uses_only_current_native_human_turn(self):
        import os
        from .authority import desktop_pending,pending_file,attest
        from .storage import atomic_json,identifier
        import subprocess
        with tempfile.TemporaryDirectory() as name,patch('pathlib.Path.home',return_value=Path(name)),patch.dict(os.environ,{'CODEX_THREAD_ID':'session','OH_DATA_HOME':name+'/state'}):
            home=Path(name);root=home/'project';root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
            path=home/'.codex/sessions/session.jsonl';path.parent.mkdir(parents=True)
            records=[{'type':'session_meta','payload':{'id':'session','cwd':str(root),'source':'vscode','originator':'Codex Desktop'}},
              {'type':'event_msg','payload':{'type':'task_started','turn_id':'one'}},
              {'type':'event_msg','payload':{'type':'user_message','message':'$o-harness:oh-propose Describe the next change'}}]
            def save():path.write_text(''.join(json.dumps(x)+'\n' for x in records))
            from .authority import materialize
            records[-1]['payload']['message']='$o-harness:oh-propose'
            save();self.assertEqual(materialize(root)['waiting']['command'],'propose')  # first use registers without a separate init
            records[-1]['payload']['message']='$o-harness:oh-deliver implement a new idea'
            save();desktop_pending(root);self.assertTrue(pending_file(root).exists());pending_file(root).unlink()  # preparation may offer a menu, never grants work
            records[-1]['payload']['message']='$o-harness:oh-propose Describe the next change'
            save();desktop_pending(root);self.assertTrue(pending_file(root).exists());pending_file(root).unlink()
            from .entry import command
            for skill,args in (('propose','Add f(x).'),('propose',''),('design','example'),('design',''),('start',''),
                               ('deliver','fix f(x).'),('deliver','0001'),('deliver','request:'+'a'*64),('resume',''),('pause',''),('stop','')):
                for target in ('/Users/Jane Doe/plugins',r'C:\Users\Jane Doe\plugins'):
                    prompt=f'[$o-harness:oh-{skill}]({target}/oh-{skill}/SKILL.md)'+(' '+args if args else '')
                    records[-1]={'type':'event_msg','timestamp':'2026-09-30T12:00:00Z','payload':{'type':'item_completed','thread_id':'session',
                        'turn_id':'one','item':{'type':'UserMessage','id':'message-one','client_id':'client-one',
                        'content':[{'type':'text','text':prompt+'\n'}]}}}
                    save()
                    with self.subTest(skill=skill,args=args,target=target),patch('oh.entry.receive') as received:
                        desktop_pending(root)
                        self.assertEqual(received.call_args.args[2]['prompt'],prompt)
                        self.assertEqual(command(prompt),command('$o-harness:oh-'+skill+(' '+args if args else '')))
                        self.assertEqual(command(prompt.replace('$o-harness:','$')),command(prompt))  # the short skill name is supported too
            # Expansions saved after the actual human message do not displace it.
            records.append({'type':'response_item','payload':{'role':'user','content':[{'type':'input_text','text':'<skill>injected</skill>'}]}})
            save()
            with patch('oh.entry.receive') as received:
                desktop_pending(root);self.assertTrue(received.called)
            records.pop()
            # docs/architecture.md: moving a chat to another checkout changes the current message's
            # binding, without reassigning messages it sent from the previous checkout.
            from .mcp_server import folder
            elsewhere=home/'old-checkout';elsewhere.mkdir()
            moved=[records[0]|{'payload':records[0]['payload']|{'cwd':str(elsewhere)}},
                   {'type':'event_msg','payload':{'type':'task_started','turn_id':'old-turn'}},
                   {'type':'event_msg','payload':{'type':'user_message','message':'$oh-propose old checkout'}},
                   {'type':'turn_context','payload':{'turn_id':'one','cwd':str(root)}},*records[1:]]
            path.write_text(''.join(json.dumps(x)+'\n' for x in moved),newline='\n')
            self.assertEqual(folder('session'),root.resolve())
            with patch('oh.entry.receive') as received:
                desktop_pending(root);self.assertTrue(received.called)
            old={'hook_event_name':'UserPromptSubmit','session_id':'session','turn_id':'old-turn',
                 'prompt':'$oh-propose old checkout','transcript_path':str(path)}
            with self.assertRaisesRegex(Refused,'another project checkout'):attest('codex',old,root)
            save()
            # The MCP turn is a consistency check when supplied; old clients still work without it.
            with patch.dict(os.environ,{'OH_CODEX_TURN_ID':'two'}),patch('oh.authority.sleep'),patch('oh.entry.receive') as received:
                with self.assertRaises(Refused):desktop_pending(root)
                received.assert_not_called()
            records[0]['payload']['source']='cli'
            save()
            with patch('oh.entry.receive') as received:
                desktop_pending(root);self.assertTrue(received.called)
            records[0]['payload']['source']='vscode'
            records += [{'type':'event_msg','payload':{'type':'task_started','turn_id':'two'}},{'type':'event_msg','payload':{'type':'user_message','message':'Discuss a different subject'}}]
            save();desktop_pending(root);self.assertFalse(pending_file(root).exists())
            # While OH waits for this conversation's answer (a bare $oh-propose), a plain message typed after the
            # question is the answer; one typed before it is not.
            from .authority import wait_for
            from .storage import now,read_json
            wait_for(root,{'host':'codex','session':'session'},'propose',"What's the idea?")
            desktop_pending(root);self.assertFalse(pending_file(root).exists())
            records += [{'type':'event_msg','payload':{'type':'task_started','turn_id':'three'}},
                        {'type':'event_msg','timestamp':now(),'payload':{'type':'user_message','message':'Search my notes'}}]
            save();desktop_pending(root);self.assertEqual(read_json(pending_file(root))['idea'],'propose');pending_file(root).unlink()
            records[0]['payload']['source']='exec';records[-1]['payload']['message']='continue'
            save();desktop_pending(root);self.assertFalse(pending_file(root).exists())
            # docs/usage.md: a delayed hook or invented locator cannot spend the actual latest command.
            # Staging happens before the transcript is saved; only materialization may choose between them.
            from .authority import Saving,stage,used_file
            from .workflow import human_event
            for host in ('codex','claude'):
                for delayed in ('old','invented','late','replay'):
                    session=f'queued-{host}-{delayed}'
                    transcript=home/('.codex/sessions' if host=='codex' else '.claude/projects')/(session+'.jsonl')
                    transcript.parent.mkdir(parents=True,exist_ok=True)
                    proof=[{'type':'session_meta','payload':{'id':session,'cwd':str(root),'source':'cli'}}] if host=='codex' else []
                    locators={}
                    for turn,at in (('old','2026-09-30T12:00:00Z'),('new','2026-09-30T12:01:00Z')):
                        prompt=('$' if host=='codex' else '/')+'oh-propose '+turn
                        locators[turn]={'hook_event_name':'UserPromptSubmit','session_id':session,'turn_id':turn,
                            'prompt':prompt,'transcript_path':str(transcript)}
                        proof.append(({'type':'event_msg','timestamp':at,'payload':{'type':'user_message','turn_id':turn,'message':prompt}}
                            if host=='codex' else {'type':'user','timestamp':at,'sessionId':session,'promptId':turn,
                                'cwd':str(root),'message':{'role':'user','content':prompt}}))
                    if delayed in ('old','late','replay'):
                        # Separate conversations: the older evidence is complete while the newer one is saving.
                        other_session=session+'-other';other_path=transcript.with_name(other_session+'.jsonl')
                        older=([proof[0]|{'payload':proof[0]['payload']|{'id':other_session}},proof[1]] if host=='codex'
                            else [proof[0]|{'sessionId':other_session}])
                        other_path.write_text(''.join(json.dumps(x)+'\n' for x in older),newline='\n')
                        locators['old']|={'session_id':other_session,'transcript_path':str(other_path)}
                    transcript.write_text('')
                    stage(root,host,locators['new'])
                    if delayed in ('old','invented'):
                        stage(root,host,locators['old'] if delayed=='old' else locators['new']|{'prompt':'/oh-propose fabricated'})
                    event=human_event(locators['new'],host)
                    self.assertFalse(used_file(root,event).exists())
                    complete=''.join(json.dumps(x)+'\n' for x in proof)
                    transcript.write_text(complete[:-8],newline='\n')
                    if delayed=='old':
                        with patch.dict(os.environ,{'CODEX_THREAD_ID':'','CODEX_SESSION_ID':''}),patch('oh.authority.sleep') as pause,\
                                patch('oh.cli.host_hook') as apply:
                            with self.assertRaises(Saving):materialize(root)
                            apply.assert_not_called();self.assertEqual(pause.call_count,4)
                        self.assertEqual(len(read_json(pending_file(root))['prior']),1)
                        self.assertFalse(used_file(root,event).exists())
                        self.assertFalse(used_file(root,human_event(locators['old'],host)).exists())
                    def finish(_):
                        self.assertFalse(used_file(root,event).exists())
                        self.assertTrue(pending_file(root).exists())
                        transcript.write_text(complete,newline='\n')
                    with patch.dict(os.environ,{'CODEX_THREAD_ID':'','CODEX_SESSION_ID':''}),patch('oh.authority.sleep',side_effect=finish),\
                            patch('oh.cli.host_hook',return_value={'waiting':{'command':'propose'}}):
                        self.assertEqual(materialize(root)['waiting']['command'],'propose')
                    self.assertIn('result',read_json(used_file(root,event)))
                    if delayed in ('late','replay'):
                        older_event=human_event(locators['old'],host)
                        self.assertFalse(used_file(root,older_event).exists())
                        if delayed=='replay':
                            stage(root,host,locators['new']);stage(root,host,locators['old'])
                            with patch.dict(os.environ,{'CODEX_THREAD_ID':'','CODEX_SESSION_ID':''}),patch('oh.cli.host_hook') as apply:
                                self.assertEqual(materialize(root)['waiting']['command'],'propose')
                                apply.assert_not_called()
                            self.assertIn('Superseded',read_json(used_file(root,older_event))['refused'])
                        # A delayed old hook cannot become fresh work after the newer request finished.
                        stage(root,host,locators['old'])
                        with patch.dict(os.environ,{'CODEX_THREAD_ID':'','CODEX_SESSION_ID':''}),patch('oh.cli.host_hook') as apply:
                            with self.assertRaisesRegex(Refused,'Superseded'):materialize(root)
                            apply.assert_not_called()
                        self.assertIn('Superseded',read_json(used_file(root,older_event))['refused'])
                    stage(root,host,locators['new']);stage(root,host,locators['old'])
                    cancelled=({'type':'event_msg','payload':{'type':'user_message','turn_id':'cancel','message':'never mind'}}
                        if host=='codex' else {'type':'user','sessionId':session,'promptId':'cancel','cwd':str(root),
                            'message':{'role':'user','content':'never mind'}})
                    transcript.write_text(complete+json.dumps(cancelled)+'\n',newline='\n')
                    with patch.dict(os.environ,{'CODEX_THREAD_ID':'','CODEX_SESSION_ID':''}),self.assertRaises(Refused):
                        materialize(root)
                    self.assertFalse(pending_file(root).exists())

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
