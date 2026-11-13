"""build: the submission's Gradle project builds. A generic level any lesson can use."""
from .toolkit import gradle, gradle_project


def check(ws, lesson):
    gradle(ws, gradle_project(ws.path), ['assemble'])
    return True, ['the project builds']
