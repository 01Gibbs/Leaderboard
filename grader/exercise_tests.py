"""Pin a lesson to the exercise repository's own tests.

Most exercises ship the tests a participant has to make pass. `pin` copies them, as they are at one commit of
the exercise repository, into the lesson's test files (grader/fixtures/<key>/), and sets the lesson to the
`tests` level. Every submission is then graded with those copies, so a participant editing the tests does not
help, and a later change to the exercise repository regrades nobody until someone pins again.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import executor
from checks.toolkit import find_project


class PinFailed(Exception):
    pass


def pin(lessons_file, fixtures, key, commit=None, url=None):
    """Copy the tests of lesson `key`'s repository at `commit` (default: its latest commit) into fixtures/<key>/.
    Returns the commit pinned."""
    items = json.loads(Path(lessons_file).read_text(encoding='utf-8'))
    item = next((i for i in items if i.get('key') == key), None)
    if item is None:
        raise PinFailed(f'No lesson "{key}" in lessons.json.')
    url = url or f'https://github.com/{item["repo"]}.git'
    with tempfile.TemporaryDirectory() as tmp:
        sha = _fetch(url, commit or 'HEAD', Path(tmp))
        project = find_project(tmp, 'gradlew', 'build.gradle', 'build.gradle.kts')
        if not project:
            raise PinFailed(f'{item["repo"]} has no Gradle project at {sha[:7]}.')
        tests = Path(project) / 'src' / 'test'
        if not tests.is_dir() or not any(f.is_file() for f in tests.rglob('*')):
            raise PinFailed(f'{item["repo"]} has no tests (src/test/) at {sha[:7]}.')
        dest = Path(fixtures) / key
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(tests, dest / 'src' / 'test')
    item['check'], item['tests_commit'] = 'tests', sha
    Path(lessons_file).write_text(json.dumps(items, indent=2) + '\n', encoding='utf-8')
    return sha


def _fetch(url, ref, dest):
    for args in (['init', '-q'], ['fetch', '-q', '--depth', '1', url, ref], ['checkout', '-q', 'FETCH_HEAD']):
        code, out = executor.host_run(['git', *args], cwd=dest, timeout=600)
        if code:
            raise PinFailed(f'Could not fetch {ref} from {url}: {out.strip()}')
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=dest, check=True, capture_output=True, text=True).stdout.strip()
