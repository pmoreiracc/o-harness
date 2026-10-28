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

    def test_codex_chat_reply_uses_the_completed_native_question_display(self):
        from copy import deepcopy
        from .authority import native_human,presented_question_at
        with tempfile.TemporaryDirectory() as name,patch('pathlib.Path.home',return_value=Path(name)):
            home=Path(name);root=home/'project';root.mkdir()
            path=home/'.codex/sessions/session.jsonl';path.parent.mkdir(parents=True)
            question='Approve the shown scope.md?'
            shown={'timestamp':'2026-10-23T18:30:01Z','type':'event_msg','payload':{
                'type':'item_completed','thread_id':'session','turn_id':'turn',
                'item':{'type':'AgentMessage','id':'question','content':[{'type':'Text','text':question}],
                        'phase':'final_answer','delivery':'async'}}}
            rows=[{'type':'session_meta','payload':{'id':'session','cwd':str(root),'source':'cli'}},
                  {'timestamp':'2026-10-23T18:30:00Z','type':'response_item','payload':{
                      'type':'message','role':'assistant','content':[{'type':'output_text','text':'Preparing the scope.'}]}},
                  shown,{'timestamp':'2026-10-23T18:30:02Z','type':'event_msg','payload':{
                      'type':'user_message','turn_id':'turn','message':'Approve this scope'}}]
            locator={'host':'codex','session':'session','transcript_path':str(path)}
            def read(records,subject='scope.md'):
                path.write_text(''.join(json.dumps(r)+'\n' for r in records),newline='\n')
                return native_human(root,locator,subject=subject)
            answer=read(rows)
            self.assertEqual((answer['prompt'],answer['question']),('Approve this scope',question))
            self.assertEqual(answer['question_at'],shown['timestamp'])
            # Native UI can put compact choices after the complete scope display.
            # Bind the original full display, not only the last assistant message.
            compact=deepcopy(shown);compact['timestamp']='2026-10-23T18:30:01.500Z'
            compact['payload']['item']['id']='choices'
            compact['payload']['item']['content'][0]['text']='Choose:\n- Approve this scope\n- Keep planning'
            split=read([*rows[:-1],compact,rows[-1]])
            self.assertEqual(presented_question_at(split,question),shown['timestamp'])
            from .decisions import verify_scope
            from .storage import digest
            scope={'tasks':['bounded']}
            prepared={'kind':'approve-scope','scope':digest(scope),'question':question,
                      'created_at':'2026-10-23T18:30:00.500Z'}
            (home/'decisions').mkdir()
            def verify(display):
                key=digest(prepared)
                (home/'decisions'/(key+'.json')).write_text(json.dumps(prepared))
                with patch('oh.native._home',return_value=home):
                    verify_scope(root,scope,{'decision':key},display)
            verify(split)
            prepared['created_at']='2026-10-23T18:30:01.250Z'
            with self.assertRaisesRegex(Refused,'predates'):verify(split)
            # Intervening human input clears that display even within the same turn.
            intervening=deepcopy(rows[-1]);intervening['timestamp']='2026-10-23T18:30:01.250Z'
            intervening['payload']['message']='Change the requested scope first'
            changed=[*rows[:-1],intervening,compact,rows[-1]]
            with self.assertRaises(Refused):read(changed)
            cleared=read(changed,subject=None)
            self.assertIsNone(presented_question_at(cleared,question))
            with self.assertRaises(Refused):verify(cleared)
            # Claude ordinary-chat replies have the same split-display contract.
            claude=home/'.claude/projects/p/session.jsonl';claude.parent.mkdir(parents=True)
            common={'sessionId':'session','cwd':str(root),'entrypoint':'cli'}
            displays=[common|{'type':'assistant','timestamp':part['timestamp'],
                      'message':{'content':[{'type':'text','text':part['payload']['item']['content'][0]['text']}]}}
                      for part in (shown,compact)]
            reply=common|{'type':'user','promptId':'reply','timestamp':rows[-1]['timestamp'],
                          'message':{'role':'user','content':'Approve this scope'}}
            for intervened in (False,True):
                content=[displays[0]]
                if intervened:content.append(reply|{'promptId':'changed','timestamp':intervening['timestamp'],
                                                   'message':{'role':'user','content':'Change the requested scope first'}})
                content += [displays[1],reply]
                claude.write_text(''.join(json.dumps(r)+'\n' for r in content),newline='\n')
                found=native_human(root,{'host':'claude','session':'session','transcript_path':str(claude)})
                self.assertEqual(presented_question_at(found,question),None if intervened else shown['timestamp'])
            # Only the actual preceding display in this conversation supplies context.
            for kind in ('other conversation','tool output','not completed','after reply','no human reply'):
                with self.subTest(kind=kind):
                    altered=deepcopy(rows)
                    if kind=='other conversation':altered[2]['payload']['thread_id']='foreign'
                    elif kind=='tool output':altered[2]['payload']['item']['type']='McpToolCall'
                    elif kind=='not completed':altered[2]['payload']['type']='item_started'
                    elif kind=='after reply':altered[2]['timestamp']='2026-10-23T18:30:03Z'
                    else:altered.pop()
                    with self.assertRaises(Refused):read(altered)

    def test_codex_repeated_chat_answers_keep_their_message_identity_and_legacy_replay(self):
        from .authority import native_human
        from .native import _human_key
        from .cancellation import owner_key
        from .storage import Journal, atomic_json, identifier
        with tempfile.TemporaryDirectory() as name,patch('pathlib.Path.home',return_value=Path(name)), \
                patch.dict(os.environ,{'OH_DATA_HOME':str(Path(name)/'data')}):
            root=Path(name)/'project';root.mkdir()
            path=Path(name)/'.codex/sessions/session.jsonl';path.parent.mkdir(parents=True)
            rows=[{'type':'session_meta','payload':{'id':'session','cwd':str(root),'source':'cli'}}]
            def append(kind,text,at,message_id):
                rows.append({'timestamp':at,'type':'event_msg','payload':{'type':'item_completed',
                    'thread_id':'session','turn_id':'same-turn','item':{'type':kind,'id':message_id,
                    'content':[{'type':'Text' if kind=='AgentMessage' else 'text','text':text}]}}})
                path.write_text(''.join(json.dumps(r)+'\n' for r in rows),newline='\n')
            locator={'host':'codex','session':'session','transcript_path':str(path)}
            append('AgentMessage','First scope.md question','2026-10-23T18:30:01Z','q1')
            append('UserMessage','Continue','2026-10-23T18:30:02Z','first')
            first=native_human(root,locator)
            append('AgentMessage','Second scope.md question','2026-10-23T18:30:03Z','q2')
            append('UserMessage','Continue','2026-10-23T18:30:04Z','second')
            # The legacy event form can coexist with the completed native item.
            rows.append({'timestamp':'2026-10-23T18:30:04Z','type':'event_msg','payload':{
                'type':'user_message','turn_id':'same-turn','message':'Continue'}})
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows),newline='\n')
            second=native_human(root,locator)
            self.assertEqual((second['message_id'],second['question'],second['at']),
                             ('second','Second scope.md question','2026-10-23T18:30:04Z'))
            old=locator|{'turn':'same-turn','message_id':'first'}
            self.assertEqual(native_human(root,old,latest=False),first)
            with self.assertRaises(Expired):native_human(root,old)
            with self.assertRaises(Refused):native_human(root,locator|{'message_id':'invented'})
            self.assertNotEqual(_human_key(first),_human_key(second))
            self.assertNotEqual(owner_key({'id':'run','human':first}),owner_key({'id':'run','human':second}))
            journal=Journal(identifier(),identifier())
            legacy={k:v for k,v in first.items() if k!='message_id'}
            key=_human_key(legacy)
            journal.append('run.started',{'human':legacy})
            state={'project':journal.path.parents[1].name,'id':journal.path.name,'source':key,'decisions':[key]}
            self.assertEqual(_human_key(first,state),key)
            self.assertEqual(_human_key(second,state),_human_key(second))
            # Old decision receipts, as well as initial scope, remain consumed.
            state['source']='another-source'
            atomic_json(journal.path/'decisions'/(key+'.json'),{'human':legacy})
            self.assertEqual(_human_key(first,state),key)
            self.assertEqual(_human_key(second,state),_human_key(second))
            # Incomplete old evidence cannot mint a second grant on upgrade.
            atomic_json(journal.path/'decisions'/(key+'.json'),{'human':{}})
            self.assertEqual(_human_key(first,state),key)

    def test_native_plan_retains_the_actual_human_accepted_scope(self):
        """The native plan viewer supplies approval once, without an OH menu identifier."""
        from copy import deepcopy
        from .authority import native_human, scope_human
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
            conversation={k:v for k,v in locator.items() if k!='tool_use_id'}
            conversation['turn']='hook-turn-not-a-plan-call'
            def recover(value=conversation, latest=True):
                return scope_human(root,value,since=since,subject='scope.md',latest=latest)
            def read(rows):
                path.write_text(''.join(json.dumps(r)+'\n' for r in rows),newline='\n')
                found=native_human(root,locator,since=since)
                recovered,resolved=recover()
                self.assertEqual(recovered,found)
                self.assertEqual(resolved['tool_use_id'],'plan')
                return found
            found=read(records)
            self.assertEqual((found['prompt'],found['via'],found['accepted_plan']),('approve','plan',plan))
            self.assertEqual(found['accepted_plan_path'],'native.md')
            self.assertEqual(len(found['record_hashes']),2)
            cancelled=base|{'type':'user','entrypoint':'cli','promptId':'cancel','timestamp':'2026-10-13T20:00:03+00:00',
                'message':{'role':'user','content':'No. Cancel that scope; do not implement it.'}}
            with self.assertRaises(Refused):read(records+[cancelled])
            with self.assertRaises(Refused):recover()
            self.assertEqual(native_human(root,locator,since=since,latest=False),found)
            self.assertEqual(recover(latest=False)[0],found)
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
                    with self.assertRaises(Refused):recover()
            read(records)
            with self.assertRaises(Refused):recover(conversation|{'tool_use_id':'wrong'})
            # A later unresolved/denied plan must not recover an older acceptance.
            later=deepcopy(records[0]);later['message']['content'][0]['id']='later'
            later['timestamp']='2026-10-13T20:00:02+00:00'
            path.write_text(''.join(json.dumps(r)+'\n' for r in records+[later]),newline='\n')
            with self.assertRaises(Refused):recover()
            denied=deepcopy(records[1]);denied['message']['content'][0].update(tool_use_id='later',is_error=True)
            with path.open('a') as stream:stream.write(json.dumps(denied)+'\n')
            with self.assertRaises(Refused):recover()
            # Existing valid typed approval remains the selected source.
            with patch('oh.authority.native_human',return_value={'via':'typed'}) as typed:
                self.assertEqual(recover(),({'via':'typed'},conversation))
                self.assertEqual(typed.call_count,1)


    def test_natural_language_and_slash_review_have_the_same_native_provenance(self):
        from .authority import native_human
        with tempfile.TemporaryDirectory() as name, patch('pathlib.Path.home',return_value=Path(name)):
            home=Path(name);root=home/'project';root.mkdir()
            for host in ('codex','claude'):
                path=home/('.codex/sessions' if host=='codex' else '.claude/projects')/'s.jsonl'
                path.parent.mkdir(parents=True)
                for prompt in ('Please review the manual changes.', '/oh-review changed', '/oh-design auth', '/oh-propose improve sign-in', '/oh-deliver fix timeout'):
                    locator={'host':host,'session':'s','turn':'t','prompt':prompt,'transcript_path':str(path)}
                    rows=([{'type':'session_meta','payload':{'id':'s','cwd':str(root),'source':'cli'}},
                           {'type':'event_msg','payload':{'type':'user_message','turn_id':'t','message':prompt}}]
                          if host=='codex' else [{'type':'user','sessionId':'s','promptId':'t','cwd':str(root),
                                                 'message':{'role':'user','content':prompt}}])
                    path.write_text(''.join(json.dumps(row)+'\n' for row in rows),newline='\n')
                    source=native_human(root,locator)
                    self.assertEqual(source['prompt'],prompt)
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
                    parents=[{'type':'assistant','sessionId':'parent','timestamp':'2026-10-15T12:00:01Z',
                              'message':{'content':[{'type':'tool_use','id':'spawn','name':'Agent','input':args}]}},
                             {'type':'user','sessionId':'parent','cwd':str(root),'timestamp':'2026-10-15T12:00:01+00:00',
                              'toolUseResult':{'isAsync':True,'status':'async_launched','agentId':'child','resolvedModel':'claude-sonnet-4-6'},
                              'message':{'content':[{'type':'tool_result','tool_use_id':'spawn','content':'Native agent launched.'}]}}]
                    children=[{'type':'assistant','agentId':'child','sessionId':'parent','cwd':str(root),
                               'timestamp':'2026-10-15T12:00:01+00:00',
                               'message':{'model':'claude-sonnet-4-6','content':[]}}]
                    final={'type':'user','agentId':'child','sessionId':'parent','cwd':str(root),
                           'timestamp':'2026-10-15T12:00:03+00:00','toolUseResult':'User rejected tool use',
                           'message':{'content':[{'type':'tool_result','tool_use_id':'bash','is_error':True,
                                                  'content':'User rejected tool use'}]}}
                def save(pr=parents,ch=children):
                    parent.write_text(''.join(json.dumps(row)+'\n' for row in pr),newline='\n')
                    child.write_text(''.join(json.dumps(row)+'\n' for row in ch),newline='\n')
                save();bound=native_child(root,state,attempt,locator)
                self.assertEqual(native_child(root,state,attempt,{}),bound)
                if host=='codex':
                    self.assertEqual(native_child(root,state,attempt,{'child_session':'/root/oh_admission'}),bound)
                    with self.assertRaises(Refused):native_child(root,state,attempt,{'child_session':'/foreign/oh_admission'})
                    duplicate=child.with_name('duplicate.jsonl');duplicate.write_bytes(child.read_bytes())
                    with self.assertRaises(Refused):native_child(root,state,attempt,{})
                    duplicate.unlink()
                self.assertEqual(bound['profile'],profile)
                self.assertEqual(bound['child_session'],'child')
                with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                if host=='claude':
                    # Claude also saves API bookkeeping with agent IDs but no cwd.
                    save(ch=children+[{'type':'api-request','agentId':'child','sessionId':'parent'}])
                    self.assertEqual(native_child(root,state,attempt,locator),bound)
                    save()
                    # Native Agent exposes a parent path alongside the child identity.
                    # Resolve only that known hint or the exact derived child path.
                    self.assertEqual(native_child(root,state,attempt,locator|{'transcript_path':str(parent)}),bound)
                    self.assertEqual(native_child(root,state,attempt,{k:v for k,v in locator.items() if k!='transcript_path'}),bound)
                    short_locator={k:v for k,v in locator.items() if k!='tool_use_id'}
                    self.assertEqual(native_child(root,state,attempt,short_locator),bound)
                    for label in ('missing result','foreign child','foreign parent','sidechain','ambiguous','failed result'):
                        events=deepcopy(parents)
                        if label=='missing result':events=events[:1]
                        elif label=='foreign child':events[-1]['toolUseResult']['agentId']='foreign'
                        elif label=='foreign parent':events[-1]['sessionId']='foreign'
                        elif label=='sidechain':events[-1]['isSidechain']=True
                        elif label=='ambiguous':
                            extra=deepcopy(events[-1]);extra['message']['content'][0]['tool_use_id']='other';events.append(extra)
                        elif label=='failed result':events[-1]['message']['content'][0]['is_error']=True
                        save(pr=events)
                        with self.subTest(spawn=label),self.assertRaises(Refused):native_child(root,state,attempt,short_locator)
                    save()
                    foreign=child.with_name('agent-foreign.jsonl');foreign.write_bytes(child.read_bytes())
                    with self.assertRaises(Refused):native_child(root,state,attempt,locator|{'transcript_path':str(foreign)})
                    foreign_parent=parent.with_name('foreign.jsonl');foreign_parent.write_bytes(parent.read_bytes())
                    with self.assertRaises(Refused):native_child(root,state|{'human':state['human']|{'transcript_path':str(foreign_parent)}},attempt,locator)
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
                if host=='codex':
                    self.assertEqual((result['text'],result['status']),('Complete public report.','completed'))
                    timed=final|{'timestamp':'2026-10-15T12:00:03Z'}
                    save(ch=children+[timed])
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['completed_at'],timed['timestamp'])
                    save(ch=children+[timed,{'type':'event_msg','timestamp':'2026-10-15T12:00:04Z',
                        'payload':{'type':'item_started','thread_id':'child','item':{'type':'FileChange','id':'later-edit'}}}])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    for empty in ('',None):
                        save(ch=children+[final|{'payload':final['payload']|{'last_agent_message':empty}}])
                        self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['status'],'unfinished')
                    save(ch=children+[final])
                else:
                    self.assertEqual(result['status'],'interrupted')
                    self.assertIn('The background task is still working.',result['text'])
                    completion={'type':'user','sessionId':'parent','timestamp':'2026-10-15T12:00:02Z',
                        'toolUseResult':{'agentId':'child','status':'completed'},
                        'message':{'content':[{'type':'tool_result','tool_use_id':'spawn','content':'Native completion.'}]}}
                    finished={'type':'assistant','agentId':'child','sessionId':'parent','cwd':str(root),
                        'timestamp':'2026-10-15T12:00:02Z','message':{'model':'claude-sonnet-4-6',
                        'content':[{'type':'text','text':'Complete public report.'}]}}
                    save(pr=parents+[completion],ch=children)
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['status'],'unfinished')
                    save(pr=parents+[completion,killed[-1]],ch=children+[finished])
                    completed=native_result(root,state,attempt|{'native_child':bound},locator)
                    self.assertEqual((completed['status'],completed['text']),('completed','Complete public report.'))
                    # Claude 2.1.296 ends a background child with an acknowledged
                    # SubagentHandback and an attributed peer message in the parent.
                    receipt='## Complete flexible receipt\n'+('Evidence remains exact: α, findings and limits.\n'*350)
                    call={'type':'assistant','isSidechain':True,'agentId':'child','sessionId':'parent','cwd':str(root),
                        'uuid':'handback-assistant','timestamp':'2026-10-15T12:00:04Z',
                        'message':{'model':'claude-sonnet-4-6','content':[{'type':'tool_use','id':'handback',
                            'name':'SubagentHandback','input':{'message':receipt},'caller':{'type':'direct'}}]}}
                    acknowledgement={'type':'user','isSidechain':True,'agentId':'child','sessionId':'parent','cwd':str(root),
                        'parentUuid':'handback-assistant','sourceToolAssistantUUID':'handback-assistant',
                        'timestamp':'2026-10-15T12:00:06Z','toolEndsTurn':True,
                        'permissionDecision':{'decision':'accept','source':'config','reasonType':'classifier'},
                        'message':{'content':[{'type':'tool_result','tool_use_id':'handback','content':[
                            {'type':'text','text':json.dumps({'success':True,'message':'Report delivered to your caller.'})}]}]}}
                    decorated='Native envelope text may change; report follows:\n'+'\n'.join('  '+line for line in receipt.split('\n'))
                    notice={'type':'user','sessionId':'parent','isSidechain':False,'isMeta':True,
                        'timestamp':'2026-10-15T12:00:05Z','promptSource':'system','turnOrigin':'peer',
                        'origin':{'kind':'peer','from':'child','senderTaskId':'child','name':'o-harness:reviewer','body':decorated,'handback':True},
                        'message':{'content':'Another Claude session sent a message: [Subagent hand-back] '+receipt}}
                    save(pr=parents+[notice],ch=[call,acknowledgement])
                    handback=native_result(root,state,attempt|{'native_child':bound},locator)
                    self.assertGreater(len(receipt),12563)
                    self.assertEqual((handback['status'],handback['text']),('completed',receipt))
                    self.assertEqual(len(handback['record_hashes']),3)
                    closing=finished|{'timestamp':'2026-10-15T12:00:07Z','message':{'content':[{'type':'text','text':'Report sent.'}]}}
                    for events in (parents+[notice],parents+[notice,completion|{'timestamp':'2026-10-15T12:00:08Z'}]):
                        save(pr=events,ch=[call,acknowledgement,closing])
                        self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['text'],receipt)
                    bad_ack=deepcopy(acknowledgement);bad_ack['message']['content'][0]['is_error']=True
                    save(pr=events,ch=[call,bad_ack,closing])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    # Background task envelopes survive even when Claude absorbs
                    # the peer handback into an already running parent turn.
                    def notification(status='completed',use='spawn',at='2026-10-15T12:00:07Z'):
                        text=('<task-notification>\n<task-id>child</task-id>\n'+('' if use is None else '<tool-use-id>'+use+'</tool-use-id>\n')+
                              '<output-file>/unused</output-file>\n<status>'+status+'</status>\n'
                              '<summary>Native task ended.</summary>\n</task-notification>')
                        return {'type':'queue-operation','operation':'enqueue','sessionId':'parent','timestamp':at,'content':text}
                    ended=notification()
                    attachment={'type':'attachment','sessionId':'parent','timestamp':ended['timestamp'],
                        'attachment':{'type':'queued_command','commandMode':'task-notification',
                            'origin':{'kind':'task-notification','producer':'session-task'},
                            'timestamp':ended['timestamp'],'prompt':ended['content']}}
                    unkeyed=notification(use=None)
                    unkeyed_attachment=deepcopy(attachment);unkeyed_attachment['attachment']['prompt']=unkeyed['content']
                    for envelope in (ended,attachment,unkeyed,unkeyed_attachment):
                        save(pr=parents+[envelope],ch=[call,acknowledgement])
                        self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['text'],receipt)
                        wrong_admission=attempt|{'profile':{'model':'opus','effort':'high'}}
                        failed=native_result(root,state,wrong_admission,locator)
                        self.assertEqual((failed['status'],failed['terminal_status']),('binding_failed','completed'))
                        self.assertEqual(failed['text'],receipt)
                    for label in ('wrong child','wrong call','wrong parent','sidechain','ordinary prose','removed queue','old event','foreign producer'):
                        with self.subTest(notification=label):
                            event=deepcopy(unkeyed)
                            if label=='wrong child':event['content']=event['content'].replace('<task-id>child','<task-id>foreign')
                            elif label=='wrong call':event['content']=event['content'].replace('</task-id>','</task-id><tool-use-id>foreign</tool-use-id>')
                            elif label=='wrong parent':event['sessionId']='foreign'
                            elif label=='sidechain':event['isSidechain']=True
                            elif label=='ordinary prose':event={'type':'user','sessionId':'parent','message':{'content':unkeyed['content']}}
                            elif label=='removed queue':event['operation']='remove'
                            elif label=='old event':event['timestamp']=attempt['started_at']
                            elif label=='foreign producer':
                                event=deepcopy(unkeyed_attachment);event['attachment']['origin']['producer']='model'
                            save(pr=parents+[event],ch=[call,acknowledgement])
                            with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    # A successful native stop needs no model-authored final report.
                    stop={'type':'assistant','sessionId':'parent','timestamp':'2026-10-15T12:00:02Z',
                        'message':{'content':[{'type':'tool_use','id':'stop','name':'TaskStop','input':{'task_id':'child'}}]}}
                    stopped={'type':'user','sessionId':'parent','timestamp':'2026-10-15T12:00:03Z',
                        'toolUseResult':{'task_id':'child','task_type':'local_agent','message':'Successfully stopped task'},
                        'message':{'content':[{'type':'tool_result','tool_use_id':'stop','content':'Native stop acknowledged.'}]}}
                    interrupted={'type':'user','agentId':'child','sessionId':'parent','cwd':str(root),'timestamp':'2026-10-15T12:00:03.001Z',
                        'message':{'content':[{'type':'text','text':'[Request interrupted by user]'}]}}
                    for evidence in ([stop,stopped],[notification('killed',at='2026-10-15T12:00:03.002Z')]):
                        save(pr=parents+evidence,ch=children+[interrupted])
                        self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['status'],'interrupted')
                        failed=native_result(root,state,wrong_admission,locator)
                        self.assertEqual((failed['status'],failed['terminal_status']),('binding_failed','interrupted'))
                    cleanup=interrupted|{'message':{'content':[{'type':'tool_result','tool_use_id':'cancelled-command',
                                                              'is_error':True,'content':'Command cancelled.'}]}}
                    save(pr=parents+[stop,stopped],ch=children+[cleanup])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    save(pr=parents+[stop,stopped,notification('killed',at='2026-10-15T12:00:03.002Z')],ch=children+[cleanup])
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['status'],'interrupted')
                    for label in ('no acknowledgement','wrong call','wrong child','shell task','failed stop','foreign parent','sidechain','model claim','missing time'):
                        with self.subTest(stop=label):
                            event=deepcopy(stopped);events=[stop,event]
                            if label=='no acknowledgement':events=[stop]
                            elif label=='wrong call':event['message']['content'][0]['tool_use_id']='foreign'
                            elif label=='wrong child':event['toolUseResult']['task_id']='foreign'
                            elif label=='shell task':event['toolUseResult']['task_type']='local_bash'
                            elif label=='failed stop':event['message']['content'][0]['is_error']=True
                            elif label=='foreign parent':event['sessionId']='foreign'
                            elif label=='sidechain':event['isSidechain']=True
                            elif label=='model claim':event['type']='assistant'
                            elif label=='missing time':event.pop('timestamp')
                            save(pr=parents+events,ch=children)
                            with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    # Reproduce the incident: stop, resume to hand back, then a
                    # completion notification referring to SendMessage, not Agent.
                    resume={'type':'assistant','sessionId':'parent','timestamp':'2026-10-15T12:00:03.500Z',
                        'message':{'content':[{'type':'tool_use','id':'resume','name':'SendMessage',
                            'input':{'to':'child','message':'Hand back.'}}]}}
                    resumed={'type':'user','sessionId':'parent','timestamp':'2026-10-15T12:00:03.600Z',
                        'toolUseResult':{'success':True,'resumedAgentId':'child'},
                        'message':{'content':[{'type':'tool_result','tool_use_id':'resume','content':'Resuming agent'}]}}
                    # Desktop Stop leaves child-local evidence when the old parent
                    # never receives a cancellation event. Both records are needed.
                    marker=interrupted|{'isSidechain':True}
                    meta_path=child.with_suffix('.meta.json')
                    stop_meta={'toolUseId':'spawn','stoppedByUser':True}
                    meta_path.write_text(json.dumps(stop_meta),newline='\n')
                    save(pr=parents,ch=children+[marker])
                    settled=native_result(root,state,attempt|{'native_child':bound},short_locator)
                    self.assertEqual(settled['status'],'interrupted')
                    # Windows Stop can use the tool-interruption marker. It is
                    # cancellation with native evidence, never later author work.
                    tool_marker=marker|{'message':{'content':[{'type':'text','text':'[Request interrupted by user for tool use]'}]}}
                    for rows in (parents,parents+[stop,stopped]):
                        save(pr=rows,ch=children+[tool_marker])
                        self.assertEqual(native_result(root,state,attempt|{'native_child':bound},short_locator)['status'],'interrupted')
                    meta_path.unlink();save(pr=parents+[stop,stopped],ch=children+[tool_marker])
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},short_locator)['status'],'interrupted')
                    save(pr=parents,ch=children+[tool_marker])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},short_locator)
                    meta_path.write_text(json.dumps(stop_meta),newline='\n');save(pr=parents,ch=children+[marker])
                    failed=native_result(root,state,attempt,short_locator)
                    self.assertEqual((failed['status'],failed['terminal_status']),('binding_failed','interrupted'))
                    self.assertEqual(native_result(root,state,attempt,short_locator),failed)
                    for label in ('no marker','no stop','foreign call','foreign parent','foreign child','not sidechain','model text','old marker','later work','later resume'):
                        event=deepcopy(marker);meta=stop_meta.copy();events=parents
                        if label=='no stop':meta['stoppedByUser']=False
                        elif label=='foreign call':meta['toolUseId']='foreign'
                        elif label=='foreign parent':event['sessionId']='foreign'
                        elif label=='foreign child':event['agentId']='foreign'
                        elif label=='not sidechain':event['isSidechain']=False
                        elif label=='model text':event['type']='assistant'
                        elif label=='old marker':event['timestamp']=attempt['started_at']
                        elif label=='later resume':events=parents+[resume,resumed]
                        records=children+([] if label=='no marker' else [event])
                        if label=='later work':records.append(call)
                        meta_path.write_text(json.dumps(meta),newline='\n');save(pr=events,ch=records)
                        with self.subTest(desktop_stop=label),self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    meta_path.unlink()
                    history=parents+[stop,stopped,resume,resumed]
                    save(pr=history,ch=children+[interrupted])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    rejected=deepcopy(resumed);rejected['message']['content'][0]['is_error']=True
                    save(pr=parents+[stop,stopped,resume,rejected],ch=children+[interrupted])
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['status'],'interrupted')
                    save(pr=history+[ended],ch=[call,acknowledgement])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    save(pr=history+[notification(use='resume')],ch=[call,acknowledgement])
                    recovered=native_result(root,state,wrong_admission,locator)
                    self.assertEqual((recovered['status'],recovered['terminal_status'],recovered['text']),('binding_failed','completed',receipt))
                    # Child activity also invalidates terminal evidence when the
                    # parent's corresponding resume record has not flushed yet.
                    save(pr=parents+[stop,stopped],ch=[call,acknowledgement])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    raw=notice|{'origin':notice['origin']|{'body':receipt}}
                    save(pr=parents+[raw],ch=[call,acknowledgement])
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['text'],receipt)
                    save(pr=parents+[notice],ch=[call,acknowledgement])
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator),handback)
                    # A synchronous Agent may absorb the forwarded message mid-turn.
                    # Its completed tool result already holds the exact handback report.
                    synchronous=deepcopy(completion);synchronous['timestamp']='2026-10-15T12:00:07Z'
                    synchronous['toolUseResult'].update(handback='send',handbackReport={'text':receipt})
                    sync_parents=[parents[0],synchronous]
                    early=progress|{'timestamp':'2026-10-15T12:00:03Z'}
                    save(pr=sync_parents,ch=[call,acknowledgement])
                    self.assertEqual(native_child(root,state,attempt,locator)['child_session'],'child')
                    sync_result=native_result(root,state,attempt|{'native_child':bound},locator)
                    self.assertEqual((sync_result['status'],sync_result['text']),('completed',receipt))
                    self.assertEqual(len(sync_result['record_hashes']),3)
                    save(pr=sync_parents,ch=[early,call,acknowledgement])
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator),sync_result)
                    self.assertEqual(native_result(root,{'host':'codex','human':{'session':'new-parent'}},
                        attempt|{'host':'claude','parent':state['human'],'native_child':bound},locator),sync_result)
                    # A report is model output, never a human decision.
                    from .authority import native_human
                    with self.assertRaises(Refused):native_human(root,{'host':'claude','session':'parent',
                        'tool_use_id':'spawn','transcript_path':str(parent)})
                    for label in ('different call','different child','different parent','sidechain','not completed',
                                  'error result','different report','malformed report','before acknowledgement'):
                        with self.subTest(synchronous=label):
                            response=deepcopy(synchronous)
                            if label=='different call':response['message']['content'][0]['tool_use_id']='other'
                            elif label=='different child':response['toolUseResult']['agentId']='other'
                            elif label=='different parent':response['sessionId']='other'
                            elif label=='sidechain':response['isSidechain']=True
                            elif label=='not completed':response['toolUseResult']['status']='async_launched'
                            elif label=='error result':response['message']['content'][0]['is_error']=True
                            elif label=='different report':response['toolUseResult']['handbackReport']['text']='Other report.'
                            elif label=='malformed report':response['toolUseResult']['handbackReport']='invalid'
                            elif label=='before acknowledgement':response['timestamp']='2026-10-15T12:00:05Z'
                            save(pr=[parents[0],response],ch=[early,call,acknowledgement])
                            with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    # Native timestamps can share a millisecond; UUID/call links and record order still establish acknowledgement.
                    save(pr=parents+[notice|{'timestamp':call['timestamp']}],ch=[call,acknowledgement|{'timestamp':call['timestamp']}])
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['text'],receipt)
                    save(pr=parents+[notice],ch=[call,acknowledgement])
                    old_attempt=attempt|{'host':'claude','parent':{'host':'claude',**state['human']},'native_child':bound}
                    transferred={'host':'codex','human':{'session':'different-parent','transcript_path':str(home/'elsewhere.jsonl')}}
                    self.assertEqual(native_result(root,transferred,old_attempt,locator),handback)
                    from .authority import human, prompted, claude_history
                    peer=notice|{'promptId':'peer-message'}
                    self.assertFalse(human(peer));self.assertFalse(prompted(peer,'parent'))
                    save(pr=parents+[peer],ch=[call,acknowledgement])
                    self.assertEqual(claude_history(parent,'parent'),[])
                    with self.assertRaises(Refused):attest('claude',{'hook_event_name':'UserPromptSubmit','session_id':'parent',
                        'turn_id':'peer-message','prompt':peer['message']['content'],'transcript_path':str(parent)},root)
                    for label in ('missing acknowledgement','wrong call','wrong parent UUID','wrong assistant UUID','not terminal',
                                  'rejected','failed acknowledgement','permission denied','foreign child','foreign parent',
                                  'ordinary tool','indirect call','missing forwarding','foreign sender','foreign task',
                                  'not peer','not handback','different body','changed indentation','trimmed body','malformed input','malformed caller','malformed permission','malformed origin',
                                  'outstanding command','background command','later activity'):
                        with self.subTest(handback=label):
                            request=deepcopy(call);reply=deepcopy(acknowledgement);forwarded=deepcopy(notice)
                            child_rows=[request,reply];parent_rows=parents+[forwarded]
                            if label=='missing acknowledgement':child_rows.pop()
                            elif label=='wrong call':reply['message']['content'][0]['tool_use_id']='other-call'
                            elif label=='wrong parent UUID':reply['parentUuid']='other-assistant'
                            elif label=='wrong assistant UUID':reply['sourceToolAssistantUUID']='other-assistant'
                            elif label=='not terminal':reply.pop('toolEndsTurn')
                            elif label=='rejected':reply['message']['content'][0]['is_error']=True
                            elif label=='failed acknowledgement':reply['message']['content'][0]['content'][0]['text']='{"success":false}'
                            elif label=='permission denied':reply['permissionDecision']['decision']='deny'
                            elif label=='foreign child':reply['agentId']='foreign'
                            elif label=='foreign parent':reply['sessionId']='foreign'
                            elif label=='ordinary tool':request['message']['content'][0]['name']='SendMessage'
                            elif label=='indirect call':request['message']['content'][0]['caller']['type']='indirect'
                            elif label=='missing forwarding':parent_rows=parents
                            elif label=='foreign sender':forwarded['origin']['from']='foreign'
                            elif label=='foreign task':forwarded['origin']['senderTaskId']='foreign'
                            elif label=='not peer':forwarded['origin']['kind']='human'
                            elif label=='not handback':forwarded['origin']['handback']=False
                            elif label=='different body':forwarded['origin']['body']=decorated+'changed'
                            elif label=='changed indentation':forwarded['origin']['body']=decorated.replace('\n  ','\n ')
                            elif label=='trimmed body':forwarded['origin']['body']=decorated.rstrip()
                            elif label=='malformed input':request['message']['content'][0]['input']='invalid native input'
                            elif label=='malformed caller':request['message']['content'][0]['caller']='invalid native caller'
                            elif label=='malformed permission':reply['permissionDecision']='invalid native permission'
                            elif label=='malformed origin':forwarded['origin']='invalid native origin'
                            elif label in ('outstanding command','background command'):
                                command=deepcopy(call);command['timestamp']='2026-10-15T12:00:03Z';command['uuid']='command'
                                command['message']['content']=[{'type':'tool_use','id':'command','name':'Bash',
                                    'input':{'command':'fixture','run_in_background':label=='background command'}}]
                                child_rows.insert(0,command)
                                if label=='background command':
                                    result=deepcopy(reply);result['message']['content'][0]['tool_use_id']='command'
                                    child_rows.insert(1,result)
                            elif label=='later activity':child_rows.append({'type':'assistant','agentId':'child','sessionId':'parent',
                                'cwd':str(root),'message':{'content':'Child resumed after handback.'}})
                            save(pr=parent_rows,ch=child_rows)
                            with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                            if label in ('missing acknowledgement','wrong call','wrong parent UUID','wrong assistant UUID',
                                         'not terminal','rejected','failed acknowledgement','permission denied','foreign child',
                                         'foreign parent','ordinary tool','indirect call','malformed input','malformed caller',
                                         'malformed permission','outstanding command','background command','later activity'):
                                save(pr=sync_parents,ch=[early]+child_rows)
                                with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    # A completed ordinary call before handback establishes quiescence.
                    command=deepcopy(call);command['timestamp']='2026-10-15T12:00:02Z';command['uuid']='command'
                    command['message']['content']=[{'type':'tool_use','id':'command','name':'Read','input':{'file_path':'fixture'}}]
                    result=deepcopy(acknowledgement);result['timestamp']='2026-10-15T12:00:03Z'
                    result['message']['content']=[{'type':'tool_result','tool_use_id':'command','content':'Read completed.'}]
                    save(pr=parents+[notice],ch=[command,result,call,acknowledgement])
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['text'],receipt)
                    # A background command the child's own record reports finished no longer blocks quiescence.
                    started=deepcopy(command);started['message']['content']=[{'type':'tool_use','id':'command','name':'Bash',
                        'input':{'command':'fixture','run_in_background':True}}]
                    denied=deepcopy(result);denied['message']['content'][0].update(is_error=True,content='User denied tool use')
                    for ending,expected in (([call,acknowledgement],receipt),
                                            ([finished|{'timestamp':'2026-10-15T12:00:04Z'}],'Complete public report.')):
                        save(pr=parents+[unkeyed],ch=[started,denied]+ending)
                        recovered=native_result(root,state,attempt|{'native_child':bound},locator)
                        self.assertEqual((recovered['status'],recovered['text']),('completed',expected))
                        for label in ('wrong call','model claim','successful start'):
                            invalid=deepcopy(denied)
                            if label=='wrong call':invalid['message']['content'][0]['tool_use_id']='foreign'
                            elif label=='model claim':invalid['type']='assistant'
                            else:invalid['message']['content'][0].pop('is_error')
                            save(pr=parents+[unkeyed],ch=[started,invalid]+ending)
                            with self.subTest(background_rejection=label),self.assertRaises(Refused):
                                native_result(root,state,attempt|{'native_child':bound},locator)
                    bg_done={'type':'attachment','agentId':'child','sessionId':'parent','cwd':str(root),'timestamp':'2026-10-15T12:00:03Z',
                        'attachment':{'type':'queued_command','prompt':'<task-notification>\n<task-id>x</task-id>\n<tool-use-id>command</tool-use-id>\n<output-file>/tmp/x</output-file>\n<status>completed</status>\n</task-notification>'}}
                    save(pr=parents+[notice],ch=[started,result,bg_done,call,acknowledgement])
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator)['text'],receipt)
                    # Claude may first report an interim stop, then finish after its
                    # own background work with a native notice lacking tool-use-id.
                    delivered={'type':'user','agentId':'child','sessionId':'parent','isMeta':True,
                        'timestamp':bg_done['timestamp'],'origin':{'kind':'task-notification','producer':'session-task'},
                        'message':{'content':'[SYSTEM NOTIFICATION - NOT USER INPUT]\n'+bg_done['attachment']['prompt']}}
                    interim=notification(at='2026-10-15T12:00:03.500Z')
                    waiting=finished|{'timestamp':'2026-10-15T12:00:03.250Z'}
                    save(pr=parents+[interim],ch=[started,result,waiting])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    for events,child_rows in (([interim],[started,result,bg_done,call,acknowledgement]),
                                              ([interim,unkeyed],[started,result,call,acknowledgement])):
                        save(pr=parents+events,ch=child_rows)
                        with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    completed_rows=[started,result,delivered,call,acknowledgement]
                    save(pr=parents+[interim,unkeyed],ch=completed_rows)
                    recovered=native_result(root,state,attempt|{'native_child':bound},locator)
                    self.assertEqual((recovered['status'],recovered['text']),('completed',receipt))
                    self.assertEqual(native_result(root,state,attempt|{'native_child':bound},locator),recovered)
                    for label in ('human','model','foreign producer','wrong command'):
                        invalid=deepcopy(delivered)
                        if label=='human':invalid.pop('isMeta')
                        elif label=='model':invalid['type']='assistant'
                        elif label=='foreign producer':invalid['origin']['producer']='model'
                        else:invalid['message']['content']=invalid['message']['content'].replace('<tool-use-id>command','<tool-use-id>foreign')
                        save(pr=parents+[interim,unkeyed],ch=[started,result,invalid,call,acknowledgement])
                        with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    save(pr=parents+[interim,unkeyed],ch=completed_rows+[finished|{'timestamp':'2026-10-15T12:00:08Z'}])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    later_resume=resume|{'timestamp':'2026-10-15T12:00:08Z'}
                    save(pr=parents+[interim,unkeyed,later_resume],ch=completed_rows)
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    # Delivery can lag enqueue. A later-delivered old parent notice
                    # must not end a newly resumed lifecycle without new child work.
                    late_delivery={'type':'user','sessionId':'parent','isMeta':True,
                        'timestamp':'2026-10-15T12:00:09Z','origin':delivered['origin'],
                        'message':{'content':'[SYSTEM NOTIFICATION - NOT USER INPUT]\n'+unkeyed['content']}}
                    save(pr=parents+[unkeyed,later_resume,late_delivery],ch=children+[finished])
                    with self.assertRaises(Refused):native_result(root,state,attempt|{'native_child':bound},locator)
                    forked=deepcopy(parents);forked[0]['message']['content'][0]['input']['subagent_type']='fork'
                    save(pr=forked)
                    with self.assertRaises(Refused):native_child(root,state,attempt,locator)
                # Transfer changes the current host/parent, never this attempt's provenance.
                original=attempt|{'host':host,'parent':{'host':host,**state['human']},'native_child':bound}
                transferred={'host':'claude' if host=='codex' else 'codex',
                             'human':{'session':'new-parent','transcript_path':str(home/'unrelated.jsonl')}}
                if host=='claude':save(pr=parents+[completion],ch=children+[finished])
                expected=native_result(root,state,original,locator)
                self.assertEqual(native_result(root,transferred,original,locator),expected)
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
                    # A later turn cannot be settled using an earlier terminal event.
                    save(pr=launched,ch=children+[final,{'type':'event_msg','payload':{'type':'task_started'}}])
                    with self.assertRaises(Refused):native_result(root,state,attempt,locator)
                    save(pr=launched,ch=children+[final,{'type':'event_msg','payload':{'type':'task_started'}},aborted])
                    self.assertEqual(native_result(root,state,attempt,locator)['terminal_status'],'interrupted')
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
                    # A launch may be cancelled before any child file is written.
                    child.unlink()
                    cancelled=native_result(root,state,attempt,locator)
                    self.assertEqual((cancelled['status'],cancelled['terminal_status']),('binding_failed','interrupted'))
                    self.assertIsNone(cancelled['profile'])
                    save(pr=launched,ch=[])
                    with self.assertRaises(Refused):native_result(root,state,attempt,locator)
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
                self.assertEqual(native_result(root,state,attempt,{}),result)
                self.assertEqual(result['status'],'failed')
                self.assertIsNone(result['profile'])
                self.assertEqual(result['admitted_profile'],attempt['profile'])
                self.assertNotIn('native_id',result)
                self.assertEqual(len(result['record_hashes']),2)
                save([request])
                with patch('oh.authority.sleep',side_effect=lambda delay:save([request,failure])) as wait:
                    self.assertEqual(native_result(root,state,attempt,{'tool_use_id':'launch'}),result)
                    self.assertEqual(wait.call_count,1)
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
                if host=='claude':
                    from .authority import coordinator
                    child=path.parent/'subagents'/'session.jsonl'
                    child.parent.mkdir();child.write_text('',newline='\n')
                    with self.assertRaisesRegex(Refused,'delegated child'):
                        coordinator(root,{'host':host,'human':{'session':'session','transcript_path':str(child)}})
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
