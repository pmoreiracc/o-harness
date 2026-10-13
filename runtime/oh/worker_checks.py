"""Attempt-bound checks, review admission and report submission; no workflow authority."""
import json
import contextlib
from pathlib import Path
from .storage import Refused, atomic_json, checkout_file, digest, git, lock, read_json, state_writer
from .workflow import load_run
from .verification import check_failed, failure_summary, tree, verify


def selection(root,state):
    from .checks import resolve
    # Include native progress before it is rendered, so document checks are not omitted.
    proposed=[state['delivery']['path']] if state.get('delivery',{}).get('layout',{}).get('location')=='repo' else []
    base=state.get('repair_source',{}).get('review_base',state['base'])
    return resolve(root,state['project_checks']+state['checks'],base,proposed_paths=proposed)


def active(directory,role='implementation',*,reporting=False):
    directory=Path(directory).resolve()
    admitted=read_json(directory/'request.json');root=Path(admitted['root'])
    journal,state=load_run(root)
    last=state['attempts'][-1]
    allowed=('running','pausing') if role=='review' or reporting else ('running',)
    if (directory!=journal.path/'attempts'/last['id'] or last['finished'] or last['role']!=role
            or state['status'] not in allowed or admitted['id']!=last['id']
            or digest(admitted)!=last.get('request_hash')
            or admitted.get('purpose','workflow')!=('standalone' if state.get('workflow')=='review' else 'workflow')
            or admitted.get('run',state['id'])!=state['id']
            or admitted['config_hash']!=state['config_hash'] or git(root,'rev-parse','HEAD')!=admitted['head']):
        raise Refused('This tool belongs only to the current running '+role+' attempt.')
    from .authority import owner_stop_reader
    if source:=owner_stop_reader(state)():
        from .controls import request,Interrupted
        request(root,'stop',expected_run=state['id'],source=source)
        raise Interrupted('Codex stopped the owning turn; no check was launched.')
    from .delivery import guard
    guard(root,state)
    return root,journal,state,last


def admission(directory):
    """Validate the active review's native bindings without running checks or changing the subject."""
    import hashlib
    from .config import HOME, version
    root,journal,state,attempt=active(directory,'review')
    request=read_json(Path(directory)/'request.json')
    if (digest(request)!=attempt.get('request_hash') or request['runtime']!=str(HOME) or
            request['harness_version']!=version() or digest(request['config'])!=state['config_hash'] or
            git(root,'branch','--show-current')!=state['branch'] or tree(root)!=request['tree'] or
            any(request[k]!=attempt[k] for k in ('id','task','role','profile','head','tree','git_tree','config_hash','harness_version'))):
        raise Refused('The review admission no longer matches this attempt, runtime or checkout. Retain it and admit the current subject again.')
    def binding(ref):
        if ref.get('path') and 'hash' in ref and digest(read_json(ref['path']))!=ref['hash']:
            raise Refused('A review JSON binding changed: '+str(ref['path']))
        if ref.get('sha256') and hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()!=ref['sha256']:
            raise Refused('A review file binding changed: '+str(ref['path']))
    for key in ('task_context','change_index','diff','covers','artifact'):
        if request.get(key):binding(request[key])
    if request.get('purpose','workflow')!=attempt.get('purpose','workflow'):
        raise Refused('Review purpose differs from its immutable admission.')
    packet=read_json(request['task_context']['path']);binding(packet['findings'])
    if packet.get('current_work') and packet['current_work']['report'].get('available',True):binding(packet['current_work']['report'])
    from .review import artifact_content
    artifact=artifact_content(request.get('artifact',{}))
    from .plans import file_identity
    for path,expected in artifact.get('files',{}).items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected or (path in artifact.get('identities',{}) and file_identity(path)!=artifact['identities'][path]):
            raise Refused('A reviewed planning artifact changed: '+path)
    return {'valid':True,'attempt':attempt['id'],'task':attempt['task'],'branch':state['branch'],
            'head':request['head'],'tree':request['tree'],'git_tree':request['git_tree'],
            'config_hash':state['config_hash'],'harness_version':request['harness_version'],
            'request_hash':attempt['request_hash'],'next':'Review the approved task, current packet and actual subject. Native bindings are verified; no harness-source investigation or project check execution is needed.'}


@state_writer
def run(directory):
    """The worker chooses when to check; commands and retained outcomes are native-owned."""
    directory=Path(directory).resolve()
    with lock(directory/'checks.lock',wait=False):
        root,journal,state,attempt=active(directory)
        checks=selection(root,state);before=tree(root)
        results=verify(root,checks,state['project'],controlled=True)
        after=tree(root)
        record={'task':attempt['task'],'attempt':attempt['id'],'head':attempt['head'],
                'tree':after,'before_tree':before,'contract':digest(checks),'checks':results}
        journal.append('verification',record)
        from .telemetry import best_effort
        best_effort('phase.finished',state['project'],state['id'],attempt['task'],phase='verification',
                    duration_ms=sum(r['duration_ms'] for r in results if not r['reused']),
                    reused=sum(r['reused'] for r in results),checks=len(results))
        passed=before==after and not any(check_failed(r) for r in results)
        return {'passed':passed,'checks':[{k:r.get(k) for k in ('name','command','returncode','duration_ms','cancellation','unavailable')} for r in results],
                'failure':failure_summary(results,state['config']['context']['result_chars']) if not passed else '',
                'next':('Complete self-review; call verify again after any further edit.' if passed else
                        'Checks changed the working tree. Inspect the changes and call verify again.' if before!=after else
                        'Diagnose and fix the failure within this task, then call verify again before returning.')}


def evidence(root,state,attempt):
    """A completed report cannot substitute for passing checks of the final implementation."""
    record=state.get('verification',{}).get(attempt['task'])
    if not record or record.get('attempt')!=attempt['id']:
        raise Refused('Call the verify tool before handing this implementation to review.')
    if (record.get('head')!=git(root,'rev-parse','HEAD') or record['tree']!=tree(root)
            or record.get('before_tree')!=record['tree'] or record.get('contract')!=digest(selection(root,state))):
        raise Refused('The implementation changed after verification. Call verify on the final work before review.')
    if any(check_failed(r) for r in record['checks']):
        raise Refused(failure_summary(record['checks'],state['config']['context']['result_chars']))
    return record['checks']


def report_errors(directory,value,root,journal,state,attempt):
    from . import hosts
    from .handoff import finding_ids,readiness_errors
    result={'failed':False,'structured':value}
    if attempt['role']=='review':return hosts.review_details(result)['issues']
    outcome,summary=hosts.work_result(result)
    if outcome=='report_invalid':return [summary]
    if outcome!='implemented':return []
    request=read_json(Path(directory)/'request.json');packet=read_json(request['task_context']['path'])
    index=read_json(packet['findings']['path'])
    if digest(packet)!=request['task_context']['hash'] or digest(index)!=packet['findings']['hash']:
        raise Refused('The supplied task packet or finding index changed; preserve the native evidence.')
    issues=readiness_errors(value['readiness'],finding_ids(index))
    failed=(any(a['task']==attempt['task'] and a.get('outcome')=='verification_failed' for a in state['attempts']) or
            any(r['kind']=='verification' and r['data'].get('attempt')==attempt['id'] and
                any(check_failed(c) for c in r['data']['checks']) for r in journal.records()))
    if failed and not value['readiness']['repairs']:
        issues.append('Explain the failed-check diagnosis, correction against approved behavior and proof in readiness.repairs.')
    try:evidence(root,state,attempt)
    except Refused as exc:issues.append(str(exc))
    return issues


@state_writer
def submit_report(directory,value):
    """Correct a report while its author is alive. Submissions never finish an attempt."""
    directory=Path(directory).resolve();request=read_json(directory/'request.json')
    role=request['role']
    if role not in ('implementation','review') or not request.get('report_protocol'):
        raise Refused('Report submission is unavailable for this admission.')
    root,journal,state,attempt=active(directory,role,reporting=True)
    if role=='review':admission(directory)
    with lock(checkout_file(root,'oh-control.lock')):
        from .controls import Interrupted
        if load_run(root)[1]['status'] not in ('running','pausing'):
            raise Interrupted('The run stopped; no report submission was accepted.')
        issues=report_errors(directory,value,root,journal,state,attempt)
        submitted={'report':value,'head':git(root,'rev-parse','HEAD'),'tree':tree(root),'issues':issues}
        key=digest(submitted);path=directory/'reports'/(key+'.json')
        if path.exists():
            if digest(read_json(path))!=key:raise Refused('The retained report submission changed; preserve its original evidence.')
        else:atomic_json(path,submitted,immutable=True)
        ref={'id':attempt['id'],'path':str(path),'hash':key,'issues':issues}
        if state.get('reports',{}).get(attempt['id'])!=ref:journal.append('report.submitted',ref)
        if issues:
            from .runner import progress
            progress(('Reviewer' if role=='review' else 'Implementation')+' report needs correction: '+'; '.join(issues)[:900])
        return {'accepted':not issues,'issues':issues,'receipt':str(path),
                'next':('Finish with a short summary. OH will recheck this report and subject before proceeding.' if not issues else
                        'Correct these problems and submit_report again in this same attempt. Do not restart the task or repeat unchanged passing checks.')}


def returned(directory,result):
    """Final prose cannot replace a submitted report, including after a rejected revision."""
    directory=Path(directory);request=read_json(directory/'request.json')
    if not request.get('report_protocol'):return result
    result=result|{'final_text':result.get('text','')}
    _,state=load_run(request['root']);ref=state.get('reports',{}).get(request['id'])
    if not ref:
        return result|{'structured':None,'text':'The agent ended without submitting its report. Preserve the work; inspect the worker tool failure before continuing.\n'+result.get('text',''),
                      'report_issues':['No native report submission was retained.']}
    value=read_json(ref['path'])
    if (digest(value)!=ref['hash'] or Path(ref['path']).parent!=directory/'reports' or
            value['head']!=git(request['root'],'rev-parse','HEAD') or value['tree']!=tree(request['root'])):
        return result|{'failed':True,'text':'The submitted report no longer matches its retained content or repository state. Preserve the work and inspect the changed binding.',
                      'structured':value.get('report'),'report_issues':['Submitted report binding changed.']}
    report=value['report']
    summary=report.get('summary','') if isinstance(report,dict) else ''
    return result|{'structured':report,'text':result.get('text','') if result.get('failed') else summary,
                  'report_submission':ref,'report_issues':value['issues']}


@contextlib.contextmanager
def service(directory):
    """Keep checks in OH's original environment; the subscription worker receives no environment copy."""
    import threading
    from http.server import BaseHTTPRequestHandler,HTTPServer
    from .storage import atomic_json,identifier
    admitted=read_json(Path(directory)/'request.json')
    operation=admission if admitted['role']=='review' else run
    route='/verify/'+identifier()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.connection.settimeout(5)
            try:length=int(self.headers.get('Content-Length','0'))
            except ValueError:length=0
            if self.path!=route or not 0<length<=262144:
                self.send_error(403);return
            try:
                payload=json.loads(self.rfile.read(length))
                if payload=={}:value=operation(directory)
                elif isinstance(payload,dict) and set(payload)=={'report'}:value=submit_report(directory,payload['report'])
                else:raise Refused('Only the admitted operation or submit_report is available.')
            except Exception as exc:value={'error':str(exc)}
            body=json.dumps(value).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers()
            with contextlib.suppress(BrokenPipeError,ConnectionResetError):self.wfile.write(body)
    class NativeServer(HTTPServer):
        def get_request(self):
            connection,address=super().get_request();connection.settimeout(5)
            return connection,address
    server=NativeServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.1},daemon=True)
    try:
        atomic_json(Path(directory)/'checks-endpoint.json',{'url':f'http://127.0.0.1:{server.server_port}'+route,
                    'timeout':admitted.get('verification_timeout',60)},immutable=True)
        thread.start()
        yield
    finally:
        # Do not return a worker result while its check is still in flight. Native Stop
        # cancels that check through the shared process controls, including on Windows.
        if thread.is_alive():server.shutdown();thread.join()
        server.server_close()


def proxy(directory,payload=None):
    from urllib.request import ProxyHandler,Request,build_opener
    from urllib.parse import urlsplit
    connection=read_json(Path(directory)/'checks-endpoint.json')
    url=urlsplit(connection['url'])
    if url.scheme!='http' or url.hostname!='127.0.0.1':raise Refused('Invalid native check endpoint')
    with build_opener(ProxyHandler({})).open(Request(connection['url'],data=json.dumps(payload or {}).encode()),timeout=connection['timeout']) as response:
        result=json.load(response)
    if 'error' in result:raise Refused(result['error'])
    return result


def serve(directory,stdin,stdout):
    from .mcp_server import Server
    request=read_json(Path(directory)/'request.json');reviewing=request['role']=='review'
    operation='admission' if reviewing else 'verify'
    from .handoff import report_schema
    packet=read_json(request['task_context']['path']);schema=report_schema(request['role'],read_json(packet['findings']['path']))
    class CheckServer(Server):
        tools=[{'name':operation,'description':("Read-only validation of this review's exact admission, runtime, repository and artifact bindings. Call before reviewing. No arguments, tests or approval authority." if reviewing else "Run this task's configured project checks on the current work. Fix failures and call again before returning. No arguments; no approval or task completion authority."),
                'inputSchema':{'type':'object','properties':{},'additionalProperties':False},
                'annotations':{'readOnlyHint':reviewing}}]
        if request.get('report_protocol'):
            tools=tools+[{'name':'submit_report','description':'Submit your final structured report for native validation. Correct returned issues before exiting. Writes OH evidence only; no task completion or approval authority.',
                'annotations':{'readOnlyHint':False,'destructiveHint':False,'openWorldHint':False},
                'inputSchema':{'type':'object','required':['report'],'additionalProperties':False,'properties':{'report':schema}}}]

        def tool(self,name,arguments,meta,ident):
            if name=='submit_report' and request.get('report_protocol') and isinstance(arguments,dict) and set(arguments)=={'report'}:
                return json.dumps(proxy(directory,arguments))
            if name!=operation or arguments:raise Refused('Only '+operation+' with no arguments is available.')
            return json.dumps(proxy(directory))
    CheckServer(stdin,stdout).serve()
