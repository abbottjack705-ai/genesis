"""Post-S5 B7 mode/safety submission-head probes (synthetic PAPER only)."""

from __future__ import annotations

import inspect
import unittest

from genesis.config import OperationalMode
from genesis.execution import (
    ModeController,
    ModeState,
    ModeStateStore,
    OrderState,
    PaperExecutionAdapter,
)
from genesis.registry import RegistryConflict
from genesis.risk import SafetyState

from ._support import scratch_directory
from .test_remediation_r5_risk import build_risk, request as risk_request
from .test_remediation_r6_execution import build_execution


READY = "2026-01-01T00:14:00Z"
CHANGED = "2026-01-01T00:15:00Z"
ACTION = "2026-01-01T00:16:00Z"


def synthetic_mode_case(root):
    case = build_execution(root)
    case["adapter"].create_intent(case["intent"])
    case["adapter"].bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
    modes = case["risk_fixture"].get("modes")
    if modes is None:  # sealed pre-B7 fixture compatibility for RED evidence
        modes = ModeStateStore(root / "mode-admission.jsonl")
        modes.append(ModeState.create(
            mode=OperationalMode.PAPER,
            occurred_at="2026-01-01T00:00:00Z",
            authorization_id="synthetic-test-only-paper",
            parent_state_id=None,
        ))
    return case, modes


def adapter_with_modes(case, modes):
    """The same test runs on the audited base, which has no modes argument."""
    if "modes" not in inspect.signature(PaperExecutionAdapter).parameters:
        return case["adapter"]
    return PaperExecutionAdapter(
        case["root"] / "orders.jsonl",
        risk=case["risk_fixture"]["engine"],
        markets=case["markets"],
        refreshes=case["refreshes"],
        strategy_view=case["adapter"].strategy_view,
        action_clock=lambda requested_at: requested_at,
        modes=modes,
    )


def no_new_event(adapter, phase, at=ACTION):
    before = len(adapter._audit.records())
    try:
        adapter.transition("key-a", phase, occurred_at=at)
    except RegistryConflict:
        blocked = True
    else:
        blocked = False
    rows = adapter._audit.records()
    return blocked and len(rows) == before and not any(
        row.get("to_state") == phase.value for row in rows[before:]
    )


class AstraModeSafetyFenceTests(unittest.TestCase):
    def test_risk_admission_requires_coherent_current_paper_mode(self):
        with scratch_directory() as root:
            case = build_risk(root)
            engine = case["engine"]
            if not hasattr(engine, "modes"):
                raise AssertionError("risk admission has no durable mode authority")
            engine.modes = None
            before = len(case["audit"].log.records())
            decision = engine.approve(risk_request(case))
            self.assertFalse(decision.passed)
            self.assertEqual(decision.reason, "mode_safety_head_not_coherent_paper")
            self.assertEqual(len(case["audit"].log.records()), before)

    def test_risk_admission_denies_partial_mode_safety_transition(self):
        with scratch_directory() as root:
            case = build_risk(root)
            engine = case["engine"]
            if not hasattr(engine, "modes"):
                raise AssertionError("risk admission has no durable mode authority")
            modes = case["modes"]
            modes.append(ModeState.create(
                mode=OperationalMode.DISABLED,
                occurred_at=CHANGED,
                authorization_id=None,
                parent_state_id=modes.current().state_id,
            ))
            before = len(case["audit"].log.records())
            decision = engine.approve(risk_request(case, requested_at=ACTION))
            self.assertFalse(decision.passed)
            self.assertEqual(decision.reason, "mode_safety_head_not_coherent_paper")
            self.assertEqual(len(case["audit"].log.records()), before)

    def test_current_disabled_mode_blocks_pending_and_sent_even_with_safe_head(self):
        with scratch_directory() as root:
            for phase in (OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT):
                with self.subTest(phase=phase.value):
                    case, modes = synthetic_mode_case(root / phase.value)
                    adapter = adapter_with_modes(case, modes)
                    if phase == OrderState.SUBMISSION_SENT:
                        adapter.transition(
                            "key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY
                        )
                    ModeController(
                        modes, case["risk_fixture"]["safety"]
                    ).transition(OperationalMode.DISABLED, occurred_at=CHANGED)
                    self.assertFalse(
                        case["risk_fixture"]["safety"].current().kill_switch_active
                    )
                    self.assertTrue(
                        no_new_event(adapter, phase),
                        "DISABLED mode with non-kill safety authorized submission",
                    )

    def test_crash_after_mode_row_before_safety_row_denies_new_action(self):
        with scratch_directory() as root:
            for phase in (OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT):
                with self.subTest(phase=phase.value):
                    case, modes = synthetic_mode_case(root / phase.value)
                    adapter = adapter_with_modes(case, modes)
                    if phase == OrderState.SUBMISSION_SENT:
                        adapter.transition(
                            "key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY
                        )
                    modes.append(
                        ModeState.create(
                            mode=OperationalMode.DISABLED,
                            occurred_at=CHANGED,
                            authorization_id=None,
                            parent_state_id=modes.current().state_id,
                        )
                    )
                    # Simulate process death before ModeController writes safety.
                    self.assertFalse(
                        case["risk_fixture"]["safety"].current().kill_switch_active
                    )
                    self.assertTrue(
                        no_new_event(adapter, phase),
                        "a partial mode/safety transition authorized submission",
                    )

    def test_unpaired_safe_safety_row_blocks_new_action(self):
        with scratch_directory() as root:
            case, modes = synthetic_mode_case(root)
            adapter = adapter_with_modes(case, modes)
            safety = case["risk_fixture"]["safety"]
            safety.append(
                SafetyState.create(
                    kill_switch_active=False,
                    recorded_at=CHANGED,
                    reason="synthetic-unpaired-safe-head",
                    parent_state_id=safety.current().state_id,
                )
            )
            self.assertEqual(modes.current().mode, OperationalMode.PAPER)
            self.assertTrue(
                no_new_event(adapter, OrderState.SUBMISSION_PENDING),
                "an unpaired safety head was treated as coherent PAPER permission",
            )

    def test_missing_mode_owner_denies_pending(self):
        with scratch_directory() as root:
            case, _modes = synthetic_mode_case(root)
            try:
                adapter = adapter_with_modes(case, None)
            except (TypeError, RegistryConflict):
                return  # Constructor denial is also a fail-closed result.
            self.assertTrue(
                no_new_event(adapter, OrderState.SUBMISSION_PENDING),
                "missing durable mode authority authorized submission",
            )

    def test_coherent_paper_mode_permits_synthetic_pending_and_sent(self):
        with scratch_directory() as root:
            case, modes = synthetic_mode_case(root)
            adapter = adapter_with_modes(case, modes)
            self.assertEqual(
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY
                ).state,
                OrderState.SUBMISSION_PENDING,
            )
            self.assertEqual(
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_SENT, occurred_at=ACTION
                ).state,
                OrderState.SUBMISSION_SENT,
            )

    def test_mode_disable_does_not_block_old_matched_order_settlement(self):
        with scratch_directory() as root:
            case, modes = synthetic_mode_case(root)
            adapter = adapter_with_modes(case, modes)
            adapter.transition("key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY)
            adapter.transition("key-a", OrderState.SUBMISSION_SENT, occurred_at=ACTION)
            adapter.transition(
                "key-a", OrderState.ACK_RECEIVED,
                occurred_at="2026-01-01T00:17:00Z",
            )
            adapter.transition(
                "key-a", OrderState.FULLY_MATCHED,
                occurred_at="2026-01-01T00:18:00Z",
            )
            ModeController(modes, case["risk_fixture"]["safety"]).transition(
                OperationalMode.DISABLED, occurred_at="2026-01-01T00:19:00Z"
            )
            self.assertEqual(
                adapter.transition(
                    "key-a", OrderState.SETTLED,
                    occurred_at="2026-01-01T00:20:00Z",
                ).state,
                OrderState.SETTLED,
            )


if __name__ == "__main__":
    unittest.main()
