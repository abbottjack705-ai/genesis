"""Astra B3 risk integration: proof, replay, correction and late facts.

All positives here are deterministic synthetic PAPER settlements.  Nothing in
this file supplies a venue/account reconciliation, real adapter or GO.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from genesis.accounting import BetSide, SettlementKind
from genesis.execution import OrderState
from genesis.ledger import FillRecord, SettlementLedger
from genesis.registry import RegistryConflict, StrategyLifecycle
from genesis.risk import ExposureState, SafetyState

from ._support import scratch_directory
from .test_astra_t1_release_proof import (
    _full_settlement, _owner, _sent,
)
from .test_remediation_r5_risk import digest, qualification, request
from .test_remediation_r6_execution import restart_adapter, restart_risk


def _release_api(engine) -> None:
    # This is intentionally an invariant assertion on audited 27dd, where
    # caller-controlled terminal labels exist but no proof-bound release API.
    if not callable(getattr(engine, "attach_release_proofs", None)):
        raise AssertionError("risk has no trusted release-proof owner binding")
    if not callable(getattr(engine, "release_with_proof", None)):
        raise AssertionError("risk has no proof-bound release action")


def _release_rows(engine):
    return [
        row for row in engine.audit_log.log.records()
        if row.get("record_type") == "risk_reservation_release"
    ]


class AstraB3RiskIntegrationTests(unittest.TestCase):
    def test_exact_proof_can_supersede_legacy_bare_terminal_history(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root)
            engine = fixture["risk_fixture"]["engine"]
            engine.audit_log.log.append({
                "record_type": "risk_reservation_transition",
                "schema_version": "risk-reservation-v2",
                "approval_id": fixture["risk_decision"].approval_id,
                "from_state": ExposureState.PENDING.value,
                "to_state": ExposureState.SETTLED.value,
                "occurred_at": "2026-01-01T00:20:30Z",
            })
            self.assertEqual(
                [item.state for item in engine.reserved_exposures()],
                [ExposureState.UNKNOWN],
            )
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id,
                occurred_at="2026-01-01T00:21:00Z",
            )
            engine.attach_release_proofs(owner)
            self.assertEqual(
                engine.release_with_proof(
                    proof_hash, occurred_at="2026-01-01T00:22:00Z",
                ).state,
                ExposureState.SETTLED,
            )
            self.assertEqual(engine.reserved_exposures(), ())

    def test_full_synthetic_paper_proof_releases_once_with_exact_lineage(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root, split=True)
            engine = fixture["risk_fixture"]["engine"]
            _release_api(engine)
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            engine.attach_release_proofs(owner)
            released = engine.release_with_proof(
                proof_hash, occurred_at="2026-01-01T00:22:00Z",
            )
            self.assertEqual(released.exposure_id, fixture["risk_decision"].approval_id)
            self.assertEqual(released.state, ExposureState.SETTLED)
            self.assertEqual(engine.reserved_exposures(), ())
            rows = _release_rows(engine)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["approval_id"], fixture["risk_decision"].approval_id)
            self.assertEqual(rows[0]["order_id"], fixture["intent"].order_id)
            self.assertEqual(rows[0]["reconciliation_proof_hash"], proof_hash)
            self.assertEqual(set(rows[0]), {
                "record_type", "schema_version", "approval_id",
                "qualification_record_id", "candidate_decision_hash",
                "decision_output_hash", "order_id", "from_state", "to_state",
                "release_reason", "order_head_record_hash", "fill_proofs",
                "reconciliation_proof_hash", "occurred_at",
                "previous_hash", "sequence", "record_hash",
            })
            self.assertEqual(
                rows[0]["qualification_record_id"],
                fixture["risk_fixture"]["qualification"].qualification_record_id,
            )
            self.assertEqual(
                rows[0]["decision_output_hash"],
                fixture["risk_fixture"]["qualification"].decision_output_hash,
            )
            self.assertEqual(
                [item["fill_id"] for item in rows[0]["fill_proofs"]],
                ["fill-1", "fill-2"],
            )
            self.assertEqual(
                engine.release_with_proof(proof_hash, occurred_at="2026-01-01T00:22:00Z"),
                released,
            )
            self.assertEqual(len(_release_rows(engine)), 1)

    def test_restart_without_then_with_proof_owner_is_conservative_then_exact(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root)
            engine = fixture["risk_fixture"]["engine"]
            _release_api(engine)
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            engine.attach_release_proofs(owner)
            engine.release_with_proof(proof_hash, occurred_at="2026-01-01T00:22:00Z")

            restarted_risk = restart_risk(root)
            self.assertEqual(
                [item.exposure_id for item in restarted_risk.reserved_exposures()],
                [fixture["risk_decision"].approval_id],
                "a missing proof owner cannot silently free capacity at startup",
            )
            restarted_adapter = restart_adapter(root, restarted_risk)
            restarted_ledger = SettlementLedger(root / "ledger.jsonl")
            restarted_owner = _owner(
                root,
                {"risk_fixture": {"engine": restarted_risk}, "adapter": restarted_adapter},
                restarted_ledger,
            )
            restarted_risk.attach_release_proofs(restarted_owner)
            self.assertEqual(restarted_risk.reserved_exposures(), ())
            self.assertEqual(restarted_owner.validate_current(proof_hash)["record_hash"], proof_hash)

    def test_late_fill_recharges_or_blocks_new_capacity_after_release(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root)
            engine = fixture["risk_fixture"]["engine"]
            _release_api(engine)
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            engine.attach_release_proofs(owner)
            engine.release_with_proof(proof_hash, occurred_at="2026-01-01T00:22:00Z")
            ledger.record_fill(FillRecord(
                fill_id="late-fill", order_id=fixture["intent"].order_id,
                candidate_decision_hash=fixture["intent"].candidate_decision_hash,
                side=BetSide.BACK, odds=fixture["intent"].odds, stake="0.50",
                filled_at="2026-01-01T00:23:00Z",
            ))
            with self.assertRaises(RegistryConflict):
                owner.validate_current(proof_hash)
            # The factual late fill remains in the ledger.  Neither risk
            # approval nor a restart may treat the old release as free space.
            self.assertEqual(ledger.verify(), 3)
            risk_fixture = fixture["risk_fixture"]
            second = qualification(
                risk_fixture["qualifications"], risk_fixture["policy"],
                candidate_hash=digest("2"),
                contract_hash=risk_fixture["contract"].contract_hash,
                tier="3.0u", candidate_id="second",
            )
            another = dict(risk_fixture)
            another["qualification"] = second
            another["candidate_hash"] = second.candidate_decision_hash
            approvals_before = len([
                row for row in engine.audit_log.log.records()
                if row.get("record_type") == "risk_approval_created"
            ])
            try:
                decision = engine.approve(request(another, requested_at="2026-01-01T00:24:00Z"))
            except RegistryConflict:
                pass
            else:
                self.assertFalse(decision.passed, "invalidated release funded new risk")
            approvals_after = len([
                row for row in engine.audit_log.log.records()
                if row.get("record_type") == "risk_approval_created"
            ])
            self.assertEqual(approvals_after, approvals_before)

    def test_same_fill_correction_keeps_release_valid_and_one_effective_pnl(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root)
            engine = fixture["risk_fixture"]["engine"]
            _release_api(engine)
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            engine.attach_release_proofs(owner)
            engine.release_with_proof(proof_hash, occurred_at="2026-01-01T00:22:00Z")
            ledger.settle(
                event_id="correct-to-loss", fill_id="fill-1", kind=SettlementKind.LOSS,
                occurred_at="2026-01-01T00:23:00Z", correction_of="settlement-1",
            )
            self.assertEqual(owner.validate_current(proof_hash)["record_hash"], proof_hash)
            self.assertEqual(engine.reserved_exposures(), ())
            self.assertEqual(Decimal(ledger.total_pnl()), -Decimal(fixture["intent"].stake))
            self.assertEqual(len(_release_rows(engine)), 1)

    def test_false_or_missing_proof_cannot_release_any_reservation(self):
        with scratch_directory() as root:
            fixture = _sent(root)
            engine = fixture["risk_fixture"]["engine"]
            _release_api(engine)
            owner = _owner(root, fixture, SettlementLedger(root / "ledger.jsonl"))
            engine.attach_release_proofs(owner)
            with self.assertRaises(RegistryConflict):
                engine.release_with_proof(
                    digest("f"), occurred_at="2026-01-01T00:21:00Z",
                )
            self.assertEqual(len(_release_rows(engine)), 0)
            self.assertEqual(
                [item.exposure_id for item in engine.reserved_exposures()],
                [fixture["risk_decision"].approval_id],
            )
            with self.assertRaises(RegistryConflict):
                owner.issue_full_settlement(
                    fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
                )

    def test_post_order_kill_and_strategy_withdrawal_do_not_block_settlement_release(self):
        with scratch_directory() as root:
            fixture = _sent(root)
            engine = fixture["risk_fixture"]["engine"]
            _release_api(engine)
            safety = fixture["risk_fixture"]["safety"]
            current_safety = safety.current()
            safety.append(SafetyState.create(
                kill_switch_active=True, recorded_at="2026-01-01T00:15:20Z",
                reason="post-order-stop", parent_state_id=current_safety.state_id,
            ))
            fixture["risk_fixture"]["strategies"].transition(
                "strategy", "v1", StrategyLifecycle.RETIRED,
                occurred_at="2026-01-01T00:15:30Z",
            )
            adapter = fixture["adapter"]
            adapter.transition("key-a", OrderState.ACK_RECEIVED,
                               occurred_at="2026-01-01T00:15:40Z")
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(FillRecord(
                fill_id="post-kill-fill", order_id=fixture["intent"].order_id,
                candidate_decision_hash=fixture["intent"].candidate_decision_hash,
                side=BetSide.BACK, odds=fixture["intent"].odds,
                stake=fixture["intent"].stake, filled_at="2026-01-01T00:16:00Z",
            ))
            adapter.transition("key-a", OrderState.FULLY_MATCHED,
                               occurred_at="2026-01-01T00:17:00Z")
            ledger.settle(event_id="post-kill-head", fill_id="post-kill-fill",
                          kind=SettlementKind.WIN, occurred_at="2026-01-01T00:18:00Z")
            adapter.transition("key-a", OrderState.SETTLED,
                               occurred_at="2026-01-01T00:20:00Z")
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            engine.attach_release_proofs(owner)
            released = engine.release_with_proof(
                proof_hash, occurred_at="2026-01-01T00:22:00Z",
            )
            self.assertEqual(released.state, ExposureState.SETTLED)
            self.assertEqual(engine.reserved_exposures(), ())
            self.assertTrue(safety.current().kill_switch_active)
            self.assertEqual(
                fixture["risk_fixture"]["strategies"].current_head(
                    "strategy", "v1"
                ).lifecycle,
                StrategyLifecycle.RETIRED,
            )


if __name__ == "__main__":
    unittest.main()
