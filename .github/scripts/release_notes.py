"""Render a version's changelog section for the GitHub release page."""
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit


def render(changelog, repository, tag):
    source = f'https://github.com/{repository}/blob/{tag}/'

    def link(match):
        target = match[1]
        if target.startswith(('#', '/')) or urlsplit(target).scheme:
            return match[0]
        return f']({urljoin(source, target)})'

    selected = False
    fence = ''
    lines = []
    for line in changelog.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = ''
        elif marker:
            fence = marker[1]
        elif heading := re.match(r'^ {0,3}##[ \t]+([^\s]+)', line):
            if selected:
                break
            selected = heading[1] == tag
            continue
        elif selected:
            line = re.sub(r'\]\(([^\s()]+)\)', link, line)
        if selected:
            lines.append(line)

    notes = ''.join(lines).strip()
    return notes + '\n' if notes else ''


if __name__ == '__main__':
    repository, tag = sys.argv[1:]
    changelog = Path('CHANGELOG.md')
    if changelog.is_file():
        sys.stdout.write(render(changelog.read_text(encoding='utf-8'), repository, tag))
