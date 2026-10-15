"""Prepare immutable bounded scope without granting it or launching an agent."""
from pathlib import Path
from .storage import Refused, project, state_home, read_json


def directory(root):return state_home()/'projects'/project(root)['id']/'prepared'


def prepare(root,manifest=None,doc=None,track='',review=None,pr=None):
    from .native import prepare_scope
    value=read_json(manifest) if manifest is not None else None
    if pr is not None:
        from .publication import prepare_correction
        target=prepare_correction(root,pr)
        if value is None:raise Refused('A PR correction needs explicit bounded repair tasks')
        value['pr_target']=target
    if review:
        from .review import repair_source
        source=repair_source(root,review)
        if value is None:raise Refused('Review findings prepare bounded repair tasks')
        value['repair_source']=source
    return prepare_scope(root,value,doc,track)


def limits(count,config):return f"Up to {min(count,config['tasks_per_batch'])} tasks; {config['review_rounds']} independent reviews per task before human renewal."


def validate_work(root,source,*,branch=None):
    from .storage import digest
    if digest(read_json(source['receipt']))!=source['hash']:raise Refused('The original review evidence changed')
    return source
