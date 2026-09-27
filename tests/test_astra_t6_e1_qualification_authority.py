"""E1: a risk-authorising V3 qualification is recorded only by the authority.

Invariant: only ``QualificationAuthority.evaluate`` records a spendable V3
qualification, after every gate passes and the pinned resolver reproduces the
exact decision output. No public store method records one, and the store's
public witness storage writes no approval witness, so a V3 row that reaches the
log any other way stays audit-only, as F-2 already treats rows without a
witness. A caller-constructed or copied record therefore never becomes
spendable, even when its schema is valid and its exact prior grant exists (so
its approval witness would be valid). A store reopened over the same logs
cannot spend it either, and a record the authority recorded stays spendable
after the store is reopened.
"""

from __future__ import annotations

import unittest

import genesis.selection as selection
from genesis.owner_binding import owner_identity
from genesis.registry import RegistryConflict
from genesis.time import iso_utc

from . import test_remediation_r3_qualification as r3
from . import test_remediation_r5_risk as r5
from ._support import SyntheticQualificationRecordStore, scratch_directory
from .test_astra_t5_owner_binding import admitted
from .test_astra_t6_approval_causality import authority, recorded, reserved_approval


NOW = "2026-01-01T00:11:00Z"
# The synthetic risk deployment's recording step, before and after the E1
# fixture migration; the attacks below replace whichever one it calls.
RECORDING_STEPS = ("append", "record_fixture_qualification")


def replacing_recording(attack):
    def appender(path):
        store = selection.QualificationRecordStore(path)
        public_append = store.append

        def step(record, **_ignored):
            attack(store, public_append, record)
            return record

        for name in RECORDING_STEPS:
            setattr(store, name, step)
        return store

    return appender


def public_append(refusals: list):
    """The auditor's route: the public store append of a constructed V3 record."""

    def attack(_store, append, record):
        try:
            append(record)
        except RegistryConflict as exc:
            refusals.append(exc)

    return replacing_recording(attack)


def public_storage(refusals: list):
    """The sibling route: the exact prior-grant witness is written through the
    store's public witness storage before the record row, which is written
    through the store's public log storage."""

    def attack(store, _append, record):
        output = store.outputs.get(record.decision_output_hash)
        grant = [
            row for row in store.approvals.log.records()
            if row["record_type"] == "strategy_output_approval_granted"
        ][-1]
        witness = {
            "record_type": "qualification_approval_witnessed",
            "schema_version": selection.APPROVAL_WITNESS_SCHEMA,
            "qualification_record_id": record.qualification_record_id,
            "decision_output_hash": record.decision_output_hash,
            "decision_at": iso_utc(record.decision_at),
            "binding_hash": output["resolver_binding_hash"],
            "approval_reference": grant["approval_reference"],
            "approval_ledger": owner_identity(store.approvals.log.path, store.log.path.parent),
            "grant_record_hash": grant["record_hash"],
            "grant_sequence": grant["sequence"],
        }
        for write in (
            lambda: store.witnesses.append(dict(witness)),
            lambda: store.witnesses.transaction(lambda _rows: dict(witness)),
        ):
            try:
                write()
                break
            except RegistryConflict as exc:
                refusals.append(exc)
        store.log.append({"record_type": "qualification_record", **record.to_dict()})

    return replacing_recording(attack)


def qualification_rows(root) -> list[dict]:
    return [
        row for row in selection.QualificationRecordStore(root / "qualifications.jsonl").log.records()
        if row.get("record_type") == "qualification_record"
    ]


def witnesses_for(root, record_id: str) -> list[dict]:
    return [
        row for row in selection.QualificationRecordStore(
            root / "qualifications.jsonl"
        ).witnesses.records()
        if row.get("qualification_record_id") == record_id
    ]


class T6E1QualificationAuthorityTests(unittest.TestCase):
    def assert_unspendable(self, root, f) -> None:
        record_id = f["qualification"].qualification_record_id
        self.assertFalse(admitted(lambda: authority(f, root).approve(r5.request(f))))
        # Reopened over the same logs, as after a restart.
        store = selection.QualificationRecordStore(root / "qualifications.jsonl")
        with self.assertRaises(RegistryConflict):
            store.get_for_new_risk(record_id, at="2026-01-01T00:10:00Z")
        self.assertEqual(witnesses_for(root, record_id), [])
        self.assertFalse(admitted(lambda: authority(f, root).approve(r5.request(f))))

    def test_e1_public_append_of_a_constructed_v3_record_never_admits_risk(self):
        with scratch_directory() as root:
            refusals: list = []
            with reserved_approval({}, grant=True):
                f = recorded(root, public_append(refusals))
            self.assert_unspendable(root, f)
            self.assertEqual(len(refusals), 1)
            self.assertEqual(qualification_rows(root), [])

    def test_e1_public_witness_and_log_storage_never_make_a_v3_row_spendable(self):
        with scratch_directory() as root:
            refusals: list = []
            with reserved_approval({}, grant=True):
                f = recorded(root, public_storage(refusals))
            self.assert_unspendable(root, f)
            self.assertEqual(len(refusals), 2)
            # The row written through the log storage is only audit-readable.
            self.assertEqual(
                selection.QualificationRecordStore(root / "qualifications.jsonl").get(
                    f["qualification"].qualification_record_id
                ),
                f["qualification"],
            )

    def test_e1_an_evaluated_record_cannot_be_copied_or_re_derived_by_a_caller(self):
        with scratch_directory() as tmp:
            fixture = r3.build_fixture(tmp)
            decision = fixture["authority"].evaluate(fixture["candidate"], now=NOW)
            self.assertEqual(decision.action, "QUALIFY")
            records = fixture["records"]
            record = records.get(decision.qualification_record_id)
            copy = SyntheticQualificationRecordStore(
                tmp / "copy" / "qualifications.jsonl",
                outputs=records.outputs, bindings=records.bindings,
            )
            derived = selection.QualificationRecord.create(**{
                **{key: value for key, value in record.to_dict().items()
                   if key != "qualification_record_id"},
                "candidate_id": "caller-derived-candidate",
                "evaluated_at": "2026-01-01T00:12:00Z",
            })
            for store, attempt in ((copy, record), (records, derived)):
                try:
                    store.append(attempt)
                except RegistryConflict:
                    pass
                reopened = SyntheticQualificationRecordStore(
                    store.log.path, outputs=records.outputs, bindings=records.bindings,
                )
                for reader in (store, reopened):
                    with self.assertRaises(RegistryConflict):
                        reader.get_for_new_risk(attempt.qualification_record_id)
                with self.assertRaises(RegistryConflict):
                    store.append(attempt)
            # The authority's own record cannot be re-appended by a caller either.
            with self.assertRaises(RegistryConflict):
                records.append(record)
            self.assertEqual(copy.verify(), 0)
            self.assertEqual(records.verify(), 1)

    def test_e1_the_authority_record_stays_spendable_after_reopening(self):
        with scratch_directory() as tmp:
            fixture = r3.build_fixture(tmp)
            first = fixture["authority"].evaluate(fixture["candidate"], now=NOW)
            second = fixture["authority"].evaluate(fixture["candidate"], now=NOW)
            self.assertEqual((first.action, first), ("QUALIFY", second))
            records = fixture["records"]
            self.assertEqual(
                records.get_for_new_risk(first.qualification_record_id),
                records.get(first.qualification_record_id),
            )
            reopened = SyntheticQualificationRecordStore(
                records.log.path, outputs=records.outputs, bindings=records.bindings,
            )
            self.assertEqual(
                reopened.get_for_new_risk(first.qualification_record_id),
                records.get(first.qualification_record_id),
            )
            self.assertEqual(reopened.verify(), 1)
            self.assertEqual(len(reopened.witnesses.records()), 1)


if __name__ == "__main__":
    unittest.main()
