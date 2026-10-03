"""SCH-01 .. SCH-03, F-38: closed provider schemas and additive drift, at exactly the design 10.1 scope."""

from __future__ import annotations

import copy
import json
import unittest

from genesis_adapters import errors as err
from genesis_adapters import jsonstrict, schema

from . import parser_support as ps
from .parser_support import (
    FIXTURE_A, FIXTURE_B, books_by, fixture_of, market_of, odds_payload, one_book, parse, price_of, reasons_of,
)

BLOCKED_DRIFT = {("BLOCKED", ("SCHEMA_DRIFT",))}


def add_key(target):
    target["surprise"] = "x"


class DriftScopeTests(unittest.TestCase):
    """An added unknown key in each semantic structure blocks exactly the entities it can affect."""

    def books_state(self, parsed, **filters):
        return {(b.state, b.reasons) for b in books_by(parsed, **filters)}

    def test_sch01_a_key_added_to_an_outcome_blocks_that_book_only(self):
        payload = odds_payload()
        add_key(market_of(payload, "pinnacle", "1010")["outcomes"]["2001"])
        parsed = parse(payload)
        book = one_book(parsed)
        self.assertEqual((book.state, book.reasons), ("BLOCKED", ("SCHEMA_DRIFT",)))
        self.assertIsNone(book.selections)
        self.assertEqual(self.books_state(parsed, bookmaker="pinnacle", family="SOCCER_1X2_FT"), {("OPEN", ())})
        self.assertEqual(self.books_state(parsed, bookmaker="fixture-book-a"), {("OPEN", ())})
        self.assertEqual(self.books_state(parsed, fixture=FIXTURE_B), {("OPEN", ())})

    def test_sch01_a_key_added_to_a_price_or_a_market_blocks_that_book_only(self):
        for label, edit in (("price", lambda p: add_key(price_of(p, "pinnacle", "1010", "2001"))),
                            ("market", lambda p: add_key(market_of(p, "pinnacle", "1010")))):
            with self.subTest(label):
                payload = odds_payload()
                edit(payload)
                parsed = parse(payload)
                self.assertEqual((one_book(parsed).state, one_book(parsed).reasons), ("BLOCKED", ("SCHEMA_DRIFT",)))
                self.assertEqual(one_book(parsed, family="SOCCER_1X2_FT").state, "OPEN")
                self.assertEqual(one_book(parsed, bookmaker="fixture-book-a").state, "OPEN")

    def test_sch01_a_line_of_the_wrong_type_blocks_the_book_that_would_carry_it(self):
        payload = odds_payload()
        market_of(payload, "pinnacle", "1010")["outcomes"]["2001"]["handicap"] = [2.5]
        parsed = parse(payload)
        book = one_book(parsed)
        self.assertEqual((book.state, book.reasons), ("BLOCKED", ("SCHEMA_DRIFT",)))
        self.assertEqual(ps.exclusion_counts(parsed).get("LINE_UNIDENTIFIED", 0), 0)     # blocked, not dropped
        self.assertEqual(self.books_state(parsed, bookmaker="fixture-book-a"), {("OPEN", ())})

    def test_sch01_a_key_added_to_a_bookmaker_block_blocks_its_books_in_that_event(self):
        payload = odds_payload()
        add_key(fixture_of(payload)["bookmakerOdds"]["pinnacle"])
        parsed = parse(payload)
        self.assertEqual(self.books_state(parsed, bookmaker="pinnacle"), BLOCKED_DRIFT)
        self.assertEqual(len(books_by(parsed, bookmaker="pinnacle")), 2)
        self.assertEqual(self.books_state(parsed, bookmaker="fixture-book-a"), {("OPEN", ())})
        self.assertEqual(self.books_state(parsed, fixture=FIXTURE_B, bookmaker="pinnacle"), {("OPEN", ())})

    def test_sch01_a_key_added_to_the_fixture_blocks_every_book_of_that_event(self):
        payload = odds_payload()
        add_key(fixture_of(payload))
        parsed = parse(payload)
        self.assertEqual(self.books_state(parsed), BLOCKED_DRIFT)
        self.assertEqual(len(books_by(parsed)), 6)
        self.assertEqual(self.books_state(parsed, fixture=FIXTURE_B), {("OPEN", ())})

    def test_sch01_status_and_participant_fields_of_the_wrong_type_stay_at_event_scope(self):
        payload = odds_payload()
        fixture_of(payload)["statusId"] = "0"
        self.assertEqual(self.books_state(parse(payload)), {("BLOCKED", ("UNKNOWN_EVENT_STATUS",))})
        payload = odds_payload()
        fixture_of(payload)["participant1Id"] = "35"
        self.assertEqual(self.books_state(parse(payload)), {("BLOCKED", ("PARTICIPANT_AMBIGUOUS",))})

    def test_sch01_the_same_key_declared_inert_is_accepted_and_never_read(self):
        base = parse(odds_payload())
        for object_name, target in (("fixture", lambda p: fixture_of(p)),
                                    ("bookmaker_block", lambda p: fixture_of(p)["bookmakerOdds"]["pinnacle"]),
                                    ("market", lambda p: market_of(p, "pinnacle", "1010")),
                                    ("outcome", lambda p: market_of(p, "pinnacle", "1010")["outcomes"]["2001"]),
                                    ("price", lambda p: price_of(p, "pinnacle", "1010", "2001"))):
            with self.subTest(object_name):
                payload = odds_payload()
                target(payload)["surprise"] = "anything at all"
                strict = parse(payload)
                self.assertEqual([f.kind for f in strict.findings], ["UNKNOWN_KEY"])       # drift by default
                self.assertIn("BLOCKED", {b.state for b in strict.books})
                tolerant = parse(payload, response_schema=ps.schema_with_inert(object_name, "surprise"))
                self.assertEqual(tolerant.findings, ())
                self.assertEqual(ps.documents(tolerant), ps.documents(base))    # the inert value never reaches a document

    def test_sch02_a_wrong_json_type_for_a_known_key_is_drift_at_its_scope(self):
        cases = (("price as text", lambda p: price_of(p, "pinnacle", "1010", "2001").__setitem__("price", "1.91")),
                 ("players as list", lambda p: market_of(p, "pinnacle", "1010")["outcomes"]["2001"]
                  .__setitem__("players", [])),
                 ("outcomes as list", lambda p: market_of(p, "pinnacle", "1010").__setitem__("outcomes", [])),
                 ("outcome as text", lambda p: market_of(p, "pinnacle", "1010")["outcomes"]
                  .__setitem__("2001", "text")))
        for label, edit in cases:
            with self.subTest(label):
                payload = odds_payload()
                edit(payload)
                parsed = parse(payload)
                book = one_book(parsed)
                self.assertEqual((book.state, book.reasons), ("BLOCKED", ("SCHEMA_DRIFT",)), label)
                self.assertIsNone(book.selections)
                self.assertEqual(self.books_state(parsed, bookmaker="fixture-book-a"), {("OPEN", ())}, label)

    def test_sch02_a_missing_required_key_is_drift_and_makes_the_response_partial(self):
        payload = odds_payload()
        del market_of(payload, "pinnacle", "1010")["outcomes"]["2001"]["players"]
        parsed = parse(payload)
        self.assertTrue(parsed.partial)
        book = one_book(parsed)
        self.assertEqual((book.state, book.reasons), ("BLOCKED", ("SCHEMA_DRIFT",)))
        self.assertEqual(ps.exclusion_counts(parsed)["PARTIAL_RESPONSE"], 1)


class EnvelopeTests(unittest.TestCase):
    def rejected(self, body):
        parsed = parse(body, expected_scope=ps.scope_of(parse(odds_payload())))
        self.assertIsNotNone(parsed.failure)
        self.assertEqual((parsed.books, parsed.tombstones, parsed.identity_rows), ((), (), ()))
        self.assertFalse(parsed.complete)
        return parsed.failure

    def test_sch03_envelope_level_drift_rejects_the_response_with_no_observation_and_no_tombstone(self):
        self.assertEqual(self.rejected(b'{"fixtures": []}'), err.AdapterFailure.ENVELOPE_SCHEMA_MISMATCH)
        self.assertEqual(self.rejected(b'["not an object"]'), err.AdapterFailure.ENVELOPE_SCHEMA_MISMATCH)
        payload = odds_payload()
        del payload[0]["fixtureId"]
        self.assertEqual(self.rejected(ps.dump(payload)), err.AdapterFailure.ENVELOPE_SCHEMA_MISMATCH)
        payload = odds_payload()
        payload[0]["fixtureId"] = 7
        self.assertEqual(self.rejected(ps.dump(payload)), err.AdapterFailure.ENVELOPE_SCHEMA_MISMATCH)

    def test_f38_response_level_drift_maps_to_the_frozen_schema_rejected_reason(self):
        for failure in (err.AdapterFailure.SCHEMA_DRIFT, err.AdapterFailure.ENVELOPE_SCHEMA_MISMATCH):
            self.assertEqual(err.reason_code(failure).value, "schema_rejected")

    def test_the_body_must_be_strict_json_before_anything_else(self):
        cases = {b"": "NOT_JSON", b"{": "NOT_JSON", b'[{"a":1,"a":2}]': "DUPLICATE_KEYS", b"[\xff]": "INVALID_UTF8",
                 b"[NaN]": "NONFINITE_NUMBER"}
        for body, code in cases.items():
            with self.subTest(body):
                self.assertEqual(parse(body).failure.value, code)

    def test_an_empty_response_to_a_request_that_named_tournaments_is_partial_and_tombstones_nothing(self):
        # Hostile audit F-03 / R-3: this test used to assert the defect ("an empty response is complete and
        # tombstones every expected book"). Design 12.4 / F-15: nothing proves those books absent.
        scope = ps.scope_of(parse(odds_payload(), requested_competitions=ps.REQUESTED_COMPETITIONS))
        parsed = parse(b"[]", expected_scope=scope, requested_competitions=ps.REQUESTED_COMPETITIONS)
        self.assertFalse(parsed.complete)
        self.assertEqual((parsed.tombstones, parsed.books), ((), ()))
        vacuous = parse(b"[]", expected_scope={}, requested_competitions=())
        self.assertTrue(vacuous.complete)                    # nothing requested and nothing expected


class DocumentLevelDriftTests(unittest.TestCase):
    def test_f38_a_drift_blocked_book_has_a_document_without_selections(self):
        payload = odds_payload()
        add_key(market_of(payload, "pinnacle", "1010"))
        parsed = parse(payload)
        book = one_book(parsed)
        document = ps.document_of(parsed, book.entity_id)
        self.assertEqual((document["market_state"], document["state_reasons"]), ("BLOCKED", ["SCHEMA_DRIFT"]))
        self.assertNotIn("selections", document)
        self.assertIsNone(document["valid_to"])

    def test_the_closed_validator_reports_stable_trails_for_every_finding(self):
        payload = odds_payload()
        add_key(price_of(payload, "pinnacle", "1010", "2001"))
        decoded = jsonstrict.loads_strict(ps.dump(payload), max_bytes=ps.POLICY.max_response_bytes,
                                          max_depth=ps.POLICY.json_max_depth,
                                          max_exponent=ps.POLICY.json_max_number_exponent)
        findings = schema.validate_closed(decoded, ps.ODDS_SCHEMA)
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual((finding.kind, finding.scope), ("UNKNOWN_KEY", "BOOK"))
        self.assertEqual(finding.trail, (0, "bookmakerOdds", "pinnacle", "markets", "1010", "outcomes", "2001",
                                         "players", "0", "surprise"))
        self.assertEqual(finding, schema.DriftFinding(finding.path, "UNKNOWN_KEY", "BOOK"))     # trail is not identity


if __name__ == "__main__":
    unittest.main()
