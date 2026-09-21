"""Hard separation between decision-time inputs and future outcome labels."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .provenance import ProvenanceRef
from .repro import canonical_json, immutable_write, sha256_bytes
from .time import assert_pit_available, iso_utc, parse_utc


FUTURE_FIELD_NAMES = frozenset(
    {
        "outcome",
        "result",
        "label",
        "final_score",
        "settled_at",
        "settlement",
        "profit",
        "payout",
        "closing_price",
        "final_bsp",
        "bsp",
        "post_event",
    }
)


def _assert_no_future_keys(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in FUTURE_FIELD_NAMES or any(
                token in normalized for token in ("outcome", "settlement", "final_score")
            ):
                raise ValueError(f"future label field is not a decision input: {path}.{key}")
            _assert_no_future_keys(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_no_future_keys(child, f"{path}[{index}]")


@dataclass(frozen=True)
class DecisionFact:
    key: str
    value: Any
    available_at: str
    ready_at: str
    source_ref: ProvenanceRef

    def __post_init__(self) -> None:
        if self.key.lower() in FUTURE_FIELD_NAMES:
            raise ValueError(f"future label field is not a decision fact: {self.key}")
        available = parse_utc(self.available_at)
        ready = parse_utc(self.ready_at)
        if ready < available:
            raise ValueError("fact ready_at cannot precede available_at")


@dataclass(frozen=True)
class DecisionFrame:
    decision_id: str
    entity_id: str
    decision_at: str
    facts: tuple[DecisionFact, ...]
    dataset_version: str
    config_digest: str

    def __post_init__(self) -> None:
        decision = parse_utc(self.decision_at)
        keys = [fact.key for fact in self.facts]
        if len(keys) != len(set(keys)):
            raise ValueError("decision facts must have unique keys")
        for fact in self.facts:
            assert_pit_available(
                decision_at=decision,
                available_at=fact.available_at,
                ready_at=fact.ready_at,
            )
            _assert_no_future_keys(fact.value, f"facts.{fact.key}")

    def values(self) -> dict[str, Any]:
        return {fact.key: fact.value for fact in self.facts}

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "entity_id": self.entity_id,
            "decision_at": iso_utc(self.decision_at),
            "facts": [asdict(fact) for fact in self.facts],
            "dataset_version": self.dataset_version,
            "config_digest": self.config_digest,
        }


@dataclass(frozen=True)
class FutureOutcomeLabel:
    label_id: str
    entity_id: str
    outcome_value: Any
    observed_at: str
    source_ref: ProvenanceRef
    label_schema_version: str

    def __post_init__(self) -> None:
        parse_utc(self.observed_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DecisionInputStore:
    """Append-only decision frames; labels cannot be stored through this API."""

    def __init__(self, path: str):
        self.path = path

    def append(self, frame: DecisionFrame) -> str:
        payload = canonical_json(frame.to_dict())
        digest = sha256_bytes(payload)
        immutable_write(f"{self.path}.{digest}.json", payload)
        return digest


class FutureLabelStore:
    """Separate append-only storage for labels, never imported by decision code."""

    def __init__(self, path: str):
        self.path = path

    def append(self, label: FutureOutcomeLabel) -> str:
        payload = canonical_json(label.to_dict())
        digest = sha256_bytes(payload)
        immutable_write(f"{self.path}.{digest}.json", payload)
        return digest


def assert_decision_frames_do_not_contain_labels(frames: Iterable[DecisionFrame]) -> None:
    for frame in frames:
        _assert_no_future_keys(frame.to_dict())
