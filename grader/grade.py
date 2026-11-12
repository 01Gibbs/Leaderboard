"""Grading: find each lesson's pull requests and grade every commit not graded yet.

Results go to grader/results.json, one entry per pull request, with the reasons it passed or failed;
Roster.apply_results then moves them onto the leaderboard. The rules people rely on live here:
  - each commit is graded once, and again only when its lesson changes (Lesson.version);
  - a grader error (not the participant's fault) is recorded as passed=None and retried next run;
  - one repository being unreachable skips that repository, not the run.

Pull requests come from a source: GitHub in production, an in-memory one in tests.
"""
import json
import os
import subprocess
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import checks
import executor
import lessons


class PullRequest(NamedTuple):
    number: int
    login: str
    sha: str
    url: str
    created_at: str = ''  # when it was opened: the first few on each lesson earn the early-PR bonus


class GitHub:
    """The production source. `api` fetches one GitHub REST path and returns the decoded JSON."""

    def __init__(self, api=None):
        self.api = api or self._fetch

    @staticmethod
    def _fetch(path):
        req = urllib.request.Request('https://api.github.com' + path, headers={'Accept': 'application/vnd.github+json'})
        token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if token:
            req.add_header('Authorization', 'Bearer ' + token)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def pull_requests(self, repo):
        """Every submission: pull requests except the repo owner's, bots', and ones closed without merging."""
        owner, page, out = repo.split('/')[0].lower(), 1, []
        while True:
            batch = self.api(f'/repos/{repo}/pulls?state=all&per_page=100&page={page}')
            for pr in batch:
                withdrawn = pr['state'] == 'closed' and not pr.get('merged_at')
                if pr['user']['type'] == 'Bot' or pr['user']['login'].lower() == owner or withdrawn:
                    continue
                out.append(PullRequest(pr['number'], pr['user']['login'], pr['head']['sha'], pr['html_url'], pr.get('created_at') or ''))
            if len(batch) < 100:
                return out
            page += 1

    def display_name(self, login):
        return self.api(f'/users/{login}').get('name') or login

    def checkout(self, repo, number, dest):
        for args in (['init', '-q'], ['fetch', '-q', '--depth', '1', f'https://github.com/{repo}.git', f'pull/{number}/head'],
                     ['checkout', '-q', 'FETCH_HEAD']):
            code, out = executor.host_run(['git', *args], cwd=dest, timeout=600)
            if code:
                raise subprocess.CalledProcessError(code, ['git', *args], out)


def still_valid(previous, pr, lesson):
    """Whether an earlier result for this pull request still counts: same commit, same lesson version, and
    actually graded (a grader error or an ungraded entry does not count)."""
    return (previous.get('passed') is not None and previous.get('sha') == pr.sha
            and previous.get('version') == lesson.version)


def grade_submission(lesson, source, pr, adapter=None):
    """Check out one pull request and run its lesson's check. Returns (passed, reasons): True or False for
    the participant's result, None when the grader itself failed (it is retried next run)."""
    with executor.workspace(adapter) as ws:
        try:
            source.checkout(lesson.repo, pr.number, ws.path)
            ws.share()
            return lesson.runner(ws, lesson)
        except checks.CheckFailed as e:
            return False, [str(e)]
        except Exception:
            return None, ['grader error, will retry:\n' + checks.tail(traceback.format_exc())]


def grade_all(root, source=None, adapter=None, no_run=False, only=None, log=print):
    """Grade every new commit on every lesson's repository; record the results in grader/results.json.
    no_run: only record who submitted. only: grade just one pull request, e.g. "owner/repo#3"."""
    root = Path(root)
    source = source or GitHub()
    results_file = root / 'grader' / 'results.json'
    results = json.loads(results_file.read_text()) if results_file.exists() else {}
    subs, people = results.setdefault('submissions', {}), results.setdefault('people', {})

    def save():
        results_file.write_text(json.dumps(results, indent=2, sort_keys=True) + '\n')

    for lesson in lessons.load(root / 'lessons.json', fixtures=root / 'grader' / 'fixtures'):
        try:
            prs = source.pull_requests(lesson.repo)
        except (urllib.error.URLError, OSError) as e:  # rate limit, outage, renamed repo: try again next run
            log(f'Skipping {lesson.repo} this run: cannot list pull requests ({e})')
            continue
        for pr in prs:
            key = f'{lesson.repo}#{pr.number}'
            if only and key != only:
                continue
            if pr.login not in people:
                try:
                    people[pr.login] = source.display_name(pr.login)
                except (urllib.error.URLError, OSError):
                    people[pr.login] = pr.login
            previous = subs.get(key, {})
            entry = {'task': lesson.key, 'login': pr.login, 'url': pr.url, 'sha': pr.sha, 'check': lesson.check, 'created_at': pr.created_at}
            if still_valid(previous, pr, lesson):
                subs[key] = {**previous, **entry}
                continue
            if lesson.runner is None:
                subs[key] = {**entry, 'passed': None, 'reasons': ['no automated check for this lesson; a facilitator marks it']}
                continue
            if no_run:
                same_commit = previous.get('sha') == pr.sha
                subs[key] = {**entry, 'passed': previous.get('passed') if same_commit else None,
                             'reasons': previous.get('reasons', []) if same_commit else []}
                continue
            log(f'Grading {key} ({pr.login} @ {pr.sha[:7]})')
            passed, reasons = grade_submission(lesson, source, pr, adapter)
            log(f"  {({True: 'PASS', False: 'FAIL'}).get(passed, 'RETRY')}: " + ' | '.join(r.splitlines()[0] for r in reasons))
            subs[key] = {**entry, 'passed': passed, 'reasons': reasons, 'version': lesson.version,
                         'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
            save()  # keep progress if a later one hangs
    save()
    return results
