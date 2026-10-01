"""EV-04 (publish level), TS-07, PIT-08, A-3 (crash at every emission checkpoint), F-30, F-32, F-33."""

from __future__ import annotations

import dataclasses
import json
import unittest

from genesis.coverage import CoverageEntry, CoverageStatus
from genesis.pit import BitemporalRecord
from genesis.provenance import AvailabilityClass
from genesis.reasons import ReasonCode

from genesis_adapters import errors as err
from genesis_adapters import ids
from genesis_adapters.oddspapi import emit, parser
from genesis_adapters.oddspapi import identity_registry as reg

from . import emit_support as es
from . import parser_support as ps
from .emit_support import (
    CAPTURE_1, build_stores, capture, coverage_rows, doc_json, head_book, iso, pit_rows, small_payload,
)
from .parser_support import fixture_of, market_of, odds_payload, price_of
from .support import Crash, SequenceClock, scratch_root


def three_state_payload():
    """OPEN 1X2 (pinnacle), SUSPENDED O/U (pinnacle) and a BLOCKED 1X2 (book-a) in one small response."""

    payload = small_payload(bookmakers=("pinnacle", "fixture-book-a"))
    price_of(payload, "pinnacle", "1010", "2002")["active"] = False
    del market_of(payload, "fixture-book-a", "101")["outcomes"]["102"]
    return payload


class ContractTests(unittest.TestCase):
    def test_ev04_normalized_observations_match_the_contract(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, ctx, result = capture(stores, odds_payload())
            self.assertEqual(len(result.observation_ids), 12)
            contract = stores.contracts.get(stores.contract_id)
            self.assertEqual((contract.provider, contract.source_type, contract.parser_version,
                              contract.availability_class),
                             ("oddspapi", "oddspapi_v4_market_book", ps.DERIVATION, AvailabilityClass.DERIVED))
            self.assertEqual(contract.uri_pattern,
                             f"genesis-derived:oddspapi-v4-market-book:{ps.DERIVATION}:*")
            self.assertEqual(stores.contract_id, f"oddspapi-v4-market-book-{ps.DERIVATION}")
            self.assertEqual(stores.source_id, f"oddspapi.v4.soccer.market_book.{ps.DERIVATION}")
            for observation_id in result.observation_ids:
                observation = stores.evidence.get_observation(observation_id)
                document = doc_json(stores, observation.artifact_hash)
                self.assertEqual((observation.contract_id, observation.provider, observation.source_type,
                                  observation.parser_version, observation.availability_class,
                                  observation.content_type, observation.upstream_version,
                                  observation.licensing_note),
                                 (stores.contract_id, "oddspapi", "oddspapi_v4_market_book", ps.DERIVATION,
                                  AvailabilityClass.DERIVED, "application/json", "v4", es.NOTE))
                self.assertEqual(observation.source_uri,
                                 f"genesis-derived:oddspapi-v4-market-book:{ps.DERIVATION}:"
                                 f"{document['entity_id']}:{ctx.raw_observation_id}")
                self.assertEqual((observation.retrieved_at, observation.first_seen_at, observation.valid_from),
                                 (ps.T1, ps.T1, ps.T1))
                self.assertEqual(observation.parse_ready_at, result.t2)
                self.assertEqual(observation.valid_to, document["valid_to"])
                self.assertEqual((document["raw_artifact_hash"], document["raw_observation_id"]),
                                 (ctx.raw_artifact_hash, ctx.raw_observation_id))
            self.assertEqual(stores.evidence.verify_manifest(), 12)

    def test_the_contract_is_registered_idempotently_and_never_changes(self):
        with scratch_root() as root:
            stores = build_stores(root)
            again = emit.register_normalized_contract(stores.contracts, derivation_version=ps.DERIVATION,
                                                      licensing_note=es.NOTE)
            self.assertTrue(again)
            with self.assertRaises(Exception):
                emit.register_normalized_contract(stores.contracts, derivation_version=ps.DERIVATION,
                                                  licensing_note="something else")

    def test_ts07_pit_fields_equal_design_11_4_exactly_for_open_and_each_non_open_state(self):
        with scratch_root() as root:
            stores = build_stores(root)
            base = capture(stores, small_payload(bookmakers=("pinnacle", "fixture-book-a")))[0]
            scope = ps.scope_of(base)
            gone = ps.one_book(base, bookmaker="fixture-book-a", family="SOCCER_1X2_FT")
            payload = three_state_payload()
            del fixture_of(payload)["bookmakerOdds"]["pinnacle"]["markets"]["101"]
            parsed, ctx, result = capture(stores, payload, t1=es.CAPTURE_2, expected_scope=scope)
            states = {b.entity_id: b.state for b in parsed.books} | {t.entity_id: "ABSENT" for t in parsed.tombstones}
            self.assertEqual(set(states.values()), {"OPEN", "SUSPENDED", "BLOCKED", "ABSENT"})
            rows = {row["entity_id"]: row for row in pit_rows(stores) if row["available_at"] == es.CAPTURE_2}
            self.assertEqual(set(rows), set(states))
            for entity, row in rows.items():
                document = doc_json(stores, row["payload_hash"])
                expected_id = "pit:" + ids_sha({"domain": "genesis.adapters.pit-record.v1",
                                                 "source_id": stores.source_id, "artifact_hash": row["payload_hash"]})
                self.assertEqual(row["record_id"], expected_id)
                self.assertEqual((row["source_id"], row["available_at"], row["retrieved_at"], row["valid_from"],
                                  row["ready_at"], row["superseded_by"], row["superseded_at"]),
                                 (stores.source_id, es.CAPTURE_2, es.CAPTURE_2, es.CAPTURE_2, result.t3, None, None))
                self.assertEqual(row["valid_to"], document["valid_to"])
                if states[entity] == "OPEN":
                    self.assertIsNotNone(row["valid_to"])
                else:
                    self.assertIsNone(row["valid_to"])                  # a non-OPEN head never expires
                observation = stores.evidence.get_observations(row["payload_hash"])[0]
                self.assertEqual(row["published_at"], observation.publisher_timestamp)
            open_row = next(row for entity, row in rows.items() if states[entity] == "OPEN")
            self.assertEqual(open_row["published_at"], "2026-10-01T11:58:30.000000Z")

    def test_pit08_record_ids_are_keyed_on_the_artifact_and_no_record_is_ever_superseded(self):
        with scratch_root() as root:
            stores = build_stores(root)
            capture(stores, odds_payload())
            capture(stores, odds_payload(), t1=es.CAPTURE_2)
            rows = pit_rows(stores)
            self.assertEqual(len(rows), 24)
            self.assertEqual(len({row["record_id"] for row in rows}), 24)
            for row in rows:
                self.assertEqual(row["record_id"], emit.pit_record_id(stores.source_id, row["payload_hash"]))
                self.assertEqual((row["superseded_by"], row["superseded_at"]), (None, None))
            self.assertNotEqual(emit.pit_record_id("a", "0" * 64), emit.pit_record_id("b", "0" * 64))
            self.assertNotEqual(emit.pit_record_id("a", "0" * 64), emit.pit_record_id("a", "1" * 64))

    def test_structured_evidence_exists_for_open_books_only_and_matches_its_observation(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, ctx, result = capture(stores, three_state_payload())
            self.assertEqual(sum(1 for b in parsed.books if b.state == "OPEN"), 2)
            self.assertEqual(len(result.structured_hashes), 2)
            bodies = [stores.structured.verify(digest) for digest in result.structured_hashes]
            claims = {json.loads(body["normalized_claim"])["bookmaker_id"] + ":" +
                      str(json.loads(body["normalized_claim"])["line"]): body for body in bodies}
            self.assertEqual(set(claims), {"bk.pinnacle:None", "bk.fixture-book-a:2.5"})
            body = claims["bk.pinnacle:None"]
            observation = stores.evidence.get_observation(body["source_ref"]["observation_id"])
            self.assertEqual(body["evidence_id"], ids.gid("rev", observation_id=observation.observation_id))
            self.assertEqual((body["category"], body["status"], body["extractor_version"]),
                             ("market_price.bookmaker_back", "confirmed", ps.DERIVATION))
            self.assertEqual((body["retrieved_at"], body["ready_at"], body["freshness_expires_at"]),
                             (ps.T1, observation.parse_ready_at, observation.valid_to))
            self.assertEqual(body["source_timestamp"], observation.publisher_timestamp)
            self.assertEqual(json.loads(body["normalized_claim"])["odds"],
                             {"HOME": "2.1", "DRAW": "3.4", "AWAY": "3.6"})
            for digest in result.structured_hashes:                 # every one names a real, matching observation
                source = stores.structured.verify(digest)["source_ref"]
                self.assertEqual(source["contract_id"], stores.contract_id)
                self.assertEqual(source["availability_class"], "derived")


def ids_sha(value) -> str:
    from genesis.repro import canonical_json, sha256_bytes
    return sha256_bytes(canonical_json(value))


class ClockTests(unittest.TestCase):
    def test_emission_reads_the_clock_exactly_three_times_and_orders_t1_t2_t3(self):
        with scratch_root() as root:
            stores = build_stores(root)
            clock = SequenceClock([iso(CAPTURE_1, seconds=1), iso(CAPTURE_1, seconds=2), iso(CAPTURE_1, seconds=3)])
            parsed, ctx, result = capture(stores, small_payload(), clock=clock)
            self.assertEqual(clock.calls, 3)
            self.assertLess(ps.T1, result.t2)
            self.assertLess(result.t2, result.t3)
            row = next(r for r in stores.acquisition.rows() if r["record_type"] == "acq_normalized")
            self.assertEqual((row["T2"], row["T3"]), (result.t2, result.t3))
            self.assertLessEqual(row["T3"], row["recorded_at"])

    def test_a_t3_before_t2_or_before_any_published_observation_is_a_fault_and_writes_no_pit_record(self):
        from genesis_adapters.clock import ClockFault
        with scratch_root() as root:
            stores = build_stores(root)
            with self.assertRaises(ClockFault):
                capture(stores, small_payload(), t2=iso(CAPTURE_1, seconds=2), t3=iso(CAPTURE_1, seconds=1))
            self.assertEqual(pit_rows(stores), [])
        with scratch_root() as root:                                   # resume: an earlier run's T2 is a floor too
            stores = build_stores(root)
            raw = ps.dump(small_payload())
            ctx = es.make_capture_ctx(stores, raw, t1=CAPTURE_1)
            parsed = parser.parse_odds_response(raw, ctx)
            es.seed_acquisition(stores, ctx)

            def crash(name):
                if name == "after_observation:1":
                    raise Crash()

            with self.assertRaises(Crash):
                emit.emit_response(parsed, ctx, stores=stores, clock=SequenceClock([iso(CAPTURE_1, seconds=5)]),
                                   checkpoint=crash)
            with self.assertRaises(ClockFault):                        # T3 below the stored T2 of 5 s
                emit.emit_response(parsed, ctx, stores=es.reopen(stores), clock=SequenceClock(
                    [iso(CAPTURE_1, seconds=2), iso(CAPTURE_1, seconds=3)]))
            self.assertEqual(pit_rows(stores), [])

    def test_a_clock_behind_t1_is_a_fault_and_nothing_is_published(self):
        from genesis_adapters.clock import ClockFault
        with scratch_root() as root:
            stores = build_stores(root)
            with self.assertRaises(ClockFault):
                capture(stores, small_payload(), t2=iso(CAPTURE_1, micros=-1))
            self.assertEqual(pit_rows(stores), [])
            self.assertEqual(stores.evidence.verify_manifest(), 0)


class ConflictTests(unittest.TestCase):
    def test_f32_an_observation_that_contradicts_the_derivation_halts_and_publishes_nothing_more(self):
        with scratch_root() as root:
            stores = build_stores(root)
            payload = small_payload()
            parsed, ctx, result = capture(stores, payload)
            first = stores.evidence.get_observation(result.observation_ids[0])
            data = stores.evidence.get_bytes(first.artifact_hash)
            other = build_stores(root / "other")             # a second world holding a contradicting observation
            other.evidence.publish(
                data, contract_id=other.contract_id,
                source_uri=f"genesis-derived:oddspapi-v4-market-book:{ps.DERIVATION}:x:y", provider="oddspapi",
                source_type="oddspapi_v4_market_book", retrieved_at=ps.T1, parse_ready_at=ps.T1,
                first_seen_at=ps.T1, parser_version=ps.DERIVATION, content_type="application/json",
                licensing_note=es.NOTE, availability_class=AvailabilityClass.DERIVED, upstream_version="v4",
                valid_from=ps.T1, valid_to=first.valid_to)
            with self.assertRaises(emit.EmitConflict) as caught:
                capture(other, payload, ctx=ctx)             # the very same derivation, so the same artifact
            self.assertEqual(caught.exception.failure, err.AdapterFailure.EVIDENCE_CONFLICT)
            self.assertEqual(pit_rows(other), [])

    def test_f33_a_pit_record_that_differs_from_the_intended_one_halts_and_is_never_replaced(self):
        with scratch_root() as root:
            stores = build_stores(root)
            payload = small_payload()
            parsed, ctx, result = capture(stores, payload)
            row = pit_rows(stores)[0]
            record = BitemporalRecord(**{k: row[k] for k in BitemporalRecord.__dataclass_fields__})
            forged = dataclasses.replace(record, valid_to=iso(ps.T1, seconds=1234))
            with self.assertRaises(emit.EmitConflict) as caught:
                emit.append_pit_once(stores, forged)
            self.assertEqual(caught.exception.failure, err.AdapterFailure.PIT_APPEND_CONFLICT)
            # one T3 per response, reused exactly by a resumed emission (design 6.2, hostile audit HA-06): a record
            # that differs only in its ready_at is a conflict too, never a silent reuse
            later_ready = dataclasses.replace(record, ready_at=iso(record.ready_at, seconds=9))
            with self.assertRaises(emit.EmitConflict) as caught:
                emit.append_pit_once(stores, later_ready)
            self.assertEqual(caught.exception.failure, err.AdapterFailure.PIT_APPEND_CONFLICT)
            self.assertEqual(emit.append_pit_once(stores, record), record.record_id)          # the identical one
            self.assertEqual(len(pit_rows(stores)), len(result.pit_record_ids))

    def test_emission_requires_its_completed_acquisition(self):
        with scratch_root() as root:
            stores = build_stores(root)
            with self.assertRaises(emit.EmitConflict):
                capture(stores, small_payload(), seed=False)
            self.assertEqual(pit_rows(stores), [])

    def test_a_response_that_failed_as_a_whole_cannot_be_emitted(self):
        with scratch_root() as root:
            stores = build_stores(root)
            with self.assertRaises(emit.EmitConflict) as caught:
                capture(stores, b'{"not": "a list"}')
            self.assertEqual(caught.exception.failure, err.AdapterFailure.ENVELOPE_SCHEMA_MISMATCH)

    def test_coverage_is_appended_exactly_once_and_a_contradicting_entry_halts(self):
        with scratch_root() as root:
            stores = build_stores(root)
            capture(stores, three_state_payload())
            rows = coverage_rows(stores)
            self.assertEqual(len(rows), len({r["entry_id"] for r in rows}))
            first = rows[0]
            entry = CoverageEntry(
                entry_id=first["entry_id"], entity_id=first["entity_id"], source_contract_id=first["source_contract_id"],
                status=CoverageStatus(first["status"]), recorded_at=iso(ps.T1, seconds=99),
                reason_codes=tuple(ReasonCode(c) for c in first["reason_codes"]),
                artifact_hash=first["artifact_hash"], note=first["note"])
            self.assertEqual(emit.append_coverage_once(stores, entry), entry.entry_id)     # identical: no new row
            self.assertEqual(len(coverage_rows(stores)), len(rows))
            changed = dataclasses.replace(entry, note="another note")
            with self.assertRaises(emit.EmitConflict):
                emit.append_coverage_once(stores, changed)


class CoverageMappingTests(unittest.TestCase):
    def rows_by_note(self, stores):
        return {(row["entity_id"], row["note"]): row for row in coverage_rows(stores)}

    def test_open_and_suspended_and_absent_are_available_with_the_artifact_hash(self):
        with scratch_root() as root:
            stores = build_stores(root)
            base = capture(stores, small_payload(bookmakers=("pinnacle", "fixture-book-a")))[0]
            scope = ps.scope_of(base)
            payload = three_state_payload()
            del fixture_of(payload)["bookmakerOdds"]["pinnacle"]["markets"]["101"]
            parsed, ctx, result = capture(stores, payload, t1=es.CAPTURE_2, expected_scope=scope)
            rows = [r for r in coverage_rows(stores) if r["recorded_at"] >= es.CAPTURE_2]
            by_note = {}
            for row in rows:
                by_note.setdefault(row["note"].split(":")[0], []).append(row)
            for note in ("SUSPENDED", "BOOK_ABSENT"):
                self.assertTrue(by_note[note])
                for row in by_note[note]:
                    self.assertEqual((row["status"], row["reason_codes"]), ("available", []))
                    self.assertEqual(len(row["artifact_hash"]), 64)
            blocked = by_note["INCOMPLETE_SELECTIONS"][0]
            self.assertEqual((blocked["status"], blocked["reason_codes"]), ("rejected", ["schema_rejected"]))

    def test_blocked_reasons_map_to_the_failure_matrix_statuses_and_reason_codes(self):
        expected = {
            "UNKNOWN_EVENT_STATUS": ("rejected", "critical_uncertainty"),
            "SCHEMA_DRIFT": ("rejected", "schema_rejected"),
            "PARTICIPANT_AMBIGUOUS": ("ambiguous", "ambiguous_identity"),
            "EVENT_METADATA_STALE": ("missing", "stale_evidence"),
            "EVENT_START_INVALID": ("rejected", "not_available_at_decision"),
        }
        edits = {
            "UNKNOWN_EVENT_STATUS": lambda p: fixture_of(p).__setitem__("statusId", 9),
            "SCHEMA_DRIFT": lambda p: fixture_of(p).__setitem__("surprise", 1),
            "PARTICIPANT_AMBIGUOUS": lambda p: fixture_of(p).__setitem__("participant2Id", fixture_of(p)["participant1Id"]),
            "EVENT_METADATA_STALE": lambda p: fixture_of(p).pop("startTime"),
            "EVENT_START_INVALID": lambda p: fixture_of(p).__setitem__("startTime", "soon"),
        }
        for code, (status, reason) in expected.items():
            with self.subTest(code), scratch_root() as root:
                stores = build_stores(root)
                payload = small_payload()
                edits[code](payload)
                capture(stores, payload)
                rows = [r for r in coverage_rows(stores) if r["note"] == code]
                self.assertTrue(rows, code)
                self.assertEqual({(r["status"], tuple(r["reason_codes"])) for r in rows}, {(status, (reason,))})

    def test_excluded_scope_is_recorded_once_per_code_with_its_count(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, ctx, result = capture(stores, odds_payload())
            rows = [r for r in coverage_rows(stores) if r["entity_id"].startswith("oddspapi-request:")]
            by_note = {r["note"]: r for r in rows}
            self.assertEqual(by_note["OUT_OF_SCOPE_LINE:24"]["reason_codes"], ["unsupported_market"])
            self.assertEqual(by_note["OUT_OF_SCOPE_BOOKMAKER:4"]["status"], "rejected")
            self.assertEqual(len(rows), 2)

    def test_an_identity_conflict_quarantines_the_event(self):
        with scratch_root() as root:
            stores = build_stores(root)
            first = capture(stores, small_payload())[0]
            payload = small_payload()
            fixture_of(payload)["participant1Id"] = 99
            capture(stores, payload, t1=es.CAPTURE_2, expected_scope=ps.scope_of(first))
            notes = {(r["status"], tuple(r["reason_codes"]), r["note"]) for r in coverage_rows(stores)
                     if r["recorded_at"] >= es.CAPTURE_2}
            self.assertIn(("quarantined", ("ambiguous_identity",), "EVENT_QUARANTINED"), notes)
            self.assertIn(("ambiguous", ("ambiguous_identity",), "IDENTITY_CONFLICT"), notes)


class IdentityOrderTests(unittest.TestCase):
    def test_identity_rows_are_applied_last_and_only_once(self):
        with scratch_root() as root:
            stores = build_stores(root)
            seen = []

            def checkpoint(name):
                seen.append((name, len(stores.identity.rows())))

            parsed, ctx, result = capture(stores, small_payload(), checkpoint=checkpoint)
            self.assertEqual({count for name, count in seen if name != "after_identity"}, {0})
            self.assertEqual(seen[-1], ("after_identity", 3))
            self.assertEqual(result.identity_rows_applied, 3)
            capture(stores, small_payload(), t1=es.CAPTURE_2)
            self.assertEqual(len(stores.identity.rows()), 3)                  # nothing new on the second sight

    def test_documents_pin_the_input_prefix_not_the_rows_the_response_itself_added(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, ctx, result = capture(stores, small_payload())
            document = doc_json(stores, stores.evidence.get_observation(result.observation_ids[0]).artifact_hash)
            self.assertEqual(document["identity_registry_head"], reg.EMPTY_HEAD)
            self.assertEqual(stores.identity.head()["sequence"], 3)


if __name__ == "__main__":
    unittest.main()
