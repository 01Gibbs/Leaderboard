"""container_image: the Dockerfile follows the platform standard (approved pinned eclipse-temurin JRE base,
multi-stage, non-root, .dockerignore), and the image builds and serves the API. Needs Docker on the grader."""
import re

from executor import host_run

from .toolkit import CheckFailed, Container, RunningApp, employee_api_checks, expect, find_project, http, tail

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


def check(ws, lesson):
    context = find_project(ws.path, 'Dockerfile')
    if not context:
        raise CheckFailed('no Dockerfile found')
    problems = dockerfile_problems(context)

    name = 'grader-' + re.sub(r'[^a-z0-9]', '', ws.root.name.lower())[:40]
    tag = name + ':grader'
    code, out = host_run(['docker', 'build', '-t', tag, '.'], cwd=context, timeout=1500)
    if code:
        return False, problems + ['docker build failed:\n' + tail(out)]
    try:
        code, uid = host_run(['docker', 'run', '--rm', '--entrypoint', 'id', tag, '-u'], cwd=context, timeout=60)
        expect(problems, code == 0 and uid.strip() != '0', f'the container should not run as root (id -u gave {uid.strip()!r})')
        with RunningApp(Container(tag, name, context), ready='/actuator/health') as app:
            status, body = http('GET', app.base + '/actuator/health')
            expect(problems, status == 200 and isinstance(body, dict) and body.get('status') == 'UP', f'/actuator/health should report UP (got {status})')
            # Writes go to the file database inside the image, so this also proves the non-root user can write it.
            employee_api_checks(app.base, problems)
    finally:
        host_run(['docker', 'rmi', '-f', tag], cwd=context, timeout=120)
    return not problems, problems or ['approved pinned JRE base, multi-stage, non-root, app works in the container']
