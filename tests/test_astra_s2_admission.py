"""Astra A7: admission must use one current, fenced authority head."""

from __future__ import annotations

import multiprocessing
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import genesis

from genesis.accounting import BetSide
from genesis.execution import ModeStateStore
from genesis.policy import PolicySet
from genesis.registry import StrategyRegistry
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
from genesis.selection import QualificationRecordStore

from ._support import SyntheticQualificationRecordStore as QualificationRecordStore, scratch_directory
from .test_remediation_r5_risk import build_risk, digest, qualification, request


def _restarted(root: Path) -> RiskEngine:
    return RiskEngine(
        policy=PolicySet(),
        bankrolls=BankrollSnapshotStore(root / "bankroll.jsonl"),
        qualifications=QualificationRecordStore(root / "qualifications.jsonl"),
        safety=SafetyStateStore(root / "safety.jsonl"),
        audit_log=RiskAuditLog(root / "risk.jsonl"),
        strategies=StrategyRegistry(root / "strategies.jsonl"),
        modes=ModeStateStore(root / "mode.jsonl"),
        action_clock=lambda requested_at: requested_at,
    )


def _isolated_worker_authority(source_root):
    # Windows spawn imports this test module from the working repository before
    # restoring the parent test runner's sys.path. Explicitly select the
    # checkout under audit inside each child, not the working source.
    for name in tuple(sys.modules):
        if name == "genesis" or name.startswith("genesis."):
            del sys.modules[name]
    sys.path.insert(0, str(source_root))
    from genesis.policy import PolicySet as WorkerPolicySet
    from genesis.risk import (
        BankrollSnapshot as WorkerBankrollSnapshot,
        BankrollSnapshotStore as WorkerBankrollStore,
        RiskAuditLog as WorkerRiskAuditLog,
        RiskEngine as WorkerRiskEngine,
        SafetyState as WorkerSafetyState,
        SafetyStateStore as WorkerSafetyStore,
    )
    from genesis.selection import QualificationRecordStore as WorkerQualifications
    from genesis.registry import StrategyRegistry as WorkerStrategyRegistry
    from genesis.execution import ModeStateStore as WorkerModeStateStore

    class SyntheticWorkerQualifications(WorkerQualifications):
        def _require_separate_approval(self, reference, *, binding_hash, decision_at):
            if not reference.startswith("synthetic-test-only-"):
                raise ValueError("fixture does not recognize output approval")

    return (WorkerPolicySet, WorkerBankrollSnapshot, WorkerBankrollStore,
            WorkerRiskAuditLog, WorkerRiskEngine, WorkerSafetyState,
            WorkerSafetyStore, SyntheticWorkerQualifications,
            WorkerStrategyRegistry, WorkerModeStateStore)


def _worker_engine(root, source_root):
    policy, _, bankrolls, audit, engine, _, safety, qualifications, strategies, modes = (
        _isolated_worker_authority(source_root)
    )
    return engine(
        policy=policy(), bankrolls=bankrolls(root / "bankroll.jsonl"),
        qualifications=qualifications(root / "qualifications.jsonl"),
        safety=safety(root / "safety.jsonl"), audit_log=audit(root / "risk.jsonl"),
        strategies=strategies(root / "strategies.jsonl"),
        modes=modes(root / "mode.jsonl"),
        action_clock=lambda requested_at: requested_at,
    )


def _paused_approval_worker(root, req, source_root, entered, release, results):
    try:
        engine = _worker_engine(root, source_root)
        original = engine.audit_log.log.transaction

        def paused(builder, **kwargs):
            entered.set()
            if not release.wait(15):
                raise TimeoutError("admission barrier timed out")
            return original(builder, **kwargs)

        engine.audit_log.log.transaction = paused
        decision = engine.approve(req)
        results.put((decision.passed, decision.reason, decision.approved_stake))
    except BaseException as exc:
        results.put(("ERROR", repr(exc), None))


def _locked_approval_worker(root, req, source_root, entered, release, results):
    try:
        engine = _worker_engine(root, source_root)
        original = engine.audit_log.log.transaction

        def gated(builder, **kwargs):
            def inside(rows):
                entered.set()
                if not release.wait(15):
                    raise TimeoutError("locked admission barrier timed out")
                return builder(rows)

            return original(inside, **kwargs)

        engine.audit_log.log.transaction = gated
        decision = engine.approve(req)
        results.put((decision.passed, decision.reason))
    except BaseException as exc:
        results.put(("ERROR", repr(exc)))


def _authority_writer(root, owner, source_root, attempting, done, results):
    try:
        _, bankroll_snapshot, bankroll_store, _, _, safety_state, safety_store, _, _, _ = (
            _isolated_worker_authority(source_root)
        )
        if owner == "bankroll":
            store = bankroll_store(root / "bankroll.jsonl")
            prior = store.current()
            record = bankroll_snapshot.create(
                bankroll="10", captured_at="2026-01-01T00:20:00Z",
                rebase_reason="drawdown_trigger", parent_snapshot_id=prior.snapshot_id,
            )
        else:
            store = safety_store(root / "safety.jsonl")
            prior = store.current()
            record = safety_state.create(
                kill_switch_active=True, recorded_at="2026-01-01T00:20:00Z",
                reason="operator-stop", parent_state_id=prior.state_id,
            )
        original = store.log.transaction

        def at_lock(builder, **kwargs):
            attempting.set()
            return original(builder, **kwargs)

        store.log.transaction = at_lock
        store.append(record)
        results.put("committed")
    except BaseException as exc:
        results.put(repr(exc))
    finally:
        done.set()


class AstraAdmissionSerializationTests(unittest.TestCase):
    def _inject(self, fixture, change):
        log = fixture["audit"].log
        original = log.transaction
        inserted = False

        def at_entry(builder, **kwargs):
            nonlocal inserted
            if not inserted:
                inserted = True
                change()
            return original(builder, **kwargs)

        log.transaction = at_entry

    def _assert_no_approval(self, fixture):
        self.assertEqual(fixture["audit"].verify(), 0)
        self.assertEqual(_restarted(fixture["root"]).audit_log.verify(), 0)

    def test_downward_rebase_at_transaction_entry_cannot_commit_old_7_5_stake(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            fixture["root"] = root
            req = request(fixture)

            def rebase():
                prior = fixture["bankrolls"].current()
                fixture["bankrolls"].append(BankrollSnapshot.create(
                    bankroll="10", captured_at="2026-01-01T00:05:00Z",
                    rebase_reason="drawdown_trigger", parent_snapshot_id=prior.snapshot_id,
                ))

            self._inject(fixture, rebase)
            decision = fixture["engine"].approve(req)
            self.assertFalse(decision.passed, "A7 admitted 7.5 against current bankroll 10")
            self.assertEqual(decision.reason, "stale_bankroll_snapshot")
            self._assert_no_approval(fixture)

    def test_kill_at_transaction_entry_cannot_commit_approval(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            fixture["root"] = root
            req = request(fixture)

            def kill():
                prior = fixture["safety"].current()
                fixture["safety"].append(SafetyState.create(
                    kill_switch_active=True, recorded_at="2026-01-01T00:05:00Z",
                    reason="operator-stop", parent_state_id=prior.state_id,
                ))

            self._inject(fixture, kill)
            decision = fixture["engine"].approve(req)
            self.assertFalse(decision.passed, "A7 admitted against an active kill switch")
            self.assertEqual(decision.reason, "kill_switch_active")
            self._assert_no_approval(fixture)

    def test_qualification_ambiguity_at_transaction_entry_cannot_commit(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            fixture["root"] = root
            req = request(fixture)
            record = fixture["qualification"]
            self._inject(fixture, lambda: fixture["qualifications"].log.append({
                "record_type": "qualification_record", **record.to_dict(),
            }))
            decision = fixture["engine"].approve(req)
            self.assertFalse(decision.passed, "ambiguous qualification granted new risk")
            self._assert_no_approval(fixture)

    def test_unknown_exposure_at_entry_and_competing_last_capacity_block(self):
        with scratch_directory() as root:
            fixture = build_risk(root / "unknown")
            req = request(fixture)
            self._inject(fixture, lambda: fixture["engine"].record_exposure(
                Exposure("other", digest("8"), "1", ExposureState.UNKNOWN),
                recorded_at="2026-01-01T00:05:00Z",
            ))
            decision = fixture["engine"].approve(req)
            self.assertFalse(decision.passed)
            self.assertEqual(decision.reason, "unknown_exposure_blocks_new_risk")

            other = build_risk(root / "capacity")
            second_qualification = qualification(
                other["qualifications"], other["policy"],
                candidate_hash=digest("2"),
                contract_hash=other["contract"].contract_hash,
                tier="3.0u", candidate_id="other",
            )
            other["engine"].record_exposure(
                Exposure("prior", digest("8"), "50", ExposureState.MATCHED),
                recorded_at="2026-01-01T00:05:00Z",
            )
            first = other["engine"].approve(request(other))
            self.assertTrue(first.passed)
            second = RiskRequest(
                second_qualification.candidate_decision_hash,
                second_qualification.qualification_record_id,
                                 other["snapshot"].snapshot_id, BetSide.BACK,
                                 "2.00", "2026-01-01T00:10:00Z")
            self.assertEqual(other["engine"].approve(second).reason,
                             "open_liability_limit")
            self.assertEqual(other["audit"].verify(), 2)

    def test_preexisting_stake_survives_rebase_but_new_risk_uses_current_cap(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            first = fixture["engine"].approve(request(fixture))
            self.assertTrue(first.passed)
            fixture["engine"].rebase(
                "10", captured_at="2026-01-01T00:20:00Z",
                scheduled_weekly=False, drawdown_triggered=True,
            )
            record = qualification(fixture["qualifications"], fixture["policy"],
                                   candidate_hash=digest("2"),
                                   contract_hash=fixture["contract"].contract_hash,
                                   tier="1.0u",
                                   candidate_id="later")
            second = RiskRequest(record.candidate_decision_hash, record.qualification_record_id,
                                 fixture["bankrolls"].current().snapshot_id,
                                 BetSide.BACK, "2.00", "2026-01-01T00:30:00Z")
            self.assertEqual(_restarted(root).approve(second).reason,
                             "open_liability_limit")
            self.assertEqual(_restarted(root).get_approval(first.approval_id).approved_stake,
                             "7.5")

    def test_multiprocess_rebase_before_admission_resumes_blocks_stale_head(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            req = request(fixture)
            context = multiprocessing.get_context("spawn")
            entered, release = context.Event(), context.Event()
            results = context.Queue()
            worker = context.Process(target=_paused_approval_worker,
                                     args=(root, req, Path(genesis.__file__).resolve().parent.parent,
                                           entered, release, results))
            worker.start()
            try:
                self.assertTrue(entered.wait(15), "worker did not reach admission barrier")
                prior = fixture["bankrolls"].current()
                fixture["bankrolls"].append(BankrollSnapshot.create(
                    bankroll="10", captured_at="2026-01-01T00:05:00Z",
                    rebase_reason="drawdown_trigger", parent_snapshot_id=prior.snapshot_id,
                ))
                release.set()
                outcome = results.get(timeout=20)
                self.assertNotEqual(outcome[0], "ERROR", outcome)
                self.assertFalse(outcome[0], "cross-process stale admission committed")
                self.assertEqual(_restarted(root).audit_log.verify(), 0)
            finally:
                release.set()
                worker.join(20)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
            self.assertEqual(worker.exitcode, 0)

    def test_multiprocess_authority_writers_wait_for_locked_admission(self):
        with scratch_directory() as root:
            for owner in ("bankroll", "safety"):
                with self.subTest(owner=owner):
                    case = root / owner
                    fixture = build_risk(case)
                    req = request(fixture)
                    context = multiprocessing.get_context("spawn")
                    entered, release = context.Event(), context.Event()
                    attempting, done = context.Event(), context.Event()
                    approval_results, writer_results = context.Queue(), context.Queue()
                    approver = context.Process(target=_locked_approval_worker,
                                               args=(case, req, Path(genesis.__file__).resolve().parent.parent,
                                                     entered, release,
                                                     approval_results))
                    writer = context.Process(target=_authority_writer,
                                             args=(case, owner, Path(genesis.__file__).resolve().parent.parent,
                                                   attempting, done,
                                                   writer_results))
                    approver.start()
                    try:
                        self.assertTrue(entered.wait(15))
                        writer.start()
                        self.assertTrue(attempting.wait(15))
                        self.assertFalse(done.wait(2),
                                         "authority writer crossed an active admission fence")
                        release.set()
                        self.assertEqual(approval_results.get(timeout=20)[0], True)
                        self.assertEqual(writer_results.get(timeout=20), "committed")
                    finally:
                        release.set()
                        approver.join(20)
                        if approver.is_alive():
                            approver.terminate()
                            approver.join(5)
                        if writer.pid is not None:
                            writer.join(20)
                            if writer.is_alive():
                                writer.terminate()
                                writer.join(5)
                    self.assertEqual(approver.exitcode, 0)
                    self.assertEqual(writer.exitcode, 0)
                    self.assertEqual(_restarted(case).audit_log.verify(), 1)

    def test_uncertain_post_append_response_restarts_as_exactly_one_approval(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            req = request(fixture)
            log = fixture["audit"].log
            original = log.transaction

            def lost_response(builder, **kwargs):
                original(builder, **kwargs)
                raise RuntimeError("synthetic lost response after durable append")

            log.transaction = lost_response
            with self.assertRaises(RuntimeError):
                fixture["engine"].approve(req)
            reopened = _restarted(root)
            self.assertEqual(reopened.audit_log.verify(), 1)
            self.assertEqual(reopened.approve(req).reason, "duplicate_order_intent")
            self.assertEqual(reopened.audit_log.verify(), 1)

    def test_coordinator_commit_failure_after_jsonl_fsync_replays_once(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            req = request(fixture)
            risk_path = fixture["audit"].log.path
            committed = False

            class LostCoordinatorCommit(sqlite3.Connection):
                def commit(self):
                    nonlocal committed
                    if not committed and risk_path.exists() and risk_path.stat().st_size:
                        committed = True
                        raise sqlite3.OperationalError("synthetic coordinator commit loss")
                    return super().commit()

            original = sqlite3.connect

            def crashing_connection(*args, **kwargs):
                return original(*args, factory=LostCoordinatorCommit, **kwargs)

            with patch("genesis.registry.sqlite3.connect", side_effect=crashing_connection):
                with self.assertRaises(sqlite3.OperationalError):
                    fixture["engine"].approve(req)
            self.assertTrue(committed)
            reopened = _restarted(root)
            self.assertEqual(reopened.audit_log.verify(), 1)
            self.assertEqual(reopened.approve(req).reason, "duplicate_order_intent")
            self.assertEqual(reopened.audit_log.verify(), 1)


if __name__ == "__main__":
    unittest.main()
