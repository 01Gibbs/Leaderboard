"""tests: the lesson's test files (grader/fixtures/<lesson key>/) are copied over the submission, then
`gradle test` must pass. A generic level any lesson can use."""
from .toolkit import gradle, gradle_project, overlay


def check(ws, lesson):
    project = gradle_project(ws.path)
    overlay(lesson.test_files, project)
    gradle(ws, project, ['test'])
    return True, ['our tests pass']
