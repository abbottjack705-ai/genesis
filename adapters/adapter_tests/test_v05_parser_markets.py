"""MKT-01, MKT-03 .. MKT-09, F-15 .. F-20: markets, lines, selections and prices."""

from __future__ import annotations

import ast
import copy
import unittest
from decimal import Decimal
from pathlib import Path

from genesis_adapters.oddspapi import parser

from . import parser_support as ps
from .parser_support import (
    FIXTURE_A, FIXTURE_B, POLICY, books_by, dump_with, exclusion_counts, fixture_of, market_of, odds_payload,
    one_book, parse, price_of,
)

OU = "SOCCER_TOTAL_GOALS_OU_FT"
ONE_X_TWO = "SOCCER_1X2_FT"
DECLARED = {"pinnacle", "fixture-book-a", "fixture-book-b"}


def implied(*odds: Decimal) -> Decimal:
    """The overround exactly as the parser computes it (same context, same order)."""

    total = Decimal(0)
    for value in odds:
        total = parser._DECIMAL.add(total, parser._DECIMAL.divide(Decimal(1), value))
    return total


class BookEnumerationTests(unittest.TestCase):
    def test_mkt01_three_bookmakers_by_two_families_give_six_distinct_books_per_event(self):
        parsed = parse(odds_payload())
        self.assertIsNone(parsed.failure)
        self.assertEqual(len(parsed.books), 12)
        self.assertTrue(all(book.state == "OPEN" for book in parsed.books))
        for fixture in (FIXTURE_A, FIXTURE_B):
            books = books_by(parsed, fixture=fixture)
            self.assertEqual(len(books), 6)
            self.assertEqual(len({book.entity_id for book in books}), 6)
            for family in (ONE_X_TWO, OU):
                members = [book for book in books if book.market_family == family]
                self.assertEqual({book.provider_bookmaker_key for book in members}, DECLARED)
                self.assertEqual(len({book.market_id for book in members}), 1)     # one market, three books
                self.assertEqual(len({book.entity_id for book in members}), 3)
        self.assertEqual({b.line for b in parsed.books if b.market_family == OU}, {"2.5"})
        self.assertEqual({b.line for b in parsed.books if b.market_family == ONE_X_TWO}, {None})

    def test_mkt01_undeclared_bookmakers_and_exchanges_are_excluded_and_counted(self):
        parsed = parse(odds_payload())
        self.assertEqual(exclusion_counts(parsed)["OUT_OF_SCOPE_BOOKMAKER"], 4)     # 2 fixtures x (c + exchange)
        self.assertFalse({b.provider_bookmaker_key for b in parsed.books} - DECLARED)

    def test_the_order_of_fixtures_bookmakers_and_markets_does_not_change_the_result(self):
        payload = odds_payload()
        shuffled = copy.deepcopy(payload)
        shuffled.reverse()
        for item in shuffled:
            item["bookmakerOdds"] = dict(reversed(list(item["bookmakerOdds"].items())))
            for block in item["bookmakerOdds"].values():
                block["markets"] = dict(reversed(list(block["markets"].items())))
        first, second = parse(payload), parse(shuffled)
        self.assertEqual([b.entity_id for b in first.books], [b.entity_id for b in second.books])
        self.assertEqual(ps.documents(first), ps.documents(second))


class LineTests(unittest.TestCase):
    def test_mkt03_only_the_exact_2_5_line_is_emitted_and_other_lines_are_counted_never_merged(self):
        parsed = parse(odds_payload())          # the base payload carries 1.5, 2.25, 2.5, 2.75 and 3.5
        self.assertEqual(exclusion_counts(parsed)["OUT_OF_SCOPE_LINE"], 24)          # 4 lines x 3 books x 2 events
        self.assertEqual(one_book(parsed).line, "2.5")
        self.assertEqual(len(books_by(parsed, family=OU)), 3)

    def test_mkt03_the_literal_2_50_is_the_same_line_as_2_5(self):
        base = one_book(parse(odds_payload()))
        payload = odds_payload()
        for outcome in market_of(payload, "pinnacle", "1010")["outcomes"].values():
            outcome["handicap"] = "@h"
        again = one_book(parse(dump_with(payload, h="2.50")))
        self.assertEqual((again.line, again.market_id, again.entity_id, again.state),
                         (base.line, base.market_id, base.entity_id, "OPEN"))

    def test_mkt03_a_line_typed_as_a_numeric_string_is_read_exactly(self):
        payload = odds_payload()
        for outcome in market_of(payload, "pinnacle", "1010")["outcomes"].values():
            outcome["handicap"] = "2.50"
        self.assertEqual(one_book(parse(payload)).state, "OPEN")

    def test_mkt03_2_4999_is_excluded_and_never_rounded_into_2_5(self):
        payload = odds_payload()
        for outcome in market_of(payload, "pinnacle", "1010")["outcomes"].values():
            outcome["handicap"] = "@h"
        parsed = parse(dump_with(payload, h="2.4999"))
        self.assertEqual(books_by(parsed, bookmaker="pinnacle", family=OU), [])
        self.assertEqual(exclusion_counts(parsed)["OUT_OF_SCOPE_LINE"], 25)

    def test_mkt05_a_missing_or_unreadable_line_is_excluded_not_guessed(self):
        cases = {"missing": lambda outcomes: [o.pop("handicap") for o in outcomes.values()],
                 "not numeric": lambda outcomes: [o.__setitem__("handicap", "two and a half")
                                                  for o in outcomes.values()],
                 "disagreeing": lambda outcomes: outcomes["2002"].__setitem__("handicap", 1.5)}
        for label, break_line in cases.items():
            with self.subTest(label):
                payload = odds_payload()
                break_line(market_of(payload, "pinnacle", "1010")["outcomes"])
                parsed = parse(payload)
                self.assertEqual(books_by(parsed, bookmaker="pinnacle", family=OU), [], label)
                self.assertEqual(exclusion_counts(parsed)["LINE_UNIDENTIFIED"], 1, label)

    def test_mkt05_a_line_from_an_undeclared_source_is_excluded(self):
        payload = odds_payload()
        market_of(payload, "pinnacle", "101")["outcomes"]["101"]["handicap"] = 0     # 1X2 declares no line source
        parsed = parse(payload)
        self.assertEqual(books_by(parsed, bookmaker="pinnacle", family=ONE_X_TWO), [])
        self.assertEqual(exclusion_counts(parsed)["LINE_UNIDENTIFIED"], 1)

    def test_mkt04_identical_duplicate_2_5_markets_collapse_to_one_open_book(self):
        payload = odds_payload()
        block = fixture_of(payload)["bookmakerOdds"]["pinnacle"]["markets"]
        block["1011"] = copy.deepcopy(block["1010"])                                 # a second entry, same line
        parsed = parse(payload)
        book = one_book(parsed)
        self.assertEqual((book.state, book.reasons), ("OPEN", ()))
        self.assertEqual(book.selections["OVER"]["odds_decimal"], "1.91")

    def test_mkt04_and_f18_differing_duplicate_2_5_markets_block_the_book(self):
        payload = odds_payload()
        block = fixture_of(payload)["bookmakerOdds"]["pinnacle"]["markets"]
        block["1011"] = copy.deepcopy(block["1010"])
        block["1011"]["outcomes"]["2002"]["players"]["0"]["price"] = 1.96
        parsed = parse(payload)
        book = one_book(parsed)
        self.assertEqual((book.state, book.reasons), ("BLOCKED", ("CONTRADICTORY_DUPLICATE",)))
        self.assertIsNone(book.selections)


class SelectionTests(unittest.TestCase):
    def test_mkt06_and_f19_a_1x2_book_without_the_draw_is_blocked_as_incomplete(self):
        payload = odds_payload()
        del market_of(payload, "pinnacle", "101")["outcomes"]["102"]
        book = one_book(parse(payload), family=ONE_X_TWO)
        self.assertEqual((book.state, book.reasons), ("BLOCKED", ("INCOMPLETE_SELECTIONS",)))
        self.assertIsNone(book.selections)

    def test_mkt06_and_f19_an_extra_unmapped_outcome_blocks_the_book(self):
        payload = odds_payload()
        outcomes = market_of(payload, "pinnacle", "101")["outcomes"]
        outcomes["999"] = copy.deepcopy(outcomes["101"])
        book = one_book(parse(payload), family=ONE_X_TWO)
        self.assertEqual((book.state, book.reasons), ("BLOCKED", ("UNMAPPED_OUTCOME",)))

    def test_mkt09_outcomes_are_mapped_by_provider_outcome_id_only(self):
        payload = odds_payload()
        base = ps.documents(parse(payload))
        swapped = copy.deepcopy(payload)
        outcomes = market_of(swapped, "pinnacle", "1010")["outcomes"]
        first, second = (outcomes[key]["players"]["0"] for key in ("2001", "2002"))
        first["bookmakerOutcomeId"], second["bookmakerOutcomeId"] = "under", "over"    # labels swapped
        first["playerName"], second["playerName"] = "Under", "Over"
        self.assertEqual(ps.documents(parse(swapped)), base)                          # ids decide, labels never

    def test_swapping_the_outcome_ids_swaps_the_selections(self):
        payload = odds_payload()
        outcomes = market_of(payload, "pinnacle", "1010")["outcomes"]
        outcomes["2001"], outcomes["2002"] = outcomes["2002"], outcomes["2001"]
        book = one_book(parse(payload))
        self.assertEqual((book.selections["OVER"]["odds_decimal"], book.selections["UNDER"]["odds_decimal"]),
                         ("1.95", "1.91"))

    def test_more_than_one_price_entry_is_a_contradiction_unless_identical(self):
        payload = odds_payload()
        players = price_of(payload, "pinnacle", "101", "101")
        outcomes = market_of(payload, "pinnacle", "101")["outcomes"]
        outcomes["101"]["players"]["1"] = copy.deepcopy(players)
        self.assertEqual(one_book(parse(payload), family=ONE_X_TWO).state, "OPEN")     # identical: collapses
        outcomes["101"]["players"]["1"]["price"] = 2.2
        book = one_book(parse(payload), family=ONE_X_TWO)
        self.assertEqual((book.state, book.reasons), ("BLOCKED", ("CONTRADICTORY_DUPLICATE",)))


class PriceTests(unittest.TestCase):
    def blocked_reason(self, payload_edit):
        payload = odds_payload()
        payload_edit(payload)
        book = one_book(parse(payload))
        return book.state, book.reasons

    def test_mkt07_and_f20_prices_at_or_below_even_money_on_an_active_outcome_are_contradictory(self):
        for value in ("1.0", "0", "-2", "0.5"):
            with self.subTest(value):
                payload = odds_payload()
                price_of(payload, "pinnacle", "1010", "2001")["price"] = "@p"
                book = one_book(parse(dump_with(payload, p=value)))
                self.assertEqual((book.state, book.reasons), ("BLOCKED", ("CONTRADICTORY_STATUS",)), value)
                self.assertIsNone(book.selections)

    def test_mkt07_the_price_band_and_precision_come_from_the_policy(self):
        low, high = Decimal(POLICY.odds_min), Decimal(POLICY.odds_max)
        places = POLICY.odds_max_fraction_digits
        unit = Decimal(1).scaleb(-places)
        self.assertIsNone(parser._price_problem(low, POLICY))
        self.assertIsNone(parser._price_problem(high, POLICY))
        self.assertEqual(parser._price_problem(low - unit, POLICY).value, "INVALID_PRICE")
        self.assertEqual(parser._price_problem(high + unit, POLICY).value, "INVALID_PRICE")
        self.assertIsNone(parser._price_problem(Decimal("1.5") + unit, POLICY))
        too_precise = Decimal("1.5") + unit / 10                                       # one digit more than allowed
        self.assertEqual(parser._price_problem(too_precise, POLICY).value, "INVALID_PRICE")
        self.assertIsNone(parser._price_problem(Decimal("1.5000"), POLICY))            # trailing zeros are not digits

    def test_mkt07_and_f20_parse_level_invalid_prices_block_the_book(self):
        unit = Decimal(1).scaleb(-POLICY.odds_max_fraction_digits)
        for label, value in (("above the maximum", str(Decimal(POLICY.odds_max) + unit)),
                             ("one digit too many", "1.91" + "0" * (POLICY.odds_max_fraction_digits - 2) + "1"),
                             ("below the minimum", str(Decimal(POLICY.odds_min) - unit))):
            with self.subTest(label):
                payload = odds_payload()
                price_of(payload, "pinnacle", "1010", "2001")["price"] = "@p"
                book = one_book(parse(dump_with(payload, p=value)))
                self.assertEqual((book.state, book.reasons), ("BLOCKED", ("INVALID_PRICE",)), label)

    def test_mkt07_an_active_outcome_without_a_price_is_contradictory(self):
        for edit in (lambda p: price_of(p, "pinnacle", "1010", "2001").pop("price"),
                     lambda p: price_of(p, "pinnacle", "1010", "2001").__setitem__("price", None)):
            payload = odds_payload()
            edit(payload)
            book = one_book(parse(payload))
            self.assertEqual((book.state, book.reasons), ("BLOCKED", ("CONTRADICTORY_STATUS",)))

    def test_mkt07_literals_are_exact_decimals_and_never_pass_through_float(self):
        payload = odds_payload()
        price_of(payload, "pinnacle", "1010", "2001")["price"] = "@over"
        price_of(payload, "pinnacle", "1010", "2002")["price"] = "@under"
        book = one_book(parse(dump_with(payload, over="1.910", under="2")))
        self.assertEqual((book.selections["OVER"]["odds_decimal"], book.selections["UNDER"]["odds_decimal"]),
                         ("1.91", "2"))
        odd = odds_payload()
        price_of(odd, "pinnacle", "1010", "2001")["price"] = "@p"
        price_of(odd, "pinnacle", "1010", "2002")["price"] = "@u"
        book = one_book(parse(dump_with(odd, p="2.675", u="1.5")))    # 2.675 has no exact binary float
        self.assertEqual(book.selections["OVER"]["odds_decimal"], "2.675")
        for module in (parser, ps.normalize):
            source = Path(module.__file__).read_text(encoding="utf-8")
            names = {node.id for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Name)}
            self.assertNotIn("float", names, module.__name__)

    def test_mkt07_non_finite_numbers_reject_the_whole_response(self):
        for body in (b"[NaN]", b"[Infinity]", b"[-Infinity]"):
            parsed = parse(body)
            self.assertEqual(parsed.failure.value, "NONFINITE_NUMBER")
            self.assertEqual((parsed.books, parsed.tombstones), ((), ()))

    def test_mkt08_and_f20_overround_bands_are_inclusive_and_exact(self):
        # the band edges are built from the actual sum of the fixture prices, so the test moves with the policy
        payload = odds_payload()
        home, draw, away = (Decimal(str(price_of(payload, "pinnacle", "101", key)["price"]))
                            for key in ("101", "102", "103"))
        total = implied(home, draw, away)
        tiny = Decimal("1E-30")
        upper = POLICY.overround_1x2[1]
        exact = parser._DECIMAL                       # the same 40-digit context the parser sums in
        for label, band, expected in (
                ("low edge is inside", (str(total), upper), "OPEN"),
                ("just under the low edge is outside", (str(exact.add(total, tiny)), upper), "BLOCKED"),
                ("high edge is inside", (POLICY.overround_1x2[0], str(total)), "OPEN"),
                ("just over the high edge is outside",
                 (POLICY.overround_1x2[0], str(exact.subtract(total, tiny))), "BLOCKED")):
            with self.subTest(label):
                book = one_book(parse(payload, policy=ps.policy_with(overround_1x2=list(band))),
                                family=ONE_X_TWO)
                self.assertEqual(book.state, expected, label)
                if expected == "BLOCKED":
                    self.assertEqual(book.reasons, ("PRICE_INCOHERENT",))

    def test_mkt08_the_over_under_band_is_separate_from_the_1x2_band(self):
        payload = odds_payload()
        over, under = (Decimal(str(price_of(payload, "pinnacle", "1010", key)["price"])) for key in ("2001", "2002"))
        total = implied(over, under)
        below = str(parser._DECIMAL.subtract(total, Decimal("1E-30")))
        book = one_book(parse(payload, policy=ps.policy_with(overround_ou=[POLICY.overround_ou[0], str(total)])))
        self.assertEqual(book.state, "OPEN")
        book = one_book(parse(payload, policy=ps.policy_with(overround_ou=[POLICY.overround_ou[0], below])))
        self.assertEqual((book.state, book.reasons), ("BLOCKED", ("PRICE_INCOHERENT",)))
        again = one_book(parse(payload, policy=ps.policy_with(overround_ou=[POLICY.overround_ou[0], below])),
                         family=ONE_X_TWO)
        self.assertEqual(again.state, "OPEN")                       # the 1X2 band was not touched


class ScopeExclusionTests(unittest.TestCase):
    def test_f16_a_competition_outside_the_allowlist_is_counted_and_never_normalized(self):
        payload = odds_payload()
        fixture_of(payload, FIXTURE_B)["tournamentId"] = 999
        parsed = parse(payload)
        self.assertEqual(exclusion_counts(parsed)["OUT_OF_SCOPE_COMPETITION"], 1)
        self.assertEqual(books_by(parsed, fixture=FIXTURE_B), [])
        self.assertEqual(len(books_by(parsed, fixture=FIXTURE_A)), 6)

    def test_f16_a_fixture_of_another_sport_is_out_of_scope(self):
        payload = odds_payload()
        fixture_of(payload, FIXTURE_B)["sportId"] = 11
        parsed = parse(payload)
        self.assertEqual(exclusion_counts(parsed)["OUT_OF_SCOPE_COMPETITION"], 1)
        self.assertEqual(books_by(parsed, fixture=FIXTURE_B), [])

    def test_f17_unmapped_markets_are_counted_and_never_normalized(self):
        payload = odds_payload()
        block = fixture_of(payload)["bookmakerOdds"]["pinnacle"]["markets"]
        block["9999"] = copy.deepcopy(block["101"])
        parsed = parse(payload)
        self.assertEqual(exclusion_counts(parsed)["OUT_OF_SCOPE_MARKET"], 1)
        self.assertEqual(len(books_by(parsed, fixture=FIXTURE_A, bookmaker="pinnacle")), 2)

    def test_f15_a_provider_partial_flag_emits_present_books_and_no_tombstones(self):
        parsed = parse(odds_payload())
        scope = ps.scope_of(parsed)
        payload = odds_payload()
        del fixture_of(payload, FIXTURE_B)["bookmakerOdds"]["pinnacle"]["markets"]["101"]     # one book missing
        partial = parse(payload, expected_scope=scope, complete_hint=False)
        self.assertTrue(partial.partial)
        self.assertFalse(partial.complete)
        self.assertEqual(len(partial.books), 11)
        self.assertEqual(partial.tombstones, ())
        self.assertEqual(exclusion_counts(partial)["PARTIAL_RESPONSE"], 1)
        complete = parse(payload, expected_scope=scope)
        self.assertTrue(complete.complete)
        self.assertEqual(len(complete.tombstones), 1)                  # the same absence in a COMPLETE response

    def test_f15_a_missing_required_list_makes_the_response_partial(self):
        parsed = parse(odds_payload())
        scope = ps.scope_of(parsed)
        payload = odds_payload()
        del fixture_of(payload, FIXTURE_B)["bookmakerOdds"]["pinnacle"]["markets"]            # required list gone
        del fixture_of(payload, FIXTURE_A)["bookmakerOdds"]["fixture-book-a"]                 # a true absence
        result = parse(payload, expected_scope=scope)
        self.assertTrue(result.partial)
        self.assertEqual(result.tombstones, ())                                               # none anywhere
        blocked = books_by(result, fixture=FIXTURE_B, bookmaker="pinnacle")
        self.assertEqual({(b.state, b.reasons) for b in blocked}, {("BLOCKED", ("SCHEMA_DRIFT",))})


if __name__ == "__main__":
    unittest.main()
