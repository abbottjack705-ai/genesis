"""Independent Astra B3 regressions for proof-bound reservation release.

The fixtures are synthetic, offline and PAPER-only.  They do not certify an
operational strategy, adapter, venue reconciliation or campaign.  These tests
deliberately exercise the *old* bare terminal API as an adversarial caller:
an enum and timestamp must never establish that an order cannot still match
or that all of its fills have reached terminal economic heads.
"""

from __future__ import annotations

import unittest

from genesis.accounting import BetSide
from genesis.execution import OrderState
from genesis.ledger import FillRecord, SettlementLedger
from genesis.registry import RegistryConflict
from genesis.risk import ExposureState

from ._support import scratch_directory
from .test_remediation_r6_execution import build_execution, restart_risk


def sent_order(root):
    """Return a genuine durable PAPER send, not a fabricated order state."""

    fixture = build_execution(root)
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


class AstraB3ReleaseTests(unittest.TestCase):
    def test_l01_sent_order_bare_settled_cannot_release_full_envelope(self):
        with scratch_directory() as root:
            fixture = sent_order(root)
            engine = fixture["risk_fixture"]["engine"]
            approval_id = fixture["risk_decision"].approval_id
            with self.assertRaises(
                RegistryConflict,
                msg="SETTLED is a caller assertion, not order/ledger release proof",
            ):
                engine.transition_reservation(
                    approval_id, ExposureState.SETTLED,
                    occurred_at="2026-01-01T00:16:00Z",
                )
            self.assertEqual(
                [item.exposure_id for item in engine.reserved_exposures()],
                [approval_id],
            )
            self.assertEqual(fixture["adapter"].get("key-a").state, OrderState.SUBMISSION_SENT)

    def test_l02_sent_order_bare_void_cannot_release_full_envelope(self):
        with scratch_directory() as root:
            fixture = sent_order(root)
            engine = fixture["risk_fixture"]["engine"]
            approval_id = fixture["risk_decision"].approval_id
            with self.assertRaises(
                RegistryConflict,
                msg="VOID alone does not prove zero fills or no further matchability",
            ):
                engine.transition_reservation(
                    approval_id, ExposureState.VOID,
                    occurred_at="2026-01-01T00:16:00Z",
                )
            self.assertEqual(
                [item.exposure_id for item in engine.reserved_exposures()],
                [approval_id],
            )

    def test_l02_unconsumed_approval_cannot_accept_bare_void_as_proof(self):
        with scratch_directory() as root:
            fixture = build_execution(root)
            engine = fixture["risk_fixture"]["engine"]
            approval_id = fixture["risk_decision"].approval_id
            with self.assertRaises(
                RegistryConflict,
                msg="even never-consumed release needs a replayable proof decision",
            ):
                engine.transition_reservation(
                    approval_id, ExposureState.VOID,
                    occurred_at="2026-01-01T00:12:00Z",
                )
            self.assertEqual(
                [item.exposure_id for item in engine.reserved_exposures()],
                [approval_id],
            )

    def test_l05_one_partial_fill_and_live_remainder_cannot_bare_settle(self):
        with scratch_directory() as root:
            fixture = sent_order(root)
            fixture["adapter"].transition(
                "key-a", OrderState.ACK_RECEIVED,
                occurred_at="2026-01-01T00:15:10Z",
            )
            fixture["adapter"].transition(
                "key-a", OrderState.PARTIALLY_MATCHED,
                occurred_at="2026-01-01T00:15:20Z",
            )
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(
                FillRecord(
                    fill_id="partial-fill-a", order_id=fixture["intent"].order_id,
                    candidate_decision_hash=fixture["intent"].candidate_decision_hash,
                    side=BetSide.BACK, odds="2.00", stake="2.50",
                    filled_at="2026-01-01T00:16:00Z",
                )
            )
            engine = fixture["risk_fixture"]["engine"]
            approval_id = fixture["risk_decision"].approval_id
            with self.assertRaises(
                RegistryConflict,
                msg="one open fragment and matchable remainder hold the full envelope",
            ):
                engine.transition_reservation(
                    approval_id, ExposureState.SETTLED,
                    occurred_at="2026-01-01T00:17:00Z",
                )
            self.assertEqual(
                [item.exposure_id for item in engine.reserved_exposures()],
                [approval_id],
            )

    def test_l04_bare_cancelled_order_does_not_prove_no_further_match(self):
        with scratch_directory() as root:
            fixture = sent_order(root)
            adapter = fixture["adapter"]
            for state, at in (
                (OrderState.ACK_RECEIVED, "2026-01-01T00:15:10Z"),
                (OrderState.UNMATCHED, "2026-01-01T00:15:20Z"),
                (OrderState.CANCEL_PENDING, "2026-01-01T00:15:30Z"),
                (OrderState.CANCELLED, "2026-01-01T00:15:40Z"),
            ):
                adapter.transition("key-a", state, occurred_at=at)
            engine = fixture["risk_fixture"]["engine"]
            approval_id = fixture["risk_decision"].approval_id
            with self.assertRaises(
                RegistryConflict,
                msg="local CANCELLED enum lacks trusted no-more-matchability proof",
            ):
                engine.transition_reservation(
                    approval_id, ExposureState.VOID,
                    occurred_at="2026-01-01T00:16:00Z",
                )
            self.assertEqual(
                [item.exposure_id for item in engine.reserved_exposures()],
                [approval_id],
            )

    def test_l05_terminal_order_enum_without_fill_heads_cannot_release(self):
        with scratch_directory() as root:
            fixture = sent_order(root)
            adapter = fixture["adapter"]
            for state, at in (
                (OrderState.ACK_RECEIVED, "2026-01-01T00:15:10Z"),
                (OrderState.FULLY_MATCHED, "2026-01-01T00:15:20Z"),
                (OrderState.SETTLED, "2026-01-01T00:15:30Z"),
            ):
                adapter.transition("key-a", state, occurred_at=at)
            engine = fixture["risk_fixture"]["engine"]
            approval_id = fixture["risk_decision"].approval_id
            with self.assertRaises(
                RegistryConflict,
                msg="order SETTLED enum cannot stand in for all fill settlement heads",
            ):
                engine.transition_reservation(
                    approval_id, ExposureState.SETTLED,
                    occurred_at="2026-01-01T00:16:00Z",
                )
            self.assertEqual(
                [item.exposure_id for item in engine.reserved_exposures()],
                [approval_id],
            )

    def test_l07_unknown_cannot_be_cleared_by_bare_terminal_label(self):
        with scratch_directory() as root:
            fixture = sent_order(root)
            engine = fixture["risk_fixture"]["engine"]
            approval_id = fixture["risk_decision"].approval_id
            engine.transition_reservation(
                approval_id, ExposureState.UNKNOWN,
                occurred_at="2026-01-01T00:16:00Z",
            )
            with self.assertRaises(
                RegistryConflict,
                msg="UNKNOWN requires exact terminal reconciliation, not a label",
            ):
                engine.transition_reservation(
                    approval_id, ExposureState.SETTLED,
                    occurred_at="2026-01-01T00:17:00Z",
                )
            self.assertEqual(
                [item.state for item in engine.reserved_exposures()],
                [ExposureState.UNKNOWN],
            )

    def test_l11_legacy_v2_terminal_row_cannot_create_spendable_capacity_on_restart(self):
        with scratch_directory() as root:
            fixture = sent_order(root)
            approval_id = fixture["risk_decision"].approval_id
            risk_log = fixture["risk_fixture"]["audit"].log
            # This is an authentic-format historical row, written through the
            # hash-chained append owner.  It is deliberately *not* a proof.
            risk_log.append({
                "record_type": "risk_reservation_transition",
                "schema_version": "risk-reservation-v2",
                "approval_id": approval_id,
                "from_state": ExposureState.PENDING.value,
                "to_state": ExposureState.SETTLED.value,
                "occurred_at": "2026-01-01T00:16:00Z",
            })
            replayed = restart_risk(root)
            self.assertEqual(
                [item.exposure_id for item in replayed.reserved_exposures()],
                [approval_id],
                "a proofless legacy terminal row must not create new capacity",
            )

    def test_l09_restart_before_release_proof_keeps_reservation(self):
        with scratch_directory() as root:
            fixture = sent_order(root)
            approval_id = fixture["risk_decision"].approval_id
            replayed = restart_risk(root)
            self.assertEqual(
                [item.exposure_id for item in replayed.reserved_exposures()],
                [approval_id],
                "a lost response or crash cannot imply settlement",
            )


if __name__ == "__main__":
    unittest.main()
