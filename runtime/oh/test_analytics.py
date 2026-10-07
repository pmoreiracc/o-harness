import json
import os
from pathlib import Path
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

    def test_requested_insights_uses_global_profile_without_registering_the_engine(self):
        # docs/analytics.md: global insights uses a native read-only launch outside Git.
        from .config import HOME,write_file
        from .suggestions import generate
        write_file({'models':{'codex':{'insights':{'model':'gpt-6.1-sol','effort':'medium'}}}})
        with connect() as db:
            fixture(db,days=12)
            db.execute('UPDATE tasks SET expected_reviews=2')  # observed rework supplies a real supported candidate
        answer={'failed':False,'duration_ms':1,'structured':{'priority':['review-rework']}}
        with patch('oh.suggestions.invoke',return_value=answer) as invoke, \
                patch('oh.suggestions.project',side_effect=AssertionError('The engine is not a consumer project')):
            result=generate()
            self.assertEqual(result,{'status':'saved','saved':1})
            self.assertEqual(invoke.call_args.args[:3],('codex',HOME,{'model':'gpt-6.1-sol','effort':'medium'}))
            self.assertTrue(invoke.call_args.args[6]['standalone'])
            self.assertEqual(generate()['status'],'unchanged')
            invoke.assert_called_once()
        # Native host arguments support the packaged engine outside Git, with read-only permissions.
        from .hosts import command
        with patch('oh.hosts.executable',side_effect=lambda host,root:host), \
                patch('oh.storage.git',side_effect=AssertionError('Standalone analysis must not require Git')):
            for windows in (False,True):
                with patch('oh.hosts.WINDOWS',windows):
                    codex=command('codex',{'model':'gpt-6.1-sol','effort':'medium'},Path(self.tmp.name),'analysis',None,60000,standalone=True)
                    claude=command('claude',{'model':'opus','effort':'high'},Path(self.tmp.name),'analysis',None,60000,standalone=True)
                self.assertIn('--skip-git-repo-check',codex)
                self.assertEqual(codex[codex.index('--sandbox')+1],'read-only')
                self.assertEqual(claude[claude.index('--permission-mode')+1],'plan')
                self.assertNotIn('Edit',claude[claude.index('--tools')+1])

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
        self.addCleanup(lambda:shutil.rmtree(destination,ignore_errors=True))
        backup(destination)
        with tempfile.TemporaryDirectory() as restored,patch.dict(os.environ,{'OH_DATA_HOME':restored}):
            restore(destination)
            with connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],28)

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
        with connect() as db:
            fixture(db,days=1)
            attempt=db.execute("SELECT id FROM attempts WHERE role='implementation'").fetchone()[0]
            ingest(db,{'id':identifier(),'kind':'usage','at':'2026-09-25','project':'ui-test-project','attempt':attempt,
              'payload':{'response_id':'partial','source':'fixture','input':100,'output':None}})
            data=analytics(db,{'from':'2000','to':'2100'})
            self.assertIsNone(data['summary']['output']);self.assertIsNone(data['summary']['tokens_per_completed'])
            self.assertIsNone(data['tasks'][0]['input']);self.assertIsNone(data['difficulty'][0]['tokens'])
            self.assertIsNone(next(m for m in data['models'] if m['role']=='implementation')['tokens'])
            self.assertEqual(next(m for m in data['model_times'] if m['role']=='implementation')['duration_ms'],500000)

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
