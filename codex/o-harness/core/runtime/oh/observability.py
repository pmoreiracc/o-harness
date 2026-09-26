"""Optional observations never grant task or review authority."""
import json
import re
import subprocess
from .storage import Refused,git,project,read_json,state_home
from .telemetry import best_effort,rows


def review_metadata(text,findings=None):
    if findings is not None and all('relation' in f for f in findings):
        relations=[f['relation'] for f in findings]
    else:
        relations=re.findall(r'Finding \d+ \| Family: [a-z0-9-]+ \| Relation: ([a-z-]+)',text)
        if not relations and 'VERDICT: clean' not in text:return {}
    return {'repeat_findings':relations.count('repeat-family'),'fix_regressions':relations.count('fix-regression')}


def observe_ci(root):
    head=git(root,'rev-parse','HEAD');p=project(root);binding=None
    for file in (state_home()/'projects'/p['id']/'runs').glob('*/*.json'):
        value=read_json(file)
        if value.get('kind')=='task.completed' and value['data'].get('commit')==head:
            binding=(file.parent.name,value['data']['task'])
    if binding is None:
        for file in (state_home()/'projects'/p['id']).glob('design-runs/*/tasks/*/done.json'):
            value=read_json(file)
            if value.get('commit')==head:binding=(file.parents[2].name,value['task'])
    if binding is None:raise Refused('Current HEAD is not a recorded reviewed OH task commit')
    result=subprocess.run(['gh','run','list','--commit',head,'--json','databaseId,conclusion,status,headSha,url'],cwd=root,capture_output=True,text=True,timeout=30,check=True)
    items=json.loads(result.stdout)
    for item in items:
        if item['headSha']==head:best_effort('ci.observed',p['id'],binding[0],binding[1],**item)
    return {'observed_runs':len(items),'commit':head}


def details(db,run,task):
    attempts=rows(db,'SELECT * FROM attempts WHERE run=? AND task=? ORDER BY started',(run,task))
    events=rows(db,'SELECT at,kind,payload FROM events WHERE run=? AND task=? ORDER BY at LIMIT 300',(run,task))
    verification=[]
    for event in events:
        payload=json.loads(event['payload'])
        if event['kind']=='phase.finished':verification.append({'started':event['at'],'phase':payload['phase'],'duration_ms':payload.get('duration_ms'),'reused':payload.get('reused')})
    return {'attempts':attempts,'events':events,'verification':verification}


def metrics(db,filters):
    where=['e.at>=?','e.at<?'];args=[filters['from'],filters['to']]
    for field,column in [('project','e.project'),('kind','r.work_kind'),('version','r.version'),('difficulty','t.difficulty')]:
        if filters.get(field):where.append(column+'=?');args.append(filters[field])
    base=' FROM events e LEFT JOIN runs r ON r.id=e.run LEFT JOIN tasks t ON t.run=e.run AND t.id=e.task WHERE '+' AND '.join(where)
    result=dict(db.execute("""SELECT
      SUM(CASE WHEN e.kind='phase.finished' AND json_extract(e.payload,'$.phase')='verification' THEN json_extract(e.payload,'$.duration_ms') END) verification_ms,
      SUM(CASE WHEN e.kind='phase.finished' THEN json_extract(e.payload,'$.reused') END) checks_reused,
      SUM(CASE WHEN e.kind='phase.finished' THEN json_extract(e.payload,'$.checks') END) checks_total,
      SUM(CASE WHEN e.kind='phase.finished' AND json_extract(e.payload,'$.phase')='waiting' THEN json_extract(e.payload,'$.duration_ms') END) waiting_ms,
      SUM(CASE WHEN e.kind='attempt.finished' THEN json_extract(e.payload,'$.repeat_findings') END) repeated_findings,
      SUM(CASE WHEN e.kind='attempt.finished' THEN json_extract(e.payload,'$.fix_regressions') END) fix_regressions,
      SUM(CASE WHEN e.kind='attempt.finished' AND json_extract(e.payload,'$.outcome') IN ('failed','interrupted','history_changed') THEN 1 ELSE 0 END) interrupted_attempts,
      SUM(CASE WHEN e.kind='task.finished' THEN json_extract(e.payload,'$.recovered') END) recovered_tasks
      """+base,args).fetchone())
    ci=dict(db.execute("WITH observed AS (SELECT json_extract(e.payload,'$.conclusion') conclusion,json_extract(e.payload,'$.status') status,ROW_NUMBER() OVER(PARTITION BY json_extract(e.payload,'$.databaseId') ORDER BY e.at DESC) ordinal"+base+" AND e.kind='ci.observed') SELECT SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) ci_completed,SUM(CASE WHEN status='completed' AND conclusion IN ('failure','timed_out','action_required') THEN 1 ELSE 0 END) ci_failures FROM observed WHERE ordinal=1",args).fetchone())
    return result|ci
