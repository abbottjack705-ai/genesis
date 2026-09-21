from __future__ import annotations

import json
import unittest
from pathlib import Path

from genesis.evidence import EvidenceStore
from genesis.provenance import AvailabilityClass
from genesis.repro import ImmutableConflict
from ._support import scratch_directory


class EvidenceTests(unittest.TestCase):
    def test_content_addressed_publish_is_idempotent_and_manifest_is_verifiable(self):
        with scratch_directory() as tmp:
            store = EvidenceStore(tmp / "evidence")
            kwargs = dict(
                source_uri="synthetic://source/1",
                provider="test",
                source_type="fixture",
                retrieved_at="2026-01-01T00:00:00Z",
                parse_ready_at="2026-01-01T00:00:01Z",
                parser_version="test-v1",
                content_type="application/json",
                licensing_note="synthetic",
                availability_class=AvailabilityClass.PROSPECTIVE_CAPTURED,
            )
            first = store.publish(b'{"a":1}', **kwargs)
            second = store.publish(b'{"a":1}', **kwargs)
            self.assertEqual(first.artifact_hash, second.artifact_hash)
            self.assertEqual(store.get_bytes(first.artifact_hash), b'{"a":1}')
            self.assertEqual(store.verify_manifest(), 2)

            with self.assertRaises(ImmutableConflict):
                store.publish(b'{"a":1}', **(kwargs | {"parser_version": "different"}))

    def test_manifest_tampering_is_detected(self):
        with scratch_directory() as tmp:
            store = EvidenceStore(tmp / "evidence")
            store.publish(
                b"payload",
                source_uri="synthetic://source/2",
                provider="test",
                source_type="fixture",
                retrieved_at="2026-01-01T00:00:00Z",
                parse_ready_at="2026-01-01T00:00:01Z",
                parser_version="test-v1",
                content_type="text/plain",
                licensing_note="synthetic",
                availability_class=AvailabilityClass.HISTORICAL_RECONSTRUCTED,
            )
            path = tmp / "evidence" / "manifests" / "evidence.jsonl"
            row = json.loads(path.read_text())
            row["source_uri"] = "synthetic://tampered"
            path.write_text(json.dumps(row) + "\n")
            with self.assertRaises(ValueError):
                store.verify_manifest()
