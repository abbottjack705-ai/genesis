from __future__ import annotations

import json
import unittest
from pathlib import Path

from genesis.evaluation import EvaluationRequest, ProtectedEvaluationService
from genesis.labels import DecisionFact, DecisionFrame, FutureOutcomeLabel
from genesis.logging import JsonlAuditLogger, LogEvent
from genesis.provenance import AvailabilityClass, ProvenanceRef
from ._support import scratch_directory


def ref() -> ProvenanceRef:
    return ProvenanceRef("b" * 64, "synthetic-v1", "synthetic://fixture", "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", AvailabilityClass.PROSPECTIVE_CAPTURED, "test-v1")


class ProtectedEvaluationAndLoggingTests(unittest.TestCase):
    def test_protected_evaluation_returns_certificate_without_labels(self):
        frames = [
            DecisionFrame("d1", "e1", "2026-01-01T00:00:00Z", (DecisionFact("signal", 1, "2025-12-31T23:00:00Z", "2025-12-31T23:01:00Z", ref()),), "d1", "c" * 64),
            DecisionFrame("d2", "e2", "2026-01-01T00:00:00Z", (DecisionFact("signal", 0, "2025-12-31T23:00:00Z", "2025-12-31T23:01:00Z", ref()),), "d1", "c" * 64),
        ]
        labels = [FutureOutcomeLabel("l1", "e1", 1, "2026-01-01T01:00:00Z", ref(), "label-v1"), FutureOutcomeLabel("l2", "e2", 0, "2026-01-01T01:00:00Z", ref(), "label-v1")]
        service = ProtectedEvaluationService(frames, labels)
        seen = []

        def strategy(frame):
            values = frame.values()
            self.assertNotIn("outcome", values)
            seen.append(values["signal"])
            return "0.9" if values["signal"] else "0.1"

        certificate = service.run(EvaluationRequest("campaign", "s1", "a" * 64, "d1", "r" * 64), strategy)
        self.assertEqual(seen, [1, 0])
        self.assertEqual(certificate.metrics["brier"], "0.01")
        self.assertFalse(certificate.raw_labels_exposed)

    def test_structured_log_redacts_secrets(self):
        with scratch_directory() as tmp:
            path = tmp / "events.jsonl"
            JsonlAuditLogger(path).emit(LogEvent("test", "2026-01-01T00:00:00Z", "test", "offline_research", fields={"api_key": "secret", "ok": 1}))
            row = json.loads(path.read_text())
            self.assertEqual(row["fields"]["api_key"], "[REDACTED]")
            self.assertEqual(row["fields"]["ok"], 1)
