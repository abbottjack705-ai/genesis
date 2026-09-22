"""Astra A5: frozen evidence requires every exact causal input, not any event row."""

from __future__ import annotations

import unittest
from dataclasses import replace

from genesis.pit import BitemporalRecord, OperationalStatus, PITStore

from ._support import scratch_directory
from .test_remediation_r3_qualification import build_fixture, digest


NOW = "2026-01-01T00:11:00Z"


class AstraExactManifestTests(unittest.TestCase):
    def _inject_at_qualification_append(self, fixture, change):
        log = fixture["records"].log
        original = log.transaction
        inserted = False

        def at_entry(builder, **kwargs):
            nonlocal inserted
            if not inserted:
                inserted = True
                change()
            return original(builder, **kwargs)

        log.transaction = at_entry

    def _alternate_pit(self, root, fixture, *, payload_hash=None, source_id="source-1",
                       retrieved_at="2026-01-01T00:01:00Z",
                       ready_at="2026-01-01T00:01:01Z", record_id="pit-other"):
        original = fixture["authority"].pit.as_of_query(
            "event-1", "2026-01-01T00:02:00Z", source_id="source-1"
        )[0]
        pit = PITStore(root / "alternate-pit.jsonl",
                       capabilities=fixture["authority"].pit.capabilities)
        pit.append(BitemporalRecord(
            record_id, "event-1", source_id, payload_hash or original.payload_hash,
            retrieved_at, None, retrieved_at, ready_at,
            "2026-01-01T00:00:00Z",
        ))
        fixture["authority"].pit = pit

    def _assert_pass_without_new_qualification(self, fixture):
        decision = fixture["authority"].evaluate(fixture["candidate"], now=NOW)
        self.assertEqual(decision.action, "PASS", "unrelated PIT row certified frozen evidence")
        self.assertIsNone(decision.qualification_record_id)
        self.assertEqual(fixture["records"].verify(), 0)

    def test_same_event_different_payload_cannot_certify_frozen_pack(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            self._alternate_pit(root, fixture, payload_hash=digest("9"))
            self._assert_pass_without_new_qualification(fixture)

    def test_same_payload_but_wrong_pit_identity_cannot_certify_pack(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            self._alternate_pit(root, fixture, record_id="pit-other")
            self._assert_pass_without_new_qualification(fixture)

    def test_same_event_wrong_source_cannot_certify_pack(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            capabilities = fixture["authority"].pit.capabilities
            source = capabilities.require_ready_at("source-1", "2026-01-01T00:02:00Z")
            capabilities.register(replace(source, source_id="source-2"))
            self._alternate_pit(root, fixture, source_id="source-2")
            self._assert_pass_without_new_qualification(fixture)

    def test_post_cutoff_retrieval_cannot_be_used_at_earlier_freeze(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            self._alternate_pit(
                root, fixture, retrieved_at="2026-01-01T00:03:00Z",
                ready_at="2026-01-01T00:03:01Z",
            )
            self._assert_pass_without_new_qualification(fixture)

    def test_missing_exact_manifest_object_cannot_be_replaced_by_digest_shape(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            # Current R3 accepts the pack's digest-shaped feature ID without
            # resolving an object. The S3a owner must fail closed if absent.
            fixture["authority"].feature_manifests = None
            self._assert_pass_without_new_qualification(fixture)

    def test_new_as_of_cutoff_head_cannot_silently_replace_pinned_row(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            fixture["authority"].pit.append(BitemporalRecord(
                "pit-correction", "event-1", "source-1", digest("9"),
                "2026-01-01T00:01:20Z", None, "2026-01-01T00:01:20Z",
                "2026-01-01T00:01:21Z", "2026-01-01T00:01:20Z",
            ))
            self._assert_pass_without_new_qualification(fixture)

    def test_capability_change_after_freeze_does_not_rewrite_old_cutoff(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            capabilities = fixture["authority"].pit.capabilities
            earlier = capabilities.require_ready_at("source-1", "2026-01-01T00:02:00Z")
            capabilities.register(replace(
                earlier, version="v2", operational_status=OperationalStatus.BLOCKED,
                recorded_at="2026-01-01T00:05:00Z",
            ))
            decision = fixture["authority"].evaluate(fixture["candidate"], now=NOW)
            self.assertEqual(decision.action, "QUALIFY",
                             "later source status retroactively replaced frozen evidence")

    def test_exact_manifest_ignores_unrelated_event_and_restarts_identically(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            fixture["authority"].pit.append(BitemporalRecord(
                "other-event", "event-other", "source-1", digest("9"),
                "2026-01-01T00:01:00Z", None, "2026-01-01T00:01:00Z",
                "2026-01-01T00:01:01Z", "2026-01-01T00:00:00Z",
            ))
            manifests = fixture["feature_manifests"]
            self.assertIsNotNone(manifests, "A5 has no durable manifest owner")
            from genesis.feature_manifest import (
                FeatureInputManifestStore, SourceInputBindingStore,
            )
            fixture["authority"].feature_manifests = FeatureInputManifestStore(
                root / "feature-manifests",
                bindings=SourceInputBindingStore(root / "source-bindings.jsonl"),
            )
            decision = fixture["authority"].evaluate(fixture["candidate"], now=NOW)
            self.assertEqual(decision.action, "QUALIFY")

    def test_hash_valid_but_unrelated_manifest_object_is_not_pack_authority(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            manifests = fixture["feature_manifests"]
            if manifests is not None:
                from genesis.feature_manifest import FeatureInputManifestStore
                original = manifests.get(fixture["candidate"].feature_manifest_hash)
                other = dict(original)
                other["event_id"] = "event-other"
                other["required_inputs"] = [dict(item, event_id="event-other")
                                            for item in original["required_inputs"]]
                unrelated = FeatureInputManifestStore(
                    root / "unrelated-manifests", bindings=manifests.bindings,
                )
                unrelated.publish(other)
                fixture["authority"].feature_manifests = unrelated
            self._assert_pass_without_new_qualification(fixture)

    def test_pit_correction_at_qualification_commit_cannot_escape_proof(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)

            def correction():
                fixture["authority"].pit.append(BitemporalRecord(
                    "pit-interleaved", "event-1", "source-1", digest("9"),
                    "2026-01-01T00:01:20Z", None,
                    "2026-01-01T00:01:20Z", "2026-01-01T00:01:21Z",
                    "2026-01-01T00:01:20Z",
                ))

            self._inject_at_qualification_append(fixture, correction)
            self._assert_pass_without_new_qualification(fixture)

    def test_source_block_at_qualification_commit_cannot_escape_proof(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)

            def source_block():
                capabilities = fixture["authority"].pit.capabilities
                earlier = capabilities.require_ready_at("source-1", "2026-01-01T00:02:00Z")
                capabilities.register(replace(
                    earlier, version="v2", operational_status=OperationalStatus.BLOCKED,
                    recorded_at="2026-01-01T00:01:30Z",
                ))

            self._inject_at_qualification_append(fixture, source_block)
            self._assert_pass_without_new_qualification(fixture)


if __name__ == "__main__":
    unittest.main()
