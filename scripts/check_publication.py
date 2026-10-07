"""Check only tracked/explicit public files; never read credentials."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    re.compile(r'/' + r'Users' + r'/[^/\s]+/|[A-Za-z]:\\\\Users\\\\'),
    re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'),
    re.compile(r'github_pat_[A-Za-z0-9_]{20,}'),
    re.compile(r'AKIA[A-Z0-9]{16}'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'(?i)(?:api_key|access_token|client_secret)\s*[=:]\s*[\"\x27][^\"\x27\s]{12,}[\"\x27]'),
)
FORBIDDEN = {'.env', '.aws', '.codex', '.workbuddy', 'local', 'outputs', 'data', 'tasks', '.venv'}


def main():
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    failures = []
    for name in filter(None, files):
        path = ROOT / name
        if set(Path(name).parts) & FORBIDDEN or path.is_symlink():
            failures.append((name, 'forbidden public path'))
            continue
        if path.stat().st_size > 1000000:
            failures.append((name, 'oversized public file'))
            continue
        text = path.read_text(encoding='utf-8')
        if any(pattern.search(text) for pattern in PATTERNS):
            failures.append((name, 'possible credential or personal path'))
    if failures:
        for name, reason in failures:
            print(name + ': ' + reason)
        return 1
    print('PUBLICATION_CHECK_PASS: tracked files only; no provider data or original history')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
