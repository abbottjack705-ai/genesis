"""Astra A3: hash-valid incompatible active risk state cannot vanish."""

from __future__ import annotations

import unittest

from genesis.registry import RegistryConflict
from genesis.risk import (
    BankrollSnapshot,
    BankrollSnapshotStore,
    ExposureState,
    RiskAuditLog,
    RiskEngine,
    SafetyStateStore,
)
from genesis.selection import QualificationRecordStore

from ._support import SyntheticQualificationRecordStore as QualificationRecordStore, scratch_directory
from .test_remediation_r5_risk import build_risk, request


def restarted(root, fixture):
    return RiskEngine(
        policy=fixture["policy"],
        bankrolls=BankrollSnapshotStore(root / "bankroll.jsonl"),
        qualifications=QualificationRecordStore(root / "qualifications.jsonl"),
        safety=SafetyStateStore(root / "safety.jsonl"),
        audit_log=RiskAuditLog(root / "risk.jsonl"),
    )


class AstraStrictReplayTests(unittest.TestCase):
    def assert_admission_blocked(self, engine, req):
        try:
            decision = engine.approve(req)
        except RegistryConflict:
            return
        except (KeyError, TypeError, ValueError) as exc:
            self.fail(f"active-state replay escaped as an untyped error: {exc!r}")
        self.assertFalse(decision.passed, "ambiguous active history granted new risk")

    def assert_restart_blocked(self, root, fixture, req):
        try:
            engine = restarted(root, fixture)
        except RegistryConflict:
            return
        self.assert_admission_blocked(engine, req)

    def test_hash_valid_unsupported_active_approval_blocks_existing_and_restart(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            req = request(fixture)
            fixture["audit"].log.append({
                "record_type": "risk_approval_created",
                "schema_version": "unsupported-active-schema",
                "approval_id": "a" * 64,
                "candidate_decision_hash": "b" * 64,
                "approved_liability": "1000",
            })
            self.assertEqual(fixture["audit"].verify(), 1)
            self.assert_admission_blocked(fixture["engine"], req)
            self.assert_restart_blocked(root, fixture, req)
            self.assertEqual(fixture["audit"].verify(), 1)

    def test_unknown_type_missing_schema_and_missing_material_fields_block(self):
        with scratch_directory() as root:
            rows = (
                {"record_type": "new_risk_liability", "schema_version": "risk-exposure-v3",
                 "liability": "1000"},
                {"record_type": "risk_approval_created", "approval_id": "a" * 64,
                 "approved_liability": "1000"},
                {"record_type": "risk_approval_created", "schema_version": "risk-approval-v2",
                 "approval_id": "a" * 64, "approved_liability": "1000"},
                {"record_type": "risk_reservation_transition",
                 "schema_version": "unsupported-reservation", "approval_id": "a" * 64,
                 "from_state": "pending", "to_state": "void"},
            )
            for index, row in enumerate(rows):
                with self.subTest(index=index):
                    case = root / str(index)
                    fixture = build_risk(case)
                    req = request(fixture)
                    fixture["audit"].log.append(row)
                    self.assertEqual(fixture["audit"].verify(), 1)
                    self.assert_admission_blocked(fixture["engine"], req)
                    self.assert_restart_blocked(case, fixture, req)

    def test_unsupported_bankroll_and_safety_heads_cannot_be_skipped(self):
        with scratch_directory() as root:
            for owner in ("bankrolls", "safety"):
                with self.subTest(owner=owner):
                    case = root / owner
                    fixture = build_risk(case)
                    req = request(fixture)
                    if owner == "bankrolls":
                        fixture[owner].log.append({
                            "record_type": "bankroll_snapshot_recorded",
                            "schema_version": "bankroll-snapshot-v3",
                            "bankroll": "10",
                        })
                    else:
                        fixture[owner].log.append({
                            "record_type": "safety_mode_transition",
                            "schema_version": "safety-state-v3",
                            "kill_switch_active": True,
                        })
                    self.assert_admission_blocked(fixture["engine"], req)
                    self.assert_restart_blocked(case, fixture, req)

    def test_invalid_known_transitions_and_missing_owner_fields_block(self):
        with scratch_directory() as root:
            for index, owner in enumerate(("risk", "bankroll", "safety")):
                with self.subTest(owner=owner):
                    case = root / str(index)
                    fixture = build_risk(case)
                    req = request(fixture)
                    if owner == "risk":
                        approval = fixture["engine"].approve(req)
                        self.assertTrue(approval.passed)
                        fixture["audit"].log.append({
                            "record_type": "risk_reservation_transition",
                            "schema_version": "risk-reservation-v2",
                            "approval_id": approval.approval_id,
                            "from_state": "pending",
                            "to_state": "matched",
                            "occurred_at": "2026-01-01T00:11:00Z",
                        })
                        # Use a second candidate request so duplicate-order
                        # protection cannot mask the invalid replay.
                        self.assert_restart_blocked(case, fixture, req)
                        with self.assertRaises(RegistryConflict):
                            fixture["engine"].reserved_exposures()
                    elif owner == "bankroll":
                        wrong = BankrollSnapshot.create(
                            bankroll="10",
                            captured_at="2026-01-01T00:11:00Z",
                            rebase_reason="test",
                            parent_snapshot_id="f" * 64,
                        )
                        fixture["bankrolls"].log.append({
                            "record_type": "bankroll_snapshot_recorded",
                            "schema_version": "bankroll-snapshot-v2",
                            **wrong.to_dict(),
                        })
                        self.assert_admission_blocked(fixture["engine"], req)
                        self.assert_restart_blocked(case, fixture, req)
                    else:
                        fixture["safety"].log.append({
                            "record_type": "safety_mode_transition",
                            "schema_version": "safety-state-v2",
                            "kill_switch_active": False,
                        })
                        self.assert_admission_blocked(fixture["engine"], req)
                        self.assert_restart_blocked(case, fixture, req)

    def test_incompatible_event_arriving_at_transaction_entry_blocks(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            req = request(fixture)
            log = fixture["audit"].log
            original = log.transaction
            inserted = False

            def inject_before_check(builder, **kwargs):
                nonlocal inserted
                if not inserted:
                    inserted = True
                    original(lambda _rows: {
                        "record_type": "risk_approval_created",
                        "schema_version": "unsupported-active-schema",
                        "approval_id": "a" * 64,
                        "candidate_decision_hash": "b" * 64,
                        "approved_liability": "1000",
                    })
                return original(builder, **kwargs)

            log.transaction = inject_before_check
            self.assert_admission_blocked(fixture["engine"], req)
            self.assertTrue(inserted)
            self.assertEqual(fixture["audit"].verify(), 1)

    def test_known_valid_history_still_approves_once(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            decision = fixture["engine"].approve(request(fixture))
            self.assertTrue(decision.passed)
            self.assertEqual(fixture["audit"].verify(), 1)
            self.assertEqual(
                restarted(root, fixture).approve(request(fixture)).reason,
                "duplicate_order_intent",
            )

    def test_consumption_after_expiry_or_release_is_not_valid_history(self):
        with scratch_directory() as root:
            for cause in ("expired", "released"):
                with self.subTest(cause=cause):
                    case = root / cause
                    fixture = build_risk(case)
                    approval = fixture["engine"].approve(request(fixture))
                    self.assertTrue(approval.passed)
                    if cause == "released":
                        fixture["engine"].transition_reservation(
                            approval.approval_id,
                            ExposureState.VOID,
                            occurred_at="2026-01-01T00:15:00Z",
                        )
                    fixture["audit"].log.append({
                        "record_type": "risk_approval_consumed",
                        "schema_version": "risk-approval-v2",
                        "approval_id": approval.approval_id,
                        "candidate_decision_hash": fixture["candidate_hash"],
                        "order_id": "too-late-order",
                        "consumed_at": (
                            "2026-01-01T02:00:00Z"
                            if cause == "expired"
                            else "2026-01-01T00:16:00Z"
                        ),
                    })
                    with self.assertRaises(RegistryConflict):
                        fixture["engine"].reserved_exposures()
                    with self.assertRaises(RegistryConflict):
                        restarted(case, fixture)


if __name__ == "__main__":
    unittest.main()
