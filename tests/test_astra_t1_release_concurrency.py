"""Independent Astra B3 release/replay/concurrency closure gates.

Every fixture in this module is deterministic synthetic PAPER evidence.  It
does not supply venue/account reconciliation, an operational adapter, or GO.
The sealed ``27dd525`` baseline intentionally reaches explicit invariant
assertions when the proof-bearing release owner/API is absent; a missing
module is never allowed to become a collection or setup error.
"""

from __future__ import annotations

import importlib
import inspect
import threading
import unittest
from decimal import Decimal

from genesis.accounting import BetSide, SettlementKind
from genesis.execution import OrderState
from genesis.ledger import FillRecord, SettlementLedger
from genesis.registry import RegistryConflict
from genesis.risk import Exposure, ExposureState

from ._support import scratch_directory
from .test_remediation_r5_risk import digest, qualification, request
from .test_remediation_r6_execution import (
    build_execution,
    restart_adapter,
    restart_risk,
)


def _proof_owner(root, fixture, ledger):
    """Return the proof owner or fail as an invariant, never an import error."""

    try:
        module = importlib.import_module("genesis.release_proof")
    except ModuleNotFoundError:
        raise AssertionError(
            "B3 requires a durable proof-bearing synthetic PAPER release owner"
        ) from None
    owner_type = getattr(module, "OfflinePaperReleaseProofStore", None)
    if not callable(owner_type):
        raise AssertionError(
            "B3 requires OfflinePaperReleaseProofStore as the trusted proof owner"
        )
    return owner_type(
        root / "release-proofs.jsonl",
        risk=fixture["risk_fixture"]["engine"],
        execution=fixture["adapter"],
        ledger=ledger,
    )


def _require_method(owner, name):
    method = getattr(owner, name, None)
    if not callable(method):
        raise AssertionError(f"B3 proof owner has no {name} evidence operation")
    return method


def _sent(root):
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


def _fully_settled(root):
    fixture = _sent(root)
    adapter = fixture["adapter"]
    adapter.transition(
        "key-a", OrderState.ACK_RECEIVED,
        occurred_at="2026-01-01T00:15:10Z",
    )
    ledger = SettlementLedger(root / "ledger.jsonl")
    ledger.record_fill(FillRecord(
        fill_id="fill-1",
        order_id=fixture["intent"].order_id,
        candidate_decision_hash=fixture["intent"].candidate_decision_hash,
        side=BetSide.BACK,
        odds=fixture["intent"].odds,
        stake=fixture["intent"].stake,
        filled_at="2026-01-01T00:16:00Z",
    ))
    adapter.transition(
        "key-a", OrderState.FULLY_MATCHED,
        occurred_at="2026-01-01T00:17:00Z",
    )
    ledger.settle(
        event_id="settlement-1",
        fill_id="fill-1",
        kind=SettlementKind.WIN,
        occurred_at="2026-01-01T00:18:00Z",
    )
    adapter.transition(
        "key-a", OrderState.SETTLED,
        occurred_at="2026-01-01T00:20:00Z",
    )
    return fixture, ledger


def _new_request(risk_fixture, *, marker, requested_at):
    kwargs = {
        "candidate_hash": digest(marker),
        "tier": "3.0u",
        "candidate_id": f"release-race-{marker}",
    }
    if "contract_hash" in inspect.signature(qualification).parameters:
        kwargs["contract_hash"] = risk_fixture["contract"].contract_hash
    record = qualification(
        risk_fixture["qualifications"], risk_fixture["policy"], **kwargs,
    )
    candidate_fixture = dict(risk_fixture)
    candidate_fixture["qualification"] = record
    candidate_fixture["candidate_hash"] = record.candidate_decision_hash
    return request(candidate_fixture, requested_at=requested_at)


def _release_rows(engine):
    return [
        row for row in engine.audit_log.log.records()
        if row.get("record_type") == "risk_reservation_release"
    ]


def _approval_rows(engine):
    return [
        row for row in engine.audit_log.log.records()
        if row.get("record_type") == "risk_approval_created"
    ]


def _open_liability(engine):
    return sum(
        (item.liability_amount for item in engine.reserved_exposures()),
        Decimal("0"),
    )


class AstraB3ReleaseConcurrencyTests(unittest.TestCase):
    def test_unconsumed_approval_voids_once_and_replays_without_order(self):
        """L03 positive: no intent/order/fill is exact evidence of no exposure."""

        with scratch_directory() as root:
            fixture = build_execution(root)
            ledger = SettlementLedger(root / "ledger.jsonl")
            owner = _proof_owner(root, fixture, ledger)
            issue = _require_method(owner, "issue_unconsumed_approval")
            proof_hash = issue(
                fixture["risk_decision"].approval_id,
                occurred_at="2026-01-01T00:13:00Z",
            )
            engine = fixture["risk_fixture"]["engine"]
            engine.attach_release_proofs(owner)
            released = engine.release_with_proof(
                proof_hash, occurred_at="2026-01-01T00:14:00Z",
            )
            self.assertEqual(released.state, ExposureState.VOID)
            self.assertEqual(engine.reserved_exposures(), ())
            row = _release_rows(engine)[0]
            self.assertIsNone(row["order_id"])
            self.assertIsNone(row["order_head_record_hash"])
            self.assertEqual(row["fill_proofs"], [])

            restarted_risk = restart_risk(root)
            restarted_adapter = restart_adapter(root, restarted_risk)
            restarted_owner = _proof_owner(
                root,
                {"risk_fixture": {"engine": restarted_risk},
                 "adapter": restarted_adapter},
                SettlementLedger(root / "ledger.jsonl"),
            )
            restarted_risk.attach_release_proofs(restarted_owner)
            self.assertEqual(restarted_risk.reserved_exposures(), ())
            self.assertEqual(
                restarted_risk.release_with_proof(
                    proof_hash, occurred_at="2026-01-01T00:14:00Z",
                ).state,
                ExposureState.VOID,
            )
            self.assertEqual(len(_release_rows(restarted_risk)), 1)

    def test_proven_synthetic_paper_unmatched_cancellation_releases_once(self):
        """L04 positive: durable zero-fill/no-matchability proof frees capacity."""

        with scratch_directory() as root:
            fixture = _sent(root)
            adapter = fixture["adapter"]
            adapter.transition(
                "key-a", OrderState.ACK_RECEIVED,
                occurred_at="2026-01-01T00:15:10Z",
            )
            adapter.transition(
                "key-a", OrderState.UNMATCHED,
                occurred_at="2026-01-01T00:16:00Z",
            )
            adapter.transition(
                "key-a", OrderState.CANCEL_PENDING,
                occurred_at="2026-01-01T00:17:00Z",
            )
            adapter.transition(
                "key-a", OrderState.CANCELLED,
                occurred_at="2026-01-01T00:18:00Z",
            )
            ledger = SettlementLedger(root / "ledger.jsonl")
            owner = _proof_owner(root, fixture, ledger)
            issue = _require_method(owner, "issue_unmatched_cancellation")
            proof_hash = issue(
                fixture["intent"].order_id,
                occurred_at="2026-01-01T00:19:00Z",
            )
            proof = owner.validate_current(proof_hash)
            self.assertEqual(proof["scope"], "SYNTHETIC_PAPER_ONLY")
            self.assertEqual(proof["release_reason"], "UNMATCHED_CANCEL_CONFIRMED")
            self.assertEqual(proof["approval_id"], fixture["risk_decision"].approval_id)
            self.assertEqual(proof["order_id"], fixture["intent"].order_id)
            self.assertEqual(proof["fill_proofs"], [])
            self.assertTrue(proof["order_head_record_hash"])
            self.assertTrue(proof["no_more_matchability_basis"])
            self.assertEqual(ledger.verify(), 0)

            engine = fixture["risk_fixture"]["engine"]
            engine.attach_release_proofs(owner)
            released = engine.release_with_proof(
                proof_hash, occurred_at="2026-01-01T00:20:00Z",
            )
            self.assertEqual(released.state, ExposureState.VOID)
            self.assertEqual(engine.reserved_exposures(), ())
            self.assertEqual(len(_release_rows(engine)), 1)

    def test_partial_fill_with_live_remainder_conserves_full_reservation(self):
        """L05/R05: a fragment never shrinks or duplicates its order envelope."""

        with scratch_directory() as root:
            fixture = _sent(root)
            adapter = fixture["adapter"]
            adapter.transition(
                "key-a", OrderState.ACK_RECEIVED,
                occurred_at="2026-01-01T00:15:10Z",
            )
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(FillRecord(
                fill_id="partial-fill",
                order_id=fixture["intent"].order_id,
                candidate_decision_hash=fixture["intent"].candidate_decision_hash,
                side=BetSide.BACK,
                odds=fixture["intent"].odds,
                stake="2.50",
                filled_at="2026-01-01T00:16:00Z",
            ))
            adapter.transition(
                "key-a", OrderState.PARTIALLY_MATCHED,
                occurred_at="2026-01-01T00:17:00Z",
            )
            owner = _proof_owner(root, fixture, ledger)
            with self.assertRaises(RegistryConflict):
                owner.issue_full_settlement(
                    fixture["intent"].order_id,
                    occurred_at="2026-01-01T00:18:00Z",
                )
            engine = fixture["risk_fixture"]["engine"]
            engine.attach_release_proofs(owner)
            engine.record_exposure(
                Exposure(
                    "independent-at-boundary", digest("f"), "52.5",
                    ExposureState.MATCHED,
                ),
                recorded_at="2026-01-01T00:18:10Z",
            )
            reservations = {
                item.exposure_id: item for item in engine.reserved_exposures()
            }
            approval_id = fixture["risk_decision"].approval_id
            self.assertEqual(
                reservations[approval_id].liability_amount,
                Decimal(fixture["risk_decision"].approved_liability),
                "a live remainder must retain the complete approval envelope",
            )
            self.assertEqual(_open_liability(engine), Decimal("60"))
            self.assertEqual(len(_release_rows(engine)), 0)

            next_request = _new_request(
                fixture["risk_fixture"], marker="2",
                requested_at="2026-01-01T00:19:00Z",
            )
            decision = engine.approve(next_request)
            self.assertFalse(decision.passed)
            self.assertEqual(decision.reason, "open_liability_limit")
            self.assertEqual(_open_liability(engine), Decimal("60"))

    def test_partial_fill_cancelled_remainder_releases_only_after_terminal_head(self):
        """L05 positive: terminal fill plus proven cancelled remainder closes all."""

        with scratch_directory() as root:
            fixture = _sent(root)
            adapter = fixture["adapter"]
            adapter.transition(
                "key-a", OrderState.ACK_RECEIVED,
                occurred_at="2026-01-01T00:15:10Z",
            )
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(FillRecord(
                fill_id="partial-terminal", order_id=fixture["intent"].order_id,
                candidate_decision_hash=fixture["intent"].candidate_decision_hash,
                side=BetSide.BACK, odds=fixture["intent"].odds, stake="2.50",
                filled_at="2026-01-01T00:16:00Z",
            ))
            adapter.transition(
                "key-a", OrderState.PARTIALLY_MATCHED,
                occurred_at="2026-01-01T00:17:00Z",
            )
            ledger.settle(
                event_id="partial-terminal-head", fill_id="partial-terminal",
                kind=SettlementKind.WIN, occurred_at="2026-01-01T00:18:00Z",
            )
            adapter.transition(
                "key-a", OrderState.CANCEL_PENDING,
                occurred_at="2026-01-01T00:19:00Z",
            )
            adapter.transition(
                "key-a", OrderState.CANCELLED,
                occurred_at="2026-01-01T00:20:00Z",
            )
            owner = _proof_owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id,
                occurred_at="2026-01-01T00:21:00Z",
            )
            proof = owner.validate_current(proof_hash)
            self.assertEqual(proof["release_reason"], "FILLS_SETTLED")
            self.assertEqual(proof["matched_stake"], "2.50")
            self.assertEqual(
                proof["no_more_matchability_basis"],
                "SYNTHETIC_PAPER_CANCELLED_REMAINDER_COMPLETE",
            )
            engine = fixture["risk_fixture"]["engine"]
            engine.attach_release_proofs(owner)
            self.assertEqual(
                engine.release_with_proof(
                    proof_hash, occurred_at="2026-01-01T00:22:00Z",
                ).state,
                ExposureState.SETTLED,
            )
            self.assertEqual(engine.reserved_exposures(), ())

            restarted_risk = restart_risk(root)
            restarted_adapter = restart_adapter(root, restarted_risk)
            restarted_owner = _proof_owner(
                root,
                {"risk_fixture": {"engine": restarted_risk},
                 "adapter": restarted_adapter},
                SettlementLedger(root / "ledger.jsonl"),
            )
            restarted_risk.attach_release_proofs(restarted_owner)
            self.assertEqual(restarted_risk.reserved_exposures(), ())
            self.assertEqual(restarted_owner.validate_current(proof_hash)["record_hash"], proof_hash)

    def test_actual_void_order_allows_later_terminal_same_fill_correction(self):
        """VOID is issuance truth; lawful terminal correction changes only P/L."""

        with scratch_directory() as root:
            fixture = _sent(root)
            adapter = fixture["adapter"]
            adapter.transition(
                "key-a", OrderState.ACK_RECEIVED,
                occurred_at="2026-01-01T00:15:10Z",
            )
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(FillRecord(
                fill_id="void-fill", order_id=fixture["intent"].order_id,
                candidate_decision_hash=fixture["intent"].candidate_decision_hash,
                side=BetSide.BACK, odds=fixture["intent"].odds,
                stake=fixture["intent"].stake,
                filled_at="2026-01-01T00:16:00Z",
            ))
            adapter.transition(
                "key-a", OrderState.FULLY_MATCHED,
                occurred_at="2026-01-01T00:17:00Z",
            )
            ledger.settle(
                event_id="void-head", fill_id="void-fill",
                kind=SettlementKind.VOID, occurred_at="2026-01-01T00:18:00Z",
            )
            adapter.transition(
                "key-a", OrderState.VOID,
                occurred_at="2026-01-01T00:20:00Z",
            )
            owner = _proof_owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id,
                occurred_at="2026-01-01T00:21:00Z",
            )
            engine = fixture["risk_fixture"]["engine"]
            engine.attach_release_proofs(owner)
            self.assertEqual(
                engine.release_with_proof(
                    proof_hash, occurred_at="2026-01-01T00:22:00Z",
                ).state,
                ExposureState.VOID,
            )
            ledger.settle(
                event_id="void-to-loss", fill_id="void-fill",
                kind=SettlementKind.LOSS, occurred_at="2026-01-01T00:23:00Z",
                correction_of="void-head",
            )
            self.assertEqual(owner.validate_current(proof_hash)["record_hash"], proof_hash)
            self.assertEqual(engine.reserved_exposures(), ())
            self.assertEqual(Decimal(ledger.total_pnl()), -Decimal(fixture["intent"].stake))
            self.assertEqual(len(_release_rows(engine)), 1)

    def test_durable_proof_then_crash_without_release_restarts_and_retries(self):
        """L09: proof alone releases nothing; restart may verify and append once."""

        with scratch_directory() as root:
            fixture, ledger = _fully_settled(root)
            owner = _proof_owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id,
                occurred_at="2026-01-01T00:21:00Z",
            )
            engine = fixture["risk_fixture"]["engine"]
            self.assertEqual(len(owner.log.records()), 1)
            self.assertEqual(len(_release_rows(engine)), 0)
            self.assertEqual(
                _open_liability(engine),
                Decimal(fixture["risk_decision"].approved_liability),
                "durable evidence without the final risk append cannot free capacity",
            )

            restarted_risk = restart_risk(root)
            self.assertEqual(
                _open_liability(restarted_risk),
                Decimal(fixture["risk_decision"].approved_liability),
            )
            restarted_adapter = restart_adapter(root, restarted_risk)
            restarted_fixture = {
                "risk_fixture": {"engine": restarted_risk},
                "adapter": restarted_adapter,
            }
            restarted_owner = _proof_owner(
                root, restarted_fixture, SettlementLedger(root / "ledger.jsonl"),
            )
            restarted_risk.attach_release_proofs(restarted_owner)
            released = restarted_risk.release_with_proof(
                proof_hash, occurred_at="2026-01-01T00:22:00Z",
            )
            self.assertEqual(released.state, ExposureState.SETTLED)
            self.assertEqual(restarted_risk.reserved_exposures(), ())
            self.assertEqual(len(_release_rows(restarted_risk)), 1)

    def test_duplicate_release_replay_is_exactly_once_across_restart(self):
        """L08/L09: response loss and exact retry never append/free twice."""

        with scratch_directory() as root:
            fixture, ledger = _fully_settled(root)
            owner = _proof_owner(root, fixture, ledger)
            proof_hash = owner.issue_full_settlement(
                fixture["intent"].order_id,
                occurred_at="2026-01-01T00:21:00Z",
            )
            engine = fixture["risk_fixture"]["engine"]
            engine.attach_release_proofs(owner)
            original_transaction = engine.audit_log.log.transaction

            def lose_response_after_fsync(build_record, *, read_locks=()):
                appended = original_transaction(
                    build_record, read_locks=read_locks,
                )
                if appended is not None:
                    raise RuntimeError(
                        "simulated response loss after durable release append"
                    )
                return appended

            engine.audit_log.log.transaction = lose_response_after_fsync
            try:
                with self.assertRaisesRegex(
                    RuntimeError, "response loss after durable release append",
                ):
                    engine.release_with_proof(
                        proof_hash, occurred_at="2026-01-01T00:22:00Z",
                    )
            finally:
                engine.audit_log.log.transaction = original_transaction
            self.assertEqual(len(_release_rows(engine)), 1)

            restarted_risk = restart_risk(root)
            restarted_adapter = restart_adapter(root, restarted_risk)
            restarted_fixture = {
                "risk_fixture": {"engine": restarted_risk},
                "adapter": restarted_adapter,
            }
            restarted_owner = _proof_owner(
                root, restarted_fixture, SettlementLedger(root / "ledger.jsonl"),
            )
            restarted_risk.attach_release_proofs(restarted_owner)
            replayed = restarted_risk.release_with_proof(
                proof_hash, occurred_at="2026-01-01T00:22:00Z",
            )
            self.assertEqual(replayed.state, ExposureState.SETTLED)
            self.assertEqual(
                restarted_risk.release_with_proof(
                    proof_hash, occurred_at="2026-01-01T00:22:00Z",
                ),
                replayed,
            )
            self.assertEqual(restarted_risk.reserved_exposures(), ())
            self.assertEqual(len(_release_rows(restarted_risk)), 1)

    def test_concurrent_release_and_new_risk_have_only_safe_serial_outcomes(self):
        """C02: release/admission share one fence and cannot mint over-cap risk."""

        for release_first in (False, True):
            with self.subTest(release_first=release_first):
                with scratch_directory() as root:
                    fixture, ledger = _fully_settled(root)
                    engine = fixture["risk_fixture"]["engine"]
                    engine.record_exposure(
                        Exposure(
                            "independent-at-boundary", digest("f"), "52.5",
                            ExposureState.MATCHED,
                        ),
                        recorded_at="2026-01-01T00:20:10Z",
                    )
                    owner = _proof_owner(root, fixture, ledger)
                    proof_hash = owner.issue_full_settlement(
                        fixture["intent"].order_id,
                        occurred_at="2026-01-01T00:21:00Z",
                    )
                    engine.attach_release_proofs(owner)
                    next_request = _new_request(
                        fixture["risk_fixture"], marker="3",
                        requested_at="2026-01-01T00:22:00Z",
                    )

                    entered = threading.Event()
                    proceed = threading.Event()
                    second_entered_transaction = threading.Event()
                    second_finished = threading.Event()
                    outcomes = {}

                    original_transaction = engine.audit_log.log.transaction

                    def observe_second_transaction(build_record, *, read_locks=()):
                        if threading.current_thread().name.endswith("-second"):
                            second_entered_transaction.set()
                        return original_transaction(
                            build_record, read_locks=read_locks,
                        )

                    engine.audit_log.log.transaction = observe_second_transaction

                    def approve_worker():
                        try:
                            outcomes["approval"] = engine.approve(next_request)
                        except BaseException as exc:  # surfaced in the test thread
                            outcomes["approval_error"] = exc
                        finally:
                            if threading.current_thread().name.endswith("-second"):
                                second_finished.set()

                    def release_worker():
                        try:
                            outcomes["release"] = engine.release_with_proof(
                                proof_hash, occurred_at="2026-01-01T00:23:00Z",
                            )
                        except BaseException as exc:  # surfaced in the test thread
                            outcomes["release_error"] = exc
                        finally:
                            if threading.current_thread().name.endswith("-second"):
                                second_finished.set()

                    if release_first:
                        original_validate = owner.validate_current_locked
                        paused = {"done": False}

                        def pause_release(*args, **kwargs):
                            value = original_validate(*args, **kwargs)
                            if (threading.current_thread().name == "b3-release-first"
                                    and not paused["done"]):
                                paused["done"] = True
                                entered.set()
                                if not proceed.wait(10):
                                    raise AssertionError("release race gate timed out")
                            return value

                        owner.validate_current_locked = pause_release
                        first = threading.Thread(
                            target=release_worker, name="b3-release-first",
                        )
                        second = threading.Thread(
                            target=approve_worker, name="b3-approval-second",
                        )
                    else:
                        original_exposures = engine._exposures
                        paused = {"done": False}

                        def pause_approval(rows, *, release_fenced=False):
                            value = original_exposures(
                                rows, release_fenced=release_fenced,
                            )
                            if (threading.current_thread().name == "b3-approval-first"
                                    and release_fenced and not paused["done"]):
                                paused["done"] = True
                                entered.set()
                                if not proceed.wait(10):
                                    raise AssertionError("approval race gate timed out")
                            return value

                        engine._exposures = pause_approval
                        first = threading.Thread(
                            target=approve_worker, name="b3-approval-first",
                        )
                        second = threading.Thread(
                            target=release_worker, name="b3-release-second",
                        )

                    first.start()
                    self.assertTrue(entered.wait(10), "first operation never held its fence")
                    second.start()
                    self.assertTrue(
                        second_entered_transaction.wait(10),
                        "second operation never attempted the contended risk transaction",
                    )
                    self.assertFalse(
                        second_finished.wait(0.2),
                        "second operation crossed the risk fence before the first committed",
                    )
                    proceed.set()
                    first.join(15)
                    second.join(15)
                    self.assertFalse(first.is_alive(), "first operation deadlocked")
                    self.assertFalse(second.is_alive(), "second operation deadlocked")
                    self.assertNotIn("approval_error", outcomes)
                    self.assertNotIn("release_error", outcomes)
                    self.assertEqual(outcomes["release"].state, ExposureState.SETTLED)
                    self.assertEqual(len(_release_rows(engine)), 1)

                    decision = outcomes["approval"]
                    risk_rows = engine.audit_log.log.records()
                    release_row = _release_rows(engine)[0]
                    competing_approvals = [
                        row for row in risk_rows
                        if row.get("record_type") == "risk_approval_created"
                        and row.get("candidate_decision_hash")
                        == next_request.candidate_decision_hash
                    ]
                    if release_first:
                        self.assertTrue(decision.passed)
                        self.assertEqual(_open_liability(engine), Decimal("60"))
                        self.assertEqual(len(_approval_rows(engine)), 2)
                        self.assertEqual(len(competing_approvals), 1)
                        self.assertLess(
                            release_row["sequence"],
                            competing_approvals[0]["sequence"],
                            "a passing approval must serialize after the capacity release",
                        )
                    else:
                        self.assertFalse(decision.passed)
                        self.assertEqual(decision.reason, "open_liability_limit")
                        self.assertEqual(_open_liability(engine), Decimal("52.5"))
                        self.assertEqual(len(_approval_rows(engine)), 1)
                        self.assertEqual(competing_approvals, [])
                    self.assertLessEqual(_open_liability(engine), Decimal("60"))

    def test_concurrent_owner_attach_and_admission_are_fully_serialized(self):
        """A None-to-owner change cannot validate release facts without locks."""

        for attach_first in (False, True):
            with self.subTest(attach_first=attach_first), scratch_directory() as root:
                fixture, ledger = _fully_settled(root)
                original_owner = _proof_owner(root, fixture, ledger)
                proof_hash = original_owner.issue_full_settlement(
                    fixture["intent"].order_id,
                    occurred_at="2026-01-01T00:21:00Z",
                )
                original_engine = fixture["risk_fixture"]["engine"]
                original_engine.attach_release_proofs(original_owner)
                original_engine.release_with_proof(
                    proof_hash, occurred_at="2026-01-01T00:22:00Z",
                )

                engine = restart_risk(root)
                adapter = restart_adapter(root, engine)
                owner = _proof_owner(
                    root,
                    {"risk_fixture": {"engine": engine}, "adapter": adapter},
                    SettlementLedger(root / "ledger.jsonl"),
                )
                restarted_fixture = dict(fixture["risk_fixture"])
                restarted_fixture["engine"] = engine
                next_request = _new_request(
                    restarted_fixture, marker="4",
                    requested_at="2026-01-01T00:23:00Z",
                )
                entered = threading.Event()
                proceed = threading.Event()
                second_entered = threading.Event()
                second_finished = threading.Event()
                outcomes = {}
                original_transaction = engine.audit_log.log.transaction

                def observe(build_record, *, read_locks=()):
                    if threading.current_thread().name.endswith("-second"):
                        second_entered.set()
                    return original_transaction(build_record, read_locks=read_locks)

                engine.audit_log.log.transaction = observe

                def attach_worker():
                    try:
                        engine.attach_release_proofs(owner)
                        outcomes["attached"] = True
                    except BaseException as exc:
                        outcomes["attach_error"] = exc
                    finally:
                        if threading.current_thread().name.endswith("-second"):
                            second_finished.set()

                def approve_worker():
                    try:
                        outcomes["approval"] = engine.approve(next_request)
                    except BaseException as exc:
                        outcomes["approval_error"] = exc
                    finally:
                        if threading.current_thread().name.endswith("-second"):
                            second_finished.set()

                if attach_first:
                    original_validate = owner.validate_current_locked
                    paused = {"done": False}

                    def pause_attach(*args, **kwargs):
                        value = original_validate(*args, **kwargs)
                        if (threading.current_thread().name == "attach-first"
                                and not paused["done"]):
                            paused["done"] = True
                            entered.set()
                            if not proceed.wait(10):
                                raise AssertionError("attach race gate timed out")
                        return value

                    owner.validate_current_locked = pause_attach
                    first = threading.Thread(target=attach_worker, name="attach-first")
                    second = threading.Thread(target=approve_worker, name="approve-second")
                else:
                    original_exposures = engine._exposures
                    paused = {"done": False}

                    def pause_approve(rows, *, release_fenced=False):
                        value = original_exposures(rows, release_fenced=release_fenced)
                        if (threading.current_thread().name == "approve-first"
                                and release_fenced and not paused["done"]):
                            paused["done"] = True
                            entered.set()
                            if not proceed.wait(10):
                                raise AssertionError("approval/attach gate timed out")
                        return value

                    engine._exposures = pause_approve
                    first = threading.Thread(target=approve_worker, name="approve-first")
                    second = threading.Thread(target=attach_worker, name="attach-second")

                first.start()
                self.assertTrue(entered.wait(10))
                second.start()
                self.assertTrue(second_entered.wait(10))
                self.assertFalse(second_finished.wait(0.2))
                proceed.set()
                first.join(15)
                second.join(15)
                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                self.assertNotIn("approval_error", outcomes)
                self.assertNotIn("attach_error", outcomes)
                self.assertTrue(outcomes["attached"])
                self.assertIs(engine.release_proofs, owner)
                if attach_first:
                    self.assertTrue(outcomes["approval"].passed)
                else:
                    self.assertFalse(outcomes["approval"].passed)
                    self.assertEqual(
                        outcomes["approval"].reason,
                        "unknown_exposure_blocks_new_risk",
                    )


if __name__ == "__main__":
    unittest.main()
