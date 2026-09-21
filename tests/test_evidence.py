from __future__ import annotations

import json
import unittest

from genesis.evidence import EvidenceStore
from genesis.provenance import (
    AvailabilityClass,
    SourceContract,
    SourceContractRegistry,
)
from ._support import scratch_directory


def store_with_contract(tmp, availability=AvailabilityClass.PROSPECTIVE_CAPTURED):
    contracts = SourceContractRegistry(tmp / "contracts.jsonl")
    contracts.register(
        SourceContract(
            "synthetic-v1", "test", "fixture", "synthetic://*", availability,
            "seconds", "parse_ready_at", "test-v1", "synthetic",
            supports_historical_reconstruction=(
                availability == AvailabilityClass.HISTORICAL_RECONSTRUCTED
            ),
            supports_prospective_capture=(
                availability == AvailabilityClass.PROSPECTIVE_CAPTURED
            ),
        )
    )
    return EvidenceStore(tmp / "evidence", contracts=contracts)


class EvidenceTests(unittest.TestCase):
    def test_content_addressed_publish_is_idempotent_and_manifest_is_verifiable(self):
        with scratch_directory() as tmp:
            store = store_with_contract(tmp)
            kwargs = dict(
                contract_id="synthetic-v1",
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
            self.assertEqual(first.observation_id, second.observation_id)
            self.assertEqual(store.get_bytes(first.artifact_hash), b'{"a":1}')
            self.assertEqual(store.verify_manifest(), 1)

            later = store.publish(
                b'{"a":1}',
                **(kwargs | {
                    "retrieved_at": "2026-01-01T00:01:00Z",
                    "parse_ready_at": "2026-01-01T00:01:01Z",
                    "content_type": "text/plain",
                }),
            )
            self.assertNotEqual(first.observation_id, later.observation_id)
            self.assertEqual(len(store.get_observations(first.artifact_hash)), 2)
            self.assertEqual(store.verify_manifest(), 2)

    def test_manifest_tampering_is_detected(self):
        with scratch_directory() as tmp:
            store = store_with_contract(
                tmp, AvailabilityClass.HISTORICAL_RECONSTRUCTED
            )
            store.publish(
                b"payload",
                contract_id="synthetic-v1",
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
