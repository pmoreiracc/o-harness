from __future__ import annotations

from .storage import state_writer

from datetime import datetime,timedelta,timezone
import json
from .config import HOME,load,load_global,version
from . import hosts
from .hosts import invoke
from .storage import atomic_json,digest,identifier,now,project,state_home
from .telemetry import analytics,best_effort,connect,rows


def candidates(db):
    end=datetime.now(timezone.utc);start=end-timedelta(days=30)
    data=analytics(db,{'from':start.isoformat(),'to':end.isoformat()})
    s=data['summary']
    if data['collection_gaps'] or s.get('incomplete_observations') or s['input'] is None or s['output'] is None or s['tasks']<10 or not s['attempts'] or (s['measured_attempts'] or 0)/s['attempts']<.8:
        return [],data
    items=[]
    # All quantities are SQL-derived. Scenario factors are explicit hypotheses, not measurements.
    costs=rows(db,'''SELECT a.role,COUNT(DISTINCT a.id) attempts,CASE WHEN COUNT(u.input)=COUNT(*) AND COUNT(u.output)=COUNT(*) THEN SUM(u.input+u.output) END tokens
      FROM attempts a JOIN usage u ON u.attempt=a.id WHERE u.at>=? AND u.at<? GROUP BY a.role''',(start.isoformat(),end.isoformat()))
    for row in costs:
        if row['tokens'] is not None and row['role']=='review' and (s['avg_reviews'] or 0)>1.5:
            items.append({'key':'review-rework','title':'Reduce repeated review repairs',
              'tokens':row['tokens'],'fraction_low':.1,'fraction_high':.25,
              'theory':'Improve task handoffs and first-pass self-review for recurring findings; preserve independent reviews.',
              'assumption':'Scenario: avoid 10–25% of current review work, without reducing review coverage.'})
        if s['coordinator_usage_complete'] and row['role']=='orchestrator' and row['tokens'] and row['tokens']>(s['input']+s['output'])*.25:
            items.append({'key':'coordination','title':'Shorten orchestration context',
              'tokens':row['tokens'],'fraction_low':.15,'fraction_high':.35,
              'theory':'Keep coordination event-driven and handoffs bounded; move transcripts out of the parent context.',
              'assumption':'Scenario: remove 15–35% of coordinator tokens by reducing repeated context.'})
    simple=rows(db,'''SELECT CASE WHEN COUNT(u.input)=COUNT(*) AND COUNT(u.output)=COUNT(*) THEN SUM(u.input+u.output) END tokens,COUNT(DISTINCT a.id) attempts
      FROM attempts a JOIN tasks t ON t.run=a.run AND t.id=a.task JOIN usage u ON u.attempt=a.id
      WHERE t.difficulty='simple' AND a.role='implementation' AND u.at>=? AND u.at<?
      AND (a.model LIKE '%astra%' OR a.model LIKE '%opus%')''',(start.isoformat(),end.isoformat()))[0]
    if simple['tokens']:
        items.append({'key':'simple-routing','title':'Evaluate a lighter simple-task profile',
          'tokens':simple['tokens'],'fraction_low':0,'fraction_high':0,
          'theory':'Compare a cheaper model on simple tasks while preserving success and review outcomes.',
          'assumption':'Tokens do not establish subscription savings across models. Run a controlled comparison first.'})
    return items[:3],data


@state_writer
def generate(root=None,host='codex'):
    with connect() as db:
        items,data=candidates(db)
        evidence={'summary':data['summary'],'difficulty':data['difficulty'],'candidates':items,
                  'tasks':[(t['run'],t['id']) for t in data['tasks']]}
        evidence_hash=digest({k:evidence[k] for k in ('difficulty','candidates','tasks')})
        previous=rows(db,'SELECT id FROM recommendations WHERE evidence_hash=?',(evidence_hash,))
        if previous:return {'status':'unchanged','saved':len(previous)}
    if not items:return {'status':'insufficient_evidence','message':'At least ten tasks and 80% usage coverage are required, with a supported improvement signal.'}
    # Dashboard analysis covers the data store, not the engine directory as a product checkout.
    p=project(root) if root is not None else {'id':'insights','name':'OH insights'}
    attempt=identifier();analysis_run=identifier();directory=state_home()/'analysis'/attempt
    config=load(root) if root is not None else load_global()
    profile=config['models'][host]['insights']
    fallback=None;profile_error=None
    if invoke is hosts.invoke:
        from .capabilities import select_profile
        try:profile,fallback=select_profile(host,profile,root if root is not None else HOME)
        except Exception as exc:profile_error=exc
    best_effort('run.started',p['id'],analysis_run,name=p['name'],work_kind='harness',host=host,version=version(),config_hash=digest(config))
    best_effort('attempt.started',p['id'],analysis_run,None,attempt,role='analysis',phase='analysis',host=host,**profile)
    keys=[i['key'] for i in items]
    schema={'type':'object','additionalProperties':False,'required':['priority'], 'properties':{
      'priority':{'type':'array','items':{'type':'string','enum':keys},'minItems':len(keys),'maxItems':len(keys)}}}
    try:
        if profile_error:raise profile_error
        result=invoke(host,root if root is not None else HOME,profile,
          'Rank these supplied improvement hypotheses by expected usefulness. Return each supplied key exactly once. '
          'Do not use tools. Measurements and explanations are calculated by OH.\n'+json.dumps(evidence),
          'analysis',directory,{'project':p['id'],'run':analysis_run,'task':None,'attempt':attempt,
                               'compact_tokens':config['context']['compact_at_tokens'],'standalone':root is None},schema=schema,timeout=120)
    except Exception as exc:
        result={'failed':True,'error':str(exc),'duration_ms':None,'structured':None}
    structured=result.get('structured')
    order=structured.get('priority') if isinstance(structured,dict) else None
    if not result['failed'] and (not isinstance(order,list) or any(not isinstance(key,str) for key in order) or sorted(order)!=sorted(keys)):
        result=result|{'failed':True,'error':'The analysis agent returned an invalid ranking.'}
    if fallback:result=result|{'model_fallback':fallback}
    best_effort('attempt.finished',p['id'],analysis_run,None,attempt,outcome='failed' if result['failed'] else 'completed',
                duration_ms=result['duration_ms'],substantive=True)
    best_effort('run.status',p['id'],analysis_run,status='failed' if result['failed'] else 'completed')
    atomic_json(directory/'result.json',result,immutable=True)
    if result['failed']:
        error=result.get('error') or result.get('text') or 'The analysis agent did not finish successfully.'
        return {'status':'failed','evidence':str(directory),
                'message':f'Analysis failed: {error} Retry Analyze my data (or `oh suggest`) after resolving the error.'}|({'model_notices':[fallback['notice']]} if fallback else {})
    items=sorted(items,key=lambda item:order.index(item['key']))
    with connect() as db:
        for item in items:
            low=int(item['tokens']*item['fraction_low']);high=int(item['tokens']*item['fraction_high'])
            record={'title':item['title'],'explanation':item['theory'],
              'confidence':'Hypothesis','savings_label':f'{low:,}–{high:,} tokens / 30 days' if high else 'Savings require a model comparison',
              'assumptions':item['assumption'],'effort':'Needs implementation estimate',
              'quality_risk':'Keep acceptance and regression rates stable',
              'evidence_label':f'{data["summary"]["tasks"]} tasks · {item["tokens"]:,} observed relevant tokens',
              'evidence':evidence,'analysis_attempt':attempt,'expected_tokens_low':low,'expected_tokens_high':high,
              'payback':None,'realized_outcome':None}
            saved={'id':identifier(),'created':now(),'evidence_hash':evidence_hash,'status':'proposed','payload':json.dumps(record)}
            atomic_json(state_home()/'analysis/recommendations'/(saved['id']+'.json'),saved,immutable=True)
            db.execute('INSERT INTO recommendations VALUES(?,?,?,?,?)',tuple(saved[k] for k in ('id','created','evidence_hash','status','payload')))
    return {'status':'saved','saved':len(items)}|({'model_notices':[fallback['notice']],'message':fallback['notice']} if fallback else {})
