"""rest_api: the submission's app, started from its bootJar, does what the REST API exercise asks
(employee_api_checks)."""
from .toolkit import IN_MEMORY_DB, Jar, RunningApp, boot_jar, employee_api_checks, gradle, gradle_project


def check(ws, lesson):
    project = gradle_project(ws.path)
    gradle(ws, project, ['bootJar', '-x', 'test'])
    problems = []
    with RunningApp(Jar(ws, boot_jar(project), IN_MEMORY_DB)) as app:
        employee_api_checks(app.base, problems)
    return not problems, problems or ['all API checks pass']
