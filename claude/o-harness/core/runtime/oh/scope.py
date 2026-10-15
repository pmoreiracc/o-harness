"""Keep unrelated observations as future work, without changing the admitted task list."""
import re
from .storage import Refused


def append_section(text, heading, entry):
    """Quote untrusted prose so a reported checkbox or heading cannot become a design task."""
    ending='\r\n' if '\r\n' in text else '\n'
    text=text.replace('\r\n','\n')
    block='\n\n'+entry.strip()+'\n'
    match=re.search(r'^'+re.escape(heading)+r'[ \t]*$',text,re.M)
    if match:
        following=re.search(r'^## ',text[match.end():],re.M)
        at=match.end()+following.start() if following else len(text)
        text=text[:at].rstrip()+block+'\n'+text[at:]
    else:text=text.rstrip()+'\n\n'+heading+block
    return text.replace('\n',ending)


def undo_notes(text,records):
    """Remove only exact journalled insertions, preserving any unrelated plan edits."""
    for record in reversed(list(records)):
        change=record.get('change')
        if not change:continue
        if text.count(change['after'])!=1:raise Refused('Recorded scope notes changed; restore their reviewed text before resuming')
        text=text.replace(change['after'],change['before'],1)
    return text
