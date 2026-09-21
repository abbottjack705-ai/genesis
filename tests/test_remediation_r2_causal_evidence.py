from __future__ import annotations

import json
import unittest
from dataclasses import replace

from genesis.canonical import EvidenceStatus, ResearchEvidence
from genesis.decision import candidate_decision_hash
from genesis.evidence import EvidenceStore, StructuredEvidenceStore
from genesis.evidence_pack import EvidencePack, EvidencePackStore
from genesis.pit import (
    BitemporalRecord,
    OperationalStatus,
    PITStore,
    SourceCapability,
    SourceCapabilityRegistry,
    SourceUnavailable,
)
from genesis.provenance import (
    AvailabilityClass,
    ProvenanceRef,
    SourceContract,
    SourceContractRegistry,
)
from genesis.repro import canonical_json, sha256_bytes
from ._support import scratch_directory


def digest(character: str) -> str:
    return character * 64


def capability(
    *,
    status: OperationalStatus,
    recorded_at: str,
    version: str,
    source_id: str = "source-1",
) -> SourceCapability:
    return SourceCapability(
        source_id,
        "synthetic",
        "fixture",
        "free",
        "test",
        "prospective",
        "verified",
        "append-only",
        "fixture",
        "7/day",
        "schema-v1",
        status,
        recorded_at,
        version,
    )


def register_contracts(path) -> SourceContractRegistry:
    registry = SourceContractRegistry(path)
    registry.register(
        SourceContract(
            "prospective-parser-v1",
            "synthetic",
            "fixture",
            "synthetic://*",
            AvailabilityClass.PROSPECTIVE_CAPTURED,
            "seconds",
            "parse_ready_at",
            "parser-v1",
            "synthetic",
            supports_prospective_capture=True,
        )
    )
    registry.register(
        SourceContract(
            "prospective-parser-v2",
            "synthetic",
            "fixture",
            "synthetic://*",
            AvailabilityClass.PROSPECTIVE_CAPTURED,
            "seconds",
            "parse_ready_at",
            "parser-v2",
            "synthetic",
            supports_prospective_capture=True,
        )
    )
    registry.register(
        SourceContract(
            "historical-v1",
            "synthetic",
            "fixture",
            "synthetic://*",
            AvailabilityClass.HISTORICAL_RECONSTRUCTED,
            "seconds",
            "parse_ready_at",
            "parser-v1",
            "synthetic",
            supports_historical_reconstruction=True,
        )
    )
    return registry


def publish(store: EvidenceStore, *, minute: int = 0, contract_id: str = "prospective-parser-v1", content_type: str = "application/json"):
    parser_version = "parser-v2" if contract_id.endswith("v2") else "parser-v1"
    return store.publish(
        b'{"weather":"dry"}',
        contract_id=contract_id,
        source_uri="synthetic://weather/1",
        provider="synthetic",
        source_type="fixture",
        retrieved_at=f"2026-01-01T00:{minute:02d}:00Z",
        parse_ready_at=f"2026-01-01T00:{minute:02d}:01Z",
        parser_version=parser_version,
        content_type=content_type,
        licensing_note="synthetic",
        availability_class=AvailabilityClass.PROSPECTIVE_CAPTURED,
    )


def provenance(observation, *, artifact_hash: str | None = None) -> ProvenanceRef:
    return ProvenanceRef(
        artifact_hash or observation.artifact_hash,
        observation.contract_id,
        observation.source_uri,
        observation.retrieved_at,
        observation.parse_ready_at,
        observation.availability_class,
        observation.parser_version,
        "$.weather",
        observation.observation_id,
    )


def research(observation, **changes) -> ResearchEvidence:
    values = {
        "evidence_id": "evidence-1",
        "event_id": "event-1",
        "category": "weather",
        "normalized_claim": "dry",
        "source_ref": provenance(observation),
        "source_timestamp": "2026-01-01T00:00:00Z",
        "retrieved_at": observation.retrieved_at,
        "status": EvidenceStatus.CONFIRMED,
        "freshness_expires_at": "2026-01-01T01:00:00Z",
        "extractor_version": "extract-v1",
        "contradiction_ids": (),
        "ready_at": observation.parse_ready_at,
        "evidence_span": "$.weather",
        "prompt_schema_hash": digest("a"),
    }
    values.update(changes)
    return ResearchEvidence(**values)


def pack(structured_hash: str) -> EvidencePack:
    return EvidencePack.freeze(
        pack_id=f"pack-{structured_hash[:8]}",
        evidence_cutoff_ts="2026-01-01T00:10:00Z",
        frozen_at="2026-01-01T00:11:00Z",
        source_artifact_hashes=(digest("b"),),
        extractor_versions=("extract-v1",),
        prompt_schema_hash=digest("a"),
        contradiction_links=(),
        freshness_state=("fresh",),
        feature_manifest_hash=digest("c"),
        structured_evidence_hashes=(structured_hash,),
    )


def decision_inputs(pack_hash: str) -> dict[str, str]:
    return {
        "strategy_version": "v1",
        "strategy_config_hash": digest("1"),
        "strategy_decision_contract_hash": digest("0"),
        "odds_profile_hash": digest("2"),
        "sport_adapter_version": "synthetic-offline-v0.4",
        "event_id": "event-1",
        "market_id": "market-1",
        "selection_id": "selection-1",
        "side": "back",
        "evidence_cutoff_ts": "2026-01-01T00:10:00Z",
        "candidate_decision_ts": "2026-01-01T00:11:00Z",
        "evidence_pack_hash": pack_hash,
        "feature_manifest_hash": digest("3"),
        "model_artifact_hash": digest("4"),
        "calibration_artifact_hash": digest("5"),
        "gate_policy_hash": digest("6"),
    }


class R2PITAuthorityTests(unittest.TestCase):
    def test_capability_authority_is_mandatory_for_all_decision_reads(self):
        with self.assertRaises(TypeError):
            PITStore(None)  # type: ignore[call-arg]
        with scratch_directory() as tmp:
            capabilities = SourceCapabilityRegistry(tmp / "capabilities.jsonl")
            store = PITStore(None, capabilities=capabilities)
            store.append(
                BitemporalRecord(
                    "r1", "entity", "unknown", digest("a"),
                    "2026-01-01T00:00:00Z", None,
                    "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z",
                    "2026-01-01T00:00:00Z",
                )
            )
            with self.assertRaises(SourceUnavailable):
                store.as_of_query("entity", "2026-01-01T00:01:00Z")
            with self.assertRaises(SourceUnavailable):
                store.feature_view("features-v1", ("entity",), "2026-01-01T00:01:00Z")

    def test_capability_is_versioned_and_resolved_at_decision_time(self):
        with scratch_directory() as tmp:
            capabilities = SourceCapabilityRegistry(tmp / "capabilities.jsonl")
            capabilities.register(
                capability(
                    status=OperationalStatus.BLOCKED,
                    recorded_at="2026-01-01T00:00:00Z",
                    version="v1",
                )
            )
            capabilities.register(
                capability(
                    status=OperationalStatus.READY,
                    recorded_at="2026-01-01T00:10:00Z",
                    version="v2",
                )
            )
            store = PITStore(tmp / "pit.jsonl", capabilities=capabilities)
            store.append(
                BitemporalRecord(
                    "r1", "entity", "source-1", digest("a"),
                    "2026-01-01T00:01:00Z", None,
                    "2026-01-01T00:02:00Z", "2026-01-01T00:03:00Z",
                    "2026-01-01T00:01:00Z",
                )
            )
            with self.assertRaises(SourceUnavailable):
                store.as_of_query("entity", "2026-01-01T00:05:00Z")
            self.assertEqual(
                [row.record_id for row in store.as_of_query("entity", "2026-01-01T00:10:00Z")],
                ["r1"],
            )

    def test_retrieval_ready_and_supersession_temporality_fail_closed(self):
        with scratch_directory() as tmp:
            capabilities = SourceCapabilityRegistry(tmp / "capabilities.jsonl")
            capabilities.register(
                capability(
                    status=OperationalStatus.READY,
                    recorded_at="2025-12-31T23:00:00Z",
                    version="v1",
                )
            )
            store = PITStore(None, capabilities=capabilities)
            store.append(
                BitemporalRecord(
                    "future-retrieval", "future-retrieval", "source-1", digest("a"),
                    "2026-01-01T00:00:00Z", None,
                    "2026-01-01T00:10:00Z", "2026-01-01T00:00:01Z",
                    "2026-01-01T00:00:00Z",
                )
            )
            store.append(
                BitemporalRecord(
                    "future-ready", "future-ready", "source-1", digest("b"),
                    "2026-01-01T00:00:00Z", None,
                    "2026-01-01T00:00:00Z", "2026-01-01T00:10:00Z",
                    "2026-01-01T00:00:00Z",
                )
            )
            self.assertEqual(
                store.as_of_query("future-retrieval", "2026-01-01T00:05:00Z"), ()
            )
            self.assertEqual(store.as_of_query("future-ready", "2026-01-01T00:05:00Z"), ())
            self.assertEqual(len(store.as_of_query("future-retrieval", "2026-01-01T00:10:00Z")), 1)


class R2ObservationIdentityTests(unittest.TestCase):
    def test_raw_content_and_observations_have_distinct_idempotent_identity(self):
        with scratch_directory() as tmp:
            store = EvidenceStore(
                tmp / "evidence", contracts=register_contracts(tmp / "contracts.jsonl")
            )
            first = publish(store, minute=0)
            exact_replay = publish(store, minute=0)
            later = publish(store, minute=1)
            parser_change = publish(store, minute=2, contract_id="prospective-parser-v2")
            type_change = publish(store, minute=3, content_type="text/plain")
            self.assertEqual(first.observation_id, exact_replay.observation_id)
            self.assertEqual(
                len({first.observation_id, later.observation_id, parser_change.observation_id, type_change.observation_id}),
                4,
            )
            self.assertEqual(len(store.get_observations(first.artifact_hash)), 4)
            self.assertEqual(store.verify_manifest(), 4)
            object_files = [path for path in store.objects.rglob("*") if path.is_file()]
            self.assertEqual(len(object_files), 1)
            with self.assertRaises(ValueError):
                store.get_metadata(first.artifact_hash)

    def test_contract_substitution_unknown_contract_and_object_tamper_are_rejected(self):
        with scratch_directory() as tmp:
            contracts = register_contracts(tmp / "contracts.jsonl")
            store = EvidenceStore(tmp / "evidence", contracts=contracts)
            kwargs = {
                "contract_id": "historical-v1",
                "source_uri": "synthetic://weather/1",
                "provider": "synthetic",
                "source_type": "fixture",
                "retrieved_at": "2026-01-01T00:00:00Z",
                "parse_ready_at": "2026-01-01T00:00:01Z",
                "parser_version": "parser-v1",
                "content_type": "application/json",
                "licensing_note": "synthetic",
                "availability_class": AvailabilityClass.PROSPECTIVE_CAPTURED,
            }
            with self.assertRaises(ValueError):
                store.publish(b"payload", **kwargs)
            with self.assertRaises(Exception):
                store.publish(b"payload", **(kwargs | {"contract_id": "missing"}))
            observation = publish(store)
            store._object_path(observation.artifact_hash).write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                store.get_bytes(observation.artifact_hash)

    def test_legacy_metadata_migrates_deterministically_under_exact_contract(self):
        with scratch_directory() as tmp:
            store = EvidenceStore(
                tmp / "evidence", contracts=register_contracts(tmp / "contracts.jsonl")
            )
            payload = b"legacy"
            artifact_hash = sha256_bytes(payload)
            object_path = store._object_path(artifact_hash)
            object_path.parent.mkdir(parents=True, exist_ok=True)
            object_path.write_bytes(payload)
            metadata_path = store.root / "metadata" / f"{artifact_hash}.json"
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.write_bytes(
                canonical_json(
                    {
                        "artifact_hash": artifact_hash,
                        "source_uri": "synthetic://legacy/1",
                        "provider": "synthetic",
                        "source_type": "fixture",
                        "retrieved_at": "2026-01-01T00:00:00Z",
                        "first_seen_at": "2026-01-01T00:00:00Z",
                        "parse_ready_at": "2026-01-01T00:00:01Z",
                        "publisher_timestamp": None,
                        "valid_from": None,
                        "valid_to": None,
                        "upstream_version": None,
                        "parser_version": "parser-v1",
                        "content_type": "text/plain",
                        "byte_length": len(payload),
                        "licensing_note": "synthetic",
                        "availability_class": "prospective_captured",
                    }
                )
            )
            first = store.import_legacy_metadata(
                artifact_hash, contract_id="prospective-parser-v1"
            )
            second = store.import_legacy_metadata(
                artifact_hash, contract_id="prospective-parser-v1"
            )
            self.assertEqual(first.observation_id, second.observation_id)
            self.assertEqual(store.verify_manifest(), 1)


class R2StructuredEvidenceTests(unittest.TestCase):
    def test_all_material_research_fields_and_exact_observation_change_digest(self):
        with scratch_directory() as tmp:
            evidence = EvidenceStore(
                tmp / "evidence", contracts=register_contracts(tmp / "contracts.jsonl")
            )
            first_observation = publish(evidence, minute=0)
            second_observation = publish(evidence, minute=1)
            original = research(first_observation)
            variants = (
                replace(original, normalized_claim="wet"),
                replace(original, status=EvidenceStatus.UNCERTAIN),
                replace(original, evidence_span="$.forecast"),
                replace(original, contradiction_ids=("contradiction-1",)),
                replace(
                    original,
                    source_ref=provenance(second_observation),
                    retrieved_at=second_observation.retrieved_at,
                    ready_at=second_observation.parse_ready_at,
                ),
            )
            self.assertEqual(original.digest, research(first_observation).digest)
            self.assertTrue(all(item.digest != original.digest for item in variants))

    def test_structured_store_resolves_exact_observation_and_pack_resolves_structured_hash(self):
        with scratch_directory() as tmp:
            evidence = EvidenceStore(
                tmp / "evidence", contracts=register_contracts(tmp / "contracts.jsonl")
            )
            observation = publish(evidence)
            structured = StructuredEvidenceStore(tmp / "structured", evidence=evidence)
            item = research(observation)
            structured_hash = structured.publish(item)
            pack_store = EvidencePackStore(tmp / "packs", structured_evidence=structured)
            frozen = pack_store.freeze(pack(structured_hash))
            self.assertTrue(frozen.authoritative_complete)
            self.assertEqual(pack_store.use_authoritatively(frozen.pack_hash), frozen)

            missing = pack(digest("f"))
            with self.assertRaises(ValueError):
                pack_store.freeze(missing)

            wrong_ref = research(
                observation, source_ref=provenance(observation, artifact_hash=digest("9"))
            )
            with self.assertRaises(ValueError):
                structured.publish(wrong_ref)

    def test_legacy_pack_is_audit_only_and_identity_propagates_to_decision(self):
        with scratch_directory() as tmp:
            evidence = EvidenceStore(
                tmp / "evidence", contracts=register_contracts(tmp / "contracts.jsonl")
            )
            observation = publish(evidence)
            structured = StructuredEvidenceStore(tmp / "structured", evidence=evidence)
            first_hash = structured.publish(research(observation))
            second_hash = structured.publish(research(observation, normalized_claim="wet"))
            first_pack = pack(first_hash)
            second_pack = pack(second_hash)
            self.assertNotEqual(first_pack.pack_hash, second_pack.pack_hash)
            self.assertNotEqual(
                candidate_decision_hash(decision_inputs(first_pack.pack_hash)),
                candidate_decision_hash(decision_inputs(second_pack.pack_hash)),
            )

            legacy = EvidencePack.freeze(
                pack_id="legacy",
                evidence_cutoff_ts="2026-01-01T00:10:00Z",
                frozen_at="2026-01-01T00:11:00Z",
                source_artifact_hashes=(observation.artifact_hash,),
                extractor_versions=("extract-v1",),
                prompt_schema_hash=digest("a"),
                contradiction_links=(),
                freshness_state=("fresh",),
                feature_manifest_hash=digest("c"),
            )
            pack_store = EvidencePackStore(tmp / "packs", structured_evidence=structured)
            pack_store.freeze(legacy)
            self.assertFalse(legacy.authoritative_complete)
            with self.assertRaises(ValueError):
                pack_store.use_authoritatively(legacy.pack_hash)


if __name__ == "__main__":
    unittest.main()
