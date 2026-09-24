"""Astra A2: consumed approval is not current reservation authority."""

from __future__ import annotations

import unittest

from genesis.accounting import SettlementKind
from genesis.execution import OrderState
from genesis.ledger import FillRecord, SettlementLedger
from genesis.release_proof import OfflinePaperReleaseProofStore
from genesis.registry import RegistryConflict
from genesis.risk import Exposure, ExposureState

from ._support import scratch_directory
from .test_astra_s1_submission import ACTION, READY, bound_case
from .test_remediation_r6_execution import restart_adapter, restart_risk


def mark_unknown(case):
    return case["risk_fixture"]["engine"].transition_reservation(
        case["risk_decision"].approval_id,
        ExposureState.UNKNOWN,
        occurred_at="2026-01-01T00:15:00Z",
    )


def prove_terminal_release(case, root, state: ExposureState):
    """Supply exact synthetic PAPER evidence; never assert terminality."""

    if state not in {ExposureState.VOID, ExposureState.SETTLED}:
        raise ValueError("proof helper requires a terminal reservation state")
    adapter = case["adapter"]
    current = adapter.get("key-a").state
    if current == OrderState.RISK_APPROVED:
        adapter.transition(
            "key-a", OrderState.SUBMISSION_PENDING,
            occurred_at="2026-01-01T00:14:00Z",
        )
        current = OrderState.SUBMISSION_PENDING
    if current == OrderState.SUBMISSION_PENDING:
        adapter.transition(
            "key-a", OrderState.SUBMISSION_SENT,
            occurred_at="2026-01-01T00:16:00Z",
        )
    adapter.transition(
        "key-a", OrderState.ACK_RECEIVED,
        occurred_at="2026-01-01T00:17:00Z",
    )
    ledger = SettlementLedger(root / "ledger.jsonl")
    ledger.record_fill(FillRecord(
        fill_id="s1-terminal-fill",
        order_id=case["intent"].order_id,
        candidate_decision_hash=case["intent"].candidate_decision_hash,
        side=case["intent"].side,
        odds=case["intent"].odds,
        stake=case["intent"].stake,
        filled_at="2026-01-01T00:18:00Z",
    ))
    adapter.transition(
        "key-a", OrderState.FULLY_MATCHED,
        occurred_at="2026-01-01T00:19:00Z",
    )
    ledger.settle(
        event_id="s1-terminal-head", fill_id="s1-terminal-fill",
        kind=SettlementKind.VOID if state == ExposureState.VOID else SettlementKind.WIN,
        occurred_at="2026-01-01T00:20:00Z",
    )
    adapter.transition(
        "key-a", OrderState.SETTLED,
        occurred_at="2026-01-01T00:21:00Z",
    )
    owner = OfflinePaperReleaseProofStore(
        root / "release-proofs.jsonl",
        risk=case["risk_fixture"]["engine"], execution=adapter, ledger=ledger,
    )
    proof_hash = owner.issue_full_settlement(
        case["intent"].order_id, occurred_at="2026-01-01T00:22:00Z",
    )
    case["risk_fixture"]["engine"].attach_release_proofs(owner)
    released = case["risk_fixture"]["engine"].release_with_proof(
        proof_hash, occurred_at="2026-01-01T00:23:00Z",
    )
    if released.state != state:
        raise AssertionError("proof-derived reservation state differs from fixture request")
    return owner, ledger


class AstraReservationGateTests(unittest.TestCase):
    def test_own_unknown_void_and_settled_block_both_submission_phases(self):
        with scratch_directory() as root:
            for phase in (OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT):
                for state in (ExposureState.UNKNOWN, ExposureState.VOID, ExposureState.SETTLED):
                    with self.subTest(phase=phase.value, reservation=state.value):
                        case = bound_case(root / f"{phase.value}-{state.value}")
                        adapter = case["adapter"]
                        if phase == OrderState.SUBMISSION_SENT:
                            adapter.transition(
                                "key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY
                            )
                        if state == ExposureState.UNKNOWN:
                            mark_unknown(case)
                            action_at = ACTION
                        else:
                            prove_terminal_release(
                                case, root / f"{phase.value}-{state.value}", state,
                            )
                            action_at = "2026-01-01T00:24:00Z"
                        self.assertFalse(
                            case["risk_fixture"]["engine"].approval_still_valid(
                                case["risk_decision"].approval_id, at=action_at,
                                release_fenced=state != ExposureState.UNKNOWN,
                            ),
                            "the exact inactive reservation cannot authorize this approval",
                        )
                        self.assertFalse(
                            adapter.recertify("key-a", at=action_at).passed,
                            "own inactive reservation cannot recertify",
                        )
                        before = len(adapter._audit.records())
                        with self.assertRaises(RegistryConflict):
                            adapter.transition("key-a", phase, occurred_at=action_at)
                        self.assertEqual(len(adapter._audit.records()), before)

    def test_other_unknown_blocks_affected_continuation(self):
        with scratch_directory() as root:
            case = bound_case(root)
            engine = case["risk_fixture"]["engine"]
            engine.record_exposure(
                Exposure("other-unknown", "8" * 64, "1", ExposureState.UNKNOWN),
                recorded_at="2026-01-01T00:15:00Z",
            )
            self.assertFalse(case["adapter"].recertify("key-a", at=ACTION).passed)
            before = len(case["adapter"]._audit.records())
            with self.assertRaises(RegistryConflict):
                case["adapter"].transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at=ACTION
                )
            self.assertEqual(len(case["adapter"]._audit.records()), before)

    def test_missing_or_conflicting_exact_reservation_never_certifies(self):
        with scratch_directory() as root:
            missing = bound_case(root / "missing")
            engine = missing["risk_fixture"]["engine"]
            engine._exposures = lambda _rows: []
            self.assertFalse(
                missing["adapter"].recertify("key-a", at=ACTION).passed,
                "a missing authoritative reservation must fail closed",
            )
            with self.assertRaises(RegistryConflict):
                missing["adapter"].transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at=ACTION
                )

            conflicting = bound_case(root / "conflicting")
            approval_id = conflicting["risk_decision"].approval_id
            conflicting["risk_fixture"]["engine"].record_exposure(
                Exposure(
                    approval_id, "9" * 64, "100", ExposureState.PENDING
                ),
                recorded_at="2026-01-01T00:15:00Z",
            )
            self.assertFalse(
                conflicting["adapter"].recertify("key-a", at=ACTION).passed,
                "a duplicate ID with wrong candidate/liability must fail closed",
            )
            with self.assertRaises(RegistryConflict):
                conflicting["adapter"].transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at=ACTION
                )

    def test_reservation_transition_at_order_transaction_entry_blocks(self):
        with scratch_directory() as root:
            case = bound_case(root)
            adapter = case["adapter"]
            self.assertTrue(adapter.recertify("key-a", at=READY).passed)
            original = adapter._audit.transaction
            changed = False

            def release_before_builder(builder, **kwargs):
                nonlocal changed
                if not changed:
                    changed = True
                    mark_unknown(case)
                return original(builder, **kwargs)

            adapter._audit.transaction = release_before_builder
            before = len(adapter._audit.records())
            with self.assertRaises(RegistryConflict):
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at=ACTION
                )
            self.assertTrue(changed)
            self.assertEqual(len(adapter._audit.records()), before)

    def test_restart_keeps_released_and_unknown_reservations_blocking(self):
        with scratch_directory() as root:
            for state in (ExposureState.UNKNOWN, ExposureState.VOID, ExposureState.SETTLED):
                with self.subTest(reservation=state.value):
                    case_root = root / state.value
                    case = bound_case(case_root)
                    if state == ExposureState.UNKNOWN:
                        mark_unknown(case)
                        action_at = ACTION
                    else:
                        prove_terminal_release(case, case_root, state)
                        action_at = "2026-01-01T00:24:00Z"
                    risk = restart_risk(case_root)
                    replayed = restart_adapter(case_root, risk)
                    if state != ExposureState.UNKNOWN:
                        owner = OfflinePaperReleaseProofStore(
                            case_root / "release-proofs.jsonl", risk=risk,
                            execution=replayed,
                            ledger=SettlementLedger(case_root / "ledger.jsonl"),
                        )
                        risk.attach_release_proofs(owner)
                    self.assertFalse(replayed.recertify("key-a", at=action_at).passed)
                    before = len(replayed._audit.records())
                    with self.assertRaises(RegistryConflict):
                        replayed.transition(
                            "key-a", OrderState.SUBMISSION_PENDING, occurred_at=action_at
                        )
                    self.assertEqual(len(replayed._audit.records()), before)

    def test_valid_reservation_and_later_terminal_release_preserve_history(self):
        with scratch_directory() as root:
            case = bound_case(root)
            adapter = case["adapter"]
            self.assertTrue(adapter.recertify("key-a", at=READY).passed)
            adapter.transition("key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY)
            adapter.transition("key-a", OrderState.SUBMISSION_SENT, occurred_at=ACTION)
            adapter.transition(
                "key-a", OrderState.ACK_RECEIVED, occurred_at="2026-01-01T00:17:00Z"
            )
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(FillRecord(
                fill_id="s1-positive-fill", order_id=case["intent"].order_id,
                candidate_decision_hash=case["intent"].candidate_decision_hash,
                side=case["intent"].side, odds=case["intent"].odds,
                stake=case["intent"].stake, filled_at="2026-01-01T00:17:30Z",
            ))
            adapter.transition(
                "key-a", OrderState.FULLY_MATCHED, occurred_at="2026-01-01T00:18:00Z"
            )
            ledger.settle(
                event_id="s1-positive-head", fill_id="s1-positive-fill",
                kind=SettlementKind.WIN, occurred_at="2026-01-01T00:18:30Z",
            )
            adapter.transition(
                "key-a", OrderState.SETTLED, occurred_at="2026-01-01T00:19:00Z"
            )
            owner = OfflinePaperReleaseProofStore(
                root / "release-proofs.jsonl",
                risk=case["risk_fixture"]["engine"], execution=adapter, ledger=ledger,
            )
            proof_hash = owner.issue_full_settlement(
                case["intent"].order_id, occurred_at="2026-01-01T00:20:00Z",
            )
            case["risk_fixture"]["engine"].attach_release_proofs(owner)
            case["risk_fixture"]["engine"].release_with_proof(
                proof_hash, occurred_at="2026-01-01T00:21:00Z",
            )
            self.assertEqual(case["risk_fixture"]["engine"].reserved_exposures(), ())
            risk = restart_risk(root)
            replayed = restart_adapter(root, risk)
            risk.attach_release_proofs(OfflinePaperReleaseProofStore(
                root / "release-proofs.jsonl", risk=risk, execution=replayed,
                ledger=SettlementLedger(root / "ledger.jsonl"),
            ))
            self.assertEqual(replayed.get("key-a").state, OrderState.SETTLED)
            self.assertEqual(
                sum(row.get("to_state") == OrderState.SUBMISSION_SENT.value
                    for row in replayed._audit.records()),
                1,
            )


if __name__ == "__main__":
    unittest.main()
