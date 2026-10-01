"""The as-of consumer of market-book evidence (design 12.3), fail-closed and verifier-parity exact.

``admissible_head`` is the ONE predicate shared by the reader, the manifest builder and the tests. It
accepts exactly what the frozen ``FeatureInputManifestStore.verify_for_pack`` would accept for the same
head at cutoff ``D``, and adds adapter-only refusals on top, never removing a verifier refusal.

The head is chosen HERE and never taken from the order of the frozen ``as_of_query`` result: that call
returns every admissible record sorted by ``record_id`` (its only ordering guarantee is that it raises
when the two latest ``valid_from`` values tie), so ``result[0]`` is an arbitrary record, not the head.
The head is the single admissible record with the greatest ``valid_from``; a tie is ``AMBIGUOUS``; and
an older record is NEVER used as a fallback, whatever happens to the newer ones.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from fnmatch import fnmatchcase
from typing import Any, Callable

from genesis.evidence import EvidenceObservation
from genesis.pit import BitemporalRecord, PITViolation, SourceCapability, SourceUnavailable
from genesis.provenance import AvailabilityClass, SourceContract
from genesis.registry import RegistryConflict
from genesis.time import AvailabilityWindow, TimestampError, iso_utc, parse_utc

from genesis_adapters import config as adapter_config
from genesis_adapters.errors import PASS_REASON_MAP, AdapterFailure
from genesis_adapters.oddspapi import quiescence
from genesis_adapters.oddspapi.emit import AdapterStores

SOURCE_PREFIX = "oddspapi.v4.soccer.market_book."
PROVIDER = "oddspapi"
_STATE_CODES = {"SUSPENDED": AdapterFailure.SUSPENDED, "ABSENT": AdapterFailure.ABSENT,
                "BLOCKED": AdapterFailure.BLOCKED, "INVALIDATED": AdapterFailure.INVALIDATED}


@dataclass(frozen=True)
class UsableBook:
    entity_id: str
    decision_at: str
    record: BitemporalRecord
    observation: EvidenceObservation
    document: dict[str, Any]
    source_id: str
    contract_id: str
    capability: SourceCapability


@dataclass(frozen=True)
class Unusable:
    code: AdapterFailure
    reasons: tuple[str, ...] = ()
    detail: str = ""

    @property
    def pass_reason(self):
        """What a decision-time consumer records for this result (frozen ReasonCode), if it maps."""

        return PASS_REASON_MAP.get(self.code)


def known_sources(stores: AdapterStores) -> tuple[str, ...]:
    """Every market-book source that ever had a capability row, in a stable order."""

    found = {row["source_id"] for row in stores.capabilities.log.records()
             if row.get("record_type") == "source_capability_registered"
             and str(row.get("source_id", "")).startswith(SOURCE_PREFIX)}
    return tuple(sorted(found))


def _contract_mismatches(contract: SourceContract, observation: EvidenceObservation) -> list[str]:
    """The frozen ``EvidenceStore._validate_contract`` rules, restated over public fields only."""

    mismatches = [name for name, actual, expected in (
        ("provider", observation.provider, contract.provider),
        ("source_type", observation.source_type, contract.source_type),
        ("parser_version", observation.parser_version, contract.parser_version),
        ("licensing_note", observation.licensing_note, contract.licensing_note),
        ("availability_class", observation.availability_class, contract.availability_class)) if actual != expected]
    if not fnmatchcase(observation.source_uri, contract.uri_pattern):
        mismatches.append("source_uri")
    klass = observation.availability_class
    if klass == AvailabilityClass.PROSPECTIVE_CAPTURED and not contract.supports_prospective_capture:
        mismatches.append("supports_prospective_capture")
    if klass == AvailabilityClass.HISTORICAL_RECONSTRUCTED and not contract.supports_historical_reconstruction:
        mismatches.append("supports_historical_reconstruction")
    if klass in (AvailabilityClass.FUTURE_LABEL, AvailabilityClass.UNKNOWN):
        mismatches.append("decision_usable_availability")
    return mismatches


def _ready_source(stores: AdapterStores, decision_at: str) -> str | Unusable:
    ready = []
    for source_id in known_sources(stores):
        try:
            stores.capabilities.require_ready_at(source_id, decision_at)
        except SourceUnavailable:
            continue
        ready.append(source_id)
    if not ready:
        return Unusable(AdapterFailure.DATA_CAPABILITY_NOT_READY)
    if len(ready) > 1:
        return Unusable(AdapterFailure.AMBIGUOUS_SOURCE, detail="more than one READY market-book source")
    source_id = ready[0]
    point = parse_utc(decision_at)
    applicable = [row for row in stores.capabilities.log.records()
                  if row.get("record_type") == "source_capability_registered"
                  and row.get("source_id") == source_id and parse_utc(row["recorded_at"]) <= point]
    latest = max(parse_utc(row["recorded_at"]) for row in applicable)
    if sum(1 for row in applicable if parse_utc(row["recorded_at"]) == latest) != 1:
        return Unusable(AdapterFailure.AMBIGUOUS_SOURCE, detail="the capability head is not unique")
    return source_id


def admissible_head(entity_id: str, decision_at: str, *, stores: AdapterStores,
                    derivation_check: Callable[[str], None] | None) -> UsableBook | Unusable:
    """The usable head of ``entity_id`` at ``decision_at``, or the exact reason it is not usable.

    ``derivation_check`` is mandatory (design 12.3 step 7, hostile audit HA-12): every head is re-derived before it
    is returned, and without a verifier nothing is usable. The adapter run lock is held while reading (design 6.3):
    nothing is read while an adapter phase of another process holds it, nor while durable adapter work is
    unfinished (``quiescence.pending_work``)."""

    if derivation_check is None:
        return Unusable(AdapterFailure.DERIVATION_UNVERIFIED, detail="no derivation verifier was supplied")
    try:
        with quiescence.run_lock(stores.root):
            unfinished = quiescence.pending_work(stores)
            if unfinished:
                return Unusable(AdapterFailure.DATA_CAPABILITY_NOT_READY,
                                detail="adapter work is unfinished: " + unfinished[0])
            return _admissible_head(entity_id, decision_at, stores=stores, derivation_check=derivation_check)
    except quiescence.QuiescenceBusy as busy:
        return Unusable(AdapterFailure.DATA_CAPABILITY_NOT_READY, detail=str(busy))


def _admissible_head(entity_id: str, decision_at: str, *, stores: AdapterStores,
                     derivation_check: Callable[[str], None]) -> UsableBook | Unusable:
    try:
        cutoff = iso_utc(decision_at)
    except TimestampError:
        return Unusable(AdapterFailure.PARITY_FAILURE, detail="the decision time is not a canonical UTC time")
    point = parse_utc(cutoff)
    source = _ready_source(stores, cutoff)
    if isinstance(source, Unusable):
        return source
    version = source[len(SOURCE_PREFIX):]
    contract_id = adapter_config.normalized_contract_id(version)
    try:
        contract = stores.contracts.get(contract_id)
        stores.bindings.require(source_id=source, source_contract_id=contract_id, provider=contract.provider)
    except (RegistryConflict, ValueError):
        return Unusable(AdapterFailure.PARITY_FAILURE, detail="no exact approved binding for the READY source")
    try:
        capability = stores.capabilities.require_ready_at(source, cutoff)
    except SourceUnavailable:
        return Unusable(AdapterFailure.DATA_CAPABILITY_NOT_READY)
    if capability.provider != contract.provider:
        return Unusable(AdapterFailure.PARITY_FAILURE, detail="capability and contract providers differ")

    try:
        admissible = stores.pit.as_of_query(entity_id, cutoff, source_id=source)
    except PITViolation:
        return Unusable(AdapterFailure.AMBIGUOUS, detail="two admissible records share the latest valid_from")
    except SourceUnavailable:
        return Unusable(AdapterFailure.DATA_CAPABILITY_NOT_READY)
    if not admissible:
        return Unusable(AdapterFailure.MISSING_OR_STALE)
    latest = max(parse_utc(item.valid_from) for item in admissible)
    heads = [item for item in admissible if parse_utc(item.valid_from) == latest]
    if len(heads) != 1:                                   # the frozen call raises first; never rely on that
        return Unusable(AdapterFailure.AMBIGUOUS, detail="two admissible records share the latest valid_from")
    head = heads[0]

    # -- parity with the frozen verifier's exact checks on the head's normalized observation
    observations = [item for item in stores.evidence.get_observations(head.payload_hash)
                    if item.contract_id == contract_id]
    if len(observations) != 1:
        return Unusable(AdapterFailure.PARITY_FAILURE, detail="the head has no unique observation under the contract")
    observation = observations[0]
    if observation.publisher_timestamp is not None and parse_utc(observation.publisher_timestamp) > point:
        return Unusable(AdapterFailure.NOT_PUBLISHED_AT_CUTOFF)           # and NO fallback to an older record
    problems = _contract_mismatches(contract, observation)
    if (observation.provider != contract.provider or observation.artifact_hash != head.payload_hash
            or parse_utc(observation.retrieved_at) > point or parse_utc(observation.parse_ready_at) > point
            or (observation.valid_from is not None and parse_utc(observation.valid_from) > point)
            or (observation.valid_to is not None and point >= parse_utc(observation.valid_to))):
        problems.append("observation")
    try:
        contract.check_window(AvailabilityWindow(parse_utc(observation.retrieved_at),
                                                 parse_utc(observation.parse_ready_at)), cutoff)
    except (ValueError, TimestampError):
        problems.append("window")
    if problems:
        return Unusable(AdapterFailure.PARITY_FAILURE, detail=",".join(sorted(set(problems))))

    # -- adapter-only refusals (stricter than the verifier, never looser)
    if _newer_capture_exists(stores, entity_id, source, head, point):
        return Unusable(AdapterFailure.STALE, detail="a newer capture exists at the cutoff and has expired")
    document = json.loads(stores.evidence.get_bytes(head.payload_hash))
    state = document.get("market_state")
    if state != "OPEN":
        code = _STATE_CODES.get(state, AdapterFailure.PARITY_FAILURE)
        return Unusable(code, tuple(document.get("state_reasons", ())))
    start = document.get("scheduled_start_as_known")
    if start is None or point >= parse_utc(start) - timedelta(seconds=stores.policy.prematch_guard_seconds):
        return Unusable(AdapterFailure.PREMATCH_WINDOW_CLOSED)
    try:
        derivation_check(observation.observation_id)
    except Exception:                                      # any failure to re-derive is a refusal, never a pass
        return Unusable(AdapterFailure.DERIVATION_UNVERIFIED)
    return UsableBook(entity_id, cutoff, head, observation, document, source, contract_id, capability)


def _newer_capture_exists(stores: AdapterStores, entity_id: str, source: str, head: BitemporalRecord, point) -> bool:
    """A record newer than ``head`` that already existed at the cutoff but is no longer admissible.

    That can only be an expired newer OPEN price. Falling back beneath it would present an older price
    as current after newer information (possibly a kickoff moved earlier) said otherwise.
    """

    for row in stores.pit.log.records():
        if row.get("record_type") != "pit_record" or row.get("entity_id") != entity_id \
                or row.get("source_id") != source:
            continue
        other = BitemporalRecord(**{key: row[key] for key in BitemporalRecord.__dataclass_fields__})
        if parse_utc(other.valid_from) > parse_utc(head.valid_from) and parse_utc(other.available_at) <= point \
                and parse_utc(other.retrieved_at) <= point and parse_utc(other.ready_at) <= point \
                and not other.admissible_at(iso_utc(point)):
            return True
    return False


class MarketBookReader:
    """The as-of consumer: ``head`` is exactly :func:`admissible_head` (the derivation verifier is mandatory)."""

    def __init__(self, stores: AdapterStores, *, derivation_check: Callable[[str], None] | None):
        self.stores = stores
        self.derivation_check = derivation_check

    def head(self, entity_id: str, decision_at: str) -> UsableBook | Unusable:
        return admissible_head(entity_id, decision_at, stores=self.stores, derivation_check=self.derivation_check)
