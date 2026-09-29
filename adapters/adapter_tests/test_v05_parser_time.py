"""TS-01 .. TS-05, F-28, F-29: provider timestamps are provenance only; offsets are rejected, never normalized."""

from __future__ import annotations

import copy
import json
import unittest

from genesis_adapters.oddspapi import parser

from . import parser_support as ps
from .parser_support import (
    FIXTURE_A, FIXTURE_DIR, FIXTURE_B, MAPS, POLICY, T1, books_by, exclusion_counts, fixture_of, iso_add,
    odds_payload, one_book, parse, price_of, reasons_of,
)

OU = "SOCCER_TOTAL_GOALS_OU_FT"
SNAPSHOT_OBSERVATION = "f" * 64


def change_of(value):
    payload = odds_payload()
    price_of(payload, "pinnacle", "1010", "2001")["changedAt"] = value
    return one_book(parse(payload))


class OutcomeTimestampTests(unittest.TestCase):
    def test_ts01_a_naive_timestamp_blocks_the_book(self):
        for text in ("2026-10-01T11:58:30", "2026-10-01 11:58:30.123", "2026-10-01"):
            with self.subTest(text):
                book = change_of(text)
                self.assertEqual((book.state, book.reasons), ("BLOCKED", ("TIMESTAMP_NAIVE",)))
                self.assertIsNone(book.selections)

    def test_ts02_an_explicit_non_zero_offset_is_rejected_not_normalized(self):
        for text in ("2026-10-01T12:58:30+01:00", "2026-10-01T06:58:30-05:00", "2026-10-01T11:58:30+00:01"):
            with self.subTest(text):
                book = change_of(text)
                self.assertEqual((book.state, book.reasons), ("BLOCKED", ("TIMESTAMP_NON_UTC",)))

    def test_ts02_a_zero_offset_in_any_spelling_is_utc(self):
        for text in ("2026-10-01T11:58:30Z", "2026-10-01T11:58:30+00:00", "2026-10-01T11:58:30.250Z",
                     "2026-10-01T11:58:30-00:00"):
            with self.subTest(text):
                self.assertEqual(change_of(text).state, "OPEN")

    def test_ts03_unparseable_or_wrongly_typed_timestamps_are_invalid(self):
        for value in ("yesterday", "", "2026-13-45T00:00:00Z", 1759319910, True, None, ["2026-10-01T00:00:00Z"]):
            with self.subTest(value=value):
                book = change_of(value)
                self.assertEqual((book.state, book.reasons), ("BLOCKED", ("TIMESTAMP_INVALID",)))

    def test_ts04_the_future_tolerance_boundary_is_exact(self):
        tolerance = POLICY.provider_future_tolerance_seconds
        edge = iso_add(T1, seconds=tolerance)
        self.assertEqual(change_of(edge).state, "OPEN")                          # T1 + tolerance is accepted
        after = change_of(iso_add(T1, seconds=tolerance, micros=1))
        self.assertEqual((after.state, after.reasons), ("BLOCKED", ("TIMESTAMP_FUTURE",)))
        self.assertEqual(change_of(iso_add(T1, seconds=tolerance + 1)).reasons, ("TIMESTAMP_FUTURE",))

    def test_provider_timestamps_are_provenance_only_and_never_move_freshness(self):
        old = odds_payload()
        price_of(old, "pinnacle", "1010", "2001")["changedAt"] = iso_add(T1, seconds=-30 * 24 * 3600)
        parsed_old, parsed_new = parse(old), parse(odds_payload())
        book = one_book(parsed_old)
        self.assertEqual(book.state, "OPEN")
        doc_old = ps.document_of(parsed_old, book.entity_id)
        doc_new = ps.document_of(parsed_new, one_book(parsed_new).entity_id)
        self.assertEqual((doc_old["valid_from"], doc_old["valid_to"]), (doc_new["valid_from"], doc_new["valid_to"]))
        self.assertEqual(doc_old["valid_from"], T1)
        self.assertEqual(doc_old["valid_to"], iso_add(T1, seconds=POLICY.price_ttl_seconds))

    def test_the_publisher_timestamp_is_the_latest_outcome_timestamp_of_the_book(self):
        payload = odds_payload()
        price_of(payload, "pinnacle", "1010", "2001")["changedAt"] = "2026-10-01T11:50:00.000Z"
        price_of(payload, "pinnacle", "1010", "2002")["changedAt"] = "2026-10-01T11:55:00.500Z"
        parsed = parse(payload)
        book = one_book(parsed)
        self.assertEqual(book.publisher_timestamp, "2026-10-01T11:55:00.500000Z")
        by_entity = {d.entity_id: d for d in ps.documents(parsed)}
        self.assertEqual(by_entity[book.entity_id].publisher_timestamp, "2026-10-01T11:55:00.500000Z")
        document = json.loads(by_entity[book.entity_id].data)
        self.assertEqual(document["provider_timestamps"],
                         {"outcome.2001.changedAt": "2026-10-01T11:50:00.000Z",
                          "outcome.2002.changedAt": "2026-10-01T11:55:00.500Z"})


class EventTimestampTests(unittest.TestCase):
    def test_f28_a_bad_event_level_timestamp_blocks_every_book_of_the_event(self):
        cases = (("updatedAt", "2026-10-01T11:59:00", "TIMESTAMP_NAIVE"),
                 ("updatedAt", "2026-10-01T12:59:00+01:00", "TIMESTAMP_NON_UTC"),
                 ("updatedAt", "garbage", "TIMESTAMP_INVALID"),
                 ("trueStartTime", iso_add(T1, seconds=POLICY.provider_future_tolerance_seconds, micros=1),
                  "TIMESTAMP_FUTURE"),
                 ("trueEndTime", "2026-10-01T13:00:00", "TIMESTAMP_NAIVE"))
        for key, value, expected in cases:
            with self.subTest(key=key, value=value):
                payload = odds_payload()
                fixture_of(payload)[key] = value
                parsed = parse(payload)
                self.assertEqual(reasons_of(parsed), {("BLOCKED", (expected,))})
                self.assertEqual(reasons_of(parsed, fixture=FIXTURE_B), {("OPEN", ())})

    def test_ts05_an_invalid_scheduled_start_is_an_event_start_problem(self):
        for value in ("soon", "2026-10-03T14:00:00", "2026-10-03T15:00:00+01:00", ""):
            with self.subTest(value):
                payload = odds_payload()
                fixture_of(payload)["startTime"] = value
                self.assertEqual(reasons_of(parse(payload)), {("BLOCKED", ("EVENT_START_INVALID",))})

    def test_a_scheduled_start_of_the_wrong_json_type_is_an_invalid_start(self):
        for value in (1759500000, True, None, ["2026-10-03T14:00:00Z"]):
            with self.subTest(value=value):
                payload = odds_payload()
                fixture_of(payload)["startTime"] = value
                self.assertEqual(reasons_of(parse(payload)), {("BLOCKED", ("EVENT_START_INVALID",))})


class FixtureJoinTests(unittest.TestCase):
    """F-29 and design 8.3: a start the ODDS payload lacks comes from the newest FIXTURES capture."""

    def snapshot(self, *, retrieved_at: str, mutate=None):
        body = json.loads((FIXTURE_DIR / "fixtures.json").read_text(encoding="ascii"))
        if mutate:
            mutate(body)
        snap = parser.build_fixture_snapshot(
            json.dumps(body).encode("ascii"), observation_id=SNAPSHOT_OBSERVATION, retrieved_at=retrieved_at,
            maps=MAPS, policy=POLICY, fixtures_schema=ps.FIXTURES_SCHEMA)
        assert snap is not None
        return snap

    def without_start(self):
        payload = odds_payload()
        del fixture_of(payload)["startTime"]
        return payload

    def test_f29_without_a_join_the_event_is_blocked_as_stale_metadata(self):
        parsed = parse(self.without_start())
        self.assertEqual(reasons_of(parsed), {("BLOCKED", ("EVENT_METADATA_STALE",))})
        self.assertEqual(reasons_of(parsed, fixture=FIXTURE_B), {("OPEN", ())})

    def test_a_fresh_join_supplies_the_start_and_is_pinned_in_the_documents(self):
        join = self.snapshot(retrieved_at=iso_add(T1, seconds=-3600))
        parsed = parse(self.without_start(), fixture_join=join)
        self.assertEqual(reasons_of(parsed), {("OPEN", ())})
        book = one_book(parsed)
        self.assertEqual(book.event.scheduled_start_as_known, "2026-10-03T14:00:00.000000Z")
        document = ps.document_of(parsed, book.entity_id)
        self.assertEqual(document["fixture_join_observation_id"], SNAPSHOT_OBSERVATION)
        self.assertEqual(document["scheduled_start_as_known"], "2026-10-03T14:00:00.000000Z")
        direct = ps.document_of(parse(odds_payload()), book.entity_id)
        self.assertIsNone(direct["fixture_join_observation_id"])               # a payload start needs no join

    def test_the_join_age_boundary_is_exact(self):
        limit = POLICY.fixture_join_max_age_seconds
        at_limit = self.snapshot(retrieved_at=iso_add(T1, seconds=-limit))
        self.assertEqual(reasons_of(parse(self.without_start(), fixture_join=at_limit)), {("OPEN", ())})
        older = self.snapshot(retrieved_at=iso_add(T1, seconds=-limit, micros=-1))
        self.assertEqual(reasons_of(parse(self.without_start(), fixture_join=older)),
                         {("BLOCKED", ("EVENT_METADATA_STALE",))})

    def test_a_join_captured_after_the_odds_response_is_never_used(self):
        for offset in (1, 3600):
            with self.subTest(offset):
                join = self.snapshot(retrieved_at=iso_add(T1, micros=offset))
                self.assertEqual(reasons_of(parse(self.without_start(), fixture_join=join)),
                                 {("BLOCKED", ("EVENT_METADATA_STALE",))})

    def test_a_join_that_lacks_the_fixture_or_names_another_competition_is_stale(self):
        missing = self.snapshot(retrieved_at=iso_add(T1, seconds=-60),
                                mutate=lambda rows: rows.__delitem__(0))
        self.assertEqual(reasons_of(parse(self.without_start(), fixture_join=missing)),
                         {("BLOCKED", ("EVENT_METADATA_STALE",))})

        def other_competition(rows):
            rows[0]["tournamentId"] = 8

        moved = self.snapshot(retrieved_at=iso_add(T1, seconds=-60), mutate=other_competition)
        self.assertEqual(reasons_of(parse(self.without_start(), fixture_join=moved)),
                         {("BLOCKED", ("EVENT_METADATA_STALE",))})

    def test_the_snapshot_keeps_only_usable_allowlisted_fixtures(self):
        def spoil(rows):
            rows[0]["tournamentId"] = 999                       # not allowlisted
            rows.append({**rows[1], "fixtureId": "id1000009", "startTime": "2026-10-05T10:00:00"})   # naive start
            rows.append({**rows[1], "fixtureId": "id1000010"})
            rows.append({**rows[1], "fixtureId": "id1000010", "startTime": "2026-10-05T11:00:00.000Z"})

        snap = self.snapshot(retrieved_at=T1, mutate=spoil)
        self.assertEqual(sorted(snap.fixtures), [FIXTURE_B])                     # duplicates that differ are dropped

    def test_the_snapshot_builder_rejects_an_unusable_response(self):
        for body in (b"not json", b"{}", b'[{"fixtureId": 5}]'):
            self.assertIsNone(parser.build_fixture_snapshot(
                body, observation_id=SNAPSHOT_OBSERVATION, retrieved_at=T1, maps=MAPS, policy=POLICY,
                fixtures_schema=ps.FIXTURES_SCHEMA))


if __name__ == "__main__":
    unittest.main()
