"""E5: submission recertification re-checks the pinned odds profile.

Invariant: an order is recertified for pending or sent only while its order
price and the current executable price both lie within its decision output's
requested odds bounds and inside the active odds profile the output pins (the
profile test qualification applies). A move that is merely better for the
side, higher for BACK or lower for LAY, is not enough. Market snapshots are
durable, so an order reopened after restart is recertified the same way.
"""

from __future__ import annotations

import unittest

from genesis.accounting import BetSide
from genesis.execution import ExecutionMarketSnapshot, OrderState
from genesis.registry import RegistryConflict

from ._support import scratch_directory
from .test_remediation_r6_execution import build_execution, restart_adapter, restart_risk


def bound_case(root, side: BetSide):
    case = build_execution(root, side=side, odds="2.00")
    case["adapter"].create_intent(case["intent"])
    case["adapter"].bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
    return case


def move(case, executable_odds: str, observed_at: str) -> None:
    case["markets"].append(ExecutionMarketSnapshot.create(
        candidate_decision_hash=case["intent"].candidate_decision_hash,
        observed_at=observed_at, market_open=True,
        executable_odds=executable_odds, available_liquidity="100",
    ))


class T6E5RecertifyOddsProfileTests(unittest.TestCase):
    # Pinned profile: the active normal profile [1.50, 3.00], which is also
    # the synthetic output's requested bounds. 1.45 is in the exceptional
    # profile, which the output does not pin.
    OUTSIDE = ((BetSide.BACK, "3.01"), (BetSide.BACK, "4.50"), (BetSide.LAY, "1.45"))
    EDGES = ((BetSide.BACK, "3.00"), (BetSide.LAY, "1.50"))

    def test_e5_pending_is_refused_when_the_executable_price_leaves_the_profile(self):
        for side, odds in self.OUTSIDE:
            with self.subTest(side=side.value, odds=odds), scratch_directory() as root:
                case = bound_case(root, side)
                move(case, odds, "2026-01-01T00:14:00Z")
                for adapter in (case["adapter"], restart_adapter(root, restart_risk(root))):
                    result = adapter.recertify("key-a", at="2026-01-01T00:16:00Z")
                    self.assertFalse(result.passed, f"E5: {side.value} sendable at {odds}")
                    self.assertEqual(result.reason, "executable_price_outside_odds_profile")
                    with self.assertRaises(RegistryConflict):
                        adapter.transition(
                            "key-a", OrderState.SUBMISSION_PENDING,
                            occurred_at="2026-01-01T00:16:00Z",
                        )
                    self.assertEqual(adapter.get("key-a").state, OrderState.RISK_APPROVED)

    def test_e5_sent_is_refused_when_the_price_leaves_the_profile_after_pending(self):
        for side, odds in self.OUTSIDE:
            with self.subTest(side=side.value, odds=odds), scratch_directory() as root:
                case = bound_case(root, side)
                adapter = case["adapter"]
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at="2026-01-01T00:14:00Z",
                )
                move(case, odds, "2026-01-01T00:15:00Z")
                with self.assertRaises(RegistryConflict, msg=f"E5: {side.value} sent at {odds}"):
                    adapter.transition(
                        "key-a", OrderState.SUBMISSION_SENT, occurred_at="2026-01-01T00:16:00Z",
                    )
                self.assertEqual(adapter.get("key-a").state, OrderState.SUBMISSION_PENDING)

    def test_e5_prices_at_the_profile_edges_still_recertify(self):
        for side, odds in self.EDGES:
            with self.subTest(side=side.value, odds=odds), scratch_directory() as root:
                case = bound_case(root, side)
                move(case, odds, "2026-01-01T00:14:00Z")
                adapter = restart_adapter(root, restart_risk(root))
                self.assertTrue(adapter.recertify("key-a", at="2026-01-01T00:16:00Z").passed)
                self.assertEqual(
                    adapter.transition(
                        "key-a", OrderState.SUBMISSION_PENDING,
                        occurred_at="2026-01-01T00:16:00Z",
                    ).state,
                    OrderState.SUBMISSION_PENDING,
                )


if __name__ == "__main__":
    unittest.main()
