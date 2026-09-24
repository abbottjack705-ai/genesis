"""Independent post-S5 B2 current-risk admission regressions.

Fixtures are synthetic PAPER authority only.  They do not approve a model,
strategy, adapter, protected campaign, or live-money path.
"""

import unittest
from decimal import Decimal

from genesis.execution import OrderState
from genesis.registry import RegistryConflict
from genesis.risk import Exposure, ExposureState

from ._support import scratch_directory
from .test_remediation_r6_execution import build_execution, restart_risk


def _bound_order(root):
    fixture = build_execution(root)
    fixture["adapter"].create_intent(fixture["intent"])
    fixture["adapter"].bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
    return fixture


def _late_exposure(fixture, liability):
    exposure = Exposure(
        f"independent-{liability}", "f" * 64, liability,
        ExposureState.MATCHED,
    )
    fixture["risk_fixture"]["engine"].record_exposure(
        exposure, recorded_at="2026-01-01T00:15:00Z",
    )
    return exposure


class CurrentPortfolioSubmissionTests(unittest.TestCase):
    def test_original_late_55_blocks_fresh_recertification_and_sent_append(self):
        """The sent gate must reject 7.5 + 55 > 60, without losing either fact."""
        with scratch_directory() as root:
            fixture = _bound_order(root)
            adapter = fixture["adapter"]
            adapter.transition(
                "key-a", OrderState.SUBMISSION_PENDING,
                occurred_at="2026-01-01T00:14:00Z",
            )
            _late_exposure(fixture, "55")
            self.assertFalse(
                adapter.recertify("key-a", at="2026-01-01T00:16:00Z").passed,
                "a fresh recertification ignored the current 62.5 liability",
            )
            with self.assertRaises(RegistryConflict):
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_SENT,
                    occurred_at="2026-01-01T00:16:00Z",
                )
            self.assertEqual(adapter.get("key-a").state, OrderState.SUBMISSION_PENDING)
            self.assertFalse(any(
                row.get("to_state") == OrderState.SUBMISSION_SENT.value
                for row in adapter._audit.records()
            ))
            self.assertEqual(
                sum((e.liability_amount for e in fixture["risk_fixture"]["engine"].reserved_exposures()), Decimal("0")),
                Decimal("62.5"),
            )

    def test_late_55_before_pending_blocks_pending_append(self):
        """PENDING has the same current portfolio obligation as SENT."""
        with scratch_directory() as root:
            fixture = _bound_order(root)
            _late_exposure(fixture, "55")
            adapter = fixture["adapter"]
            with self.assertRaises(RegistryConflict):
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_PENDING,
                    occurred_at="2026-01-01T00:16:00Z",
                )
            self.assertEqual(adapter.get("key-a").state, OrderState.RISK_APPROVED)
            self.assertFalse(any(
                row.get("to_state") == OrderState.SUBMISSION_PENDING.value
                for row in adapter._audit.records()
            ))

    def test_own_reservation_is_counted_once_at_exact_total_cap(self):
        """7.5 own plus 52.5 independent equals 60, not 67.5."""
        with scratch_directory() as root:
            fixture = _bound_order(root)
            _late_exposure(fixture, "52.5")
            adapter = fixture["adapter"]
            self.assertEqual(
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_PENDING,
                    occurred_at="2026-01-01T00:16:00Z",
                ).state, OrderState.SUBMISSION_PENDING,
            )
            self.assertEqual(
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_SENT,
                    occurred_at="2026-01-01T00:17:00Z",
                ).state, OrderState.SUBMISSION_SENT,
            )

    def test_single_increment_above_total_cap_denies_new_submission(self):
        """A 60.01 portfolio is over cap even if the own approval was legal."""
        with scratch_directory() as root:
            fixture = _bound_order(root)
            _late_exposure(fixture, "52.51")
            with self.assertRaises(RegistryConflict):
                fixture["adapter"].transition(
                    "key-a", OrderState.SUBMISSION_PENDING,
                    occurred_at="2026-01-01T00:16:00Z",
                )
            self.assertEqual(
                fixture["adapter"].get("key-a").state,
                OrderState.RISK_APPROVED,
            )

    def test_restart_replays_breach_and_keeps_factual_exposure(self):
        """A new process cannot forget the later matched exposure."""
        with scratch_directory() as root:
            fixture = _bound_order(root)
            _late_exposure(fixture, "55")
            restarted_risk = restart_risk(root)
            self.assertEqual(
                sum((e.liability_amount for e in restarted_risk.reserved_exposures()), Decimal("0")),
                Decimal("62.5"),
            )
            self.assertFalse(
                restarted_risk.approval_still_valid(
                    fixture["risk_decision"].approval_id,
                    at="2026-01-01T00:16:00Z",
                ),
                "restart replayed the exposure but still approved unsafe new submission",
            )
