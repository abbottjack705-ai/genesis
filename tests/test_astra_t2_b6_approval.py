from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import genesis.decision_output as decision_output_module
from genesis.decision import candidate_decision_hash, candidate_v3_decision_hash
from genesis.decision_output import (
    DecisionOutputStore,
    StrategyOutputRuleBindingStore,
    TrustedDecisionOutputAuthority,
    rule_binding_hash,
)
from genesis.repro import canonical_json, immutable_write, sha256_bytes

from ._support import scratch_directory


V2_PREFIX = "strategy-output-approval-v2:"


def digest(character: str) -> str:
    return character * 64


def binding(reference: str) -> dict:
    return {
        "domain": "genesis.strategy-output-rule-binding.v1",
        "schema_version": "strategy-output-rule-binding-v1",
        "strategy_decision_contract_hash": digest("2"),
        "active_policy_digest": digest("3"),
        "approved_tier_policy_id": "risk-v1",
        "model_artifact_hash": digest("4"),
        "calibration_artifact_hash": digest("5"),
        "feature_manifest_hash": digest("6"),
        "gate_policy_hash": digest("7"),
        "model_runner_hash": digest("8"),
        "calibration_runner_hash": digest("9"),
        "tier_rule_hash": digest("a"),
        "expiry_rule_hash": digest("b"),
        "resolver_artifact_hash": digest("c"),
        "scope": "PAPER",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_through": None,
        "human_approval_reference": reference,
    }


class AstraT2B6ApprovalTests(unittest.TestCase):
    """Independent tests for a genuine, non-circular approval workflow."""

    def approval_store(self, path: Path):
        store_type = getattr(
            decision_output_module, "StrategyOutputApprovalStore", None,
        )
        self.assertIsNotNone(
            store_type,
            "B6 RED: production has no durable acyclic approval owner",
        )
        return store_type(path)

    @staticmethod
    def authority(root: Path, approvals=None) -> TrustedDecisionOutputAuthority:
        arguments = dict(
            outputs=DecisionOutputStore(root / "outputs"),
            bindings=StrategyOutputRuleBindingStore(root / "bindings.jsonl"),
            resolver=None,
            approval_root=root / "legacy-approvals",
        )
        if approvals is not None:
            arguments["approvals"] = approvals
        return TrustedDecisionOutputAuthority(**arguments)

    @staticmethod
    def reserve(store, *, request_id: str = "synthetic-b6-request") -> str:
        return store.reserve(
            request_id=request_id,
            reserved_by="synthetic-b6-operator",
            reserved_at="2026-01-01T00:00:00Z",
            scope="PAPER",
        )

    @staticmethod
    def grant(store, reference: str, binding_hash: str) -> None:
        store.grant(
            reference,
            binding_hash=binding_hash,
            approved_by="synthetic-b6-human",
            approved_at="2026-01-01T00:05:00Z",
            scope="PAPER",
        )

    def test_reserved_reference_constructs_final_binding_and_real_validator_accepts(self):
        with scratch_directory() as root:
            approvals = self.approval_store(root / "approvals-v2.jsonl")
            reference = self.reserve(approvals)
            self.assertTrue(reference.startswith(V2_PREFIX))
            final_hash = rule_binding_hash(binding(reference))
            self.grant(approvals, reference, final_hash)

            # No validator override: this is the production authority itself.
            self.authority(root, approvals)._validate_approval_reference(
                reference,
                binding_hash=final_hash,
                decision_at="2026-01-01T00:10:00Z",
            )

    def test_missing_wrong_future_tampered_and_revoked_approval_fail_closed(self):
        with scratch_directory() as root:
            path = root / "approvals-v2.jsonl"
            approvals = self.approval_store(path)
            reference = self.reserve(approvals)
            final_hash = rule_binding_hash(binding(reference))
            authority = self.authority(root, approvals)

            with self.assertRaises(ValueError):
                authority._validate_approval_reference(
                    reference, binding_hash=final_hash,
                    decision_at="2026-01-01T00:10:00Z",
                )
            self.grant(approvals, reference, final_hash)
            with self.assertRaises(ValueError):
                authority._validate_approval_reference(
                    reference, binding_hash=digest("f"),
                    decision_at="2026-01-01T00:10:00Z",
                )
            with self.assertRaises(ValueError):
                authority._validate_approval_reference(
                    V2_PREFIX + digest("f"), binding_hash=final_hash,
                    decision_at="2026-01-01T00:10:00Z",
                )
            with self.assertRaises(ValueError):
                authority._validate_approval_reference(
                    reference, binding_hash=final_hash,
                    decision_at="2026-01-01T00:04:59Z",
                )

            approvals.revoke(
                reference,
                binding_hash=final_hash,
                revoked_by="synthetic-b6-human",
                revoked_at="2026-01-01T00:06:00Z",
                reason="synthetic adversarial revocation",
            )
            with self.assertRaises(ValueError):
                authority._validate_approval_reference(
                    reference, binding_hash=final_hash,
                    decision_at="2026-01-01T00:10:00Z",
                )

            raw = path.read_bytes()
            path.write_bytes(raw.replace(
                b"synthetic-b6-human", b"synthetic-b6-tamper", 1,
            ))
            with self.assertRaises(ValueError):
                authority._validate_approval_reference(
                    reference, binding_hash=final_hash,
                    decision_at="2026-01-01T00:10:00Z",
                )

    def test_wrong_scope_and_absent_real_authority_fail_closed(self):
        with scratch_directory() as root:
            approvals = self.approval_store(root / "approvals-v2.jsonl")
            with self.assertRaises(ValueError):
                approvals.reserve(
                    request_id="live-is-not-authorized",
                    reserved_by="synthetic-b6-operator",
                    reserved_at="2026-01-01T00:00:00Z",
                    scope="LIVE",
                )
            reference = self.reserve(approvals)
            final_hash = rule_binding_hash(binding(reference))
            self.grant(approvals, reference, final_hash)
            with self.assertRaises(ValueError):
                self.authority(root, None)._validate_approval_reference(
                    reference, binding_hash=final_hash,
                    decision_at="2026-01-01T00:10:00Z",
                )

    def test_restart_and_exact_replay_are_idempotent(self):
        with scratch_directory() as root:
            path = root / "approvals-v2.jsonl"
            first = self.approval_store(path)
            reference = self.reserve(first)
            final_hash = rule_binding_hash(binding(reference))
            self.grant(first, reference, final_hash)
            rows_before = first.log.records()

            restarted = self.approval_store(path)
            self.assertEqual(reference, self.reserve(restarted))
            self.grant(restarted, reference, final_hash)
            self.assertEqual(rows_before, restarted.log.records())
            self.authority(root, restarted)._validate_approval_reference(
                reference, binding_hash=final_hash,
                decision_at="2026-01-01T00:10:00Z",
            )

    def test_concurrent_reservation_and_publication_are_single_winner(self):
        with scratch_directory() as root:
            path = root / "approvals-v2.jsonl"

            def reserve_once(_index: int) -> str:
                return self.reserve(self.approval_store(path))

            with ThreadPoolExecutor(max_workers=8) as pool:
                references = list(pool.map(reserve_once, range(16)))
            self.assertEqual(1, len(set(references)))
            reference = references[0]
            final_hash = rule_binding_hash(binding(reference))

            def grant_once(_index: int) -> str:
                self.grant(self.approval_store(path), reference, final_hash)
                return final_hash

            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(
                    [final_hash] * 16,
                    list(pool.map(grant_once, range(16))),
                )
            rows = self.approval_store(path).log.records()
            self.assertEqual(
                1,
                sum(row.get("record_type") ==
                    "strategy_output_approval_reference_reserved" for row in rows),
            )
            self.assertEqual(
                1,
                sum(row.get("record_type") ==
                    "strategy_output_approval_granted" for row in rows),
            )

            other_hash = digest("e")

            def conflicting(candidate_hash: str) -> str:
                try:
                    self.grant(
                        self.approval_store(path), reference, candidate_hash,
                    )
                except ValueError:
                    return "rejected"
                return "accepted"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(conflicting, (final_hash, other_hash)))
            self.assertEqual(["accepted", "rejected"], outcomes)

    def test_legacy_v1_content_hash_note_remains_valid(self):
        with scratch_directory() as root:
            note = {
                "domain": "genesis.strategy-output-approval.v1",
                "schema_version": "strategy-output-approval-v1",
                "binding_hash": digest("d"),
                "approved_by": "historical-operator",
                "approved_at": "2026-01-01T00:05:00.000000Z",
                "scope": "PAPER",
            }
            raw = canonical_json(note)
            reference = sha256_bytes(raw)
            immutable_write(
                root / "legacy-approvals" / f"{reference}.json", raw,
            )
            self.authority(root)._validate_approval_reference(
                reference,
                binding_hash=digest("d"),
                decision_at="2026-01-01T00:10:00Z",
            )

    def test_historical_identity_golden_hashes_are_unchanged(self):
        historical_v1_v2_preimage = {
            "strategy_version": "v1",
            "strategy_config_hash": digest("1"),
            "strategy_decision_contract_hash": digest("2"),
            "odds_profile_hash": digest("3"),
            "sport_adapter_version": "adapter-v1",
            "event_id": "event-1",
            "market_id": "market-1",
            "selection_id": "selection-1",
            "side": "back",
            "evidence_cutoff_ts": "2026-01-01T00:00:00.000000Z",
            "candidate_decision_ts": "2026-01-01T00:10:00.000000Z",
            "evidence_pack_hash": digest("4"),
            "feature_manifest_hash": digest("5"),
            "model_artifact_hash": digest("6"),
            "calibration_artifact_hash": digest("7"),
            "gate_policy_hash": digest("8"),
        }
        # Candidate-v1 and candidate-v2 deliberately share this frozen legacy
        # preimage; neither is relabelled or rehashed by T2.
        self.assertEqual(
            "716af420a02a122d69e673683008150c3e4b4dc5618e3387bd14f9a570e9f717",
            candidate_decision_hash(historical_v1_v2_preimage),
        )
        self.assertEqual(
            "a34308a04805b64ee572afbfc6bceb2fb44db2fdecd87dfea9d184a02e7c62db",
            candidate_v3_decision_hash(
                strategy_decision_contract_hash=digest("2"),
                feature_manifest_hash=digest("5"),
                evidence_pack_hash=digest("4"),
                decision_output_hash=digest("9"),
            ),
        )
        self.assertEqual(
            "3770e0e8001851b1355bce63a5ce28c73740f66cb2ac55fc0265e73530b4d2b9",
            rule_binding_hash(binding("historical-reference")),
        )


if __name__ == "__main__":
    unittest.main()
