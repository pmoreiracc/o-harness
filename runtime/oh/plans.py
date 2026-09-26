"""Roadmaps, design docs and decision records as plain documents in a project's plans location.

Models write prose; this module owns every structural edit (rows, numbers, links, logs), so no
table breaks and no two documents share a number. The formats follow Geoffrey's documents."""
from datetime import date
import os
from pathlib import Path
import re
from .design_parse import US, design_file, fm_value, link_prefix, lines, plan, roadmap
from .storage import Refused

SLUG = r'[a-z0-9]+(-[a-z0-9]+)*'
TABLE = ['| Slug | Initiative | Depends | Design |', '|---|---|---|---|']


def layout(root, location=None):
    """Where this project's plans live. Geoffrey's document profile keeps them in the repository."""
    from .config import load
    from .storage import project, state_home
    settings = load(root)['plans']
    location = location or settings['location']
    if location == 'ask' and project(root).get('design_profile') == 'consumer-v1':location = 'repo'
    if location == 'ask':
        raise Refused('Choose where plans live first: oh config set plans.location repo (committed, the merge approves '
                      'them) or private (OH\'s folder, nothing in the repository)')
    base = Path(root) if location == 'repo' else state_home() / 'projects' / project(root)['id'] / 'plans'
    return {'location': location, 'base': base, 'roadmap': base / settings['roadmap'],
            'designs': base / settings['designs'], 'decisions': base / settings['decisions']}


def write(path, text):
    import tempfile
    from .system import replace
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.oh-plan-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', newline='\n') as stream:stream.write(text)
        mask = os.umask(0);os.umask(mask);os.chmod(temporary, 0o666 & ~mask)
        replace(temporary, path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def initiatives(root, where):
    """{slug: (milestone, depends, design)} from the roadmap, refusing a roadmap that doesn't parse."""
    rows = roadmap(root, '', where).strip('\n')
    return {cells[0]: tuple(cells[1:]) for cells in (row.split(US) for row in rows.split('\n') if row)}


def milestones(where):
    """[(id, shipped)] in document order."""
    found = []
    for line in lines(where['roadmap']):
        match = re.match(r'###\s+(M[0-9]+)(\s|$)', line)
        if match:found.append((match[1], '✅' in line))
    return found


def start_roadmap(where, title):
    """A new, empty roadmap. Refuses to replace one."""
    if Path(where['roadmap']).exists():raise Refused(f'{where["roadmap"]} already exists')
    write(where['roadmap'], f'---\ntype: plan\nstatus: living\nlast-verified: {date.today().isoformat()}\n---\n\n'
          f'# {title} — Roadmap\n\nOne row is one initiative, the unit a design doc covers. **Depends** names only work '
          'that genuinely has to come first.\n')


def add_milestone(root, where, milestone, title, done_when):
    """Append an open milestone with its bar and an empty initiative table."""
    if not re.fullmatch(r'M[0-9]+', milestone):raise Refused(f"'{milestone}' is not a milestone id like M3")
    for text in (title, done_when):
        if not text.strip() or '\n' in text:raise Refused('Milestone title and "Done when" are one line each')
    if not Path(where['roadmap']).exists():raise Refused('Start the roadmap first')
    if milestones(where):initiatives(root, where)  # an existing roadmap must parse before it grows
    if milestone in [m for m, _ in milestones(where)]:raise Refused(f'The roadmap already has {milestone}')
    text = Path(where['roadmap']).read_text().rstrip('\n')
    write(where['roadmap'], text + f'\n\n---\n\n### {milestone} — {title.strip()}\n\n**Done when:** {done_when.strip()}\n\n'
          + '\n'.join(TABLE) + '\n')
    verify_roadmap(root, where)


def add_initiative(root, where, milestone, slug, text, depends):
    """Insert one initiative row as the last row of an open milestone's table (add-initiative.sh)."""
    if not re.fullmatch(r'M[0-9]+', milestone):raise Refused(f"'{milestone}' is not a milestone id")
    if not re.fullmatch(SLUG, slug):raise Refused(f"'{slug}' is not a kebab-case slug")
    if '|' in text or '\n' in text or not text.strip():raise Refused('The initiative text is one line without a pipe')
    existing = initiatives(root, where)
    if slug in existing:
        if existing[slug][0] == milestone:return {'unchanged': True}
        raise Refused(f"'{slug}' already exists, in {existing[slug][0]}. A slug is an identity; choose another")
    state = dict(milestones(where))
    if milestone not in state:raise Refused(f'The roadmap has no milestone {milestone}')
    if state[milestone]:raise Refused(f'{milestone} has already shipped. New work belongs in an open milestone')
    for item in depends:
        if item not in existing and not re.fullmatch(r'M[0-9]+', item):
            raise Refused(f"'{slug}' would depend on '{item}', which is neither a slug nor a milestone")
    cell = ', '.join(f'`{d}`' for d in depends) if depends else '—'
    rows, current, last = lines(where['roadmap']), '', None
    for index, line in enumerate(rows):
        match = re.match(r'###\s+(M[0-9]+)(\s|$)', line)
        if match:current = match[1];continue
        if re.match(r'#{2,3}\s', line):current = '';continue
        if current == milestone and line.startswith('|'):last = index
    if last is None:raise Refused(f'{milestone} has no initiative table')
    rows.insert(last + 1, f'| `{slug}` | {text.strip()} | {cell} | — |')
    before = Path(where['roadmap']).read_text()
    write(where['roadmap'], '\n'.join(rows) + '\n')
    try:verify_roadmap(root, where)
    except Refused:
        write(where['roadmap'], before);raise
    return {'added': slug, 'milestone': milestone}


def claim(root, where, slug, number):
    """Fill an initiative's design cell with its design doc (claim.sh)."""
    existing = initiatives(root, where)
    if slug not in existing:raise Refused(f"No initiative '{slug}' in the roadmap")
    if existing[slug][2] == number:return {'unchanged': True}
    if existing[slug][2]:raise Refused(f"'{slug}' already names design doc {existing[slug][2]}")
    path = design_file(root, number, where)
    if not path:raise Refused(f'No design doc {number}')
    link = f'[{number}]({link_prefix(root, where)}{Path(path).name})'
    rows = lines(where['roadmap']);changed = 0
    for index, line in enumerate(rows):
        if line.startswith(f'| `{slug}` |'):
            cells = line.split('|')
            if cells[4].strip() != '—':raise Refused(f"'{slug}' row has an unexpected design cell")
            cells[4] = f' {link} ';rows[index] = '|'.join(cells);changed += 1
    if changed != 1:raise Refused(f"Expected one row for '{slug}', found {changed}")
    write(where['roadmap'], '\n'.join(rows) + '\n')
    verify_roadmap(root, where)
    return {'claimed': slug, 'design': number}


def next_number(folder):
    numbers = [int(p.name[:4]) for p in Path(folder).glob('[0-9][0-9][0-9][0-9]-*.md')]
    return f'{max(numbers, default=0) + 1:04}'


def write_design(root, where, slug, title, body, status='approved'):
    """A new design doc, numbered after the last one. `body` is everything after the title."""
    if not re.fullmatch(SLUG, slug):raise Refused(f"'{slug}' is not a kebab-case slug")
    if '\n' in title or not title.strip():raise Refused('The design title is one line')
    number = next_number(where['designs'])
    path = Path(where['designs']) / f'{number}-{slug}.md'
    write(path, f'---\ntype: design\nstatus: {status}\nlast-verified: {date.today().isoformat()}\n---\n\n'
          f'# {number} — {title.strip()}\n\n{body.strip()}\n')
    return number, path


def write_decision(root, where, title, context, alternatives, consequences, decision=''):
    """A decision record. Without a decision it is proposed, with its Decision left for the human."""
    if '\n' in title or not title.strip() or '|' in title:raise Refused('The decision title is one line without a pipe')
    folder = Path(where['decisions']);number = next_number(folder)
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:60].strip('-') or 'decision'
    status = 'accepted' if decision.strip() else 'proposed'
    today = date.today().isoformat()
    write(folder / f'{number}-{slug}.md', f'---\ntype: decision\nstatus: {status}\ndate: {today}\n---\n\n'
          f'# ADR-{number} — {title.strip()}\n\n## Context\n\n{context.strip()}\n\n## Decision\n\n'
          f'{decision.strip() or "_Not decided yet. This record states the question and its alternatives for a human decision._"}\n\n'
          f'## Alternatives considered\n\n{alternatives.strip()}\n\n## Consequences\n\n{consequences.strip()}\n')
    log = folder / 'README.md'
    row = f'| [{number}](./{number}-{slug}.md) | {title.strip()} | {today} | {status} |'
    if not log.exists():
        write(log, '# Decisions\n\nWhy things are the way they are. A decision is never edited once accepted; a new one '
              'supersedes it.\n\n## The log\n\n| # | Decision | Date | Status |\n|---|---|---|---|\n' + row + '\n')
    else:
        rows = lines(log)
        last = max((i for i, line in enumerate(rows) if re.match(r'\| \[[0-9]{4}\]', line)), default=None)
        if last is None:
            header = next((i for i, line in enumerate(rows) if line.startswith('| # |')), None)
            if header is None:raise Refused(f'{log} has no decision log table')
            last = header + 1
        rows.insert(last + 1, row);write(log, '\n'.join(rows) + '\n')
    return number, folder / f'{number}-{slug}.md'


def verify_roadmap(root, where):
    """The mechanical half of the roadmap rules (verify-roadmap.sh); judgement stays with the reviewer."""
    rows = initiatives(root, where)  # parses, or refuses
    problems, found = [], milestones(where)
    ids = [m for m, _ in found]
    problems += [f'duplicate milestone id {m}' for m in sorted({m for m in ids if ids.count(m) > 1})]
    text, current, bars = lines(where['roadmap']), None, {}
    for line in text:
        match = re.match(r'###\s+(M[0-9]+)(\s|$)', line)
        if match:current = match[1];bars.setdefault(current, False);continue
        if re.match(r'#{2,3}\s', line):current = None;continue
        if current and line.startswith('**Done when:**'):bars[current] = True
    problems += [f'{m} has no "Done when:"' for m, shipped in found if not shipped and not bars.get(m)]
    for slug, (_, depends, design) in rows.items():
        for item in filter(None, depends.split(',')):
            if item not in rows and item not in ids:problems.append(f'{slug} depends on {item}, which is neither a slug nor a milestone')
        if design and not design_file(root, design, where):problems.append(f'{slug} names design doc {design}, which does not exist')
    graph = {s: [d for d in filter(None, v[1].split(',')) if d in rows] for s, v in rows.items()}
    if cyclic(graph):problems.append('the initiative dependencies form a cycle: ' + ' '.join(sorted(cyclic(graph))))
    if problems:raise Refused('The roadmap breaks its rules:\n' + ''.join(f'  {p}\n' for p in problems))
    return {'initiatives': len(rows), 'milestones': len(ids)}


def cyclic(graph):
    """Nodes left after repeatedly removing those with no remaining dependencies."""
    remaining = dict(graph)
    while True:
        free = [n for n, needs in remaining.items() if not [d for d in needs if d in remaining]]
        if not free:return set(remaining)
        for n in free:remaining.pop(n)


def verify_design(root, where, number=None):
    """Whether design docs can be delivered (verify-design.sh): structure, not editorial quality."""
    folder, problems = Path(where['designs']), []
    docs = sorted(folder.glob('*.md')) if folder.exists() else []
    docs = [d for d in docs if d.name.lower() != 'readme.md']
    for doc in docs:
        if not re.fullmatch(r'[0-9]{4}-' + SLUG + r'\.md', doc.name):problems.append(f'{doc.name} is not named NNNN-<slug>.md')
    numbers = [d.name[:4] for d in docs]
    problems += [f'two design docs share number {n}' for n in sorted({n for n in numbers if numbers.count(n) > 1})]
    rows = initiatives(root, where) if Path(where['roadmap']).exists() else {}
    named = {v[2] for v in rows.values() if v[2]}
    for doc in docs:
        n = doc.name[:4]
        if number and n != number:continue
        status = fm_value(str(doc), 'status')
        try:tasks = [row.split(US) for row in plan(root, n, where).strip('\n').split('\n')]
        except Refused as exc:problems.append(f'{doc.name} does not parse: {str(exc).strip()}');continue
        ids = {t[0] for t in tasks}
        for task, _, _, needs, blocked, _ in tasks:
            for need in filter(None, needs.split(',')):
                if need not in ids:problems.append(f'{doc.name}: task {task} depends on task {need}, which does not exist')
            if blocked:
                section = re.fullmatch(r'§([0-9]+)', blocked)
                heading = section and next((line for line in lines(doc) if re.match(rf'## {section[1]}\.\s', line)), None)
                if not section:problems.append(f'{doc.name}: task {task} is blocked on "{blocked}", not a section like §5')
                elif not heading:problems.append(f'{doc.name}: task {task} is blocked on §{section[1]}, which the doc lacks')
                elif 'Open' not in heading:problems.append(f'{doc.name}: task {task} is blocked on §{section[1]}, which is not an open-questions section')
        if cyclic({t[0]: [d for d in filter(None, t[3].split(',')) if d in ids] for t in tasks}):
            problems.append(f'{doc.name}: task dependencies form a cycle')
        pending = [t[0] for t in tasks if t[1] == 'pending']
        if status == 'frozen' and pending:problems.append(f'{doc.name} is frozen with pending tasks: {" ".join(pending)}')
        if status == 'approved' and rows and n not in named:problems.append(f'{doc.name} is approved but no roadmap row names it')
        if status not in ('approved', 'frozen', 'draft'):problems.append(f"{doc.name} has status '{status or 'missing'}'")
    if problems:raise Refused('Design docs break their rules:\n' + ''.join(f'  {p}\n' for p in problems))
    return {'designs': len(docs)}


def check(root, where=None):
    """Every mechanical rule for the plans a project has."""
    where = where or layout(root)
    result = {'location': where['location']}
    if Path(where['roadmap']).exists():result.update(verify_roadmap(root, where))
    if Path(where['designs']).exists():result.update(verify_design(root, where))
    return result
