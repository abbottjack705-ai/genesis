from __future__ import annotations

import json
import unittest
from decimal import Decimal

from genesis.accounting import BetSide
from genesis.policy import PolicySet, RiskPolicy
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
from ._support import scratch_directory


def digest(character: str) -> str:
    return character * 64


def qualification(
    store: QualificationRecordStore,
    policy: PolicySet,
    *,
    candidate_hash: str,
    tier: str,
    candidate_id: str = "candidate",
    expires_at: str = "2026-01-01T01:00:00Z",
) -> QualificationRecord:
    return store.append(
        QualificationRecord.create(
            candidate_id=candidate_id,
            candidate_decision_hash=candidate_hash,
            strategy_id="strategy",
            strategy_version="v1",
            strategy_decision_contract_hash=digest("a"),
            approved_tier=tier,
            comparability_group_id="group",
            active_policy_digest=policy.digest,
            market_capability_id="capability-v1",
            decision_at="2026-01-01T00:00:00Z",
            evaluated_at="2026-01-01T00:01:00Z",
            expires_at=expires_at,
            gate_results_digest=digest("b"),
        )
    )


def build_risk(
    tmp,
    *,
    tier: str = "3.0u",
    candidate_hash: str = digest("1"),
    bankroll: str = "100",
    expires_at: str = "2026-01-01T01:00:00Z",
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
        reason="initial-safe",
    )
    safety.append(safety_state)
    qualifications = QualificationRecordStore(tmp / "qualifications.jsonl")
    record = qualification(
        qualifications,
        policy,
        candidate_hash=candidate_hash,
        tier=tier,
        expires_at=expires_at,
    )
    audit = RiskAuditLog(tmp / "risk.jsonl")
    engine = RiskEngine(
        policy=policy,
        bankrolls=bankrolls,
        qualifications=qualifications,
        safety=safety,
        audit_log=audit,
    )
    return {
        "policy": policy,
        "bankrolls": bankrolls,
        "snapshot": snapshot,
        "safety": safety,
        "qualifications": qualifications,
        "qualification": record,
        "audit": audit,
        "engine": engine,
        "candidate_hash": candidate_hash,
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
                    self.assertEqual(decision.reason, "invalid_qualification_tier")

    def test_lay_liability_and_caller_mismatch_checks_are_decimal_exact(self):
        with scratch_directory() as tmp:
            fixture = build_risk(tmp, tier="2.0u")
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
