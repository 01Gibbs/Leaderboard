"""Opens an interactive walkthrough of the leaderboard in your browser.

    python3 walkthrough.py          (Windows: py walkthrough.py)       Needs Python 3.8 or newer.
    python3 walkthrough.py --real   show the real scores instead of made-up example people

It serves this folder on your own computer only (http://127.0.0.1), opens the walkthrough, and keeps running
until you press Ctrl+C. Nothing is changed or sent anywhere.
"""
import argparse
import csv
import io
import json
import re
import socket
import subprocess
import sys
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'grader'))
import lessons  # noqa: E402
import roster  # noqa: E402
import rules  # noqa: E402
CONTEXT_PATH = '/walkthrough/context.json'


# Made-up people for the example board, so the tour can show every state without showing anyone's real scores.
SAMPLE_PEOPLE = [('Asha Rao', 'asha-rao'), ('Ben Okafor', 'benok'), ('Chloe Martin', 'chloe-m'), ('Dev Patel', 'devpatel'),
                 ('Elif Yilmaz', 'elify'), ('Finn Byrne', 'finnb'), ('Grace Chen', 'gracechen'), ('Hamza Ali', 'hamza-a'),
                 ('Isla Murray', 'islam'), ('Jonas Weber', 'jweber')]
SAMPLE_STATES = ['correct', 'submitted', '', 'submitted']
SAMPLE_EXTRAS = [(2, 1, 5), (1, 3, 0), (0, 0, 0), (3, 0, 0), (0, 2, 0), (1, 0, 10), (0, 1, 0), (0, 0, 0), (2, 0, 0), (0, 0, 0)]


def sample_csv(lesson_keys):
    """An example participants.csv with a column for every lesson: one person correct on everything, the rest
    a mix of correct, submitted and not yet, plus some stretch, helped and bonus points."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow([*rules.BASE_COLUMNS, *lesson_keys, *rules.COUNTS])
    for i, ((name, login), extras) in enumerate(zip(SAMPLE_PEOPLE, SAMPLE_EXTRAS)):
        states = ['correct'] * len(lesson_keys) if i == 0 else [SAMPLE_STATES[(i + 2 * j) % 4] for j in range(len(lesson_keys))]
        w.writerow([name, login, *states, *(str(n) if n else '' for n in extras)])
    return buf.getvalue()


def github_repo(root):
    """(owner, name) of the GitHub remote this folder was cloned from, or None."""
    try:
        url = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=root, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$', url)
    return (m.group(1), m.group(2)) if m else None


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def build_context(root, sample=True):
    """Everything the walkthrough shows that comes from this repository: the GitHub links, the facilitator
    forms, each lesson with its submission counts, and recent facilitator actions."""
    repo = github_repo(root)
    base = f'https://github.com/{repo[0]}/{repo[1]}' if repo else None
    workflows = root / '.github' / 'workflows'

    forms = []
    for f in sorted(workflows.glob('*.yml')) if workflows.is_dir() else []:
        text = f.read_text(encoding='utf-8', errors='replace')
        name = re.search(r"^name:\s*['\"]?(.+?)['\"]?\s*$", text, re.M)
        if name and 'workflow_dispatch' in text and f.name != 'facilitator-action.yml':
            forms.append({'file': f.name, 'name': name.group(1), 'url': f'{base}/actions/workflows/{f.name}' if base else None})

    results = read_json(root / 'grader' / 'results.json', {}).get('submissions', {})
    try:
        loaded, problems = lessons.load(root / 'lessons.json', fixtures=root / 'grader' / 'fixtures'), []
    except lessons.LessonsInvalid as e:
        loaded, problems = [], e.problems
    lesson_rows = []
    for lesson in loaded:
        subs = [s for s in results.values() if s.get('task') == lesson.key]
        lesson_rows.append({'key': lesson.key, 'label': lesson.label, 'repo': lesson.repo, 'check': lesson.check,
                            'repo_url': f'https://github.com/{lesson.repo}', 'submissions': len(subs),
                            'people': len({s.get('login') for s in subs}), 'correct': sum(1 for s in subs if s.get('passed'))})

    history = roster.Roster(root).history()
    return {
        'repo': {'owner': repo[0], 'name': repo[1], 'url': base,
                 'pages_url': f'https://{repo[0].lower()}.github.io/{repo[1]}/'} if repo else None,
        'forms': forms,
        'lessons': lesson_rows,
        'lesson_problems': problems,
        'sample': sample,
        'recent_actions': [{k: h.get(k) for k in ('at', 'by', 'action')} for h in reversed(history[-3:])],
    }


class Handler(SimpleHTTPRequestHandler):
    """Serves the repository folder, plus the walkthrough's context built fresh on each request. With `sample`,
    participants.csv is replaced by example people (sample_csv)."""

    def __init__(self, *args, sample=True, **kwargs):
        self.sample = sample  # set first: the parent constructor handles the request straight away
        super().__init__(*args, **kwargs)

    def send_text(self, body, content_type):
        body = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/.git' or path.startswith('/.git/'):
            self.send_error(404)
            return
        root = Path(self.directory)
        if path == CONTEXT_PATH:
            self.send_text(json.dumps(build_context(root, self.sample)), 'application/json')
            return
        if path == '/participants.csv' and self.sample:
            try:
                keys = [l.key for l in lessons.load(root / 'lessons.json', fixtures=root / 'grader' / 'fixtures')]
            except lessons.LessonsInvalid:
                keys = []
            self.send_text(sample_csv(keys), 'text/csv; charset=utf-8')
            return
        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')  # always show the files as they are now
        super().end_headers()

    def log_message(self, *args):
        pass  # keep the terminal quiet


def free_port(preferred):
    """The preferred port if it is free, otherwise any free one."""
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise SystemExit('Could not find a free port.')


def main(argv):
    p = argparse.ArgumentParser(description='Open an interactive walkthrough of the leaderboard.')
    p.add_argument('--port', type=int, default=8123)
    p.add_argument('--no-open', action='store_true', help='do not open a browser window')
    p.add_argument('--real', action='store_true', help='show the real scores instead of example people')
    args = p.parse_args(argv)

    port = free_port(args.port)
    server = ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, directory=str(ROOT), sample=not args.real))
    url = f'http://127.0.0.1:{port}/walkthrough/'
    print(f'Walkthrough running at {url}\nPress Ctrl+C to stop.', flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
