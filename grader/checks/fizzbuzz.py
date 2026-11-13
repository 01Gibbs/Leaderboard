"""fizzbuzz: the participant's FizzBuzzTest must pass against a correct FizzBuzz and fail against every
planted bug (MUTANTS). The correct FizzBuzz is grader/fixtures/fizzbuzz/FizzBuzz.java (lesson.test_files):
here it is the reference the bugs are planted in, not a test file copied over the submission."""
import re
import shutil
import urllib.request
from pathlib import Path

from .toolkit import CACHE, CheckFailed, find_file, newest_jdk, tail

JUNIT_JAR_URL = ('https://repo1.maven.org/maven2/org/junit/platform/junit-platform-console-standalone/'
                 '1.10.2/junit-platform-console-standalone-1.10.2.jar')

# Each mutant is a small bug. Meaningful tests must fail on every one of them.
MUTANTS = [
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
        CACHE.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(JUNIT_JAR_URL, jar)
    return jar


def check(ws, lesson):
    test = find_file(ws.path, 'FizzBuzzTest.java')
    if not test:
        raise CheckFailed('no FizzBuzzTest.java found')
    source = test.read_text(errors='replace')
    if not re.search(r'@(Test|ParameterizedTest|RepeatedTest|TestFactory)\b', source):
        raise CheckFailed('FizzBuzzTest.java has no tests')
    pkg = re.search(r'^\s*package\s+([\w.]+)\s*;', source, re.M)
    pkg = pkg.group(1) if pkg else ''
    fqcn = (pkg + '.' if pkg else '') + 'FizzBuzzTest'
    canonical = (lesson.test_files / 'FizzBuzz.java').read_text()
    jar = junit_jar()
    java_home = newest_jdk()

    def run_against(impl):
        tmp = ws.scratch()
        src = tmp / 'src'
        src.mkdir()
        (src / 'FizzBuzz.java').write_text((f'package {pkg};\n' if pkg else '') + impl)
        shutil.copy(test, src / 'FizzBuzzTest.java')
        classes = tmp / 'classes'
        code, out = ws.run([str(Path(java_home, 'bin', 'javac')), '-cp', str(jar), '-d', str(classes),
                            str(src / 'FizzBuzz.java'), str(src / 'FizzBuzzTest.java')], cwd=tmp, timeout=120, java_home=java_home)
        if code:
            raise CheckFailed('FizzBuzzTest.java does not compile:\n' + tail(out))
        code, out = ws.run([str(Path(java_home, 'bin', 'java')), '-jar', str(jar), 'execute', '--disable-banner',
                            '--details=summary', '-cp', str(classes), '--select-class', fqcn], cwd=tmp, timeout=120, java_home=java_home)
        found = re.search(r'(\d+) tests found', out)
        if found and found.group(1) == '0':
            raise CheckFailed('no tests were found in FizzBuzzTest')
        return code == 0, out

    passed, out = run_against(canonical)
    if not passed:
        raise CheckFailed('tests fail against the correct FizzBuzz:\n' + tail(out))
    survived = []
    for label, old, new in MUTANTS:
        if old not in canonical:  # the reference FizzBuzz.java changed; test_checks catches this first
            raise CheckFailed(f'grader setup: the planted bug "{label}" no longer applies to FizzBuzz.java')
        if run_against(canonical.replace(old, new, 1))[0]:
            survived.append(label)
    if survived:
        return False, ['tests still pass when FizzBuzz has a bug: ' + '; '.join(survived)]
    return True, [f'tests pass and catch all {len(MUTANTS)} planted bugs']
