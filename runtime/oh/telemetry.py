from __future__ import annotations

from .storage import state_writer, snapshot_guard

import json
import sqlite3
import time
from pathlib import Path
from .storage import atomic_json, encode, identifier, now, read_json, state_home, lock, Refused

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS events(
 id TEXT PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL,
 project TEXT NOT NULL, run TEXT, task TEXT, attempt TEXT, agent TEXT,
 payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_time ON events(at);
CREATE INDEX IF NOT EXISTS events_project_time ON events(project,at);
CREATE INDEX IF NOT EXISTS events_run_task ON events(run,task,kind);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, project TEXT NOT NULL, name TEXT, work_kind TEXT NOT NULL,
 host TEXT, version TEXT, config_hash TEXT, started TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS tasks(
 run TEXT NOT NULL, id TEXT NOT NULL, title TEXT, difficulty TEXT,
 rubric INTEGER, status TEXT, started TEXT, ended TEXT, wall_ms REAL,
 intervention_count INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(run,id));
CREATE INDEX IF NOT EXISTS tasks_started ON tasks(started,difficulty);
CREATE TABLE IF NOT EXISTS attempts(
 id TEXT PRIMARY KEY, run TEXT, task TEXT, role TEXT, phase TEXT, host TEXT,
 model TEXT, effort TEXT, tier TEXT, started TEXT, ended TEXT, duration_ms REAL,
 outcome TEXT, substantive INTEGER, context_tokens INTEGER, parent TEXT);
CREATE INDEX IF NOT EXISTS attempts_run_task ON attempts(run,task);
CREATE INDEX IF NOT EXISTS attempts_role_started ON attempts(role,started);
CREATE TABLE IF NOT EXISTS usage(
 id TEXT PRIMARY KEY, attempt TEXT NOT NULL, at TEXT NOT NULL,
 input INTEGER, cached INTEGER, output INTEGER, reasoning INTEGER,
 model TEXT, source TEXT NOT NULL, context_tokens INTEGER,
 UNIQUE(attempt,source,id));
CREATE INDEX IF NOT EXISTS attempts_run_task ON attempts(run,task);
CREATE INDEX IF NOT EXISTS usage_attempt ON usage(attempt,at);
CREATE INDEX IF NOT EXISTS usage_at ON usage(at);
CREATE TABLE IF NOT EXISTS recommendations(
 id TEXT PRIMARY KEY, created TEXT, evidence_hash TEXT, status TEXT,
 payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collector_state(key TEXT PRIMARY KEY, value TEXT);
'''


class Connection(sqlite3.Connection):
    def close(self):
        try:super().close()
        finally:
            guard=getattr(self,'_snapshot',None)
            if guard is not None:
                self._snapshot=None;guard.__exit__(None,None,None)
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()


def connect(path=None,*,readonly=False):
    guard=snapshot_guard();guard.__enter__()
    try:
        path=Path(path or state_home()/'analytics.sqlite3')
        connection=sqlite3.connect('file:'+str(path)+'?mode=ro' if readonly else path,
          uri=readonly,timeout=1,factory=Connection)
        connection._snapshot=guard
        connection.row_factory=sqlite3.Row
        if readonly:
            connection.execute('PRAGMA query_only=ON')
            return connection
        with lock(state_home()/'schema.lock'):
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA foreign_keys=ON')
            connection.executescript(SCHEMA)
            if 'project' not in {r[1] for r in connection.execute('PRAGMA table_info(attempts)')}:
                connection.execute('ALTER TABLE attempts ADD COLUMN project TEXT')
                connection.execute('CREATE INDEX IF NOT EXISTS attempts_project ON attempts(project,started)')
            columns={r[1] for r in connection.execute('PRAGMA table_info(tasks)')}
            for name,kind in [('expected_attempts','INTEGER'),('expected_reviews','INTEGER'),('confirmed_interventions','INTEGER'),('first_review','TEXT')]:
                if name not in columns:connection.execute(f'ALTER TABLE tasks ADD COLUMN {name} {kind}')
            connection.execute('INSERT OR IGNORE INTO schema_version VALUES(3)')
            connection.commit()
        return connection
    except BaseException:
        if 'connection' in locals():connection.close()
        else:guard.__exit__(None,None,None)
        raise


@state_writer
def emit(kind, project, run=None, task=None, attempt=None, agent=None, **payload):
    if kind=='run.status' and payload.get('status') in ('completed','stopped','pr','checkpoint'):
        from .transcripts import end_run
        end_run(run)
    event = {'id': identifier(), 'at': now(), 'kind': kind, 'project': project,
             'run': run, 'task': task, 'attempt': attempt, 'agent': agent, 'payload': payload,'recorded_ns':time.time_ns()}
    # Only a tiny durable file on the critical path. No SQLite or model call here.
    atomic_json(state_home() / 'spool' / (event['id'] + '.json'), event, immutable=True)
    return event


def best_effort(*args, **kwargs):
    try:
        return emit(*args, **kwargs)
    except (OSError,Refused,ValueError,KeyError) as exc:
        # Authority is separate; surface the gap without granting or losing task state.
        import sys
        print(f'OH telemetry unavailable: {exc}', file=sys.stderr)
        try:atomic_json(state_home()/'gaps'/(identifier()+'.json'),{'kind':args[0] if args else 'unknown','reason':str(exc),'at':now()},immutable=True)
        except (OSError,Refused):pass
        return None


def count(value):
    return value if type(value) is int and value >= 0 else None


def usage_values(payload):
    values = {key: count(payload.get(key)) for key in ('input', 'cached', 'output', 'reasoning')}
    if values['cached'] is not None and values['input'] is not None and values['cached'] > values['input']:
        raise Refused('Cached input cannot exceed total input')
    if values['reasoning'] is not None and values['output'] is not None and values['reasoning'] > values['output']:
        raise Refused('Reasoning cannot exceed total output')
    return values


def ingest(connection, event):
    p = event['payload']; kind = event['kind']
    cursor = connection.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
        (event['id'], event['at'], kind, event['project'], event.get('run'), event.get('task'),
         event.get('attempt'), event.get('agent'), json.dumps(p)))
    if not cursor.rowcount:
        return
    if event.get('run') and kind!='run.started' and not connection.execute('SELECT 1 FROM runs WHERE id=?',(event['run'],)).fetchone():
        connection.execute('INSERT INTO runs(id,project,name,work_kind,started,status) VALUES(?,?,?,?,?,?)',(event['run'],event['project'],'Unknown run (missing start)','unknown',event['at'],'unknown'))
        connection.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',('gap:run:'+event['run'],'Missing run start observation'))
    if event.get('task') and kind!='task.started' and not connection.execute('SELECT 1 FROM tasks WHERE run=? AND id=?',(event['run'],event['task'])).fetchone():
        connection.execute('INSERT INTO tasks(run,id,title,status,started) VALUES(?,?,?,?,?)',(event['run'],event['task'],'Unknown task (missing start)','unknown',event['at']))
        connection.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',('gap:task:'+event['run']+':'+event['task'],'Missing task start; timestamp is first observed event'))
    if event.get('attempt') and kind!='attempt.started' and not connection.execute('SELECT 1 FROM attempts WHERE id=?',(event['attempt'],)).fetchone():
        connection.execute('INSERT INTO attempts(id,run,task,role,phase,started,project) VALUES(?,?,?,?,?,?,?)',(event['attempt'],event.get('run'),event.get('task'),'unknown','unknown',event['at'],event['project']))
        connection.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',('gap:attempt:'+event['attempt'],'Missing attempt start; timestamp is first observed event'))
    if kind=='collection.gap':connection.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',('gap:'+event['id'],p.get('reason','Missing observation')))
    if kind == 'run.started':
        connection.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,work_kind=excluded.work_kind,host=excluded.host,version=excluded.version,config_hash=excluded.config_hash,started=excluded.started',
            (event['run'], event['project'], p.get('name'), p['work_kind'], p['host'],
             p['version'], p['config_hash'], event['at'], 'running'))
        connection.execute('DELETE FROM collector_state WHERE key=?',('gap:run:'+event['run'],))
    elif kind == 'run.status':
        connection.execute('UPDATE runs SET status=? WHERE id=?', (p['status'], event['run']))
    elif kind == 'task.started':
        connection.execute('INSERT INTO tasks(run,id,title,difficulty,rubric,status,started) VALUES(?,?,?,?,?,?,?) ON CONFLICT(run,id) DO UPDATE SET title=excluded.title,difficulty=excluded.difficulty,rubric=excluded.rubric,started=excluded.started',
            (event['run'], event['task'], p['title'], p['difficulty'], p['rubric'], 'running', event['at']))
        connection.execute('DELETE FROM collector_state WHERE key=?',('gap:task:'+event['run']+':'+event['task'],))
    elif kind == 'task.finished':
        connection.execute('UPDATE tasks SET status=?,ended=?,wall_ms=? WHERE run=? AND id=?',
            (p['status'], event['at'], p.get('wall_ms'), event['run'], event['task']))
        db_values=(p.get('expected_attempts'),p.get('expected_reviews'),p.get('confirmed_interventions'),p.get('first_review'),event['run'],event['task'])
        connection.execute('UPDATE tasks SET expected_attempts=?,expected_reviews=?,confirmed_interventions=?,first_review=? WHERE run=? AND id=?',db_values)
    elif kind == 'task.intervention':
        connection.execute('UPDATE tasks SET intervention_count=intervention_count+1 WHERE run=? AND id=?',
            (event['run'], event['task']))
    elif kind == 'attempt.started':
        connection.execute('''INSERT INTO attempts
          (id,run,task,role,phase,host,model,effort,tier,started,parent,project) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET run=excluded.run,task=excluded.task,role=excluded.role,phase=excluded.phase,host=excluded.host,model=excluded.model,effort=excluded.effort,tier=excluded.tier,started=excluded.started,parent=excluded.parent,project=excluded.project''',
            (event['attempt'],event['run'],event['task'],p['role'],p['phase'],p['host'],p.get('model'),
             p.get('effort'),p.get('tier'),event['at'],p.get('parent'),event['project']))
        connection.execute('DELETE FROM collector_state WHERE key=?',('gap:attempt:'+event['attempt'],))
    elif kind == 'attempt.finished':
        connection.execute('UPDATE attempts SET ended=?,duration_ms=?,outcome=?,substantive=?,context_tokens=? WHERE id=?',
            (event['at'],p.get('duration_ms'),p['outcome'],p.get('substantive'),p.get('context_tokens'),event['attempt']))
    elif kind == 'usage':
        u = usage_values(p)
        connection.execute('INSERT INTO usage VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET input=MAX(COALESCE(usage.input,excluded.input),COALESCE(excluded.input,usage.input)),cached=MAX(COALESCE(usage.cached,excluded.cached),COALESCE(excluded.cached,usage.cached)),output=MAX(COALESCE(usage.output,excluded.output),COALESCE(excluded.output,usage.output)),reasoning=MAX(COALESCE(usage.reasoning,excluded.reasoning),COALESCE(excluded.reasoning,usage.reasoning))',
            (p['response_id'],event['attempt'],event['at'],u['input'],u['cached'],u['output'],u['reasoning'],
             p.get('model'),p['source'],p.get('context_tokens')))


@state_writer
def collect(limit=2000):
    from .transcripts import poll
    poll()
    home = state_home()
    with lock(home / 'collector.lock'):
        # Unprocessed files only; dashboard reads never visit transcripts or receipts.
        paths = sorted((home / 'spool').glob('*.json'), key=lambda p: p.stat().st_mtime_ns)[:limit]
        gaps=list((home/'gaps').glob('*.json'))
        if not paths and not gaps:return 0
        with connect() as db:
            for gap in gaps:
                db.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',('gap:'+gap.stem,json.dumps(read_json(gap))))
            invalid=[]
            for path in paths:
                db.execute('SAVEPOINT event')
                try:ingest(db,read_json(path))
                except (Refused,ValueError,KeyError,TypeError,sqlite3.IntegrityError) as exc:
                    db.execute('ROLLBACK TO event')
                    invalid.append((path,str(exc)))
                finally:db.execute('RELEASE event')
            if invalid:
                db.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',('invalid_events',json.dumps([{'file':p.name,'error':e} for p,e in invalid])))
            db.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)', ('last_ingested', now()))
        # Archive only after committing. A crash here replays safely by ID.
        archive = home / 'events'
        archive.mkdir(exist_ok=True, mode=0o700)
        invalid_names={p.name for p,_ in invalid}
        quarantine=home/'quarantine';quarantine.mkdir(exist_ok=True,mode=0o700)
        for path in paths:
            path.replace((quarantine if path.name in invalid_names else archive)/path.name)
        gap_archive=home/'gaps/retained';gap_archive.mkdir(parents=True,exist_ok=True)
        for gap in gaps:gap.replace(gap_archive/gap.name)
        from .backup import sync_parent
        for folder in {home,home/'spool',archive,quarantine,home/'gaps',gap_archive}:
            if folder.exists():sync_parent(folder/'.entry')
        return len(paths)


def rows(db, sql, args=()):
    return [dict(row) for row in db.execute(sql, args)]


def analytics(db, filters):
    where = ['t.started >= ?', 't.started < ?']
    args = [filters['from'], filters['to']]
    for field, col in [('project','r.project'),('difficulty','t.difficulty'),('kind','r.work_kind'),('version','r.version')]:
        if filters.get(field):
            where.append(col + '=?');args.append(filters[field])
    predicate = ' AND '.join(where)
    # Pre-aggregate independent children before joining so attempts never multiply usage.
    cohort = f'''WITH selected AS (SELECT t.*,r.project,r.name,r.work_kind,r.host,r.version FROM tasks t
      JOIN runs r ON r.id=t.run WHERE {predicate}),
      au AS (SELECT a.id,a.run,a.task,a.role,a.model,a.effort,a.phase,a.duration_ms,a.outcome,a.substantive,
        SUM(u.input) input,SUM(u.cached) cached,SUM(u.output) output,SUM(u.reasoning) reasoning,
        MAX(u.context_tokens) context_tokens,COUNT(u.id) usage_rows,SUM(CASE WHEN u.input IS NOT NULL AND u.output IS NOT NULL THEN 1 ELSE 0 END) observations
        FROM attempts a JOIN selected selected_task ON selected_task.run=a.run AND selected_task.id=a.task LEFT JOIN usage u ON u.attempt=a.id GROUP BY a.id),
      totals AS (SELECT s.*,
        CASE WHEN COUNT(au.id)=SUM(CASE WHEN au.observations>0 AND au.observations=au.usage_rows THEN 1 ELSE 0 END)
          AND COUNT(au.id)>=COALESCE(s.expected_attempts,COUNT(au.id)) THEN SUM(au.input) END input,
        CASE WHEN COUNT(au.cached)=COUNT(au.id) THEN SUM(au.cached) END cached,
        CASE WHEN COUNT(au.id)=SUM(CASE WHEN au.observations>0 AND au.observations=au.usage_rows THEN 1 ELSE 0 END)
          AND COUNT(au.id)>=COALESCE(s.expected_attempts,COUNT(au.id)) THEN SUM(au.output) END output,SUM(au.reasoning) reasoning,
        COALESCE(s.expected_reviews,SUM(CASE WHEN au.role='review' THEN 1 ELSE 0 END)) reviews,
        SUM(CASE WHEN au.role='review' AND au.substantive=1 THEN 1 ELSE 0 END) substantive_reviews,
        SUM(CASE WHEN au.role='review' AND au.outcome='clean' THEN 1 ELSE 0 END) clean_reviews,
        SUM(au.duration_ms) agent_ms,COUNT(au.id) attempts,
        SUM(CASE WHEN au.observations>0 AND au.observations=au.usage_rows THEN 1 ELSE 0 END) measured_attempts
        FROM selected s LEFT JOIN au ON au.run=s.run AND au.task=s.id GROUP BY s.run,s.id)'''
    summary = dict(db.execute(cohort + ''' SELECT COUNT(*) tasks,
      SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,
      SUM(input) input,SUM(cached) cached,SUM(output) output,SUM(reasoning) reasoning,
      AVG(CASE WHEN status='completed' THEN wall_ms END) avg_wall_ms,AVG(CASE WHEN status='completed' THEN reviews END) avg_reviews,SUM(MAX(attempts,COALESCE(expected_attempts,attempts))) attempts,
      SUM(measured_attempts) measured_attempts,
      AVG(CASE WHEN status='completed' THEN CASE WHEN expected_reviews IS NOT NULL AND first_review IS NOT NULL THEN CASE WHEN first_review='clean' THEN 1.0 ELSE 0 END END END) first_pass,
      AVG(CASE WHEN status='completed' THEN CASE WHEN confirmed_interventions IS NOT NULL THEN CASE WHEN confirmed_interventions=0 THEN 1.0 ELSE 0 END END END) autonomous,
      CASE WHEN SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)>0 THEN
      CASE WHEN SUM(CASE WHEN status='completed' AND (input IS NULL OR output IS NULL) THEN 1 ELSE 0 END)=0 THEN 1.0*SUM(CASE WHEN status='completed' THEN input+output END)/SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) END END tokens_per_completed
      FROM totals''',args).fetchone())
    difficulties = rows(db,cohort+''' SELECT difficulty,COUNT(*) tasks,AVG(CASE WHEN status='completed' THEN wall_ms END) wall_ms,AVG(CASE WHEN status='completed' THEN COALESCE(expected_reviews,reviews) END) reviews,
       CASE WHEN COUNT(input)=COUNT(*) AND COUNT(output)=COUNT(*) THEN SUM(input+output) END tokens,AVG(CASE WHEN status='completed' THEN 1.0 ELSE 0 END) completion,
       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,
       SUM(CASE WHEN status='completed' AND expected_reviews IS NOT NULL AND first_review IS NOT NULL THEN 1 ELSE 0 END) quality_samples,
       SUM(CASE WHEN status='completed' AND confirmed_interventions IS NOT NULL THEN 1 ELSE 0 END) autonomy_samples,
       AVG(CASE WHEN status='completed' THEN CASE WHEN expected_reviews IS NOT NULL AND first_review IS NOT NULL THEN CASE WHEN first_review='clean' THEN 1.0 ELSE 0 END END END) first_pass,
       AVG(CASE WHEN status='completed' THEN CASE WHEN confirmed_interventions IS NOT NULL THEN CASE WHEN confirmed_interventions=0 THEN 1.0 ELSE 0 END END END) autonomous
       FROM totals GROUP BY difficulty''',args)
    tasks = rows(db,cohort+''' SELECT * FROM totals ORDER BY started DESC LIMIT 100''',args)
    # Spending follows observation time, not the date its task happened to start.
    # Include analysis, orchestration, unfinished and failed work without multiplying joins.
    spending_where=['u.at >= ?','u.at < ?'];spending_args=[filters['from'],filters['to']]
    for field,col in [('project','COALESCE(a.project,r.project)'),('difficulty','t.difficulty'),
                      ('kind','r.work_kind'),('version','r.version')]:
        if filters.get(field):spending_where.append(col+'=?');spending_args.append(filters[field])
    for field,col in [('model','COALESCE(u.model,a.model)'),('phase','a.phase')]:
        if filters.get(field):spending_where.append(col+'=?');spending_args.append(filters[field])
    spending=dict(db.execute('''SELECT CASE WHEN COUNT(u.input)=COUNT(*) THEN SUM(u.input) END input,CASE WHEN COUNT(u.cached)=COUNT(*) THEN SUM(u.cached) END cached,
      CASE WHEN COUNT(u.output)=COUNT(*) THEN SUM(u.output) END output,CASE WHEN COUNT(u.reasoning)=COUNT(*) THEN SUM(u.reasoning) END reasoning,COUNT(u.id) observations,SUM(CASE WHEN u.input IS NULL OR u.output IS NULL THEN 1 ELSE 0 END) incomplete_observations
      FROM usage u LEFT JOIN attempts a ON a.id=u.attempt LEFT JOIN runs r ON r.id=a.run
      LEFT JOIN tasks t ON t.run=a.run AND t.id=a.task WHERE '''+' AND '.join(spending_where),spending_args).fetchone())
    joins=' FROM usage u LEFT JOIN attempts a ON a.id=u.attempt LEFT JOIN runs r ON r.id=a.run LEFT JOIN tasks t ON t.run=a.run AND t.id=a.task WHERE '+' AND '.join(spending_where)
    series=rows(db,'SELECT substr(u.at,1,10) day,CASE WHEN COUNT(u.input)=COUNT(*) THEN SUM(u.input) END input,CASE WHEN COUNT(u.cached)=COUNT(*) THEN SUM(u.cached) END cached,CASE WHEN COUNT(u.output)=COUNT(*) THEN SUM(u.output) END output'+joins+' GROUP BY day ORDER BY day',spending_args)
    models=rows(db,'SELECT t.difficulty,COALESCE(u.model,a.model) model,a.role,a.effort,COUNT(DISTINCT a.id) attempts,COUNT(*) observations,SUM(CASE WHEN u.input IS NULL OR u.output IS NULL THEN 1 ELSE 0 END) incomplete_observations,CASE WHEN COUNT(u.input)=COUNT(*) AND COUNT(u.output)=COUNT(*) THEN SUM(u.input+u.output) END tokens'+joins+' GROUP BY t.difficulty,COALESCE(u.model,a.model),a.role,a.effort ORDER BY tokens DESC',spending_args)
    summary.update(spending)
    # A role with no usage rows must not disappear from coordinator coverage.
    # Include attempts overlapping the window, even if they began earlier.
    coord_where=["a.role='orchestrator'",'a.started < ?','(a.ended IS NULL OR a.ended >= ?)']
    coord_args=[filters['to'],filters['from']]
    for field,col in [('project','COALESCE(a.project,r.project)'),('difficulty','t.difficulty'),('kind','r.work_kind'),('version','r.version'),('model','a.model'),('phase','a.phase')]:
        if filters.get(field):coord_where.append(col+'=?');coord_args.append(filters[field])
    coverage=dict(db.execute('''SELECT COUNT(*) attempts,
      SUM(CASE WHEN EXISTS(SELECT 1 FROM usage u WHERE u.attempt=a.id AND u.at>=? AND u.at<?)
       AND NOT EXISTS(SELECT 1 FROM usage u WHERE u.attempt=a.id AND u.at>=? AND u.at<? AND (u.input IS NULL OR u.output IS NULL)) THEN 1 ELSE 0 END) measured
      FROM attempts a LEFT JOIN runs r ON r.id=a.run LEFT JOIN tasks t ON t.run=a.run AND t.id=a.task WHERE '''+' AND '.join(coord_where),[filters['from'],filters['to'],filters['from'],filters['to'],*coord_args]).fetchone())
    summary['coordinator_usage_complete']=bool(coverage['attempts'] and coverage['attempts']==coverage['measured'])
    # Duration counts each attempt once, using its start-time cohort, not usage rows.
    duration_where=['a.started >= ?','a.started < ?'];duration_args=[filters['from'],filters['to']]
    for field,col in [('project','COALESCE(a.project,r.project)'),('difficulty','t.difficulty'),('kind','r.work_kind'),('version','r.version'),('model','a.model'),('phase','a.phase')]:
        if filters.get(field):duration_where.append(col+'=?');duration_args.append(filters[field])
    model_times=rows(db,"SELECT t.difficulty,a.model,a.role,a.effort,COUNT(*) attempts,COUNT(a.duration_ms) measured_attempts,CASE WHEN COUNT(a.duration_ms)=COUNT(*) THEN SUM(a.duration_ms) END duration_ms FROM attempts a LEFT JOIN runs r ON r.id=a.run LEFT JOIN tasks t ON t.run=a.run AND t.id=a.task WHERE "+' AND '.join(duration_where)+' GROUP BY t.difficulty,a.model,a.role,a.effort',duration_args)
    phases=rows(db,"SELECT a.phase,COUNT(*) attempts,COUNT(a.duration_ms) measured_attempts,SUM(a.duration_ms) observed_ms,MAX((SELECT MAX(u.context_tokens) FROM usage u WHERE u.attempt=a.id)) peak_context FROM attempts a LEFT JOIN runs r ON r.id=a.run LEFT JOIN tasks t ON t.run=a.run AND t.id=a.task WHERE "+' AND '.join(duration_where)+' GROUP BY a.phase',duration_args)
    from .observability import metrics
    operations=metrics(db,filters)
    latest = db.execute("SELECT value FROM collector_state WHERE key='last_ingested'").fetchone()
    return {'summary':summary,'difficulty':difficulties,'series':series,'models':models,'model_times':model_times,'phases':phases,'operations':operations,'tasks':tasks,
      'freshness':latest[0] if latest else None,
      'collection_gaps':rows(db,"SELECT value FROM collector_state WHERE key='invalid_events' OR key LIKE 'gap:%'"),
      'projects':rows(db,'SELECT DISTINCT project id,name,work_kind FROM runs'),
      'versions':rows(db,'SELECT DISTINCT version FROM runs ORDER BY started DESC'),
      'recommendations':[json.loads(r['payload']) | {'id':r['id'],'status':r['status'],'created':r['created']}
        for r in rows(db,'SELECT * FROM recommendations ORDER BY created DESC LIMIT 3')]}


def rebuild():
    """Recreate derived analytics from retained events without touching task authority."""
    import os,tempfile,shutil
    with snapshot_guard(exclusive=True):
        home=state_home();temporary=Path(tempfile.mkdtemp(prefix='.rebuild-',dir=home))
        try:
            old=home/'analytics.sqlite3';recommendations=[]
            readable=False
            if old.exists():
                # SQLite may rewrite SHM even on a read-only connection. Preserve the
                # whole pre-open set first, while the exclusive snapshot lock is held.
                recovery=home/'recovery'/identifier();recovery.mkdir(parents=True)
                from .backup import durable,sync_parent
                for suffix in ('','-wal','-shm'):
                    component=Path(str(old)+suffix)
                    if component.exists():shutil.copy2(component,recovery/component.name)
                durable(recovery);sync_parent(recovery);sync_parent(recovery.parent)
                try:
                    with connect(readonly=True) as db:recommendations=rows(db,'SELECT * FROM recommendations')
                    readable=True
                except sqlite3.DatabaseError:pass
            saved=home/'analysis/recommendations'
            for record in recommendations:
                if not (saved/(record['id']+'.json')).exists():atomic_json(saved/(record['id']+'.json'),record,immutable=True)
            recommendations=[read_json(p) for p in saved.glob('*.json')]
            events=[read_json(p)|{'_mtime':p.stat().st_mtime_ns} for folder in ('events','spool') for p in (home/folder).glob('*.json')]
            events.sort(key=lambda e:(e['at'],e.get('recorded_ns',e['_mtime'])))
            with connect(temporary/'analytics.sqlite3') as db:
                for event in events:ingest(db,event)
                for record in recommendations:
                    db.execute('INSERT OR IGNORE INTO recommendations VALUES(?,?,?,?,?)',tuple(record[k] for k in ('id','created','evidence_hash','status','payload')))
                for gap in (home/'gaps').rglob('*.json'):
                    db.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',('gap:'+gap.stem,json.dumps(read_json(gap))))
                quarantined=list((home/'quarantine').glob('*.json'))
                if quarantined:db.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',('invalid_events',json.dumps({'quarantined':len(quarantined)})))
                db.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',('last_ingested',now()))
                db.commit();db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.execute('PRAGMA journal_mode=DELETE')
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise Refused('Rebuilt database failed integrity check')
            if old.exists():
                if readable:
                    with connect() as db:db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            for suffix in ('-wal','-shm'):Path(str(old)+suffix).unlink(missing_ok=True)
            from .system import replace
            replace(temporary/'analytics.sqlite3',old)
            from .backup import sync_parent
            sync_parent(old)
            return {'status':'rebuilt','events':len(events),'authority':'preserved'}
        finally:shutil.rmtree(temporary)
