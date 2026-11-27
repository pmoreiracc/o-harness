import json
import os
from .system import Path
import tempfile
import unittest
from unittest.mock import patch
from .storage import atomic_json,identifier
from .telemetry import connect,ingest,collect,emit,analytics
from .server import overview


def fixture(db,*,days=28):
    from datetime import datetime,timedelta,timezone
    project='ui-test-project';end=datetime.now(timezone.utc)
    for day in range(days):
        at=(end-timedelta(days=day,hours=2)).isoformat();run=f'run-{day}';task='1'
        def event(kind,payload,attempt=None):
            return {'id':identifier(),'at':at,'kind':kind,'project':project,'run':run,'task':task,'attempt':attempt,'payload':payload}
        ingest(db,event('run.started',{'name':'UI test data — disposable','work_kind':'harness','host':'codex','version':'test-v2' if day<14 else 'test-v1','config_hash':'fixture'}))
        ingest(db,event('task.started',{'title':'Fixture task '+str(day),'difficulty':['simple','standard','complex'][day%3],'rubric':1}))
        for role,model,tokens in [('implementation','gpt-5.6-sol',8000+day*300),('review','gpt-5.6-sol',6000+day*150)]:
            attempt=run+'-'+role
            ingest(db,event('attempt.started',{'role':role,'phase':role,'host':'codex','model':model,'effort':'high'},attempt))
            ingest(db,event('usage',{'response_id':attempt,'source':'fixture','input':tokens,'cached':tokens//2,'output':1000,'reasoning':400},attempt))
            ingest(db,event('attempt.finished',{'outcome':'clean' if role=='review' else 'implemented','duration_ms':500000,'substantive':True},attempt))
        ingest(db,event('task.finished',{'status':'completed','wall_ms':1200000+day*20000,'expected_attempts':2,'expected_reviews':1,'confirmed_interventions':0,'first_review':'clean'}))


class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,{'OH_DATA_HOME':self.tmp.name});env.start();self.addCleanup(env.stop)

    def test_coordinator_transcript_registration_uses_the_selected_claude_profile(self):
        from .transcripts import register
        from .storage import Refused,digest,read_json
        home=Path(self.tmp.name);profile=home/'separate profile'
        path=profile/'projects/p/session.jsonl';path.parent.mkdir(parents=True)
        path.write_text('{}\n',newline='\n')
        with patch.dict(os.environ,{'CLAUDE_CONFIG_DIR':str(profile),'OH_CHILD_ATTEMPT':''}):
            register(home,'claude',{'session_id':'session','transcript_path':str(path)},'run','project')
            source=home/'sources'/(digest({'host':'claude','session':'session'})+'.json')
            self.assertEqual(read_json(source)['path'],str(path.resolve()))
            outside=home/'outside.jsonl';outside.write_text('{}\n',newline='\n')
            with self.assertRaisesRegex(Refused,'Unexpected host transcript path'):
                register(home,'claude',{'session_id':'other','transcript_path':str(outside)},'run','project')

    def test_unavailable_dashboard_analysis_never_launches_a_model_or_alters_saved_analytics(self):
        from types import SimpleNamespace
        from .server import Handler
        with connect() as db:fixture(db,days=2)
        before=overview({})
        sent=[]
        handler=SimpleNamespace(trusted=lambda:True,path='/api/suggestions',
            headers={'X-OH-Token':'token','Origin':'http://localhost:4318'},
            server=SimpleNamespace(token='token',server_port=4318),send=lambda code,value:sent.append((code,value)))
        with patch('subprocess.run',side_effect=AssertionError('Analytics must not launch an agent')):
            Handler.do_POST(handler)
        self.assertEqual(sent[0][0],503)
        self.assertIn('unavailable',sent[0][1]['error'])
        self.assertEqual(overview({})['summary'],before['summary'])

    def test_dashboard_counts_deliveries_beyond_task_pages_and_keeps_unmeasured_work_unknown(self):
        from .dashboard import PAGE_SIZE, snapshot
        with connect() as db:
            fixture(db, days=105)
            db.execute("UPDATE tasks SET started='2026-11-20T01:00:00+00:00', "
                       "ended='2026-11-20T01:21:00+00:00', wall_ms=NULL")
            db.execute("UPDATE tasks SET started='2026-11-19T23:00:00+00:00' WHERE run='run-0'")
            db.execute("UPDATE tasks SET expected_attempts=3, expected_reviews=NULL WHERE run='run-1'")
            db.execute("UPDATE attempts SET duration_ms=NULL WHERE run='run-1' AND role='review'")
            db.execute("DELETE FROM usage WHERE attempt='run-1-review'")
            db.execute("INSERT INTO collector_state VALUES('gap:task:run-2:1','Missing task start')")
            db.execute("INSERT INTO collector_state VALUES('invalid_events','[{},{}]')")
            bounds = {'from': '2026-11-20T00:00:00+00:00', 'to': '2026-11-21T00:00:00+00:00'}
            data = snapshot(db, bounds)
            filtered = snapshot(db, bounds | {'model': 'gpt-5.6-sol', 'phase': 'assessment'})
            final_page = snapshot(db, bounds, 100)
        self.assertEqual(len(data['tasks']), PAGE_SIZE)
        self.assertEqual(len(final_page['tasks']), 4)
        self.assertEqual(data['started'], 103)
        self.assertEqual(data['delivered'], 103)
        self.assertEqual(sum(day['delivered'] for day in data['delivery']), 105)
        self.assertEqual(sum(day['timed'] for day in data['cohort']), 103)
        self.assertEqual(sum(day['elapsed_ms'] for day in data['cohort']), 103 * 21 * 60000)
        self.assertEqual(sum(day['reviewed'] for day in data['cohort']), 102)
        self.assertEqual(filtered['task_count'], 0)
        partial = next(task for task in data['tasks'] if task['run'] == 'run-1')
        self.assertIsNone(partial['observed_tokens'])
        self.assertIsNone(partial['agent_ms'])
        self.assertEqual(partial['review_outcomes'], ['clean'])
        self.assertEqual(data['health']['invalid_records'], 2)
        self.assertEqual(data['health']['gaps'], ['Missing task start'])

    def test_dashboard_http_projection_and_fonts_use_local_only_read_paths(self):
        from types import SimpleNamespace
        from .server import Handler

        with connect() as db:
            fixture(db, days=2)
            db.execute('DELETE FROM usage')
        sent = []
        handler = SimpleNamespace(
            trusted=lambda: True, path='/api/dashboard?offset=0&project=ui-test-project',
            send=lambda *args: sent.append(args))
        with patch('oh.transcripts.poll', side_effect=AssertionError('Dashboard GET cannot poll transcripts')):
            Handler.do_GET(handler)
        status, data = sent.pop()
        self.assertEqual(status, 200)
        self.assertEqual(data['task_count'], 2)
        self.assertEqual(data['coverage'], {'attempts': 4, 'measured': 0})
        self.assertEqual(data['usage'], [])
        self.assertTrue(all(task['observed_tokens'] is None for task in data['tasks']))
        handler.path = '/api/dashboard?offset=-1'
        Handler.do_GET(handler)
        self.assertEqual(sent.pop()[0], 400)
        handler.path = '/fonts/inter.ttf'
        Handler.do_GET(handler)
        status, body, content_type = sent.pop()
        self.assertEqual((status, content_type), (200, 'font/ttf'))
        self.assertTrue(body.startswith(b'\x00\x01\x00\x00'))
        handler.trusted = lambda: False
        Handler.do_GET(handler)
        self.assertEqual(sent.pop()[0], 403)

    def test_invalid_event_does_not_block_valid_events(self):
        emit('usage','p',attempt='bad',response_id='bad',source='fixture',input=2,cached=3)
        emit('usage','p',attempt='good',response_id='good',source='fixture',input=10,output=2)
        emit('usage',None,attempt='malformed',response_id='malformed',source='fixture',input=1,output=1)
        self.assertEqual(collect(),3)
        with connect() as db:self.assertEqual(db.execute('SELECT SUM(input) FROM usage').fetchone()[0],10)
        self.assertEqual(len(list((Path(self.tmp.name)/'quarantine').glob('*.json'))),2)
    def test_spend_follows_usage_time_and_includes_unfinished_work(self):
        with connect() as db:
            for kind,at,payload in [('run.started','2026-01-01',{'name':'Fixture','work_kind':'product','host':'codex','version':'1','config_hash':'c'}),('task.started','2026-01-01',{'title':'Old task','difficulty':'complex','rubric':1}),('attempt.started','2026-01-01',{'role':'implementation','phase':'implementation','host':'codex','model':'m'}),('usage','2026-02-10',{'response_id':'r','source':'fixture','input':100,'output':20})]:
                ingest(db,{'id':identifier(),'kind':kind,'at':at,'project':'p','run':'r','task':'t','attempt':'a','payload':payload})
            data=analytics(db,{'from':'2026-02-01','to':'2026-03-01'})
        self.assertEqual(data['summary']['input'],100);self.assertEqual(data['summary']['tasks'],0)
        self.assertEqual(data['series'][0]['day'],'2026-02-10');self.assertIsNone(data['summary']['tokens_per_completed'])
    def test_repeated_response_snapshot_uses_final_counts_once(self):
        with connect() as db:
            for output in [0,20,20,5]:
                ingest(db,{'id':identifier(),'kind':'usage','at':'2026-01-01','project':'p','attempt':'a','payload':{'response_id':'same','source':'fixture','input':10,'output':output}})
            self.assertEqual(tuple(db.execute('SELECT input,output FROM usage').fetchone()),(10,20))
    def test_matched_comparison_and_backup_restore(self):
        from .backup import backup,restore
        with connect() as db:fixture(db)
        data=overview({});self.assertEqual(len(data['matched_difficulties']),3)
        self.assertGreater(data['comparison']['tasks_per_period'],9)
        destination=Path(self.tmp.name).parent/('oh-backup-test-'+identifier())
        import shutil
        self.addCleanup(lambda path=destination:shutil.rmtree(path,ignore_errors=True))
        destination=destination/('a'*90)/('b'*90)/('backup # '+ 'c'*90)
        backup(destination)
        with tempfile.TemporaryDirectory() as restored:
            target=Path(restored)/('a'*90)/('b'*90)/('restored # '+ 'c'*90)
            try:
                with patch.dict(os.environ,{'OH_DATA_HOME':str(target)}):
                    if os.name=='nt':
                        import subprocess
                        from .storage import state_home
                        state_home()
                        subprocess.run(['icacls',os.fspath(target),'/grant','*S-1-5-32-545:(OI)(CI)(M)'],check=True,capture_output=True)
                    restore(destination)
                    if os.name=='nt':
                        from .system import untrusted
                        self.assertIn('S-1-5-32-545',untrusted(target,'folder'))
                        self.assertIn('S-1-5-32-545',untrusted(target/'analytics.sqlite3','file'))
                    with connect(readonly=True) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],28)
            finally:shutil.rmtree(Path(restored),ignore_errors=True)

    def test_missing_completion_evidence_remains_unknown_and_partial_usage_is_not_zero(self):
        with connect() as db:
            fixture(db,days=1)
            db.execute('UPDATE tasks SET confirmed_interventions=NULL,first_review=NULL,expected_reviews=NULL,expected_attempts=3')
            db.execute('UPDATE usage SET cached=NULL WHERE id LIKE ?',('%review',))
            data=analytics(db,{'from':'2000','to':'2100'})
            self.assertIsNone(data['summary']['autonomous']);self.assertIsNone(data['summary']['first_pass'])
            self.assertEqual(data['summary']['attempts'],3)
            self.assertIsNone(data['series'][0]['cached'])

    def test_filters_normalize_offset_instants(self):
        from .server import filters
        actual=filters({'from':['2026-09-25T00:00:00-03:00'],'to':['2026-09-26T00:00:00-03:00']})
        self.assertEqual(actual['from'],'2026-09-25T03:00:00.000+00:00')
        with self.assertRaises(ValueError):filters({'from':['2026-09-25'],'to':['2026-09-26']})

    def test_backup_refuses_active_writer_and_failed_restore_leaves_destination_empty(self):
        import threading,shutil
        from .backup import backup,restore
        from .storage import snapshot_guard,Refused
        with connect() as db:fixture(db,days=1)
        target=Path(self.tmp.name).parent/('oh-backup-test-'+identifier())
        self.addCleanup(lambda:shutil.rmtree(target,ignore_errors=True))
        entered=threading.Event();release=threading.Event()
        def active():
            with snapshot_guard():entered.set();release.wait(5)
        thread=threading.Thread(target=active);thread.start();entered.wait(1)
        try:
            with self.assertRaises(Refused):backup(target)
        finally:release.set();thread.join()
        backup(target)
        with tempfile.TemporaryDirectory() as restored,patch.dict(os.environ,{'OH_DATA_HOME':restored}):
            with patch('oh.backup.shutil.copytree',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):restore(target)
            self.assertEqual(list(Path(restored).iterdir()),[])
            restore(target)

    def test_partial_groups_and_attempt_time_do_not_present_exact_totals(self):
        from .observability import details

        with connect() as db:
            fixture(db,days=1)
            attempt=db.execute("SELECT id FROM attempts WHERE role='implementation'").fetchone()[0]
            ingest(db,{'id':identifier(),'kind':'usage','at':'2026-09-25','project':'ui-test-project','attempt':attempt,
              'payload':{'response_id':'partial','source':'fixture','input':100,'output':None}})
            data=analytics(db,{'from':'2000','to':'2100'})
            detail=details(db,'run-0','1')
            self.assertIsNone(data['summary']['output']);self.assertIsNone(data['summary']['tokens_per_completed'])
            self.assertIsNone(data['tasks'][0]['input']);self.assertIsNone(data['difficulty'][0]['tokens'])
            self.assertIsNone(next(m for m in data['models'] if m['role']=='implementation')['tokens'])
            self.assertEqual(next(m for m in data['model_times'] if m['role']=='implementation')['duration_ms'],500000)
        attempts={item['role']:item for item in detail['attempts']}
        self.assertIsNone(attempts['implementation']['observed_tokens'])
        self.assertEqual(attempts['review']['observed_tokens'],7000)

    def test_running_tasks_do_not_lower_completed_review_average(self):
        with connect() as db:
            fixture(db,days=2)
            db.execute("UPDATE tasks SET status='running',expected_reviews=0 WHERE run='run-1'")
            data=analytics(db,{'from':'2000','to':'2100'})
            self.assertEqual(data['summary']['avg_reviews'],1)
            self.assertEqual(data['summary']['tokens_per_completed'],16000)

    def test_corrupted_authority_backup_cannot_replace_destination(self):
        from .backup import backup,restore
        from .storage import Refused
        import shutil
        with connect():pass
        authority=Path(self.tmp.name)/'projects/example/authority.json'
        atomic_json(authority,{'allowed':1})
        target=Path(self.tmp.name).parent/('oh-backup-test-'+identifier())
        self.addCleanup(lambda:shutil.rmtree(target,ignore_errors=True))
        backup(target)
        (target/'projects/example/authority.json').write_text('{"allowed":999}')
        with tempfile.TemporaryDirectory() as restored,patch.dict(os.environ,{'OH_DATA_HOME':restored}):
            with self.assertRaises(Refused):restore(target)
            self.assertEqual(list(Path(restored).iterdir()),[])

    def test_readonly_connection_holds_snapshot_lock_and_cannot_write(self):
        import threading,sqlite3
        from .storage import snapshot_guard,Refused
        with connect():pass
        ready=threading.Event();release=threading.Event()
        def reader():
            with connect(readonly=True) as db:
                ready.set();release.wait(5)
        thread=threading.Thread(target=reader);thread.start();ready.wait(2)
        try:
            with self.assertRaises(Refused):
                with snapshot_guard(exclusive=True):pass
        finally:release.set();thread.join()
        with connect(readonly=True) as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM tasks')

    def test_terminal_transcript_boundary_excludes_later_conversation(self):
        from .transcripts import end_run,poll
        home=Path(self.tmp.name);transcript=home/'conversation.jsonl'
        def event(total):return json.dumps({'payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':total,'output_tokens':0},'last_token_usage':{'input_tokens':total}}}})+'\n'
        transcript.write_text(event(10))
        atomic_json(home/'sources/source.json',{'path':str(transcript),'host':'codex','session':'s','run':'r','project':'p','attempt':'a','offset':0,'totals':{'input_tokens':0,'output_tokens':0},'model':'m','effort':'high','end':None})
        end_run('r')
        with transcript.open('a') as stream:stream.write(event(999))
        poll()
        values=[json.loads(p.read_text())['payload']['input'] for p in (home/'spool').glob('*.json')]
        self.assertEqual(values,[10]);self.assertFalse((home/'sources/source.json').exists())

    def test_rebuild_recovers_derived_rows_and_preserves_authority(self):
        from .telemetry import rebuild
        emit('usage','p',attempt='a',response_id='r',source='fixture',input=20,output=5)
        collect()
        authority=Path(self.tmp.name)/'projects/p/authority.json';atomic_json(authority,{'untouched':True})
        with connect() as db:db.execute('DELETE FROM usage')
        result=rebuild();self.assertEqual(result['events'],1)
        with connect(readonly=True) as db:self.assertEqual(db.execute('SELECT input FROM usage').fetchone()[0],20)
        self.assertEqual(json.loads(authority.read_text()),{'untouched':True})

    def test_missing_start_is_visible_and_spool_failure_retains_gap(self):
        from .telemetry import best_effort
        emit('task.finished','p','r','t',status='completed',expected_attempts=2,wall_ms=10)
        with patch('oh.telemetry.emit',side_effect=OSError('simulated spool failure')):best_effort('task.started','p','r','missing')
        collect()
        with connect() as db:
            data=analytics(db,{'from':'2000','to':'2100'})
            self.assertEqual(data['summary']['tasks'],1);self.assertTrue(data['collection_gaps']);self.assertIsNone(data['tasks'][0]['input'])
            fresh=db.execute("SELECT value FROM collector_state WHERE key='last_ingested'").fetchone()[0]
        self.assertEqual(collect(),0)
        with connect() as db:self.assertEqual(db.execute("SELECT value FROM collector_state WHERE key='last_ingested'").fetchone()[0],fresh)

    def test_rebuild_corrupted_database_retains_gaps_and_recommendations(self):
        from .telemetry import rebuild
        home=Path(self.tmp.name)
        emit('usage','p',attempt='a',response_id='r',source='fixture',input=20,output=5)
        emit('usage','p',attempt='bad',response_id='bad',source='fixture',input=1,cached=99)
        collect()
        atomic_json(home/'analysis/recommendations/r.json',{'id':'r','created':'2026','evidence_hash':'h','status':'proposed','payload':'{}'})
        atomic_json(home/'gaps/retained/g.json',{'reason':'fixture'})
        (home/'analytics.sqlite3').write_bytes(b'corrupt')
        rebuild()
        with connect(readonly=True) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM recommendations').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT SUM(input) FROM usage').fetchone()[0],20)
            self.assertGreaterEqual(len(analytics(db,{'from':'2000','to':'2100'})['collection_gaps']),2)

    def test_terminal_boundary_inside_record_never_reads_later_bytes(self):
        from .transcripts import end_run,poll
        home=Path(self.tmp.name);path=home/'transcript.jsonl'
        line=json.dumps({'payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':999,'output_tokens':1}}}})+'\n'
        path.write_text(line[:20])
        atomic_json(home/'sources/s.json',{'path':str(path),'host':'codex','session':'s','run':'r','project':'p','attempt':'a','offset':0,'totals':{'input_tokens':0,'output_tokens':0},'end':None})
        end_run('r')
        with path.open('a') as stream:stream.write(line[20:])
        poll()
        events=[json.loads(p.read_text()) for p in (home/'spool').glob('*.json')]
        self.assertEqual([e['kind'] for e in events],['collection.gap']);self.assertFalse((home/'sources/s.json').exists())

    def test_unreadable_legacy_source_does_not_block_new_events(self):
        home=Path(self.tmp.name)
        (home/'sources').mkdir()
        (home/'sources/broken.json').write_text('unparseable',encoding='utf-8')
        emit('usage','p',attempt='a',response_id='response',source='fixture',input=10,output=2)
        self.assertEqual(collect(),1)
        self.assertEqual(collect(),0)
        with connect(readonly=True) as db:
            self.assertEqual(db.execute('SELECT SUM(input+output) FROM usage').fetchone()[0],12)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM collector_state WHERE value LIKE '%%legacy usage source%%'").fetchone()[0],1)

    def test_missing_attempt_start_is_visible_then_reconciled(self):
        emit('task.started','p','r','t',title='Task',difficulty='standard',rubric=1)
        emit('usage','p','r','t','a',response_id='response',source='fixture',input=10,output=2)
        emit('attempt.finished','p','r','t','a',outcome='implemented',duration_ms=9)
        collect()
        with connect() as db:
            row=db.execute("SELECT role,duration_ms FROM attempts WHERE id='a'").fetchone();self.assertEqual(tuple(row),('unknown',9))
            self.assertTrue(db.execute("SELECT 1 FROM collector_state WHERE key='gap:attempt:a'").fetchone())
        emit('attempt.started','p','r','t','a',role='implementation',phase='implementation',host='codex',model='fixture')
        collect()
        with connect() as db:
            self.assertEqual(tuple(db.execute("SELECT role,duration_ms FROM attempts WHERE id='a'").fetchone()),('implementation',9))
            self.assertFalse(db.execute("SELECT 1 FROM collector_state WHERE key='gap:attempt:a'").fetchone())

    def test_oversized_and_malformed_transcript_records_make_bounded_progress(self):
        from .transcripts import poll
        home=Path(self.tmp.name);path=home/'transcript.jsonl'
        usage={'payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':10,'output_tokens':2}}}}
        path.write_text(json.dumps({'large':'x'*(2*1024*1024+100)})+'\nnot-json\n'+json.dumps(usage)+'\n')
        atomic_json(home/'sources/s.json',{'path':str(path),'host':'codex','session':'s','run':'r','project':'p','attempt':'a','offset':0,'totals':{'input_tokens':0,'output_tokens':0},'end':None})
        poll();first=json.loads((home/'sources/s.json').read_text())['offset'];self.assertGreater(first,0);poll()
        events=[json.loads(p.read_text()) for p in (home/'spool').glob('*.json')]
        self.assertEqual(len([e for e in events if e['kind']=='collection.gap']),2)
        self.assertEqual([e['payload']['input'] for e in events if e['kind']=='usage'],[10])
        self.assertEqual(json.loads((home/'sources/s.json').read_text())['offset'],path.stat().st_size)

    def test_corrupt_rebuild_preserves_sqlite_sidecars(self):
        from .telemetry import rebuild
        home=Path(self.tmp.name);(home/'analytics.sqlite3').write_bytes(b'corrupt main')
        (home/'analytics.sqlite3-wal').write_bytes(b'corrupt wal evidence');(home/'analytics.sqlite3-shm').write_bytes(b'shm evidence')
        rebuild();saved=list((home/'recovery').iterdir());self.assertEqual(len(saved),1)
        self.assertEqual((saved[0]/'analytics.sqlite3-wal').read_bytes(),b'corrupt wal evidence')
        self.assertEqual((saved[0]/'analytics.sqlite3-shm').read_bytes(),b'shm evidence')

    def test_event_archival_syncs_both_directories_before_success(self):
        from .backup import sync_parent
        emit('usage','p',attempt='a',response_id='r',source='fixture',input=1,output=1)
        with patch('oh.backup.sync_parent',wraps=sync_parent) as sync:collect()
        synced={call.args[0].parent.resolve() for call in sync.call_args_list};home=Path(self.tmp.name).resolve()
        self.assertTrue({home/'spool',home/'events',home/'quarantine',home/'gaps',home/'gaps/retained'}<=synced)

    def test_coordinator_coverage_includes_wholly_unobserved_attempt(self):
        with connect() as db:
            for attempt in ['seen','missing']:
                ingest(db,{'id':identifier(),'kind':'attempt.started','at':'2026-01-01','project':'p','run':'r','task':None,'attempt':attempt,'payload':{'role':'orchestrator','phase':'coordination','host':'codex','model':'m'}})
            ingest(db,{'id':identifier(),'kind':'usage','at':'2026-02-10','project':'p','run':'r','attempt':'seen','payload':{'response_id':'seen','source':'fixture','input':10,'output':2}})
            filters={'from':'2026-02-01','to':'2026-03-01'}
            self.assertFalse(analytics(db,filters)['summary']['coordinator_usage_complete'])
            ingest(db,{'id':identifier(),'kind':'usage','at':'2026-02-10','project':'p','run':'r','attempt':'missing','payload':{'response_id':'missing','source':'fixture','input':10,'output':2}})
            self.assertTrue(analytics(db,filters)['summary']['coordinator_usage_complete'])
            def add(kind, run, attempt=None, **payload):
                ingest(db,{'id':identifier(),'at':'2026-02-10','kind':kind,'project':'p',
                           'run':run,'task':None,'attempt':attempt,'payload':payload})

            add('run.started','r',name='Legacy',work_kind='product',host='codex',version='old',config_hash='x')
            add('run.started','native',name='Native',work_kind='product',host='codex',version='new',
                config_hash='x',workflow='deliver')
            add('attempt.started','native','native-worker',role='implementation',phase='implementation',host='codex',model='m')
            self.assertTrue(analytics(db,filters|{'version':'old'})['summary']['coordinator_usage_complete'])
            self.assertFalse(analytics(db,filters)['summary']['coordinator_usage_complete'])


    def test_native_measurements_replay_distinguishes_child_and_coordinator_usage(self):
        from .storage import Journal
        from .telemetry import rebuild

        home = Path(self.tmp.name)
        native_homes = {'CODEX_HOME':str(home/'codex'), 'CLAUDE_CONFIG_DIR':str(home/'claude')}
        project = identifier()
        paths = []

        def at(minute):
            return f'2026-11-27T12:{minute:02}:00.000+00:00'

        def write(path, entries):
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(''.join(json.dumps(entry)+'\n' for entry in entries),encoding='utf-8',newline='\n')
            paths.append(path)

        def codex_record(kind, payload, minute):
            return {'timestamp':at(minute),'type':kind,'payload':payload}

        def claude_record(parent, msg, minute, usage, content=(), agent=None):
            return {'timestamp':at(minute),'type':'assistant','sessionId':parent,'agentId':agent,
                    'message':{'id':msg,'model':'claude-fixture','usage':usage,'content':list(content)}}

        def usage(parent, resp, i, o, minute):
            return codex_record('token_usage_record',{'thread_id':parent,'turn_id':'turn',
                'response_id':resp,'usage':{'input_tokens':i,'cached_input_tokens':5,
                                           'output_tokens':o,'reasoning_output_tokens':1}},minute)

        with patch.dict(os.environ,native_homes):
            for host, workflow, number in [('codex','deliver',1),('claude','propose',2)]:
                run, attempt, parent, child, call = [identifier() for _ in range(5)]
                if host == 'codex':
                    bound = home/'codex'/'sessions'/('child-'+child+'.jsonl')
                    owner = bound.parent/('parent-'+parent+'.jsonl')
                    write(bound,[
                        codex_record('session_meta',{'id':child,'model_provider':'openai','parent_thread_id':parent},1),
                        usage(child,'codex-child',40,10,2), usage(child,'codex-child',40,10,2),
                        usage(parent,'wrong-thread',500,10,2),
                    ])
                    child_records = bound.read_text(encoding='utf-8')
                    bound.unlink()  # The finished journal can reach OH before the transcript is saved.
                    delayed_child = bound, child_records
                    write(owner,[
                        usage(parent,'unallocated-other-turn',1000,20,1),
                        codex_record('response_item',{'type':'function_call','name':'spawn_agent','call_id':call},2),
                        usage(parent,'codex-parent',80,10,2),
                        codex_record('event_msg',{'type':'item_completed','thread_id':parent,'turn_id':'turn',
                            'item':{'type':'SubAgentActivity','id':call,'agent_thread_id':child,'model':'gpt-fixture'}},2),
                        codex_record('response_item',{'type':'function_call_output','call_id':call},2),
                    ])
                else:
                    owner = home/'claude'/'projects'/'fixture'/(parent+'.jsonl')
                    bound = owner.parent/parent/'subagents'/('agent-'+child+'.jsonl')
                    counters = {'input_tokens':5,'cache_read_input_tokens':10,'cache_creation_input_tokens':20}
                    write(bound,[claude_record(parent,'claude-child',2,counters|{'output_tokens':2},agent=child),
                                 claude_record(parent,'claude-child',2,counters|{'output_tokens':6},agent=child)])
                    spawn = {'type':'tool_use','id':call,'name':'Agent'}
                    write(owner,[
                        claude_record(parent,'mixed',1,counters|{'output_tokens':100},[spawn,spawn|{'id':'another-call'}]),
                        claude_record(parent,'claude-parent',2,counters|{'output_tokens':7},[spawn]),
                        claude_record(parent,'not-evidence',3,counters|{'output_tokens':999}),
                    ])
                journal = Journal(project,run)
                tasks = [{'id':str(n+1),'title':'A task','instructions':'Do work'} for n in range(number)]
                parent_ref = {'host':host,'session':parent,'transcript_path':str(owner)}
                entries = [
                    (0,'run.started',{'id':run,'project':project,'host':host,'native_version':2,'workflow':workflow,
                     'name':'Fixture','work_kind':'product','harness_version':'1.0.1','config_hash':'x',
                     'human':parent_ref,'tasks':tasks}),
                    (1,'task.started',{'task':'1'}),
                    (1,'attempt.started',{'id':attempt,'task':'1','role':'assessment','profile':{'model':'assessor'}}),
                    (1,'native.child.bound',{'attempt':attempt,'child':{'parent_session':parent,'child_session':child,
                         'tool_use_id':call,'transcript_path':str(bound)}}),
                    (4,'attempt.finished',{'id':attempt,'outcome':'assessed','duration_ms':101}),
                    (4,'task.assessed',{'task':'1','attempt':attempt,'difficulty':'complex','rationale':'Saved rating'}),
                    (5,'verification',{'task':'1','checks':[{'duration_ms':20},{'duration_ms':999,'reused':True}]}),
                    (6,'task.completed',{'task':'1'}),
                ]
                for minute,kind,record in entries:
                    with patch('oh.storage.now',return_value=at(minute)):
                        journal.append(kind,record)

            self.assertGreater(collect(),0)
            with connect(readonly=True) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM usage WHERE source='native.child.codex'").fetchone()[0],0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM usage WHERE source='native.child.claude'").fetchone()[0],1)
            delayed_child[0].write_text(delayed_child[1],encoding='utf-8',newline='\n')
            self.assertGreater(collect(),0)
            self.assertEqual(collect(),0)
            filters={'from':'2026-11-27T00:00:00.000+00:00','to':'2026-11-28T00:00:00.000+00:00'}
            with connect(readonly=True) as db:
                rows_before = [tuple(row) for row in db.execute('SELECT source,input,cached,output FROM usage ORDER BY source')]
                self.assertEqual(rows_before,[
                    ('native.anchor.claude',35,10,7), ('native.anchor.codex',80,5,10),
                    ('native.child.claude',35,10,6), ('native.child.codex',40,5,10),
                ])
                delivers = analytics(db,filters|{'workflow':'deliver'})
                proposes = analytics(db,filters|{'workflow':'propose'})
                task = delivers['tasks'][0]
                self.assertEqual((task['difficulty'],task['wall_ms']),('complex',300000))
                self.assertEqual((task['observed_worker_tokens'],task['observed_coordinator_tokens']),(50,90))
                self.assertIsNone(delivers['summary']['tokens_per_completed'])
                self.assertFalse(delivers['summary']['coordinator_usage_complete'])
                self.assertIsNone(proposes['tasks'][0]['observed_coordinator_tokens'])
                self.assertEqual(delivers['operations']['verification_ms'],20)
                self.assertEqual(delivers['operations']['checks_reused'],1)
                self.assertEqual({row['workflow'] for row in proposes['workflow_usage']},{'propose'})
            for path in paths:
                path.unlink()
            self.assertGreater(rebuild()['events'],4)
            with connect(readonly=True) as db:
                self.assertEqual([tuple(row) for row in db.execute('SELECT source,input,cached,output FROM usage ORDER BY source')],
                                 rows_before)
            self.assertEqual(collect(),0)
            with connect(readonly=True) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM usage').fetchone()[0],4)
                self.assertGreater(db.execute("SELECT COUNT(*) FROM collector_state WHERE key LIKE 'gap:native:%'").fetchone()[0],0)


    def test_native_restart_and_delivery_recovery_replace_stale_completed_measurements(self):
        from .storage import Journal
        from .telemetry import rebuild

        def at(minute):
            return f'2026-11-27T12:{minute:02}:00.000+00:00'

        def state(run):
            with connect(readonly=True) as db:
                return tuple(db.execute('SELECT status,started,ended,wall_ms FROM tasks WHERE run=?',(run,)).fetchone())

        for transition, change in [
            ('workflow.restarted',{'branch':'new','base':'base'}),
            ('delivery.recovered',{'branch':'new','base':'base','done':[],'summaries':[],'granted':['1'],'restart':True}),
        ]:
            with self.subTest(transition=transition):
                project, run = identifier(), identifier()
                journal = Journal(project,run)
                def append(minute,kind,data):
                    with patch('oh.storage.now',return_value=at(minute)):
                        journal.append(kind,data)
                append(0,'run.started',{'id':run,'project':project,'host':'codex','native_version':2,'workflow':'deliver',
                    'name':'Fixture','work_kind':'product','harness_version':'1.0.1','config_hash':'x',
                    'human':{'host':'codex','session':'coordinator'},
                    'tasks':[{'id':'1','title':'Task','instructions':'Do work'}]})
                append(1,'task.started',{'task':'1'})
                append(2,'task.completed',{'task':'1'})
                collect()
                self.assertEqual(state(run),('completed',at(1),at(2),60000))
                append(3,transition,change)
                collect()
                self.assertEqual(state(run),('unknown',at(1),None,None))
                rebuild()
                self.assertEqual(state(run),('unknown',at(1),None,None))
                append(4,'task.started',{'task':'1'})
                collect()
                self.assertEqual(state(run),('running',at(4),None,None))
                rebuild()
                self.assertEqual(state(run),('running',at(4),None,None))
