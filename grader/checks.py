"""Automated checks. A lesson's "check" in lessons.json names one of CHECKS at the bottom of this file.

Generic levels any lesson can use without writing Python:
  build   the submission's Gradle project builds
  tests   our test files in grader/fixtures/<lesson key>/ are copied over the submission, then `gradle test` must pass
Custom checks (fizzbuzz, rest_api, ...) cover what a generic level cannot, such as calling the running app.

Each check receives the checked-out pull request and the lesson, and returns (passed, reasons). It never
trusts the participant's own tests: it runs ours, or calls the running application over HTTP.
"""
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from base64 import b64encode
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / 'fixtures'
CACHE = Path(os.environ.get('GRADER_CACHE') or HERE / '.cache')
# In CI, participant code runs as this separate user, which cannot write to the grader or its results.
SANDBOX_USER = os.environ.get('GRADER_SANDBOX_USER')
SKIP_DIRS = {'.git', '.gradle', '.idea', '.vscode', 'build', 'bin', 'out', 'target', 'node_modules'}
JUNIT_JAR_URL = ('https://repo1.maven.org/maven2/org/junit/platform/junit-platform-console-standalone/'
                 '1.10.2/junit-platform-console-standalone-1.10.2.jar')


class CheckFailed(Exception):
    pass


# ---------- helpers ----------

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


def newest_jdk():
    homes = jdks()
    if not homes:
        raise CheckFailed('grader has no JDK installed')
    return list(homes.values())[-1]


def clean_env(java_home=None):
    """Environment for participant code: no tokens or other secrets."""
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'TMPDIR') if k in os.environ}
    if java_home:
        env['JAVA_HOME'] = java_home
        env['PATH'] = str(Path(java_home, 'bin')) + os.pathsep + env.get('PATH', '')
    return env


def as_sandbox(cmd, env):
    """The command to run participant code: as the sandbox user when there is one."""
    if not SANDBOX_USER:
        return cmd
    return ['sudo', '-n', '-H', '-u', SANDBOX_USER, 'env', *(f'{k}={v}' for k, v in env.items() if k != 'HOME'), *cmd]


def share_with_sandbox(path):
    """Let the sandbox user read and write a scratch folder (the checked-out pull request), and reach it
    through any folders between it and the temp directory."""
    if not SANDBOX_USER:
        return
    path, temp_root = Path(path).resolve(), Path(tempfile.gettempdir()).resolve()
    subprocess.run(['chmod', '-R', 'a+rwX', str(path)], check=True)
    for parent in path.parents:
        if parent == temp_root or temp_root not in parent.parents:
            break
        subprocess.run(['chmod', 'a+x', str(parent)], check=True)


def stop_sandbox_processes():
    """Kill everything participant code started, including anything it left running in the background."""
    if SANDBOX_USER:
        subprocess.run(['sudo', '-n', 'pkill', '-KILL', '-u', SANDBOX_USER], capture_output=True)


def run(cmd, cwd, timeout, java_home=None, sandbox=True):
    """Run a command and return (exit code, output). sandbox=False only for commands that never execute
    participant code on this machine (docker runs builds and images inside containers)."""
    env = clean_env(java_home)
    if sandbox:
        cmd = as_sandbox(cmd, env)
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f'timed out after {timeout}s'
    return p.returncode, (p.stdout + p.stderr)


def tail(text, n=12):
    return '\n'.join(text.strip().splitlines()[-n:])


def gradle_project(repo):
    project = find_project(repo, 'gradlew', 'build.gradle', 'build.gradle.kts')
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


def gradle(project, tasks, timeout=900):
    """Run the project's Gradle wrapper, trying each installed JDK until one works."""
    wrapper = project / 'gradlew'
    if not wrapper.exists():
        raise CheckFailed(f'no Gradle wrapper (gradlew) in {project.name or "the repository root"}')
    wrapper.chmod(0o755)
    homes = jdks()
    if not homes:
        raise CheckFailed('grader has no JDK installed')
    toolchains = '-Porg.gradle.java.installations.paths=' + ','.join(homes.values())
    # Try 21 first: it runs every recent Gradle release. Fall back to the others.
    out = ''
    for _, home in sorted(homes.items(), key=lambda kv: kv[0] != 21):
        code, out = run(['./gradlew', '--no-daemon', '-q', toolchains, *tasks], project, timeout, home)
        if code == 0:
            return
    raise CheckFailed('Gradle build failed:\n' + tail(out))


def overlay(fixture_dir, project):
    """Copy our files over the submission, replacing any file of the same path."""
    if not fixture_dir.is_dir() or not any(f.is_file() for f in fixture_dir.rglob('*')):
        raise CheckFailed(f'grader setup: no test files in grader/fixtures/{fixture_dir.name}/')
    for f in fixture_dir.rglob('*'):
        if f.is_file():
            dest = project / f.relative_to(fixture_dir)
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


class RunningJar:
    def __init__(self, jar, args, workdir):
        self.port = free_port()
        java = Path(newest_jdk(), 'bin', 'java')
        self.log = open(Path(workdir, 'app.log'), 'w+')
        env = clean_env()
        self.proc = subprocess.Popen(
            as_sandbox([str(java), '-jar', str(jar), f'--server.port={self.port}', *args], env),
            cwd=workdir, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        self.base = f'http://127.0.0.1:{self.port}'

    def __enter__(self):
        try:
            wait_until_up(self.base + '/', lambda: self.proc.poll() is None)
        except CheckFailed as e:
            self.log.seek(0)
            output = self.log.read()
            self.stop()  # `with` does not call __exit__ when __enter__ fails
            raise CheckFailed(f'{e}:\n' + tail(output)) from None
        return self

    def __exit__(self, *exc):
        self.stop()

    def stop(self):
        if SANDBOX_USER:
            stop_sandbox_processes()
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.proc.wait()
        self.log.close()


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


# ---------- generic levels ----------

def check_build(repo, lesson):
    gradle(gradle_project(repo), ['assemble'])
    return True, ['the project builds']


def check_tests(repo, lesson):
    project = gradle_project(repo)
    overlay(FIXTURES / lesson['key'], project)
    gradle(project, ['test'])
    return True, ['our tests pass']


# ---------- exercise 1: FizzBuzz unit tests ----------

# Each mutant is a small bug. Meaningful tests must fail on every one of them.
FIZZBUZZ_MUTANTS = [
    ('stops one number early', 'i <= n', 'i < n'),
    ('starts at 0', 'int i = 1', 'int i = 0'),
    ('never says FizzBuzz', 'i % 15 == 0', 'i % 15 == 99'),
    ('says Buzz instead of Fizz', 'results.add("Fizz");', 'results.add("Buzz");'),
    ('says Fizz instead of Buzz', 'results.add("Buzz");', 'results.add("Fizz");'),
    ('treats multiples of 7 as Buzz', 'i % 5 == 0', 'i % 7 == 0'),
    ('writes the wrong number', 'String.valueOf(i)', 'String.valueOf(i + 1)'),
]


def junit_jar():
    jar = CACHE / Path(JUNIT_JAR_URL).name
    if not jar.exists():
        CACHE.mkdir(exist_ok=True)
        urllib.request.urlretrieve(JUNIT_JAR_URL, jar)
    return jar


def check_fizzbuzz(repo, lesson):
    test = find_file(repo, 'FizzBuzzTest.java')
    if not test:
        raise CheckFailed('no FizzBuzzTest.java found')
    source = test.read_text(errors='replace')
    if not re.search(r'@(Test|ParameterizedTest|RepeatedTest|TestFactory)\b', source):
        raise CheckFailed('FizzBuzzTest.java has no tests')
    pkg = re.search(r'^\s*package\s+([\w.]+)\s*;', source, re.M)
    pkg = pkg.group(1) if pkg else ''
    fqcn = (pkg + '.' if pkg else '') + 'FizzBuzzTest'
    canonical = (FIXTURES / 'fizzbuzz' / 'FizzBuzz.java').read_text()
    jar = junit_jar()
    java_home = newest_jdk()

    def run_against(impl):
        with tempfile.TemporaryDirectory() as tmp:
            share_with_sandbox(tmp)
            src = Path(tmp, 'src')
            src.mkdir()
            Path(src, 'FizzBuzz.java').write_text((f'package {pkg};\n' if pkg else '') + impl)
            shutil.copy(test, src / 'FizzBuzzTest.java')
            classes = Path(tmp, 'classes')
            code, out = run([str(Path(java_home, 'bin', 'javac')), '-cp', str(jar), '-d', str(classes),
                             str(src / 'FizzBuzz.java'), str(src / 'FizzBuzzTest.java')], tmp, 120, java_home)
            if code:
                raise CheckFailed('FizzBuzzTest.java does not compile:\n' + tail(out))
            code, out = run([str(Path(java_home, 'bin', 'java')), '-jar', str(jar), 'execute', '--disable-banner',
                             '--details=summary', '-cp', str(classes), '--select-class', fqcn], tmp, 120, java_home)
            found = re.search(r'(\d+) tests found', out)
            if found and found.group(1) == '0':
                raise CheckFailed('no tests were found in FizzBuzzTest')
            return code == 0, out

    passed, out = run_against(canonical)
    if not passed:
        raise CheckFailed('tests fail against the correct FizzBuzz:\n' + tail(out))
    survived = []
    for label, old, new in FIZZBUZZ_MUTANTS:
        assert old in canonical, old
        if run_against(canonical.replace(old, new, 1))[0]:
            survived.append(label)
    if survived:
        return False, ['tests still pass when FizzBuzz has a bug: ' + '; '.join(survived)]
    return True, [f'tests pass and catch all {len(FIZZBUZZ_MUTANTS)} planted bugs']


# ---------- exercise 2: REST API ----------

def check_rest_api(repo, lesson):
    project = gradle_project(repo)
    gradle(project, ['bootJar', '-x', 'test'])
    problems = []
    with RunningJar(boot_jar(project), IN_MEMORY_DB, project) as app:
        employee_api_checks(app.base, problems)
    return not problems, problems or ['all API checks pass']


# ---------- exercise 3: Spring Boot upgrade ----------

REMOVED_PROPERTIES = ['server.max-http-header-size', 'spring.jpa.hibernate.use-new-id-generator-mappings']


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', v)[:3])


def check_framework_upgrade(repo, lesson):
    project = gradle_project(repo)
    problems = []
    for f in (project / 'src').rglob('*.java') if (project / 'src').exists() else []:
        if re.search(r'\bjavax\.(persistence|validation)\b', f.read_text(errors='replace')):
            problems.append(f'{f.relative_to(project)} still uses javax.persistence or javax.validation')
    for props in (project / 'src' / 'main' / 'resources').glob('application*.properties'):
        text = props.read_text(errors='replace')
        for p in REMOVED_PROPERTIES:
            if re.search(rf'^\s*{re.escape(p)}\s*[=:]', text, re.M):
                problems.append(f'{props.name} still sets the removed property {p}')

    overlay(FIXTURES / 'framework_upgrade', project)  # our copy of the tests, so editing them cannot make it pass
    gradle(project, ['test', 'bootJar'])
    jar = boot_jar(project)

    libs = [Path(n).name for n in zipfile.ZipFile(jar).namelist() if n.startswith('BOOT-INF/lib/')]
    boot = next((n for n in libs if re.fullmatch(r'spring-boot-\d.*\.jar', n)), None)
    if not boot or version_tuple(boot)[:2] != (3, 5):
        problems.append(f'should run on Spring Boot 3.5.x (found {boot or "none"})')
    text_lib = next((n for n in libs if n.startswith('commons-text-')), None)
    if text_lib and version_tuple(text_lib) < (1, 10, 0):
        problems.append(f'{text_lib} is vulnerable (CVE-2022-42889); use 1.10.0 or newer')

    with RunningJar(jar, IN_MEMORY_DB, project) as app:
        employee_api_checks(app.base, problems, auth=('admin', 'admin123'), sent_name='asha RAO')
        status, _ = http('GET', app.base + '/api/employees')
        expect(problems, status == 401, f'GET /api/employees without credentials should return 401 (got {status})')
    return not problems, problems or ['builds on Spring Boot 3.5, our tests pass, API unchanged']


# ---------- exercise 4: container base image ----------

APPROVED_TAG = re.compile(r'(21|25)([.\d_+]*)-(jre|jdk)(-[a-z0-9.]+)?')


def parse_from(line):
    """FROM [--platform=x] image[:tag][@digest] [AS name] -> (image, tag, stage name)."""
    parts = [p for p in line.split()[1:] if not p.startswith('--')]
    ref = parts[0] if parts else ''
    name = parts[2].lower() if len(parts) >= 3 and parts[1].lower() == 'as' else None
    ref = ref.split('@')[0]
    image, _, tag = ref.rpartition(':') if ':' in ref.split('/')[-1] else (ref, '', '')
    image = re.sub(r'^(docker\.io/)?(library/)?', '', image.lower())
    return image, tag.lower(), name


def dockerfile_problems(context):
    """The platform-standard rules that can be read from the Dockerfile without building it."""
    dockerfile = (context / 'Dockerfile').read_text(errors='replace')
    lines = [l.strip() for l in re.sub(r'\\\n', ' ', dockerfile).splitlines() if l.strip() and not l.strip().startswith('#')]
    problems = []

    stages, final_user = [], None
    for l in lines:
        word = l.split()[0].upper()
        if word == 'FROM':
            stages.append(parse_from(l))
            final_user = None
        elif word == 'USER':
            final_user = l.split(None, 1)[1].strip()
    names = {s[2] for s in stages if s[2]}
    expect(problems, len(stages) >= 2, 'should be a multi-stage build (a JDK build stage and a JRE runtime stage)')
    for image, tag, _ in stages:
        if image in names:
            continue
        ok = image == 'eclipse-temurin' and APPROVED_TAG.fullmatch(tag or '')
        expect(problems, ok, f'base image {image}:{tag or "latest"} is not on the approved list (eclipse-temurin 21 or 25, pinned tag)')
    if stages:
        image, tag, _ = stages[-1]
        expect(problems, image == 'eclipse-temurin' and '-jre' in tag, f'the runtime stage should use a JRE image (got {image}:{tag or "latest"})')
    expect(problems, final_user and final_user.split(':')[0] not in ('root', '0'), 'the runtime stage should switch to a non-root USER')
    expect(problems, (context / '.dockerignore').exists(), 'there should be a .dockerignore file')
    return problems


def check_container_image(repo, lesson):
    context = find_project(repo, 'Dockerfile')
    if not context:
        raise CheckFailed('no Dockerfile found')
    problems = dockerfile_problems(context)

    container = 'grader-' + re.sub(r'[^a-z0-9]', '', repo.name.lower())[:40]
    tag = container + ':grader'
    code, out = run(['docker', 'build', '-t', tag, '.'], context, 1500, sandbox=False)
    if code:
        return False, problems + ['docker build failed:\n' + tail(out)]
    try:
        code, uid = run(['docker', 'run', '--rm', '--entrypoint', 'id', tag, '-u'], context, 60, sandbox=False)
        expect(problems, code == 0 and uid.strip() != '0', f'the container should not run as root (id -u gave {uid.strip()!r})')

        port = free_port()
        code, out = run(['docker', 'run', '-d', '--name', container, '-p', f'127.0.0.1:{port}:8080', tag], context, 60, sandbox=False)
        if code:
            raise CheckFailed('docker run failed:\n' + tail(out))
        base = f'http://127.0.0.1:{port}'

        def alive():
            return run(['docker', 'inspect', '-f', '{{.State.Running}}', container], context, 30, sandbox=False)[1].strip() == 'true'
        try:
            wait_until_up(base + '/actuator/health', alive)
        except CheckFailed as e:
            raise CheckFailed(f'{e}:\n' + tail(run(['docker', 'logs', container], context, 30, sandbox=False)[1])) from None
        status, body = http('GET', base + '/actuator/health')
        expect(problems, status == 200 and isinstance(body, dict) and body.get('status') == 'UP', f'/actuator/health should report UP (got {status})')
        # Writes go to the file database inside the image, so this also proves the non-root user can write it.
        employee_api_checks(base, problems)
    finally:
        run(['docker', 'rm', '-f', container], context, 60, sandbox=False)
        run(['docker', 'rmi', '-f', tag], context, 120, sandbox=False)
    return not problems, problems or ['approved pinned JRE base, multi-stage, non-root, app works in the container']


CHECKS = {
    'build': check_build,
    'tests': check_tests,
    'fizzbuzz': check_fizzbuzz,
    'rest_api': check_rest_api,
    'framework_upgrade': check_framework_upgrade,
    'container_image': check_container_image,
}
