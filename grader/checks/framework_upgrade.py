"""framework_upgrade: the app is moved to Spring Boot 3.5 (jakarta imports, no removed properties, a fixed
commons-text), our copy of its tests pass, and its API still works, now behind a login."""
import re
import zipfile
from pathlib import Path

from .toolkit import IN_MEMORY_DB, Jar, RunningApp, boot_jar, employee_api_checks, expect, gradle, gradle_project, http, overlay

REMOVED_PROPERTIES = ['server.max-http-header-size', 'spring.jpa.hibernate.use-new-id-generator-mappings']


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', v)[:3])


def check(ws, lesson):
    project = gradle_project(ws.path)
    problems = []
    for f in (project / 'src').rglob('*.java') if (project / 'src').exists() else []:
        if re.search(r'\bjavax\.(persistence|validation)\b', f.read_text(errors='replace')):
            problems.append(f'{f.relative_to(project)} still uses javax.persistence or javax.validation')
    for props in (project / 'src' / 'main' / 'resources').glob('application*.properties'):
        text = props.read_text(errors='replace')
        for p in REMOVED_PROPERTIES:
            if re.search(rf'^\s*{re.escape(p)}\s*[=:]', text, re.M):
                problems.append(f'{props.name} still sets the removed property {p}')

    overlay(lesson.test_files, project)  # our copy of the tests, so editing them cannot make it pass
    gradle(ws, project, ['test', 'bootJar'])
    jar = boot_jar(project)

    libs = [Path(n).name for n in zipfile.ZipFile(jar).namelist() if n.startswith('BOOT-INF/lib/')]
    boot = next((n for n in libs if re.fullmatch(r'spring-boot-\d.*\.jar', n)), None)
    if not boot or version_tuple(boot)[:2] != (3, 5):
        problems.append(f'should run on Spring Boot 3.5.x (found {boot or "none"})')
    text_lib = next((n for n in libs if n.startswith('commons-text-')), None)
    if text_lib and version_tuple(text_lib) < (1, 10, 0):
        problems.append(f'{text_lib} is vulnerable (CVE-2022-42889); use 1.10.0 or newer')

    with RunningApp(Jar(ws, jar, IN_MEMORY_DB)) as app:
        employee_api_checks(app.base, problems, auth=('admin', 'admin123'), sent_name='asha RAO')
        status, _ = http('GET', app.base + '/api/employees')
        expect(problems, status == 401, f'GET /api/employees without credentials should return 401 (got {status})')
    return not problems, problems or ['builds on Spring Boot 3.5, our tests pass, API unchanged']
