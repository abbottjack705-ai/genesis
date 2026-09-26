"""B1: trusted decision-output dependence, not a risk caller's cluster copy.

Every authority fixture in this module is synthetic-test-only and cannot be
used as an operational strategy, calibration, tier or expiry approval.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from dataclasses import asdict
from pathlib import Path

from genesis.accounting import BetSide
from genesis.decision import candidate_v3_decision_hash
from genesis.execution import ModeStateStore
from genesis.policy import PolicySet
from genesis.registry import RegistryConflict, StrategyRegistry
from genesis.risk import (
    BankrollSnapshotStore,
    Exposure,
    ExposureState,
    RiskAuditLog,
    RiskEngine,
    RiskRequest,
    SafetyStateStore,
)
from genesis.selection import QualificationRecord

from ._support import SyntheticQualificationRecordStore, scratch_directory
from .test_remediation_r5_risk import build_risk, digest, qualification, request


def _publish_clustered(fixture: dict, record: QualificationRecord, clusters: tuple[str, ...]) -> QualificationRecord:
    """Bind a synthetic v3 qualification to a new immutable output identity."""

    store = fixture["qualifications"]
    body = store.outputs.get(record.decision_output_hash)
    body["correlation_cluster_ids"] = sorted(set(clusters))
    output_hash = store.outputs.publish(body)
    fields = asdict(record)
    fields.pop("qualification_record_id")
    fields["decision_output_hash"] = output_hash
    fields["candidate_decision_hash"] = candidate_v3_decision_hash(
        strategy_decision_contract_hash=record.strategy_decision_contract_hash,
        feature_manifest_hash=record.feature_manifest_hash,
        evidence_pack_hash=body["evidence_pack_hash"],
        decision_output_hash=output_hash,
    )
    return store.append(QualificationRecord.create(**fields))


def _use_clustered(fixture: dict, clusters: tuple[str, ...]) -> QualificationRecord:
    record = _publish_clustered(fixture, fixture["qualification"], clusters)
    fixture["qualification"] = record
    fixture["candidate_hash"] = record.candidate_decision_hash
    return record


def _risk_worker(
    root: str, qualification_id: str, candidate_hash: str, label: str,
) -> None:
    """Independent process, independent risk owner, one shared durable log."""

    try:
        path = Path(root)
        engine = RiskEngine(
            policy=PolicySet(),
            bankrolls=BankrollSnapshotStore(path / "bankroll.jsonl"),
            qualifications=SyntheticQualificationRecordStore(path / "qualifications.jsonl"),
            safety=SafetyStateStore(path / "safety.jsonl"),
            audit_log=RiskAuditLog(path / "risk.jsonl"),
            strategies=StrategyRegistry(path / "strategies.jsonl"),
            modes=ModeStateStore(path / "mode.jsonl"),
            action_clock=lambda requested_at: requested_at,
        )
        (path / f"{label}.ready").touch()
        deadline = time.monotonic() + 20
        while not (path / "go.flag").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("two-process risk start was not released")
            time.sleep(0.02)
        snapshot = engine.bankrolls.current()
        decision = engine.approve(RiskRequest(
            candidate_decision_hash=candidate_hash,
            qualification_record_id=qualification_id,
            bankroll_snapshot_id=snapshot.snapshot_id,
            side=BetSide.BACK,
            odds="2",
            requested_at="2026-01-01T00:10:00Z",
            correlation_cluster_ids=(),
        ))
        outcome = (decision.passed, decision.reason, decision.approval_id)
    except BaseException as exc:  # A child error must be visible, never a false RED.
        outcome = ("ERROR", type(exc).__name__, str(exc))
    Path(root, f"{label}.result.json").write_text(json.dumps(outcome), encoding="utf-8")


class AstraB1DependenceTests(unittest.TestCase):
    def test_d01_original_shared_cluster_caller_omission_cannot_approve(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            record = _use_clustered(fixture, ("shared-cluster",))
            fixture["engine"].record_exposure(
                Exposure("existing", digest("e"), "10", ExposureState.MATCHED,
                         ("shared-cluster",)),
                recorded_at="2026-01-01T00:02:00Z",
            )
            honest = fixture["engine"].approve(
                request(fixture, correlation_cluster_ids=("shared-cluster",))
            )
            self.assertFalse(honest.passed)
            self.assertEqual(honest.reason, "correlation_cluster_limit")
            before = len(fixture["audit"].log.records())
            omitted = fixture["engine"].approve(request(fixture))
            self.assertFalse(omitted.passed, "empty caller copy bypassed output-derived dependence")
            self.assertEqual(omitted.reason, "correlation_cluster_limit")
            self.assertEqual(len(fixture["audit"].log.records()), before)
            self.assertEqual(
                fixture["qualifications"].outputs.get(record.decision_output_hash)[
                    "correlation_cluster_ids"
                ], ["shared-cluster"],
            )

    def test_d02_nonempty_wrong_subset_and_superset_copies_are_denied(self):
        with scratch_directory() as root:
            for label, copied in (
                ("wrong", ("other",)),
                ("subset", ("alpha",)),
                ("superset", ("alpha", "beta", "extra")),
            ):
                with self.subTest(copy=label):
                    fixture = build_risk(root / label)
                    _use_clustered(fixture, ("alpha", "beta"))
                    before = len(fixture["audit"].log.records())
                    decision = fixture["engine"].approve(
                        request(fixture, correlation_cluster_ids=copied)
                    )
                    self.assertFalse(decision.passed,
                                     f"{label} caller copy overrode trusted membership")
                    self.assertEqual(len(fixture["audit"].log.records()), before)
                    self.assertEqual(fixture["engine"].reserved_exposures(), ())

    def test_d02_reordered_equal_copy_and_omission_persist_canonical_output(self):
        with scratch_directory() as root:
            for label, copied in (
                ("reordered", ("beta", "alpha")),
                ("omitted", ()),
            ):
                with self.subTest(copy=label):
                    fixture = build_risk(root / label)
                    _use_clustered(fixture, ("alpha", "beta"))
                    decision = fixture["engine"].approve(
                        request(fixture, correlation_cluster_ids=copied)
                    )
                    self.assertTrue(decision.passed, decision.reason)
                    reservation = fixture["engine"].reserved_exposures()
                    self.assertEqual(len(reservation), 1)
                    self.assertEqual(reservation[0].correlation_cluster_ids,
                                     ("alpha", "beta"),
                                     "reservation must persist trusted canonical output membership")
                    row = fixture["audit"].log.records()[-1]
                    self.assertEqual(row["correlation_cluster_ids"], ["alpha", "beta"])

    def test_d03_missing_output_binding_and_legacy_v2_do_not_default_empty(self):
        with scratch_directory() as root:
            missing = build_risk(root / "missing")
            _use_clustered(missing, ("shared",))
            output_hash = missing["qualification"].decision_output_hash
            (missing["qualifications"].outputs.root / f"{output_hash}.json").unlink()
            self.assertFalse(missing["engine"].approve(request(missing)).passed)
            self.assertEqual(missing["engine"].reserved_exposures(), ())

            invalid = build_risk(root / "invalid")
            invalid_hash = invalid["qualification"].decision_output_hash
            (invalid["qualifications"].outputs.root / f"{invalid_hash}.json").write_bytes(b"{}")
            self.assertFalse(invalid["engine"].approve(request(invalid)).passed)
            self.assertEqual(invalid["engine"].reserved_exposures(), ())

            wrong_hash = build_risk(root / "wrong-hash")
            old_wrong = wrong_hash["qualification"]
            altered_output = wrong_hash["qualifications"].outputs.get(
                old_wrong.decision_output_hash
            )
            altered_output["correlation_cluster_ids"] = ["shared"]
            alternate_hash = wrong_hash["qualifications"].outputs.publish(altered_output)
            wrong_fields = asdict(old_wrong)
            wrong_fields.pop("qualification_record_id")
            wrong_fields["decision_output_hash"] = alternate_hash
            # Candidate hash intentionally remains bound to the original output.
            wrong_hash["qualification"] = wrong_hash["qualifications"].append(
                QualificationRecord.create(**wrong_fields)
            )
            self.assertFalse(wrong_hash["engine"].approve(request(wrong_hash)).passed)
            self.assertEqual(wrong_hash["engine"].reserved_exposures(), ())

            binding = build_risk(root / "binding")
            old = binding["qualification"]
            output = binding["qualifications"].outputs.get(old.decision_output_hash)
            output["resolver_binding_hash"] = digest("f")
            changed_hash = binding["qualifications"].outputs.publish(output)
            fields = asdict(old)
            fields.pop("qualification_record_id")
            fields["decision_output_hash"] = changed_hash
            fields["candidate_decision_hash"] = candidate_v3_decision_hash(
                strategy_decision_contract_hash=old.strategy_decision_contract_hash,
                feature_manifest_hash=old.feature_manifest_hash,
                evidence_pack_hash=output["evidence_pack_hash"],
                decision_output_hash=changed_hash,
            )
            # T5/O-5 refuses to record a V3 qualification whose binding (and so
            # its prior human grant) does not exist. Seed the byte-identical row
            # the pre-T5 API appended so risk admission is still exercised.
            record = QualificationRecord.create(**fields)
            binding["qualifications"].log.append(
                {"record_type": "qualification_record", **record.to_dict()}
            )
            binding["qualification"] = record
            binding["candidate_hash"] = fields["candidate_decision_hash"]
            self.assertFalse(binding["engine"].approve(request(binding)).passed)
            self.assertEqual(binding["engine"].reserved_exposures(), ())

            legacy = build_risk(root / "legacy")
            old = legacy["qualification"]
            v2 = legacy["qualifications"].append(QualificationRecord.create(
                schema_version="qualification-record-v2",
                candidate_id="legacy-candidate", candidate_decision_hash=digest("f"),
                strategy_id=old.strategy_id, strategy_version=old.strategy_version,
                strategy_decision_contract_hash=old.strategy_decision_contract_hash,
                approved_tier=old.approved_tier,
                comparability_group_id=old.comparability_group_id,
                active_policy_digest=old.active_policy_digest,
                market_capability_id=old.market_capability_id,
                decision_at=old.decision_at, evaluated_at=old.evaluated_at,
                expires_at=old.expires_at, gate_results_digest=old.gate_results_digest,
            ))
            decision = legacy["engine"].approve(request(
                legacy, candidate_hash=v2.candidate_decision_hash,
                qualification_record_id=v2.qualification_record_id,
            ))
            self.assertFalse(decision.passed)
            self.assertEqual(legacy["engine"].reserved_exposures(), ())
            self.assertEqual(legacy["qualifications"].get(v2.qualification_record_id), v2)

    def test_d04_trusted_empty_dependence_can_pass_without_other_blocker(self):
        with scratch_directory() as root:
            fixture = build_risk(root)
            self.assertEqual(
                fixture["qualifications"].outputs.get(
                    fixture["qualification"].decision_output_hash
                )["correlation_cluster_ids"], [],
            )
            fixture["engine"].record_exposure(
                Exposure("independent", digest("e"), "10", ExposureState.MATCHED,
                         ("unrelated",)),
                recorded_at="2026-01-01T00:02:00Z",
            )
            decision = fixture["engine"].approve(request(fixture))
            self.assertTrue(decision.passed, decision.reason)
            reservation = [item for item in fixture["engine"].reserved_exposures()
                           if item.exposure_id == decision.approval_id]
            self.assertEqual(len(reservation), 1)
            self.assertEqual(reservation[0].correlation_cluster_ids, ())

    def test_d05_exact_cluster_boundary_and_one_cent_above(self):
        with scratch_directory() as root:
            for label, prior, permitted in (
                ("equal", "10", True),
                ("above", "10.01", False),
            ):
                with self.subTest(label=label):
                    fixture = build_risk(root / label, tier="1.0u")
                    _use_clustered(fixture, ("shared",))
                    fixture["engine"].record_exposure(
                        Exposure("prior", digest("e"), prior, ExposureState.MATCHED,
                                 ("shared",)),
                        recorded_at="2026-01-01T00:02:00Z",
                    )
                    decision = fixture["engine"].approve(request(fixture))
                    self.assertEqual(decision.passed, permitted,
                                     f"trusted cluster boundary at prior={prior}: {decision}")
                    self.assertEqual(sum(
                        item.exposure_id == decision.approval_id
                        for item in fixture["engine"].reserved_exposures()
                    ),
                                     1 if permitted else 0)

    def test_d06_restart_replays_exact_output_membership_and_identity(self):
        with scratch_directory() as root:
            fixture = build_risk(root, tier="1.0u")
            record = _use_clustered(fixture, ("alpha", "beta"))
            decision = fixture["engine"].approve(request(fixture))
            self.assertTrue(decision.passed, decision.reason)
            approval = fixture["engine"].get_approval(decision.approval_id)
            restarted = RiskEngine(
                policy=fixture["policy"],
                bankrolls=BankrollSnapshotStore(root / "bankroll.jsonl"),
                qualifications=SyntheticQualificationRecordStore(root / "qualifications.jsonl"),
                safety=SafetyStateStore(root / "safety.jsonl"),
                audit_log=RiskAuditLog(root / "risk.jsonl"),
                strategies=StrategyRegistry(root / "strategies.jsonl"),
                modes=ModeStateStore(root / "mode.jsonl"),
                action_clock=lambda requested_at: requested_at,
            )
            self.assertEqual(restarted.get_approval(decision.approval_id), approval)
            self.assertEqual(restarted.reserved_exposures()[0].correlation_cluster_ids,
                             ("alpha", "beta"))
            self.assertEqual(record.decision_output_hash,
                             restarted.qualifications.get(record.qualification_record_id).decision_output_hash)
            self.assertEqual(record.candidate_decision_hash,
                             restarted.get_approval(decision.approval_id).candidate_decision_hash)

    def test_d06_replay_rejects_approval_clusters_that_disagree_with_bound_output(self):
        with scratch_directory() as root:
            fixture = build_risk(root, tier="1.0u")
            _use_clustered(fixture, ("shared",))
            decision = fixture["engine"].approve(
                request(fixture, correlation_cluster_ids=("shared",))
            )
            self.assertTrue(decision.passed, decision.reason)
            valid_row = fixture["audit"].log.records()[-1]
            forged = {key: value for key, value in valid_row.items()
                      if key not in {"sequence", "previous_hash", "record_hash"}}
            forged["correlation_cluster_ids"] = []
            tampered_audit = RiskAuditLog(root / "tampered-risk.jsonl")
            tampered_audit.log.append(forged)
            with self.assertRaises(RegistryConflict,
                                   msg="replay accepted a reservation detached from decision output"):
                RiskEngine(
                    policy=fixture["policy"],
                    bankrolls=BankrollSnapshotStore(root / "bankroll.jsonl"),
                    qualifications=SyntheticQualificationRecordStore(
                        root / "qualifications.jsonl"
                    ),
                    safety=SafetyStateStore(root / "safety.jsonl"),
                    audit_log=tampered_audit,
                )

    def test_d06_two_processes_contend_for_same_last_cluster_capacity(self):
        with scratch_directory() as root:
            fixture = build_risk(root, tier="1.0u")
            first = _use_clustered(fixture, ("shared",))
            second_base = qualification(
                fixture["qualifications"], fixture["policy"],
                candidate_hash=digest("2"), tier="1.0u", candidate_id="second",
                contract_hash=fixture["contract"].contract_hash,
            )
            second = _publish_clustered(fixture, second_base, ("shared",))
            fixture["engine"].record_exposure(
                Exposure("prior", digest("e"), "10", ExposureState.MATCHED,
                         ("shared",)),
                recorded_at="2026-01-01T00:02:00Z",
            )
            workers = [
                subprocess.Popen(
                    [sys.executable, "-m", "tests.test_astra_t1_dependence",
                     "--risk-worker", str(root), record.qualification_record_id,
                     record.candidate_decision_hash, label],
                    cwd=Path(__file__).resolve().parents[1],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                for label, record in (("first", first), ("second", second))
            ]
            try:
                deadline = time.monotonic() + 20
                while not all((root / f"{label}.ready").exists()
                              for label in ("first", "second")):
                    if time.monotonic() >= deadline or any(w.poll() is not None for w in workers):
                        self.fail(f"two-process workers failed setup: {[w.poll() for w in workers]}")
                    time.sleep(0.02)
                (root / "go.flag").touch()
                for worker in workers:
                    worker.wait(timeout=20)
                outcomes = [
                    json.loads((root / f"{label}.result.json").read_text(encoding="utf-8"))
                    for label in ("first", "second")
                ]
                self.assertTrue(all(worker.returncode == 0 for worker in workers), outcomes)
                self.assertFalse(any(row[0] == "ERROR" for row in outcomes), outcomes)
                self.assertEqual(sum(row[0] is True for row in outcomes), 1, outcomes)
                reservations = [item for item in fixture["engine"].reserved_exposures()
                                if item.exposure_id != "prior"]
                self.assertEqual(len(reservations), 1)
                self.assertEqual(reservations[0].correlation_cluster_ids, ("shared",))
            finally:
                for worker in workers:
                    if worker.poll() is None:
                        worker.terminate()
                    worker.wait(timeout=5)


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--risk-worker":
        _risk_worker(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        unittest.main()
