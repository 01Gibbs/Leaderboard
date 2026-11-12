"""The walkthrough (walkthrough.py and walkthrough/): its context, its server, and its contract with index.html."""
import json
import re
import shutil
import subprocess
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import walkthrough  # noqa: E402

STEPS = (REPO / 'walkthrough' / 'steps.js').read_text()


class ContextTests(unittest.TestCase):
    def repo(self, remote=None):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        if remote:
            subprocess.run(['git', 'remote', 'add', 'origin', remote], cwd=root, check=True)
        (root / '.github' / 'workflows').mkdir(parents=True)
        (root / 'grader').mkdir()
        return root

    def test_github_links_from_https_and_ssh_remotes(self):
        for remote in ('https://github.com/Some-Org/My.Board.git', 'git@github.com:Some-Org/My.Board.git', 'https://github.com/Some-Org/My.Board'):
            ctx = walkthrough.build_context(self.repo(remote))
            self.assertEqual(ctx['repo']['url'], 'https://github.com/Some-Org/My.Board', remote)
            self.assertEqual(ctx['repo']['pages_url'], 'https://some-org.github.io/My.Board/')

    def test_without_a_github_remote_there_are_no_links_but_it_still_works(self):
        root = self.repo()
        (root / '.github' / 'workflows' / 'facilitator-award.yml').write_text("name: 'Facilitator: Award points'\non:\n  workflow_dispatch:\n")
        ctx = walkthrough.build_context(root)
        self.assertIsNone(ctx['repo'])
        self.assertIsNone(ctx['forms'][0]['url'])

    def test_forms_are_the_workflows_people_can_run(self):
        root = self.repo('https://github.com/o/r.git')
        wf = root / '.github' / 'workflows'
        (wf / 'facilitator-award.yml').write_text("name: 'Facilitator: Award points'\non:\n  workflow_dispatch:\n")
        (wf / 'facilitator-action.yml').write_text("name: Facilitator action\non:\n  workflow_call:\n  workflow_dispatch:\n")
        (wf / 'grade.yml').write_text("name: Grade submissions\non:\n  workflow_dispatch:\n")
        (wf / 'test.yml').write_text("name: Test the grader\non:\n  workflow_dispatch:\n")
        (wf / 'pages.yml').write_text("name: Publish\non:\n  push:\n")
        forms = {f['file']: f for f in walkthrough.build_context(root)['forms']}
        self.assertEqual(set(forms), {'facilitator-award.yml', 'grade.yml', 'test.yml'})
        self.assertEqual(forms['facilitator-award.yml']['name'], 'Facilitator: Award points')
        self.assertEqual(forms['facilitator-award.yml']['url'], 'https://github.com/o/r/actions/workflows/facilitator-award.yml')

    def test_lessons_carry_submission_counts(self):
        root = self.repo()
        (root / 'lessons.json').write_text(json.dumps([{'key': 'a', 'label': 'A', 'repo': 'o/a', 'check': 'none'}]))
        (root / 'grader' / 'results.json').write_text(json.dumps({'submissions': {
            'o/a#1': {'task': 'a', 'login': 'x', 'passed': True},
            'o/a#2': {'task': 'a', 'login': 'x', 'passed': False},
            'o/a#3': {'task': 'a', 'login': 'y', 'passed': None},
            'o/b#1': {'task': 'b', 'login': 'z', 'passed': True}}}))
        lesson = walkthrough.build_context(root)['lessons'][0]
        self.assertEqual((lesson['submissions'], lesson['people'], lesson['correct'], lesson['repo_url']), (3, 2, 1, 'https://github.com/o/a'))

    def test_recent_actions_newest_first_without_the_undo_data(self):
        root = self.repo()
        (root / 'grader' / 'history.json').write_text(json.dumps(
            [{'at': str(i), 'by': 'f', 'action': f'change {i}', 'changes': [{'before': {}, 'after': {}}]} for i in range(5)]))
        recent = walkthrough.build_context(root)['recent_actions']
        self.assertEqual([r['action'] for r in recent], ['change 4', 'change 3', 'change 2'])
        self.assertNotIn('changes', recent[0])

    def test_missing_or_broken_files_give_empty_sections(self):
        root = self.repo()
        ctx = walkthrough.build_context(root)
        self.assertEqual((ctx['lessons'], ctx['recent_actions']), ([], []))

    def test_a_broken_lessons_file_is_explained_not_hidden(self):
        root = self.repo()
        (root / 'lessons.json').write_text(json.dumps([{'key': 'Bad Key', 'label': 'x', 'repo': 'o/r'}]))
        ctx = walkthrough.build_context(root)
        self.assertEqual(ctx['lessons'], [])
        self.assertIn('must be lowercase', ctx['lesson_problems'][0])

    def test_real_repository(self):
        ctx = walkthrough.build_context(REPO)
        self.assertEqual([l['key'] for l in ctx['lessons']], [l['key'] for l in json.loads((REPO / 'lessons.json').read_text())])
        self.assertTrue(any(f['file'] == 'facilitator-undo.yml' for f in ctx['forms']))


class SampleDataTests(unittest.TestCase):
    KEYS = ['fizzbuzz', 'rest_api', 'framework_upgrade', 'container_image', 'kafka']

    def parsed(self):
        sys.path.insert(0, str(REPO / 'grader'))
        import rules
        return rules.read_participants(walkthrough.sample_csv(self.KEYS), self.KEYS)['rows']

    def test_has_a_column_for_every_lesson(self):
        head = walkthrough.sample_csv(self.KEYS).splitlines()[0].split(',')
        self.assertEqual(head, ['name', 'github', *self.KEYS, 'stretch', 'helped', 'bonus'])

    def test_shows_every_state_the_tour_talks_about(self):
        rows = self.parsed()
        statuses = {s for r in rows for s in r['tracks'].values()}
        self.assertEqual(statuses, {'none', 'submitted', 'correct'})
        self.assertTrue(all(s == 'correct' for s in rows[0]['tracks'].values()), 'someone is correct on every exercise')
        self.assertTrue(all(any(r[k] for r in rows) for k in ('stretch', 'helped', 'bonus')))
        self.assertGreaterEqual(len(rows), 8)

    def test_is_the_same_every_time(self):
        self.assertEqual(walkthrough.sample_csv(self.KEYS), walkthrough.sample_csv(self.KEYS))

    def test_names_are_made_up(self):
        real = (REPO / 'participants.csv').read_text().lower()
        for r in self.parsed():
            self.assertNotIn(r['name'].lower(), real)


class ServerTests(unittest.TestCase):
    def setUp(self, sample=True):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(walkthrough.Handler, directory=str(REPO), sample=sample))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.headers, r.read()

    def test_serves_the_context_fresh_each_time(self):
        status, headers, body = self.get(walkthrough.CONTEXT_PATH)
        self.assertEqual((status, headers['Content-Type'], headers['Cache-Control']), (200, 'application/json', 'no-store'))
        self.assertIn('lessons', json.loads(body))

    def test_does_not_serve_the_git_folder(self):
        for path in ('/.git/config', '/.git', '/.git/HEAD?x=1'):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.get(path)
            e.exception.close()
            self.assertEqual(e.exception.code, 404, path)

    def test_serves_the_walkthrough_and_the_leaderboard(self):
        for path in ('/walkthrough/', '/walkthrough/steps.js', '/walkthrough/tour.js', '/index.html', '/scoring.js', '/participants.csv', '/lessons.json'):
            self.assertEqual(self.get(path)[0], 200, path)

    def test_the_leaderboard_shows_sample_people_by_default(self):
        body = self.get('/participants.csv')[2].decode()
        self.assertIn(walkthrough.SAMPLE_PEOPLE[0][0], body)
        self.assertTrue(json.loads(self.get(walkthrough.CONTEXT_PATH)[2])['sample'])

    def test_real_scores_when_asked(self):
        self.tearDown_server()
        self.setUp(sample=False)
        self.assertEqual(self.get('/participants.csv')[2].decode(), (REPO / 'participants.csv').read_text())
        self.assertFalse(json.loads(self.get(walkthrough.CONTEXT_PATH)[2])['sample'])

    def tearDown_server(self):
        self.server.shutdown()
        self.server.server_close()

    def test_free_port_falls_back_when_taken(self):
        taken = self.server.server_address[1]
        self.assertNotEqual(walkthrough.free_port(taken), taken)


STEPS_IN_NODE = r'''
const fs = require('fs'), vm = require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));  // like <script src="../scoring.js">: a classic script
import(process.argv[2]).then((m) => {
  const ctx = JSON.parse(fs.readFileSync(0, 'utf8'));
  const steps = m.steps(ctx);
  process.stdout.write(JSON.stringify(steps.map((s) => [s.title, s.text + (s.stage || '')])));
}).catch((e) => { console.error(e.stack || e); process.exit(1); });
'''


@unittest.skipUnless(shutil.which('node'), 'needs Node.js')
class StepsRenderTests(unittest.TestCase):
    """steps.js run the way the browser runs it: scoring.js loaded first as a classic script."""

    def render(self, ctx):
        r = subprocess.run(['node', '-e', STEPS_IN_NODE, str(REPO / 'scoring.js'), (REPO / 'walkthrough' / 'steps.js').as_uri()],
                           input=json.dumps(ctx), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return dict(json.loads(r.stdout))

    def test_renders_for_the_real_repository(self):
        steps = self.render(walkthrough.build_context(REPO))
        self.assertIn('lessons.json: the list of exercises', steps)
        self.assertIn('made-up example people', steps['Welcome'])
        self.assertIn('<b>30</b> when correct', steps['How points work'])

    def test_explains_a_broken_lessons_file(self):
        ctx = {**walkthrough.build_context(REPO), 'lessons': [], 'lesson_problems': ['lesson 2 (Bad): key "Bad" must be lowercase']}
        self.assertIn('lessons.json has problems right now', self.render(ctx)['lessons.json: the list of exercises'])

    def test_real_scores_mode_says_so(self):
        steps = self.render({**walkthrough.build_context(REPO), 'sample': False})
        self.assertIn('real scores', steps['Welcome'])


class ContractTests(unittest.TestCase):
    """walkthrough/steps.js points at the leaderboard only through data-tour names, and links to repo files."""

    def test_every_step_target_exists_in_the_leaderboard(self):
        page = (REPO / 'index.html').read_text()
        anchors = set(re.findall(r'data-tour="([\w-]+)"', page)) | set(re.findall(r"dataset\.tour = '([\w-]+)'", page))
        targets = {name for t in re.findall(r"target: (\[[^\]]*\]|'[\w-]+')", STEPS) for name in re.findall(r"'([\w-]+)'", t)}
        self.assertTrue(targets)
        self.assertEqual(targets - anchors, set(), 'steps.js targets missing from index.html')

    def test_every_linked_file_exists(self):
        paths = set(re.findall(r"fileLink\(ctx, '([^']+)'", STEPS))
        self.assertTrue(paths)
        for p in paths:
            self.assertTrue((REPO / p).exists() or p == 'grader/history.json', p)  # history.json appears after the first change

    def test_every_facilitator_form_is_described(self):
        help_for = set(re.findall(r"'([\w-]+\.yml)':", STEPS))
        forms = {p.name for p in (REPO / '.github' / 'workflows').glob('facilitator-*.yml')} - {'facilitator-action.yml'}
        self.assertEqual(forms | {'grade.yml'}, help_for, 'steps.js FORM_HELP must list exactly the facilitator forms')


if __name__ == '__main__':
    unittest.main()
