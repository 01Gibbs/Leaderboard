"""Submissions: grader/results.json, one entry per pull request, and everything it means for scores.

grade.grade_all records here; Roster.apply_results and the walkthrough read from here. What an entry means:
  - passed True: the check passed, so the lesson is correct;
  - passed False: the check failed, so the lesson is submitted;
  - passed None: not graded (a grader error, a lesson a facilitator marks by hand, or a --no-run), so the
    lesson is submitted, and an automated lesson is graded again next run;
  - a result counts until the pull request gets a new commit or its lesson changes (Lesson.version).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from rules import EARLY_BONUS, RANK, to_int

UNCHECKED = 'no automated check for this lesson; a facilitator marks it'


def key(lesson, pr):
    """How a pull request is named in results.json and on the command line: "owner/repo#3"."""
    return f'{lesson.repo}#{pr.number}'


def _status(entry):
    return 'correct' if entry.get('passed') else 'submitted'


class Submissions:
    """grader/results.json of the leaderboard repository at `root`. A missing file is empty."""

    def __init__(self, root):
        self.file = Path(root) / 'grader' / 'results.json'
        self._data = json.loads(self.file.read_text(encoding='utf-8')) if self.file.exists() else {}
        self._subs = self._data.setdefault('submissions', {})
        self.names = self._data.setdefault('people', {})  # GitHub login -> profile name

    def save(self):
        self.file.write_text(json.dumps(self._data, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    def name(self, login):
        """The person's GitHub profile name, or the login if it is not known."""
        return self.names.get(login) or login

    # ---------- grading ----------

    def _previous(self, lesson, pr):
        return self._subs.get(key(lesson, pr), {})

    def _still_valid(self, lesson, pr):
        previous = self._previous(lesson, pr)
        return (previous.get('passed') is not None and previous.get('sha') == pr.sha
                and previous.get('version') == lesson.version)

    def needs_grading(self, lesson, pr):
        """Whether this pull request's check should run: the lesson is automated and there is no result that
        still counts."""
        return lesson.runner is not None and not self._still_valid(lesson, pr)

    def record_result(self, lesson, pr, passed, reasons):
        """Record the outcome of running the lesson's check on this pull request, replacing any earlier one:
        passed True or False, or None when the grader itself failed (graded again next run)."""
        self._subs[key(lesson, pr)] = self._entry(lesson, pr) | {
            'passed': passed, 'reasons': reasons, 'version': lesson.version,
            'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}

    def record(self, lesson, pr):
        """Record a pull request without grading it: a result that still counts is kept (or, for the same
        commit, its pass or fail), with the pull request's latest details."""
        previous, entry = self._previous(lesson, pr), self._entry(lesson, pr)
        if self._still_valid(lesson, pr):
            entry = {**previous, **entry}
        elif lesson.runner is None:
            entry |= {'passed': None, 'reasons': [UNCHECKED]}
        else:
            same_commit = previous.get('sha') == pr.sha
            entry |= {'passed': previous.get('passed') if same_commit else None,
                      'reasons': previous.get('reasons', []) if same_commit else []}
        self._subs[key(lesson, pr)] = entry

    @staticmethod
    def _entry(lesson, pr):
        return {'task': lesson.key, 'login': pr.login, 'url': pr.url, 'sha': pr.sha, 'check': lesson.check, 'created_at': pr.created_at}

    # ---------- reading ----------

    def best_statuses(self, lesson_keys):
        """[(login, lesson, status)]: each person's best status on each of `lesson_keys`, from all their pull
        requests. Logins differing only in case are one person. Sorted by lowercase login, then lesson."""
        best, spelling = {}, {}  # (login, lesson) -> status; lowercase login -> login as GitHub spells it
        for s in self._subs.values():
            if s['task'] not in lesson_keys:  # a lesson removed from lessons.json
                continue
            k = (s['login'].lower(), s['task'])
            spelling[k[0]] = s['login']
            if RANK[_status(s)] > RANK.get(best.get(k), -1):
                best[k] = _status(s)
        return [(spelling[login], lesson, status) for (login, lesson), status in sorted(best.items())]

    def early_bonus(self, lesson_keys):
        """{lowercase login: points}: one point for each of the first pull requests opened on each lesson.
        Worked out from scratch every time, so it is never added up twice."""
        early = {}
        for lesson in lesson_keys:
            # Opened first = earliest created_at; results recorded before created_at existed fall back to PR number.
            opened = sorted((s for s in self._subs.values() if s['task'] == lesson),
                            key=lambda s: (s.get('created_at') or '', to_int(str(s.get('url', '')).rsplit('/', 1)[-1])))
            for s in opened[:EARLY_BONUS['firstSubmissions']]:
                early[s['login'].lower()] = early.get(s['login'].lower(), 0) + 1
        return early

    def stats(self, lesson_key):
        """{submissions, people, correct} for one lesson: pull requests, distinct people, and passed ones."""
        subs = [s for s in self._subs.values() if s.get('task') == lesson_key]
        return {'submissions': len(subs), 'people': len({s.get('login') for s in subs}),
                'correct': sum(1 for s in subs if _status(s) == 'correct')}
