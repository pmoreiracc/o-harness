"""Shared sample plans and approved-plan setup for tests."""
from pathlib import Path
from . import plans
from .config import change
from .hosts import PROPOSAL_SCHEMA

BODY = '''## 1. Why this, and why now

People need to sign in before anything else works.

## 2. Tasks

### Core track

- [ ] **1.** Add the credential store.
- [ ] **2.** Add the sign-in endpoint. Depends on task 1.
'''


def design(title='Sign-in', body=BODY, summary='Two tasks.'):
    return {'kind': 'design', 'title': title, 'body': body, 'context': '', 'alternatives': '', 'consequences': '', 'summary': summary}


def idea(route='roadmap', **values):
    value = {key: '' for key in PROPOSAL_SCHEMA['required']} | {'depends': []}
    value |= {'route': route, 'understanding': 'Search across notes.', 'reason': 'New area with several PRs.',
              'evidence': 'Read docs/roadmap.md.', 'text': 'Full-text search over notes', 'summary': 'A new search row in M1.'}
    if route == 'roadmap':value |= {'slug': 'search', 'milestone': 'M1'}
    if route == 'task':value |= {'design': '0001', 'track': 'Core', 'text': 'Rate-limit sign-in attempts. Read §1.', 'depends': ['2']}
    return value | values


def delivery_documents(self,location='repo',body=BODY,base='main'):
    change(self.root,'plans.private_folder',str(Path(self.temp.name)/'plans'))
    change(self.root,'plans.location',location)
    where=plans.layout(self.root)
    plans.start_roadmap(where,'Fixture');plans.add_milestone(self.root,where,'M1','First','It works')
    plans.add_initiative(self.root,where,'M1','auth','Sign in',[])
    number,path=plans.write_design(self.root,where,'auth','Sign in',body,'approved')
    plans.claim(self.root,where,'auth',number)
    if location=='private':plans.approve(self.root,where,number,'human-approved',False)
    else:self.git('add','.');self.git('commit','-qm','approved plan')
    self.git('update-ref','refs/remotes/origin/'+base,'HEAD')
    return where,Path(path)
