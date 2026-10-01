"""Test-only helpers for the emission / PIT / reader stages (S5): real frozen stores in a scratch root."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

from genesis.coverage import CoverageLedger
from genesis.evidence import EvidenceStore, StructuredEvidenceStore
from genesis.feature_manifest import SourceInputBindingStore
from genesis.pit import OperationalStatus, PITStore, SourceCapability, SourceCapabilityRegistry
from genesis.provenance import SourceContractRegistry

from genesis_adapters import config as adapter_config
from genesis_adapters.oddspapi import emit, parser
from genesis_adapters.oddspapi import identity_registry as identity_mod
from genesis_adapters.oddspapi.acquisition import AcquisitionLedger
from genesis_adapters.oddspapi.invalidation import InvalidationLedger

from . import parser_support as ps
from .support import SequenceClock

NOTE = "FIXTURE-ONLY-NO-PROVIDER-TERMS"
CAPABILITY_TIME = "2026-09-30T00:00:00.000000Z"     # a capability row that predates every capture below
CAPTURE_1 = "2026-10-01T12:00:00.000000Z"
CAPTURE_2 = "2026-10-01T12:30:00.000000Z"


def iso(base: str, *, seconds: float = 0, micros: int = 0) -> str:
    return ps.iso_add(base, seconds=seconds, micros=micros)


def build_stores(root: Path, *, derivation_version: str | None = None, policy=None, ready: bool = True,
                 capability_time: str = CAPABILITY_TIME) -> emit.AdapterStores:
    version = derivation_version or ps.DERIVATION
    contracts = SourceContractRegistry(root / "contracts.jsonl")
    emit.register_normalized_contract(contracts, derivation_version=version, licensing_note=NOTE)
    evidence = EvidenceStore(root / "evidence", contracts=contracts)
    capabilities = SourceCapabilityRegistry(root / "capabilities.jsonl")
    stores = emit.AdapterStores(
        root=root, contracts=contracts, evidence=evidence,
        structured=StructuredEvidenceStore(root / "structured", evidence=evidence), capabilities=capabilities,
        bindings=SourceInputBindingStore(root / "bindings.jsonl"),
        pit=PITStore(root / "pit.jsonl", capabilities=capabilities), coverage=CoverageLedger(root / "coverage.jsonl"),
        identity=identity_mod.IdentityRegistry(root / "identity.jsonl"),
        acquisition=AcquisitionLedger(root / "acquisition.jsonl"),
        invalidations=InvalidationLedger(root / "invalidations.jsonl"), derivation_version=version,
        licensing_note=NOTE, policy=policy or ps.POLICY)
    if ready:
        approve_source(stores, at=capability_time)
    return stores


def source_capability(stores: emit.AdapterStores, *, status: OperationalStatus, at: str, suffix: str,
                      reliability: str = "prospective_verified") -> SourceCapability:
    return SourceCapability(
        source_id=stores.source_id, provider="oddspapi", access_method="rest_pregame_v4", cost_tier="fixture",
        entitlement_class="fixture", historical_availability_class="none", point_in_time_reliability=reliability,
        revision_behaviour="append_only_supersede", coverage="fixture", rate_quota_limits="fixture",
        schema_version="v1", operational_status=status, recorded_at=at, version=f"{stores.derivation_version}-{suffix}")


def approve_source(stores: emit.AdapterStores, *, at: str, approval: str = "synthetic-test-only-binding") -> None:
    """READY capability plus the approved 1:1 binding (test registries only; never adapter runtime code)."""

    stores.capabilities.register(source_capability(stores, status=OperationalStatus.READY, at=at, suffix="ready-1"))
    stores.bindings.register(source_id=stores.source_id, source_contract_id=stores.contract_id,
                             provider="oddspapi", approval_reference=approval)


def set_capability(stores: emit.AdapterStores, status: OperationalStatus, at: str, suffix: str) -> None:
    stores.capabilities.register(source_capability(stores, status=status, at=at, suffix=suffix))


def seed_acquisition(stores: emit.AdapterStores, ctx: parser.ParseContext, *, request_hash: str | None = None) -> None:
    """The acquisition rows that precede emission (planned .. completed), timed consistently with ``ctx``."""

    aid, t0, t1 = ctx.acquisition_id, ctx.request_started_at, ctx.response_received_at
    tq = iso(t0, micros=-1000)
    ledger = stores.acquisition
    ledger.append("acq_planned", recorded_at=iso(t0, micros=-2000), acquisition_id=aid,
                  request_id="oddspapi-attempt:" + aid, window_id="w-" + aid[:8], purpose="SCHEDULED", attempt=1,
                  provider_request_hash=request_hash or ctx.provider_request_hash, role="ODDS",
                  provider_metering="PER_REQUEST", provider_request_weight=1, provider_documented_billable=True,
                  genesis_debit_units=1)
    ledger.append("acq_quota_decided", recorded_at=iso(t0, micros=-500), acquisition_id=aid, Tq=tq,
                  frozen_ledger_reason="billable_call_reserved", allowed=True, genesis_units_debited=1,
                  cache_entry_id=None, cache_miss_reason=None)
    ledger.append("acq_sent", recorded_at=t0, acquisition_id=aid, T0=t0,
                  expected_scope_hash=ctx.expected_scope_hash)            # pinned before the send (12.4)
    ledger.append("acq_completed", recorded_at=t1, acquisition_id=aid, T1=t1, outcome="RESPONSE", http_status=200,
                  headers=[], content_encoding=None, byte_length=1, raw_observation_id=ctx.raw_observation_id,
                  sanitized_error=None, provider_reported_usage=None, failure=None)


# The request this emission harness answers: tournament 17 only, which is what ``small_payload()`` keeps (fixture
# A). The parse context always carries the request's competitions; a request that also named tournament 8 would
# make these reduced responses partial (design 12.4 / F-15, hostile audit F-03 - tested in test_v05_r1_*).
HARNESS_REQUEST = (ps.MAPS.competition("int", "17").genesis_id,)


def make_capture_ctx(stores: emit.AdapterStores, raw: bytes, *, t1: str, expected_scope=None, expected_hash=None,
                     fixture_join=None, complete_hint: bool = True, derivation_version: str | None = None,
                     tag: str = "", policy=None, maps=None, requested_competitions=HARNESS_REQUEST):
    return ps.make_ctx(
        requested_competitions=requested_competitions,
        acquisition_id=hashlib.sha256(f"acquisition-{t1}-{tag}".encode()).hexdigest(),
        raw_observation_id=hashlib.sha256(f"raw-observation-{t1}-{tag}".encode()).hexdigest(),
        raw_artifact_hash=hashlib.sha256(raw).hexdigest(), request_started_at=iso(t1, seconds=-0.1),
        response_received_at=t1, derivation_version=derivation_version or stores.derivation_version,
        identity_prefix=tuple(stores.identity.rows()), expected_scope=expected_scope,
        expected_scope_hash=expected_hash, fixture_join=fixture_join, complete_hint=complete_hint,
        policy=policy or stores.policy, maps=maps or ps.MAPS)


def capture(stores: emit.AdapterStores, payload, *, t1: str = CAPTURE_1, t2: str | None = None,
            t3: str | None = None, stamp: str | None = None, expected_scope=None, expected_hash=None,
            complete_hint: bool = True, checkpoint=None, clock=None, ctx=None, seed: bool = True, tag: str = "",
            fixture_join=None):
    """Parse ``payload`` as one ODDS response received at ``t1`` and emit it. Returns (parsed, ctx, result).

    ``T2``/``T3`` default to ``t1 + 0.5 s`` / ``t1 + 1 s`` (the times the stages really completed)."""

    raw = payload if isinstance(payload, bytes) else ps.dump(payload)
    ctx = ctx or make_capture_ctx(stores, raw, t1=t1, expected_scope=expected_scope, expected_hash=expected_hash,
                                  complete_hint=complete_hint, tag=tag, fixture_join=fixture_join)
    parsed = parser.parse_odds_response(raw, ctx)
    if seed:
        seed_acquisition(stores, ctx)
    t2 = t2 or iso(t1, seconds=0.5)
    t3 = t3 or iso(t1, seconds=1)
    clock = clock or SequenceClock([t2, t3, stamp or iso(t3, micros=1)])
    result = emit.emit_response(parsed, ctx, stores=stores, clock=clock, checkpoint=checkpoint)
    return parsed, ctx, result


def small_payload(*, bookmakers=("pinnacle",), fixtures=("A",)):
    """A reduced ODDS payload (fewer books) for tests that run emission many times."""

    payload = ps.odds_payload()
    keep = {"A": ps.FIXTURE_A, "B": ps.FIXTURE_B}
    payload = [item for item in payload if item["fixtureId"] in {keep[name] for name in fixtures}]
    for item in payload:
        item["bookmakerOdds"] = {key: value for key, value in item["bookmakerOdds"].items() if key in bookmakers}
    return payload


def pit_rows(stores: emit.AdapterStores) -> list[dict]:
    return [row for row in stores.pit.log.records() if row.get("record_type") == "pit_record"]


def coverage_rows(stores: emit.AdapterStores) -> list[dict]:
    return [row for row in stores.coverage.log.records() if row.get("record_type") == "coverage"]


def head_book(parsed: parser.ParsedResponse, *, fixture: str = ps.FIXTURE_A, bookmaker: str = "pinnacle",
              family: str = "SOCCER_TOTAL_GOALS_OU_FT") -> parser.BookResult:
    return ps.one_book(parsed, fixture=fixture, bookmaker=bookmaker, family=family)


def doc_json(stores: emit.AdapterStores, artifact_hash: str) -> dict:
    return json.loads(stores.evidence.get_bytes(artifact_hash))


def with_version(stores: emit.AdapterStores, derivation_version: str) -> emit.AdapterStores:
    """The same physical stores under another derivation (new contract, source, binding, capability)."""

    other = dataclasses.replace(stores, derivation_version=derivation_version)
    emit.register_normalized_contract(other.contracts, derivation_version=derivation_version, licensing_note=NOTE)
    return other


def reopen(stores: emit.AdapterStores) -> emit.AdapterStores:
    """Fresh store objects over the same files: what a restarted process sees."""

    root = stores.root
    contracts = SourceContractRegistry(root / "contracts.jsonl")
    evidence = EvidenceStore(root / "evidence", contracts=contracts)
    capabilities = SourceCapabilityRegistry(root / "capabilities.jsonl")
    return dataclasses.replace(
        stores, contracts=contracts, evidence=evidence,
        structured=StructuredEvidenceStore(root / "structured", evidence=evidence), capabilities=capabilities,
        bindings=SourceInputBindingStore(root / "bindings.jsonl"),
        pit=PITStore(root / "pit.jsonl", capabilities=capabilities), coverage=CoverageLedger(root / "coverage.jsonl"),
        identity=identity_mod.IdentityRegistry(root / "identity.jsonl"),
        acquisition=AcquisitionLedger(root / "acquisition.jsonl"),
        invalidations=InvalidationLedger(root / "invalidations.jsonl"))


def structured_files(stores: emit.AdapterStores) -> list[Path]:
    folder = stores.root / "structured"
    return sorted(folder.glob("*.json")) if folder.exists() else []


def durable_summary(stores: emit.AdapterStores) -> dict:
    """What a crash-resumed history must equal, modulo the times of the steps that ran after the restart."""

    observations = {}
    for row in pit_rows(stores):
        found = [o for o in stores.evidence.get_observations(row["payload_hash"]) if o.contract_id == stores.contract_id]
        observations[row["payload_hash"]] = len(found)
    identity = sorted((r["record_type"], r.get("event_id") or r.get("participant_id")) for r in stores.identity.rows())
    return {
        "artifacts": sorted(row["payload_hash"] for row in pit_rows(stores)),
        "record_ids": sorted(row["record_id"] for row in pit_rows(stores)),
        "observations_per_artifact": sorted(observations.values()),
        "coverage_ids": sorted(row["entry_id"] for row in coverage_rows(stores)),
        "coverage_duplicates": len(coverage_rows(stores)) - len({r["entry_id"] for r in coverage_rows(stores)}),
        "normalized_rows": sum(1 for r in stores.acquisition.rows() if r["record_type"] == "acq_normalized"),
        "identity": identity,
        "structured": len(structured_files(stores)),
        "manifest_rows": stores.evidence.verify_manifest(),
    }
