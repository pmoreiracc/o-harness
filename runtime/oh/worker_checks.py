"""An implementer's single-purpose check tool; native evidence, no workflow authority."""
import json
import contextlib
from pathlib import Path
from .storage import Refused, digest, git, lock, read_json, state_writer
from .workflow import load_run
from .verification import check_failed, failure_summary, tree, verify


def selection(root,state):
    from .checks import resolve
    # Include native progress before it is rendered, so document checks are not omitted.
    proposed=[state['delivery']['path']] if state.get('delivery',{}).get('layout',{}).get('location')=='repo' else []
    return resolve(root,state['project_checks']+state['checks'],state['base'],proposed_paths=proposed)


def active(directory,role='implementation'):
    directory=Path(directory).resolve()
    admitted=read_json(directory/'request.json');root=Path(admitted['root'])
    journal,state=load_run(root)
    last=state['attempts'][-1]
    allowed=('running','pausing') if role=='review' else ('running',)
    if (directory!=journal.path/'attempts'/last['id'] or last['finished'] or last['role']!=role
            or state['status'] not in allowed or admitted['id']!=last['id']
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
    packet=read_json(request['task_context']['path']);binding(packet['findings'])
    if packet.get('current_work') and packet['current_work']['report'].get('available',True):binding(packet['current_work']['report'])
    artifact=request.get('artifact',{})
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
            if self.path!=route or self.headers.get('Content-Length')!='2' or self.rfile.read(2)!=b'{}':
                self.send_error(403);return
            try:value=operation(directory)
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


def proxy(directory):
    from urllib.request import ProxyHandler,Request,build_opener
    from urllib.parse import urlsplit
    connection=read_json(Path(directory)/'checks-endpoint.json')
    url=urlsplit(connection['url'])
    if url.scheme!='http' or url.hostname!='127.0.0.1':raise Refused('Invalid native check endpoint')
    with build_opener(ProxyHandler({})).open(Request(connection['url'],data=b'{}'),timeout=connection['timeout']) as response:
        result=json.load(response)
    if 'error' in result:raise Refused(result['error'])
    return result


def serve(directory,stdin,stdout):
    from .mcp_server import Server
    reviewing=read_json(Path(directory)/'request.json')['role']=='review'
    operation='admission' if reviewing else 'verify'
    class CheckServer(Server):
        tools=[{'name':operation,'description':("Read-only validation of this review's exact admission, runtime, repository and artifact bindings. Call before reviewing. No arguments, tests or approval authority." if reviewing else "Run this task's configured project checks on the current work. Fix failures and call again before returning. No arguments; no approval or task completion authority."),
                'inputSchema':{'type':'object','properties':{},'additionalProperties':False},
                'annotations':{'readOnlyHint':reviewing}}]

        def tool(self,name,arguments,meta,ident):
            if name!=operation or arguments:raise Refused('Only '+operation+' with no arguments is available.')
            return json.dumps(proxy(directory))
    CheckServer(stdin,stdout).serve()
