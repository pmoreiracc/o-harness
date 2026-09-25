from __future__ import annotations

from .storage import state_writer

import os
from pathlib import Path
import subprocess
from .config import HOME,load as load_config,version
from .storage import atomic_json,checkout_id,digest,project,state_home,git


def environment(root):
    p=project(root);checkout=checkout_id(root);config=load_config(root)
    from .initial import pointer,load as load_initial
    if pointer(root).exists():
        _,initial=load_initial(root)
        branch=git(root,'branch','--show-current')
        if initial['branch']==branch or (branch=='main' and initial['base']==git(root,'rev-parse','HEAD')):config=initial['config']
    policy={'continuation_window_tasks':config['tasks_per_batch'],'review_window_rounds':config['review_rounds']}
    policy_file=state_home()/'policies'/(digest(policy)+'.json')
    if not policy_file.exists():atomic_json(policy_file,policy,immutable=True)
    evidence=state_home()/'projects'/p['id']/'checkouts'/checkout/'reviews'
    return os.environ|{'OH_HOME':str(HOME),'CLAUDE_PROJECT_DIR':str(root),'OH_PROJECT_ROOT':str(root),
      'OH_STATE_ROOT':str(evidence),'OH_POLICY_FILE':str(policy_file),
      'OH_REPOSITORY_ID':p['id']+':'+checkout,'OH_HARNESS_VERSION':version(),
      'OH_CONFIG_HASH':digest(config),'OH_EVENT_HOST':os.environ.get('OH_EVENT_HOST','')}


@state_writer
def execute(root,entry,args=(),*,input=None,check=False):
    return subprocess.run(['/bin/bash',str(HOME/'core'/entry),*map(str,args)],cwd=root,
      env=environment(root),input=input,text=True,capture_output=True,check=check)
