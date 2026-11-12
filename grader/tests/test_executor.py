"""The executor: how participant code is run, locally or as the sandbox user in CI.

Run: python3 -m unittest discover grader/tests
Both adapters are tested here: the local one for real, the sandbox one through a stand-in `sudo` that records
what it was asked to do (the real sudo path runs in CI, in test_checks.py).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

GRADER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GRADER))
import executor  # noqa: E402

FAKE_SUDO = r'''#!/bin/sh
# Stand-in for sudo: records each call, runs the command (dropping sudo's own options), ignores pkill.
# The log path is written in, because the executor gives sudo a clean environment.
echo "$*" >> "{log}"
[ "$1" = "-n" ] && shift
[ "$1" = "-H" ] && shift
[ "$1" = "-u" ] && shift 2
[ "$1" = "pkill" ] && exit 0
exec "$@"
'''


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed child that has not been reaped yet is a zombie: gone for our purposes.
    stat = Path(f'/proc/{pid}/stat')
    if stat.exists():
        return stat.read_text().split()[2] != 'Z'
    ps = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(ps) and not ps.startswith('Z')


def wait_dead(pid, seconds=3):
    end = time.time() + seconds
    while time.time() < end and alive(pid):
        time.sleep(0.05)
    return not alive(pid)


class LocalWorkspaceTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {'GH_TOKEN': 'secret-1', 'GITHUB_TOKEN': 'secret-2', 'AWS_SECRET_ACCESS_KEY': 'secret-3'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_participant_code_gets_no_secrets(self):
        with executor.workspace(executor.Local()) as ws:
            code, out = ws.run(['env'], timeout=10)
        self.assertEqual(code, 0)
        self.assertNotIn('secret', out)
        self.assertIn('PATH=', out)

    def test_java_home_is_set_and_first_on_the_path(self):
        with executor.workspace(executor.Local()) as ws:
            _, out = ws.run(['sh', '-c', 'echo "$JAVA_HOME|$PATH"'], timeout=10, java_home='/opt/jdk21')
        java_home, path = out.strip().split('|')
        self.assertEqual(java_home, '/opt/jdk21')
        self.assertTrue(path.startswith('/opt/jdk21/bin' + os.pathsep))

    def test_output_includes_errors_and_the_exit_code(self):
        with executor.workspace(executor.Local()) as ws:
            code, out = ws.run(['sh', '-c', 'echo out; echo err >&2; exit 3'], timeout=10)
        self.assertEqual(code, 3)
        self.assertIn('out', out)
        self.assertIn('err', out)

    def test_runs_in_the_workspace_by_default(self):
        with executor.workspace(executor.Local()) as ws:
            (ws.path / 'marker').write_text('x')
            _, out = ws.run(['ls'], timeout=10)
        self.assertIn('marker', out)

    def test_a_timeout_stops_the_command_and_everything_it_started(self):
        with executor.workspace(executor.Local()) as ws:
            code, out = ws.run(['sh', '-c', 'sleep 60 & echo $! > child.pid; sleep 60'], timeout=1)
            child = int((ws.path / 'child.pid').read_text())
            self.assertEqual(code, 124)
            self.assertIn('timed out after 1s', out)
            self.assertTrue(wait_dead(child))

    def test_processes_left_running_are_killed_when_the_workspace_closes(self):
        with executor.workspace(executor.Local()) as ws:
            ws.run(['sh', '-c', 'nohup sleep 60 >/dev/null 2>&1 & echo $! > left.pid'], timeout=10)
            left = int((ws.path / 'left.pid').read_text())
            app = ws.start(['sleep', '60'], log=ws.path / 'app.log')
            self.assertTrue(alive(left) and alive(app.pid))
        self.assertTrue(wait_dead(left))
        self.assertTrue(wait_dead(app.pid))

    def test_the_folder_is_removed_even_after_an_error(self):
        with self.assertRaises(RuntimeError):
            with executor.workspace(executor.Local()) as ws:
                path = ws.path
                raise RuntimeError('check crashed')
        self.assertFalse(path.exists())

    def test_scratch_folders_are_inside_the_workspace(self):
        with executor.workspace(executor.Local()) as ws:
            a, b = ws.scratch(), ws.scratch()
            self.assertNotEqual(a, b)
            self.assertEqual((a.parent, b.parent), (ws.path.parent, ws.path.parent))


class SandboxWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.bin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.bin)
        self.log = self.bin / 'sudo.log'
        sudo = self.bin / 'sudo'
        sudo.write_text(FAKE_SUDO.replace('{log}', str(self.log)))
        sudo.chmod(0o755)
        patcher = mock.patch.dict(os.environ, {'PATH': f'{self.bin}{os.pathsep}{os.environ["PATH"]}', 'GH_TOKEN': 'secret-1'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_participant_code_runs_as_the_sandbox_user_without_secrets(self):
        with executor.workspace(executor.Sandbox('grader-sandbox')) as ws:
            code, out = ws.run(['echo', 'hello'], timeout=10)
        self.assertEqual((code, out.strip()), (0, 'hello'))
        first = self.calls()[0]
        self.assertTrue(first.startswith('-n -H -u grader-sandbox env '), first)
        self.assertTrue(first.endswith(' echo hello'), first)
        self.assertNotIn('secret', first)

    def test_long_running_apps_also_run_as_the_sandbox_user(self):
        with executor.workspace(executor.Sandbox('grader-sandbox')) as ws:
            ws.start(['true'], log=ws.path / 'app.log').wait()
        self.assertTrue(self.calls()[0].endswith(' true'))

    def test_everything_the_sandbox_user_started_is_killed_on_close(self):
        with executor.workspace(executor.Sandbox('grader-sandbox')):
            pass
        self.assertIn('-n pkill -KILL -u grader-sandbox', self.calls())

    def test_the_folder_is_removed_as_root_because_the_sandbox_user_owns_files_in_it(self):
        with executor.workspace(executor.Sandbox('grader-sandbox')) as ws:
            root = ws.root
        self.assertIn(f'-n rm -rf {root}', self.calls())
        self.assertFalse(root.exists())

    def test_the_workspace_is_shared_with_the_sandbox_user(self):
        with executor.workspace(executor.Sandbox('grader-sandbox')) as ws:
            (ws.path / 'src').mkdir()
            ws.share()
            mode = (ws.path / 'src').stat().st_mode & 0o777
            scratch_mode = ws.scratch().stat().st_mode & 0o777
        self.assertEqual((mode, scratch_mode), (0o777, 0o777))

    def test_trusted_commands_never_go_through_sudo(self):
        code, out = executor.host_run(['echo', 'docker stand-in'], cwd=self.bin, timeout=10)
        self.assertEqual((code, out.strip()), (0, 'docker stand-in'))
        self.assertEqual(self.calls(), [])


class ChoosingTests(unittest.TestCase):
    def test_the_sandbox_is_used_when_ci_names_a_user(self):
        with mock.patch.dict(os.environ, {'GRADER_SANDBOX_USER': 'grader-sandbox'}):
            self.assertEqual(executor.from_env(), executor.Sandbox('grader-sandbox'))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(executor.from_env(), executor.Local())


if __name__ == '__main__':
    unittest.main()
