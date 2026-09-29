"""Test-only helpers for the end-to-end fixture pipeline (S6)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from genesis.pit import OperationalStatus
from genesis.quota import QuotaLedger, VerifiedCacheStore
from genesis.registry import AppendOnlyJsonl

from genesis_adapters import provenance_guard
from genesis_adapters.config import load_policy
from genesis_adapters.oddspapi import endpoints as ep
from genesis_adapters.oddspapi import pipeline, verify
from genesis_adapters.oddspapi.acquisition import PlanItem

from . import parser_support as ps
from .support import CONFIG, REPO, FakeTransport, FixedClock, ok, read_jsonl, test_quota_policy

JSON = (("content-type", "application/json"),)
START = "2026-10-01T12:00:00.000000Z"
DECLARED = ["pinnacle", "fixture-book-a", "fixture-book-b"]
SPECS = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", load_policy(CONFIG / "oddspapi_slice1_policy.json"))


def real_guard():
    """The module-provenance guard exactly as a runner calls it at startup (design 2.4)."""

    return provenance_guard.verify_loaded_genesis_modules(
        REPO, manifest_path=CONFIG / "frozen_genesis_modules.json",
        expected_manifest_sha256=verify.FROZEN_MANIFEST_SHA256)


def open_rt(root: Path, *, script=(), clock=None, transport=None, secret=None, config_dir: Path = CONFIG,
            quota_ledger=None, cache=None, quota_policy=None, provenance_check=None, checkpoint=None,
            runner_checkpoint=None, live: bool = False, authority=None, credential_check=None,
            require_date: bool = False) -> pipeline.AdapterRuntime:
    clock = clock or FixedClock(START, step_micros=1000)
    cache = cache or VerifiedCacheStore(root / "quota" / "cache")
    if quota_ledger is None:
        quota_ledger = QuotaLedger(root / "quota" / "ledger.jsonl", policy=quota_policy or test_quota_policy(),
                                   allow_test_policy=True, cache_store=cache)
    return pipeline.open_runtime(
        root, config_dir=config_dir, clock=clock, transport=transport or FakeTransport(script),
        quota_ledger=quota_ledger, cache=cache, secret=secret, live=live, authority=authority,
        credential_check=credential_check, require_date=require_date,
        provenance_check=provenance_check or real_guard, checkpoint=checkpoint, runner_checkpoint=runner_checkpoint)


def reopen(rt: pipeline.AdapterRuntime, **kw) -> pipeline.AdapterRuntime:
    """A restarted process over the same runtime root (same quota ledger and cache files)."""

    return open_rt(rt.root, clock=kw.pop("clock", None) or FixedClock(later_than(rt), step_micros=1000),
                   quota_ledger=QuotaLedger(rt.root / "quota" / "ledger.jsonl", policy=rt.gate.ledger.policy,
                                            allow_test_policy=True, cache_store=rt.gate.cache),
                   cache=rt.gate.cache, config_dir=kw.pop("config_dir", rt.config_dir), **kw)


def later_than(rt: pipeline.AdapterRuntime, seconds: int = 60) -> str:
    rows = rt.stores.acquisition.rows()
    last = rows[-1]["recorded_at"] if rows else START
    return ps.iso_add(last, seconds=seconds)


def odds_item(window: str = "w1", attempt: int = 1, bookmakers=None, tournaments=(17, 8)) -> PlanItem:
    request = ep.build_request(SPECS["ODDS"], bookmaker=list(bookmakers or DECLARED),
                               tournamentIds=list(tournaments), oddsFormat="decimal")
    return PlanItem(window_id=window, purpose="SCHEDULED", request=request, attempt=attempt)


def fixtures_item(window: str = "wf") -> PlanItem:
    request = ep.build_request(SPECS["FIXTURES"], **{"from": "2026-10-01", "to": "2026-10-08", "sportId": 10,
                                                     "tournamentIds": [17, 8]})
    return PlanItem(window_id=window, purpose="SCHEDULED", request=request)


def meta_item(role: str = "META_TOURNAMENTS", window: str = "wm") -> PlanItem:
    params = {"META_TOURNAMENTS": {"sportId": 10}}.get(role, {})
    return PlanItem(window_id=window, purpose="METADATA", request=ep.build_request(SPECS[role], **params))


def fixture_body(name: str) -> bytes:
    return (ps.FIXTURE_DIR / name).read_bytes()


def odds_response(payload=None, **kw):
    return ok(ps.dump(payload if payload is not None else ps.odds_payload()), headers=kw.pop("headers", JSON), **kw)


def pit_rows(rt) -> list[dict]:
    return [row for row in rt.stores.pit.log.records() if row.get("record_type") == "pit_record"]


def coverage_rows(rt) -> list[dict]:
    return read_jsonl(rt.root / "coverage.jsonl")


def acquisition_rows(rt) -> list[dict]:
    return read_jsonl(rt.root / "acquisition.jsonl")


def documents(rt) -> list[dict]:
    return [json.loads(rt.stores.evidence.get_bytes(row["payload_hash"])) for row in pit_rows(rt)]


def approve(rt, at: str = "2026-09-30T00:00:00.000000Z") -> None:
    """READY capability + binding for the runtime's source (test registries only)."""

    from .emit_support import approve_source

    approve_source(rt.stores, at=at)


def summary(rt) -> dict:
    """The derivation-relevant durable history, independent of T2/T3."""

    return {
        "artifacts": sorted((row["entity_id"], row["available_at"], row["payload_hash"]) for row in pit_rows(rt)),
        "record_ids": sorted(row["record_id"] for row in pit_rows(rt)),
        "identity_head": rt.stores.identity.head(),
        "normalized": sorted(row["acquisition_id"] for row in acquisition_rows(rt)
                             if row["record_type"] == "acq_normalized"),
    }


def copy_config(target: Path) -> Path:
    destination = target / "config"
    shutil.copytree(CONFIG, destination)
    return destination


def run_rows(rt) -> list[dict]:
    return AppendOnlyJsonl(rt.root / "runs.jsonl").records()
