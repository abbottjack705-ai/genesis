from __future__ import annotations

import json
import unittest
from dataclasses import asdict
from decimal import Decimal

from genesis.accounting import BetSide
from genesis.config import OperationalMode
from genesis.decision import candidate_v3_decision_hash
from genesis.execution import ModeState, ModeStateStore
from genesis.policy import PolicySet, RiskPolicy, canonical_decimal, parse_tier
from genesis.registry import (
    StrategyArtifact, StrategyDecisionContract, StrategyLifecycle,
    StrategyRegistry,
)
from genesis.risk import (
    BankrollSnapshot,
    BankrollSnapshotStore,
    Exposure,
    ExposureState,
    RiskAuditLog,
    RiskEngine,
    RiskRequest,
    SafetyState,
    SafetyStateStore,
)
from genesis.selection import QualificationRecord, QualificationRecordStore
from genesis.time import iso_utc
from ._support import SyntheticQualificationRecordStore as QualificationRecordStore, scratch_directory


def digest(character: str) -> str:
    return character * 64


def qualification(
    store: QualificationRecordStore,
    policy: PolicySet,
    *,
    candidate_hash: str,
    contract_hash: str,
    tier: str,
    candidate_id: str = "candidate",
    expires_at: str = "2026-01-01T01:00:00Z",
    side: BetSide = BetSide.BACK,
    odds: str = "2",
) -> QualificationRecord:
    binding = {
        "domain": "genesis.strategy-output-rule-binding.v1",
        "schema_version": "strategy-output-rule-binding-v1",
        "strategy_decision_contract_hash": contract_hash,
        "active_policy_digest": policy.digest,
        "approved_tier_policy_id": policy.risk.version,
        "model_artifact_hash": digest("1"),
        "calibration_artifact_hash": digest("2"),
        "feature_manifest_hash": digest("c"),
        "gate_policy_hash": digest("3"),
        "model_runner_hash": digest("4"),
        "calibration_runner_hash": digest("5"),
        "tier_rule_hash": digest("6"),
        "expiry_rule_hash": digest("7"),
        "resolver_artifact_hash": digest("9"),
        "scope": "PAPER", "valid_from": iso_utc("2026-01-01T00:00:00Z"),
        "valid_through": None,
        "human_approval_reference": "synthetic-test-only-risk-not-operational",
    }
    binding_hash = store.bindings.register_approved(binding)
    output = {
        "domain": "genesis.decision-output.v1", "schema_version": "decision-output-v1",
        "feature_manifest_hash": digest("c"), "evidence_pack_hash": digest("d"),
        "strategy_decision_contract_hash": contract_hash,
        "strategy_config_hash": digest("e"), "odds_profile_hash": digest("f"),
        "sport_adapter_version": "synthetic-risk-test", "market_capability_id": "capability-v1",
        "model_artifact_hash": digest("1"), "calibration_artifact_hash": digest("2"),
        "gate_policy_hash": digest("3"), "model_runner_hash": digest("4"),
        "calibration_runner_hash": digest("5"), "tier_rule_hash": digest("6"),
        "expiry_rule_hash": digest("7"), "resolver_binding_hash": binding_hash,
        "strategy_id": "strategy", "strategy_version": "v1", "model_version": "model-v1",
        "sport": "football", "market_family": "match_winner",
        "event_id": f"event-{candidate_id}-{candidate_hash[:8]}",
        "market_id": "market-test", "selection_id": f"selection-{candidate_id}-{candidate_hash[:8]}",
        "side": side.value, "evidence_cutoff_ts": iso_utc("2026-01-01T00:00:00Z"),
        "decision_at": iso_utc("2026-01-01T00:00:00Z"),
        "model_probability": "0.62", "calibrated_probability": "0.61",
        "conservative_probability": "0.6", "model_support_status": "supported",
        "calibration_status": "supported", "uncertainty_status": "supported",
        "critical_uncertainty_flags": [], "support_region_id": "synthetic-risk-test",
        "observed_odds": canonical_decimal(Decimal(odds)), "requested_odds_min": "1.5",
        "requested_odds_max": "3", "approved_tier": tier if tier in {
            "1.0u", "1.5u", "2.0u", "2.5u", "3.0u",
        } else "3.0u", "expires_at": iso_utc(expires_at),
        "comparability_group_id": "group", "selection_dependency_group": None,
        "correlation_cluster_ids": [], "meeting_id": None, "competition_id": None,
        "participant_ids": [], "shared_evidence_ids": [],
    }
    output_hash = store.outputs.publish(output)
    derived_hash = candidate_v3_decision_hash(
        strategy_decision_contract_hash=contract_hash,
        feature_manifest_hash=output["feature_manifest_hash"],
        evidence_pack_hash=output["evidence_pack_hash"],
        decision_output_hash=output_hash,
    )
    return store.record_fixture_qualification(
        QualificationRecord.create(
            schema_version="qualification-record-v3",
            candidate_id=candidate_id,
            candidate_decision_hash=derived_hash,
            strategy_id="strategy",
            strategy_version="v1",
            strategy_decision_contract_hash=contract_hash,
            approved_tier=tier,
            comparability_group_id="group",
            active_policy_digest=policy.digest,
            market_capability_id="capability-v1",
            decision_at="2026-01-01T00:00:00Z",
            evaluated_at="2026-01-01T00:01:00Z",
            expires_at=expires_at,
            gate_results_digest=digest("b"),
            decision_output_hash=output_hash,
            feature_manifest_hash=output["feature_manifest_hash"],
        )
    )


def build_risk(
    tmp,
    *,
    tier: str = "3.0u",
    candidate_hash: str = digest("1"),
    bankroll: str = "100",
    expires_at: str = "2026-01-01T01:00:00Z",
    side: BetSide = BetSide.BACK,
    odds: str = "2",
):
    policy = PolicySet()
    bankrolls = BankrollSnapshotStore(tmp / "bankroll.jsonl")
    snapshot = BankrollSnapshot.create(
        bankroll=bankroll,
        captured_at="2026-01-01T00:00:00Z",
        rebase_reason="initial",
    )
    bankrolls.append(snapshot)
    safety = SafetyStateStore(tmp / "safety.jsonl")
    safety_state = SafetyState.create(
        kill_switch_active=False,
        recorded_at="2026-01-01T00:00:00Z",
        reason="mode:paper",
    )
    safety.append(safety_state)
    modes = ModeStateStore(tmp / "mode.jsonl")
    modes.append(ModeState.create(
        mode=OperationalMode.PAPER,
        occurred_at="2026-01-01T00:00:00Z",
        authorization_id="synthetic-offline-test-only",
        parent_state_id=None,
    ))
    # Synthetic, nonoperational exact PAPER strategy/contract authority for
    # risk and execution regression fixtures. It grants no model/tier/TTL GO.
    strategies = StrategyRegistry(tmp / "strategies.jsonl")
    strategies.register(StrategyArtifact(
        "strategy", "v1", StrategyLifecycle.IDEA,
        digest("8"), digest("e"), digest("1"),
        "synthetic-risk-test", "2025-12-31T23:50:00Z",
    ))
    for lifecycle, at in (
        (StrategyLifecycle.EXPLORATION, "2025-12-31T23:51:00Z"),
        (StrategyLifecycle.WALK_FORWARD, "2025-12-31T23:52:00Z"),
        (StrategyLifecycle.PROTECTED, "2025-12-31T23:53:00Z"),
        (StrategyLifecycle.PROSPECTIVE_SHADOW, "2025-12-31T23:54:00Z"),
        (StrategyLifecycle.PAPER, "2025-12-31T23:55:00Z"),
    ):
        strategies.transition("strategy", "v1", lifecycle, occurred_at=at)
    contract = StrategyDecisionContract.create(
        strategy_id="strategy", strategy_version="v1",
        strategy_config_hash=digest("e"), odds_profile_hash=digest("f"),
        sport_adapter_version="synthetic-risk-test",
        market_capability_id="capability-v1",
        required_lifecycle=StrategyLifecycle.PAPER,
        support_region="synthetic-risk-test", comparability_group_id="group",
        model_artifact_hash=digest("1"),
        calibration_artifact_hash=digest("2"),
        feature_manifest_hash=digest("c"), gate_policy_hash=digest("3"),
        approved_tier_policy_id=policy.risk.version,
        approved_tiers=("1.0u", "1.5u", "2.0u", "2.5u", "3.0u"),
        created_at="2025-12-31T23:56:00Z",
    )
    strategies.register_decision_contract(contract)
    qualifications = QualificationRecordStore(tmp / "qualifications.jsonl")
    record = qualification(
        qualifications,
        policy,
        candidate_hash=candidate_hash,
        contract_hash=contract.contract_hash,
        tier=tier,
        expires_at=expires_at,
        side=side,
        odds=odds,
    )
    audit = RiskAuditLog(tmp / "risk.jsonl")
    engine = RiskEngine(
        policy=policy,
        bankrolls=bankrolls,
        qualifications=qualifications,
        safety=safety,
        audit_log=audit,
        strategies=strategies,
        modes=modes,
        action_clock=lambda requested_at: requested_at,  # synthetic offline time
    )
    return {
        "policy": policy,
        "bankrolls": bankrolls,
        "snapshot": snapshot,
        "safety": safety,
        "modes": modes,
        "strategies": strategies,
        "contract": contract,
        "qualifications": qualifications,
        "qualification": record,
        "audit": audit,
        "engine": engine,
        "candidate_hash": record.candidate_decision_hash,
    }


def request(
    fixture,
    *,
    side: BetSide = BetSide.BACK,
    odds: str = "2.00",
    requested_at: str = "2026-01-01T00:10:00Z",
    expected_tier: str | None = None,
    expected_stake: str | None = None,
    expected_liability: str | None = None,
    correlation_cluster_ids: tuple[str, ...] = (),
    candidate_hash: str | None = None,
    qualification_record_id: str | None = None,
    bankroll_snapshot_id: str | None = None,
) -> RiskRequest:
    return RiskRequest(
        candidate_hash or fixture["candidate_hash"],
        qualification_record_id or fixture["qualification"].qualification_record_id,
        bankroll_snapshot_id or fixture["bankrolls"].current().snapshot_id,
        side,
        odds,
        requested_at,
        correlation_cluster_ids,
        expected_tier=expected_tier,
        expected_stake=expected_stake,
        expected_liability=expected_liability,
    )


class R5RiskAuthorityTests(unittest.TestCase):
    def test_raw_liability_is_not_an_api_and_three_units_back_is_exact(self):
        with scratch_directory() as tmp:
            fixture = build_risk(tmp)
            with self.assertRaises(TypeError):
                fixture["engine"].approve(  # type: ignore[call-arg]
                    candidate_decision_hash=fixture["candidate_hash"],
                    bankroll="100",
                    requested_liability="50",
                )
            mismatch = fixture["engine"].approve(
                request(fixture, expected_liability="50")
            )
            self.assertFalse(mismatch.passed)
            self.assertEqual(mismatch.reason, "caller_liability_mismatch")
            approved = fixture["engine"].approve(
                request(fixture, expected_stake="7.50", expected_liability="7.50")
            )
            self.assertTrue(approved.passed)
            self.assertEqual(approved.approved_stake, "7.5")
            self.assertEqual(approved.approved_liability, "7.5")

    def test_invalid_or_contract_disallowed_tier_never_reaches_approval(self):
        with scratch_directory() as tmp:
            for index, tier in enumerate(("3.5u", "4.0u", "2.25u"), start=1):
                with self.subTest(tier=tier):
                    fixture = build_risk(
                        tmp / f"case-{index}", tier=tier, candidate_hash=str(index) * 64
                    )
                    decision = fixture["engine"].approve(request(fixture))
                    self.assertFalse(decision.passed)
                    with self.assertRaises(ValueError):
                        parse_tier(tier)
                    self.assertEqual(decision.reason, "authority_unavailable")

    def test_lay_liability_and_caller_mismatch_checks_are_decimal_exact(self):
        with scratch_directory() as tmp:
            fixture = build_risk(tmp, tier="2.0u", side=BetSide.LAY, odds="3")
            stake_mismatch = fixture["engine"].approve(
                request(fixture, side=BetSide.LAY, odds="3.00", expected_stake="5.01")
            )
            self.assertEqual(stake_mismatch.reason, "caller_stake_mismatch")
            liability_mismatch = fixture["engine"].approve(
                request(fixture, side=BetSide.LAY, odds="3.00", expected_liability="9.99")
            )
            self.assertEqual(liability_mismatch.reason, "caller_liability_mismatch")
            approved = fixture["engine"].approve(
                request(
                    fixture,
                    side=BetSide.LAY,
                    odds="3.00",
                    expected_stake="5.00",
                    expected_liability="10.00",
                )
            )
            self.assertTrue(approved.passed)
            self.assertEqual(approved.approved_stake, "5")
            self.assertEqual(approved.approved_liability, "10")

    def test_portfolio_cluster_unknown_and_duplicate_limits_use_durable_exposure(self):
        with scratch_directory() as tmp:
            total = build_risk(tmp / "total")
            total["engine"].record_exposure(
                Exposure("open", digest("8"), "55", ExposureState.MATCHED),
                recorded_at="2026-01-01T00:05:00Z",
            )
            self.assertEqual(
                total["engine"].approve(request(total)).reason, "open_liability_limit"
            )

            cluster = build_risk(tmp / "cluster")
            # B1: the correlated group must be in the trusted v3 output, not
            # introduced only by a risk caller's comparison copy.
            old_record = cluster["qualification"]
            output = cluster["qualifications"].outputs.get(
                old_record.decision_output_hash
            )
            output["correlation_cluster_ids"] = ["cluster-1"]
            output_hash = cluster["qualifications"].outputs.publish(output)
            fields = asdict(old_record)
            fields.pop("qualification_record_id")
            fields["decision_output_hash"] = output_hash
            fields["candidate_decision_hash"] = candidate_v3_decision_hash(
                strategy_decision_contract_hash=old_record.strategy_decision_contract_hash,
                feature_manifest_hash=old_record.feature_manifest_hash,
                evidence_pack_hash=output["evidence_pack_hash"],
                decision_output_hash=output_hash,
            )
            cluster["qualification"] = cluster["qualifications"].record_fixture_qualification(
                QualificationRecord.create(**fields)
            )
            cluster["candidate_hash"] = fields["candidate_decision_hash"]
            cluster["engine"].record_exposure(
                Exposure(
                    "cluster-open",
                    digest("8"),
                    "10",
                    ExposureState.PENDING,
                    ("cluster-1",),
                ),
                recorded_at="2026-01-01T00:05:00Z",
            )
            self.assertEqual(
                cluster["engine"].approve(
                    request(cluster, correlation_cluster_ids=("cluster-1",))
                ).reason,
                "correlation_cluster_limit",
            )

            unknown = build_risk(tmp / "unknown")
            unknown["engine"].record_exposure(
                Exposure("unknown", digest("8"), "1", ExposureState.UNKNOWN),
                recorded_at="2026-01-01T00:05:00Z",
            )
            self.assertEqual(
                unknown["engine"].approve(request(unknown)).reason,
                "unknown_exposure_blocks_new_risk",
            )

            duplicate = build_risk(tmp / "duplicate")
            first = duplicate["engine"].approve(request(duplicate))
            self.assertTrue(first.passed)
            self.assertEqual(
                duplicate["engine"].approve(request(duplicate)).reason,
                "duplicate_order_intent",
            )

    def test_durable_kill_switch_and_stale_bankroll_cannot_be_overridden(self):
        with scratch_directory() as tmp:
            kill = build_risk(tmp / "kill")
            safe = kill["safety"].current()
            kill["safety"].append(
                SafetyState.create(
                    kill_switch_active=True,
                    recorded_at="2026-01-01T00:05:00Z",
                    reason="operator-stop",
                    parent_state_id=safe.state_id,
                )
            )
            restarted = RiskEngine(
                policy=kill["policy"],
                bankrolls=BankrollSnapshotStore(tmp / "kill" / "bankroll.jsonl"),
                qualifications=QualificationRecordStore(
                    tmp / "kill" / "qualifications.jsonl"
                ),
                safety=SafetyStateStore(tmp / "kill" / "safety.jsonl"),
                audit_log=RiskAuditLog(tmp / "kill" / "risk.jsonl"),
            )
            self.assertEqual(restarted.approve(request(kill)).reason, "kill_switch_active")

            stale = build_risk(tmp / "stale")
            old_snapshot = stale["snapshot"]
            stale["engine"].rebase(
                "50",
                captured_at="2026-01-01T00:05:00Z",
                scheduled_weekly=False,
                drawdown_triggered=True,
            )
            decision = stale["engine"].approve(
                request(stale, bankroll_snapshot_id=old_snapshot.snapshot_id)
            )
            self.assertEqual(decision.reason, "stale_bankroll_snapshot")

    def test_restart_rehydrates_bankroll_approval_and_reservation(self):
        with scratch_directory() as tmp:
            fixture = build_risk(tmp)
            approved = fixture["engine"].approve(request(fixture))
            restarted = RiskEngine(
                policy=fixture["policy"],
                bankrolls=BankrollSnapshotStore(tmp / "bankroll.jsonl"),
                qualifications=QualificationRecordStore(tmp / "qualifications.jsonl"),
                safety=SafetyStateStore(tmp / "safety.jsonl"),
                audit_log=RiskAuditLog(tmp / "risk.jsonl"),
            )
            self.assertEqual(restarted.bankrolls.current(), fixture["snapshot"])
            self.assertEqual(restarted.get_approval(approved.approval_id).approved_unit_tier, "3.0u")
            self.assertEqual(len(restarted.reserved_exposures()), 1)

    def test_policy_hard_laws_reject_redefinition_and_no_daily_cap_exists(self):
        with self.assertRaises(ValueError):
            RiskPolicy(
                stake_tiers=(Decimal("1.0"), Decimal("5.0")),
                max_single_units=Decimal("5.0"),
            )
        with self.assertRaises(ValueError):
            RiskPolicy(unit_fraction=Decimal("0.01"))
        self.assertIsNone(PolicySet().risk.daily_turnover_cap)

    def test_qualification_record_owns_tier_candidate_and_expiry(self):
        with scratch_directory() as tmp:
            fixture = build_risk(tmp / "tier", tier="1.0u")
            mismatch = fixture["engine"].approve(
                request(fixture, expected_tier="3.0u")
            )
            self.assertEqual(mismatch.reason, "caller_tier_mismatch")
            approved = fixture["engine"].approve(request(fixture))
            self.assertTrue(approved.passed)
            self.assertEqual(approved.approved_stake, "2.5")

            missing = fixture["engine"].approve(
                request(fixture, qualification_record_id=digest("9"))
            )
            self.assertEqual(missing.reason, "authority_unavailable")

            wrong = build_risk(tmp / "wrong")
            mismatch = wrong["engine"].approve(
                request(wrong, candidate_hash=digest("8"))
            )
            self.assertEqual(mismatch.reason, "qualification_candidate_mismatch")

            expired = build_risk(
                tmp / "expired", expires_at="2026-01-01T00:10:00Z"
            )
            at_expiry = expired["engine"].approve(
                request(expired, requested_at="2026-01-01T00:10:00Z")
            )
            self.assertEqual(at_expiry.reason, "qualification_expired")

            corrupt = build_risk(tmp / "corrupt")
            path = tmp / "corrupt" / "qualifications.jsonl"
            row = json.loads(path.read_text(encoding="utf-8"))
            row["candidate_id"] = "tampered"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertEqual(
                corrupt["engine"].approve(request(corrupt)).reason,
                "authority_unavailable",
            )


if __name__ == "__main__":
    unittest.main()
