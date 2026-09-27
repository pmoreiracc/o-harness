"""Roadmaps, design docs and decision records as plain documents in a project's plans location.

Models write prose; this module owns every structural edit (rows, numbers, links, logs). Adding a
milestone, an initiative, a claim, a design doc or a decision is all or nothing: if a document would
break a rule afterwards, every file the edit touched is put back byte for byte."""
import contextlib
from datetime import date
import os
from pathlib import Path
import re
from .design_parse import US, design_file, lines, link_prefix, plan, roadmap
from .storage import Refused

SLUG = r'[a-z0-9]+(-[a-z0-9]+)*'
TABLE = ['| Slug | Initiative | Depends | Design |', '|---|---|---|---|']
WS = '[ \t\n\r\f\v]'  # ASCII whitespace, as the shared parser reads it (C locale)
MILESTONE = re.compile(r'###' + WS + r'+(M[0-9]+)(' + WS + '|$)')
DEFAULTS = {'roadmap': 'docs/roadmap.md', 'designs': 'docs/design', 'decisions': 'docs/decisions'}


def layout(root, location=None):
    """Where this project's plans live. The consumer-v1 document profile keeps them in the repository."""
    from .config import load
    from .storage import project, state_home
    settings = load(root)['plans']
    location = location or settings['location']
    if project(root).get('design_profile') == 'consumer-v1':
        # Delivery of that profile reads docs/design in the repository; plans can't live anywhere else.
        if location not in ('ask', 'repo') or any(settings[k] != v for k, v in DEFAULTS.items()):
            raise Refused('This project uses the consumer-v1 document profile, whose plans live in the repository at '
                          'docs/roadmap.md, docs/design and docs/decisions; keep the default plans settings')
        location = 'repo'
    if location == 'ask':
        raise Refused('Choose where plans live first: oh config set plans.location repo (committed in the repository) '
                      'or private (OH\'s folder, nothing in the repository)')
    base = Path(root) if location == 'repo' else state_home() / 'projects' / project(root)['id'] / 'plans'
    where = {'location': location, 'base': base, 'roadmap': base / settings['roadmap'],
             'designs': base / settings['designs'], 'decisions': base / settings['decisions']}
    def folded(path):return Path(os.path.realpath(path).casefold())  # case-insensitive file systems share folders
    designs, decisions = folded(where['designs']), folded(where['decisions'])
    if designs.is_relative_to(decisions) or decisions.is_relative_to(designs):
        raise Refused('plans.designs and plans.decisions overlap; give design docs and decisions separate folders')
    for key in ('designs', 'decisions'):
        if folded(where['roadmap'].parent).is_relative_to(folded(where[key])):
            raise Refused(f'plans.roadmap is inside plans.{key}; keep the roadmap outside the numbered folders')
    return where


def one_line(text, what):
    """A single line of text: no line break of any kind, which Markdown or the parser would split on."""
    if not isinstance(text, str) or not text.strip() or len(text.splitlines()) != 1 or '\x1f' in text:
        raise Refused(f'{what} must be one non-empty line')
    return text.strip()


def raw(path):
    return Path(path).read_bytes() if Path(path).exists() else None


def rows_of(path):
    """A document's lines without line endings, and the line ending most of its lines use."""
    try:data = Path(path).read_bytes().decode()
    except UnicodeDecodeError:raise Refused(f'{Path(path).name} is not valid UTF-8') from None
    rows = data.split('\n')
    rows = rows[:-1] if rows[-1] == '' else rows
    crlf = sum(r.endswith('\r') for r in rows)
    return [r[:-1] if r.endswith('\r') else r for r in rows], '\r\n' if crlf * 2 > len(rows) else '\n'


def fenced(rows):
    """For each line, whether it belongs to a fenced code block (CommonMark: a closing fence uses the
    opener's character, is at least as long, and has nothing after it)."""
    result, opener = [], None
    for line in rows:
        marker = re.match(r' {0,3}(`{3,}|~{3,})(.*)$', line)
        if opener is None:
            if marker and not (marker[1][0] == '`' and '`' in marker[2]):
                opener = marker[1];result.append(True);continue
            result.append(False)
        else:
            result.append(True)
            if marker and marker[1][0] == opener[0] and len(marker[1]) >= len(opener) and not marker[2].strip():opener = None
    return result


def outside(rows):
    """(index, line) for lines outside fenced code blocks."""
    return [(i, line) for (i, line), inside in zip(enumerate(rows), fenced(rows)) if not inside]


def write(path, text):
    import tempfile
    from .system import replace
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.oh-plan-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:stream.write(text.encode() if isinstance(text, str) else text)
        mask = os.umask(0);os.umask(mask);os.chmod(temporary, 0o666 & ~mask)
        replace(temporary, path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def write_rows(path, rows, ending):
    write(path, ending.join(rows) + ending)


@contextlib.contextmanager
def all_or_nothing(*paths):
    """Restore every listed file (or its absence) byte for byte if the edit fails."""
    from .storage import snapshot_guard, state_home
    # Plans in OH's folder are OH state: hold the state guard so a backup never sees half an edit.
    guard = snapshot_guard() if any(Path(p).resolve().is_relative_to(state_home().resolve()) for p in paths) else contextlib.nullcontext()
    with guard:
        before = {Path(p): raw(p) for p in paths}
        try:yield
        except BaseException:
            for path, data in before.items():
                if data is None:path.unlink(missing_ok=True)
                else:write(path, data)
            raise


def initiatives(root, where):
    """[(slug, milestone, depends, design)] from the roadmap in document order, refusing one that doesn't parse.
    The shared parser (design_parse, from the former roadmap.sh) reads code blocks too, so a fenced milestone heading, or a fenced
    heading, row or bar inside a milestone, is refused. Structure is read from the parser's own raw lines."""
    if not Path(where['roadmap']).is_file():raise Refused('Start the roadmap first')
    rows_all, section = lines(where['roadmap']), None
    for (index, line), inside in zip(enumerate(rows_all), fenced(rows_all)):
        # Follow the parser's own section state: inside a milestone it reads headings, rows and bars.
        heading, milestone = re.match(r'#{2,3}' + WS, line), MILESTONE.match(line)
        name = f'{where["roadmap"].name} line {index + 1}'
        if inside and milestone:raise Refused(f'{name} is in a code block but reads as a milestone heading; indent or reword it')
        if inside and section and (heading or line.startswith(('|', '**Done when:**', 'Delivered as '))):
            raise Refused(f'{name} is in a code block inside milestone {section} but reads as roadmap structure; '
                          'move it out of the milestone, or indent it')
        section = milestone[1] if milestone else (None if heading else section)
    rows = roadmap(root, '', where).strip('\n')
    return [tuple(row.split(US)) for row in rows.split('\n') if row]


def milestones(where):
    """[(id, shipped)] in document order."""
    return [(match[1], '✅' in line) for _, line in outside(lines(where['roadmap'])) if (match := MILESTONE.match(line))]


def start_roadmap(where, title):
    """A new, empty roadmap. Refuses to replace one."""
    title = one_line(title, 'The roadmap title')
    if title.startswith('#'):raise Refused('The roadmap title can\'t start with #')
    if Path(where['roadmap']).exists():raise Refused(f'{where["roadmap"]} already exists')
    with all_or_nothing(where['roadmap']):write(where['roadmap'], f'---\ntype: plan\nstatus: living\nlast-verified: {date.today().isoformat()}\n---\n\n'
          f'# {title} — Roadmap\n\nOne row is one initiative, the unit a design doc covers. **Depends** names only work '
          'that genuinely has to come first.\n')


def add_milestone(root, where, milestone, title, done_when):
    """Add an open milestone, with its bar and an empty initiative table, after the last milestone."""
    if not re.fullmatch(r'M[0-9]+', milestone):raise Refused(f"'{milestone}' is not a milestone id like M3")
    title, done_when = one_line(title, 'The milestone title'), one_line(done_when, '"Done when"')
    if '✅' in title:raise Refused('A new milestone is open; its title can\'t carry ✅')
    if not Path(where['roadmap']).exists():raise Refused('Start the roadmap first')
    if milestones(where):initiatives(root, where)  # an existing roadmap must parse before it grows
    if milestone in [m for m, _ in milestones(where)]:raise Refused(f'The roadmap already has {milestone}')
    rows, ending = rows_of(where['roadmap'])
    visible = outside(rows)
    starts = [i for i, line in visible if MILESTONE.match(line)]
    # After the last milestone's section, before the next level-2 heading such as "Deliberately deferred";
    # the first milestone goes before the first level-2 heading after the title.
    after = starts[-1] if starts else next((i for i, line in visible if re.match(r'#' + WS, line)), -1)
    at = next((i for i, line in visible if i > after and re.match(r'##' + WS, line)), len(rows))
    front = next((i for i in range(1, len(rows)) if rows[i] == '---'), -1) if rows and rows[0] == '---' else -1
    while at > max(after, front) + 1 and rows[at - 1].strip() in ('', '---'):at -= 1
    block = ['', '---', '', f'### {milestone} — {title}', '', f'**Done when:** {done_when}', '', *TABLE]
    block += [''] if at < len(rows) and rows[at].strip() else []
    with all_or_nothing(where['roadmap']):
        write_rows(where['roadmap'], rows[:at] + block + rows[at:], ending)
        verify_roadmap(root, where)
    return {'added': milestone}


def add_initiative(root, where, milestone, slug, text, depends):
    """Insert one initiative row as the last row of an open milestone's table (add-initiative.sh)."""
    if not re.fullmatch(r'M[0-9]+', milestone):raise Refused(f"'{milestone}' is not a milestone id")
    if not re.fullmatch(SLUG, slug):raise Refused(f"'{slug}' is not a kebab-case slug")
    text = one_line(text, 'The initiative text')
    if '|' in text:raise Refused('The initiative text can\'t contain a pipe')
    existing = initiatives(root, where)
    found = [row[1] for row in existing if row[0] == slug]
    if found:
        if found == [milestone]:return {'unchanged': True}
        raise Refused(f"'{slug}' already exists, in {found[0]}. A slug is an identity; choose another")
    state = dict(milestones(where))
    if milestone not in state:raise Refused(f'The roadmap has no milestone {milestone}')
    if state[milestone]:raise Refused(f'{milestone} has already shipped. New work belongs in an open milestone')
    for item in depends:
        if item not in [row[0] for row in existing] and item not in state:
            raise Refused(f"'{slug}' would depend on '{item}', which is neither a slug nor a milestone")
    cell = ', '.join(f'`{d}`' for d in depends) if depends else '—'
    rows, ending = rows_of(where['roadmap'])
    current, last = '', None
    for index, line in outside(rows):
        match = MILESTONE.match(line)
        if match:current = match[1];continue
        if re.match(r'#{2,3}' + WS, line):current = '';continue
        if current == milestone and line.startswith('|'):last = index
    if last is None:raise Refused(f'{milestone} has no initiative table')
    rows.insert(last + 1, f'| `{slug}` | {text} | {cell} | — |')
    with all_or_nothing(where['roadmap']):
        write_rows(where['roadmap'], rows, ending)
        verify_roadmap(root, where)
    return {'added': slug, 'milestone': milestone}


def claim(root, where, slug, number):
    """Fill an initiative's design cell with its design doc (claim.sh)."""
    if not re.fullmatch(r'[0-9]{4}', number):raise Refused(f"'{number}' is not a four-digit design number")
    existing = [row for row in initiatives(root, where) if row[0] == slug]
    if len(existing) != 1:raise Refused(f"Expected one initiative '{slug}' in the roadmap, found {len(existing)}")
    if existing[0][3] == number:return {'unchanged': True}
    if existing[0][3]:raise Refused(f"'{slug}' already names design doc {existing[0][3]}")
    path = design_file(root, number, where)
    if not path or not re.fullmatch(number + '-' + SLUG + r'\.md', Path(path).name):raise Refused(f'No design doc {number}-<slug>.md')
    rows, ending = rows_of(where['roadmap']);changed = 0
    for index, line in outside(rows):
        if line.startswith(f'| `{slug}` |'):
            cells = line.split('|')
            if len(cells) != 6 or cells[4].strip() != '—':raise Refused(f"'{slug}' row has an unexpected design cell")
            cells[4] = f' [{number}]({link_prefix(root, where)}{Path(path).name}) ';rows[index] = '|'.join(cells);changed += 1
    if changed != 1:raise Refused(f"Expected one row for '{slug}', found {changed}")
    with all_or_nothing(where['roadmap']):
        write_rows(where['roadmap'], rows, ending)
        verify_roadmap(root, where)
    return {'claimed': slug, 'design': number}


def next_number(folder):
    numbers = [int(p.name[:4]) for p in Path(folder).glob('[0-9][0-9][0-9][0-9]-*.md')]
    if max(numbers, default=0) >= 9999:raise Refused(f'{folder} has used every four-digit number')
    return f'{max(numbers, default=0) + 1:04}'


def write_design(root, where, slug, title, body, status):
    """A new design doc, numbered after the last one. `body` is everything after the title.
    The caller decides the status: approval is a merge or a human gate, never this function."""
    if not re.fullmatch(SLUG, slug):raise Refused(f"'{slug}' is not a kebab-case slug")
    if status not in ('draft', 'approved'):raise Refused('A new design doc is a draft or approved')
    title = one_line(title, 'The design title')
    number = next_number(where['designs'])
    path = Path(where['designs']) / f'{number}-{slug}.md'
    with all_or_nothing(path):
        write(path, f'---\ntype: design\nstatus: {status}\nlast-verified: {date.today().isoformat()}\n---\n\n'
              f'# {number} — {title}\n\n{body.strip()}\n')
        verify_design(root, where, number, orphans=False)  # the roadmap names it only after claim
    return number, path


def write_decision(root, where, title, context, alternatives, consequences, decision='', recommendation=''):
    """A decision record plus its log row. Without a decision it is proposed, its Decision left to a human, with the
    proposer's recommendation when there is one."""
    title = one_line(title, 'The decision title')
    if '|' in title:raise Refused('The decision title can\'t contain a pipe')
    folder = Path(where['decisions']);number = next_number(folder)
    slug = decision_slug(title)
    status = 'accepted' if decision.strip() else 'proposed'
    today = date.today().isoformat()
    path, log = folder / f'{number}-{slug}.md', folder / 'README.md'
    row = f'| [{number}](./{number}-{slug}.md) | {title} | {today} | {status} |'
    if log.exists():
        rows, ending = rows_of(log)
        visible = outside(rows)
        log_heading = next((i for i, line in visible if re.match(r'##' + WS + r'+The log' + WS + '*$', line)), -1)
        headers = [i for i, line in visible if re.match(r'\|\s*#\s*\|\s*Decision\s*\|', line)]
        header = next((i for i in headers if i > log_heading), headers[0] if headers else None)
        if header is None:raise Refused(f'{log} has no decision log table (a "| # | Decision | Date | Status |" header)')
        end = header + 1
        while end + 1 < len(rows) and rows[end + 1].startswith('|'):end += 1
        rows.insert(end + 1, row)
    else:
        rows, ending = ['# Decisions', '', 'Why things are the way they are. A decision is never edited once accepted; '
                        'a new one supersedes it.', '', '## The log', '', '| # | Decision | Date | Status |', '|---|---|---|---|', row], '\n'
    with all_or_nothing(path, log):
        write(path, f'---\ntype: decision\nstatus: {status}\ndate: {today}\n---\n\n'
              f'# ADR-{number} — {title}\n\n## Context\n\n{context.strip()}\n\n## Decision\n\n'
              f'{decision.strip() or "_Not decided yet. This record states the question and its alternatives for a human decision._"}\n\n'
              + (f'## Recommendation\n\n{recommendation.strip()}\n\n' if recommendation.strip() and not decision.strip() else '') +
              f'## Alternatives considered\n\n{alternatives.strip()}\n\n## Consequences\n\n{consequences.strip()}\n')
        write_rows(log, rows, ending)
    return number, path


def verify_roadmap(root, where):
    """The mechanical half of the roadmap rules (verify-roadmap.sh); judgement stays with the reviewer."""
    rows = initiatives(root, where)  # parses, or refuses
    problems, found = [], milestones(where)
    ids = [m for m, _ in found]
    slugs = [row[0] for row in rows]
    problems += [f'duplicate slug {s}' for s in sorted({s for s in slugs if slugs.count(s) > 1})]
    problems += [f'duplicate milestone id {m}' for m in sorted({m for m in ids if ids.count(m) > 1})]
    current, bars = None, {}
    for _, line in outside(lines(where['roadmap'])):
        match = MILESTONE.match(line)
        if match:current = match[1];bars.setdefault(current, False);continue
        if re.match(r'#{2,3}' + WS, line):current = None;continue
        if current and line.startswith('**Done when:**'):bars[current] = True
    problems += [f'{m} has no "Done when:"' for m, shipped in found if not shipped and not bars.get(m)]
    graph = {}
    for slug, milestone, depends, design in rows:
        edges = graph.setdefault(slug, set())
        for item in filter(None, depends.split(',')):
            if item in slugs:edges.add(item)
            elif item in ids:edges.update(s for s, m, _, _ in rows if m == item)  # waits for the whole milestone
            else:problems.append(f'{slug} depends on {item}, which is neither a slug nor a milestone')
        if design and not design_file(root, design, where):problems.append(f'{slug} names design doc {design}, which does not exist')
    if cyclic(graph):problems.append('the initiative dependencies form a cycle: ' + ' '.join(sorted(cyclic(graph))))
    if problems:raise Refused('The roadmap breaks its rules:\n' + ''.join(f'  {p}\n' for p in problems))
    return {'initiatives': len(rows), 'milestones': len(ids)}


def cyclic(graph):
    """Nodes left after repeatedly removing those whose dependencies are all removed."""
    remaining = {node: set(edges) for node, edges in graph.items()}
    while True:
        free = [n for n, needs in remaining.items() if not needs & remaining.keys()]
        if not free:return set(remaining)
        for n in free:remaining.pop(n)


def headings(path):
    """Level-2 headings outside fenced code blocks."""
    return [line for _, line in outside(rows_of(path)[0]) if line.startswith('## ')]


def status_of(path):
    """A document's frontmatter status, whatever its line endings."""
    rows = rows_of(path)[0]
    if not rows or rows[0] != '---':return ''
    for line in rows[1:]:
        if re.match('---' + WS + '*$', line):break
        if line.startswith('status:'):return re.sub(WS + '*$', '', re.sub('^status:' + WS + '*', '', line, count=1))
    return ''


def verify_design(root, where, number=None, orphans=True):
    """Whether approved and frozen design docs can be delivered (verify-design.sh): structure, not editorial
    quality. Drafts may have loose ends, and abandoned docs are records."""
    folder, problems = Path(where['designs']), []
    docs = [d for d in (sorted(folder.glob('*.md')) if folder.exists() else []) if d.name.lower() != 'readme.md']
    wellformed = [d for d in docs if re.fullmatch(r'[0-9]{4}-' + SLUG + r'\.md', d.name)]
    numbers = [d.name[:4] for d in wellformed]
    if number is None:  # one doc's check (e.g. while writing it) never fails on its neighbours
        problems += [f'{d.name} is not named NNNN-<slug>.md' for d in docs if d not in wellformed]
        problems += [f'two design docs share number {n}' for n in sorted({n for n in numbers if numbers.count(n) > 1})]
    elif numbers.count(number) > 1:problems.append(f'two design docs share number {number}')
    has_roadmap = Path(where['roadmap']).exists()
    named = {row[3] for row in initiatives(root, where) if row[3]} if orphans and has_roadmap else set()
    for doc in wellformed:
        n = doc.name[:4]
        if number and n != number:continue
        status = status_of(doc)
        if status not in ('draft', 'approved', 'frozen', 'abandoned'):
            problems.append(f"{doc.name} has status '{status or 'missing'}'");continue
        if status in ('draft', 'abandoned'):continue
        try:tasks = [row.split(US) for row in plan(root, n, where).strip('\n').split('\n')]
        except Refused as exc:problems.append(f'{doc.name} does not parse: {str(exc).strip()}');continue
        if any(len(t) != 6 for t in tasks):problems.append(f'{doc.name} does not parse: a task title contains a control character');continue
        ids = {t[0] for t in tasks}
        sections = headings(doc)
        for task, _, _, needs, blocked, _ in tasks:
            for need in filter(None, needs.split(',')):
                if need not in ids:problems.append(f'{doc.name}: task {task} depends on task {need}, which does not exist')
            if blocked:
                section = re.fullmatch(r'§([0-9]+)', blocked)
                heading = section and next((h for h in sections if re.match(rf'## {section[1]}\.' + WS, h)), None)
                if not section:problems.append(f'{doc.name}: task {task} is blocked on "{blocked}", not a section like §5')
                elif not heading:problems.append(f'{doc.name}: task {task} is blocked on §{section[1]}, which the doc lacks')
                elif not re.match(rf'## {section[1]}\.' + WS + '+Open', heading):
                    problems.append(f'{doc.name}: task {task} is blocked on §{section[1]}, which is not an open-questions section')
        if cyclic({t[0]: {d for d in t[3].split(',') if d in ids} for t in tasks}):
            problems.append(f'{doc.name}: task dependencies form a cycle')
        pending = [t[0] for t in tasks if t[1] == 'pending']
        if status == 'frozen' and pending:problems.append(f'{doc.name} is frozen with pending tasks: {" ".join(pending)}')
        if status == 'approved' and not pending:problems.append(f'{doc.name} is approved but every task is done; finalize it')
        if orphans and status == 'approved' and has_roadmap and n not in named:problems.append(f'{doc.name} is approved but no roadmap row names it')
    if problems:raise Refused('Design docs break their rules:\n' + ''.join(f'  {p}\n' for p in problems))
    return {'designs': len(docs)}


def check(root, where=None):
    """Every mechanical rule for the plans a project has."""
    where = where or layout(root)
    result = {'location': where['location']}
    if Path(where['roadmap']).exists():result.update(verify_roadmap(root, where))
    if Path(where['designs']).exists():result.update(verify_design(root, where))
    return result


class Blocked(Refused):
    """A problem the worker can't fix (the checkout, the settings or the roadmap itself): it stops the run with its
    reason instead of going back to the worker as feedback."""


def blocked(action):
    try:return action()
    except Blocked:raise
    except Refused as exc:raise Blocked(str(exc)) from None


def editing(root):
    """One plan edit at a time per project, whichever checkout it runs in."""
    from .storage import lock, project, state_home
    return lock(state_home() / 'projects' / project(root)['id'] / 'plans.lock')


def initiative(root, where, slug):
    """The roadmap row a design covers: its milestone, text and dependencies. It must not name a design yet."""
    if not isinstance(slug, str) or not re.fullmatch(SLUG, slug):
        raise Refused('Name one roadmap initiative by its slug: /oh-design <slug>. New ideas start with /oh-propose')
    rows = initiatives(root, where)
    found = [row for row in rows if row[0] == slug]
    if not found:
        free = [row[0] for row in rows if not row[3]]
        raise Refused(f"The roadmap has no initiative '{slug}'." + (f' Initiatives without a design: {", ".join(free)}.' if free else '')
                      + ' New work starts with /oh-propose')
    _, milestone, depends, design = found[0]
    if design:
        raise Refused(f"'{slug}' already has design doc {design} ({design_file(root, design, where)}); edit that doc instead")
    text = next(line.split('|')[2].strip() for _, line in outside(rows_of(where['roadmap'])[0]) if line.startswith(f'| `{slug}` |'))
    return {'slug': slug, 'milestone': milestone, 'text': text, 'depends': [d for d in depends.split(',') if d]}


def design_manifest(root, slug):
    """The run that designs one roadmap initiative, and the plan settings only OH may give it. Code finds the row;
    the worker writes only prose."""
    where = layout(root)
    if where['location'] != 'repo':
        raise Refused('/oh-design writes plans in the repository for now; private plans get their approval step in a coming '
                      'update. Use oh config set plans.location repo, or wait for that update')
    row = initiative(root, where, slug)
    try:verify_roadmap(root, where)
    except Refused as exc:raise Refused(f'Fix the roadmap first. {exc}') from None
    planned = [Path(where['designs']) / f'{next_number(where["designs"])}-{slug}.md', Path(where['roadmap'])]
    if (skipped := ignored(root, [Path(p).relative_to(root).as_posix() for p in planned])):
        raise Refused(f'Git ignores {", ".join(skipped)}; plans in the repository must be committed')
    shown = {key: Path(where[key]).relative_to(root).as_posix() for key in ('roadmap', 'designs', 'decisions')}
    instructions = (f"Design the roadmap initiative `{slug}` in milestone {row['milestone']}: {row['text']}\n"
                    f"It depends on: {', '.join(row['depends']) or 'nothing'}.\n"
                    f"Roadmap: {shown['roadmap']}. Design docs: {shown['designs']}/. Decision records: {shown['decisions']}/.")
    return ({'workflow': 'design', 'tasks': [{'id': 'design', 'title': f'Design {slug}', 'instructions': instructions,
                                              'transition': {'profile': 'plans', 'slug': slug}}]},
            {'workflow': 'design', 'plans': {'location': 'repo'}, 'slug': slug})


def branch_for(root, slug, run, kind='design'):
    """<kind>/<slug>; <kind>-<slug> when a branch named <kind> exists (Git can't have both); a run-specific
    name when that is taken too."""
    import subprocess
    def exists(name):
        return subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', '--quiet', 'refs/heads/' + name], capture_output=True).returncode == 0
    def nested(name):  # design/auth can't exist beside design/auth/v2
        return bool(subprocess.run(['git', '-C', str(root), 'for-each-ref', '--format=%(refname)', f'refs/heads/{name}/'], capture_output=True, text=True).stdout.strip())
    name = f'{kind}-{slug}' if exists(kind) else f'{kind}/{slug}'
    return f'{name}-{run[:8]}' if exists(name) or nested(name) else name


TITLE_CHARS, SUMMARY_CHARS = 150, 1000


def answer(value):
    """The design worker's answer, checked. It carries prose only: OH adds numbers, frontmatter and links."""
    from .hosts import DESIGN_SCHEMA
    fields = DESIGN_SCHEMA['required']
    if not isinstance(value, dict) or set(value) != set(fields) or any(not isinstance(value[k], str) for k in fields):
        raise Refused('The answer must be the JSON object the output schema describes, with every field a string')
    if value['kind'] not in ('design', 'decision'):raise Refused("kind must be 'design' or 'decision'")
    one_line(value['title'], 'The title')
    if len(value['title'].strip()) > TITLE_CHARS:raise Refused(f'The title is longer than {TITLE_CHARS} characters')
    if len(value['summary'].strip()) > SUMMARY_CHARS:raise Refused(f'The summary is longer than {SUMMARY_CHARS} characters')
    needed = ('body',) if value['kind'] == 'design' else ('context', 'alternatives', 'consequences')
    missing = [k for k in needed if not value[k].strip()]
    if missing:raise Refused(f"A {value['kind']} needs {', '.join(missing)}")
    if value['kind'] == 'decision' and '|' in value['title']:raise Refused('A decision title cannot contain |')
    if value['kind'] == 'design' and any(re.match(r'#' + WS, line) for _, line in outside(value['body'].split('\n'))):
        raise Refused('The body starts below the title: use ## sections, not a # heading')
    return value


def changes(root):
    """Paths Git sees as changed or untracked in the checkout."""
    import subprocess
    output = subprocess.run(['git', '-C', str(root), 'status', '--porcelain=v1', '-z', '--untracked-files=all'],
                            capture_output=True, check=True).stdout.decode().split('\0')
    paths, skip = [], False
    for entry in output:
        if skip or not entry:skip = False;continue
        paths.append(entry[3:]);skip = entry[0] in 'RC'  # a rename or copy is followed by its old path
    return paths


def ignored(root, relative):
    """Which new paths Git ignores, so a commit would miss them. Tracked files are committed even when a pattern
    matches them; exit status 1 means none is ignored."""
    import subprocess
    found = subprocess.run(['git', '-C', str(root), 'check-ignore', '--', *relative], capture_output=True)
    if found.returncode not in (0, 1):raise Blocked(f'git check-ignore failed: {found.stderr.decode().strip()}')
    return found.stdout.decode().split()


def digest_of(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


def undo(root, previous, check_only=False):
    """Put back what this run's last render wrote, so a repair starts from the reviewed parent. Safe to repeat.
    It never discards a change it can't prove OH made: a file edited after OH wrote it, or a file OH was writing
    when it was interrupted, stops the run for a person to look at. check_only only asks whether undo could run."""
    from .storage import git
    import hashlib
    if not previous:return
    # An ignored file OH wrote isn't in git status, so a new file counts as changed whenever it exists.
    written, dirty = previous.get('files', {}), set(changes(root))
    dirty |= {r for r in previous.get('intent', []) if (Path(root) / r).exists() and not git(root, 'ls-tree', '--name-only', 'HEAD', '--', r)}
    for relative in previous.get('intent', []):
        if relative not in dirty:continue  # already as HEAD has it
        path = Path(root) / relative
        current = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if relative not in written:
            raise Blocked(f'OH was interrupted while writing {relative}. Discard that change (git checkout -- <file>, or delete '
                          'a new file) and run OH again, or stop the run with /oh-stop to keep it')
        if current != written[relative]:
            raise Blocked(f'{relative} changed after OH wrote it. Stop this run (/oh-stop) and keep or discard that edit yourself')
    if check_only:return
    for relative in previous.get('intent', []):
        if relative not in dirty:continue
        if git(root, 'ls-tree', '--name-only', 'HEAD', '--', relative):git(root, 'checkout', 'HEAD', '--', relative)
        else:(Path(root) / relative).unlink(missing_ok=True)


def render(root, slug, value, record):
    """Write the design (or the owed decision record) into a checkout that undo put back to HEAD.
    `record` saves the paths before anything is written. A Refused is about the worker's prose and goes back to it;
    a Blocked is about the checkout, settings or roadmap and stops the run. Returns the paths and their hashes."""
    import hashlib
    where = blocked(lambda: layout(root))
    if where['location'] != 'repo':raise Blocked('This design run writes plans in the repository, but plans.location changed')
    with editing(root):
        changed = changes(root)
        if changed:raise Blocked(f"The checkout has changes OH didn't write ({', '.join(changed[:5])}); a design commit holds only its plan files")
        value = answer(value)
        blocked(lambda: initiative(root, where, slug));blocked(lambda: verify_roadmap(root, where))
        if value['kind'] == 'design':
            number = blocked(lambda: next_number(where['designs']))
            paths = [Path(where['designs']) / f'{number}-{slug}.md', Path(where['roadmap'])]
        else:
            number = blocked(lambda: next_number(where['decisions']))
            paths = [Path(where['decisions']) / f'{number}-{decision_slug(value["title"])}.md', Path(where['decisions']) / 'README.md']
        intent = [Path(p).relative_to(root).as_posix() for p in paths]
        skipped = ignored(root, intent)
        if skipped:raise Blocked(f'Git ignores {", ".join(skipped)}; plans in the repository must be committed')
        record(intent)
        with all_or_nothing(*paths):
            if value['kind'] == 'design':
                written, path = write_design(root, where, slug, value['title'], value['body'], 'approved')
                rows = [row.split(US) for row in plan(root, written, where).split('\n') if row]
                if any(row[1] != 'pending' for row in rows):
                    raise Refused('A new design has only open tasks: write each as "- [ ] **N.**", never "- [x]"')
                blocked(lambda: claim(root, where, slug, written))
                verify_design(root, where, written)
                tasks = len(rows)
            else:
                written, path = blocked(lambda: write_decision(root, where, value['title'], value['context'], value['alternatives'],
                                                               value['consequences'], recommendation=value['summary']))
                tasks = 0
            if written != number or Path(path) != paths[0]:raise Blocked('The plan was written under another number')
        files = {relative: hashlib.sha256((Path(root) / relative).read_bytes()).hexdigest() for relative in intent}
    return {'kind': value['kind'], 'number': number, 'title': value['title'].strip(), 'path': intent[0], 'tasks': tasks,
            'summary': value['summary'].strip(), 'intent': intent, 'files': files}


def decision_slug(title):
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:60].strip('-') or 'decision'


def propose_manifest(root, idea):
    """The run that routes one idea: a roadmap row, a task in an approved design, or an improvement."""
    where = layout(root)
    if where['location'] != 'repo':
        raise Refused('/oh-propose writes plans in the repository for now; private plans get their approval step in a coming '
                      'update. Use oh config set plans.location repo, or wait for that update')
    idea = idea.strip()
    if not idea:raise Refused('Say what you want to add: /oh-propose <idea>')
    shown = {key: Path(where[key]).relative_to(root).as_posix() for key in ('roadmap', 'designs', 'decisions')}
    started = 'exists' if Path(where['roadmap']).is_file() else 'is not started yet; OH starts it if the idea needs a row'
    instructions = (f"The idea, in the person's words:\n{idea}\n\nRoadmap: {shown['roadmap']} ({started}). "
                    f"Design docs: {shown['designs']}/. Decision records: {shown['decisions']}/.")
    if Path(where['roadmap']).is_file():
        try:verify_roadmap(root, where)
        except Refused as exc:raise Refused(f'Fix the roadmap first. {exc}') from None
    return ({'workflow': 'propose', 'tasks': [{'id': 'propose', 'title': 'Propose: ' + idea.splitlines()[0][:60],
                                               'instructions': instructions, 'transition': {'profile': 'intake'}}]},
            {'workflow': 'propose', 'plans': {'location': 'repo'}})


def proposal(value):
    """The intake worker's answer, checked: its route and prose. OH decides every number and link."""
    from .hosts import PROPOSAL_SCHEMA
    fields = PROPOSAL_SCHEMA['required']
    if not isinstance(value, dict) or set(value) != set(fields):
        raise Refused('The answer must be the JSON object the output schema describes')
    if any(not isinstance(value[k], str) for k in fields if k != 'depends') or not isinstance(value['depends'], list) \
            or any(not isinstance(d, str) for d in value['depends']):
        raise Refused('Every field is a string, and depends a list of strings')
    if value['route'] not in ('roadmap', 'task', 'improvement', 'unclear'):
        raise Refused("route must be 'roadmap', 'task', 'improvement' or 'unclear'")
    for key in ('understanding', 'reason', 'text'):
        if not value[key].strip():raise Refused(f'{key} is empty')
    for key, limit in (('understanding', SUMMARY_CHARS), ('reason', SUMMARY_CHARS), ('summary', SUMMARY_CHARS), ('evidence', 2 * SUMMARY_CHARS),
                       ('text', 2 * SUMMARY_CHARS), ('milestone_title', TITLE_CHARS), ('decision_title', TITLE_CHARS)):
        if len(value[key].strip()) > limit:raise Refused(f'{key} is longer than {limit} characters')
    if '|' in value['decision_title']:raise Refused('A decision title cannot contain |')
    if value['route'] == 'roadmap':
        if not re.fullmatch(SLUG, value['slug']):raise Refused(f"'{value['slug']}' is not a kebab-case slug")
        if not re.fullmatch(r'M[0-9]+', value['milestone']):raise Refused(f"'{value['milestone']}' is not a milestone id like M3")
        decision = [value[k].strip() for k in ('decision_title', 'decision_context', 'decision_alternatives', 'decision_consequences')]
        if any(decision) and not all(decision):raise Refused('A contested choice needs its decision title, context, alternatives and consequences')
    if value['route'] == 'task':
        if not re.fullmatch(r'[0-9]{4}', value['design']):raise Refused(f"'{value['design']}' is not a four-digit design number")
        if not value['track'].strip():raise Refused('A task names the track it joins')
        if any(not re.fullmatch(r'[0-9]+', d) for d in value['depends']):raise Refused('A task depends on task numbers')
    return value


def add_task(root, where, design, track, text, depends):
    """Append one pending task to an approved design's track, numbered after the doc's last task."""
    path = design_file(root, design, where)
    if not path:raise Refused(f'There is no design doc {design}')
    status = status_of(path)
    if status != 'approved':
        raise Refused(f"Design doc {design} is {status or 'missing a status'}: only an approved design takes new tasks"
                      + ('; a frozen design has shipped, so new work is a roadmap row or an improvement' if status == 'frozen' else ''))
    text = one_line(text, 'The task text')
    rows = [row.split(US) for row in plan(root, design, where).strip('\n').split('\n')]
    owner = track.strip().split()[0].lower()
    if owner not in {row[2] for row in rows}:
        raise Refused(f"Design doc {design} has no {track} track; its tracks are {', '.join(sorted({row[2] for row in rows}))}")
    for need in depends:
        if need not in {row[0] for row in rows}:raise Refused(f'Design doc {design} has no task {need}')
    number = str(max(int(row[0]) for row in rows) + 1)
    lines, ending = rows_of(path)
    section, end = None, None
    for index, line in outside(lines):
        heading = re.match(r'###' + WS + r'+(\S+).*[Tt]rack' + WS + '*$', line)
        if heading:section = heading[1].lower();continue
        if re.match(r'#{1,3}' + WS, line):
            if section == owner:break
            section = None;continue
        if section == owner and line.strip():end = index
    if end is None:raise Refused(f'Cannot find the end of the {track} track in design doc {design}')
    needs = f" Depends on task{'s' if len(depends) > 1 else ''} {', '.join(depends)}." if depends else ''
    task = f'- [ ] **{number}.** {text.rstrip()}{needs}'
    lines.insert(end + 1, task)
    with all_or_nothing(path):
        write_rows(path, lines, ending)
        verify_design(root, where, design)
    return number, task


def render_proposal(root, value, record, move):
    """Write the proposal's route into the checkout: nothing for an improvement or an unclear idea.
    `move` puts the work on its own branch before anything is written; `record` saves the paths first."""
    import hashlib
    from .storage import project
    where = blocked(lambda: layout(root))
    if where['location'] != 'repo':raise Blocked('This proposal writes plans in the repository, but plans.location changed')
    with editing(root):
        changed = changes(root)
        if changed:raise Blocked(f"The checkout has changes OH didn't write ({', '.join(changed[:5])}); a proposal commit holds only its plan files")
        value = proposal(value)
        if Path(where['roadmap']).is_file():blocked(lambda: verify_roadmap(root, where))
        shown = {k: value[k] for k in ('route', 'understanding', 'reason', 'evidence', 'text', 'summary')}
        if value['route'] in ('improvement', 'unclear'):return shown | {'intent': [], 'files': {}, 'lines': []}
        if value['route'] == 'roadmap':
            paths, topic = [Path(where['roadmap'])], value['slug']
            if value['decision_title'].strip():
                number = blocked(lambda: next_number(where['decisions']))
                paths += [Path(where['decisions']) / f'{number}-{decision_slug(value["decision_title"])}.md', Path(where['decisions']) / 'README.md']
        else:
            path = design_file(root, value['design'], where)
            if not path:raise Refused(f"There is no design doc {value['design']}")
            paths, topic = [Path(path)], f"design-{value['design']}"
        intent = [Path(p).relative_to(root).as_posix() for p in paths]
        skipped = ignored(root, intent)
        if skipped:raise Blocked(f'Git ignores {", ".join(skipped)}; plans in the repository must be committed')
        blocked(lambda: move(topic))
        record(intent)
        lines = []
        with all_or_nothing(*paths):
            if value['route'] == 'roadmap':
                if not Path(where['roadmap']).exists():blocked(lambda: start_roadmap(where, project(root)['name']))
                if value['milestone'] not in dict(milestones(where)):
                    add_milestone(root, where, value['milestone'], value['milestone_title'], value['milestone_done_when'])
                    lines.append(f"### {value['milestone']} — {value['milestone_title'].strip()}")
                add_initiative(root, where, value['milestone'], value['slug'], value['text'], value['depends'])
                lines.append(next(line for _, line in outside(rows_of(where['roadmap'])[0]) if line.startswith(f"| `{value['slug']}` |")))
                if value['decision_title'].strip():
                    number, _ = blocked(lambda: write_decision(root, where, value['decision_title'], value['decision_context'],
                                               value['decision_alternatives'], value['decision_consequences'], recommendation=value['summary']))
                    lines.append(f"Decision record {number} (proposed): {value['decision_title'].strip()}")
            else:
                _, task = add_task(root, where, value['design'], value['track'], value['text'], value['depends'])
                lines.append(task)
        files = {relative: hashlib.sha256((Path(root) / relative).read_bytes()).hexdigest() for relative in intent}
    return shown | {'path': intent[0], 'intent': intent, 'files': files, 'lines': lines}
