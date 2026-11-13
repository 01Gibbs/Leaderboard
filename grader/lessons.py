"""Lessons: the exercises on the leaderboard, as listed in lessons.json.

Everything else (the grader, the roster, the walkthrough) reads lessons through `load()`, so a mistake in
lessons.json is reported the same way everywhere, with every problem listed at once.
"""
import hashlib
import inspect
import json
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import checks
import rules

HERE = Path(__file__).resolve().parent
LESSONS_FILE = HERE.parent / 'lessons.json'
FIXTURES = HERE / 'fixtures'
RESERVED = tuple(rules.BASE_COLUMNS + rules.COUNTS)  # participants.csv columns that are not lessons
# Used by every check, so a change to any of these regrades every automated lesson.
SHARED_CODE = [HERE / 'executor.py'] + [HERE / 'checks' / f'{m}.py' for m in checks.SHARED]


class LessonsInvalid(Exception):
    def __init__(self, problems):
        self.problems = problems
        super().__init__('lessons.json has problems:\n  ' + '\n  '.join(problems))


@dataclass(frozen=True)
class Lesson:
    key: str          # the participants.csv column
    label: str        # shown on the page
    repo: str         # owner/name: where participants open pull requests
    check: str        # how "correct" is decided: 'none' or a name in checks.CHECKS (a module in grader/checks/)
    test_files: Path  # our files for this lesson: tests copied over each submission, or a check's reference files

    @property
    def runner(self):
        """The check function, or None when a facilitator marks the lesson by hand."""
        return checks.CHECKS.get(self.check)

    @cached_property
    def version(self):
        """Changes whenever anything that decides this lesson's results changes: its check name, its check's
        module (grader/checks/<check>.py, constants included), the code every check shares (SHARED_CODE), or
        its test files. Other checks' modules are left out, so editing one check regrades only its lessons.
        Results graded under another version are graded again."""
        h = hashlib.sha256(self.check.encode())
        if self.runner:
            h.update(Path(inspect.getsourcefile(self.runner)).read_bytes())
            for f in SHARED_CODE:
                h.update(Path(f).read_bytes())
        if self.test_files.is_dir():
            for f in sorted(self.test_files.rglob('*')):
                if f.is_file():
                    h.update(f.relative_to(self.test_files).as_posix().encode() + f.read_bytes())
        return h.hexdigest()[:12]


def load(path=LESSONS_FILE, fixtures=FIXTURES):
    """The lessons, in order. Raises LessonsInvalid listing every problem."""
    try:
        items = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise LessonsInvalid([f'cannot read it as JSON ({e})']) from None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise LessonsInvalid(['it must be a list of lessons, each one {"key": ..., "label": ..., "repo": ..., "check": ...}'])

    problems, seen, out = [], set(), []
    for n, item in enumerate(items, 1):
        key, check = item.get('key', ''), item.get('check', 'none')
        where = f'lesson {n}' + (f' ({key})' if key else '')
        if not re.fullmatch(r'[a-z][a-z0-9_]*', key):
            problems.append(f'{where}: key "{key}" must be lowercase letters, digits and _')
        elif key in seen or key in RESERVED:
            problems.append(f'{where}: key "{key}" is already used')
        seen.add(key)
        if not item.get('label'):
            problems.append(f'{where}: needs a label')
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', item.get('repo', '')):
            problems.append(f'{where}: repo must look like owner/name')
        if check != 'none' and check not in checks.CHECKS:
            problems.append(f'{where}: check must be one of none, {", ".join(checks.CHECKS)}')
        out.append(Lesson(key, item.get('label', ''), item.get('repo', ''), check, Path(fixtures) / key))
    if problems:
        raise LessonsInvalid(problems)
    return out
