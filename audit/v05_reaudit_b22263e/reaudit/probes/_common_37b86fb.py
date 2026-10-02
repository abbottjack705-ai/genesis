"""Shared scaffolding for the hostile-audit attacks (auditor-written; no implementer helper is imported).

Only the candidate's PUBLIC production modules and the frozen ``genesis`` package are used, plus the
committed fixture FILES (as inputs, re-hashed against FIXTURES.sha256 before use). Clocks, transports,
crash injection and every assertion are the auditor's own.

Run every attack with ``python -B`` and a fresh ``PYTHONPYCACHEPREFIX`` (the candidate's provenance guard,
which the runtime calls at start, requires both).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
SENTINEL = "GENESIS-SENTINEL-KEY-0123456789abcdef"
START = "2026-10-01T12:00:00.000000Z"
DECLARED = ["pinnacle", "fixture-book-a", "fixture-book-b"]
RESULTS: list[dict] = []


def setup(repo: str) -> Path:
    root = Path(repo).resolve()
    for entry in (root / "adapters" / "src", root / "src"):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    return root


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse(text: str) -> datetime:
    return datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)


def add(text: str, *, seconds: float = 0, micros: int = 0) -> str:
    return iso(parse(text) + timedelta(seconds=seconds, microseconds=micros))


class Crash(BaseException):
    """Simulated process death (never an Exception, so no adapter handler can swallow it)."""


class StepClock:
    """Auditor clock: every read advances by ``step`` microseconds; ``jump`` moves it forward."""

    def __init__(self, start: str = START, step: int = 1000):
        self.t = parse(start)
        self.step = timedelta(microseconds=step)
        self.reads = 0

    def now(self) -> str:
        self.reads += 1
        value = self.t
        self.t = self.t + self.step
        return iso(value)

    def jump(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


class StuckClock:
    """Returns the same instant forever (coarse/stuck clock attack)."""

    def __init__(self, value: str):
        self.value = value
        self.reads = 0

    def now(self) -> str:
        self.reads += 1
        return self.value


class CountingTransport:
    """Scripted auditor transport. ``responses`` is a list of (status, headers, body) or callables."""

    def __init__(self, responses=None, default=None, crash_after_receive: bool = False,
                 crash_before_receive: bool = False):
        self.responses = list(responses or [])
        self.default = default
        self.sends = 0
        self.crash_after_receive = crash_after_receive
        self.crash_before_receive = crash_before_receive
        self.requests = []

    def send(self, request, *, clock, deadline_at):
        from genesis_adapters.oddspapi.transport import TransportResult

        self.sends += 1
        self.requests.append(request.provider_request_hash)
        t0 = clock.now()
        if self.crash_before_receive:
            raise Crash("transport: died before the response")
        step = self.responses.pop(0) if self.responses else self.default
        if callable(step):
            step = step(request)
        status, headers, body = step
        t1 = clock.now()
        if self.crash_after_receive:
            raise Crash("transport: died after the last body byte")
        return TransportResult("RESPONSE", status, tuple(headers), body, None, t0, t1)


def fixture_bytes(repo: Path, name: str) -> bytes:
    folder = repo / "adapters" / "adapter_tests" / "fixtures" / "oddspapi" / "v4"
    pins = {}
    for line in (folder / "FIXTURES.sha256").read_text(encoding="ascii").splitlines():
        digest, file_name = line.split()
        pins[file_name.lstrip("*")] = digest
    data = (folder / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != pins[name]:
        raise SystemExit(f"fixture {name} does not match FIXTURES.sha256 - refusing to use it")
    return data


JSON_HEADERS = (("content-type", "application/json"),)


def guard(repo: Path):
    from genesis_adapters import provenance_guard
    from genesis_adapters.oddspapi import verify

    return provenance_guard.verify_loaded_genesis_modules(
        repo, manifest_path=repo / "adapters" / "config" / "frozen_genesis_modules.json",
        expected_manifest_sha256=verify.FROZEN_MANIFEST_SHA256)


def test_quota_policy():
    from genesis.quota import QuotaInterpretation, QuotaPolicy

    return QuotaPolicy.test_fixture(QuotaInterpretation.A, provider_monthly_allowance=250,
                                    normal_monthly_budget=220, reserve_units=30, daily_billable_budget=7)


def open_runtime(repo: Path, root: Path, *, clock, transport, secret=None, checkpoint=None,
                 runner_checkpoint=None):
    from genesis.quota import QuotaLedger, VerifiedCacheStore

    from genesis_adapters.oddspapi import pipeline

    cache = VerifiedCacheStore(root / "quota" / "cache")
    ledger = QuotaLedger(root / "quota" / "ledger.jsonl", policy=test_quota_policy(), allow_test_policy=True,
                         cache_store=cache)
    return pipeline.open_runtime(root, config_dir=repo / "adapters" / "config", clock=clock, transport=transport,
                                 quota_ledger=ledger, cache=cache, secret=secret, live=False,
                                 provenance_check=lambda: guard(repo), checkpoint=checkpoint,
                                 runner_checkpoint=runner_checkpoint)


def specs(repo: Path):
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi import endpoints as ep

    config = repo / "adapters" / "config"
    return ep.load_endpoints(config / "oddspapi_v4_endpoints.json", load_policy(config / "oddspapi_slice1_policy.json"))


def odds_item(repo: Path, *, window: str = "w1", attempt: int = 1):
    from genesis_adapters.oddspapi import endpoints as ep
    from genesis_adapters.oddspapi.acquisition import PlanItem

    request = ep.build_request(specs(repo)["ODDS"], bookmaker=list(DECLARED), tournamentIds=[17, 8],
                               oddsFormat="decimal")
    return PlanItem(window_id=window, purpose="SCHEDULED", request=request, attempt=attempt)


def jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def quota_rows(root: Path, request_id: str | None = None) -> list[dict]:
    rows = [r for r in jsonl(root / "quota" / "ledger.jsonl") if r.get("record_type", "").startswith("quota_")]
    return [r for r in rows if request_id is None or r.get("request_id") == request_id]


def scratch(prefix: str) -> Path:
    base = Path(os.environ.get("HA_SCRATCH", tempfile.gettempdir())) / "ha_attacks"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base))


def check(area: str, name: str, ok: bool, **detail) -> bool:
    RESULTS.append({"area": area, "check": name, "pass": bool(ok), **detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {area} {name} " + (json.dumps(detail, default=str)[:600] if detail else ""))
    return ok


def finish(out: str | None) -> int:
    failed = [r for r in RESULTS if not r["pass"]]
    summary = {"checks": len(RESULTS), "failed": len(failed), "results": RESULTS}
    if out:
        Path(out).write_bytes((json.dumps(summary, indent=1, default=str) + "\n").encode("utf-8"))  # LF on every OS
    print(f"== {len(RESULTS)} checks, {len(failed)} failed")
    return 0 if not failed else 1


def remove(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
