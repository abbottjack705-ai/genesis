"""T6 F-2: a qualification admits risk only with a durable witness of its prior grant.

Invariant (durable causality): a V3 qualification admits new risk only if the
risk-bound qualification log carries exactly one approval witness for it,
written by the recording path while the qualification did not yet exist. The
witness names the exact approval the record relies on. For a versioned
approval that is the ledger, as the risk authority resolves it, and the exact
grant row, which must still be that reference's unique unrevoked grant.

A grant appended after the qualification never makes it spendable. That holds
for a grant byte-identical to one made in a copied ledger, for a raw-written
qualification, and when the recording path is re-run after the record exists.
The witness storage itself accepts no witness after its record and no witness
other than the one the recording path would write; a witness of a copied
ledger's grant neither admits risk nor blocks the real one. Revocation still
blocks. Qualification rows and identities are unchanged.
"""

from __future__ import annotations

import contextlib
import shutil
import threading
import unittest
from pathlib import Path

import genesis.decision_output as decision_output
import genesis.selection as selection
from genesis.registry import AppendOnlyJsonl, RegistryConflict
from genesis.risk import RiskAuditLog, RiskEngine

from . import test_remediation_r5_risk as r5
from ._support import SyntheticRecordingQualificationStore, scratch_directory
from .test_astra_t5_owner_binding import admitted, risk_like


ORIGINAL_REGISTER = decision_output.StrategyOutputRuleBindingStore.register_approved
LEDGER = "strategy-output-approvals-v2.jsonl"
GRANT = {"approved_by": "synthetic-operator", "approved_at": "2025-12-31T23:00:00Z"}


@contextlib.contextmanager
def reserved_approval(state: dict, *, grant: bool):
    """Reserve a genuine v2 reference in the deployment's ledger; grant it now or later."""

    def register(self, body):
        ledger = decision_output.StrategyOutputApprovalStore(self.log.path.parent / LEDGER)
        reference = ledger.reserve(
            request_id="t6-f2", reserved_by="synthetic-operator",
            reserved_at="2025-12-31T22:00:00Z",
        )
        binding_hash = ORIGINAL_REGISTER(self, dict(body, human_approval_reference=reference))
        state.update(ledger=ledger, reference=reference, binding_hash=binding_hash)
        if grant:
            ledger.grant(reference, binding_hash=binding_hash, **GRANT)
        if "before_record" in state:
            state["before_record"](state)
        return binding_hash

    decision_output.StrategyOutputRuleBindingStore.register_approved = register
    try:
        yield
    finally:
        decision_output.StrategyOutputRuleBindingStore.register_approved = ORIGINAL_REGISTER


def recorded(root: Path, appender) -> dict:
    """Build the synthetic PAPER deployment, recording through ``appender``.

    No risk authority is composed here, so the authority composed afterwards
    over the deployment's own qualification store binds the real owners.
    """

    saved = (r5.QualificationRecordStore, r5.RiskEngine)
    r5.QualificationRecordStore = appender
    r5.RiskEngine = lambda **_owners: None
    try:
        return r5.build_risk(root)
    finally:
        r5.QualificationRecordStore, r5.RiskEngine = saved


def raw_appender(path):
    """The auditor's raw route: the record row is written without the recording path."""

    store = selection.QualificationRecordStore(path)

    def append(record, **_ignored):
        AppendOnlyJsonl(store.log.path).append(
            {"record_type": "qualification_record", **record.to_dict()}
        )
        return record

    store.record_fixture_qualification = append
    return store


def authority(f: dict, root: Path) -> RiskEngine:
    return RiskEngine(
        policy=f["policy"], bankrolls=f["bankrolls"],
        qualifications=selection.QualificationRecordStore(root / "qualifications.jsonl"),
        safety=f["safety"], audit_log=RiskAuditLog(root / "risk.jsonl"),
        strategies=f["strategies"], modes=f["modes"],
        action_clock=lambda requested_at: requested_at,
    )


def witnesses_for(root: Path, record_id: str) -> list[dict]:
    store = selection.QualificationRecordStore(root / "qualifications.jsonl")
    return [row for row in store.witnesses.records()
            if row.get("qualification_record_id") == record_id]


class T6ApprovalCausalityTests(unittest.TestCase):
    def test_t6_grant_reproduced_from_a_copied_ledger_never_admits_risk(self):
        with scratch_directory() as root:
            copy = root / "elsewhere" / LEDGER
            state: dict = {}

            def grant_in_copy(current: dict) -> None:
                copy.parent.mkdir(parents=True)
                shutil.copyfile(current["ledger"].log.path, copy)
                decision_output.StrategyOutputApprovalStore(copy).grant(
                    current["reference"], binding_hash=current["binding_hash"], **GRANT,
                )

            state["before_record"] = grant_in_copy
            with reserved_approval(state, grant=False):
                f = recorded(root, lambda path: SyntheticRecordingQualificationStore(
                    path, approvals=decision_output.StrategyOutputApprovalStore(copy),
                ))
            engine = authority(f, root)
            self.assertFalse(admitted(lambda: engine.approve(r5.request(f))))
            state["ledger"].grant(state["reference"], binding_hash=state["binding_hash"], **GRANT)
            # The later real grant row is byte-identical to the copied ledger's
            # grant, so a bare grant-row hash could not order the two.
            self.assertEqual(
                state["ledger"].log.records()[-1],
                decision_output.StrategyOutputApprovalStore(copy).log.records()[-1],
            )
            self.assertFalse(
                admitted(lambda: engine.approve(r5.request(f))),
                "F-2: a grant reproduced after the qualification admitted risk",
            )

    def test_t6_raw_written_qualification_never_admits_risk_after_a_later_grant(self):
        with scratch_directory() as root:
            state: dict = {}
            with reserved_approval(state, grant=False):
                f = recorded(root, raw_appender)
            engine = authority(f, root)
            self.assertFalse(admitted(lambda: engine.approve(r5.request(f))))
            state["ledger"].grant(
                state["reference"], binding_hash=state["binding_hash"],
                approved_by="synthetic-operator", approved_at="2025-12-31T23:59:59Z",
            )
            self.assertFalse(
                admitted(lambda: engine.approve(r5.request(f))),
                "F-2: a backdated grant admitted a raw-written qualification",
            )

    def test_t6_recording_path_rerun_after_the_record_exists_adds_no_witness(self):
        with scratch_directory() as root:
            state: dict = {}
            with reserved_approval(state, grant=False):
                f = recorded(root, raw_appender)
            state["ledger"].grant(state["reference"], binding_hash=state["binding_hash"], **GRANT)
            # The recording path over the real composition is idempotent for
            # an existing record and must not witness it retroactively.
            SyntheticRecordingQualificationStore(
                root / "qualifications.jsonl"
            ).record_fixture_qualification(f["qualification"])
            engine = authority(f, root)
            self.assertFalse(
                admitted(lambda: engine.approve(r5.request(f))),
                "F-2: re-running the recording path admitted a grant-later qualification",
            )
            self.assertEqual(witnesses_for(root, f["qualification"].qualification_record_id), [])

    def test_t6_witness_storage_refuses_a_forged_or_late_witness(self):
        with scratch_directory() as root:
            state: dict = {}
            with reserved_approval(state, grant=False):
                f = recorded(root, raw_appender)
            state["ledger"].grant(state["reference"], binding_hash=state["binding_hash"], **GRANT)
            store = selection.QualificationRecordStore(root / "qualifications.jsonl")
            record = f["qualification"]
            # Exactly the witness the recording path would write now: refused,
            # because its record already exists.
            late = store._require_prior_grant(record)
            for label, write in (
                ("append", lambda: store.witnesses.append(dict(late))),
                ("transaction", lambda: store.witnesses.transaction(lambda _rows: dict(late))),
            ):
                with self.subTest(label):
                    with self.assertRaises(RegistryConflict, msg=f"F-2: late witness via {label}"):
                        write()
            self.assertEqual(witnesses_for(root, record.qualification_record_id), [])
            self.assertFalse(admitted(lambda: authority(f, root).approve(r5.request(f))))

    def test_t6_witness_storage_refuses_a_wrong_grant_before_the_record(self):
        with scratch_directory() as root:
            state: dict = {}

            def deferred(path):
                store = selection.QualificationRecordStore(path)
                store.record_fixture_qualification = (
                    lambda record: state.setdefault("record", record)
                )
                return store

            with reserved_approval(state, grant=True):
                recorded(root, deferred)
            store = selection.QualificationRecordStore(root / "qualifications.jsonl")
            witness = store._require_prior_grant(state["record"])
            for field, value in (("grant_record_hash", "0" * 64), ("grant_sequence", 1),
                                 ("approval_ledger", "elsewhere/" + LEDGER)):
                with self.subTest(field):
                    with self.assertRaises(RegistryConflict):
                        store.witnesses.append(dict(witness, **{field: value}))
            self.assertEqual(witnesses_for(root, state["record"].qualification_record_id), [])

    def test_t6_copied_ledger_witness_neither_admits_nor_blocks_the_real_grant(self):
        with scratch_directory() as root:
            copy = root / "elsewhere" / LEDGER
            state: dict = {}

            def grant_in_copy(current: dict) -> None:
                copy.parent.mkdir(parents=True)
                shutil.copyfile(current["ledger"].log.path, copy)
                decision_output.StrategyOutputApprovalStore(copy).grant(
                    current["reference"], binding_hash=current["binding_hash"], **GRANT,
                )

            def deferred(path):
                store = selection.QualificationRecordStore(path)
                store.record_fixture_qualification = (
                    lambda record: state.setdefault("record", record)
                )
                return store

            state["before_record"] = grant_in_copy
            with reserved_approval(state, grant=False):
                f = recorded(root, deferred)
            record = state["record"]
            # A composition over the real log and a copied ledger witnesses the
            # copy's grant first, without recording the qualification.
            selection.QualificationRecordStore(
                root / "qualifications.jsonl",
                approvals=decision_output.StrategyOutputApprovalStore(copy),
            )._record_witness(record)
            engine = authority(f, root)
            self.assertFalse(admitted(lambda: engine.approve(r5.request(f))))
            state["ledger"].grant(state["reference"], binding_hash=state["binding_hash"], **GRANT)
            SyntheticRecordingQualificationStore(
                root / "qualifications.jsonl"
            ).record_fixture_qualification(record)
            self.assertEqual(
                sorted(row["approval_ledger"]
                       for row in witnesses_for(root, record.qualification_record_id)),
                ["elsewhere/" + LEDGER, LEDGER],
            )
            decision = engine.approve(r5.request(f))
            self.assertTrue(decision.passed, decision.reason)

    def test_t6_pre_witness_v3_qualification_is_audit_only_for_new_risk(self):
        # The grant existed first, but the row carries no durable witness, as
        # every V3 row recorded before T6 does: it stays readable, not spendable.
        with scratch_directory() as root:
            state: dict = {}
            with reserved_approval(state, grant=True):
                f = recorded(root, raw_appender)
            engine = authority(f, root)
            record_id = f["qualification"].qualification_record_id
            self.assertEqual(engine.qualifications.get(record_id), f["qualification"])
            self.assertEqual(engine.qualifications.verify(), 1)
            self.assertFalse(admitted(lambda: engine.approve(r5.request(f))))

    def test_t6_prior_grant_is_witnessed_and_admits_risk_after_relocation(self):
        with scratch_directory() as root:
            deploy = root / "deploy"
            deploy.mkdir()
            state: dict = {}
            with reserved_approval(state, grant=True):
                f = recorded(deploy, SyntheticRecordingQualificationStore)
            record_id = f["qualification"].qualification_record_id
            grant = state["ledger"].log.records()[-1]
            [witness] = witnesses_for(deploy, record_id)
            self.assertEqual(
                (witness["approval_reference"], witness["binding_hash"],
                 witness["approval_ledger"], witness["grant_record_hash"],
                 witness["grant_sequence"]),
                (state["reference"], state["binding_hash"], LEDGER,
                 grant["record_hash"], grant["sequence"]),
            )
            self.assertEqual(
                selection.QualificationRecordStore(deploy / "qualifications.jsonl").get(record_id),
                f["qualification"],
            )
            engine = authority(f, deploy)
            decision = engine.approve(r5.request(f))
            self.assertTrue(decision.passed, decision.reason)
            moved = root / "moved"
            shutil.move(str(deploy), str(moved))
            reopened = risk_like(
                moved, qualifications=selection.QualificationRecordStore(moved / "qualifications.jsonl"),
            )
            consumed = reopened.consume_for_order(
                decision.approval_id, order_id="t6-order", consumed_at="2026-01-01T00:11:00Z",
            )
            self.assertEqual(consumed.status, "CONSUMED")

    def test_t6_revoked_grant_blocks_new_risk_after_recording(self):
        with scratch_directory() as root:
            state: dict = {}
            with reserved_approval(state, grant=True):
                f = recorded(root, SyntheticRecordingQualificationStore)
            state["ledger"].revoke(
                state["reference"], binding_hash=state["binding_hash"],
                revoked_by="synthetic-operator", revoked_at="2026-01-01T00:05:00Z",
                reason="synthetic revocation",
            )
            engine = authority(f, root)
            self.assertFalse(admitted(lambda: engine.approve(r5.request(f))))

    def test_t6_crash_after_the_witness_resumes_to_one_witness_and_one_record(self):
        with scratch_directory() as root:
            state: dict = {}

            def crashing(path):
                store = SyntheticRecordingQualificationStore(path)
                original_append, original_transaction = (
                    store.record_fixture_qualification, store.log.transaction,
                )

                def append(record, **kwargs):
                    state["record"] = record
                    return original_append(record, **kwargs)

                def transaction(build, **kwargs):
                    store.log.transaction = original_transaction
                    raise RuntimeError("synthetic crash before the qualification append")

                store.record_fixture_qualification, store.log.transaction = append, transaction
                return store

            with reserved_approval(state, grant=True):
                with self.assertRaises(RuntimeError):
                    recorded(root, crashing)
            record = state["record"]
            store = SyntheticRecordingQualificationStore(root / "qualifications.jsonl")
            self.assertEqual(store.verify(), 0)
            self.assertEqual(len(witnesses_for(root, record.qualification_record_id)), 1)
            store.record_fixture_qualification(record)
            store.record_fixture_qualification(record)
            self.assertEqual(store.verify(), 1)
            self.assertEqual(len(witnesses_for(root, record.qualification_record_id)), 1)

    def test_t6_concurrent_recording_of_one_qualification_has_one_witness(self):
        with scratch_directory() as root:
            state: dict = {}

            def deferred(path):
                store = selection.QualificationRecordStore(path)

                def append(record):
                    state["record"] = record
                    return record

                store.record_fixture_qualification = append
                return store

            with reserved_approval(state, grant=True):
                f = recorded(root, deferred)
            record = state["record"]
            errors: list[BaseException] = []
            barrier = threading.Barrier(2)

            def record_it():
                try:
                    barrier.wait(30)
                    SyntheticRecordingQualificationStore(
                        root / "qualifications.jsonl"
                    ).record_fixture_qualification(record)
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=record_it) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)
            self.assertEqual(errors, [])
            self.assertEqual(
                selection.QualificationRecordStore(root / "qualifications.jsonl").verify(), 1,
            )
            self.assertEqual(len(witnesses_for(root, record.qualification_record_id)), 1)
            self.assertTrue(authority(f, root).approve(r5.request(f)).passed)


if __name__ == "__main__":
    unittest.main()
