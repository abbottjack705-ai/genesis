"""ST-02 .. ST-06, F-23 .. F-27: provider status allowlists, contradictions, suspension and non-pre-match."""

from __future__ import annotations

import unittest

from . import parser_support as ps
from .parser_support import (
    FIXTURE_A, FIXTURE_B, T1, books_by, exclusion_counts, fixture_of, iso_add, market_of, odds_payload, one_book,
    parse, price_of, reasons_of, set_all_outcomes,
)

OU = "SOCCER_TOTAL_GOALS_OU_FT"
ONE_X_TWO = "SOCCER_1X2_FT"


class EventStatusTests(unittest.TestCase):
    def test_st02_and_f23_an_unknown_event_status_blocks_every_book_of_the_event_and_only_that_event(self):
        payload = odds_payload()
        fixture_of(payload)["statusId"] = 9
        parsed = parse(payload)
        self.assertEqual(reasons_of(parsed), {("BLOCKED", ("UNKNOWN_EVENT_STATUS",))})
        self.assertTrue(all(book.selections is None for book in books_by(parsed)))
        self.assertEqual(len(books_by(parsed)), 6)
        self.assertEqual(reasons_of(parsed, fixture=FIXTURE_B), {("OPEN", ())})

    def test_st06_a_status_of_the_wrong_json_type_is_unknown_not_a_number(self):
        for value in ("0", True, False, "PREMATCH", None):
            with self.subTest(value=value):
                payload = odds_payload()
                fixture_of(payload)["statusId"] = value
                self.assertEqual(reasons_of(parse(payload)), {("BLOCKED", ("UNKNOWN_EVENT_STATUS",))})

    def test_st06_a_missing_event_status_is_unknown(self):
        payload = odds_payload()
        del fixture_of(payload)["statusId"]
        self.assertEqual(reasons_of(parse(payload)), {("BLOCKED", ("UNKNOWN_EVENT_STATUS",))})

    def test_f26_an_event_that_is_not_pre_match_blocks_every_book_when_no_price_is_active(self):
        for status_id in (1, 2, 3):                                  # live, finished, cancelled
            with self.subTest(status_id):
                payload = odds_payload()
                fixture_of(payload)["statusId"] = status_id
                set_all_outcomes(payload, active=False)
                self.assertEqual(reasons_of(parse(payload)), {("BLOCKED", ("EVENT_NOT_PREMATCH",))})

    def test_st04_and_f24_a_finished_event_with_an_active_price_is_contradictory(self):
        payload = odds_payload()
        fixture_of(payload)["statusId"] = 2
        parsed = parse(payload)
        self.assertEqual(reasons_of(parsed), {("BLOCKED", ("CONTRADICTORY_STATUS",))})
        self.assertTrue(all(book.selections is None for book in books_by(parsed)))

    def test_f26_an_expected_book_missing_from_a_not_pre_match_event_is_blocked_not_absent(self):
        scope = ps.scope_of(parse(odds_payload()))
        payload = odds_payload()
        fixture_of(payload)["statusId"] = 2
        del fixture_of(payload)["bookmakerOdds"]["pinnacle"]["markets"]["101"]
        parsed = parse(payload, expected_scope=scope)
        book = one_book(parsed, family=ONE_X_TWO)
        self.assertEqual((book.state, book.reasons), ("BLOCKED", ("EVENT_NOT_PREMATCH",)))
        self.assertEqual(parsed.tombstones, ())


class MarketAndOutcomeStatusTests(unittest.TestCase):
    def test_st03_and_f23_an_unknown_outcome_status_blocks_that_book_only(self):
        for label, edit in (("integer", lambda entry: entry.__setitem__("active", 1)),
                            ("string", lambda entry: entry.__setitem__("active", "true")),
                            ("null", lambda entry: entry.__setitem__("active", None)),
                            ("missing", lambda entry: entry.pop("active"))):
            with self.subTest(label):
                payload = odds_payload()
                edit(price_of(payload, "pinnacle", "1010", "2001"))
                parsed = parse(payload)
                book = one_book(parsed)
                self.assertEqual((book.state, book.reasons), ("BLOCKED", ("UNKNOWN_OUTCOME_STATUS",)), label)
                self.assertIsNone(book.selections)
                self.assertEqual(one_book(parsed, bookmaker="fixture-book-a").state, "OPEN")

    def test_st03_and_f23_an_unknown_bookmaker_level_status_blocks_that_bookmakers_books_in_the_event(self):
        for value in ("yes", 1, None):
            with self.subTest(value):
                payload = odds_payload()
                fixture_of(payload)["bookmakerOdds"]["pinnacle"]["bookmakerIsActive"] = value
                parsed = parse(payload)
                got = {(b.state, b.reasons) for b in books_by(parsed, bookmaker="pinnacle")}
                self.assertEqual(got, {("BLOCKED", ("UNKNOWN_MARKET_STATUS",))})
                self.assertEqual(one_book(parsed, bookmaker="fixture-book-a").state, "OPEN")

    def test_st06_the_boolean_and_the_integer_one_are_different_status_values(self):
        payload = odds_payload()
        price_of(payload, "pinnacle", "1010", "2001")["active"] = 1
        self.assertEqual(one_book(parse(payload)).reasons, ("UNKNOWN_OUTCOME_STATUS",))
        payload = odds_payload()
        price_of(payload, "pinnacle", "1010", "2001")["active"] = True
        self.assertEqual(one_book(parse(payload)).state, "OPEN")

    def test_f25_an_inactive_outcome_suspends_the_book_and_carries_no_prices(self):
        payload = odds_payload()
        price_of(payload, "pinnacle", "1010", "2002")["active"] = False
        book = one_book(parse(payload))
        self.assertEqual((book.state, book.reasons), ("SUSPENDED", ("OUTCOME_INACTIVE",)))
        self.assertIsNone(book.selections)
        self.assertIsNotNone(book.publisher_timestamp)             # provenance is kept for a suspended book

    def test_f25_an_inactive_bookmaker_suspends_all_its_books_in_the_event(self):
        payload = odds_payload()
        fixture_of(payload)["bookmakerOdds"]["pinnacle"]["bookmakerIsActive"] = False
        parsed = parse(payload)
        self.assertEqual({(b.state, b.reasons) for b in books_by(parsed, bookmaker="pinnacle")},
                         {("SUSPENDED", ("MARKET_SUSPENDED",))})
        self.assertEqual(one_book(parsed, bookmaker="fixture-book-a").state, "OPEN")

    def test_a_blocking_problem_outranks_a_suspension(self):
        payload = odds_payload()
        price_of(payload, "pinnacle", "1010", "2002")["active"] = False
        price_of(payload, "pinnacle", "1010", "2001")["active"] = "maybe"
        book = one_book(parse(payload))
        self.assertEqual((book.state, book.reasons), ("BLOCKED", ("UNKNOWN_OUTCOME_STATUS",)))

    def test_st04_an_inactive_outcome_may_carry_any_price_but_an_active_one_may_not_be_invalid(self):
        payload = odds_payload()
        price_of(payload, "pinnacle", "1010", "2002").update(active=False, price=0)
        self.assertEqual(one_book(parse(payload)).state, "SUSPENDED")
        payload = odds_payload()
        price_of(payload, "pinnacle", "1010", "2002").update(active=True, price=0)
        self.assertEqual(one_book(parse(payload)).reasons, ("CONTRADICTORY_STATUS",))


class PrematchWindowTests(unittest.TestCase):
    """F-27 and TS-05/TS-06: the guard before kickoff and a start that is not in the future."""

    def kickoff(self, offset_seconds: float = 0, micros: int = 0) -> str:
        return iso_add(T1, seconds=offset_seconds, micros=micros)

    def parse_with_start(self, start: str):
        payload = odds_payload()
        fixture_of(payload)["startTime"] = start
        return parse(payload)

    def test_ts06_at_the_guard_edge_nothing_is_emitted_and_one_microsecond_earlier_the_book_is_open(self):
        guard = ps.POLICY.prematch_guard_seconds
        at_edge = self.parse_with_start(self.kickoff(guard))                 # T1 = S - guard
        self.assertEqual(books_by(at_edge), [])
        self.assertEqual(exclusion_counts(at_edge)["PREMATCH_WINDOW_CLOSED"], 1)
        inside = self.parse_with_start(self.kickoff(guard, micros=1))       # T1 = S - guard - 1 us
        book = one_book(inside)
        self.assertEqual(book.state, "OPEN")
        document = ps.document_of(inside, book.entity_id)
        self.assertEqual(document["valid_to"], iso_add(T1, micros=1))        # capped at S - guard, not T1 + ttl
        self.assertLess(iso_add(T1, micros=1), iso_add(T1, seconds=ps.POLICY.price_ttl_seconds))

    def test_f27_after_the_guard_no_head_is_created_and_no_tombstone_either(self):
        base = parse(odds_payload())
        scope = ps.scope_of(base)
        event_a = books_by(base)[0].event.event_id
        payload = odds_payload()
        fixture_of(payload)["startTime"] = self.kickoff(ps.POLICY.prematch_guard_seconds - 1)
        parsed = parse(payload, expected_scope=scope)
        self.assertEqual(books_by(parsed), [])
        fixture_a_entities = {key for key, book in scope.items() if book.event_id == event_a}
        self.assertEqual(len(fixture_a_entities), 6)
        self.assertFalse(fixture_a_entities & {tomb.entity_id for tomb in parsed.tombstones})
        self.assertEqual(len(books_by(parsed, fixture=FIXTURE_B)), 6)

    def test_ts05_a_start_at_or_before_receipt_while_pre_match_is_contradictory(self):
        for offset in (0, -1, -3600):
            with self.subTest(offset):
                parsed = self.parse_with_start(self.kickoff(offset))
                self.assertEqual(reasons_of(parsed), {("BLOCKED", ("CONTRADICTORY_STATUS",))})

    def test_a_far_future_start_leaves_the_book_open(self):
        parsed = self.parse_with_start(self.kickoff(48 * 3600))
        self.assertEqual(reasons_of(parsed), {("OPEN", ())})


if __name__ == "__main__":
    unittest.main()
