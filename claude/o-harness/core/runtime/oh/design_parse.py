"""Numbered design documents and the roadmap: the task list parser and the lifecycle renderer.
Output and messages match the former core/scripts/plan.sh, roadmap.sh and freeze.sh run in the C locale:
whitespace and case folding are ASCII only. Under a UTF-8 locale macOS awk also treated U+00A0 as space and
lowercased non-ASCII capitals, and it cut long titles by bytes where this cuts by characters."""
from datetime import date
from pathlib import Path
import re
from .storage import Refused

US='\x1f'
WS=' \t\n\r\f\v'  # awk [[:space:]]
SPACE='[ \t\n\r\f\v]'


def lines(path):
    try:text=Path(path).read_bytes().decode()
    except UnicodeDecodeError:raise Refused(f'{Path(path).name} is not valid UTF-8') from None
    rows=text.split('\n')
    return rows[:-1] if rows[-1]=='' else rows


def captured(text):
    # Shell $(...) drops trailing newlines; sed 's/^/  /' then indents every line.
    return ''.join('  '+line+'\n' for line in text.rstrip('\n').split('\n'))


def number(a,b):
    # awk compares two numeric-looking strings as numbers.
    return float(a)==float(b)


def design_file(root,doc):
    found=sorted(Path(root,'docs/design').glob(doc+'-*.md'))
    return str(root)+'/docs/design/'+found[0].name if found and found[0].is_file() else None


def frontmatter(path):
    result=[]
    for index,line in enumerate(lines(path)):
        if index==0:
            if line!='---':break
            continue
        if re.match('---'+SPACE+'*$',line):break
        result.append(line)
    return result


def fm_value(path,key):
    if not Path(path).is_file():return ''
    for line in frontmatter(path):
        if line.startswith(key+':'):return re.sub(SPACE+'*$','',re.sub('^'+key+':'+SPACE+'*','',line,count=1),count=1)
    return ''


def plan(root,doc):
    """Task rows: n, status, owner, needs, blocked and title, separated by 0x1f."""
    path=design_file(root,doc)
    if not path:raise Refused(f'plan.sh: no design doc matching docs/design/{doc}-*.md\n')
    rows=[];errors=[]
    state={'cur':'','owner':'','status':'','title':'','block':''}
    def flush():
        cur=state['cur']
        if cur=='':return
        block=state['block'];needs=''
        match=re.search(r'Depends on tasks?[^.*]*',block)
        if match:needs=','.join(re.findall('[0-9]+',match.group(0)))
        position=block.find('Depends on')
        if needs=='' and position>=0:
            fragment=re.split('[.*]',block[position:],maxsplit=1)[0]
            errors.append(f'task {cur} says "{fragment}" — expected "Depends on task N" or "Depends on tasks N, M"')
            state['cur']='';return
        blocked=''
        position=block.find('Blocked on ')
        if position>=0:blocked=re.split('[.*]',block[position+11:],maxsplit=1)[0].strip(WS)
        rows.append(US.join((cur,state['status'],state['owner'],needs,blocked,state['title'])))
        state['cur']=''
    blank=False
    for line in lines(path):
        was_blank,blank=blank,re.fullmatch(SPACE+'*',line) is not None
        if re.match('###'+SPACE+'+.*[Tt]rack'+SPACE+'*$',line):
            flush()
            fields=re.split('[ \t\n]+',line.strip(' \t\n'))
            state['owner']=re.sub('[A-Z]',lambda m:m[0].lower(),fields[1] if len(fields)>1 else '')
            continue
        if re.match('##[^#]',line):
            flush();state['owner']='';continue
        if re.match(r'-'+SPACE+r'*\[',line):
            flush()
            if not re.match(r'- \[[ x]\] \*\*[0-9]+\.\*\* ',line):
                errors.append('unrecognised task line: '+line);continue
            if state['owner']=='':
                errors.append('task outside any "### <name> track" section: '+line);continue
            marker=re.match(r'\*\*([0-9]+)\.',line[6:])
            title=re.sub('[`*]','',line[6+marker.end()+2:])
            title=re.sub(SPACE+'+',' ',title)
            title=re.sub('^ | $','',title)
            if len(title)>70:title=title[:67]+'...'
            state.update(cur=marker[1],status='done' if line[3:4]=='x' else 'pending',title=title,block=line)
            continue
        if re.match('[^ \t\n\r\f\v]',line) and was_blank:
            flush()
            # A dependency stranded on the far side of the blank line belongs to no task.
            if re.search('Depends on tasks?'+SPACE+'+[0-9]',line):
                errors+=['orphan dependency: '+line,'  a blank line separates it from any task. Put it on the task line, or indent it.']
            continue
        if state['cur']!='':state['block']+=' '+line
    flush()
    if errors:
        raise Refused(f'plan.sh: cannot parse {path} — refusing to report a partial task list.\n'+''.join('  '+e+'\n' for e in errors))
    if not rows:raise Refused(f'plan.sh: {path} has no task list. A design doc without tasks cannot be delivered.\n')
    ids=[row.split(US,1)[0] for row in rows]
    duplicates=sorted({i for i in ids if ids.count(i)>1})
    if duplicates:raise Refused(f'plan.sh: duplicate task numbers in {path}: '+' '.join(duplicates)+'\n')
    return ''.join(row+'\n' for row in rows)


LINK=r'\[[0-9]{4}\]\(\./design/[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*\.md\)'


def roadmap(root,mode=''):
    """Initiative rows (slug, milestone, depends, design) or, with --delivered, collapsed pointers."""
    path=str(root)+'/docs/roadmap.md'
    if not Path(path).is_file():raise Refused(f'roadmap.sh: no docs/roadmap.md under {root}\n')
    rows=[];errors=[];delivered=[];shipped={};milestone=''
    for line in lines(path):
        if re.match('###'+SPACE+'+M[0-9]+('+SPACE+'|$)',line):
            milestone=re.search('M[0-9]+',line).group(0)
            shipped[milestone]='shipped' if '✅' in line else ''
            continue
        if re.match('#{2,3}'+SPACE,line):
            milestone='';continue
        if milestone and line.startswith('**Done when:**'):continue
        if milestone and line.startswith('Delivered as '):
            rest=line
            while match:=re.search(LINK,rest):
                label=match.group(0)[1:5];target=re.sub(r'^.*\./design/','',match.group(0))[:4]
                if label!=target:errors.append(f'collapsed pointer in {milestone} names design {label} but links to design {target}')
                if shipped[milestone]!='shipped':errors.append(f'collapsed pointer for design {label} appears before {milestone} has shipped')
                delivered.append(label+US+milestone)
                rest=rest[match.end():]
            if re.search(r'\]\(\./design/',rest):errors.append(f'invalid collapsed design pointer in {milestone}: {line}')
            continue
        if not milestone:
            # An initiative outside every milestone belongs to no table and would vanish.
            if re.match(r'\|'+SPACE+'*`[a-z0-9-]+`'+SPACE+r'*\|',line):errors.append('initiative row outside any milestone: '+line)
            continue
        if not line.startswith('|'):continue
        if re.match(r'\|'+SPACE+'*Slug'+SPACE+r'*\|',line) or re.match(r'\|'+SPACE+'*-+'+SPACE+r'*\|',line):continue
        if shipped[milestone]=='shipped':
            errors.append(f'initiative row remains under shipped milestone {milestone}: {line}');continue
        if not re.match(r'\| `[a-z0-9]+(-[a-z0-9]+)*` \| ',line):
            errors.append(f'unrecognised row in {milestone}: {line}');continue
        cells=line.split('|')
        if len(cells)!=6:
            errors.append(f'row in {milestone} has {len(cells)-2} cells, expected 4 (an unescaped pipe?): {line}');continue
        slug=re.sub('[` ]','',cells[1]);depends=re.sub('[` ]','',cells[3]);design=cells[4].strip(WS)
        if depends=='—':depends=''
        if depends:
            for item in depends.split(','):
                if not re.fullmatch('[a-z0-9]+(-[a-z0-9]+)*|M[0-9]+',item):
                    errors.append(f'{slug} depends on "{item}", which is not a slug or a milestone id')
        if design=='—':design=''
        elif re.fullmatch(LINK,design):
            label=design[1:5];target=re.sub(r'^.*\./design/','',design)[:4]
            if label!=target:errors.append(f'{slug} names design {label} but links to design {target}')
            design=label
        else:
            errors.append(f'{slug} has an invalid design link: {design}');design=''
        rows.append(US.join((slug,milestone,depends,design)))
    if errors:
        raise Refused(f'roadmap.sh: cannot parse {path} — refusing to report a partial registry.\n'+''.join('  '+e+'\n' for e in errors))
    if mode=='--delivered':return ''.join(row+'\n' for row in delivered)
    if not rows and not any(re.match('###'+SPACE+'+M[0-9]+('+SPACE+'|$)',line) for line in lines(path)):
        raise Refused(f'roadmap.sh: {path} has no milestones. Nothing can be designed from it.\n')
    return ''.join(row+'\n' for row in rows) or '\n'


def freeze_render(root,doc,task=''):
    """The design document after task completes; with no task, after the design is finalized."""
    def fail(*messages):raise Refused(''.join('freeze.sh: '+m+'\n' if i==0 else m+'\n' for i,m in enumerate(messages)))
    if not re.fullmatch('[0-9]{4}',doc):raise Refused('usage: freeze.sh <four-digit-design-doc-number>\n')
    if task and not re.fullmatch('[0-9]+',task):fail('completion task must be numeric.')
    path=design_file(root,doc)
    if not path:fail(f'no design doc matching docs/design/{doc}-*.md')
    name=Path(path).name
    try:state=plan(root,doc).rstrip('\n')
    except Refused as exc:raise Refused(f'freeze.sh: {name} does not have a valid task list.\n'+captured(str(exc))) from None
    rows=[row.split(US) for row in state.split('\n')]
    kind=fm_value(path,'type');status=fm_value(path,'status');delivered=fm_value(path,'delivered')
    if kind!='design':fail(f"{name} has type '{kind or 'missing'}', not 'design'.")
    pending=[row[0] for row in rows if len(row)>1 and row[1]=='pending']
    tick=False
    if task:
        states=[row[1] for row in rows if len(row)>1 and number(row[0],task)]
        if not states:fail(f'no task {task} in {name}.')
        tick='\n'.join(states)=='pending'
    after=[row[0] for row in rows if len(row)>1 and row[1]=='pending' and not number(row[0],task)] if tick else pending
    if status=='approved' and delivered:
        fail(f'approved design doc {doc} already carries delivered: {delivered}.','Only a frozen design doc may claim delivery.')
    if status=='frozen' and pending:fail(f'frozen design doc {doc} still has pending tasks.')
    if status not in ('approved','frozen'):
        fail(f"design doc {doc} is '{status or 'missing a status'}', not 'approved'.",'Only an approved, complete design doc can be frozen.')
    freeze=status=='approved' and not after;milestone=''
    if freeze or status=='frozen':
        try:initiatives=roadmap(root)
        except Refused as exc:raise Refused('freeze.sh: the roadmap does not parse, so the delivering milestone is unknown.\n'+captured(str(exc))) from None
        milestones=[row[1] for row in (line.split(US) for line in initiatives.split('\n')) if len(row)>3 and row[3]==doc]
        try:collapsed=roadmap(root,'--delivered')
        except Refused as exc:raise Refused('freeze.sh: collapsed milestone pointers do not parse.\n'+captured(str(exc))) from None
        if status=='approved':
            if len(milestones)!=1:
                fail(f'design doc {doc} must be named by exactly one roadmap row; found {len(milestones)}.','The roadmap row is the authority for the delivering milestone.')
            milestone=milestones[0]
        else:
            if not milestones:
                pointers=[row[1] for row in (line.split(US) for line in collapsed.split('\n')) if len(row)>1 and row[0]==doc]
                if len(pointers)!=1 or delivered!=pointers[0]:
                    fail(f'frozen design doc {doc} has no matching roadmap row or collapsed milestone pointer.')
                milestone=delivered
            elif len(milestones)==1:milestone=milestones[0]
            else:fail(f'frozen design doc {doc} is named by {len(milestones)} roadmap rows; expected one.')
            if delivered!=milestone:
                fail(f"design doc {doc} says delivered: '{delivered or 'missing'}', but its roadmap record is in {milestone}.")
    if freeze:
        fields=frontmatter(path)
        if [sum(line.startswith(k) for line in fields) for k in ('status:','last-verified:','delivered:')]!=[1,1,0]:
            fail(f'{name} has ambiguous lifecycle frontmatter.','Expected one status, one last-verified, and no delivered field before freezing.')
    pending_marker=f'- [ ] **{task}.**';done_marker=f'- [x] **{task}.**'
    output=[];inside=False
    for index,line in enumerate(lines(path)):
        if index==0 and line=='---':inside=True;output.append(line);continue
        if inside and line=='---':inside=False;output.append(line);continue
        if freeze and inside and line.startswith('status:'):output+=['status: frozen','delivered: '+milestone];continue
        if freeze and inside and line.startswith('last-verified:'):output.append('last-verified: '+date.today().isoformat());continue
        if tick and line.startswith(pending_marker):output.append(done_marker+line[len(pending_marker):]);continue
        output.append(line)
    return ''.join(line+'\n' for line in output)
