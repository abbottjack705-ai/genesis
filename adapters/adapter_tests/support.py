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
import time
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


# ---------------------------------------------------------------------------------------
# Transport doubles and the acquisition rig (test-only; FRZ-08 forbids these in production)
# ---------------------------------------------------------------------------------------
import json  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from types import SimpleNamespace  # noqa: E402


class Crash(BaseException):
    """Simulated process death. Deliberately NOT an Exception: adapter code never catches it."""


@dataclass
class Scripted:
    kind: str = "RESPONSE"                   # RESPONSE | NO_RESPONSE | TRUNCATED | RAISE | CRASH
    status: int | None = 200
    body: bytes | None = b"[]"
    headers: tuple = (("content-type", "application/json"),)
    latency: float = 0.05                    # seconds between T0 and T1
    error_class: str = "TimeoutError"
    errno: int | None = None
    exc: BaseException | None = None
    t1: str | None = None                    # force the response-received stamp


def ok(body: bytes = b"[]", **kw) -> Scripted:
    return Scripted(body=body, **kw)


def status(code: int, body: bytes = b"{}", **kw) -> Scripted:
    return Scripted(status=code, body=body, **kw)


def no_response(error_class: str = "TimeoutError", errno: int | None = None, **kw) -> Scripted:
    return Scripted(kind="NO_RESPONSE", status=None, body=None, error_class=error_class, errno=errno, **kw)


def truncated(body: bytes = b"[1,", **kw) -> Scripted:
    return Scripted(kind="TRUNCATED", body=body, **kw)


def raises(exc: BaseException) -> Scripted:
    return Scripted(kind="RAISE", exc=exc)


def crash() -> Scripted:
    return Scripted(kind="CRASH")


class FakeTransport:
    """Scripted transport. Stamps T0/T1 from the injected clock like the real one must."""

    def __init__(self, script=(), default: Scripted | None = None):
        self.script = list(script)
        self.default = default if default is not None else ok()
        self.calls: list = []

    def send(self, request, *, clock, deadline_at):
        from genesis_adapters.oddspapi.transport import TransportResult

        self.calls.append(SimpleNamespace(role=request.role, hash=request.provider_request_hash,
                                          deadline_at=deadline_at, request=request))
        step = self.script.pop(0) if self.script else self.default
        if callable(step):                       # a step may be built from the clock at send time
            step = step(clock)
        t0 = clock.now()
        if step.kind == "CRASH":
            raise Crash()
        if step.kind == "RAISE":
            raise step.exc
        if step.latency and hasattr(clock, "advance"):
            clock.advance(seconds=step.latency)
        t1 = step.t1 or clock.now()
        while step.t1 is None and not hasattr(clock, "advance") and _parse(t1) <= _parse(t0):
            time.sleep(0.001)                    # a real clock: like the real transport, T1 is a later tick
            t1 = clock.now()
        if step.kind == "NO_RESPONSE":
            return TransportResult("NO_RESPONSE", None, (), None,
                                   {"class": step.error_class, "errno": step.errno}, t0, None)
        return TransportResult(step.kind, step.status, tuple(step.headers), step.body, None, t0, t1)


def http_date(iso_value: str) -> str:
    """RFC 7231 ``Date`` header value for a canonical UTC timestamp (whole seconds)."""

    from email.utils import format_datetime

    return format_datetime(_parse(iso_value), usegmt=True)


def test_quota_policy(*, daily: int = 7, normal: int = 220, reserve: int = 30, allowance: int = 250):
    from genesis.quota import QuotaInterpretation, QuotaPolicy

    return QuotaPolicy.test_fixture(QuotaInterpretation.A, provider_monthly_allowance=allowance,
                                    normal_monthly_budget=normal, reserve_units=reserve,
                                    daily_billable_budget=daily)


@dataclass
class Rig:
    root: Path
    clock: object
    transport: FakeTransport
    quota_ledger: object
    cache: object
    gate: object
    runner: object
    specs: dict
    policy: object
    evidence: object = None
    contracts: object = None
    capture: object = None
    blocked: list = field(default_factory=list)

    @property
    def acq_path(self) -> Path:
        return self.root / "acquisition.jsonl"

    @property
    def coverage_path(self) -> Path:
        return self.root / "coverage.jsonl"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def load_schemas():
    from genesis_adapters import schema as schema_mod

    document = json.loads((CONFIG / "oddspapi_v4_response_schemas.json").read_text(encoding="utf-8"))
    return {name: schema_mod.load_closed_schema(name, body) for name, body in document["schemas"].items()}


def build_rig(root: Path, *, clock=None, script=(), quota_policy=None, live: bool = False,
              authority=None, credential_check=None, checkpoint=None, specs=None, policy=None,
              transport=None, quota_ledger=None, cache=None, halt_hook=None, capability_blocker=None,
              capture: bool = False, secret=None, require_date: bool = False):
    from genesis.evidence import EvidenceStore
    from genesis.provenance import SourceContractRegistry
    from genesis.quota import QuotaLedger, VerifiedCacheStore

    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi import endpoints as ep
    from genesis_adapters.oddspapi.acquisition import AcquisitionRunner
    from genesis_adapters.oddspapi.quota_gate import QuotaGate

    policy = policy or load_policy(CONFIG / "oddspapi_slice1_policy.json")
    specs = specs or ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", policy)
    clock = clock or FixedClock(step_micros=1000)
    cache = cache or VerifiedCacheStore(root / "quota" / "cache")
    if quota_ledger is None:
        quota_ledger = QuotaLedger(root / "quota" / "ledger.jsonl", policy=quota_policy or test_quota_policy(),
                                   allow_test_policy=True, cache_store=cache)
    gate = QuotaGate(quota_ledger, cache, cache_index_path=root / "quota" / "cache-index.jsonl")
    transport = transport or FakeTransport(script)
    blocked: list = []

    def blocker(reason):
        blocked.append(reason)
        if capability_blocker is not None:
            capability_blocker(reason)

    config = SimpleNamespace(endpoints=specs, policy=policy, schemas=load_schemas())
    evidence = contracts = raw_capture = None
    if capture:
        from genesis_adapters.oddspapi.raw_capture import RawCapture, register_raw_contract

        contracts = SourceContractRegistry(root / "contracts.jsonl")
        register_raw_contract(contracts, licensing_note="FIXTURE-ONLY-NO-PROVIDER-TERMS")
        evidence = EvidenceStore(root / "evidence", contracts=contracts)
        raw_capture = RawCapture(root=root, evidence=evidence, gate=gate, config=config, secret=secret,
                                 require_date=require_date, licensing_note="FIXTURE-ONLY-NO-PROVIDER-TERMS")
    runner = AcquisitionRunner(root=root, clock=clock, transport=transport, quota=gate,
                               authority=authority, config=config, live=live,
                               credential_check=credential_check, checkpoint=checkpoint,
                               capability_blocker=blocker, capture=raw_capture)
    return Rig(root, clock, transport, quota_ledger, cache, gate, runner, specs, policy, evidence,
               contracts, raw_capture, blocked)


def odds_item(*, window: str = "w1", attempt: int = 1, purpose: str = "SCHEDULED", specs=None,
              not_after: str | None = None, **overrides):
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi import endpoints as ep
    from genesis_adapters.oddspapi.acquisition import PlanItem

    if specs is None:
        specs = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json",
                                  load_policy(CONFIG / "oddspapi_slice1_policy.json"))
    params = {"bookmaker": ["pinnacle"], "tournamentIds": [17, 8], "oddsFormat": "decimal"}
    params.update(overrides)
    request = ep.build_request(specs["ODDS"], **params)
    return PlanItem(window_id=window, purpose=purpose, request=request, attempt=attempt, not_after=not_after)


def meta_item(role: str = "META_TOURNAMENTS", *, window: str = "wm", attempt: int = 1, specs=None):
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi import endpoints as ep
    from genesis_adapters.oddspapi.acquisition import PlanItem

    if specs is None:
        specs = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json",
                                  load_policy(CONFIG / "oddspapi_slice1_policy.json"))
    params = {"META_TOURNAMENTS": {"sportId": 10}}.get(role, {})
    return PlanItem(window_id=window, purpose="METADATA", request=ep.build_request(specs[role], **params),
                    attempt=attempt)
