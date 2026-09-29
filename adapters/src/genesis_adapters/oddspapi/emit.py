"""Emission of one parsed response: normalized evidence, structured evidence, PIT, coverage (design 11).

Order (each step durable before the next, every step idempotent so that a crash at ANY point can be
resumed by simply running the same emission again with a later clock):

1. ``T2`` <- clock; every document becomes a normalized observation under the derivation's contract
   (an observation already published for the same artifact is verified field by field and reused);
2. one ``ResearchEvidence`` per OPEN book;
3. ``T3`` <- clock, after everything above is durable;
4. one PIT record per document (``record_id`` is keyed on the artifact, so a resume can never create a
   second record; an existing record must equal the intended one in every field except ``ready_at``,
   whose earlier value is when it really became durable);
5. coverage entries (exactly once, by deterministic entry id);
6. the acquisition row ``normalized``;
7. the identity-registry rows, LAST, so that the registry prefix a resumed derivation sees is the same
   prefix the original derivation pinned.

An existing artifact under the same identity but different content is a conflict and halts; nothing
is ever overwritten. ``T2``/``T3`` are never reused across a resume, so nothing becomes admissible
earlier than it really became durable.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from genesis.canonical import EvidenceStatus, ResearchEvidence
from genesis.coverage import CoverageEntry, CoverageLedger, CoverageStatus
from genesis.evidence import EvidenceObservation, EvidenceStore, StructuredEvidenceStore
from genesis.pit import BitemporalRecord, PITStore, SourceCapabilityRegistry
from genesis.provenance import AvailabilityClass, ProvenanceRef, SourceContract, SourceContractRegistry
from genesis.registry import RegistryConflict
from genesis.repro import canonical_json, sha256_bytes
from genesis.time import iso_utc, parse_utc

from genesis_adapters import config as adapter_config
from genesis_adapters.clock import ClockFault, TrustedClock, require_not_before
from genesis_adapters.errors import AdapterFailure, reason_code
from genesis_adapters.ids import gid
from genesis_adapters.oddspapi import identity_registry as identity_mod
from genesis_adapters.oddspapi.acquisition import AcquisitionLedger
from genesis_adapters.oddspapi.invalidation import (
    EFFECT_EMITTED, EFFECT_SUPERSEDED, InvalidationLedger, applied_row, build_invalidation_document,
    recorded_row,
)
from genesis_adapters.oddspapi.normalize import NormalizedDocument, build_documents
from genesis_adapters.oddspapi.parser import (
    STATE_ABSENT, STATE_BLOCKED, STATE_OPEN, STATE_SUSPENDED, ParseContext, ParsedResponse,
)

PROVIDER = "oddspapi"
NORMALIZED_SOURCE_TYPE = "oddspapi_v4_market_book"
NORMALIZED_CONTENT_TYPE = "application/json"
EVIDENCE_CATEGORY = "market_price.bookmaker_back"
PIT_DOMAIN = "genesis.adapters.pit-record.v1"
UPSTREAM_VERSION = "v4"
HTTP_OK = 200
COVERAGE_AGGREGATE_PREFIX = "oddspapi-request:"
_AMBIGUOUS_CODES = frozenset({AdapterFailure.IDENTITY_CONFLICT, AdapterFailure.PARTICIPANT_AMBIGUOUS})
_MISSING_CODES = frozenset({AdapterFailure.EVENT_METADATA_STALE})


class EmitConflict(RuntimeError):
    """Emission must halt: an existing artifact contradicts what it would write (F-32/F-33), the inputs do not
    belong to one completed acquisition, or the running configuration is not the derivation's (F-31).
    Nothing is ever overwritten."""

    def __init__(self, failure: AdapterFailure, detail: str = ""):
        super().__init__(f"{failure}: {detail}" if detail else str(failure))
        self.failure = failure
        self.detail = detail


@dataclass(frozen=True)
class AdapterStores:
    """Every durable store emission and the reader touch, plus the derivation they belong to."""

    root: Path
    contracts: SourceContractRegistry
    evidence: EvidenceStore
    structured: StructuredEvidenceStore
    capabilities: SourceCapabilityRegistry
    bindings: Any
    pit: PITStore
    coverage: CoverageLedger
    identity: identity_mod.IdentityRegistry
    acquisition: AcquisitionLedger
    invalidations: InvalidationLedger
    derivation_version: str
    licensing_note: str
    policy: Any                                    # the SlicePolicy this derivation was built with

    @property
    def contract_id(self) -> str:
        return adapter_config.normalized_contract_id(self.derivation_version)

    @property
    def source_id(self) -> str:
        return adapter_config.market_book_source_id(self.derivation_version)


@dataclass(frozen=True)
class EmitResult:
    t2: str
    t3: str
    observation_ids: tuple[str, ...]
    structured_hashes: tuple[str, ...]
    pit_record_ids: tuple[str, ...]
    coverage_entry_ids: tuple[str, ...]
    identity_rows_applied: int
    already_normalized: bool = False


# --------------------------------------------------------------------------------------
# Contracts, ids, uris
# --------------------------------------------------------------------------------------
def normalized_contract(derivation_version: str, licensing_note: str) -> SourceContract:
    return SourceContract(
        contract_id=adapter_config.normalized_contract_id(derivation_version), provider=PROVIDER,
        source_type=NORMALIZED_SOURCE_TYPE,
        uri_pattern=f"genesis-derived:oddspapi-v4-market-book:{derivation_version}:*",
        availability_class=AvailabilityClass.DERIVED, timestamp_precision="microsecond",
        availability_rule="available at T1; ready at T3; valid until valid_to",
        parser_version=derivation_version, licensing_note=licensing_note,
        supports_historical_reconstruction=False, supports_prospective_capture=False)


def register_normalized_contract(contracts: SourceContractRegistry, *, derivation_version: str,
                                 licensing_note: str) -> str:
    return contracts.register(normalized_contract(derivation_version, licensing_note))


def pit_record_id(source_id: str, artifact_hash: str) -> str:
    """Keyed on the artifact, never on the observation (whose id contains ``T2``)."""

    return "pit:" + sha256_bytes(canonical_json({"domain": PIT_DOMAIN, "source_id": source_id,
                                                 "artifact_hash": artifact_hash}))


def response_source_uri(derivation_version: str, entity_id: str, raw_observation_id: str) -> str:
    return f"genesis-derived:oddspapi-v4-market-book:{derivation_version}:{entity_id}:{raw_observation_id}"


def invalidation_source_uri(derivation_version: str, entity_id: str, invalidation_id: str) -> str:
    return f"genesis-derived:oddspapi-v4-market-book:{derivation_version}:{entity_id}:invalidation:{invalidation_id}"


# --------------------------------------------------------------------------------------
# Idempotent building blocks
# --------------------------------------------------------------------------------------
def _identity_fields(observation: EvidenceObservation) -> dict[str, Any]:
    """The observation's fields that a re-derivation must reproduce exactly (everything but the ids and T2)."""

    body = observation.unsigned_dict()
    body.pop("parse_ready_at")
    return body


def _publish_observation(stores: AdapterStores, document: NormalizedDocument, *, source_uri: str, t2: str,
                         retrieved_at: str) -> EvidenceObservation:
    """Publish the normalized observation, or verify and reuse the one a crashed run already published."""

    wanted = dict(
        contract_id=stores.contract_id, source_uri=source_uri, provider=PROVIDER,
        source_type=NORMALIZED_SOURCE_TYPE, retrieved_at=retrieved_at, first_seen_at=retrieved_at,
        publisher_timestamp=document.publisher_timestamp, valid_from=retrieved_at, valid_to=document.valid_to,
        upstream_version=UPSTREAM_VERSION, parser_version=stores.derivation_version,
        content_type=NORMALIZED_CONTENT_TYPE, licensing_note=stores.licensing_note,
        availability_class=AvailabilityClass.DERIVED)
    existing = [item for item in stores.evidence.get_observations(document.artifact_hash)
                if item.contract_id == stores.contract_id]
    if not existing:
        try:
            return stores.evidence.publish(document.data, parse_ready_at=t2, **wanted)
        except (RegistryConflict, ValueError):
            raise EmitConflict(AdapterFailure.EVIDENCE_CONFLICT) from None
    if len(existing) != 1:
        raise EmitConflict(AdapterFailure.EVIDENCE_CONFLICT)
    probe = dict(wanted, availability_class=wanted["availability_class"].value)
    have = _identity_fields(existing[0])
    for name, value in probe.items():
        stored = have.get(name)
        if name in ("retrieved_at", "first_seen_at", "valid_from", "valid_to", "publisher_timestamp") and value:
            value = iso_utc(value)
        if stored != value:
            raise EmitConflict(AdapterFailure.EVIDENCE_CONFLICT)
    return existing[0]


def _research_evidence(document: NormalizedDocument, observation: EvidenceObservation,
                       body: dict[str, Any], stores: AdapterStores) -> ResearchEvidence:
    claim = canonical_json({"market_id": body["market_id"], "bookmaker_id": body["bookmaker_id"],
                            "line": body["line"],
                            "odds": {sel: item["odds_decimal"] for sel, item in sorted(body["selections"].items())}})
    return ResearchEvidence(
        evidence_id=gid("rev", observation_id=observation.observation_id), event_id=body["event_id"],
        category=EVIDENCE_CATEGORY, normalized_claim=claim.decode("utf-8").rstrip("\n"),
        source_ref=ProvenanceRef(
            artifact_hash=document.artifact_hash, contract_id=stores.contract_id,
            source_uri=observation.source_uri, retrieved_at=observation.retrieved_at,
            parse_ready_at=observation.parse_ready_at, availability_class=AvailabilityClass.DERIVED,
            parser_version=stores.derivation_version, observation_id=observation.observation_id),
        source_timestamp=document.publisher_timestamp, retrieved_at=observation.retrieved_at,
        status=EvidenceStatus.CONFIRMED, freshness_expires_at=document.valid_to,
        extractor_version=stores.derivation_version, ready_at=observation.parse_ready_at)


def _pit_record(stores: AdapterStores, document: NormalizedDocument, *, t1: str, t3: str) -> BitemporalRecord:
    return BitemporalRecord(
        record_id=pit_record_id(stores.source_id, document.artifact_hash), entity_id=document.entity_id,
        source_id=stores.source_id, payload_hash=document.artifact_hash, available_at=t1,
        published_at=document.publisher_timestamp, retrieved_at=t1, ready_at=t3, valid_from=t1,
        valid_to=document.valid_to, superseded_by=None, superseded_at=None)


def append_pit_once(stores: AdapterStores, record: BitemporalRecord) -> str:
    """Append ``record`` unless the identical one exists (identical except for its earlier ``ready_at``).

    Anything else under the same ``record_id`` is a conflict (F-33): the frozen store is append-only and
    an existing row is never replaced.
    """

    for row in stores.pit.log.records():
        if row.get("record_type") == "pit_record" and row.get("record_id") == record.record_id:
            existing = BitemporalRecord(**{key: row[key] for key in BitemporalRecord.__dataclass_fields__})
            if dataclasses.replace(existing, ready_at=record.ready_at) != record:
                raise EmitConflict(AdapterFailure.PIT_APPEND_CONFLICT)
            return existing.record_id
    try:
        stores.pit.append(record)
    except RegistryConflict:
        raise EmitConflict(AdapterFailure.PIT_APPEND_CONFLICT) from None
    return record.record_id


def append_coverage_once(stores: AdapterStores, entry: CoverageEntry) -> str:
    """Append ``entry`` exactly once: an existing entry id must carry identical content (``recorded_at`` aside)."""

    for row in stores.coverage.log.records():
        if row.get("record_type") == "coverage" and row.get("entry_id") == entry.entry_id:
            wanted = {"entity_id": entry.entity_id, "source_contract_id": entry.source_contract_id,
                      "status": entry.status.value, "reason_codes": [code.value for code in entry.reason_codes],
                      "artifact_hash": entry.artifact_hash, "supersedes_entry_id": entry.supersedes_entry_id,
                      "note": entry.note}
            if {key: row.get(key) for key in wanted} != wanted:
                raise EmitConflict(AdapterFailure.EVIDENCE_CONFLICT)
            return entry.entry_id
    stores.coverage.append(entry)
    return entry.entry_id


def _block_status(failure: AdapterFailure) -> CoverageStatus:
    if failure in _AMBIGUOUS_CODES:
        return CoverageStatus.AMBIGUOUS
    if failure in _MISSING_CODES:
        return CoverageStatus.MISSING
    return CoverageStatus.REJECTED


def _coverage_entries(stores: AdapterStores, parsed: ParsedResponse, ctx: ParseContext,
                      documents: Sequence[NormalizedDocument], *, recorded_at: str) -> list[CoverageEntry]:
    """One entry per non-OPEN reason (design 15) plus aggregated exclusions and OPEN availability."""

    entries: list[CoverageEntry] = []
    aid = ctx.acquisition_id
    by_entity = {document.entity_id: document for document in documents}

    def entry(entity: str, status: CoverageStatus, note: str, *, reasons=(), artifact: str | None = None):
        entries.append(CoverageEntry(
            entry_id=gid("cov", acquisition_id=aid, entity_id=entity, note=note), entity_id=entity,
            source_contract_id=stores.contract_id, status=status, recorded_at=recorded_at,
            reason_codes=tuple(reasons), artifact_hash=artifact, note=note))

    for book in parsed.books:
        document = by_entity[book.entity_id]
        if book.state in (STATE_OPEN, STATE_SUSPENDED):
            entry(book.entity_id, CoverageStatus.AVAILABLE, book.state if book.state == STATE_OPEN
                  else "SUSPENDED:" + ",".join(book.reasons), artifact=document.artifact_hash)
        else:
            for code in book.reasons:
                failure = AdapterFailure(code)
                entry(book.entity_id, _block_status(failure), code, reasons=(reason_code(failure),))
    for tombstone in parsed.tombstones:
        entry(tombstone.entity_id, CoverageStatus.AVAILABLE, AdapterFailure.BOOK_ABSENT.value,
              artifact=by_entity[tombstone.entity_id].artifact_hash)
    for item in parsed.exclusions:
        failure = AdapterFailure(item.code)
        note = f"{item.code}:{item.count}"
        entries.append(CoverageEntry(
            entry_id=gid("cov", acquisition_id=aid, entity_id="response", note=item.code),
            entity_id=COVERAGE_AGGREGATE_PREFIX + ctx.provider_request_hash, source_contract_id=stores.contract_id,
            status=CoverageStatus.REJECTED, recorded_at=recorded_at, reason_codes=(reason_code(failure),),
            note=note))
    for event_id in parsed.quarantined_events:
        entries.append(CoverageEntry(
            entry_id=gid("cov", acquisition_id=aid, entity_id=event_id, note="EVENT_QUARANTINED"),
            entity_id=event_id, source_contract_id=stores.contract_id, status=CoverageStatus.QUARANTINED,
            recorded_at=recorded_at, reason_codes=(reason_code(AdapterFailure.IDENTITY_CONFLICT),),
            note="EVENT_QUARANTINED"))
    return entries


# --------------------------------------------------------------------------------------
# emit_response
# --------------------------------------------------------------------------------------
def _mark(checkpoint: Callable[[str], None] | None, name: str) -> None:
    if checkpoint is not None:
        checkpoint(name)


def _verify_complete(stores: AdapterStores, documents: Sequence[NormalizedDocument], row: dict[str, Any]) -> None:
    """A NORMALIZED acquisition is complete only if every artifact it lists is really durable and unique."""

    for document in documents:
        observations = [item for item in stores.evidence.get_observations(document.artifact_hash)
                        if item.contract_id == stores.contract_id]
        if len(observations) != 1 or observations[0].observation_id not in row["normalized_observation_ids"]:
            raise EmitConflict(AdapterFailure.EVIDENCE_CONFLICT)
        wanted = pit_record_id(stores.source_id, document.artifact_hash)
        if wanted not in row["pit_record_ids"]:
            raise EmitConflict(AdapterFailure.PIT_APPEND_CONFLICT)
        matches = [r for r in stores.pit.log.records()
                   if r.get("record_type") == "pit_record" and r.get("record_id") == wanted]
        if len(matches) != 1 or matches[0]["payload_hash"] != document.artifact_hash:
            raise EmitConflict(AdapterFailure.PIT_APPEND_CONFLICT)


def _completed_row(stores: AdapterStores, acquisition_id: str) -> dict[str, Any] | None:
    for row in reversed(stores.acquisition.rows()):
        if row["record_type"] == "acq_completed" and row["acquisition_id"] == acquisition_id:
            return row
    return None


def emit_response(parsed: ParsedResponse, ctx: ParseContext, *, stores: AdapterStores, clock: TrustedClock,
                  checkpoint: Callable[[str], None] | None = None) -> EmitResult:
    """Publish everything one parsed response produces; safe to run again after a crash (see the module doc)."""

    if ctx.derivation_version != stores.derivation_version:
        raise EmitConflict(AdapterFailure.CONFIG_DIGEST_MISMATCH, "the parse context is not this derivation")
    if parsed.failure is not None:
        raise EmitConflict(parsed.failure, "a response rejected as a whole emits nothing")
    documents = build_documents(parsed, ctx)
    t1 = iso_utc(ctx.response_received_at)
    state = stores.acquisition.attempts().get(ctx.acquisition_id)
    completed = _completed_row(stores, ctx.acquisition_id)
    if (state is None or state.state not in ("COMPLETED", "NORMALIZED") or completed is None
            or completed["outcome"] != "RESPONSE" or completed["http_status"] != HTTP_OK
            or completed["failure"] is not None or completed["T1"] is None or iso_utc(completed["T1"]) != t1
            or completed["raw_observation_id"] != ctx.raw_observation_id):
        raise EmitConflict(AdapterFailure.EVIDENCE_CONFLICT, "emission needs its own successful, completed acquisition")
    if state.state == "NORMALIZED":
        row = next(r for r in reversed(stores.acquisition.rows())
                   if r["record_type"] == "acq_normalized" and r["acquisition_id"] == ctx.acquisition_id)
        _verify_complete(stores, documents, row)
        applied = stores.identity.apply(parsed.identity_rows)
        return EmitResult(row["T2"], row["T3"], tuple(row["normalized_observation_ids"]), (),
                          tuple(row["pit_record_ids"]), tuple(row["coverage_entry_ids"]), len(applied), True)

    t2 = clock.now()
    require_not_before(t2, t1)
    _mark(checkpoint, "after_t2")
    observations: list[EvidenceObservation] = []
    structured: list[str] = []
    for index, document in enumerate(documents):
        source_uri = response_source_uri(stores.derivation_version, document.entity_id, ctx.raw_observation_id)
        observation = _publish_observation(stores, document, source_uri=source_uri, t2=t2, retrieved_at=t1)
        observations.append(observation)
        _mark(checkpoint, f"after_observation:{index}")
        if document.state == STATE_OPEN:
            body = json.loads(document.data)
            evidence = _research_evidence(document, observation, body, stores)
            try:
                structured.append(stores.structured.publish(evidence))
            except (RegistryConflict, ValueError):
                raise EmitConflict(AdapterFailure.EVIDENCE_CONFLICT) from None
            _mark(checkpoint, f"after_structured:{index}")
    t3 = clock.now()
    require_not_before(t3, t2, *(item.parse_ready_at for item in observations))
    _mark(checkpoint, "after_t3")
    pit_ids: list[str] = []
    for index, document in enumerate(documents):
        pit_ids.append(append_pit_once(stores, _pit_record(stores, document, t1=t1, t3=t3)))
        _mark(checkpoint, f"after_pit:{index}")
    coverage_ids = [append_coverage_once(stores, item)
                    for item in _coverage_entries(stores, parsed, ctx, documents, recorded_at=t3)]
    _mark(checkpoint, "after_coverage")
    stamp = clock.now()
    require_not_before(stamp, t3)
    stores.acquisition.append(
        "acq_normalized", recorded_at=stamp, acquisition_id=ctx.acquisition_id, T2=t2, T3=t3,
        derivation_version=stores.derivation_version, expected_scope_hash=ctx.expected_scope_hash,
        identity_registry_head=identity_mod.head_of(ctx.identity_prefix),
        normalized_observation_ids=[item.observation_id for item in observations], pit_record_ids=pit_ids,
        coverage_entry_ids=coverage_ids)
    _mark(checkpoint, "after_normalized_row")
    applied = stores.identity.apply(parsed.identity_rows)
    _mark(checkpoint, "after_identity")
    return EmitResult(t2, t3, tuple(item.observation_id for item in observations), tuple(structured),
                      tuple(pit_ids), tuple(coverage_ids), len(applied))


# --------------------------------------------------------------------------------------
# emit_invalidation (design 13.2)
# --------------------------------------------------------------------------------------
class InvalidationRefused(RuntimeError):
    """The target of an invalidation is not a known, current market-book observation."""


@dataclass(frozen=True)
class InvalidationResult:
    invalidation_id: str
    head_effect: str
    t_inv: str
    invalidation_observation_id: str | None
    invalidation_pit_record_id: str | None
    coverage_entry_id: str


def _scope_records(stores: AdapterStores, entity_id: str) -> list[BitemporalRecord]:
    found = []
    for row in stores.pit.log.records():
        if row.get("record_type") == "pit_record" and row.get("entity_id") == entity_id \
                and row.get("source_id") == stores.source_id:
            found.append(BitemporalRecord(**{key: row[key] for key in BitemporalRecord.__dataclass_fields__}))
    return found


def _prior_invalidation(stores: AdapterStores, *, observation_id: str, invalidation_class: str, reason: str,
                        actor: str, evidence_refs: Sequence[str]):
    """The earlier recording of this very invalidation (a crashed run), or None."""

    for entry in stores.invalidations.state().values():
        recorded = entry["recorded"]
        if (recorded["invalidated_observation_id"], recorded["invalidation_class"], recorded["reason"],
                recorded["actor"], recorded["evidence_refs"]) == (
                observation_id, invalidation_class, reason, actor, list(evidence_refs)):
            return entry
    return None


def emit_invalidation(*, invalidated_observation_id: str, invalidation_class: str, reason: str, actor: str,
                      evidence_refs: Sequence[str], stores: AdapterStores, clock: TrustedClock,
                      checkpoint: Callable[[str], None] | None = None) -> InvalidationResult:
    """Record an invalidation and, when the target is still its scope's head, emit the INVALIDATED head.

    Safe to run again after a crash: an earlier recording of the same invalidation is completed, never
    duplicated, and an already emitted INVALIDATED head is recognised by its deterministic artifact.
    """

    try:
        observation = stores.evidence.get_observation(invalidated_observation_id)
        target = json.loads(stores.evidence.get_bytes(observation.artifact_hash))
    except (OSError, ValueError, RegistryConflict):
        raise InvalidationRefused("the invalidated observation is unknown or unreadable") from None
    if observation.contract_id != stores.contract_id or target.get("derivation_kind") != "RESPONSE":
        raise InvalidationRefused("only a RESPONSE observation of this derivation can be invalidated")
    entity_id = target["entity_id"]
    record_id = pit_record_id(stores.source_id, observation.artifact_hash)
    scope = _scope_records(stores, entity_id)
    if not any(item.record_id == record_id and item.payload_hash == observation.artifact_hash for item in scope):
        raise InvalidationRefused("the invalidated observation has no PIT record")
    prior = _prior_invalidation(stores, observation_id=observation.observation_id,
                                invalidation_class=invalidation_class, reason=reason, actor=actor,
                                evidence_refs=evidence_refs)
    if prior is not None:
        row, applied = prior["recorded"], prior["applied"]
        row = {key: value for key, value in row.items() if key not in ("previous_hash", "sequence", "record_hash")}
        t_inv = row["recorded_at"]
    else:
        applied = None
        floor = max(parse_utc(item.valid_from) for item in scope)
        t_inv = clock.now()
        # never earlier than anything already durable for this scope (a reading below is a clock fault) ...
        require_not_before(t_inv, stores.invalidations.last_time(), *(item.ready_at for item in scope))
        if parse_utc(t_inv) < floor:
            raise ClockFault("CLOCK_BEHIND_DURABLE")
        while parse_utc(t_inv) <= floor:                      # ... and a tie is re-read until strictly later
            following = clock.now()
            if parse_utc(following) < parse_utc(t_inv):
                raise ClockFault("CLOCK_REGRESSED")
            t_inv = following
        row = recorded_row(
            invalidated_observation_id=observation.observation_id, invalidated_artifact_hash=observation.artifact_hash,
            invalidated_pit_record_id=record_id, entity_id=entity_id, source_id=stores.source_id,
            invalidation_class=invalidation_class, reason=reason, recorded_at=t_inv, actor=actor,
            evidence_refs=evidence_refs)
        stores.invalidations.record(row)
    _mark(checkpoint, "after_recorded")
    note = f"INVALIDATED:{reason}"
    if applied is not None:                                   # complete: report what was recorded
        entry_id = _invalidation_coverage(stores, row, applied["applied_at"], note=note)
        return InvalidationResult(row["invalidation_id"], applied["head_effect"], t_inv,
                                  applied["invalidation_observation_id"], applied["invalidation_pit_record_id"],
                                  entry_id)
    ledger_head = stores.invalidations.head_containing(row["invalidation_id"])
    data = build_invalidation_document(row, target, ledger_head=ledger_head)
    document = NormalizedDocument(entity_id, "INVALIDATED", data, t_inv, None, None)
    own_record = pit_record_id(stores.source_id, document.artifact_hash)
    emitted_before = any(item.record_id == own_record for item in scope)
    others = [item for item in scope if item.record_id != own_record]
    latest = max(parse_utc(item.valid_from) for item in others)
    still_head = any(item.record_id == record_id for item in others if parse_utc(item.valid_from) == latest)
    if not still_head and not emitted_before:
        applied_at = clock.now()
        stores.invalidations.apply(applied_row(
            invalidation_id=row["invalidation_id"], head_effect=EFFECT_SUPERSEDED, invalidation_observation_id=None,
            invalidation_pit_record_id=None, applied_at=applied_at))
        entry_id = _invalidation_coverage(stores, row, applied_at, note=note)
        return InvalidationResult(row["invalidation_id"], EFFECT_SUPERSEDED, t_inv, None, None, entry_id)
    t2_inv = clock.now()
    source_uri = invalidation_source_uri(stores.derivation_version, entity_id, row["invalidation_id"])
    published = _publish_observation(stores, document, source_uri=source_uri, t2=t2_inv, retrieved_at=t_inv)
    _mark(checkpoint, "after_invalidation_observation")
    t3_inv = clock.now()
    require_not_before(t3_inv, published.parse_ready_at)
    pit_id = append_pit_once(stores, _pit_record(stores, document, t1=t_inv, t3=t3_inv))
    _mark(checkpoint, "after_invalidation_pit")
    applied_at = clock.now()
    stores.invalidations.apply(applied_row(
        invalidation_id=row["invalidation_id"], head_effect=EFFECT_EMITTED,
        invalidation_observation_id=published.observation_id, invalidation_pit_record_id=pit_id,
        applied_at=applied_at))
    entry_id = _invalidation_coverage(stores, row, applied_at, note=note)
    return InvalidationResult(row["invalidation_id"], EFFECT_EMITTED, t_inv, published.observation_id, pit_id,
                              entry_id)


def _invalidation_coverage(stores: AdapterStores, row: dict[str, Any], at: str, *, note: str) -> str:
    """QUARANTINED coverage: CONTRADICTORY_EVIDENCE, or ARTIFACT_TAMPERED for a derivation defect (design 13.2)."""

    failure = (AdapterFailure.DERIVATION_UNVERIFIED if row["invalidation_class"] == "DERIVATION_DEFECT"
               else AdapterFailure.INVALIDATED)
    return append_coverage_once(stores, CoverageEntry(
        entry_id=gid("cov", invalidation_id=row["invalidation_id"], entity_id=row["entity_id"], note=note),
        entity_id=row["entity_id"], source_contract_id=stores.contract_id, status=CoverageStatus.QUARANTINED,
        recorded_at=at, reason_codes=(reason_code(failure),), note=note))


def invalidate_if_underivable(observation_id: str, *, check: Callable[[str], None], stores: AdapterStores,
                              clock: TrustedClock, evidence_refs: Sequence[str] = ()) -> InvalidationResult | None:
    """Run ``check`` (the derivation verifier) and, if it fails for any reason, invalidate the observation
    automatically (design 13.2: a fail-safe reduction of usability that needs no gate record)."""

    try:
        check(observation_id)
    except Exception:                                         # any failure to re-derive invalidates; never passes
        return emit_invalidation(
            invalidated_observation_id=observation_id, invalidation_class="DERIVATION_DEFECT",
            reason=AdapterFailure.DERIVATION_UNVERIFIED.value, actor="ADAPTER_AUTOMATIC",
            evidence_refs=tuple(evidence_refs) or (f"verify_derivation:{observation_id}",), stores=stores,
            clock=clock)
    return None
