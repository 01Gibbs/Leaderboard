"""The automated checks, run against known-good and known-bad submissions.

Run: python3 -m unittest discover grader/tests
Needs a JDK (JAVA_HOME, or JAVA_HOME_<version>_X64 as set by actions/setup-java) and network access to clone
the starter projects; the container test also needs Docker. Tests skip themselves when these are missing.
Only trusted inputs are used here: the exercise starters and submissions written for these tests.
"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GRADER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GRADER))
import checks  # noqa: E402
from checks import container_image, fizzbuzz  # noqa: E402
import grade  # noqa: E402
import lessons  # noqa: E402

DATA = Path(__file__).resolve().parent / 'data'
STARTERS = {
    'rest_reference': 'https://github.com/AtulKumarSharma79/containerbaseimage.git',  # a finished REST API
    'upgrade_starter': 'https://github.com/AtulKumarSharma79/Frameworkupgrade.git',
}
SECURITY_CONFIG_6 = '''package com.example.onboarding.config;

import org.springframework.boot.autoconfigure.security.servlet.PathRequest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.provisioning.InMemoryUserDetailsManager;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
public class SecurityConfig {

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http.csrf(c -> c.disable())
            .authorizeHttpRequests(a -> a.requestMatchers(PathRequest.toH2Console()).permitAll().anyRequest().authenticated())
            .httpBasic(Customizer.withDefaults())
            .headers(h -> h.frameOptions(f -> f.sameOrigin()));
        return http.build();
    }

    @Bean
    InMemoryUserDetailsManager users() {
        return new InMemoryUserDetailsManager(User.withUsername("admin").password("{noop}admin123").roles("ADMIN").build());
    }
}
'''
GOOD_DOCKERFILE = '''FROM eclipse-temurin:21-jdk AS build
WORKDIR /src
COPY . .
RUN chmod +x gradlew && ./gradlew --no-daemon bootJar -x test

FROM eclipse-temurin:21-jre
RUN useradd --system --uid 10001 app && mkdir /app && chown app /app
WORKDIR /app
COPY --from=build /src/build/libs/*-SNAPSHOT.jar app.jar
USER app
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
'''


def reference_upgrade(project):
    """What a correct framework-upgrade submission does to the starter."""
    gradle = project / 'build.gradle'
    gradle.write_text(gradle.read_text().replace("version '2.7.18'", "version '3.5.7'")
                      .replace("version '1.0.15.RELEASE'", "version '1.1.7'").replace('commons-text:1.9', 'commons-text:1.12.0'))
    for f in (project / 'src').rglob('*.java'):
        f.write_text(re.sub(r'\bjavax\.(persistence|validation)', r'jakarta.\1', f.read_text()))
    props = project / 'src/main/resources/application.properties'
    props.write_text(props.read_text().replace('server.max-http-header-size=', 'server.max-http-request-header-size=')
                     .replace('spring.jpa.hibernate.use-new-id-generator-mappings=true\n', ''))
    (project / 'src/main/java/com/example/onboarding/config/SecurityConfig.java').write_text(SECURITY_CONFIG_6)


class LocalFolder:
    """A source whose one "pull request" is a folder on this machine (a starter or a reference submission)."""

    def __init__(self, path):
        self.path = Path(path)

    def checkout(self, repo, number, dest):
        shutil.copytree(self.path, dest, dirs_exist_ok=True)


def run_check(check, folder, lesson_key=None):
    """Grade a folder exactly as grade.py grades a pull request: same workspace, sandbox and error handling."""
    lesson = lessons.Lesson(lesson_key or check, lesson_key or check, 'local/folder', check, lessons.FIXTURES / (lesson_key or check))
    passed, reasons = grade.grade_submission(lesson, LocalFolder(folder), grade.PullRequest(1, 'tester', 'local', ''))
    return passed, reasons


@unittest.skipUnless(checks.jdks(), 'needs a JDK')
class FizzBuzzCheckTests(unittest.TestCase):
    def test_meaningful_tests_pass(self):
        ok, reasons = run_check('fizzbuzz', DATA / 'fizzbuzz' / 'good')
        self.assertTrue(ok, reasons)

    def test_tests_in_a_package_pass(self):
        ok, reasons = run_check('fizzbuzz', DATA / 'fizzbuzz' / 'in_package')
        self.assertTrue(ok, reasons)

    def test_weak_tests_fail_and_name_the_bugs_they_miss(self):
        ok, reasons = run_check('fizzbuzz', DATA / 'fizzbuzz' / 'weak')
        self.assertFalse(ok)
        self.assertIn('never says FizzBuzz', reasons[0])

    def test_missing_test_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, reasons = run_check('fizzbuzz', Path(tmp))
        self.assertFalse(ok)
        self.assertIn('no FizzBuzzTest.java', reasons[0])


@unittest.skipUnless(checks.jdks(), 'needs a JDK')
class GradleCheckTests(unittest.TestCase):
    """Builds real Spring Boot projects, so each test takes 15-60 seconds."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for name, url in STARTERS.items():
            r = subprocess.run(['git', 'clone', '-q', '--depth', '1', url, str(cls.tmp / name)], capture_output=True)
            if r.returncode:
                raise unittest.SkipTest('cannot clone the starter projects (offline?)')
        shutil.copytree(cls.tmp / 'upgrade_starter', cls.tmp / 'upgrade_done')
        reference_upgrade(cls.tmp / 'upgrade_done')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self, name):
        dest = Path(tempfile.mkdtemp()) / name
        self.addCleanup(shutil.rmtree, dest.parent, True)
        shutil.copytree(self.tmp / name, dest)
        return dest

    def test_rest_api_reference_passes(self):
        ok, reasons = run_check('rest_api', self.copy('rest_reference'))
        self.assertTrue(ok, reasons)

    def test_rest_api_with_auth_on_every_endpoint_fails(self):
        ok, reasons = run_check('rest_api', self.copy('upgrade_done'))
        self.assertFalse(ok)
        self.assertTrue(any('401' in r for r in reasons), reasons)

    def test_framework_upgrade_starter_fails_with_every_reason(self):
        ok, reasons = run_check('framework_upgrade', self.copy('upgrade_starter'))
        self.assertFalse(ok)
        text = '\n'.join(reasons)
        for part in ('javax', 'server.max-http-header-size', 'use-new-id-generator-mappings', 'Spring Boot 3.5', 'commons-text-1.9'):
            self.assertIn(part, text)

    def test_framework_upgrade_reference_passes(self):
        ok, reasons = run_check('framework_upgrade', self.copy('upgrade_done'))
        self.assertTrue(ok, reasons)

    def test_framework_upgrade_ignores_edited_tests(self):
        project = self.copy('upgrade_done')
        test = project / 'src/test/java/com/example/onboarding/EmployeeApiTests.java'
        test.write_text(test.read_text().replace('isUnauthorized()', 'isOk()'))  # would fail if it were used
        ok, reasons = run_check('framework_upgrade', project)
        self.assertTrue(ok, reasons)

    def test_level_build(self):
        self.assertTrue(run_check('build', self.copy('rest_reference'))[0])
        with tempfile.TemporaryDirectory() as tmp:
            ok, reasons = run_check('build', Path(tmp))
        self.assertFalse(ok)
        self.assertIn('no Gradle project', reasons[0])

    def test_level_tests_uses_the_lessons_fixture_files(self):
        ok, reasons = run_check('tests', self.copy('upgrade_done'), 'framework_upgrade')
        self.assertTrue(ok, reasons)
        ok, reasons = run_check('tests', self.copy('rest_reference'), 'framework_upgrade')
        self.assertFalse(ok)  # no security there, so our auth tests cannot pass
        self.assertIn('Gradle build failed', reasons[0])

    def test_level_tests_without_fixture_files_says_so(self):
        ok, reasons = run_check('tests', self.copy('rest_reference'), 'no_such_lesson')
        self.assertFalse(ok)
        self.assertIn('grader/fixtures/no_such_lesson', reasons[0])

    def test_project_in_a_subfolder_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(self.tmp / 'rest_reference', Path(tmp) / 'onboarding-tracker')
            ok, reasons = run_check('rest_api', Path(tmp))
        self.assertTrue(ok, reasons)


class FizzBuzzSetupTests(unittest.TestCase):
    def test_every_planted_bug_still_applies_to_the_reference_fizzbuzz(self):
        reference = (lessons.FIXTURES / 'fizzbuzz' / 'FizzBuzz.java').read_text()
        for label, old, new in fizzbuzz.MUTANTS:
            self.assertEqual(reference.count(old), 1, f'planted bug "{label}": "{old}" must appear once in FizzBuzz.java')


class DockerfileRuleTests(unittest.TestCase):
    def problems(self, dockerfile, dockerignore=True):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'Dockerfile').write_text(dockerfile)
            if dockerignore:
                Path(tmp, '.dockerignore').write_text('.git\nbuild\n')
            return container_image.dockerfile_problems(Path(tmp))

    def test_compliant_dockerfile(self):
        self.assertEqual(self.problems(GOOD_DOCKERFILE), [])

    def test_starter_dockerfile_breaks_every_rule(self):
        text = '\n'.join(self.problems('FROM openjdk:17-jdk-slim\nCOPY app.jar app.jar\nENTRYPOINT ["java","-jar","app.jar"]\n', False))
        for part in ('multi-stage', 'openjdk:17-jdk-slim is not on the approved list', 'JRE image', 'non-root', '.dockerignore'):
            self.assertIn(part, text)

    def test_root_user_latest_tag_and_jdk_runtime_are_caught(self):
        text = '\n'.join(self.problems('FROM eclipse-temurin:21-jdk AS b\nFROM eclipse-temurin\nUSER root\n'))
        self.assertIn('eclipse-temurin:latest is not on the approved list', text)
        self.assertIn('non-root', text)
        text = '\n'.join(self.problems('FROM eclipse-temurin:21-jdk AS b\nFROM eclipse-temurin:21-jdk\nUSER app\n'))
        self.assertIn('JRE image', text)

    def test_digest_platform_and_registry_prefix_are_understood(self):
        df = GOOD_DOCKERFILE.replace('FROM eclipse-temurin:21-jre',
                                     'FROM --platform=linux/amd64 docker.io/library/eclipse-temurin:21.0.5_11-jre-noble@sha256:abc')
        self.assertEqual(self.problems(df), [])

    def test_unsupported_java_version_is_rejected(self):
        self.assertTrue(self.problems(GOOD_DOCKERFILE.replace('21-jre', '17-jre')))


def docker_running():
    return bool(shutil.which('docker')) and subprocess.run(['docker', 'info'], capture_output=True).returncode == 0


@unittest.skipUnless(checks.jdks() and docker_running(), 'needs a JDK and a running Docker')
class ContainerCheckTests(unittest.TestCase):
    def test_compliant_image_builds_runs_and_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            r = subprocess.run(['git', 'clone', '-q', '--depth', '1', STARTERS['rest_reference'], str(repo)], capture_output=True)
            if r.returncode:
                self.skipTest('cannot clone the starter project')
            (repo / 'Dockerfile').write_text(GOOD_DOCKERFILE)
            (repo / '.dockerignore').write_text('.git\n.gradle\nbuild\n')
            ok, reasons = run_check('container_image', repo)
        self.assertTrue(ok, reasons)


if __name__ == '__main__':
    unittest.main()
