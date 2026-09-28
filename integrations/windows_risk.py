"""Flag lines a change adds that commonly break on Windows, so they are fixed before CI runs.
Each rule comes from a real Windows failure in OH. Add `# windows-ok: <why>` to a line that is safe.

  python3 integrations/windows_risk.py [base]   check lines added since base (default origin/main)
  python3 integrations/windows_risk.py --all    check every line, to judge the rules
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RULES = [
    (r"write_text\((?=.*\\n)(?!.*newline=)", "Windows writes \\n as \\r\\n: pass newline='\\n' or use write_bytes"),
    (r"assert.*st_mode.*0o[0-7]{3}", "Windows keeps only the writable bit: compare with the mode read back, not a POSIX literal"),
    (r"rmtree\((?!.*(onexc|onerror|ignore_errors))", "Git's object files are read-only and Windows refuses to delete them: clear the bit in onexc"),
    (r"assertRaisesRegex\((?=.*str\()(?!.*re\.escape)", "Windows paths contain backslashes: re.escape them in a regex"),
    (r"os\.symlink|symlink_to\(", "Windows needs special rights for symlinks: avoid them or skip the test there"),
    (r"\bfcntl\b|os\.setsid|preexec_fn|os\.killpg|SIGKILL|os\.get(e)?uid|\bimport pwd\b", "POSIX only: go through OH's platform module"),
    (r"['\"]/tmp\b", "No /tmp on Windows: use tempfile"),
]
RULES = [(re.compile(pattern), why) for pattern, why in RULES]
# OH's platform module and the macOS service are where POSIX-only calls belong.
SKIP = {'integrations/windows_risk.py', 'runtime/oh/system.py', 'runtime/oh/service.py'}


def added(base):
    merge = subprocess.run(['git', '-C', str(ROOT), 'merge-base', base, 'HEAD'], capture_output=True, text=True).stdout.strip()
    if not merge:sys.exit(f'windows-risk: cannot find {base}; fetch it or pass another base')
    diff = subprocess.run(['git', '-C', str(ROOT), 'diff', '-U0', merge, '--', '*.py'], capture_output=True, text=True, check=True).stdout
    name = number = None
    for row in diff.splitlines():
        if row.startswith('+++ '):name = row[6:]
        elif row.startswith('@@'):number = int(re.search(r'\+(\d+)', row).group(1))
        elif row.startswith('+') and name:
            yield name, number, row[1:];number += 1


def everything():
    for path in sorted(ROOT.glob('**/*.py')):
        name = str(path.relative_to(ROOT))
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):yield name, number, line


def main(argv):
    rows = everything() if argv[:1] == ['--all'] else added(argv[0] if argv else 'origin/main')
    hits = [(name, number, why) for name, number, line in rows if name not in SKIP and '# windows-ok' not in line
            for rule, why in RULES if rule.search(line)]
    for name, number, why in hits:print(f'{name}:{number}: {why}')
    if hits:print(f'windows-risk: {len(hits)} line(s) may break on Windows; fix them or mark `# windows-ok: <why>`.')
    return 1 if hits else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
