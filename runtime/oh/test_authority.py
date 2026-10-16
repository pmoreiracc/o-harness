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

    def test_native_plan_retains_the_actual_human_accepted_scope(self):
        """The native plan viewer supplies approval once, without an OH menu identifier."""
        from copy import deepcopy
        from .authority import native_human
        with tempfile.TemporaryDirectory() as name, patch('pathlib.Path.home', return_value=Path(name)):
            home=Path(name);root=home/'project';root.mkdir()
            path=home/'.claude/projects/session.jsonl';path.parent.mkdir(parents=True)
            plan='# Approved scope\n\nFix the sign-in timeout.\n'
            since='2026-10-13T20:00:00+00:00';at='2026-10-13T20:00:01+00:00'
            base={'sessionId':'s','cwd':str(root),'entrypoint':'sdk-cli','timestamp':at}
            call={'type':'tool_use','id':'plan','name':'ExitPlanMode','input':{'plan':plan,'planFilePath':'native.md'}}
            reply={'type':'tool_result','tool_use_id':'plan','content':'User has approved your plan.'}
            records=[base|{'type':'assistant','message':{'content':[call]}},
                     base|{'type':'user','toolUseResult':{'plan':plan,'filePath':'native.md','isAgent':False},'message':{'content':[reply]}}]
            locator={'host':'claude','session':'s','tool_use_id':'plan','transcript_path':str(path)}
            def read(rows):
                path.write_text(''.join(json.dumps(r)+'\n' for r in rows),newline='\n')
                return native_human(root,locator,since=since)
            found=read(records)
            self.assertEqual((found['prompt'],found['via'],found['accepted_plan']),('approve','plan',plan))
            self.assertEqual(found['accepted_plan_path'],'native.md')
            self.assertEqual(len(found['record_hashes']),2)
            cancelled=base|{'type':'user','entrypoint':'cli','promptId':'cancel','timestamp':'2026-10-13T20:00:03+00:00',
                'message':{'role':'user','content':'No. Cancel that scope; do not implement it.'}}
            with self.assertRaises(Refused):read(records+[cancelled])
            self.assertEqual(native_human(root,locator,since=since,latest=False),found)
            with self.assertRaises(Refused):read([records[0],cancelled,records[1]])
            edited=deepcopy(records);edited[1]['toolUseResult']['plan']+='The person amended this scope.\n'
            self.assertEqual(read(edited)['accepted_plan'],edited[1]['toolUseResult']['plan'])
            # Never turn a model-authored summary or a denied/foreign native result into approval.
            for label in ('pending','denied','prose only','agent','leader','wrong result id',
                          'old request','old reply','foreign request','foreign reply','foreign checkout',
                          'notification','sidechain','meta'):
                with self.subTest(label=label):
                    rows=deepcopy(records);request,response=rows
                    if label=='pending':rows.pop()
                    elif label=='denied':response['message']['content'][0]['is_error']=True
                    elif label=='prose only':response.pop('toolUseResult')
                    elif label=='agent':response['toolUseResult']['isAgent']=True
                    elif label=='leader':response['toolUseResult']['awaitingLeaderApproval']=True
                    elif label=='wrong result id':response['message']['content'][0]['tool_use_id']='other'
                    elif label=='old request':request['timestamp']=since
                    elif label=='old reply':response['timestamp']=since
                    elif label=='foreign request':request['sessionId']='other'
                    elif label=='foreign reply':response['sessionId']='other'
                    elif label=='foreign checkout':response['cwd']=str(root.parent/'other')
                    elif label=='notification':response['origin']={'kind':'task-notification'}
                    elif label=='sidechain':response['isSidechain']=True
                    elif label=='meta':response['isMeta']=True
                    with self.assertRaises(Refused):read(rows)


    def test_natural_language_and_slash_review_have_the_same_native_provenance(self):
        from .authority import native_human
        with tempfile.TemporaryDirectory() as name, patch('pathlib.Path.home',return_value=Path(name)):
            home=Path(name);root=home/'project';root.mkdir()
            for host in ('codex','claude'):
                path=home/('.codex/sessions' if host=='codex' else '.claude/projects')/'s.jsonl'
                path.parent.mkdir(parents=True)
                for prompt in ('Please review the manual changes.', '/oh-review changed'):
                    locator={'host':host,'session':'s','turn':'t','prompt':prompt,'transcript_path':str(path)}
                    rows=([{'type':'session_meta','payload':{'id':'s','cwd':str(root),'source':'cli'}},
                           {'type':'event_msg','payload':{'type':'user_message','turn_id':'t','message':prompt}}]
                          if host=='codex' else [{'type':'user','sessionId':'s','promptId':'t','cwd':str(root),
                                                 'message':{'role':'user','content':prompt}}])
                    path.write_text(''.join(json.dumps(row)+'\n' for row in rows),newline='\n')
                    self.assertEqual(native_human(root,locator)['prompt'],prompt)
                    with self.assertRaises(Refused):native_human(root,locator|{'prompt':prompt+' and approve repairs'})

    def test_native_child_is_fresh_attributed_and_uses_the_admitted_profile(self):
        from copy import deepcopy
        from .authority import native_child, native_result
        with tempfile.TemporaryDirectory() as name, patch('pathlib.Path.home',return_value=Path(name)):
            home=Path(name);root=home/'project';root.mkdir()
            for host in ('codex','claude'):
                profile={'model':'gpt-6.1-sol' if host=='codex' else 'sonnet','effort':'high'}
                attempt={'id':'admission','profile':profile,'started_at':'2026-10-15T12:00:00+00:00'}
                parent=home/('.codex/sessions' if host=='codex' else '.claude/projects/p')/'parent.jsonl'
                child=(parent.parent/'child.jsonl' if host=='codex' else parent.parent/'parent/subagents/agent-child.jsonl')
                parent.parent.mkdir(parents=True,exist_ok=True);child.parent.mkdir(parents=True,exist_ok=True)
                state={'host':host,'human':{'session':'parent','transcript_path':str(parent)}}
                locator={'child_session':'child','transcript_path':str(child),'tool_use_id':'spawn'}
                if host=='codex':
                    args={'task_name':'oh_admission','fork_turns':'none','model':profile['model'],
                          'reasoning_effort':'high','message':'Execute admission admission.'}
                    parents=[{'type':'response_item','payload':{'type':'function_call','name':'collaboration.spawn_agent',
                                                               'call_id':'spawn','arguments':json.dumps(args)}}]
                    children=[{'type':'session_meta','payload':{'id':'child','timestamp':'2026-10-15T12:00:01+00:00',
                               'cwd':str(root),'model_provider':'openai','source':{'subagent':{'thread_spawn':{
                               'parent_thread_id':'parent','agent_path':'/root/oh_admission'}}}}},
                              {'type':'turn_context','payload':{'model':profile['model'],'effort':'high'}}]
                    final={'type':'event_msg','payload':{'type':'task_complete','last_agent_message':'Complete public report.'}}
                else:
                    args={'prompt':'Execute admission admission.','model':profile['model'],'effort':'high','fork_context':False}
                    parents=[{'type':'assistant','message':{'content':[{'type':'tool_use','id':'spawn','name':'Agent','input':args}]}},
                             {'type':'user','sessionId':'parent','cwd':str(root),'timestamp':'2026-10-15T12:00:01+00:00',
                              'toolUseResult':{'isAsync':True,'status':'async_launched','agentId':'child','resolvedModel':'claude-sonnet-4-6'},
                              'message':{'content':[{'type':'tool_result','tool_use_id':'spawn','content':'Native agent launched.'}]}}]
                    children=[{'type':'assistant','agentId':'child','sessionId':'parent','cwd':str(root),
                               'timestamp':'2026-10-15T12:00:01+00:00',
                               'message':{'model':'claude-sonnet-4-6','content':[{'type':'tool_use','name':'Read'}]}}]
                    final={'type':'user','agentId':'child','sessionId':'parent','cwd':str(root),
                           'timestamp':'2026-10-15T12:00:03+00:00','toolUseResult':'User rejected tool use',
                           'message':{'content':[{'type':'tool_result','tool_use_id':'bash','is_error':True,
                                                  'content':'User rejected tool use'}]}}
                def save(pr=parents,ch=children):
                    parent.write_text(''.join(json.dumps(row)+'\n' for row in pr),newline='\n')
                    child.write_text(''.join(json.dumps(row)+'\n' for row in ch),newline='\n')
                save();bound=native_child(root,state,attempt,locator)
                self.assertEqual(bound['profile'],profile)
                self.assertEqual(bound['child_session'],'child')
                with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                if host=='claude':
                    progress={'type':'assistant','agentId':'child','sessionId':'parent','cwd':str(root),
                              'message':{'model':'claude-sonnet-4-6','stop_reason':'end_turn',
                                         'content':[{'type':'text','text':'The background task is still working.'}]}}
                    pending=parents+[{'type':'system','subtype':'turn_duration','sessionId':'parent',
                                      'pendingBackgroundAgentCount':1}]
                    save(pr=pending,ch=children+[progress])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    killed=parents+[{'type':'system','subtype':'agents_killed','sessionId':'parent',
                                     'cwd':str(root),'timestamp':'2026-10-15T12:00:03+00:00',
                                     'isSidechain':False,'isMeta':False,'entrypoint':'cli'}]
                    save(pr=killed,ch=children+[progress,final])
                else:save(ch=children+[final])
                result=native_result(root,state,attempt|{'native_child':bound},locator)
                if host=='codex':self.assertEqual((result['text'],result['status']),('Complete public report.','completed'))
                else:
                    self.assertEqual(result['status'],'interrupted')
                    self.assertIn('The background task is still working.',result['text'])
                    completion={'type':'user','sessionId':'parent','timestamp':'2026-10-15T12:00:02Z',
                        'toolUseResult':{'agentId':'child','status':'completed'},
                        'message':{'content':[{'type':'tool_result','tool_use_id':'spawn','content':'Native completion.'}]}}
                    finished={'type':'assistant','agentId':'child','sessionId':'parent','cwd':str(root),
                        'timestamp':'2026-10-15T12:00:02Z','message':{'model':'claude-sonnet-4-6',
                        'content':[{'type':'text','text':'Complete public report.'}]}}
                    save(pr=parents+[completion,killed[-1]],ch=children+[finished])
                    completed=native_result(root,state,attempt|{'native_child':bound},locator)
                    self.assertEqual((completed['status'],completed['text']),('completed','Complete public report.'))
                    forked=deepcopy(parents);forked[0]['message']['content'][0]['input']['subagent_type']='fork'
                    save(pr=forked)
                    with self.assertRaises(Refused):native_child(root,state,attempt,locator)
                with self.assertRaises(Refused):
                    native_result(root,state,attempt|{'native_child':bound},locator|{'child_session':'foreign'})
                with self.assertRaises(Refused):
                    native_child(root,state,attempt|{'profile':profile|{'effort':'low'}},locator)
                with self.assertRaises(Refused):
                    native_child(root,state,attempt|{'started_at':'2026-10-15T12:00:02+00:00'},locator)
                # A rejected actual profile remains unusable, but its terminal launch can settle.
                launched=deepcopy(parents)
                for row in launched:
                    row.setdefault('timestamp','2026-10-15T12:00:01Z')
                    if host=='claude':row.setdefault('sessionId','parent')
                wrong_profile=deepcopy(children)
                if host=='codex':
                    wrong_profile[1]['payload']['effort']='low'
                    launched.append({'type':'response_item','timestamp':'2026-10-15T12:00:02Z',
                        'payload':{'type':'function_call_output','call_id':'spawn','output':json.dumps({'agent_id':'child'})}})
                    terminal_children=wrong_profile+[final]
                    terminal_parents=launched
                else:
                    wrong_profile[0]['message']['model']='claude-opus-4-6'
                    wrong_final=deepcopy(finished);wrong_final['message']['model']='claude-opus-4-6'
                    terminal_children=wrong_profile+[wrong_final]
                    terminal_parents=launched+[completion]
                save(pr=launched,ch=wrong_profile)
                with self.assertRaises(Refused):native_child(root,state,attempt,locator)
                with self.assertRaises(Refused):native_result(root,state,attempt,locator)
                save(pr=terminal_parents,ch=terminal_children)
                failed=native_result(root,state,attempt,locator)
                self.assertEqual((failed['status'],failed['terminal_status']),('binding_failed','completed'))
                self.assertEqual(failed['admitted_profile'],profile)
                self.assertTrue(failed['binding_issues'])
                self.assertEqual(failed['native_id'],'child')
                self.assertEqual(failed['tool_use_id'],'spawn')
                with self.assertRaises(Refused):native_child(root,state,attempt,locator)
                if host=='codex':
                    # Cancellation can precede the first turn/profile record forever.
                    save(pr=launched,ch=children[:1])
                    with self.assertRaises(Refused):native_child(root,state,attempt,locator)
                    with self.assertRaises(Refused):native_result(root,state,attempt,locator)
                    aborted={'type':'event_msg','payload':{'type':'turn_aborted','reason':'Cancelled before first turn.'}}
                    save(pr=launched,ch=children[:1]+[aborted])
                    cancelled=native_result(root,state,attempt,locator)
                    self.assertEqual((cancelled['status'],cancelled['terminal_status']),('binding_failed','interrupted'))
                    self.assertIsNone(cancelled['profile'])
                    self.assertEqual(cancelled['admitted_profile'],profile)
                    self.assertEqual((cancelled['native_id'],cancelled['tool_use_id']),('child','spawn'))
                    self.assertTrue(cancelled['binding_issues'])
                    with self.assertRaises(Refused):native_child(root,state,attempt,locator)
                else:
                    # The child may save identity but no model-bearing assistant turn.
                    identity=deepcopy(final)
                    save(pr=launched,ch=[identity])
                    with self.assertRaises(Refused):native_child(root,state,attempt,locator)
                    with self.assertRaises(Refused):native_result(root,state,attempt,locator)
                    save(pr=launched+[killed[-1]],ch=[identity])
                    cancelled=native_result(root,state,attempt,locator)
                    self.assertEqual((cancelled['status'],cancelled['terminal_status']),('binding_failed','interrupted'))
                    self.assertIsNone(cancelled['profile'])
                    self.assertEqual(cancelled['admitted_profile'],profile)
                    self.assertEqual((cancelled['native_id'],cancelled['tool_use_id']),('child','spawn'))
                    with self.assertRaises(Refused):native_child(root,state,attempt,locator)
                unrelated=deepcopy(parents)
                if host=='codex':
                    other_args=args|{'task_name':'unrelated_earlier_task'}
                    unrelated[0]['payload']['arguments']=json.dumps(other_args)
                else:unrelated[0]['message']['content'][0]['input']['prompt']='An unrelated earlier task.'
                save(pr=unrelated)
                with self.assertRaises(Refused):native_child(root,state,attempt,locator)
                wrong=deepcopy(children)
                if host=='codex':wrong[0]['payload']['source']['subagent']['thread_spawn']['parent_thread_id']='foreign'
                else:wrong[0]['sessionId']='foreign'
                save(ch=wrong)
                with self.assertRaises(Refused):native_child(root,state,attempt,locator)

    def test_native_failed_launch_is_attributed_without_inventing_a_child(self):
        from .authority import native_result
        with tempfile.TemporaryDirectory() as name,patch('pathlib.Path.home',return_value=Path(name)):
            home=Path(name);root=home/'project';root.mkdir()
            for host in ('codex','claude'):
                path=home/('.codex/sessions' if host=='codex' else '.claude/projects')/'parent.jsonl'
                path.parent.mkdir(parents=True)
                state={'host':host,'human':{'session':'parent','transcript_path':str(path)}}
                attempt={'id':'admission','profile':{'model':'fixture','effort':'high'},'started_at':'2026-10-15T12:00:00Z'}
                if host=='codex':
                    request={'type':'response_item','timestamp':'2026-10-15T12:00:01Z','payload':{'type':'function_call','name':'collaboration.spawn_agent',
                        'call_id':'launch','arguments':json.dumps({'task_name':'oh_admission','fork_turns':'none',
                                                                'model':'fixture','reasoning_effort':'high'})}}
                    failure={'type':'response_item','timestamp':'2026-10-15T12:00:02Z','payload':{'type':'function_call_output','call_id':'launch',
                        'output':'Error parsing native spawn: unavailable model.'}}
                else:
                    request={'type':'assistant','timestamp':'2026-10-15T12:00:01Z','sessionId':'parent','message':{'content':[{'type':'tool_use','id':'launch',
                        'name':'Agent','input':{'prompt':'Execute admission admission.','model':'fixture','effort':'high','fork_context':False}}]}}
                    failure={'type':'user','timestamp':'2026-10-15T12:00:02Z','sessionId':'parent','message':{'content':[{'type':'tool_result',
                        'tool_use_id':'launch','is_error':True,'content':'Native agent launch failed.'}]}}
                def save(rows):path.write_text(''.join(json.dumps(row)+'\n' for row in rows),newline='\n')
                save([request,failure])
                result=native_result(root,state,attempt,{'tool_use_id':'launch'})
                self.assertEqual(result['status'],'failed')
                self.assertIsNone(result['profile'])
                self.assertEqual(result['admitted_profile'],attempt['profile'])
                self.assertNotIn('native_id',result)
                self.assertEqual(len(result['record_hashes']),2)
                with self.assertRaises(Refused):native_result(root,state,attempt,{'tool_use_id':'foreign'})
                with self.assertRaises(Refused):native_result(root,state,attempt|{'started_at':'2026-10-15T12:00:03Z'},{'tool_use_id':'launch'})
                wrong_profile=json.loads(json.dumps(request))
                if host=='codex':
                    args=json.loads(wrong_profile['payload']['arguments']);args.update(model='unavailable',reasoning_effort='low')
                    wrong_profile['payload']['arguments']=json.dumps(args)
                else:wrong_profile['message']['content'][0]['input'].update(model='unavailable',effort='low')
                save([wrong_profile,failure])
                failed=native_result(root,state,attempt,{'tool_use_id':'launch'})
                self.assertIsNone(failed['profile']);self.assertEqual(failed['admitted_profile'],attempt['profile'])
                self.assertEqual(failed['requested_profile']['model'],'unavailable')
                save([request,{'type':'assistant','message':{'content':[{'type':'text','text':'Native launch failed.'}]}}])
                with self.assertRaises(Refused):native_result(root,state,attempt,{'tool_use_id':'launch'})

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
                from .authority import native_human
                locator={'host':host,'session':'session','prompt':'continue','transcript_path':str(path)}
                self.assertEqual(native_human(root,locator,latest=False)['prompt'],'continue')
                self.assertEqual(native_human(root,locator|{'turn':'turn'},latest=False)['prompt'],'continue')
                with self.assertRaises(Expired):native_human(root,locator)
                save()
                if host=='claude':  # the desktop app saves a typed turn as from a person, with its SDK marker
                    records[0]|={'origin':{'kind':'human'},'turnOrigin':'human','promptSource':'sdk','entrypoint':'claude-desktop'}
                    # docs/architecture.md: SDK code can stamp human origin; this is an accepted limitation.
                    for entrypoint in ('claude-desktop','sdk-cli','sdk-py','sdk-ts'):
                        records[0]['entrypoint']=entrypoint
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
                path.write_text('',newline='\n')
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
