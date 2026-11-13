"""Pinning a lesson to the exercise repository's own tests: the files a submission is graded with come from
that repository at one recorded commit, so a new lesson needs no hand-written test files.

Run: python3 -m unittest discover grader/tests
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GRADER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GRADER))
import exercise_tests  # noqa: E402


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


class Exercise:
    """A local stand-in for an exercise repository on GitHub: a Gradle project in a subfolder."""

    def __init__(self, root):
        self.path = root / 'exercise'
        self.path.mkdir()
        git(self.path, 'init', '-q', '-b', 'main')
        git(self.path, 'config', 'user.email', 'author@example.com')
        git(self.path, 'config', 'user.name', 'Author')
        git(self.path, 'config', 'uploadpack.allowAnySHA1InWant', 'true')  # GitHub allows fetching a commit by id

    def commit(self, files, message='change'):
        for rel, text in files.items():
            f = self.path / rel
            if text is None:
                f.unlink()
                continue
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
        git(self.path, 'add', '-A')
        git(self.path, 'commit', '-q', '-m', message)
        return git(self.path, 'rev-parse', 'HEAD')


STARTER = {
    'README.md': 'Make the tests pass.',
    'app/build.gradle': "plugins { id 'java' }",
    'app/src/main/java/Greeter.java': 'class Greeter {}',
    'app/src/test/java/GreeterTest.java': 'class GreeterTest { /* v1 */ }',
    'app/src/test/resources/names.txt': 'Ada',
}


class PinTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.exercise = Exercise(self.dir)
        self.lessons_file = self.dir / 'lessons.json'
        self.fixtures = self.dir / 'fixtures'
        self.lessons_file.write_text(json.dumps([
            {'key': 'greeter', 'label': 'Greeter', 'repo': 'o/greeter', 'check': 'none'},
            {'key': 'other', 'label': 'Other', 'repo': 'o/other', 'check': 'build'},
        ], indent=2) + '\n')

    def pin(self, key='greeter', commit=None):
        return exercise_tests.pin(self.lessons_file, self.fixtures, key, commit, url=str(self.exercise.path))

    def fixture_files(self, key='greeter'):
        root = self.fixtures / key
        return {f.relative_to(root).as_posix(): f.read_text() for f in root.rglob('*') if f.is_file()}

    def test_copies_the_test_files_at_the_named_commit_relative_to_the_gradle_project(self):
        first = self.exercise.commit(STARTER)
        self.exercise.commit({'app/src/test/java/GreeterTest.java': 'class GreeterTest { /* v2 */ }'})
        self.pin(commit=first)
        self.assertEqual(self.fixture_files(), {
            'src/test/java/GreeterTest.java': 'class GreeterTest { /* v1 */ }',
            'src/test/resources/names.txt': 'Ada',
        })

    def test_records_the_commit_and_the_tests_level_and_leaves_other_lessons_alone(self):
        first = self.exercise.commit(STARTER)
        self.assertEqual(self.pin(commit=first), first)
        self.assertEqual(json.loads(self.lessons_file.read_text()), [
            {'key': 'greeter', 'label': 'Greeter', 'repo': 'o/greeter', 'check': 'tests', 'tests_commit': first},
            {'key': 'other', 'label': 'Other', 'repo': 'o/other', 'check': 'build'},
        ])

    def test_pins_the_latest_commit_by_default_and_drops_tests_removed_since(self):
        self.exercise.commit(STARTER)
        self.pin()
        latest = self.exercise.commit({'app/src/test/resources/names.txt': None})
        self.assertEqual(self.pin(), latest)
        self.assertEqual(set(self.fixture_files()), {'src/test/java/GreeterTest.java'})

    def test_a_repository_without_tests_or_gradle_changes_nothing_and_says_why(self):
        self.exercise.commit(STARTER)
        self.pin()
        before = self.lessons_file.read_text(), self.fixture_files()
        for change, reason in (({'app/src/test/java/GreeterTest.java': None, 'app/src/test/resources/names.txt': None}, 'no tests'),
                               ({'app/build.gradle': None}, 'no Gradle project')):
            self.exercise.commit(change)
            with self.assertRaisesRegex(exercise_tests.PinFailed, reason):
                self.pin()
            self.assertEqual((self.lessons_file.read_text(), self.fixture_files()), before)

    def test_tests_below_a_root_gradle_wrapper_keep_their_path_from_the_root(self):
        """`gradle init` puts gradlew at the root and the tests in app/; grading finds the root, so paths start there."""
        self.exercise.commit({**STARTER, 'gradlew': '#!/bin/sh', 'settings.gradle': "include 'app'"})
        self.pin()
        self.assertEqual(set(self.fixture_files()), {'app/src/test/java/GreeterTest.java', 'app/src/test/resources/names.txt'})

    def test_a_shortened_commit_id_is_refused_before_fetching(self):
        first = self.exercise.commit(STARTER)
        with self.assertRaisesRegex(exercise_tests.PinFailed, 'full 40-character commit id'):
            self.pin(commit=first[:7])

    def test_a_lesson_with_a_custom_check_is_not_replaced(self):
        self.exercise.commit(STARTER)
        self.lessons_file.write_text(json.dumps([{'key': 'greeter', 'label': 'Greeter', 'repo': 'o/greeter', 'check': 'fizzbuzz'}]))
        before = self.lessons_file.read_text()
        with self.assertRaisesRegex(exercise_tests.PinFailed, 'custom check "fizzbuzz"'):
            self.pin()
        self.assertEqual(self.lessons_file.read_text(), before)
        self.assertFalse((self.fixtures / 'greeter').exists())

    def test_a_broken_lessons_file_is_explained(self):
        self.lessons_file.write_text('[{"key": "greeter"}]')
        with self.assertRaisesRegex(exercise_tests.PinFailed, 'needs a label'):
            self.pin()

    def test_unknown_lesson(self):
        with self.assertRaisesRegex(exercise_tests.PinFailed, 'No lesson "nope"'):
            self.pin('nope')


if __name__ == '__main__':
    unittest.main()
