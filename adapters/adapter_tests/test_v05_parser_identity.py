"""ID-02 .. ID-08, F-21, F-22 and the identity registry: identity comes from provider ids, never from names."""

from __future__ import annotations

import copy
import json
import unittest

from genesis.registry import RegistryConflict

from genesis_adapters import errors as err
from genesis_adapters import ids
from genesis_adapters.oddspapi import identity_registry as reg

from . import parser_support as ps
from .parser_support import (
    FIXTURE_A, FIXTURE_B, books_by, exclusion_counts, fixture_of, odds_payload, one_book, parse, reasons_of,
)
from .support import scratch_root

ONE_X_TWO = "SOCCER_1X2_FT"


def registry_rows(parsed, registry):
    """Apply a parse's proposed rows to a real registry and return its verified prefix."""

    registry.apply(parsed.identity_rows)
    return registry.rows()


class NativeIdTests(unittest.TestCase):
    def test_id02_a_fixture_id_of_the_wrong_json_type_rejects_the_whole_response(self):
        payload = odds_payload()
        fixture_of(payload)["fixtureId"] = 1761301153
        parsed = parse(payload)
        self.assertEqual(parsed.failure, err.AdapterFailure.ENVELOPE_SCHEMA_MISMATCH)
        self.assertEqual(err.reason_code(parsed.failure).value, "schema_rejected")
        self.assertEqual((parsed.books, parsed.tombstones, parsed.identity_rows), ((), (), ()))

    def test_id02_a_fixture_id_outside_the_native_grammar_rejects_the_whole_response(self):
        for value in ("id 1000", "", "x" * 65, "é1"):
            with self.subTest(value):
                payload = odds_payload()
                fixture_of(payload)["fixtureId"] = value
                self.assertEqual(parse(payload).failure, err.AdapterFailure.ENVELOPE_SCHEMA_MISMATCH)

    def test_id02_a_tournament_id_of_the_wrong_type_is_schema_rejected_at_event_scope(self):
        payload = odds_payload()
        fixture_of(payload, FIXTURE_B)["tournamentId"] = "8"
        base = parse(odds_payload())
        scope = ps.scope_of(base)
        parsed = parse(payload, expected_scope=scope)
        self.assertEqual(reasons_of(parsed, fixture=FIXTURE_B), {("BLOCKED", ("SCHEMA_DRIFT",))})
        self.assertEqual(err.reason_code(err.AdapterFailure.SCHEMA_DRIFT).value, "schema_rejected")
        self.assertEqual(reasons_of(parsed), {("OPEN", ())})
        self.assertEqual(parsed.tombstones, ())
        without_history = parse(payload)                                  # nothing known: coverage only
        self.assertEqual(books_by(without_history, fixture=FIXTURE_B), [])
        self.assertEqual(exclusion_counts(without_history)["SCHEMA_DRIFT"], 1)

    def test_id03_participants_come_from_provider_ids_not_names(self):
        base = parse(odds_payload())
        book = one_book(base)
        renamed = odds_payload()
        fixture_of(renamed)["participant1Name"] = "Team Alpha FC"                  # same id, new name
        same = one_book(parse(renamed))
        self.assertEqual((same.event.home_participant_id, same.event.away_participant_id),
                         (book.event.home_participant_id, book.event.away_participant_id))
        other = odds_payload()
        fixture_of(other)["participant1Id"] = 36                                   # same name, new id
        different = one_book(parse(other))
        self.assertNotEqual(different.event.home_participant_id, book.event.home_participant_id)
        self.assertEqual(book.event.home_participant_id,
                         ids.gid("part", provider="oddspapi", ns="v4.participant", native_type="int", native="35"))

    def test_id03_a_new_name_for_a_known_participant_appends_one_name_drift_row(self):
        with scratch_root() as root:
            registry = reg.IdentityRegistry(root / "identity.jsonl")
            first = parse(odds_payload())
            self.assertEqual([row["record_type"] for row in first.identity_rows],
                             ["fixture_bound", "participant_seen", "participant_seen"] * 2)
            prefix = registry_rows(first, registry)
            self.assertEqual({row["note"] for row in prefix if row["record_type"] == "participant_seen"},
                             {reg.NOTE_FIRST_SEEN})
            again = parse(odds_payload(), identity_prefix=prefix)
            self.assertEqual(again.identity_rows, ())                              # nothing new to record
            renamed = odds_payload()
            fixture_of(renamed)["participant1Name"] = "Team Alpha FC"
            drift = parse(renamed, identity_prefix=prefix)
            self.assertEqual(len(drift.identity_rows), 1)
            row = drift.identity_rows[0]
            self.assertEqual((row["record_type"], row["note"], row["display_name"]),
                             ("participant_seen", reg.NOTE_NAME_DRIFT, "Team Alpha FC"))
            self.assertEqual(row["participant_id"], one_book(drift).event.home_participant_id)
            self.assertEqual(reg.replay(registry_rows(drift, registry)).participants[row["participant_id"]],
                             "Team Alpha FC")

    def test_id08_changing_every_display_name_changes_no_id_and_no_artifact(self):
        payload = odds_payload()
        base = parse(payload)
        renamed = copy.deepcopy(payload)
        for item in renamed:
            for key in ("participant1Name", "participant2Name", "tournamentName", "sportName", "statusName"):
                item[key] = item[key] + " (renamed)"
        after = parse(renamed)
        self.assertEqual([book.entity_id for book in base.books], [book.entity_id for book in after.books])
        self.assertEqual(ps.documents(base), ps.documents(after))                  # byte-identical artifacts
        with scratch_root() as root:
            registry = reg.IdentityRegistry(root / "identity.jsonl")
            prefix = registry_rows(base, registry)
            drift = parse(renamed, identity_prefix=prefix)
            self.assertEqual({row["note"] for row in drift.identity_rows}, {reg.NOTE_NAME_DRIFT})
            self.assertEqual({row["record_type"] for row in drift.identity_rows}, {"participant_seen"})
            self.assertEqual(len(drift.identity_rows), 4)
            self.assertEqual(ps.documents(drift, identity_prefix=prefix), ps.documents(base, identity_prefix=prefix))


class ConflictTests(unittest.TestCase):
    def bound(self, root):
        registry = reg.IdentityRegistry(root / "identity.jsonl")
        base = parse(odds_payload())
        return registry, registry_rows(base, registry), base

    def test_id04_and_f21_rebinding_a_fixture_blocks_its_known_books_and_writes_no_row(self):
        variants = {
            "other home participant": lambda item: item.__setitem__("participant1Id", 99),
            "other away participant": lambda item: item.__setitem__("participant2Id", 99),
            "swapped home and away": lambda item: item.update(participant1Id=42, participant2Id=35),
            "other competition": lambda item: item.__setitem__("tournamentId", 8),
        }
        for label, edit in variants.items():
            with self.subTest(label), scratch_root() as root:
                registry, prefix, base = self.bound(root)
                event_a = books_by(base)[0].event.event_id
                payload = odds_payload()
                edit(fixture_of(payload))
                parsed = parse(payload, identity_prefix=prefix, expected_scope=ps.scope_of(base))
                self.assertEqual(reasons_of(parsed), {("BLOCKED", ("IDENTITY_CONFLICT",))}, label)
                self.assertEqual(len(books_by(parsed)), 6)
                self.assertEqual(parsed.quarantined_events, (event_a,))
                self.assertEqual(reasons_of(parsed, fixture=FIXTURE_B), {("OPEN", ())})
                self.assertEqual([row for row in parsed.identity_rows if row.get("event_id") == event_a], [])
                self.assertTrue(all(b.selections is None for b in books_by(parsed)))
                self.assertEqual(err.reason_code(err.AdapterFailure.IDENTITY_CONFLICT).value, "ambiguous_identity")

    def test_the_registry_refuses_a_conflicting_binding_and_accepts_an_identical_one(self):
        with scratch_root() as root:
            registry, prefix, base = self.bound(root)
            bound = next(row for row in prefix if row["record_type"] == "fixture_bound")
            identical = {k: v for k, v in bound.items() if k not in ("previous_hash", "sequence", "record_hash")}
            self.assertEqual(registry.apply([identical]), ())                      # crash resume: already there
            conflicting = {**identical, "home_participant_id": "part:" + "1" * 64}
            with self.assertRaises(reg.IdentityConflict):
                registry.apply([conflicting])
            self.assertEqual(len(registry.rows()), len(prefix))

    def test_a_conflicted_event_stays_blocked_on_every_later_response(self):
        with scratch_root() as root:
            registry, prefix, base = self.bound(root)
            payload = odds_payload()
            fixture_of(payload)["participant1Id"] = 99
            for _ in range(2):
                parsed = parse(payload, identity_prefix=prefix, expected_scope=ps.scope_of(base))
                self.assertEqual(reasons_of(parsed), {("BLOCKED", ("IDENTITY_CONFLICT",))})


class AmbiguityTests(unittest.TestCase):
    def test_id05_and_f22_home_equal_to_away_is_ambiguous_and_binds_nothing(self):
        payload = odds_payload()
        fixture_of(payload)["participant2Id"] = fixture_of(payload)["participant1Id"]
        parsed = parse(payload)
        self.assertEqual(reasons_of(parsed), {("BLOCKED", ("PARTICIPANT_AMBIGUOUS",))})
        self.assertEqual([row for row in parsed.identity_rows if row["record_type"] == "fixture_bound"
                          and row["provider_fixture_id"]["value"] == FIXTURE_A], [])
        self.assertEqual(err.reason_code(err.AdapterFailure.PARTICIPANT_AMBIGUOUS).value, "ambiguous_identity")

    def test_id05_and_f22_a_missing_or_wrongly_typed_participant_id_is_ambiguous(self):
        cases = (("missing home", lambda item: item.pop("participant1Id")),
                 ("missing away", lambda item: item.pop("participant2Id")),
                 ("string id", lambda item: item.__setitem__("participant1Id", "35")),
                 ("null id", lambda item: item.__setitem__("participant2Id", None)),
                 ("negative id", lambda item: item.__setitem__("participant1Id", -1)),
                 ("boolean id", lambda item: item.__setitem__("participant1Id", True)))
        for label, edit in cases:
            with self.subTest(label):
                payload = odds_payload()
                edit(fixture_of(payload))
                parsed = parse(payload)
                self.assertEqual(reasons_of(parsed), {("BLOCKED", ("PARTICIPANT_AMBIGUOUS",))}, label)
                self.assertEqual(reasons_of(parsed, fixture=FIXTURE_B), {("OPEN", ())})
                self.assertFalse([r for r in parsed.identity_rows if r["record_type"] == "fixture_bound"
                                  and r["provider_fixture_id"]["value"] == FIXTURE_A])

    def test_id07_the_declared_bookmaker_order_is_irrelevant(self):
        def reordered(identity):
            identity["bookmakers"] = list(reversed(identity["bookmakers"]))
            return identity

        base = parse(odds_payload())
        again = parse(odds_payload(), maps=ps.maps_with(identity=reordered))
        self.assertEqual([b.entity_id for b in base.books], [b.entity_id for b in again.books])
        self.assertEqual(ps.documents(base), ps.documents(again))

    def test_id07_an_undeclared_bookmaker_is_excluded_and_a_declared_one_is_kept(self):
        def declare_c(identity):
            for entry in identity["bookmakers"]:
                if entry["provider_bookmaker_key"] == "fixture-book-c":
                    entry["declared"] = True
            return identity

        maps = ps.maps_with(identity=declare_c, declared_max=4)
        parsed = parse(odds_payload(), maps=maps)
        self.assertEqual({b.provider_bookmaker_key for b in parsed.books},
                         {"pinnacle", "fixture-book-a", "fixture-book-b", "fixture-book-c"})
        self.assertEqual(exclusion_counts(parsed)["OUT_OF_SCOPE_BOOKMAKER"], 2)     # only the exchanges remain


class RegistryTests(unittest.TestCase):
    def test_the_empty_registry_has_the_zero_head_and_rows_extend_it(self):
        with scratch_root() as root:
            registry = reg.IdentityRegistry(root / "identity.jsonl")
            self.assertEqual(registry.head(), {"sequence": 0, "record_hash": "0" * 64})
            registry.apply(parse(odds_payload()).identity_rows)
            head = registry.head()
            self.assertEqual(head["sequence"], len(registry.rows()))
            self.assertEqual(reg.head_of(registry.prefix(head["sequence"])), head)
            self.assertEqual(reg.head_of(registry.prefix(2))["sequence"], 2)
            with self.assertRaises(reg.IdentityRegistryInvalid):
                registry.prefix(head["sequence"] + 1)

    def test_documents_pin_the_head_of_the_prefix_they_used(self):
        with scratch_root() as root:
            registry = reg.IdentityRegistry(root / "identity.jsonl")
            first = parse(odds_payload())
            self.assertEqual(ps.document_of(first, one_book(first).entity_id)["identity_registry_head"],
                             {"sequence": 0, "record_hash": "0" * 64})
            prefix = registry_rows(first, registry)
            second = parse(odds_payload(), identity_prefix=prefix)
            self.assertEqual(ps.document_of(second, one_book(second).entity_id,
                                            identity_prefix=prefix)["identity_registry_head"], registry.head())

    def test_replay_rejects_malformed_or_inconsistent_histories(self):
        good_fixture = reg.fixture_binding_row(
            event_id="evt:" + "1" * 64, provider_fixture_id={"native_type": "str", "value": "f1"},
            competition_id="soccer.eng.premier-league", home_participant_id="part:" + "2" * 64,
            away_participant_id="part:" + "3" * 64, first_seen_at="2026-10-01T12:00:00.000000Z",
            raw_observation_id="a" * 64)
        seen = reg.participant_seen_row(
            participant_id="part:" + "2" * 64, provider_participant_id={"native_type": "int", "value": "35"},
            display_name="A", first_seen_at="2026-10-01T12:00:00.000000Z", raw_observation_id="a" * 64,
            drift=False)
        reg.replay([good_fixture, seen])
        bad = {
            "unknown key": [{**good_fixture, "surprise": 1}],
            "unknown type": [{**good_fixture, "record_type": "other"}],
            "home equals away": [{**good_fixture, "away_participant_id": good_fixture["home_participant_id"]}],
            "bound twice": [good_fixture, good_fixture],
            "time regresses": [good_fixture, {**seen, "first_seen_at": "2026-10-01T11:59:59.000000Z"}],
            "non canonical time": [{**good_fixture, "first_seen_at": "2026-10-01T12:00:00Z"}],
            "drift without earlier name": [{**seen, "note": reg.NOTE_NAME_DRIFT}],
            "first seen twice": [seen, {**seen, "display_name": "B"}],
            "drift with the same name": [seen, {**seen, "note": reg.NOTE_NAME_DRIFT}],
        }
        for label, rows in bad.items():
            with self.subTest(label), self.assertRaises(reg.IdentityRegistryInvalid):
                reg.replay(rows)

    def test_the_registry_is_append_only_and_tampering_is_detected(self):
        with scratch_root() as root:
            registry = reg.IdentityRegistry(root / "identity.jsonl")
            registry.apply(parse(odds_payload()).identity_rows)
            raw = (root / "identity.jsonl").read_bytes()
            (root / "identity.jsonl").write_bytes(raw.replace(b"Team Alpha", b"Team Omega"))
            with self.assertRaises(RegistryConflict):
                registry.rows()

    def test_apply_is_idempotent_so_a_crash_between_rows_resumes_without_duplicates(self):
        with scratch_root() as root:
            registry = reg.IdentityRegistry(root / "identity.jsonl")
            rows = parse(odds_payload()).identity_rows
            registry.apply(rows[:2])                                              # "crash" after two rows
            appended = registry.apply(rows)
            self.assertEqual(len(appended), len(rows) - 2)
            self.assertEqual(registry.apply(rows), ())
            self.assertEqual(len(registry.rows()), len(rows))


if __name__ == "__main__":
    unittest.main()
