"""PIT-01 .. PIT-05, PIT-08, PIT-09 (re-derivation), FR-01 .. FR-04, ST-05, F-25, F-30: point-in-time behaviour."""

from __future__ import annotations

import unittest

from genesis.pit import BitemporalRecord

from genesis_adapters import errors as err
from genesis_adapters.oddspapi import emit, parser, scope
from genesis_adapters.oddspapi.reader import UsableBook, Unusable, admissible_head

from . import emit_support as es
from . import parser_support as ps
from .emit_support import (
    CAPTURE_1, CAPTURE_2, build_stores, capture, doc_json, head_book, iso, pit_rows, small_payload,
)
from .parser_support import fixture_of, market_of, price_of
from .support import Crash, SequenceClock, scratch_root

OU = "SOCCER_TOTAL_GOALS_OU_FT"


def record_of(stores, entity_id: str, t1: str) -> BitemporalRecord:
    rows = [row for row in pit_rows(stores) if row["entity_id"] == entity_id and row["available_at"] == t1]
    assert len(rows) == 1, f"{len(rows)} records for the entity at {t1}"
    return BitemporalRecord(**{key: rows[0][key] for key in BitemporalRecord.__dataclass_fields__})


def repriced(over=1.9, under=1.96):
    payload = small_payload()
    price_of(payload, "pinnacle", "1010", "2001")["price"] = over
    price_of(payload, "pinnacle", "1010", "2002")["price"] = under
    return payload


def head(stores, entity_id, decision_at):
    return admissible_head(entity_id, decision_at, stores=stores)


class AsOfTests(unittest.TestCase):
    def test_pit01_each_cutoff_sees_the_capture_that_was_ready_then(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, first = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            capture(stores, repriced(), t1=CAPTURE_2)
            one, two = record_of(stores, entity, CAPTURE_1), record_of(stores, entity, CAPTURE_2)
            self.assertNotEqual(one.payload_hash, two.payload_hash)
            for decision_at, expected in ((first.t3, one), (iso(CAPTURE_2, seconds=-1), one),
                                          (CAPTURE_2, one), (iso(CAPTURE_2, seconds=0.9), one),     # T1_2 <= D < T3_2
                                          (iso(CAPTURE_2, seconds=1), two), (iso(CAPTURE_2, seconds=600), two)):
                with self.subTest(decision_at):
                    result = head(stores, entity, decision_at)
                    self.assertIsInstance(result, UsableBook, decision_at)
                    self.assertEqual(result.record, expected, decision_at)
                    self.assertEqual(result.document["selections"]["OVER"]["odds_decimal"],
                                     "1.91" if expected is one else "1.9")

    def test_pit02_one_microsecond_before_t3_the_capture_is_not_visible(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, result = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            before = head(stores, entity, iso(result.t3, micros=-1))
            self.assertIsInstance(before, Unusable)
            self.assertEqual(before.code, err.AdapterFailure.MISSING_OR_STALE)
            self.assertEqual(before.pass_reason.value, "PASS_STALE_EVIDENCE")
            self.assertIsInstance(head(stores, entity, result.t3), UsableBook)

    def test_pit03_two_records_with_the_same_valid_from_are_ambiguous(self):
        with scratch_root() as root:
            stores = build_stores(root)
            raw_a, raw_b = ps.dump(small_payload()), ps.dump(repriced())
            ctx_a = es.make_capture_ctx(stores, raw_a, t1=CAPTURE_1, tag="a")
            ctx_b = es.make_capture_ctx(stores, raw_b, t1=CAPTURE_1, tag="b")
            seed_pair(stores, ctx_a, ctx_b)
            for raw, ctx, offset in ((raw_a, ctx_a, 1), (raw_b, ctx_b, 3)):
                emit.emit_response(parser.parse_odds_response(raw, ctx), ctx, stores=stores, clock=SequenceClock(
                    [iso(CAPTURE_1, seconds=offset), iso(CAPTURE_1, seconds=offset + 0.5),
                     iso(CAPTURE_1, seconds=offset + 0.6)]))
            entity = head_book(parser.parse_odds_response(raw_a, ctx_a)).entity_id
            result = head(stores, entity, iso(CAPTURE_1, seconds=10))
            self.assertIsInstance(result, Unusable)
            self.assertEqual(result.code, err.AdapterFailure.AMBIGUOUS)
            self.assertEqual(result.pass_reason.value, "PASS_UNKNOWN_STATE")
            from .parity_support import verifier_verdict
            for label, pinned in (("a", record_of_tag(stores, entity, 0)), ("b", record_of_tag(stores, entity, 1))):
                accepted, why = verifier_verdict(stores, [(pinned, "OVER")], decision_at=iso(CAPTURE_1, seconds=10),
                                                 scratch=root, label=label)
                self.assertFalse(accepted, why)
                self.assertIn("unique as-of head", why)

    def test_pit04_and_st05_a_suspension_blocks_an_older_open_price_for_good(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, first = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            suspended = small_payload()
            price_of(suspended, "pinnacle", "1010", "2002")["active"] = False
            capture(stores, suspended, t1=CAPTURE_2)
            old = record_of(stores, entity, CAPTURE_1)
            self.assertEqual(head(stores, entity, iso(CAPTURE_2, seconds=0.5)).record, old)   # before T3_2
            for decision_at in (iso(CAPTURE_2, seconds=1), iso(old.valid_to, micros=-1), old.valid_to,
                                iso(old.valid_to, seconds=86400)):
                with self.subTest(decision_at):
                    result = head(stores, entity, decision_at)
                    self.assertIsInstance(result, Unusable)
                    self.assertEqual((result.code, result.reasons), (err.AdapterFailure.SUSPENDED, ("OUTCOME_INACTIVE",)))
            # a later BLOCKED capture with a moved kickoff: the old OPEN price never comes back either
            moved = small_payload()
            fixture_of(moved)["startTime"] = "2026-10-05T14:00:00.000Z"
            price_of(moved, "pinnacle", "1010", "2002")["active"] = "unknown"
            later = iso(CAPTURE_2, seconds=1800)
            capture(stores, moved, t1=later)
            for decision_at in (iso(later, seconds=1), iso(later, seconds=7 * 86400)):
                result = head(stores, entity, decision_at)
                self.assertEqual((result.code, result.reasons),
                                 (err.AdapterFailure.BLOCKED, ("UNKNOWN_OUTCOME_STATUS",)))

    def test_pit04_the_older_open_record_is_rejected_by_the_frozen_verifier_too(self):
        from .parity_support import verifier_verdict
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, first = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            suspended = small_payload()
            price_of(suspended, "pinnacle", "1010", "2002")["active"] = False
            capture(stores, suspended, t1=CAPTURE_2)
            old = record_of(stores, entity, CAPTURE_1)
            accepted, _ = verifier_verdict(stores, [(old, "OVER")], decision_at=iso(CAPTURE_2, seconds=0.5),
                                           scratch=root, label="before")
            self.assertTrue(accepted)
            accepted, why = verifier_verdict(stores, [(old, "OVER")], decision_at=iso(CAPTURE_2, seconds=1),
                                             scratch=root, label="after")
            self.assertFalse(accepted)
            self.assertIn("unique as-of head", why)
            new = record_of(stores, entity, CAPTURE_2)
            accepted, why = verifier_verdict(stores, [(new, "OVER")], decision_at=iso(CAPTURE_2, seconds=1),
                                             scratch=root, label="suspended")
            self.assertFalse(accepted)
            self.assertIn("absent from exact bytes", why)                      # a suspended head has no price


def seed_pair(stores, ctx_a, ctx_b):
    """Two acquisitions that complete at the same instant (interleaved rows keep the ledger monotonic)."""

    ledger = stores.acquisition
    for ctx in (ctx_a, ctx_b):
        aid = ctx.acquisition_id
        ledger.append("acq_planned", recorded_at=iso(ctx.request_started_at, micros=-2000), acquisition_id=aid,
                      request_id="oddspapi-attempt:" + aid, window_id="w-" + aid[:8], purpose="SCHEDULED", attempt=1,
                      provider_request_hash=ctx.provider_request_hash, role="ODDS", provider_metering="PER_REQUEST",
                      provider_request_weight=1, provider_documented_billable=True, genesis_debit_units=1)
    for ctx in (ctx_a, ctx_b):
        ledger.append("acq_quota_decided", recorded_at=iso(ctx.request_started_at, micros=-500),
                      acquisition_id=ctx.acquisition_id, Tq=iso(ctx.request_started_at, micros=-1000),
                      frozen_ledger_reason="billable_call_reserved", allowed=True, genesis_units_debited=1,
                      cache_entry_id=None, cache_miss_reason=None)
    for ctx in (ctx_a, ctx_b):
        ledger.append("acq_sent", recorded_at=ctx.request_started_at, acquisition_id=ctx.acquisition_id,
                      T0=ctx.request_started_at)
    for ctx in (ctx_a, ctx_b):
        ledger.append("acq_completed", recorded_at=ctx.response_received_at, acquisition_id=ctx.acquisition_id,
                      T1=ctx.response_received_at, outcome="RESPONSE", http_status=200, headers=[],
                      content_encoding=None, byte_length=1, raw_observation_id=ctx.raw_observation_id,
                      sanitized_error=None, provider_reported_usage=None, failure=None)


def record_of_tag(stores, entity_id, index):
    rows = sorted((row for row in pit_rows(stores) if row["entity_id"] == entity_id), key=lambda row: row["ready_at"])
    return BitemporalRecord(**{key: rows[index][key] for key in BitemporalRecord.__dataclass_fields__})


class TombstoneTests(unittest.TestCase):
    def two_bookmakers(self):
        return small_payload(bookmakers=("pinnacle", "fixture-book-a"))

    def expected_at(self, stores, decision_at):
        return scope.build_expected_scope(pit=stores.pit, evidence=stores.evidence, source_id=stores.source_id,
                                          decision_at=decision_at, competition_ids=("soccer.eng.premier-league",
                                                                                    "soccer.esp.laliga"),
                                          bookmaker_ids=("bk.pinnacle", "bk.fixture-book-a", "bk.fixture-book-b"))

    def test_pit05_and_f30_a_complete_response_without_an_expected_book_leaves_an_absent_head(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, _ = capture(stores, self.two_bookmakers())
            gone = ps.one_book(parsed, bookmaker="fixture-book-a", family="SOCCER_1X2_FT")
            tq = iso(CAPTURE_2, seconds=-0.2)
            expected = self.expected_at(stores, tq)
            self.assertEqual(set(expected), {book.entity_id for book in parsed.books})
            digest = scope.publish_scope(root, expected.values(), as_of=tq)
            self.assertEqual(scope.load_scope(root, digest), expected)
            payload = self.two_bookmakers()
            del fixture_of(payload)["bookmakerOdds"]["fixture-book-a"]["markets"]["101"]
            second, _, result = capture(stores, payload, t1=CAPTURE_2, expected_scope=expected, expected_hash=digest)
            self.assertEqual([t.entity_id for t in second.tombstones], [gone.entity_id])
            absent = record_of(stores, gone.entity_id, CAPTURE_2)
            self.assertIsNone(absent.valid_to)
            self.assertEqual(doc_json(stores, absent.payload_hash)["expected_scope_hash"], digest)
            for decision_at in (result.t3, iso(CAPTURE_2, seconds=30 * 86400)):
                verdict = head(stores, gone.entity_id, decision_at)
                self.assertEqual(verdict.code, err.AdapterFailure.ABSENT)
                self.assertEqual(verdict.pass_reason.value, "PASS_MISSING_EVIDENCE")
            self.assertIsInstance(head(stores, gone.entity_id, iso(CAPTURE_2, seconds=0.5)), UsableBook)
            self.assertIsInstance(head(stores, ps.one_book(parsed).entity_id, result.t3), UsableBook)

    def test_pit05_a_partial_or_failed_response_leaves_no_tombstone(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, _ = capture(stores, self.two_bookmakers())
            gone = ps.one_book(parsed, bookmaker="fixture-book-a", family="SOCCER_1X2_FT")
            expected = self.expected_at(stores, iso(CAPTURE_2, seconds=-0.2))
            payload = self.two_bookmakers()
            del fixture_of(payload)["bookmakerOdds"]["fixture-book-a"]["markets"]["101"]
            partial, _, _ = capture(stores, payload, t1=CAPTURE_2, expected_scope=expected, complete_hint=False)
            self.assertEqual(partial.tombstones, ())
            self.assertEqual([r for r in pit_rows(stores) if r["entity_id"] == gone.entity_id
                              and r["available_at"] == CAPTURE_2], [])
            self.assertIsInstance(head(stores, gone.entity_id, iso(CAPTURE_2, seconds=5)), UsableBook)
            with self.assertRaises(emit.EmitConflict):
                capture(stores, b"[1, 2", t1=iso(CAPTURE_2, seconds=60), expected_scope=expected)
            self.assertEqual(len([r for r in pit_rows(stores) if r["entity_id"] == gone.entity_id]), 1)

    def test_the_expected_scope_holds_only_open_or_suspended_heads_of_the_declared_books(self):
        with scratch_root() as root:
            stores = build_stores(root)
            payload = self.two_bookmakers()
            del market_of(payload, "fixture-book-a", "101")["outcomes"]["102"]                    # BLOCKED
            price_of(payload, "pinnacle", "1010", "2002")["active"] = False                     # SUSPENDED
            parsed, _, result = capture(stores, payload)
            expected = self.expected_at(stores, result.t3)
            states = {book.entity_id: book.state for book in parsed.books}
            self.assertEqual({states[e] for e in expected}, {"OPEN", "SUSPENDED"})
            self.assertNotIn("BLOCKED", {states[e] for e in expected})
            self.assertEqual(self.expected_at(stores, iso(result.t3, micros=-1)), {})           # nothing ready yet
            narrowed = scope.build_expected_scope(pit=stores.pit, evidence=stores.evidence, source_id=stores.source_id,
                                                  decision_at=result.t3, competition_ids=("soccer.esp.laliga",),
                                                  bookmaker_ids=("bk.pinnacle",))
            self.assertEqual(narrowed, {})

    def test_a_scope_artifact_is_immutable_and_verified_on_load(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, result = capture(stores, small_payload())
            expected = self.expected_at(stores, result.t3)
            digest = scope.publish_scope(root, expected.values(), as_of=result.t3)
            self.assertEqual(scope.publish_scope(root, expected.values(), as_of=result.t3), digest)   # idempotent
            path = root / "scopes" / f"{digest}.json"
            path.write_bytes(path.read_bytes().replace(b"FT_REGULAR", b"FT_REGULAX"))
            with self.assertRaises(scope.ScopeError):
                scope.load_scope(root, digest)


class FreshnessTests(unittest.TestCase):
    def test_fr01_the_ttl_boundary_is_exact(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, _ = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            ttl = stores.policy.price_ttl_seconds
            self.assertIsInstance(head(stores, entity, iso(CAPTURE_1, seconds=ttl, micros=-1)), UsableBook)
            stale = head(stores, entity, iso(CAPTURE_1, seconds=ttl))
            self.assertEqual(stale.code, err.AdapterFailure.MISSING_OR_STALE)
            self.assertEqual(stale.pass_reason.value, "PASS_STALE_EVIDENCE")

    def test_fr02_valid_to_is_capped_at_the_prematch_guard(self):
        with scratch_root() as root:
            stores = build_stores(root)
            guard = stores.policy.prematch_guard_seconds
            kickoff = iso(CAPTURE_1, seconds=guard + 600)                       # S - guard = T1 + 10 min < T1 + ttl
            payload = small_payload()
            fixture_of(payload)["startTime"] = kickoff
            parsed, _, _ = capture(stores, payload)
            entity = head_book(parsed).entity_id
            record = record_of(stores, entity, CAPTURE_1)
            self.assertEqual(record.valid_to, iso(kickoff, seconds=-guard))
            self.assertIsInstance(head(stores, entity, iso(kickoff, seconds=-guard, micros=-1)), UsableBook)
            self.assertEqual(head(stores, entity, iso(kickoff, seconds=-guard)).code, err.AdapterFailure.MISSING_OR_STALE)

    def test_fr03_a_failed_or_blocked_refresh_changes_nothing(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, _ = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            before = pit_rows(stores)
            for index, (label, body) in enumerate((("not json", b"{"), ("envelope", b'{"a": 1}'))):
                with self.subTest(label), self.assertRaises(emit.EmitConflict):
                    capture(stores, body, t1=iso(CAPTURE_2, seconds=60 * index), tag=label)
            self.assertEqual(pit_rows(stores), before)
            record = record_of(stores, entity, CAPTURE_1)
            self.assertEqual(record.valid_to, iso(CAPTURE_1, seconds=stores.policy.price_ttl_seconds))
            self.assertEqual(head(stores, entity, iso(CAPTURE_1, seconds=stores.policy.price_ttl_seconds)).code,
                             err.AdapterFailure.MISSING_OR_STALE)               # never extended

    def test_fr04_a_cache_hit_acquisition_can_never_become_an_observation(self):
        with scratch_root() as root:
            stores = build_stores(root)
            raw = ps.dump(small_payload())
            ctx = es.make_capture_ctx(stores, raw, t1=CAPTURE_1)
            aid, t0 = ctx.acquisition_id, ctx.request_started_at
            stores.acquisition.append("acq_planned", recorded_at=iso(t0, micros=-2000), acquisition_id=aid,
                                      request_id="oddspapi-attempt:" + aid, window_id="w", purpose="METADATA",
                                      attempt=1, provider_request_hash=ctx.provider_request_hash, role="ODDS",
                                      provider_metering="PER_REQUEST", provider_request_weight=1,
                                      provider_documented_billable=True, genesis_debit_units=1)
            stores.acquisition.append("acq_quota_decided", recorded_at=iso(t0, micros=-500), acquisition_id=aid,
                                      Tq=iso(t0, micros=-1000), frozen_ledger_reason="verified_cache_hit",
                                      allowed=True, genesis_units_debited=0, cache_entry_id="e" * 64,
                                      cache_miss_reason=None)
            with self.assertRaises(emit.EmitConflict):
                es.capture(stores, raw, ctx=ctx, seed=False)
            self.assertEqual(pit_rows(stores), [])
            self.assertEqual(stores.evidence.verify_manifest(), 0)


class CrashAndRebuildTests(unittest.TestCase):
    def test_pit08_a_crash_between_publication_and_the_pit_append_reuses_the_observation(self):
        with scratch_root() as root:
            stores = build_stores(root)
            raw = ps.dump(small_payload())
            ctx = es.make_capture_ctx(stores, raw, t1=CAPTURE_1)
            parsed = parser.parse_odds_response(raw, ctx)
            es.seed_acquisition(stores, ctx)

            def crash(name):
                if name == "after_t3":
                    raise Crash()

            with self.assertRaises(Crash):
                emit.emit_response(parsed, ctx, stores=stores, clock=SequenceClock(
                    [iso(CAPTURE_1, seconds=0.5), iso(CAPTURE_1, seconds=1)]), checkpoint=crash)
            self.assertEqual(pit_rows(stores), [])
            published = stores.evidence.verify_manifest()
            restarted = es.reopen(stores)
            result = emit.emit_response(parsed, ctx, stores=restarted,
                                        clock=SequenceClock([iso(CAPTURE_1, seconds=5), iso(CAPTURE_1, seconds=6),
                                                             iso(CAPTURE_1, seconds=7)]))
            self.assertEqual(restarted.evidence.verify_manifest(), published)       # nothing re-published
            rows = pit_rows(restarted)
            self.assertEqual(len(rows), len(result.pit_record_ids))
            self.assertEqual(len({row["record_id"] for row in rows}), len(rows))
            for row in rows:
                observations = restarted.evidence.get_observations(row["payload_hash"])
                self.assertEqual(len(observations), 1)
                self.assertEqual(observations[0].parse_ready_at, iso(CAPTURE_1, seconds=0.5))
                self.assertEqual(row["ready_at"], iso(CAPTURE_1, seconds=6))       # the new, later T3

    def test_pit09_rederiving_the_same_captures_into_empty_stores_gives_identical_artifacts_and_record_ids(self):
        payloads = [(small_payload(bookmakers=("pinnacle", "fixture-book-a")), CAPTURE_1),
                    (repriced(), CAPTURE_2)]

        def run(root):
            stores = build_stores(root)
            for payload, t1 in payloads:
                capture(stores, payload, t1=t1)
            return stores

        with scratch_root() as first_root, scratch_root() as second_root:
            first, second = run(first_root), run(second_root)
            key = lambda row: (row["entity_id"], row["available_at"])
            one = sorted(((key(r), r["payload_hash"], r["record_id"]) for r in pit_rows(first)))
            two = sorted(((key(r), r["payload_hash"], r["record_id"]) for r in pit_rows(second)))
            self.assertEqual(one, two)
            self.assertEqual(first.identity.head(), second.identity.head())



if __name__ == "__main__":
    unittest.main()
