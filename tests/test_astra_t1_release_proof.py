"""Synthetic PAPER-only positive and adversarial B3 proof-owner tests.

These are not venue/account reconciliation and do not authorize an adapter,
campaign, shadow or live path.  The tests deliberately construct full PAPER
fill and settlement histories under the existing append-only owners.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from genesis.accounting import BetSide, SettlementKind
from genesis.execution import OrderState
from genesis.ledger import FillRecord, SettlementLedger
from genesis.registry import RegistryConflict
from genesis.release_proof import OfflinePaperReleaseProofStore
from genesis.repro import canonical_json, sha256_bytes

from ._support import scratch_directory
from .test_remediation_r6_execution import build_execution


def _sent(root, *, side: BetSide = BetSide.BACK):
    fixture = build_execution(root, side=side)
    adapter = fixture["adapter"]
    adapter.create_intent(fixture["intent"])
    adapter.bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
    adapter.transition(
        "key-a", OrderState.SUBMISSION_PENDING,
        occurred_at="2026-01-01T00:14:00Z",
    )
    adapter.transition(
        "key-a", OrderState.SUBMISSION_SENT,
        occurred_at="2026-01-01T00:15:00Z",
    )
    return fixture


def _owner(root, fixture, ledger):
    return OfflinePaperReleaseProofStore(
        root / "release-proofs.jsonl",
        risk=fixture["risk_fixture"]["engine"],
        execution=fixture["adapter"], ledger=ledger,
    )


def _forged_owner(root, fixture, ledger, proof, **changes):
    owner = OfflinePaperReleaseProofStore(
        root / "forged-release-proofs.jsonl",
        risk=fixture["risk_fixture"]["engine"],
        execution=fixture["adapter"], ledger=ledger,
    )
    payload = {
        key: value for key, value in proof.items()
        if key not in {"previous_hash", "sequence", "record_hash", "proof_id"}
    }
    payload.update(changes)
    payload["proof_id"] = sha256_bytes(canonical_json(payload))
    return owner, owner.log.append(payload)


def _full_settlement(root, *, side=BetSide.BACK, split=False, void=False):
    fixture = _sent(root, side=side)
    adapter = fixture["adapter"]
    adapter.transition(
        "key-a", OrderState.ACK_RECEIVED,
        occurred_at="2026-01-01T00:15:10Z",
    )
    ledger = SettlementLedger(root / "ledger.jsonl")
    stakes = ("2.50", "5.00") if split else (fixture["intent"].stake,)
    for index, stake in enumerate(stakes, start=1):
        ledger.record_fill(FillRecord(
            fill_id=f"fill-{index}", order_id=fixture["intent"].order_id,
            candidate_decision_hash=fixture["intent"].candidate_decision_hash,
            side=side, odds=fixture["intent"].odds, stake=stake,
            filled_at=f"2026-01-01T00:16:0{index}Z",
        ))
    adapter.transition(
        "key-a", OrderState.FULLY_MATCHED,
        occurred_at="2026-01-01T00:17:00Z",
    )
    for index in range(1, len(stakes) + 1):
        ledger.settle(
            event_id=f"settlement-{index}", fill_id=f"fill-{index}",
            kind=SettlementKind.VOID if void else SettlementKind.WIN,
            occurred_at=f"2026-01-01T00:18:0{index}Z",
        )
    adapter.transition(
        "key-a", OrderState.SETTLED,
        occurred_at="2026-01-01T00:20:00Z",
    )
    return fixture, ledger


class AstraB3ReleaseProofTests(unittest.TestCase):
    def test_forged_issuance_reason_time_and_stale_head_fail_closed(self):
        for case in ("false-reason", "predates-heads", "stale-at-issuance"):
            with self.subTest(case=case), scratch_directory() as root:
                fixture, ledger = _full_settlement(root)
                genuine = _owner(root, fixture, ledger)
                genuine_hash = genuine.issue_full_settlement(
                    fixture["intent"].order_id,
                    occurred_at="2026-01-01T00:21:00Z",
                )
                proof = genuine.validate_current(genuine_hash)
                changes = {}
                if case == "false-reason":
                    changes["release_reason"] = "FILLS_VOID"
                elif case == "predates-heads":
                    changes["occurred_at"] = "2026-01-01T00:17:00Z"
                else:
                    ledger.settle(
                        event_id="already-current-correction", fill_id="fill-1",
                        kind=SettlementKind.LOSS,
                        occurred_at="2026-01-01T00:22:00Z",
                        correction_of="settlement-1",
                    )
                    changes["occurred_at"] = "2026-01-01T00:23:00Z"
                forged, forged_hash = _forged_owner(
                    root, fixture, ledger, proof, **changes,
                )
                with self.assertRaises(RegistryConflict):
                    forged.validate_current(forged_hash)

    def test_full_paper_settlement_issues_exact_replayable_one_time_proof(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root, split=True)
            owner = _owner(root, fixture, ledger)
            order_id = fixture["intent"].order_id
            proof_hash = owner.issue_full_settlement(
                order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            row = owner.validate_current(proof_hash)
            self.assertEqual(row["record_hash"], proof_hash)
            self.assertEqual(row["approval_id"], fixture["risk_decision"].approval_id)
            self.assertEqual(row["candidate_decision_hash"], fixture["intent"].candidate_decision_hash)
            self.assertEqual(row["scope"], "SYNTHETIC_PAPER_ONLY")
            self.assertEqual(row["release_reason"], "FILLS_SETTLED")
            self.assertEqual([item["fill_id"] for item in row["fill_proofs"]], ["fill-1", "fill-2"])
            self.assertEqual(Decimal(row["matched_stake"]), Decimal(fixture["intent"].stake))
            self.assertEqual(
                Decimal(row["matched_liability"]),
                Decimal(fixture["risk_decision"].approved_liability),
            )
            self.assertEqual(
                owner.issue_full_settlement(order_id, occurred_at="2026-01-01T00:22:00Z"),
                proof_hash,
                "an exact retry must not append a second proof",
            )
            self.assertEqual(len(owner.log.records()), 1)
            restarted = _owner(root, fixture, SettlementLedger(root / "ledger.jsonl"))
            self.assertEqual(restarted.validate_current(proof_hash)["record_hash"], proof_hash)

    def test_all_void_heads_still_require_full_match_and_exact_lineage(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root, split=True, void=True)
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            self.assertEqual(owner.validate_current(proof_hash)["release_reason"], "FILLS_VOID")
            self.assertEqual(ledger.total_pnl(), "0.00")

    def test_valid_same_fill_terminal_correction_does_not_reopen_exposure(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root)
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            ledger.settle(
                event_id="settlement-correction", fill_id="fill-1",
                kind=SettlementKind.LOSS,
                occurred_at="2026-01-01T00:22:00Z",
                correction_of="settlement-1",
            )
            self.assertEqual(owner.validate_current(proof_hash)["record_hash"], proof_hash)
            self.assertEqual(
                Decimal(ledger.total_pnl()), -Decimal(fixture["intent"].stake),
            )
            self.assertEqual(len(owner.log.records()), 1)

    def test_late_fill_invalidates_current_release_proof_without_erasing_fact(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root)
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            ledger.record_fill(FillRecord(
                fill_id="late-fill", order_id=fixture["intent"].order_id,
                candidate_decision_hash=fixture["intent"].candidate_decision_hash,
                side=BetSide.BACK, odds=fixture["intent"].odds, stake="0.50",
                filled_at="2026-01-01T00:22:00Z",
            ))
            with self.assertRaises(RegistryConflict):
                owner.validate_current(proof_hash)
            self.assertEqual(ledger.verify(), 3)

    def test_partial_or_unsettled_fill_and_zero_fill_cancel_have_no_proof(self):
        with scratch_directory() as root:
            partial = _sent(root / "partial")
            partial_ledger = SettlementLedger(root / "partial" / "ledger.jsonl")
            partial_ledger.record_fill(FillRecord(
                fill_id="partial", order_id=partial["intent"].order_id,
                candidate_decision_hash=partial["intent"].candidate_decision_hash,
                side=BetSide.BACK, odds=partial["intent"].odds, stake="2.50",
                filled_at="2026-01-01T00:16:00Z",
            ))
            partial["adapter"].transition("key-a", OrderState.ACK_RECEIVED,
                                          occurred_at="2026-01-01T00:16:10Z")
            partial["adapter"].transition("key-a", OrderState.PARTIALLY_MATCHED,
                                          occurred_at="2026-01-01T00:17:00Z")
            with self.assertRaises(RegistryConflict):
                _owner(root / "partial", partial, partial_ledger).issue_full_settlement(
                    partial["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
                )

            missing_head = _sent(root / "missing-head")
            missing_ledger = SettlementLedger(root / "missing-head" / "ledger.jsonl")
            missing_ledger.record_fill(FillRecord(
                fill_id="complete-but-open", order_id=missing_head["intent"].order_id,
                candidate_decision_hash=missing_head["intent"].candidate_decision_hash,
                side=BetSide.BACK, odds=missing_head["intent"].odds,
                stake=missing_head["intent"].stake,
                filled_at="2026-01-01T00:16:00Z",
            ))
            for state, at in (
                (OrderState.ACK_RECEIVED, "2026-01-01T00:16:10Z"),
                (OrderState.FULLY_MATCHED, "2026-01-01T00:17:00Z"),
                (OrderState.SETTLED, "2026-01-01T00:20:00Z"),
            ):
                missing_head["adapter"].transition("key-a", state, occurred_at=at)
            with self.assertRaises(RegistryConflict):
                _owner(root / "missing-head", missing_head, missing_ledger).issue_full_settlement(
                    missing_head["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
                )

            cancelled = _sent(root / "cancelled")
            for state, at in (
                (OrderState.ACK_RECEIVED, "2026-01-01T00:16:10Z"),
                (OrderState.UNMATCHED, "2026-01-01T00:17:00Z"),
                (OrderState.CANCEL_PENDING, "2026-01-01T00:18:00Z"),
                (OrderState.CANCELLED, "2026-01-01T00:20:00Z"),
            ):
                cancelled["adapter"].transition("key-a", state, occurred_at=at)
            with self.assertRaises(RegistryConflict):
                _owner(root / "cancelled", cancelled,
                       SettlementLedger(root / "cancelled" / "ledger.jsonl")).issue_full_settlement(
                    cancelled["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
                )

    def test_worse_lay_price_exceeds_approval_envelope_and_is_rejected(self):
        with scratch_directory() as root:
            fixture = _sent(root, side=BetSide.LAY)
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(FillRecord(
                fill_id="worse-lay", order_id=fixture["intent"].order_id,
                candidate_decision_hash=fixture["intent"].candidate_decision_hash,
                side=BetSide.LAY, odds="3.00", stake=fixture["intent"].stake,
                filled_at="2026-01-01T00:16:00Z",
            ))
            for state, at in (
                (OrderState.ACK_RECEIVED, "2026-01-01T00:16:10Z"),
                (OrderState.FULLY_MATCHED, "2026-01-01T00:17:00Z"),
                (OrderState.SETTLED, "2026-01-01T00:20:00Z"),
            ):
                fixture["adapter"].transition("key-a", state, occurred_at=at)
            ledger.settle(event_id="lay-head", fill_id="worse-lay",
                          kind=SettlementKind.LOSS,
                          occurred_at="2026-01-01T00:18:00Z")
            with self.assertRaises(RegistryConflict):
                _owner(root, fixture, ledger).issue_full_settlement(
                    fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
                )

    def test_semantically_invalid_order_head_fails_closed_on_current_validation(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root)
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            fixture["adapter"]._audit.append({
                "record_type": "order_state_transition",
                "schema_version": "order-event-v2",
                "order_id": fixture["intent"].order_id,
                "from_state": OrderState.SETTLED.value,
                "to_state": OrderState.VOID.value,
                "occurred_at": "2026-01-01T00:22:00Z",
            })
            with self.assertRaises(RegistryConflict):
                owner.validate_current(proof_hash)

    def test_conflicting_duplicate_proof_row_fails_closed(self):
        with scratch_directory() as root:
            fixture, ledger = _full_settlement(root)
            owner = _owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
            )
            original = owner.validate_current(proof_hash)
            duplicate = {
                key: value for key, value in original.items()
                if key not in {"previous_hash", "sequence", "record_hash"}
            }
            owner.log.append(duplicate)
            with self.assertRaises(RegistryConflict):
                owner.validate_current(proof_hash)


if __name__ == "__main__":
    unittest.main()
