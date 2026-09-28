"""TEST-ONLY support: fixed clocks, scratch roots, git helpers, child-process runner.

``FixedClock`` (and later ``FakeTransport``) exist only in this package. The static
scanner FRZ-08 proves the production package never defines or imports them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADAPTERS = REPO / "adapters"
CONFIG = ADAPTERS / "config"
FIXTURES = ADAPTERS / "adapter_tests" / "fixtures" / "oddspapi" / "v4"
SENTINEL_KEY = "GENESIS-SENTINEL-KEY-0123456789abcdef"

_UTC = timezone.utc


def _fmt(value: datetime) -> str:
    return value.astimezone(_UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


class FixedClock:
    """A settable clock. ``step_micros`` makes every ``now()`` strictly later."""

    def __init__(self, start: str = "2026-10-01T12:00:00.000000Z", *, step_micros: int = 0):
        self._current = _parse(start)
        self._step = timedelta(microseconds=step_micros)
        self.calls = 0

    def now(self) -> str:
        self.calls += 1
        value = self._current
        self._current = self._current + self._step
        return _fmt(value)

    def set(self, value: str) -> None:
        self._current = _parse(value)

    def advance(self, *, seconds: float = 0, micros: int = 0) -> None:
        self._current = self._current + timedelta(seconds=seconds, microseconds=micros)

    def peek(self) -> str:
        return _fmt(self._current)


class SequenceClock:
    """Returns the given timestamps in order; raises when exhausted."""

    def __init__(self, values):
        self._values = list(values)
        self.calls = 0

    def now(self) -> str:
        self.calls += 1
        if not self._values:
            raise AssertionError("SequenceClock exhausted")
        return self._values.pop(0)


def scratch_parent() -> Path:
    root = Path(tempfile.gettempdir()) / "genesis-adapter-tests"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _remove(path: Path) -> None:
    def writable(function, target, _error):
        try:
            os.chmod(target, 0o700)
        except OSError:
            pass
        function(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable, ignore_errors=False)
    else:  # pragma: no cover
        shutil.rmtree(path, onerror=writable)


@contextmanager
def scratch_root():
    """A fresh temp directory OUTSIDE the repository, removed afterwards."""

    root = scratch_parent() / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root
    finally:
        _remove(root)


def child_env(extra: dict | None = None, *, pycache: Path | None = None) -> dict:
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE"}}
    if pycache is not None:
        env["PYTHONPYCACHEPREFIX"] = str(pycache)
    if extra:
        env.update(extra)
    return env


def run_child(code: str, *, env: dict | None = None, isolated_bytecode: bool = True,
              cwd: Path | None = None, timeout: int = 120):
    """Run ``python [-B] -c code`` and return the CompletedProcess (bytes)."""

    with scratch_root() as prefix_root:
        args = [sys.executable]
        environment = dict(env) if env is not None else child_env()
        if isolated_bytecode:
            args.append("-B")
            environment["PYTHONPYCACHEPREFIX"] = str(prefix_root)
        args += ["-c", code]
        return subprocess.run(args, env=environment, cwd=str(cwd or REPO),
                              capture_output=True, timeout=timeout)


def git(repo: Path, *args: str, env: dict | None = None, check: bool = True) -> str:
    result = subprocess.run(["git", "--no-replace-objects", "-C", str(repo), *args],
                            capture_output=True, env=env, check=False)
    if check and result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout.decode("utf-8", errors="replace").strip()


def git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "--no-replace-objects", "-C", str(repo), *args],
                            capture_output=True, check=True)
    return result.stdout


def synthetic_commit(clone: Path, changes: dict[str, bytes | None]) -> str:
    """Commit ``changes`` (path -> bytes, or None to delete) on top of HEAD of ``clone``.

    Uses plumbing and a private index, so no working tree is needed.
    """

    index = clone / ".git" / "synthetic.index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    try:
        git(clone, "read-tree", "HEAD", env=env)
        for path, data in changes.items():
            if data is None:
                git(clone, "update-index", "--force-remove", path, env=env)
                continue
            blob = subprocess.run(["git", "-C", str(clone), "hash-object", "-w", "--stdin"],
                                  input=data, capture_output=True, check=True, env=env)
            git(clone, "update-index", "--add", "--cacheinfo",
                f"100644,{blob.stdout.decode().strip()},{path}", env=env)
        tree = git(clone, "write-tree", env=env)
        return git(clone, "commit-tree", tree, "-p", "HEAD", "-m", "synthetic", env=env)
    finally:
        index.unlink(missing_ok=True)


def shared_clone(dest: Path) -> Path:
    """A no-checkout, object-sharing clone of the repository (fast; repo untouched)."""

    subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", str(REPO), str(dest)],
                   check=True, capture_output=True)
    return dest
