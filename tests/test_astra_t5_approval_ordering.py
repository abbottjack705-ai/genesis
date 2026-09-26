"""T5 / B6 observation O-5: human approval must exist before it is relied on.

Invariant: a V3 qualification is durably recorded only while the exact,
unrevoked human grant for its output binding already exists (checked under the
approval-ledger lock). A grant appended after a qualification - including a
backdated one - therefore can never be the grant that admits that
qualification to risk. The production validator is used here; no fixture
approval override is involved.
"""

from __future__ import annotations

import contextlib
import unittest

import genesis.decision_output as decision_output
import genesis.selection as selection
from genesis.execution import OrderState
from genesis.registry import RegistryConflict

from . import test_remediation_r5_risk as r5
from . import test_remediation_r6_execution as r6
from ._support import scratch_directory


ORIGINAL_REGISTER = decision_output.StrategyOutputRuleBindingStore.register_approved


@contextlib.contextmanager
def production_approvals(mode: str, state: dict):
    """Reserve a genuine v2 reference; grant it (or not) before qualification."""

    def register(self, body):
        approvals = decision_output.StrategyOutputApprovalStore(
            self.log.path.parent / "strategy-output-approvals-v2.jsonl"
        )
        reference = approvals.reserve(
            request_id=f"t5-{mode}", reserved_by="synthetic-operator",
            reserved_at="2025-12-31T22:00:00Z",
        )
        binding_hash = ORIGINAL_REGISTER(self, dict(body, human_approval_reference=reference))
        state.update(reference=reference, binding_hash=binding_hash, approvals=approvals)
        grants = {
            "prior": (binding_hash, "2025-12-31T23:00:00Z"),
            "wrong": ("0" * 64, "2025-12-31T23:00:00Z"),
            "late": (binding_hash, "2026-01-01T00:00:01Z"),
        }
        if mode in grants:
            granted_hash, approved_at = grants[mode]
            approvals.grant(
                reference, binding_hash=granted_hash,
                approved_by="synthetic-operator", approved_at=approved_at,
            )
        return binding_hash

    saved = (r5.QualificationRecordStore, r6.QualificationRecordStore)
    decision_output.StrategyOutputRuleBindingStore.register_approved = register
    r5.QualificationRecordStore = selection.QualificationRecordStore
    r6.QualificationRecordStore = selection.QualificationRecordStore
    try:
        yield
    finally:
        decision_output.StrategyOutputRuleBindingStore.register_approved = ORIGINAL_REGISTER
        r5.QualificationRecordStore, r6.QualificationRecordStore = saved


class T5ApprovalOrderingTests(unittest.TestCase):
    def test_qualification_requires_its_exact_prior_grant_when_recorded(self):
        for mode in ("none", "wrong", "late"):
            with self.subTest(mode=mode), scratch_directory() as root:
                with production_approvals(mode, {}):
                    with self.assertRaises(
                        (RegistryConflict, ValueError),
                        msg=f"O-5: a V3 qualification was recorded with grant mode {mode!r}",
                    ):
                        r5.build_risk(root)

    def test_grant_appended_after_the_qualification_never_admits_risk(self):
        with scratch_directory() as root:
            state: dict = {}
            with production_approvals("none", state):
                try:
                    fixture = r5.build_risk(root)
                except (RegistryConflict, ValueError):
                    return
            state["approvals"].grant(
                state["reference"], binding_hash=state["binding_hash"],
                approved_by="synthetic-operator", approved_at="2025-12-31T23:59:59Z",
            )
            decision = fixture["engine"].approve(r5.request(fixture))
            self.assertFalse(
                decision.passed, "O-5: a backdated grant appended after qualification admitted risk",
            )

    def test_prior_grant_admits_risk_and_submission_through_production_validator(self):
        with scratch_directory() as root:
            with production_approvals("prior", {}):
                fixture = r6.build_execution(root)
            adapter = fixture["adapter"]
            self.assertIs(
                type(fixture["risk_fixture"]["qualifications"]), selection.QualificationRecordStore,
            )
            adapter.create_intent(fixture["intent"])
            adapter.bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
            adapter.transition("key-a", OrderState.SUBMISSION_PENDING, occurred_at="2026-01-01T00:14:00Z")
            sent = adapter.transition(
                "key-a", OrderState.SUBMISSION_SENT, occurred_at="2026-01-01T00:15:00Z",
            )
            self.assertEqual(sent.state, OrderState.SUBMISSION_SENT)


if __name__ == "__main__":
    unittest.main()
