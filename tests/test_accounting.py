from __future__ import annotations

import unittest
from decimal import Decimal

from genesis.accounting import (
    SettlementKind,
    expected_value,
    implied_probability,
    settle_back,
    settle_lay,
)


class AccountingTests(unittest.TestCase):
    def test_odds_and_back_arithmetic(self):
        self.assertEqual(implied_probability("2.00"), Decimal("0.5"))
        self.assertEqual(settle_back("10", "2.50", SettlementKind.WIN).pnl, Decimal("15.00"))
        self.assertEqual(settle_back("10", "2.50", SettlementKind.LOSS).pnl, Decimal("-10.00"))
        self.assertEqual(settle_back("10", "2.50", SettlementKind.WIN, commission_rate="0.05").pnl, Decimal("14.25"))

    def test_void_nonrunner_dead_heat_and_lay(self):
        self.assertEqual(settle_back("10", "3", SettlementKind.VOID).pnl, Decimal("0.00"))
        self.assertEqual(settle_back("10", "3", SettlementKind.NON_RUNNER).returned_stake, Decimal("10.00"))
        self.assertEqual(settle_back("10", "3", SettlementKind.DEAD_HEAT, dead_heat_fraction="0.5").pnl, Decimal("10.00"))
        self.assertEqual(settle_lay("10", "3", SettlementKind.WIN).pnl, Decimal("-20.00"))
        self.assertEqual(settle_lay("10", "3", SettlementKind.LOSS, commission_rate="0.05").pnl, Decimal("9.50"))

    def test_expected_value_is_not_the_selection_objective(self):
        self.assertEqual(expected_value("0.5", "2"), Decimal("0.0"))

