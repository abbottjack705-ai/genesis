"""R-3 (hostile audit F-03; design 12.4 and section 15 F-15; oracle PS-06 / TP-12): a requested tournament that is
missing from an ODDS response is an UNPROVEN omission, never a proven absence.

The ODDS payload is a flat fixture list, so a requested tournament is visible only through its fixtures. A
response that carries no in-scope fixture of a requested tournament may simply not contain it: it is partial.
Its well-formed books are still emitted, ``PARTIAL_RESPONSE`` is recorded (REJECTED / MISSING_EVIDENCE), and no
ABSENT tombstone is written - not for the missing tournament and not for any other book of that response. A
tournament that IS present keeps design 12.4's rule: an expected book it no longer carries is absent (F-30).

The pipeline tests go through the real runtime, so the requested set is read from the stored canonical request
(its SHA-256 is the acquisition's request hash), exactly as re-derivation and rebuild read it.
"""

from __future__ import annotations

import copy
import unittest

from genesis_adapters import errors as err
from genesis_adapters.oddspapi import pipeline
from genesis_adapters.oddspapi.reader import UsableBook, admissible_head

from . import parser_support as ps
from .parser_support import FIXTURE_A, FIXTURE_B, fixture_of
from .pipeline_support import (
    acquisition_rows, approve, coverage_rows, documents, odds_item, odds_response, open_rt, pit_rows, reopen, summary,
)
from .support import Crash, FixedClock, scratch_root

A = err.AdapterFailure
PREMIER_LEAGUE = ps.MAPS.competition("int", "17").genesis_id
BOTH = ps.REQUESTED_COMPETITIONS                                   # tournaments 17 and 8
PARTIAL = {("rejected", ("missing_evidence",))}


def only(*fixture_ids, payload=None):
    base = payload if payload is not None else ps.odds_payload()
    return [copy.deepcopy(fixture_of(base, fixture_id)) for fixture_id in fixture_ids]


def run_pair(root, second, *, second_item=None, **kw):
    """A complete first capture (OPEN heads for tournaments 17 and 8), then ``second`` ten minutes later."""

    rt = open_rt(root, script=[odds_response(), odds_response(second)], **kw)
    rt.acquire(odds_item("w1"))
    rt.clock.advance(seconds=600)
    rt.acquire(second_item or odds_item("w2"))
    return rt


def absent_documents(rt) -> list[dict]:
    return [d for d in documents(rt) if d["market_state"] == "ABSENT"]


def notes(rt, note) -> set:
    return {(row["status"], tuple(row["reason_codes"])) for row in coverage_rows(rt)
            if row["note"] == note or row["note"].startswith(note + ":")}


def second_capture(rt) -> list[dict]:
    later = max(row["available_at"] for row in pit_rows(rt))
    return [d for d, row in zip(documents(rt), pit_rows(rt)) if row["available_at"] == later]


def w1_entities(rt, fixture_id) -> list[str]:
    first = min(row["available_at"] for row in pit_rows(rt))
    return sorted(row["entity_id"] for d, row in zip(documents(rt), pit_rows(rt))
                  if row["available_at"] == first and d["provider_fixture_id"]["value"] == fixture_id)


class RequestedTournamentTests(unittest.TestCase):
    def assert_partial_without_tombstones(self, rt):
        self.assertEqual(notes(rt, "PARTIAL_RESPONSE"), PARTIAL)
        self.assertEqual(absent_documents(rt), [])                            # no ABSENT document ...
        self.assertEqual(notes(rt, "BOOK_ABSENT"), set())                     # ... and no ABSENT coverage entry
        normalized = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_normalized"]
        self.assertEqual(len(normalized), 2)                                  # the partial response WAS normalized

    def assert_heads_still_open(self, rt, *fixture_ids):
        """The earlier OPEN heads of an omitted tournament are still the usable heads (not ABSENT)."""

        approve(rt)
        cutoff = ps.iso_add(max(row["ready_at"] for row in pit_rows(rt)), seconds=1)
        for fixture_id in fixture_ids:
            entities = w1_entities(rt, fixture_id)
            self.assertTrue(entities)
            for entity in entities:
                head = admissible_head(entity, cutoff, stores=rt.stores)
                self.assertIsInstance(head, UsableBook, entity)

    # -- the cases of the remediation brief --------------------------------------------------------
    def test_r3_every_requested_tournament_present_with_markets_keeps_proven_absences(self):
        with scratch_root() as root:
            second = ps.odds_payload()
            del fixture_of(second)["bookmakerOdds"]["pinnacle"]["markets"]["1010"]   # one book really gone
            rt = run_pair(root, second)
            self.assertEqual(notes(rt, "PARTIAL_RESPONSE"), set())
            absent = absent_documents(rt)
            self.assertEqual([(d["provider_fixture_id"]["value"], d["bookmaker_id"]) for d in absent],
                             [(FIXTURE_A, "bk.pinnacle")])
            self.assertEqual(notes(rt, "BOOK_ABSENT"), {("available", ())})
            self.assertEqual(rt.verify_all(), len(pit_rows(rt)))

    def test_r3_a_requested_tournament_present_with_no_odds_is_a_proven_absence(self):
        # the provider returned tournament 8's fixture, and it carries no odds: its expected books are absent
        with scratch_root() as root:
            second = ps.odds_payload()
            fixture_of(second, FIXTURE_B)["bookmakerOdds"] = {}
            fixture_of(second, FIXTURE_B)["hasOdds"] = False
            rt = run_pair(root, second)
            self.assertEqual(notes(rt, "PARTIAL_RESPONSE"), set())
            absent = absent_documents(rt)
            self.assertEqual({d["provider_fixture_id"]["value"] for d in absent}, {FIXTURE_B})
            self.assertEqual(sorted(d["entity_id"] for d in absent), w1_entities(rt, FIXTURE_B))
            self.assertEqual(rt.verify_all(), len(pit_rows(rt)))

    def test_r3_one_of_two_requested_tournaments_omitted_is_partial_and_tombstones_nothing(self):
        with scratch_root() as root:
            rt = run_pair(root, only(FIXTURE_A))
            self.assert_partial_without_tombstones(rt)
            later = second_capture(rt)
            self.assertEqual({d["provider_fixture_id"]["value"] for d in later}, {FIXTURE_A})   # A still emitted
            self.assertEqual({d["market_state"] for d in later}, {"OPEN"})
            self.assertEqual(rt.verify_all(), len(pit_rows(rt)))
            self.assert_heads_still_open(rt, FIXTURE_B)

    def test_r3_every_requested_tournament_omitted_is_partial_and_tombstones_nothing(self):
        with scratch_root() as root:
            rt = run_pair(root, [])
            self.assert_partial_without_tombstones(rt)
            self.assertEqual(len(pit_rows(rt)), 12)                           # only the first capture's books
            self.assert_heads_still_open(rt, FIXTURE_A, FIXTURE_B)

    def test_r3_duplicate_blocks_of_one_tournament_never_stand_in_for_an_omitted_one(self):
        twin = only(FIXTURE_A)[0]
        differing = copy.deepcopy(twin)
        differing["participant1Name"] = "Team Alpha Reserves"
        for label, second in (("identical duplicate", only(FIXTURE_A) + [twin]),
                              ("contradictory duplicate", only(FIXTURE_A) + [differing])):
            with self.subTest(label), scratch_root() as root:
                rt = run_pair(root, second)
                self.assert_partial_without_tombstones(rt)
                self.assert_heads_still_open(rt, FIXTURE_B)

    def test_r3_a_tournament_present_only_in_a_malformed_or_foreign_block_counts_as_omitted(self):
        edits = {
            "tournamentId as text": lambda f: f.__setitem__("tournamentId", "8"),
            "tournamentId as a float": lambda f: f.__setitem__("tournamentId", 8.0),
            "tournamentId as a boolean": lambda f: f.__setitem__("tournamentId", True),
            "another sport": lambda f: f.__setitem__("sportId", 11),
            "an unrequested tournament": lambda f: f.__setitem__("tournamentId", 999),
        }
        for label, edit in edits.items():
            with self.subTest(label), scratch_root() as root:
                second = ps.odds_payload()
                edit(fixture_of(second, FIXTURE_B))
                rt = run_pair(root, second)
                self.assertIn(("rejected", ("missing_evidence",)), notes(rt, "PARTIAL_RESPONSE"))
                self.assertEqual(absent_documents(rt), [])
                self.assertEqual(notes(rt, "BOOK_ABSENT"), set())

    def test_r3_a_tournament_block_missing_its_odds_list_is_partial(self):
        with scratch_root() as root:
            second = ps.odds_payload()
            del fixture_of(second, FIXTURE_B)["bookmakerOdds"]
            rt = run_pair(root, second)
            self.assertEqual(notes(rt, "PARTIAL_RESPONSE"), PARTIAL)
            self.assertEqual(absent_documents(rt), [])

    def test_r3_the_requested_set_comes_from_the_request_not_from_earlier_captures(self):
        # a request that names only tournament 17, answered with tournament 17 only, is complete: its expected
        # scope holds only tournament 17's books, and a book tournament 17 no longer carries is a proven absence
        with scratch_root() as root:
            second = only(FIXTURE_A)
            del second[0]["bookmakerOdds"]["pinnacle"]["markets"]["1010"]
            rt = run_pair(root, second, second_item=odds_item("w2", tournaments=(17,)))
            self.assertEqual(notes(rt, "PARTIAL_RESPONSE"), set())
            absent = absent_documents(rt)
            self.assertEqual([(d["provider_fixture_id"]["value"], d["bookmaker_id"]) for d in absent],
                             [(FIXTURE_A, "bk.pinnacle")])
            self.assert_heads_still_open(rt, FIXTURE_B)                       # outside that request's scope

    # -- restart / replay after an incomplete response ------------------------------------------------
    def test_r3_restart_resume_rebuild_and_reverification_after_a_partial_response_never_tombstone(self):
        with scratch_root() as root:
            names: list[tuple[str, str]] = []
            phase = {"window": "w1"}
            clean = open_rt(root / "clean", script=[odds_response(), odds_response(only(FIXTURE_A))],
                            checkpoint=lambda step: names.append((phase["window"], step)))
            clean.acquire(odds_item("w1"))
            phase["window"] = "w2"
            clean.clock.advance(seconds=600)
            clean.acquire(odds_item("w2"))
            baseline = summary(clean)
            self.assertEqual(absent_documents(clean), [])
            target = pipeline.build_stores(root / "rebuilt", derivation_version=clean.config.derivation_version,
                                           policy=clean.config.policy, licensing_note=pipeline.FIXTURE_LICENSING_NOTE)
            rebuilt = pipeline.rebuild_into(clean, target, clock=FixedClock("2026-12-01T00:00:00.000000Z",
                                                                            step_micros=10))
            self.assertEqual(len(rebuilt), 2)
            key = lambda row: (row["entity_id"], row["available_at"], row["payload_hash"], row["record_id"])
            self.assertEqual(sorted(key(r) for r in target.pit.log.records() if r.get("record_type") == "pit_record"),
                             sorted(key(r) for r in pit_rows(clean)))
        steps = sorted({step for window, step in names if window == "w2"})     # steps of the PARTIAL response
        self.assertIn("after_identity", steps)
        for name in steps:
            with self.subTest(crash_after=name), scratch_root() as root:
                armed = {"on": False}

                def hook(step, name=name):
                    if armed["on"] and step == name:
                        raise Crash()

                rt = open_rt(root, script=[odds_response(), odds_response(only(FIXTURE_A))], checkpoint=hook)
                rt.acquire(odds_item("w1"))
                armed["on"] = True                                             # crash inside the second response
                rt.clock.advance(seconds=600)
                with self.assertRaises(Crash):
                    rt.acquire(odds_item("w2"))
                restarted = reopen(rt)
                restarted.resume()
                self.assertEqual(summary(restarted), baseline, name)
                self.assertEqual(absent_documents(restarted), [], name)
                self.assertEqual(restarted.verify_all(), len(pit_rows(restarted)), name)
                self.assertEqual(len(restarted.runner.transport.calls), 0)    # nothing re-sent


class ParserRequestedSetTests(unittest.TestCase):
    """The same rule at the pure parser: ``ParseContext.requested_competitions`` is the request's competitions."""

    def setUp(self):
        self.full = ps.parse(ps.odds_payload(), requested_competitions=BOTH)
        self.scope = ps.scope_of(self.full)

    def test_r3_parser_an_omitted_requested_tournament_makes_the_response_partial(self):
        parsed = ps.parse(only(FIXTURE_A), requested_competitions=BOTH, expected_scope=self.scope)
        self.assertTrue(parsed.partial)
        self.assertEqual(parsed.tombstones, ())
        self.assertEqual(ps.exclusion_counts(parsed).get(A.PARTIAL_RESPONSE.value), 1)
        self.assertEqual({b.event.provider_fixture_id["value"] for b in parsed.books}, {FIXTURE_A})

    def test_r3_parser_an_empty_response_to_a_request_is_partial(self):
        parsed = ps.parse(b"[]", requested_competitions=BOTH, expected_scope=self.scope)
        self.assertEqual((parsed.partial, parsed.tombstones, parsed.books), (True, (), ()))

    def test_r3_parser_a_request_for_the_present_tournament_only_is_complete(self):
        scope = {key: book for key, book in self.scope.items() if book.competition_id == PREMIER_LEAGUE}
        parsed = ps.parse(only(FIXTURE_A), requested_competitions=(PREMIER_LEAGUE,), expected_scope=scope)
        self.assertFalse(parsed.partial)
        self.assertNotIn(A.PARTIAL_RESPONSE.value, ps.exclusion_counts(parsed))

    def test_r3_parser_only_an_exactly_typed_in_scope_tournament_is_present(self):
        for label, value in (("text", "8"), ("float", 8.0), ("boolean", True)):
            with self.subTest(label):
                payload = ps.odds_payload()
                fixture_of(payload, FIXTURE_B)["tournamentId"] = value
                parsed = ps.parse(payload, requested_competitions=BOTH, expected_scope=self.scope)
                self.assertTrue(parsed.partial)
                self.assertEqual(parsed.tombstones, ())
        payload = ps.odds_payload()
        fixture_of(payload, FIXTURE_B)["sportId"] = 11
        self.assertTrue(ps.parse(payload, requested_competitions=BOTH, expected_scope=self.scope).partial)


if __name__ == "__main__":
    unittest.main()
