"""Pin a lesson to the exercise repository's own tests.

Most exercises ship the tests a participant has to make pass. `pin` copies them, as they are at one commit of
the exercise repository, into the lesson's test files (grader/fixtures/<key>/), and sets the lesson to the
`tests` level. Every submission is then graded with those copies, so a participant editing the tests does not
help, and a later change to the exercise repository regrades nobody until someone pins again.
"""
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import executor
import lessons
from checks.toolkit import SKIP_DIRS, CheckFailed, gradle_project

GENERIC = ('none', 'build', 'tests')  # levels pinning may replace; a custom check is never replaced silently


class PinFailed(Exception):
    pass


def pin(lessons_file, fixtures, key, commit=None, url=None):
    """Copy the tests of lesson `key`'s repository at `commit` (a full commit id; default: its latest commit)
    into fixtures/<key>/ and record the commit in lessons.json. Returns the commit pinned. On failure nothing
    is changed."""
    if commit and not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise PinFailed('Give the full 40-character commit id, or leave it out to pin the latest commit.')
    try:
        lesson = next((l for l in lessons.load(lessons_file, fixtures) if l.key == key), None)
    except lessons.LessonsInvalid as e:
        raise PinFailed(str(e)) from None
    if lesson is None:
        raise PinFailed(f'No lesson "{key}" in lessons.json.')
    if lesson.check not in GENERIC:
        raise PinFailed(f'{key} uses the custom check "{lesson.check}", which pinning would replace. '
                        'Set its check to "none" in lessons.json first if that is what you want.')
    fixtures = Path(fixtures)
    fixtures.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory(dir=fixtures, prefix='.pin-') as staged:
        sha = _fetch(url or f'https://github.com/{lesson.repo}.git', commit or 'HEAD', Path(tmp))
        try:
            project = gradle_project(tmp)  # the same folder grading copies the test files into
        except CheckFailed:
            raise PinFailed(f'{lesson.repo} has no Gradle project at {sha[:7]}.') from None
        new = Path(staged) / key
        try:
            for tests in _test_folders(project):
                shutil.copytree(tests, new / tests.relative_to(project), dirs_exist_ok=True)
        except OSError as e:
            raise PinFailed(f'Could not copy the tests: {e}') from None
        if not new.is_dir() or not any(f.is_file() for f in new.rglob('*')):
            raise PinFailed(f'{lesson.repo} has no tests (src/test/) at {sha[:7]}.')
        _swap(new, fixtures / key, Path(staged) / 'old')
    items = json.loads(Path(lessons_file).read_text(encoding='utf-8'))
    item = next(i for i in items if i.get('key') == key)
    item['check'], item['tests_commit'] = 'tests', sha
    Path(lessons_file).write_text(json.dumps(items, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return sha


def _test_folders(project):
    """Every src/test/ under the project, including those of subprojects such as app/."""
    for dirpath, dirnames, _ in os.walk(project):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        here = Path(dirpath)
        if here.name == 'test' and here.parent.name == 'src':
            dirnames[:] = []
            yield here


def _swap(new, dest, old):
    """Put `new` at `dest`; whatever was there is moved aside first and removed with the staging folder."""
    if dest.exists():
        dest.rename(old)
    new.rename(dest)


def _fetch(url, ref, dest):
    for args in (['init', '-q'], ['fetch', '-q', '--depth', '1', url, ref], ['checkout', '-q', 'FETCH_HEAD'], ['rev-parse', 'HEAD']):
        code, out = executor.host_run(['git', *args], cwd=dest, timeout=600)
        if code:
            raise PinFailed(f'Could not fetch {ref} from {url}: {out.strip()}')
    return out.strip()
