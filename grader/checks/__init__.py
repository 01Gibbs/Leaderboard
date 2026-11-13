"""Automated checks. A lesson's "check" in lessons.json names a module in this folder: checks/<name>.py, with a
function check(ws, lesson). Adding a module adds the check; CHECKS finds it by its file name. `build` and
`tests` are generic levels any lesson can use without writing Python; the others are custom checks for what
a generic level cannot do, such as calling the running app.

Each check is check(ws, lesson) -> (passed, reasons), or raises CheckFailed with a reason the participant can
act on. `ws` is an executor.Workspace holding the checked-out pull request at ws.path; participant code runs
only through ws.run and ws.start. A check never trusts the participant's own tests: it runs ours, or calls
the running application over HTTP.

A lesson's version (lessons.Lesson.version) covers its check's module and the SHARED modules, so editing one
check, constants included, regrades only the lessons that use it. For that to hold, a check imports only from
the SHARED modules, never from another check.
"""
import importlib
import pkgutil

from .toolkit import CheckFailed, jdks, tail  # noqa: F401  (what the grader and tests use)

SHARED = ['toolkit']  # modules here that every check is built from, rather than checks themselves

CHECKS = {m.name: importlib.import_module(f'{__name__}.{m.name}').check
          for m in pkgutil.iter_modules(__path__) if m.name not in SHARED}
