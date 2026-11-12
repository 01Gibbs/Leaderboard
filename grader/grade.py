"""Pull exercise submissions (pull requests) into the leaderboard and grade them.

grade: find every pull request on each lesson's repository (lessons.json), run the lesson's check on any
commit not graded yet, and record the outcome in grader/results.json.
apply: merge grader/results.json into participants.csv. It adds a row for any new GitHub account and raises
each exercise column to the graded status. It never lowers a status, so facilitator changes survive.
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import roster

HERE = Path(__file__).resolve().parent
RESULTS = HERE / 'results.json'


def load_lessons():
    """lessons.json, checked so a typo fails loudly instead of silently grading nothing."""
    import checks
    items, problems, seen = roster.lessons(), [], set()
    for i, l in enumerate(items, 1):
        key = l.get('key', '')
        if not re.fullmatch(r'[a-z][a-z0-9_]*', key):
            problems.append(f'lesson {i}: key "{key}" must be lowercase letters, digits and _')
        if key in seen or key in roster.BASE_COLUMNS + roster.COUNTS:
            problems.append(f'lesson {i}: key "{key}" is already used')
        seen.add(key)
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', l.get('repo', '')):
            problems.append(f'lesson {i} ({key}): repo must look like owner/name')
        if l.get('check', 'none') not in checks.CHECKS and l.get('check', 'none') != 'none':
            problems.append(f'lesson {i} ({key}): check must be one of none, {", ".join(checks.CHECKS)}')
        if not l.get('label'):
            problems.append(f'lesson {i} ({key}): needs a label')
    if problems:
        raise SystemExit('lessons.json has problems:\n  ' + '\n  '.join(problems))
    return items


# ---------- GitHub ----------

def api(path):
    req = urllib.request.Request('https://api.github.com' + path, headers={'Accept': 'application/vnd.github+json'})
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pull_requests(repo):
    owner = repo.split('/')[0].lower()
    page = 1
    while True:
        batch = api(f'/repos/{repo}/pulls?state=all&per_page=100&page={page}')
        for pr in batch:
            closed_unmerged = pr['state'] == 'closed' and not pr.get('merged_at')
            if pr['user']['type'] == 'Bot' or pr['user']['login'].lower() == owner or closed_unmerged:
                continue
            yield pr
        if len(batch) < 100:
            return
        page += 1


def checkout(repo, number, dest):
    def git(*args):
        subprocess.run(['git', *args], cwd=dest, check=True, capture_output=True, timeout=600)
    git('init', '-q')
    git('fetch', '-q', '--depth', '1', f'https://github.com/{repo}.git', f'pull/{number}/head')
    git('checkout', '-q', 'FETCH_HEAD')


def grader_version():
    """Changes whenever the checks or fixtures change, so every submission is graded again."""
    h = hashlib.sha256()
    for f in sorted([HERE / 'checks.py', *(HERE / 'fixtures').rglob('*')]):
        if f.is_file():
            h.update(f.relative_to(HERE).as_posix().encode() + f.read_bytes())
    return h.hexdigest()[:12]


# ---------- grade ----------

def load_results():
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else {}


def save_results(results):
    RESULTS.write_text(json.dumps(results, indent=2, sort_keys=True) + '\n')


def grade(no_run=False, only=None):
    import checks
    results = load_results()
    subs, people = results.setdefault('submissions', {}), results.setdefault('people', {})
    version = grader_version()

    for lesson in load_lessons():
        check_name = lesson.get('check', 'none')
        check = checks.CHECKS.get(check_name)
        try:
            prs = list(pull_requests(lesson['repo']))
        except (urllib.error.URLError, OSError) as e:  # rate limit, outage, renamed repo: try again next run
            print(f"Skipping {lesson['repo']} this run: cannot list pull requests ({e})", flush=True)
            continue
        for pr in prs:
            key = f"{lesson['repo']}#{pr['number']}"
            if only and key != only:
                continue
            login, sha = pr['user']['login'], pr['head']['sha']
            if login not in people:
                try:
                    people[login] = api(f'/users/{login}').get('name') or login
                except (urllib.error.URLError, OSError):
                    people[login] = login
            prev = subs.get(key, {})
            entry = {'task': lesson['key'], 'login': login, 'url': pr['html_url'], 'sha': sha, 'check': check_name}
            graded = prev.get('passed') is not None
            if graded and all(prev.get(k) == v for k, v in [('sha', sha), ('version', version), ('check', check_name)]):
                subs[key] = {**prev, **entry}
                continue
            if check is None:  # check "none": submissions are tracked and a facilitator marks them correct
                subs[key] = {**entry, 'passed': None, 'reasons': ['no automated check for this lesson; a facilitator marks it']}
                continue
            if no_run:
                subs[key] = {**entry, 'passed': prev.get('passed') if prev.get('sha') == sha else None, 'reasons': prev.get('reasons', [])}
                continue
            print(f'Grading {key} ({login} @ {sha[:7]})', flush=True)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    checkout(lesson['repo'], pr['number'], tmp)
                    checks.share_with_sandbox(tmp)
                    passed, reasons = check(Path(tmp), lesson)
                except checks.CheckFailed as e:
                    passed, reasons = False, [str(e)]
                except Exception:  # the grader's fault, not the submission's: passed=None grades it again next run
                    passed, reasons = None, ['grader error, will retry:\n' + checks.tail(traceback.format_exc())]
                finally:
                    checks.stop_sandbox_processes()
            print(f"  {({True: 'PASS', False: 'FAIL'}).get(passed, 'RETRY')}: " + ' | '.join(r.splitlines()[0] for r in reasons), flush=True)
            subs[key] = {**entry, 'passed': passed, 'reasons': reasons, 'version': version,
                         'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
            save_results(results)  # keep progress if a later one hangs

    save_results(results)


# ---------- apply ----------

def apply(quiet=False):
    results = load_results()
    subs, people = results.get('submissions', {}), results.get('people', {})
    r = roster.Roster()
    by_login, warnings = r.by_login()
    for w in warnings:
        print('Warning: ' + w)
    keys = roster.lesson_keys()

    best, spelling = {}, {}  # (login, lesson) -> status; lowercase login -> login as GitHub spells it
    for s in subs.values():
        if s['task'] not in keys:  # a lesson removed from lessons.json
            continue
        status = 'correct' if s.get('passed') else 'submitted'
        k = (s['login'].lower(), s['task'])
        spelling[k[0]] = s['login']
        if roster.RANK[status] > roster.RANK.get(best.get(k), -1):
            best[k] = status

    changes = []
    for (login, lesson), status in sorted(best.items()):
        row = by_login.get(login)
        if row is None:
            gh = spelling[login]
            row = by_login[login] = r.new_row(people.get(gh) or gh, gh)
            changes.append(f'Added {row["name"]} (@{gh})')
        if roster.RANK[status] > roster.RANK[roster.norm_status(row.get(lesson))]:
            changes.append(f'{row["name"]}: {lesson} -> {status}')
            row[lesson] = status
    if not quiet:
        print('\n'.join(changes) or 'No changes')
    r.save()
