"""Grading: finding pull requests and deciding which to grade, through an in-memory GitHub.

Run: python3 -m unittest discover grader/tests
No network or JDK: the checks here are small stand-ins registered for the test.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

GRADER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GRADER))
import checks  # noqa: E402
import grade  # noqa: E402
import roster  # noqa: E402

calls = []


def passes(workspace, lesson):
    calls.append((lesson.key, (workspace.path / 'sha.txt').read_text()))
    return True, ['all good']


def fails(workspace, lesson):
    calls.append((lesson.key, (workspace.path / 'sha.txt').read_text()))
    raise checks.CheckFailed('POST should return 201 (got 500)')


def crashes(workspace, lesson):
    calls.append((lesson.key, (workspace.path / 'sha.txt').read_text()))
    raise RuntimeError('Maven Central rate limit')


STAND_INS = {'stand_in_pass': passes, 'stand_in_fail': fails, 'stand_in_crash': crashes}


class FakeGitHub:
    """The in-memory adapter: pull requests per repo, profile names, and checkouts that write the commit sha."""

    def __init__(self):
        self.prs, self.names, self.down, self.checkouts = {}, {}, set(), []

    def add(self, repo, number, login, sha, created_at='2026-11-01T09:00:00Z'):
        self.prs.setdefault(repo, []).append(grade.PullRequest(number, login, sha, f'https://github.com/{repo}/pull/{number}', created_at))

    def pull_requests(self, repo):
        if repo in self.down:
            raise urllib.error.URLError('rate limited')
        return list(self.prs.get(repo, []))

    def display_name(self, login):
        if login not in self.names:
            raise urllib.error.URLError('404')
        return self.names[login]

    def checkout(self, repo, number, dest):
        pr = next(p for p in self.prs[repo] if p.number == number)
        self.checkouts.append((repo, number))
        Path(dest, 'sha.txt').write_text(pr.sha)


class Sandbox(unittest.TestCase):
    def setUp(self):
        calls.clear()
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        (self.dir / 'grader' / 'fixtures').mkdir(parents=True)
        self.github = FakeGitHub()
        patcher = mock.patch.dict(checks.CHECKS, STAND_INS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.lessons([('alpha', 'o/alpha', 'stand_in_pass'), ('beta', 'o/beta', 'stand_in_fail')])

    def lessons(self, items):
        (self.dir / 'lessons.json').write_text(json.dumps([{'key': k, 'label': k.title(), 'repo': r, 'check': c} for k, r, c in items]))

    def grade(self, **kw):
        out = []
        grade.grade_all(self.dir, source=self.github, log=out.append, **kw)
        return out

    def results(self):
        return json.loads((self.dir / 'grader' / 'results.json').read_text())

    def sub(self, key):
        return self.results()['submissions'][key]


class GradingTests(Sandbox):
    def test_new_pull_requests_are_graded_with_reasons(self):
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.github.add('o/beta', 7, 'ann', 'b1')
        self.github.names['ann'] = 'Ann Lee'
        self.grade()
        self.assertEqual((self.sub('o/alpha#1')['passed'], self.sub('o/alpha#1')['reasons']), (True, ['all good']))
        self.assertEqual((self.sub('o/beta#7')['passed'], self.sub('o/beta#7')['reasons']), (False, ['POST should return 201 (got 500)']))
        self.assertEqual(self.results()['people'], {'ann': 'Ann Lee'})

    def test_when_each_pull_request_was_opened_is_recorded(self):
        self.github.add('o/alpha', 1, 'ann', 'a1', created_at='2026-11-03T10:00:00Z')
        self.grade(no_run=True)
        self.assertEqual(self.sub('o/alpha#1')['created_at'], '2026-11-03T10:00:00Z')

    def test_a_commit_is_graded_once(self):
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.grade()
        self.grade()
        self.assertEqual(calls, [('alpha', 'a1')])

    def test_a_new_commit_is_graded_again(self):
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.grade()
        self.github.prs['o/alpha'][0] = grade.PullRequest(1, 'ann', 'a2', 'u', '2026-11-01T09:00:00Z')
        self.grade()
        self.assertEqual(calls, [('alpha', 'a1'), ('alpha', 'a2')])

    def test_changing_a_lesson_regrades_only_that_lesson(self):
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.github.add('o/beta', 1, 'ann', 'b1')
        self.grade()
        (self.dir / 'grader' / 'fixtures' / 'beta').mkdir()
        (self.dir / 'grader' / 'fixtures' / 'beta' / 'NewTest.java').write_text('class NewTest {}')
        self.grade()
        self.assertEqual(calls, [('alpha', 'a1'), ('beta', 'b1'), ('beta', 'b1')])

    def test_a_grader_error_is_retried_next_run(self):
        self.lessons([('alpha', 'o/alpha', 'stand_in_crash')])
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.grade()
        self.assertIsNone(self.sub('o/alpha#1')['passed'])
        self.assertIn('Maven Central rate limit', self.sub('o/alpha#1')['reasons'][0])
        self.grade()
        self.assertEqual(len(calls), 2)

    def test_a_checkout_failure_is_a_grader_error(self):
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.github.checkout = mock.Mock(side_effect=subprocess.CalledProcessError(128, 'git fetch'))
        self.grade()
        self.assertIsNone(self.sub('o/alpha#1')['passed'])

    def test_a_hand_marked_lesson_is_never_checked_out(self):
        self.lessons([('alpha', 'o/alpha', 'none')])
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.grade()
        self.assertEqual(self.github.checkouts, [])
        self.assertIsNone(self.sub('o/alpha#1')['passed'])
        self.assertIn('facilitator', self.sub('o/alpha#1')['reasons'][0])

    def test_no_run_records_submissions_and_keeps_earlier_results(self):
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.grade()
        self.github.add('o/alpha', 2, 'bob', 'a9')
        self.grade(no_run=True)
        self.assertEqual(self.github.checkouts, [('o/alpha', 1)])
        self.assertTrue(self.sub('o/alpha#1')['passed'])
        self.assertIsNone(self.sub('o/alpha#2')['passed'])

    def test_only_grades_the_named_pull_request(self):
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.github.add('o/alpha', 2, 'bob', 'a2')
        self.grade(only='o/alpha#2')
        self.assertEqual(calls, [('alpha', 'a2')])

    def test_one_repository_failing_does_not_stop_the_others(self):
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.github.add('o/beta', 1, 'ann', 'b1')
        self.github.down.add('o/alpha')
        log = self.grade()
        self.assertIn('o/beta#1', self.results()['submissions'])
        self.assertTrue(any('Skipping o/alpha' in line for line in log))

    def test_an_unknown_profile_falls_back_to_the_login(self):
        self.github.add('o/alpha', 1, 'ghost', 'a1')
        self.grade()
        self.assertEqual(self.results()['people'], {'ghost': 'ghost'})

    def test_progress_is_saved_after_each_pull_request(self):
        seen = []

        def records_progress(workspace, lesson):
            path = self.dir / 'grader' / 'results.json'
            seen.append(sorted(json.loads(path.read_text())['submissions']) if path.exists() else [])
            return True, ['ok']
        self.lessons([('alpha', 'o/alpha', 'stand_in_progress')])
        checks.CHECKS['stand_in_progress'] = records_progress
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.github.add('o/alpha', 2, 'bob', 'a2')
        self.grade()
        self.assertEqual(seen, [[], ['o/alpha#1']])

    def test_graded_results_reach_the_leaderboard(self):
        self.github.add('o/alpha', 1, 'ann', 'a1')
        self.github.add('o/beta', 1, 'ann', 'b1')
        self.github.names['ann'] = 'Ann Lee'
        self.grade()
        roster.Roster(self.dir).apply_results()
        row = roster.Roster(self.dir).find('ann')
        self.assertEqual((row['name'], row['alpha'], row['beta']), ('Ann Lee', 'correct', 'submitted'))


class GitHubAdapterTests(unittest.TestCase):
    """The real adapter, with GitHub's HTTP responses replaced."""

    def pr(self, number, login, state='open', merged=False, kind='User'):
        return {'number': number, 'user': {'login': login, 'type': kind}, 'state': state,
                'merged_at': '2026-01-01' if merged else None, 'head': {'sha': f's{number}'}, 'html_url': f'u{number}', 'created_at': f'2026-10-{number}'}

    def test_lists_submissions_across_pages_and_skips_what_is_not_one(self):
        page1 = [self.pr(n, f'p{n}') for n in range(1, 101)]
        page2 = [self.pr(101, 'Owner'), self.pr(102, 'dependabot[bot]', kind='Bot'),
                 self.pr(103, 'quitter', state='closed'), self.pr(104, 'merged', state='closed', merged=True)]
        responses = {'/repos/Owner/repo/pulls?state=all&per_page=100&page=1': page1,
                     '/repos/Owner/repo/pulls?state=all&per_page=100&page=2': page2}
        prs = grade.GitHub(api=responses.__getitem__).pull_requests('Owner/repo')
        self.assertEqual(len(prs), 101)
        self.assertEqual(prs[-1], grade.PullRequest(104, 'merged', 's104', 'u104', '2026-10-104'))
        self.assertNotIn('quitter', [p.login for p in prs])

    def test_display_name_falls_back_to_the_login_when_unset(self):
        gh = grade.GitHub(api={'/users/ann': {'name': None}}.__getitem__)
        self.assertEqual(gh.display_name('ann'), 'ann')


if __name__ == '__main__':
    unittest.main()
