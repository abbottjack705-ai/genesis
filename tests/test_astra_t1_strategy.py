"""Independent post-S5 B7 regression tests; all authorities are synthetic PAPER fixtures.

These tests do not assert that any real strategy, adapter, or campaign is approved.
The order tests deliberately exercise the old boolean view as a *negative* input:
its answer has no durable strategy-head fence and cannot authorize a new action.
"""

from __future__ import annotations

import unittest

from genesis.execution import OrderState
from genesis.registry import (
    RegistryConflict,
    StrategyArtifact,
    StrategyLifecycle,
    StrategyRegistry,
)

from ._support import scratch_directory
from .test_remediation_r6_execution import ActiveStrategyView, build_execution


READY = "2026-01-01T00:14:00Z"
WITHDRAWN = "2026-01-01T00:15:00Z"
ACTION = "2026-01-01T00:16:00Z"


def strategy_at_paper(root) -> StrategyRegistry:
    """Synthetic same-id fixture; PAPER here is test data, not an approval."""
    registry = StrategyRegistry(root / "strategies.jsonl")
    registry.register(
        StrategyArtifact(
            "strategy",
            "v1",
            StrategyLifecycle.IDEA,
            "1" * 64,
            "2" * 64,
            "3" * 64,
            "synthetic-test-only",
            "2025-12-31T23:00:00Z",
        )
    )
    for state, at in (
        (StrategyLifecycle.EXPLORATION, "2025-12-31T23:01:00Z"),
        (StrategyLifecycle.WALK_FORWARD, "2025-12-31T23:02:00Z"),
        (StrategyLifecycle.PROTECTED, "2025-12-31T23:03:00Z"),
        (StrategyLifecycle.PROSPECTIVE_SHADOW, "2025-12-31T23:04:00Z"),
        (StrategyLifecycle.PAPER, "2025-12-31T23:05:00Z"),
    ):
        registry.transition("strategy", "v1", state, occurred_at=at)
    return registry


def bound_case(root):
    case = build_execution(root)
    case["adapter"].create_intent(case["intent"])
    case["adapter"].bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
    return case


def seed_pending_history(case) -> None:
    """Seed a historical pending row; do not authorize it through today's gate."""
    case["adapter"]._audit.append(
        {
            "record_type": "order_state_transition",
            "schema_version": "order-event-v2",
            "order_id": case["intent"].order_id,
            "from_state": OrderState.RISK_APPROVED.value,
            "to_state": OrderState.SUBMISSION_PENDING.value,
            "occurred_at": READY,
        }
    )


def transition_blocked_without_append(case, phase: OrderState, at: str = ACTION) -> bool:
    adapter = case["adapter"]
    before = len(adapter._audit.records())
    try:
        adapter.transition("key-a", phase, occurred_at=at)
    except RegistryConflict:
        blocked = True
    else:
        blocked = False
    after = adapter._audit.records()
    # The invariant is the event stream, not merely the exception type.
    return blocked and len(after) == before and not any(
        row.get("to_state") == phase.value for row in after[before:]
    )


class RetireAfterTrueRead:
    """Reproduces the original stale-true view with a durable withdrawal."""

    def __init__(self, registry: StrategyRegistry):
        self.registry = registry
        self.called = False

    def is_active(self, candidate_decision_hash: str, at: str) -> bool:
        del candidate_decision_hash, at
        was_paper = (
            self.registry.get("strategy", "v1").lifecycle
            == StrategyLifecycle.PAPER
        )
        self.registry.transition(
            "strategy", "v1", StrategyLifecycle.RETIRED, occurred_at=WITHDRAWN
        )
        self.called = True
        return was_paper


class BackdatedRegistryBooleanView:
    """Legacy view incorrectly substitutes historical PIT for current permission."""

    def __init__(self, registry: StrategyRegistry):
        self.registry = registry

    def is_active(self, candidate_decision_hash: str, at: str) -> bool:
        del candidate_decision_hash
        return (
            self.registry.lifecycle_at("strategy", "v1", at)
            == StrategyLifecycle.PAPER
        )


class AstraStrategyFenceTests(unittest.TestCase):
    def test_boolean_strategy_view_cannot_authorize_pending_or_sent(self):
        with scratch_directory() as root:
            for phase in (OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT):
                with self.subTest(phase=phase.value):
                    case = bound_case(root / phase.value)
                    if phase == OrderState.SUBMISSION_SENT:
                        seed_pending_history(case)
                    case["adapter"].strategy_view = ActiveStrategyView()
                    self.assertTrue(
                        transition_blocked_without_append(case, phase),
                        "unfenced caller boolean authorized a new order state",
                    )

    def test_true_read_then_committed_withdrawal_cannot_append_new_action(self):
        with scratch_directory() as root:
            for phase in (OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT):
                with self.subTest(phase=phase.value):
                    case = bound_case(root / phase.value)
                    if phase == OrderState.SUBMISSION_SENT:
                        seed_pending_history(case)
                    registry = strategy_at_paper(root / phase.value)
                    view = RetireAfterTrueRead(registry)
                    case["adapter"].strategy_view = view
                    blocked = transition_blocked_without_append(case, phase)
                    if view.called:
                        self.assertEqual(
                            StrategyRegistry(root / phase.value / "strategies.jsonl")
                            .get("strategy", "v1")
                            .lifecycle,
                            StrategyLifecycle.RETIRED,
                            "withdrawal must be durable before judging the action",
                        )
                    self.assertTrue(
                        blocked,
                        "new action appended after the strategy withdrawal committed",
                    )

    def test_backdated_order_event_does_not_restore_withdrawn_strategy(self):
        with scratch_directory() as root:
            case = bound_case(root)
            registry = strategy_at_paper(root)
            registry.transition(
                "strategy", "v1", StrategyLifecycle.RETIRED, occurred_at=WITHDRAWN
            )
            # Historical PIT qualification is still PAPER at the decision time.
            self.assertEqual(
                registry.lifecycle_at("strategy", "v1", "2026-01-01T00:00:00Z"),
                StrategyLifecycle.PAPER,
            )
            case["adapter"].strategy_view = BackdatedRegistryBooleanView(registry)
            # An earlier caller timestamp is not current authority for a send.
            self.assertTrue(
                transition_blocked_without_append(
                    case, OrderState.SUBMISSION_PENDING, at=READY
                ),
                "backdated caller time bypassed a durable strategy withdrawal",
            )

    def test_cross_instance_current_head_replays_committed_retirement(self):
        with scratch_directory() as root:
            first = strategy_at_paper(root)
            second = StrategyRegistry(root / "strategies.jsonl")
            first.transition(
                "strategy", "v1", StrategyLifecycle.RETIRED, occurred_at=WITHDRAWN
            )
            self.assertEqual(
                second.get("strategy", "v1").lifecycle,
                StrategyLifecycle.RETIRED,
                "a stale in-process strategy cache hid the durable head",
            )
            self.assertEqual(
                second.lifecycle_at("strategy", "v1", "2026-01-01T00:00:00Z"),
                StrategyLifecycle.PAPER,
                "current-head repair changed historical PIT meaning",
            )

    def test_cross_instance_duplicate_registration_is_rejected(self):
        with scratch_directory() as root:
            first = StrategyRegistry(root / "strategies.jsonl")
            second = StrategyRegistry(root / "strategies.jsonl")
            artifact = StrategyArtifact(
                "strategy", "v1", StrategyLifecycle.IDEA,
                "1" * 64, "2" * 64, "3" * 64,
                "synthetic-test-only", "2025-12-31T23:00:00Z",
            )
            first.register(artifact)
            with self.assertRaises(
                RegistryConflict,
                msg="a second process registered the same strategy version",
            ):
                second.register(artifact)


if __name__ == "__main__":
    unittest.main()
