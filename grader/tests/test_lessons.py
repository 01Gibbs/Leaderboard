"""The Lesson module: lessons.json loaded, validated, and resolved to checks, test files and versions.

Run: python3 -m unittest discover grader/tests
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

GRADER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GRADER))
import lessons  # noqa: E402

VALID = [
    {'key': 'fizzbuzz', 'label': 'FizzBuzz', 'repo': 'o/fizz', 'check': 'fizzbuzz'},
    {'key': 'manual', 'label': 'Manual', 'repo': 'o/manual', 'check': 'none'},
    {'key': 'upgrade', 'label': 'Upgrade', 'repo': 'o/up', 'check': 'tests'},
]


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.file = self.dir / 'lessons.json'
        self.fixtures = self.dir / 'fixtures'
        self.write(VALID)

    def write(self, items):
        self.file.write_text(json.dumps(items))

    def load(self):
        return lessons.load(self.file, fixtures=self.fixtures)


class LoadingTests(Sandbox):
    def test_valid_lessons_load_in_order(self):
        self.assertEqual([l.key for l in self.load()], ['fizzbuzz', 'manual', 'upgrade'])
        self.assertEqual(self.load()[0].label, 'FizzBuzz')
        self.assertEqual(self.load()[0].repo, 'o/fizz')

    def test_every_problem_is_reported_at_once(self):
        self.write([{'key': 'Bad Key', 'label': 'x', 'repo': 'o/r', 'check': 'none'},
                    {'key': 'helped', 'label': 'x', 'repo': 'o/r', 'check': 'none'},
                    {'key': 'ok', 'label': '', 'repo': 'not-a-repo', 'check': 'magic'},
                    {'key': 'ok', 'label': 'Again', 'repo': 'o/r'}])
        with self.assertRaises(lessons.LessonsInvalid) as e:
            self.load()
        msg = str(e.exception)
        for part in ('lowercase', '"helped" is already used', 'owner/name', 'check must be one of', 'needs a label', '"ok" is already used'):
            self.assertIn(part, msg)
        self.assertEqual(len(e.exception.problems), 6)

    def test_missing_check_means_none(self):
        self.write([{'key': 'a', 'label': 'A', 'repo': 'o/a'}])
        self.assertEqual(self.load()[0].check, 'none')

    def test_not_a_list_or_not_json(self):
        for text in ('{not json', '{"key": "a"}'):
            self.file.write_text(text)
            with self.assertRaises(lessons.LessonsInvalid):
                self.load()

    def test_the_real_lessons_file_is_valid(self):
        self.assertTrue(lessons.load())


class CheckTests(Sandbox):
    def test_runner_is_the_named_check_or_none(self):
        import checks
        by_key = {l.key: l for l in self.load()}
        self.assertIs(by_key['fizzbuzz'].runner, checks.CHECKS['fizzbuzz'])
        self.assertIsNone(by_key['manual'].runner)

    def test_test_files_live_in_the_lessons_fixture_folder(self):
        self.assertEqual(self.load()[2].test_files, self.fixtures / 'upgrade')


class VersionTests(Sandbox):
    """A lesson's version changes when anything deciding its result changes, and only then."""

    def versions(self):
        return {l.key: l.version for l in self.load()}

    def test_stable_when_nothing_changes(self):
        self.assertEqual(self.versions(), self.versions())

    def test_changing_one_lessons_test_files_regrades_only_that_lesson(self):
        before = self.versions()
        (self.fixtures / 'upgrade').mkdir(parents=True)
        (self.fixtures / 'upgrade' / 'ApiTest.java').write_text('class ApiTest {}')
        after = self.versions()
        self.assertNotEqual(before['upgrade'], after['upgrade'])
        self.assertEqual((before['fizzbuzz'], before['manual']), (after['fizzbuzz'], after['manual']))

    def test_changing_one_lessons_check_regrades_only_that_lesson(self):
        before = self.versions()
        self.write([VALID[0], {**VALID[1], 'check': 'build'}, VALID[2]])
        after = self.versions()
        self.assertNotEqual(before['manual'], after['manual'])
        self.assertEqual((before['fizzbuzz'], before['upgrade']), (after['fizzbuzz'], after['upgrade']))

    def test_editing_one_check_regrades_only_its_lesson_but_shared_code_regrades_all(self):
        import importlib
        import checks
        module = self.dir / 'stand_in_checks.py'
        source = ('def helper():\n    return 1\n\n\n'
                  'def check_a(ws, lesson):\n    return helper() == 1, ["a"]\n\n\n'
                  'def check_b(ws, lesson):\n    return True, ["b"]\n')
        sys.path.insert(0, str(self.dir))
        self.addCleanup(sys.path.remove, str(self.dir))

        def versions(text):
            module.write_text(text)
            sys.modules.pop('stand_in_checks', None)
            m = importlib.import_module('stand_in_checks')
            with mock.patch.dict(checks.CHECKS, {'check_a': m.check_a, 'check_b': m.check_b}):
                self.write([{'key': 'a', 'label': 'A', 'repo': 'o/a', 'check': 'check_a'},
                            {'key': 'b', 'label': 'B', 'repo': 'o/b', 'check': 'check_b'}])
                return {l.key: l.version for l in self.load()}

        before = versions(source)
        after_a = versions(source.replace('["a"]', '["a, edited"]'))
        self.assertNotEqual(before['a'], after_a['a'])
        self.assertEqual(before['b'], after_a['b'])
        after_helper = versions(source.replace('return 1', 'return 2'))
        self.assertNotEqual(before['a'], after_helper['a'])
        self.assertNotEqual(before['b'], after_helper['b'])

    def test_the_code_that_runs_participant_code_is_part_of_every_version(self):
        with mock.patch.object(lessons, 'SHARED_CODE', [self.dir / 'executor_stand_in.py']):
            (self.dir / 'executor_stand_in.py').write_text('x = 1')
            before = {l.key: l.version for l in self.load() if l.runner}
            (self.dir / 'executor_stand_in.py').write_text('x = 2')
            after = {l.key: l.version for l in self.load() if l.runner}
        self.assertTrue(all(before[k] != after[k] for k in before))

    def test_label_does_not_affect_the_version(self):
        before = self.versions()
        self.write([{**VALID[0], 'label': 'Fizz Buzz!'}, VALID[1], VALID[2]])
        self.assertEqual(before['fizzbuzz'], self.versions()['fizzbuzz'])


if __name__ == '__main__':
    unittest.main()
