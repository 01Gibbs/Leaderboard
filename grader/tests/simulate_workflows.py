"""Runs the workflows' shell steps against a scratch copy of this repository with a local 'origin', the way
GitHub would: each form's JSON arguments built from the YAML, then every `run:` step with GitHub's bash options.
Run by test_workflows.py; or directly: python3 grader/tests/simulate_workflows.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
WF = SRC / '.github' / 'workflows'
work = Path(tempfile.mkdtemp())
origin, clone = work / 'origin.git', work / 'clone'
ok_count = 0


def sh(cmd, cwd, env=None, check=True, pipefail=True):
    """Run a shell step. pipefail=False is GitHub's default shell for `run:` (bash -e {0}); a workflow gets
    pipefail only by setting `shell: bash`."""
    flags = ['-eo', 'pipefail'] if pipefail else ['-e']
    r = subprocess.run(['bash', '--noprofile', '--norc', *flags, '-c', cmd], cwd=cwd,
                       env={**os.environ, **(env or {})}, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f'step failed ({r.returncode}):\n{cmd}\n{r.stdout}\n{r.stderr}')
    return r


def yaml(path):
    out = subprocess.run(['ruby', '-ryaml', '-rjson', '-e', 'puts JSON.generate(YAML.load_file(ARGV[0]))', str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def run_steps(workflow, job, cwd, env):
    """Run a job's `run:` steps with the shell GitHub would use. Returns True if every step succeeded."""
    shell = (job.get('defaults') or workflow.get('defaults') or {}).get('run', {}).get('shell')
    failed = False
    for step in job['steps']:
        if 'run' not in step or (failed and step.get('if') != 'always()'):
            continue
        pipefail = (step.get('shell') or shell) == 'bash'
        r = sh(step['run'], cwd, env, check=False, pipefail=pipefail)
        failed = failed or r.returncode != 0
    return not failed


def to_json_args(template, inputs):
    """Evaluate the '${{ toJSON(inputs.x) }}' expressions the way GitHub does."""
    return re.sub(r'\$\{\{\s*toJSON\(inputs\.(\w+)\)\s*\}\}', lambda m: json.dumps(inputs.get(m.group(1), '')), template)


def expect(cond, msg):
    global ok_count
    if not cond:
        raise SystemExit('FAILED: ' + msg)
    ok_count += 1
    print('  ok -', msg)


# A scratch copy of the repository with a local bare 'origin', like GitHub.
shutil.copytree(SRC, work / 'seed', ignore=shutil.ignore_patterns('.git', '__pycache__'))
# Fixed participants, so this does not depend on the real scores.
(work / 'seed' / 'participants.csv').write_text('''name,github_username,fizzbuzz,rest_api,framework_upgrade,container_image,stretch,helped,bonus,pr_stretch
Stuart Smith,StuartJSmith10-dev,correct,,,,1,,,
madbpopye,madbpopye,submitted,submitted,,,,,,
bukkie-create,bukkie-create,submitted,submitted,,,,,,
Josh,j-r-wil,submitted,submitted,submitted,,,,,
''')
(work / 'seed' / 'grader' / 'results.json').write_text('{"people": {}, "submissions": {}}\n')
(work / 'seed' / 'grader' / 'history.json').unlink(missing_ok=True)
sh(f'git init -q -b main && git add -A && git -c user.name=t -c user.email=t@t commit -qm seed && git clone -q --bare . {origin}', work / 'seed')
sh(f'git clone -q {origin} {clone}', work)


def run_facilitator(dispatcher, inputs, actor='facilitator-ann', before_push=None):
    """Run a 'Facilitator: ...' workflow: build its args, then the shared job's steps in a fresh checkout."""
    caller = yaml(WF / dispatcher)
    args = to_json_args(caller['jobs']['run']['with']['args'], inputs)
    json.loads(args)  # GitHub would pass a broken template straight through; make sure it is valid JSON
    workflow = yaml(WF / 'facilitator-action.yml')
    checkout = work / ('run-' + dispatcher)
    shutil.rmtree(checkout, ignore_errors=True)
    sh(f'git clone -q {origin} {checkout}', work)
    if before_push:
        before_push(checkout)
    runner_temp = Path(tempfile.mkdtemp())
    summary = runner_temp / 'step_summary.md'
    env = {'ARGS': args, 'RUNNER_TEMP': str(runner_temp), 'GITHUB_STEP_SUMMARY': str(summary), 'GITHUB_ACTOR': actor}
    ok = run_steps(workflow, workflow['jobs']['change'], checkout, env)
    return ok, summary.read_text() if summary.exists() else ''


def csv_at_origin():
    sh('git pull -q', clone)
    return (clone / 'participants.csv').read_text()


def row(name):
    return next(l for l in csv_at_origin().splitlines() if l.startswith(name + ','))


print('Facilitator journeys')
ok, s = run_facilitator('facilitator-award.yml', {'person': 'stuart smith', 'kind': 'helped', 'amount': '2'})
expect(ok and '✅ Gave 2 helps to Stuart Smith' in s, 'award: run succeeds and summary says what changed')
expect(row('Stuart Smith').endswith(',1,2,,'), 'award: helped is 2 at origin')
expect('facilitator-ann: Gave 2 helps' in s, 'award: recent actions list who did it')
log = sh('git log -1 --format=%s%n%b', clone).stdout
expect('Leaderboard: Gave 2 helps to Stuart Smith' in log and '@facilitator-ann' in log, 'award: commit message names the change and the facilitator')

ok, s = run_facilitator('facilitator-award.yml', {'person': 'StuartJSmith10-dev', 'kind': 'bonus', 'amount': '-3'})
expect(ok and row('Stuart Smith').endswith(',1,2,-3,'), 'award: negative bonus by GitHub login')

ok, s = run_facilitator('facilitator-rename.yml', {'person': 'madbpopye', 'new_name': 'Ali "The Builder" O\'Neil, $(whoami)'})
expect(ok and '"Ali ""The Builder"" O\'Neil, $(whoami)",madbpopye' in csv_at_origin(), 'rename: quotes, commas and $(...) stay plain text')

ok, s = run_facilitator('facilitator-add.yml', {'name': 'Bukky Adeyemi', 'github': ''})
ok2, _ = run_facilitator('facilitator-award.yml', {'person': 'Bukky Adeyemi', 'kind': 'stretch', 'amount': '3'})
expect(ok and ok2 and row('Bukky Adeyemi').startswith('Bukky Adeyemi,,,,,,3'), 'add: new person, then award to them')

ok, s = run_facilitator('facilitator-merge.yml', {'keep': 'Bukky Adeyemi', 'duplicate': 'bukkie-create'})
merged = row('Bukky Adeyemi')
expect(ok and merged == 'Bukky Adeyemi,bukkie-create,submitted,submitted,,,3,,,', 'merge: higher value of each column kept, GitHub login carried over')
expect('bukkie-create,bukkie-create' not in csv_at_origin(), 'merge: duplicate row removed')

ok, s = run_facilitator('facilitator-mark.yml', {'person': 'Bukky Adeyemi', 'lesson': 'container_image', 'status': 'correct'})
expect(ok and row('Bukky Adeyemi').split(',')[5] == 'correct', 'mark: exercise marked correct')

print('Mistakes')
before = csv_at_origin()
ok, s = run_facilitator('facilitator-award.yml', {'person': 'Stuart Smit', 'kind': 'helped', 'amount': '1'})
expect(not ok and "❌ Nothing was changed" in s and "Did you mean 'Stuart Smith'" in s, 'typo: run fails, says nothing changed, suggests the right name')
expect(csv_at_origin() == before, 'typo: origin unchanged')
ok, s = run_facilitator('facilitator-mark.yml', {'person': 'Bukky Adeyemi', 'lesson': 'docker', 'status': 'correct'})
expect(not ok and 'fizzbuzz, rest_api, framework_upgrade, container_image' in s, 'mark: unknown exercise lists the valid keys')

print('Undo')
ok, s = run_facilitator('facilitator-undo.yml', {})
expect(ok and 'Undid: Marked Bukky Adeyemi container_image as correct' in s, 'undo: reverses the latest change and says which')
expect(row('Bukky Adeyemi').split(',')[5] == '', 'undo: mark reverted at origin')
run_facilitator('facilitator-undo.yml', {})
expect('bukkie-create,bukkie-create,submitted' in csv_at_origin(), 'undo again: merge reverted, both rows back')

print('Two changes at the same moment')


def someone_else_pushes_first(checkout):
    """A git hook: the first push is beaten by another facilitator's award to Josh, and rejected."""
    other = work / 'other-facilitator'
    hook = checkout / '.git' / 'hooks' / 'pre-push'
    hook.write_text(f"""#!/bin/bash
[ -e {work}/raced ] && exit 0
touch {work}/raced
unset GITHUB_STEP_SUMMARY
rm -rf {other} && git clone -q {origin} {other} && cd {other}
python3 grader/leaderboard.py award Josh helped 1 >/dev/null
git -c user.name=o -c user.email=o@o commit -qam 'other facilitator' && git push -q origin HEAD:main
exit 1
""")
    hook.chmod(0o755)


josh_before = int(row('Josh').split(',')[7] or 0)
ok, s = run_facilitator('facilitator-award.yml', {'person': 'Josh', 'kind': 'helped', 'amount': '2'}, before_push=someone_else_pushes_first)
expect(ok and (work / 'raced').exists(), 'race: first push rejected because someone else pushed first, run still succeeds')
expect(int(row('Josh').split(',')[7]) == josh_before + 3, 'race: both changes land (+1 from the other facilitator, +2 from this run)')
expect(s.count('✅') == 1 and s.count('Recent actions') == 1, 'race: the run page reports the change once, not once per attempt')

print('Grading run publishing after facilitator changes')
grade_wf = yaml(WF / 'grade.yml')
gradejob = work / 'grade-checkout'
sh(f'git clone -q {origin} {gradejob}', work)  # the grading run checked out before the facilitator acted
run_facilitator('facilitator-award.yml', {'person': 'Josh', 'kind': 'helped', 'amount': '1'})
josh_now = row('Josh')
results = json.loads((gradejob / 'grader' / 'results.json').read_text())
results['people']['newperson'] = 'New Person'
results['submissions']['o/r#99'] = {'login': 'newperson', 'task': 'rest_api', 'passed': True}
runner_temp = Path(tempfile.mkdtemp())
(runner_temp / 'graded').mkdir()
(runner_temp / 'graded' / 'results.json').write_text(json.dumps(results))  # what download-artifact puts there
publish = work / 'publish-checkout'
sh(f'git clone -q {origin} {publish}', work)
ok = run_steps(grade_wf, grade_wf['jobs']['publish'], publish, {'GITHUB_ACTOR': 'github-actions', 'RUNNER_TEMP': str(runner_temp)})
text = csv_at_origin()
expect(ok and 'New Person,newperson,,correct' in text, 'publish: new participant from grading added')
expect(row('Josh') == josh_now, 'publish: facilitator change made during grading survives')
expect('Update leaderboard from graded submissions' in sh('git log -1 --format=%s', clone).stdout, 'publish: commit title')

print('Page publishing')
for name, wf in [('facilitator-action.yml', yaml(WF / 'facilitator-action.yml')), ('grade.yml', grade_wf)]:
    callers = [j for j in wf['jobs'].values() if j.get('uses') == './.github/workflows/pages.yml']
    expect(len(callers) == 1 and callers[0]['permissions'].get('pages') == 'write', f'{name} republishes the page after saving')
for f in WF.glob('facilitator-*.yml'):
    if f.name != 'facilitator-action.yml':
        expect(yaml(f)['permissions'].get('pages') == 'write', f'{f.name} grants the page permission it passes down')

print(f'\nAll {ok_count} workflow checks passed')
shutil.rmtree(work)
