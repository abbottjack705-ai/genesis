"""The fixture-mode end-to-end pipeline (design 11.1): acquire -> raw capture -> parse -> emit.

``open_runtime`` wires the frozen stores, the quota gate, raw capture and the acquisition runner
under one runtime root. The runtime refuses to start when the module-provenance guard fails (F-41),
halts when the configuration on disk no longer matches the configuration it started with (F-31),
resumes cleanly after a crash at any step (A-3), and can rebuild every RESPONSE derivation into
empty stores from raw evidence plus the acquisition ledger (PIT-09).

Nothing here sends to a network: the transport is whatever the caller supplies (a fake in fixture
mode; the dormant live transport only after G1/G2, design 16).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from genesis.coverage import CoverageEntry, CoverageLedger, CoverageStatus
from genesis.evidence import EvidenceStore, StructuredEvidenceStore
from genesis.feature_manifest import SourceInputBindingStore
from genesis.pit import PITStore, SourceCapabilityRegistry
from genesis.provenance import SourceContractRegistry
from genesis.registry import AppendOnlyJsonl
from genesis.time import iso_utc

from genesis_adapters import config as adapter_config
from genesis_adapters.errors import AdapterFailure, reason_code
from genesis_adapters.ids import gid
from genesis_adapters.oddspapi import capability, derivation, emit, normalize, parser
from genesis_adapters.oddspapi import identity_registry as identity_mod
from genesis_adapters.oddspapi import quiescence
from genesis_adapters.oddspapi import scope as scope_mod
from genesis_adapters.oddspapi.acquisition import AcquisitionLedger, AcquisitionRunner, AttemptOutcome, PlanItem
from genesis_adapters.oddspapi.endpoints import RAW_CONTRACT_ID
from genesis_adapters.oddspapi.invalidation import InvalidationLedger
from genesis_adapters.oddspapi.maps import AdapterMaps, maps_from_config
from genesis_adapters.oddspapi.quota_gate import QuotaGate
from genesis_adapters.oddspapi.raw_capture import RawCapture, register_raw_contract
from genesis_adapters.oddspapi.reader import MarketBookReader

FIXTURE_LICENSING_NOTE = "FIXTURE-ONLY-NO-PROVIDER-TERMS"
_TAMPER_FAILURES = frozenset({AdapterFailure.EVIDENCE_CONFLICT, AdapterFailure.PIT_APPEND_CONFLICT})
RUN_SCHEMA = "adapter-run-v1"


class PipelineHalt(RuntimeError):
    """The runtime must stop; the reason is recorded durably before this is raised."""

    def __init__(self, code: AdapterFailure):
        super().__init__(str(code))
        self.code = code


@dataclass(frozen=True)
class PipelineResult:
    outcome: Any                       # AcquisitionOutcome
    emitted: emit.EmitResult | None = None


@dataclass
class AdapterRuntime:
    root: Path
    config_dir: Path
    config: adapter_config.AdapterConfig
    maps: AdapterMaps
    stores: emit.AdapterStores
    runner: AcquisitionRunner
    capture: RawCapture
    gate: QuotaGate
    clock: Any
    startup_digests: Mapping[str, str]
    runs: AppendOnlyJsonl
    checkpoint: Callable[[str], None] | None = None
    blocked: list = field(default_factory=list)

    # -- guards -------------------------------------------------------------------------------
    def _current_digests(self) -> dict[str, str]:
        digests = dict(adapter_config.load_config_digests(self.config_dir))
        digests["policy"] = adapter_config.load_policy(self.config_dir / adapter_config.POLICY_FILE).digest
        return digests

    def check_configuration(self) -> None:
        """F-31: the configuration on disk must still be the one this runtime started with."""

        if self._current_digests() == dict(self.startup_digests):
            return
        at = self.clock.now()
        self.stores.acquisition.append("acq_halted", recorded_at=at, reason=AdapterFailure.CONFIG_DIGEST_MISMATCH.value)
        self.stores.coverage.append(CoverageEntry(
            entry_id=gid("cov", runtime="config", at=at, note=AdapterFailure.CONFIG_DIGEST_MISMATCH.value),
            entity_id="oddspapi-runtime", source_contract_id=RAW_CONTRACT_ID, status=CoverageStatus.NOT_ATTEMPTED,
            recorded_at=at, reason_codes=(reason_code(AdapterFailure.CONFIG_DIGEST_MISMATCH),),
            note=AdapterFailure.CONFIG_DIGEST_MISMATCH.value))
        raise PipelineHalt(AdapterFailure.CONFIG_DIGEST_MISMATCH)

    # -- acquisition and normalization -------------------------------------------------------
    def acquire(self, item: PlanItem, *, clock_check: bool = False) -> PipelineResult:
        with quiescence.run_lock(self.root):              # design 6.3: one adapter phase at a time
            self.check_configuration()
            outcome = self.runner.acquire(item, clock_check=clock_check)
            emitted = None
            captured = getattr(outcome, "captured", None)
            if item.request.role == derivation.ROLE_ODDS and outcome.outcome == AttemptOutcome.RESPONSE \
                    and outcome.failure is None and captured is not None and captured.kind == "STORED":
                emitted = self.normalize(outcome.acquisition_id)
                if emitted is None:                         # its derivation was refused: the durable verdict says why
                    refused = self.stores.acquisition.attempts()[outcome.acquisition_id]
                    outcome = dataclasses.replace(outcome, failure=AdapterFailure(refused.failure))
            return PipelineResult(outcome, emitted)

    def _inputs(self, acquisition_id: str) -> derivation.DerivationInputs:
        rows = derivation.acquisition_rows(self.stores.acquisition, acquisition_id)
        completed, planned = rows["acq_completed"], rows["acq_planned"]
        join = derivation.fixture_snapshot_for(self.stores, self.config, self.maps, at=completed["T1"])
        normalized = rows.get("acq_normalized")
        if normalized is not None:                  # the pinned inputs of a finished derivation
            head = normalized["identity_registry_head"]
            prefix = self.stores.identity.prefix(head["sequence"])
            if identity_mod.head_of(prefix) != head:
                raise derivation.DerivationError("the pinned identity-registry head is not a prefix")
            scope_hash = normalized["expected_scope_hash"]
        else:                                       # a first derivation (or a resume before the row existed)
            prefix = self.stores.identity.rows()
            scope_hash = rows["acq_sent"]["expected_scope_hash"]
        # design 12.4 (hostile audit HA-11): exactly the scope pinned on the sent row BEFORE the send, never one
        # recomputed later from a PIT log that may have changed since
        if scope_hash is None or scope_hash != rows["acq_sent"]["expected_scope_hash"]:
            raise derivation.DerivationError("no expected scope was pinned before this ODDS request was sent")
        expected = scope_mod.load_scope(self.root, scope_hash)
        return derivation.odds_inputs(self.stores, self.config, self.maps, acquisition_id, identity_prefix=prefix,
                                      expected_scope=expected, expected_scope_hash=scope_hash, fixture_join=join,
                                      request_root=self.root)

    def normalize(self, acquisition_id: str) -> emit.EmitResult | None:
        """Derive one successful ODDS capture and publish it, or - when its pure derivation cannot produce documents -
        record the durable TERMINAL verdict and return None (hostile audit RA5-001).

        The pure stage runs inside the total boundary :func:`derivation.derive`, so provider content can never raise
        out of it. A capture that fails there is refused exactly once, durably (``reject_derivation``): afterwards it
        is not a successful capture, no restart re-derives it and nothing is pending. The one exception is a capture
        that was ALREADY normalized: its derivation was deterministic, so a failure now is a changed derivation or
        damaged evidence, an integrity halt (never a silent rewrite of what the documents were derived from)."""

        with quiescence.run_lock(self.root):
            self.check_configuration()
            inputs = self._inputs(acquisition_id)
            derived = derivation.derive(inputs.raw, inputs.ctx)
            if derived.failure is not None:
                if self.stores.acquisition.attempts()[acquisition_id].state != "COMPLETED":
                    self._halt(derived.failure, inputs.ctx.provider_request_hash)
                self.runner.reject_derivation(acquisition_id, derived.failure, self.config.derivation_version,
                                              derived.detail)
                return None
            try:
                return emit.emit_response(derived.parsed, inputs.ctx, stores=self.stores, clock=self.clock,
                                          checkpoint=self.checkpoint, documents=derived.documents)
            except emit.EmitConflict as conflict:
                self._halt(conflict.failure, inputs.ctx.provider_request_hash)

    def _halt(self, failure: AdapterFailure, request_hash: str) -> None:
        """Record a durable halt (every later acquisition is refused) plus its coverage entry, then stop."""

        at = self.clock.now()
        self.stores.acquisition.append("acq_halted", recorded_at=at, reason=failure.value)
        status = (CoverageStatus.QUARANTINED if failure in _TAMPER_FAILURES else
                  CoverageStatus.NOT_ATTEMPTED if failure == AdapterFailure.CONFIG_DIGEST_MISMATCH else
                  CoverageStatus.REJECTED)
        self.stores.coverage.append(CoverageEntry(
            entry_id=gid("cov", request=request_hash, at=at, note=failure.value),
            entity_id="oddspapi-request:" + request_hash, source_contract_id=self.stores.contract_id, status=status,
            recorded_at=at, reason_codes=(reason_code(failure),), note=failure.value))
        raise PipelineHalt(failure)

    # -- restart ---------------------------------------------------------------------------------
    def resume(self) -> tuple[tuple[str, ...], tuple[emit.EmitResult, ...]]:
        """Reconcile orphaned reservations (and settle the newest verdict), complete every invalidation a crash
        left pending (design 13.2, hostile audit HA-05), finish the newest derivation's identity rows, then derive
        every successful ODDS capture that has no normalized row yet (in ledger order)."""

        with quiescence.run_lock(self.root):
            reconciled = self.runner.reconcile_after_restart()
            emit.complete_pending_invalidations(self.stores, clock=self.clock)
            attempts = self.stores.acquisition.attempts()
            order: list[str] = []
            for row in self.stores.acquisition.rows():
                if row["record_type"] == "acq_planned":
                    order.append(row["acquisition_id"])
            odds = [aid for aid in order if attempts[aid].role == derivation.ROLE_ODDS]
            results: list[emit.EmitResult] = []
            finished = [aid for aid in odds if attempts[aid].state == "NORMALIZED"]
            if finished:
                results.append(self.normalize(finished[-1]))
            for aid in odds:
                rows = derivation.acquisition_rows(self.stores.acquisition, aid)
                if attempts[aid].state == "COMPLETED" and derivation.successful_capture(rows):
                    emitted = self.normalize(aid)
                    if emitted is not None:                 # None: refused, durably (it is not derived again)
                        results.append(emitted)
            return reconciled, tuple(results)

    # -- consumption and verification ----------------------------------------------------------
    def reader(self) -> MarketBookReader:
        """The production consumer (design 12.3): every head it returns re-derives exactly (step 7)."""

        return MarketBookReader(self.stores, derivation_check=self.checked_derivation)

    def checked_derivation(self, observation_id: str) -> None:
        """``verify_derivation`` for a head about to be used; one that fails is invalidated automatically
        (design 13.2, ADAPTER_AUTOMATIC) before the failure is passed on, so the reader refuses it now and the
        INVALIDATED head supersedes it from its own admissible time on (hostile audit HA-12)."""

        try:
            self.verify_derivation(observation_id)
        except Exception:
            emit.invalidate_if_underivable(observation_id, check=self.verify_derivation, stores=self.stores,
                                           clock=self.clock)
            raise

    def verify_derivation(self, observation_id: str) -> None:
        derivation.verify_derivation(observation_id, stores=self.stores, config=self.config, maps=self.maps)

    def verify_all(self) -> int:
        return derivation.verify_all(self.stores, self.config, self.maps)


# --------------------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------------------
def build_stores(root: Path, *, derivation_version: str, policy, licensing_note: str) -> emit.AdapterStores:
    root = Path(root)
    contracts = SourceContractRegistry(root / "contracts.jsonl")
    register_raw_contract(contracts, licensing_note=licensing_note)
    emit.register_normalized_contract(contracts, derivation_version=derivation_version, licensing_note=licensing_note)
    evidence = EvidenceStore(root / "evidence", contracts=contracts)
    capabilities = SourceCapabilityRegistry(root / "capabilities.jsonl")
    return emit.AdapterStores(
        root=root, contracts=contracts, evidence=evidence,
        structured=StructuredEvidenceStore(root / "structured", evidence=evidence), capabilities=capabilities,
        bindings=SourceInputBindingStore(root / "bindings.jsonl"), pit=PITStore(root / "pit.jsonl",
                                                                                capabilities=capabilities),
        coverage=CoverageLedger(root / "coverage.jsonl"), identity=identity_mod.IdentityRegistry(root / "identity.jsonl"),
        acquisition=AcquisitionLedger(root / "acquisition.jsonl"),
        invalidations=InvalidationLedger(root / "invalidations.jsonl"), derivation_version=derivation_version,
        licensing_note=licensing_note, policy=policy)


def _refuse_start(root: Path, clock, reason: AdapterFailure, detail: str) -> None:
    """F-41: record the refusal (run record + NOT_ATTEMPTED coverage) and refuse to start."""

    at = clock.now()
    AppendOnlyJsonl(Path(root) / "runs.jsonl").append({"record_type": "run_refused", "schema_version": RUN_SCHEMA,
                                                         "recorded_at": at, "reason": reason.value,
                                                         "guard_verdict": detail})
    CoverageLedger(Path(root) / "coverage.jsonl").append(CoverageEntry(
        entry_id=gid("cov", runtime="start", at=at, note=reason.value), entity_id="oddspapi-runtime",
        source_contract_id=RAW_CONTRACT_ID, status=CoverageStatus.NOT_ATTEMPTED, recorded_at=at,
        reason_codes=(reason_code(reason),), note=reason.value))
    raise PipelineHalt(reason)


def open_runtime(root: Path, *, config_dir: Path, clock, transport, quota_ledger, cache, secret=None,
                 live: bool = False, authority=None, credential_check=None, require_date: bool = False,
                 licensing_note: str = FIXTURE_LICENSING_NOTE, allow_fixture_only: bool = True,
                 provenance_check: Callable[[], Mapping[str, Any]], checkpoint=None,
                 runner_checkpoint=None) -> AdapterRuntime:
    """Start a runtime under ``root``. ``provenance_check`` is the module-provenance guard (design 2.4); it
    must return the guard's verdict record, and any exception refuses the start (F-41)."""

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        verdict = provenance_check()
    except Exception as exc:                                  # any guard failure refuses the start
        _refuse_start(root, clock, AdapterFailure.MODULE_PROVENANCE, type(exc).__name__)
    config = adapter_config.load_adapter_config(config_dir, allow_fixture_only=allow_fixture_only,
                                                code_version=normalize.CODE_VERSION)
    maps = maps_from_config(config)
    stores = build_stores(root, derivation_version=config.derivation_version, policy=config.policy,
                          licensing_note=licensing_note)
    gate = QuotaGate(quota_ledger, cache, cache_index_path=root / "quota" / "cache-index.jsonl")
    raw = RawCapture(root=root, evidence=stores.evidence, gate=gate, config=config, secret=secret,
                     require_date=require_date, licensing_note=licensing_note)
    blocked: list = []

    def block_capabilities(reason: str) -> None:
        blocked.append(reason)
        # idempotent: a restart that settles the same verdict again leaves an already BLOCKED source as it is
        capability.block_market_book_sources(stores.capabilities, at=clock.now(), reason=reason,
                                             also=(stores.source_id,), skip_blocked=True)

    def pin_scope(request, tq: str) -> str | None:
        """Design 12.4: the expected scope of an ODDS request as of ``Tq``, written immutably before the send."""

        if request.role != derivation.ROLE_ODDS:
            return None
        expected = derivation.expected_scope_at(stores, maps, json.loads(request.canonical_bytes()), tq=tq)
        return scope_mod.publish_scope(root, expected.values(), as_of=tq)

    runner = AcquisitionRunner(root=root, clock=clock, transport=transport, quota=gate, authority=authority,
                               config=config, live=live, credential_check=credential_check,
                               checkpoint=runner_checkpoint, capability_blocker=block_capabilities, capture=raw,
                               scope_pinner=pin_scope)
    digests = dict(adapter_config.load_config_digests(config_dir))
    digests["policy"] = config.policy.digest
    runs = AppendOnlyJsonl(root / "runs.jsonl")
    runs.append({"record_type": "run_started", "schema_version": RUN_SCHEMA, "recorded_at": clock.now(),
                 "derivation_version": config.derivation_version, "config_digests": dict(sorted(digests.items())),
                 "guard_verdict": verdict.get("verdict") if isinstance(verdict, Mapping) else None, "live": live})
    return AdapterRuntime(root=root, config_dir=Path(config_dir), config=config, maps=maps, stores=stores,
                          runner=runner, capture=raw, gate=gate, clock=clock, startup_digests=digests, runs=runs,
                          checkpoint=checkpoint, blocked=blocked)


# --------------------------------------------------------------------------------------
# PIT-09: rebuild every RESPONSE derivation into empty stores
# --------------------------------------------------------------------------------------
def rebuild_into(source: AdapterRuntime, target: emit.AdapterStores, *, clock) -> tuple[emit.EmitResult, ...]:
    """Re-derive every normalized ODDS acquisition of ``source`` into the empty ``target`` stores.

    Inputs are the durable ones only: the source's raw evidence (re-published byte-exact with identical
    observation fields, hence identical observation ids), its acquisition ledger, its request bytes, its
    pinned expected-scope artifacts and the pinned identity-registry heads (the target registry is rebuilt
    by applying the same rows in the same order, so the heads match or the rebuild fails). ``T2``/``T3`` are
    new, which changes no artifact: documents carry neither.
    """

    from genesis.repro import immutable_write

    results: list[emit.EmitResult] = []
    order: list[str] = []
    for row in source.stores.acquisition.rows():
        if row["record_type"] == "acq_planned":
            order.append(row["acquisition_id"])
    for aid in order:
        rows = derivation.acquisition_rows(source.stores.acquisition, aid)
        if not derivation.successful_capture(rows):
            continue
        raw_observation = source.stores.evidence.get_observation(rows["acq_completed"]["raw_observation_id"])
        copy = target.evidence.publish(
            source.stores.evidence.get_bytes(raw_observation.artifact_hash), contract_id=raw_observation.contract_id,
            source_uri=raw_observation.source_uri, provider=raw_observation.provider,
            source_type=raw_observation.source_type, retrieved_at=raw_observation.retrieved_at,
            first_seen_at=raw_observation.first_seen_at, parse_ready_at=raw_observation.parse_ready_at,
            publisher_timestamp=raw_observation.publisher_timestamp, valid_from=raw_observation.valid_from,
            valid_to=raw_observation.valid_to, upstream_version=raw_observation.upstream_version,
            parser_version=raw_observation.parser_version, content_type=raw_observation.content_type,
            licensing_note=raw_observation.licensing_note, availability_class=raw_observation.availability_class)
        if copy.observation_id != raw_observation.observation_id:
            raise derivation.DerivationError("a copied raw observation changed identity")
        normalized = rows.get("acq_normalized")
        if rows["acq_planned"]["role"] != derivation.ROLE_ODDS or normalized is None:
            continue
        head = normalized["identity_registry_head"]
        prefix = target.identity.rows()
        if identity_mod.head_of(prefix) != head:
            raise derivation.DerivationError("the rebuilt identity registry diverged from the pinned head")
        scope_hash = normalized["expected_scope_hash"]
        if scope_hash is None or scope_hash != rows["acq_sent"]["expected_scope_hash"]:
            raise derivation.DerivationError("the normalized scope is not the one pinned before the send")
        expected = scope_mod.load_scope(source.root, scope_hash)
        immutable_write(Path(target.root) / "scopes" / f"{scope_hash}.json",
                        (Path(source.root) / "scopes" / f"{scope_hash}.json").read_bytes())
        join = derivation.fixture_snapshot_for(_Reading(source.stores.acquisition, target.evidence), source.config,
                                               source.maps, at=rows["acq_completed"]["T1"])
        inputs = derivation.odds_inputs(_Reading(source.stores.acquisition, target.evidence), source.config,
                                        source.maps, aid, identity_prefix=prefix, expected_scope=expected,
                                        expected_scope_hash=scope_hash, fixture_join=join, request_root=source.root)
        parsed = parser.parse_odds_response(inputs.raw, inputs.ctx)
        results.append(emit.emit_documents(parsed, inputs.ctx, stores=target, clock=clock))
        target.identity.apply(parsed.identity_rows)
    return tuple(results)


@dataclass(frozen=True)
class _Reading:
    """The source acquisition ledger read together with the target evidence store."""

    acquisition: AcquisitionLedger
    evidence: EvidenceStore
