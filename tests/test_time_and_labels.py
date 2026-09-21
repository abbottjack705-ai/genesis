from __future__ import annotations

import unittest

from genesis.labels import DecisionFact, DecisionFrame, FutureOutcomeLabel
from genesis.provenance import AvailabilityClass, ProvenanceRef, SourceContract
from genesis.time import AvailabilityWindow
from genesis.time import TimestampError


def ref() -> ProvenanceRef:
    return ProvenanceRef(
        artifact_hash="a" * 64,
        contract_id="synthetic-v1",
        source_uri="synthetic://fixture",
        retrieved_at="2026-01-01T00:00:00Z",
        parse_ready_at="2026-01-01T00:00:01Z",
        availability_class=AvailabilityClass.PROSPECTIVE_CAPTURED,
        parser_version="test-v1",
    )


class TimeAndLabelTests(unittest.TestCase):
    def test_future_ready_time_is_rejected(self):
        with self.assertRaises(TimestampError):
            DecisionFrame(
                "d1", "e1", "2026-01-01T00:00:00Z",
                (DecisionFact("weather", "dry", "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", ref()),),
                "dataset-v1", "c" * 64,
            )

    def test_future_label_fields_cannot_enter_decision_frame(self):
        with self.assertRaises(ValueError):
            DecisionFrame(
                "d2", "e1", "2026-01-01T00:00:00Z",
                (DecisionFact("research", {"outcome": "home_win"}, "2025-12-31T23:00:00Z", "2025-12-31T23:01:00Z", ref()),),
                "dataset-v1", "c" * 64,
            )

    def test_future_label_is_a_distinct_record_type(self):
        label = FutureOutcomeLabel("l1", "e1", 1, "2026-01-01T02:00:00Z", ref(), "label-v1")
        self.assertEqual(label.outcome_value, 1)

    def test_source_contract_requires_ready_by_decision(self):
        contract = SourceContract(
            "source-v1", "synthetic", "fixture", "synthetic://*",
            AvailabilityClass.PROSPECTIVE_CAPTURED, "seconds", "ready_at<=decision_at",
            "parser-v1", "synthetic", supports_prospective_capture=True,
        )
        contract.check_window(
            AvailabilityWindow("2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z"),
            "2026-01-01T00:00:02Z",
        )
        with self.assertRaises(ValueError):
            contract.check_window(
                AvailabilityWindow("2026-01-01T00:00:00Z", "2026-01-01T00:00:03Z"),
                "2026-01-01T00:00:02Z",
            )
