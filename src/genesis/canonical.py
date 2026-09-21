"""Canonical sport, event, market, participant, and candidate schemas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .provenance import ProvenanceRef
from .repro import canonical_json, sha256_bytes
from .time import iso_utc, parse_utc


def stable_id(prefix: str, *parts: str) -> str:
    value = "|".join((prefix, *parts)).encode("utf-8")
    return f"{prefix}_{sha256_bytes(value)[:24]}"


class MarketSide(StrEnum):
    BACK = "back"
    LAY = "lay"


class EvidenceStatus(StrEnum):
    CONFIRMED = "confirmed"
    EXPECTED = "expected"
    UNCERTAIN = "uncertain"
    CONTRADICTED = "contradicted"


@dataclass(frozen=True)
class Participant:
    participant_id: str
    sport: str
    canonical_name: str
    source_refs: tuple[ProvenanceRef, ...] = ()
    identity_confidence: str = "unverified"
    valid_from: str | None = None
    valid_to: str | None = None

    def __post_init__(self) -> None:
        if not self.participant_id or not self.sport or not self.canonical_name:
            raise ValueError("participant identity fields are required")
        if self.valid_from:
            parse_utc(self.valid_from)
        if self.valid_to:
            parse_utc(self.valid_to)


@dataclass(frozen=True)
class Event:
    event_id: str
    sport: str
    scheduled_start: str
    participant_ids: tuple[str, ...]
    source_refs: tuple[ProvenanceRef, ...] = ()
    venue: str | None = None
    event_version: str = "event-v1"
    meeting_id: str | None = None
    competition_id: str | None = None

    def __post_init__(self) -> None:
        parse_utc(self.scheduled_start)
        if len(self.participant_ids) < 2 or len(set(self.participant_ids)) != len(self.participant_ids):
            raise ValueError("event must contain distinct participants")


@dataclass(frozen=True)
class MarketSnapshot:
    snapshot_id: str
    event_id: str
    market_id: str
    selection_id: str
    market_type: str
    observed_at: str
    received_at: str
    parse_ready_at: str
    side: MarketSide
    odds_decimal: str
    available_size: str | None
    status: str
    source_refs: tuple[ProvenanceRef, ...] = ()
    source_sequence: str | None = None
    published_at: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        for value in (self.observed_at, self.received_at, self.parse_ready_at, self.published_at, self.valid_from, self.valid_to):
            if value is not None:
                parse_utc(value)
        from decimal import Decimal

        odds = Decimal(self.odds_decimal)
        if odds <= 1:
            raise ValueError("decimal odds must be greater than 1")
        if self.available_size is not None and Decimal(self.available_size) < 0:
            raise ValueError("available size cannot be negative")


@dataclass(frozen=True)
class ResearchEvidence:
    evidence_id: str
    event_id: str
    category: str
    normalized_claim: str
    source_ref: ProvenanceRef
    source_timestamp: str | None
    retrieved_at: str
    status: EvidenceStatus
    freshness_expires_at: str | None
    extractor_version: str | None = None
    contradiction_ids: tuple[str, ...] = ()
    ready_at: str | None = None
    evidence_span: str | None = None
    prompt_schema_hash: str | None = None

    def __post_init__(self) -> None:
        retrieved = parse_utc(self.retrieved_at)
        if self.source_timestamp:
            parse_utc(self.source_timestamp)
        if self.freshness_expires_at:
            parse_utc(self.freshness_expires_at)
        if self.ready_at:
            if parse_utc(self.ready_at) < retrieved:
                raise ValueError("research evidence ready_at cannot precede retrieved_at")
        if self.prompt_schema_hash and len(self.prompt_schema_hash) != 64:
            raise ValueError("prompt_schema_hash must be a SHA-256 digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "event_id": self.event_id,
            "category": self.category,
            "normalized_claim": self.normalized_claim,
            "source_ref": self.source_ref.to_dict(),
            "source_timestamp": iso_utc(self.source_timestamp) if self.source_timestamp else None,
            "retrieved_at": iso_utc(self.retrieved_at),
            "status": self.status.value,
            "freshness_expires_at": (
                iso_utc(self.freshness_expires_at) if self.freshness_expires_at else None
            ),
            "extractor_version": self.extractor_version,
            "contradiction_ids": list(self.contradiction_ids),
            "ready_at": iso_utc(self.ready_at) if self.ready_at else None,
            "evidence_span": self.evidence_span,
            "prompt_schema_hash": self.prompt_schema_hash,
        }

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json(self.to_dict()))

    @property
    def is_authoritative_v2(self) -> bool:
        return self.source_ref.is_authoritative_v2


@dataclass(frozen=True)
class CandidateBet:
    candidate_id: str
    strategy_id: str
    strategy_version: str
    sport: str
    event_id: str
    market_id: str
    selection_id: str
    side: MarketSide
    requested_odds_min: str
    requested_odds_max: str
    observed_odds: str
    model_probability: str
    conservative_probability: str
    model_version: str
    evidence_pack_id: str
    decision_at: str
    expires_at: str
    evidence_complete: bool
    critical_uncertainty_flags: tuple[str, ...] = ()
    contradiction_state: str = "none"
    qualification_reasons: tuple[str, ...] = ()
    rejection_reasons: tuple[str, ...] = ()
    candidate_version: str = "candidate-v1"
    evidence_cutoff_ts: str | None = None
    execution_check_ts: str | None = None
    market_family: str | None = None
    meeting_id: str | None = None
    competition_id: str | None = None
    participant_ids: tuple[str, ...] = ()
    shared_evidence_ids: tuple[str, ...] = ()
    selection_dependency_group: str | None = None
    correlation_cluster_ids: tuple[str, ...] = ()
    model_support_status: str = "unknown"
    calibration_status: str = "unknown"
    uncertainty_status: str = "unknown"
    evidence_completeness_status: str = "unknown"
    critical_evidence_status: str = "unknown"
    contradiction_status: str = "unknown"
    price_sanity_status: str = "unknown"
    odds_profile_status: str = "unknown"
    execution_status: str = "unknown"
    risk_status: str = "unknown"
    correlation_status: str = "unknown"
    strategy_tier: str | None = None
    model_artifact_hash: str | None = None
    calibration_artifact_hash: str | None = None
    feature_manifest_hash: str | None = None
    gate_policy_hash: str | None = None
    config_digest: str | None = None
    candidate_decision_hash: str | None = None

    def __post_init__(self) -> None:
        from decimal import Decimal

        parse_utc(self.decision_at)
        parse_utc(self.expires_at)
        for value in (self.evidence_cutoff_ts, self.execution_check_ts):
            if value is not None:
                parse_utc(value)
        for value in (
            self.requested_odds_min,
            self.requested_odds_max,
            self.observed_odds,
        ):
            if Decimal(value) <= 1:
                raise ValueError("candidate odds must be greater than 1")
        if Decimal(self.requested_odds_min) > Decimal(self.requested_odds_max):
            raise ValueError("candidate odds range is inverted")
        for value in (self.model_probability, self.conservative_probability):
            probability = Decimal(value)
            if not 0 <= probability <= 1:
                raise ValueError("probabilities must be in [0, 1]")
        for name in (
            "model_artifact_hash",
            "calibration_artifact_hash",
            "feature_manifest_hash",
            "gate_policy_hash",
            "config_digest",
            "candidate_decision_hash",
        ):
            value = getattr(self, name)
            if value is not None and len(value) != 64:
                raise ValueError(f"{name} must be a SHA-256 digest")


def as_record(value: Any) -> dict[str, Any]:
    """Serialize dataclasses without making IDs or timestamps implicit."""

    result = asdict(value)
    return _enum_values(result)


def _enum_values(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _enum_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_enum_values(item) for item in value]
    return value
