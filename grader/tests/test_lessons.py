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

    def test_tests_commit_is_a_full_commit_id_on_a_tests_lesson(self):
        sha = 'a' * 40
        self.write([{'key': 'a', 'label': 'A', 'repo': 'o/a', 'check': 'tests', 'tests_commit': sha}])
        self.assertEqual(self.load()[0].check, 'tests')
        for item in ({'check': 'tests', 'tests_commit': 'main'}, {'check': 'build', 'tests_commit': sha}):
            self.write([{'key': 'a', 'label': 'A', 'repo': 'o/a', **item}])
            with self.assertRaisesRegex(lessons.LessonsInvalid, 'tests_commit'):
                self.load()

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

    def test_each_check_is_a_module_named_after_it(self):
        import checks
        modules = {f.stem for f in (lessons.HERE / 'checks').glob('*.py')} - {'__init__', *checks.SHARED}
        self.assertEqual(set(checks.CHECKS), modules)
        for name, runner in checks.CHECKS.items():
            self.assertEqual(runner.__module__, f'checks.{name}')

    def test_a_check_imports_only_the_shared_modules_so_its_version_covers_its_code(self):
        import re
        import checks
        for name in checks.CHECKS:
            source = (lessons.HERE / 'checks' / f'{name}.py').read_text()
            used = set(re.findall(r'^from \.(\w+) import|^from checks\.(\w+) import', source, re.M))
            others = {m for pair in used for m in pair if m} - set(checks.SHARED)
            self.assertEqual(others, set(), f'checks/{name}.py imports another check')

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

    def test_editing_a_check_module_regrades_only_its_lessons(self):
        import importlib
        import checks
        source = 'LIMIT = 1\n\n\ndef check(ws, lesson):\n    return LIMIT == 1, ["ok"]\n'
        sys.path.insert(0, str(self.dir))
        self.addCleanup(sys.path.remove, str(self.dir))

        def versions(a_text, b_text):
            stand_ins = {}
            for name, text in (('stand_in_a', a_text), ('stand_in_b', b_text)):
                (self.dir / f'{name}.py').write_text(text)
                sys.modules.pop(name, None)
                stand_ins[name] = importlib.import_module(name).check
            with mock.patch.dict(checks.CHECKS, {'check_a': stand_ins['stand_in_a'], 'check_b': stand_ins['stand_in_b']}):
                self.write([{'key': 'a', 'label': 'A', 'repo': 'o/a', 'check': 'check_a'},
                            {'key': 'b', 'label': 'B', 'repo': 'o/b', 'check': 'check_b'}])
                return {l.key: l.version for l in self.load()}

        before = versions(source, source)
        after = versions(source.replace('LIMIT = 1', 'LIMIT = 2'), source)  # a constant, not just the function
        self.assertNotEqual(before['a'], after['a'])
        self.assertEqual(before['b'], after['b'])

    def test_the_toolkit_and_the_executor_are_shared_by_every_check(self):
        self.assertIn(lessons.HERE / 'executor.py', lessons.SHARED_CODE)
        self.assertIn(lessons.HERE / 'checks' / 'toolkit.py', lessons.SHARED_CODE)
        self.assertTrue(all(p.exists() for p in lessons.SHARED_CODE))

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
