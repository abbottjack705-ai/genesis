"""BILL-05: the table-driven boundability evaluator (design section 20.1, a G1 human check aid)."""

from __future__ import annotations

import unittest

from genesis.quota import QuotaInterpretation, QuotaPolicy

from genesis_adapters.config import load_policy
from genesis_adapters.oddspapi import boundability as bnd

from .support import CONFIG

POLICY = load_policy(CONFIG / "oddspapi_slice1_policy.json")
FROZEN = QuotaPolicy.test_fixture(QuotaInterpretation.A, provider_monthly_allowance=250,
                                  normal_monthly_budget=220, reserve_units=30, daily_billable_budget=7)

W = bnd.ProviderWindow
T = bnd.RoleTerms


def role(window, metering="PER_REQUEST", weight=1, debit=1):
    return T(role="ODDS", metering=metering, weight=weight, genesis_debit_units=debit, windows=(window,))


def run(terms, mode):
    return bnd.evaluate_boundability(terms, slice_policy=POLICY, quota_policy=FROZEN, mode=mode)


# (label, terms, passes with the section 14.6 guard, passes in fallback W+ mode)
TABLE = [
    ("allowance 300/month (UTC)", role(W("UTC_MONTH", 300)), True, True),
    ("allowance 250/month (UTC)", role(W("UTC_MONTH", 250)), True, True),
    ("allowance 230/month (UTC)", role(W("UTC_MONTH", 230)), False, False),
    ("rolling 30 days, 250", role(W("ROLLING_DAYS", 250, length_days=30)), True, True),
    ("non-UTC calendar month, 250", role(W("NON_UTC_MONTH", 250)), True, True),
    ("UTC-aligned daily 7", role(W("UTC_DAY", 7)), True, False),
    ("UTC-aligned daily 5", role(W("UTC_DAY", 5)), False, False),
    ("non-aligned daily 10", role(W("NON_ALIGNED_DAY", 10)), False, False),
    ("fixed weight 2 (debit 2)", role(W("UTC_MONTH", 300), "FIXED_WEIGHT", 2, 2), True, True),
    ("non-metered", role(W("UTC_MONTH", 300), "NON_METERED", 0, 1), True, True),
]


class BoundabilityTests(unittest.TestCase):
    def test_bill05_table_with_the_guard_and_in_fallback_mode(self):
        for label, terms, guarded, fallback in TABLE:
            self.assertEqual(run(terms, "GUARDED").passes, guarded, f"GUARDED {label}")
            self.assertEqual(run(terms, "FALLBACK").passes, fallback, f"FALLBACK {label}")

    def test_bill05_the_utc_aligned_daily_7_case_passes_only_with_the_guard(self):
        terms = role(W("UTC_DAY", 7))
        guarded, fallback = run(terms, "GUARDED"), run(terms, "FALLBACK")
        self.assertTrue(guarded.passes)
        self.assertFalse(fallback.passes)
        self.assertEqual((guarded.rows[0].days, guarded.rows[0].genesis_max), (1, 7))
        self.assertGreater(fallback.rows[0].days, 1)

    def test_bill05_documented_figures_for_rolling_and_non_utc_month_windows(self):
        rolling = run(role(W("ROLLING_DAYS", 250, length_days=30)), "GUARDED").rows[0]
        self.assertEqual((rolling.days, rolling.genesis_max), (31, 217))
        rolling_fb = run(role(W("ROLLING_DAYS", 250, length_days=30)), "FALLBACK").rows[0]
        self.assertEqual((rolling_fb.days, rolling_fb.genesis_max), (32, 224))
        month = run(role(W("NON_UTC_MONTH", 250)), "GUARDED").rows[0]
        self.assertEqual((month.days, month.genesis_max), (32, 224))
        month_fb = run(role(W("NON_UTC_MONTH", 250)), "FALLBACK").rows[0]
        self.assertEqual((month_fb.days, month_fb.genesis_max), (33, 231))

    def test_bill05_figures_follow_the_policy_values_not_literals(self):
        # The fallback extension is derived from request_timeout_seconds and clock_skew_max_seconds.
        import json
        from genesis_adapters.config import parse_policy
        body = json.loads((CONFIG / "oddspapi_slice1_policy.json").read_text())
        body["request_timeout_seconds"] = 86400 - 2 * body["clock_skew_max_seconds"] - 1 - 82800
        self.assertLess(body["request_timeout_seconds"] + 2 * body["clock_skew_max_seconds"], 3600)
        wide = parse_policy(body)
        row = bnd.evaluate_boundability(role(W("ROLLING_DAYS", 250, length_days=30)), slice_policy=wide,
                                        quota_policy=FROZEN, mode="FALLBACK").rows[0]
        self.assertGreaterEqual(row.days, 32)

    def test_bill05_b2_pre_send_cost_bound(self):
        good = run(role(W("UTC_MONTH", 300), "FIXED_WEIGHT", 2, 2), "GUARDED")
        self.assertTrue(good.b2_ok)
        bad_debit = run(role(W("UTC_MONTH", 300), "FIXED_WEIGHT", 3, 2), "GUARDED")
        self.assertFalse(bad_debit.b2_ok)
        self.assertFalse(bad_debit.passes)
        for metering in ("VARIABLE", "UNKNOWN"):
            result = run(role(W("UTC_MONTH", 300), metering, None, 1), "GUARDED")
            self.assertFalse(result.b2_ok, metering)
            self.assertFalse(result.passes, metering)
        self.assertTrue(run(role(W("UTC_MONTH", 300), "NON_METERED", 0, 1), "GUARDED").b2_ok)

    def test_bill05_rows_explain_themselves(self):
        result = run(role(W("UTC_DAY", 5)), "GUARDED")
        row = result.rows[0]
        self.assertEqual((row.kind, row.limit, row.ok), ("UTC_DAY", 5, False))
        self.assertIn("B1", row.note)
        self.assertEqual(result.mode, "GUARDED")

    def test_bill05_invalid_inputs_are_refused(self):
        with self.assertRaises(ValueError):
            run(role(W("UTC_DAY", 0)), "GUARDED")
        with self.assertRaises(ValueError):
            run(role(W("HOURLY", 5)), "GUARDED")
        with self.assertRaises(ValueError):
            run(role(W("UTC_DAY", 7)), "SIDEWAYS")
        with self.assertRaises(ValueError):
            bnd.evaluate_boundability(T(role="ODDS", metering="PER_REQUEST", weight=1, genesis_debit_units=1,
                                        windows=()), slice_policy=POLICY, quota_policy=FROZEN, mode="GUARDED")


if __name__ == "__main__":
    unittest.main()
