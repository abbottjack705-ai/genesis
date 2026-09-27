"""E7: an approval witness names its ledger as the N2 owner binding does.

Invariant: the F-2 witness's ledger identity is compared exactly as the N2
risk-owner binding compares owner identities (caselessly on Windows, exactly
elsewhere). A ledger that N2 accepts as the risk authority's bound owner
therefore reads the witness its recording wrote, whatever case its name was
opened in, and one ledger never holds two witnesses of one record under two
spellings. The witness still binds the exact grant row; the F-2 suite covers
copied ledgers and revocation. A durable history that already holds two
witnesses of one record naming one ledger is ambiguous and fails closed.
"""

from __future__ import annotations

import os
import unittest

import genesis.decision_output as decision_output
import genesis.selection as selection
from genesis.registry import AppendOnlyJsonl
from genesis.risk import RiskAuditLog, RiskEngine

from . import test_remediation_r5_risk as r5
from ._support import SyntheticRecordingQualificationStore, scratch_directory
from .test_astra_t5_owner_binding import admitted
from .test_astra_t6_approval_causality import (
    LEDGER, recorded, reserved_approval, witnesses_for,
)


VARIANT = "Strategy-Output-Approvals-V2.jsonl"
assert VARIANT != LEDGER and VARIANT.lower() == LEDGER.lower()


def store(root, ledger: str, cls=selection.QualificationRecordStore):
    return cls(
        root / "qualifications.jsonl",
        approvals=decision_output.StrategyOutputApprovalStore(root / ledger),
    )


def engine(f: dict, root, ledger: str) -> RiskEngine:
    return RiskEngine(
        policy=f["policy"], bankrolls=f["bankrolls"], qualifications=store(root, ledger),
        safety=f["safety"], audit_log=RiskAuditLog(root / "risk.jsonl"),
        strategies=f["strategies"], modes=f["modes"],
        action_clock=lambda requested_at: requested_at,
    )


def deferred(state: dict):
    def appender(path):
        qualifications = selection.QualificationRecordStore(path)
        qualifications.record_fixture_qualification = (
            lambda record: state.setdefault("record", record)
        )
        return qualifications

    return appender


@unittest.skipUnless(os.name == "nt", "N2 compares owner identities caselessly only on Windows")
class T6E7WitnessLedgerIdentityTests(unittest.TestCase):
    def test_e7_a_ledger_spelling_n2_accepts_reads_the_recorded_witness(self):
        for recorded_as, spent_as in ((LEDGER, VARIANT), (VARIANT, LEDGER)):
            with self.subTest(recorded_as=recorded_as), scratch_directory() as root:
                state: dict = {}
                with reserved_approval(state, grant=True):
                    f = recorded(root, deferred(state))
                store(root, recorded_as, SyntheticRecordingQualificationStore) \
                    .record_fixture_qualification(state["record"])
                # N2 binds the ledger under one spelling and accepts the other.
                engine(f, root, recorded_as)
                spender = engine(f, root, spent_as)
                self.assertEqual(spender.owner_mismatches(), ())
                decision = spender.approve(r5.request(f))
                self.assertTrue(decision.passed, decision.reason)

    def test_e7_one_ledger_never_holds_two_witnesses_of_one_record(self):
        with scratch_directory() as root:
            state: dict = {}
            with reserved_approval(state, grant=True):
                f = recorded(root, deferred(state))
            record = state["record"]
            store(root, LEDGER)._record_witness(record)
            store(root, VARIANT)._record_witness(record)
            self.assertEqual(len(witnesses_for(root, record.qualification_record_id)), 1)
            store(root, VARIANT, SyntheticRecordingQualificationStore) \
                .record_fixture_qualification(record)
            self.assertEqual(len(witnesses_for(root, record.qualification_record_id)), 1)
            for ledger in (LEDGER, VARIANT):
                with self.subTest(ledger=ledger):
                    self.assertTrue(
                        store(root, ledger).get_for_new_risk(
                            record.qualification_record_id, at="2026-01-01T00:10:00Z",
                        ),
                    )
            decision = engine(f, root, LEDGER).approve(r5.request(f))
            self.assertTrue(decision.passed, decision.reason)

    def test_e7_durable_witnesses_of_one_record_under_two_spellings_fail_closed(self):
        with scratch_directory() as root:
            state: dict = {}
            with reserved_approval(state, grant=True):
                f = recorded(root, deferred(state))
            record = state["record"]
            witness = store(root, LEDGER)._require_prior_grant(record)
            # Durable history as a pre-E7 composition over each spelling could
            # write it: two witnesses of the record, then the record itself.
            raw_witnesses = AppendOnlyJsonl(store(root, LEDGER).witnesses.path)
            raw_witnesses.append(dict(witness))
            raw_witnesses.append(dict(witness, approval_ledger=VARIANT))
            AppendOnlyJsonl(root / "qualifications.jsonl").append(
                {"record_type": "qualification_record", **record.to_dict()}
            )
            self.assertEqual(len(witnesses_for(root, record.qualification_record_id)), 2)
            engine(f, root, LEDGER)
            for ledger in (LEDGER, VARIANT):
                with self.subTest(ledger=ledger):
                    self.assertFalse(admitted(lambda: engine(f, root, ledger).approve(r5.request(f))))


if __name__ == "__main__":
    unittest.main()
