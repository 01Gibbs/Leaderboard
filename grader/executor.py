"""Running participant code. Everything a pull request contains runs through a Workspace from here.

A workspace is a scratch folder plus a way of running commands in it. It guarantees:
  - participant code gets a clean environment: no tokens or other secrets;
  - a command that times out is stopped together with everything it started;
  - when the workspace closes, anything still running is killed and the folder is removed.

Two adapters decide how commands run: Local (this machine's user) and Sandbox (a separate user in CI, which
cannot write to the grader or its results). `from_env()` picks the sandbox when GRADER_SANDBOX_USER is set.
Trusted commands that never execute participant code on this machine (git, docker) use `host_run`.
"""
import os
import shutil
import signal
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SAFE_ENV = ('PATH', 'HOME', 'LANG', 'TMPDIR')


def clean_env(java_home=None):
    env = {k: os.environ[k] for k in SAFE_ENV if k in os.environ}
    if java_home:
        env['JAVA_HOME'] = java_home
        env['PATH'] = str(Path(java_home, 'bin')) + os.pathsep + env.get('PATH', '')
    return env


def _run(cmd, cwd, env, timeout, started=None, stop=None):
    """Run in its own process group, so a timeout stops everything the command started. Returns (exit code,
    output); 124 means it timed out. `started(p)` sees the process; `stop(pids)` adds a way to stop it."""
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         start_new_session=True)
    if started:
        started(p)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out
    except subprocess.TimeoutExpired:
        if stop:
            stop([p.pid])
        _kill_group(p.pid)
        p.communicate()
        return 124, f'timed out after {timeout}s'


def _kill_group(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def host_run(cmd, cwd, timeout):
    """A trusted command (git, docker): clean environment, never as the sandbox user."""
    return _run(cmd, cwd, clean_env(), timeout)


@dataclass(frozen=True)
class Local:
    """Participant code runs as this machine's user. For local runs and tests only."""

    def command(self, cmd, env):
        return cmd

    def share(self, path):
        pass

    def stop_all(self, groups):
        for pgid in groups:
            _kill_group(pgid)

    def remove(self, path):
        shutil.rmtree(path, ignore_errors=True)


@dataclass(frozen=True)
class Sandbox:
    """Participant code runs as `user` through sudo (GitHub's runners allow it without a password)."""
    user: str

    def command(self, cmd, env):
        return ['sudo', '-n', '-H', '-u', self.user, 'env', *(f'{k}={v}' for k, v in env.items() if k != 'HOME'), *cmd]

    def share(self, path):
        """Let the sandbox user read and write `path`, and reach it through folders inside the temp directory."""
        path, temp_root = Path(path).resolve(), Path(tempfile.gettempdir()).resolve()
        subprocess.run(['chmod', '-R', 'a+rwX', str(path)], check=True)
        for parent in path.parents:
            if parent == temp_root or temp_root not in parent.parents:
                break
            subprocess.run(['chmod', 'a+x', str(parent)], check=True)

    def stop_all(self, groups):
        # The runner may not signal the sandbox user's processes, and some may have left their group.
        subprocess.run(['sudo', '-n', 'pkill', '-KILL', '-u', self.user], capture_output=True)

    def remove(self, path):
        # Folders the sandbox user created are not writable by the runner, so remove them as root.
        subprocess.run(['sudo', '-n', 'rm', '-rf', str(path)], capture_output=True)


def from_env():
    user = os.environ.get('GRADER_SANDBOX_USER')
    return Sandbox(user) if user else Local()


class Workspace:
    def __init__(self, root, adapter):
        self.root, self.adapter = root, adapter
        self.path = root / 'repo'
        self.path.mkdir()
        self.processes = []
        self.share()

    def share(self):
        """Call after putting files in the workspace (e.g. a checkout) so participant code can use them."""
        self.adapter.share(self.root)

    def scratch(self):
        """Another empty folder participant code may use."""
        d = Path(tempfile.mkdtemp(dir=self.root))
        self.adapter.share(d)
        return d

    def run(self, cmd, cwd=None, timeout=600, java_home=None):
        """Run participant code to completion. Returns (exit code, output); 124 means it timed out."""
        env = clean_env(java_home)
        return _run(self.adapter.command(cmd, env), cwd or self.path, env, timeout,
                    started=self.processes.append, stop=self.adapter.stop_all)

    def start(self, cmd, log, cwd=None, java_home=None):
        """Start participant code that keeps running (an app). It is stopped when the workspace closes."""
        env = clean_env(java_home)
        with open(log, 'w') as out:
            p = subprocess.Popen(self.adapter.command(cmd, env), cwd=cwd or self.path, env=env, stdout=out,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        self.processes.append(p)
        return p

    def stop(self, process):
        """Stop one process started with start(), before the workspace closes."""
        self.adapter.stop_all([process.pid])
        _kill_group(process.pid)
        process.wait()

    def close(self):
        self.adapter.stop_all([p.pid for p in self.processes])
        for p in self.processes:  # collect them, so a long grading run does not pile up zombie processes
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        self.adapter.remove(self.root)


@contextmanager
def workspace(adapter=None):
    ws = Workspace(Path(tempfile.mkdtemp(prefix='grader-')), adapter or from_env())
    try:
        yield ws
    finally:
        ws.close()
