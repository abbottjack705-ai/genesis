"""Adversarial module which must never be executable in the research worker."""

from genesis.labels import DecisionFrame, FutureOutcomeLabel
from genesis.provenance import AvailabilityClass, ProvenanceRef


RAW_LABEL = FutureOutcomeLabel(
    "forbidden-label",
    "entity-0",
    "TOP-SECRET-MODULE-LABEL",
    "2026-01-01T01:00:00Z",
    ProvenanceRef(
        "a" * 64,
        "synthetic-v1",
        "synthetic://forbidden-label",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:01Z",
        AvailabilityClass.FUTURE_LABEL,
        "test-v1",
    ),
    "label-v1",
)


def label_bearing_program(_frame: DecisionFrame) -> str:
    return "0.9" if RAW_LABEL.outcome_value else "0.1"
