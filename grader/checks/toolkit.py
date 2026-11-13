"""The toolkit every check is built from: finding the project, running Gradle with whichever JDK works, copying
our test files over a submission, and RunningApp (Jar and Container adapters) for calling a running app over
HTTP. Participant code runs only through the workspace (ws.run, ws.start), never directly.

A change here regrades every automated lesson (lessons.SHARED_CODE).
"""
import json
import os
import re
import shutil
import socket
import time
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

from executor import host_run

GRADER = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get('GRADER_CACHE') or GRADER / '.cache')
SKIP_DIRS = {'.git', '.gradle', '.idea', '.vscode', 'build', 'bin', 'out', 'target', 'node_modules'}


class CheckFailed(Exception):
    pass


def jdks():
    """{major version: JDK home}, oldest first. setup-java exports JAVA_HOME_<version>_X64 for each one it installs."""
    found = {}
    for k, v in os.environ.items():
        m = re.fullmatch(r'JAVA_HOME_(\d+)_(X64|ARM64)', k)
        if m and Path(v, 'bin', 'java').exists():
            found[int(m.group(1))] = v
    if not found and os.environ.get('JAVA_HOME'):
        found[0] = os.environ['JAVA_HOME']
    return dict(sorted(found.items()))


def installed_jdks():
    homes = jdks()
    if not homes:
        raise CheckFailed('grader has no JDK installed')
    return homes


def newest_jdk():
    return list(installed_jdks().values())[-1]


def tail(text, n=12):
    return '\n'.join(text.strip().splitlines()[-n:])


def gradle_project(root):
    project = find_project(root, 'gradlew', 'build.gradle', 'build.gradle.kts')
    if not project:
        raise CheckFailed('no Gradle project found')
    return project


def find_project(root, *markers):
    """Shallowest directory under root that contains any of the marker files."""
    best = None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if any(m in filenames for m in markers):
            depth = len(Path(dirpath).relative_to(root).parts)
            if best is None or depth < best[0]:
                best = (depth, Path(dirpath))
    return best[1] if best else None


def find_file(root, name):
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if name in filenames:
            hits.append(Path(dirpath, name))
    # Prefer the conventional location, then the shallowest.
    hits.sort(key=lambda p: ('src/test/java' not in p.as_posix(), len(p.parts)))
    return hits[0] if hits else None


def gradle(ws, project, tasks, timeout=900):
    """Run the project's Gradle wrapper, trying each installed JDK until one works."""
    wrapper = project / 'gradlew'
    if not wrapper.exists():
        raise CheckFailed(f'no Gradle wrapper (gradlew) in {project.name or "the repository root"}')
    wrapper.chmod(0o755)
    homes = installed_jdks()
    toolchains = '-Porg.gradle.java.installations.paths=' + ','.join(homes.values())
    # Try 21 first: it runs every recent Gradle release. Fall back to the others.
    out = ''
    for _, home in sorted(homes.items(), key=lambda kv: kv[0] != 21):
        code, out = ws.run(['./gradlew', '--no-daemon', '-q', toolchains, *tasks], cwd=project, timeout=timeout, java_home=home)
        if code == 0:
            return
    raise CheckFailed('Gradle build failed:\n' + tail(out))


def overlay(test_files, project):
    """Copy our files over the submission, replacing any file of the same path."""
    if not test_files.is_dir() or not any(f.is_file() for f in test_files.rglob('*')):
        raise CheckFailed(f'grader setup: no test files in grader/fixtures/{test_files.name}/')
    for f in test_files.rglob('*'):
        if f.is_file():
            dest = project / f.relative_to(test_files)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dest)


def boot_jar(project):
    libs = project / 'build' / 'libs'
    jars = [j for j in libs.glob('*.jar') if not j.name.endswith('-plain.jar')] if libs.exists() else []
    if not jars:
        raise CheckFailed('bootJar produced no runnable jar in build/libs')
    return jars[0]


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def http(method, url, body=None, auth=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    if auth:
        req.add_header('Authorization', 'Basic ' + b64encode(f'{auth[0]}:{auth[1]}'.encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        with e:
            status, raw = e.code, e.read()
    try:
        return status, json.loads(raw or b'null')
    except ValueError:
        return status, raw.decode(errors='replace')


def wait_until_up(url, is_alive, timeout=150):
    end = time.time() + timeout
    while time.time() < end:
        if not is_alive():
            raise CheckFailed('the application exited during startup')
        try:
            http('GET', url, timeout=3)
            return
        except (urllib.error.URLError, ConnectionError, socket.timeout, OSError):
            time.sleep(2)
    raise CheckFailed(f'the application did not start within {timeout}s')


# ---------- the app under test ----------

class RunningApp:
    """An app under test: started, waited for until it answers `ready`, called over HTTP at .base, and always
    stopped, with its last log lines in the reason if it never came up. Adapters: Jar and Container."""

    def __init__(self, adapter, ready='/', timeout=150):
        self.adapter, self.ready, self.timeout = adapter, ready, timeout
        self.base = adapter.base

    def __enter__(self):
        self.adapter.start()
        try:
            wait_until_up(self.base + self.ready, self.adapter.alive, self.timeout)
        except CheckFailed as e:
            logs = self.adapter.logs()
            self.adapter.stop()  # `with` does not call __exit__ when __enter__ fails
            raise CheckFailed(f'{e}:\n' + tail(logs)) from None
        return self

    def __exit__(self, *exc):
        self.adapter.stop()


class Jar:
    """A Spring Boot jar, run as participant code in the workspace."""

    def __init__(self, ws, jar, args):
        self.ws, self.jar, self.args = ws, jar, args
        self.port = free_port()
        self.base = f'http://127.0.0.1:{self.port}'
        self.log, self.proc = ws.scratch() / 'app.log', None

    def start(self):
        java = Path(newest_jdk(), 'bin', 'java')
        self.proc = self.ws.start([str(java), '-jar', str(self.jar), f'--server.port={self.port}', *self.args],
                                  log=self.log, cwd=self.jar.parent)

    def alive(self):
        return self.proc.poll() is None

    def logs(self):
        return self.log.read_text(errors='replace') if self.log.exists() else ''

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.ws.stop(self.proc)


class Container:
    """A Docker image, run by Docker (its code runs inside the container, not on this machine)."""

    def __init__(self, tag, name, cwd, container_port=8080):
        self.tag, self.name, self.cwd, self.container_port = tag, name, cwd, container_port
        self.port = free_port()
        self.base = f'http://127.0.0.1:{self.port}'

    def start(self):
        code, out = host_run(['docker', 'run', '-d', '--name', self.name, '-p', f'127.0.0.1:{self.port}:{self.container_port}', self.tag],
                             cwd=self.cwd, timeout=60)
        if code:
            raise CheckFailed('docker run failed:\n' + tail(out))

    def alive(self):
        return host_run(['docker', 'inspect', '-f', '{{.State.Running}}', self.name], cwd=self.cwd, timeout=30)[1].strip() == 'true'

    def logs(self):
        return host_run(['docker', 'logs', self.name], cwd=self.cwd, timeout=30)[1]

    def stop(self):
        host_run(['docker', 'rm', '-f', self.name], cwd=self.cwd, timeout=60)


def expect(problems, ok, message):
    if not ok:
        problems.append(message)


def employee_api_checks(base, problems, auth=None, sent_name='Asha Rao', expected_name='Asha Rao'):
    """The behaviour the REST API exercise asks for. Later exercises must keep it."""
    url = base + '/api/employees'
    status, body = http('GET', url, auth=auth)
    expect(problems, status == 200 and isinstance(body, list), f'GET /api/employees should return 200 and a JSON array (got {status})')

    status, body = http('POST', url, {'name': sent_name, 'role': 'Engineer', 'onboardingDate': '2026-11-10'}, auth=auth)
    expect(problems, status == 201, f'POST with a valid employee should return 201 (got {status})')
    if status == 201:
        b = body if isinstance(body, dict) else {}
        expect(problems, b.get('id') is not None, 'POST response should include the generated id')
        expect(problems, b.get('name') == expected_name, f'POST response name should be "{expected_name}" (got {b.get("name")!r})')
        expect(problems, b.get('onboardingDate') == '2026-11-10', f'onboardingDate should come back as "2026-11-10" (got {b.get("onboardingDate")!r})')

    status, body = http('GET', url, auth=auth)
    saved = isinstance(body, list) and any(isinstance(e, dict) and e.get('name') == expected_name and e.get('onboardingDate') == '2026-11-10' for e in body)
    expect(problems, status == 200 and saved, 'GET /api/employees should list the employee just saved')

    for label, payload in [('an empty body', {}),
                           ('a missing role', {'name': 'A', 'onboardingDate': '2026-11-10'}),
                           ('a blank name', {'name': ' ', 'role': 'B', 'onboardingDate': '2026-11-10'}),
                           ('a date of "10-11-2026"', {'name': 'A', 'role': 'B', 'onboardingDate': '10-11-2026'})]:
        status, _ = http('POST', url, payload, auth=auth)
        expect(problems, status == 400, f'POST with {label} should return 400 (got {status})')


IN_MEMORY_DB = ['--spring.datasource.url=jdbc:h2:mem:grader;DB_CLOSE_DELAY=-1', '--spring.jpa.hibernate.ddl-auto=update']
