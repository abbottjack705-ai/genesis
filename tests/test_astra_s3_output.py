"""Astra A4: legacy hashes cannot authorize new material decision outputs."""

from __future__ import annotations

import unittest
import importlib
import importlib.util
from dataclasses import replace

from ._support import scratch_directory
from .test_remediation_r3_qualification import build_fixture, digest
from genesis.decision import decision_hash_for_candidate
from genesis.time import iso_utc


NOW = "2026-01-01T00:11:00Z"


class AstraDecisionOutputBoundaryTests(unittest.TestCase):
    def _assert_legacy_audit_only(self, **changes):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            candidate = fixture["candidate"]
            if candidate.candidate_version == "candidate-v3":
                candidate = replace(
                    candidate, candidate_version="candidate-v2", decision_output_hash=None,
                )
                candidate = replace(
                    candidate,
                    candidate_decision_hash=decision_hash_for_candidate(
                        candidate,
                        strategy_config_hash=fixture["contract"].strategy_config_hash,
                        odds_profile_hash=fixture["profile_hash"],
                        sport_adapter_version=fixture["contract"].sport_adapter_version,
                    ),
                )
            candidate = replace(candidate, **changes)
            decision = fixture["authority"].evaluate(candidate, now=NOW)
            self.assertEqual(decision.action, "PASS", "unbound v2 output qualified")
            self.assertIsNone(decision.qualification_record_id)
            self.assertEqual(fixture["records"].verify(), 0)

    def test_original_candidate_v2_hash_is_audit_only_for_new_qualification(self):
        self._assert_legacy_audit_only()

    def test_copied_hash_cannot_change_model_probability(self):
        self._assert_legacy_audit_only(model_probability="0.63")

    def test_copied_hash_cannot_change_conservative_probability(self):
        self._assert_legacy_audit_only(conservative_probability="0.61")

    def test_copied_hash_cannot_change_uncertainty_status(self):
        self._assert_legacy_audit_only(uncertainty_status="uncertain")

    def test_copied_hash_cannot_change_observed_price(self):
        self._assert_legacy_audit_only(observed_odds="2.01")

    def test_copied_hash_cannot_change_price_band(self):
        self._assert_legacy_audit_only(requested_odds_min="1.60")

    def test_copied_hash_cannot_substitute_another_permitted_tier(self):
        self._assert_legacy_audit_only(strategy_tier="2.5u")

    def test_copied_hash_cannot_extend_expiry(self):
        self._assert_legacy_audit_only(expires_at="2026-01-01T02:00:00Z")

    def test_copied_hash_cannot_change_dependence(self):
        self._assert_legacy_audit_only(correlation_cluster_ids=("cluster-other",))


def synthetic_output_body(fixture):
    candidate = fixture["candidate"]
    contract = fixture["contract"]
    return {
        "domain": "genesis.decision-output.v1", "schema_version": "decision-output-v1",
        "feature_manifest_hash": candidate.feature_manifest_hash,
        "evidence_pack_hash": candidate.evidence_pack_id,
        "strategy_decision_contract_hash": contract.contract_hash,
        "strategy_config_hash": candidate.config_digest,
        "odds_profile_hash": fixture["profile_hash"],
        "sport_adapter_version": contract.sport_adapter_version,
        "market_capability_id": contract.market_capability_id,
        "model_artifact_hash": candidate.model_artifact_hash,
        "calibration_artifact_hash": candidate.calibration_artifact_hash,
        "gate_policy_hash": candidate.gate_policy_hash,
        "model_runner_hash": digest("1"), "calibration_runner_hash": digest("2"),
        "tier_rule_hash": digest("3"), "expiry_rule_hash": digest("4"),
        "resolver_binding_hash": digest("5"),
        "strategy_id": candidate.strategy_id, "strategy_version": candidate.strategy_version,
        "model_version": candidate.model_version, "sport": candidate.sport,
        "market_family": candidate.market_family, "event_id": candidate.event_id,
        "market_id": candidate.market_id, "selection_id": candidate.selection_id,
        "side": candidate.side.value,
        "evidence_cutoff_ts": iso_utc(candidate.evidence_cutoff_ts),
        "decision_at": iso_utc(candidate.decision_at),
        "model_probability": "0.62", "calibrated_probability": "0.61",
        "conservative_probability": "0.6", "model_support_status": "supported",
        "calibration_status": "supported", "uncertainty_status": "supported",
        "critical_uncertainty_flags": [], "support_region_id": "synthetic-test-region",
        "observed_odds": "2", "requested_odds_min": "1.5",
        "requested_odds_max": "3", "approved_tier": candidate.strategy_tier,
        "expires_at": iso_utc(candidate.expires_at),
        "comparability_group_id": candidate.comparability_group_id,
        "selection_dependency_group": None, "correlation_cluster_ids": [],
        "meeting_id": None, "competition_id": None,
        "participant_ids": [], "shared_evidence_ids": [],
    }


class AstraV3ContractTests(unittest.TestCase):
    def test_v3_preimage_and_output_are_domain_separated_and_material(self):
        from genesis import decision as decision_module
        spec = importlib.util.find_spec("genesis.decision_output")
        self.assertIsNotNone(spec, "no trusted v3 output contract exists")
        output_module = importlib.import_module("genesis.decision_output")
        self.assertTrue(callable(getattr(decision_module, "candidate_v3_decision_hash", None)))

        with scratch_directory() as root:
            fixture = build_fixture(root)
            body = synthetic_output_body(fixture)
            store = output_module.DecisionOutputStore(root / "outputs")
            first_output_hash = store.publish(body)
            self.assertEqual(store.get(first_output_hash), body)
            first_candidate_hash = decision_module.candidate_v3_decision_hash(
                strategy_decision_contract_hash=body["strategy_decision_contract_hash"],
                feature_manifest_hash=body["feature_manifest_hash"],
                evidence_pack_hash=body["evidence_pack_hash"],
                decision_output_hash=first_output_hash,
            )
            changed = dict(body, approved_tier="2.5u")
            second_output_hash = store.publish(changed)
            second_candidate_hash = decision_module.candidate_v3_decision_hash(
                strategy_decision_contract_hash=body["strategy_decision_contract_hash"],
                feature_manifest_hash=body["feature_manifest_hash"],
                evidence_pack_hash=body["evidence_pack_hash"],
                decision_output_hash=second_output_hash,
            )
            self.assertNotEqual(first_output_hash, second_output_hash)
            self.assertNotEqual(first_candidate_hash, second_candidate_hash)
            self.assertNotEqual(first_candidate_hash, fixture["candidate"].candidate_decision_hash)

    def test_output_schema_rejects_implicit_or_noncanonical_material_values(self):
        spec = importlib.util.find_spec("genesis.decision_output")
        self.assertIsNotNone(spec, "no strict output schema exists")
        output_module = importlib.import_module("genesis.decision_output")

        with scratch_directory() as root:
            fixture = build_fixture(root)
            body = synthetic_output_body(fixture)
            invalid = (
                dict(body, approved_tier="3.5u"),
                dict(body, model_probability="0.620"),
                dict(body, observed_odds=2),
                dict(body, expires_at=body["decision_at"]),
                dict(body, critical_uncertainty_flags=["x", "x"]),
                dict(body, extra_output="surprise"),
            )
            for item in invalid:
                with self.subTest(item=item):
                    with self.assertRaises(ValueError):
                        output_module.validate_decision_output(item)


if __name__ == "__main__":
    unittest.main()
