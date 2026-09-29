"""RDR-02, RDR-03, F-36, F-39 and A-4 (unique head, ties block, no fallback); A-5 differential parity with the
REAL frozen verifier (public interfaces only) over a grid of cutoffs."""

from __future__ import annotations

import unittest

from genesis.pit import BitemporalRecord, OperationalStatus

from genesis_adapters import errors as err
from genesis_adapters.oddspapi import capability, reader
from genesis_adapters.oddspapi.reader import UsableBook, Unusable, admissible_head

from . import emit_support as es
from . import parser_support as ps
from .emit_support import (
    CAPABILITY_TIME, CAPTURE_1, CAPTURE_2, build_stores, capture, head_book, iso, pit_rows, small_payload,
)
from .parity_support import verifier_verdict
from .parser_support import fixture_of, price_of
from .support import scratch_root


def records_of(stores, entity_id):
    rows = [row for row in pit_rows(stores) if row["entity_id"] == entity_id]
    return [BitemporalRecord(**{key: row[key] for key in BitemporalRecord.__dataclass_fields__}) for row in rows]


def record_at(stores, entity_id, t1):
    found = [record for record in records_of(stores, entity_id) if record.available_at == t1]
    assert len(found) == 1
    return found[0]


def priced(over, under):
    payload = small_payload()
    price_of(payload, "pinnacle", "1010", "2001")["price"] = over
    price_of(payload, "pinnacle", "1010", "2002")["price"] = under
    return payload


class HeadSelectionTests(unittest.TestCase):
    """A-4: the head is chosen by the adapter, never taken from the frozen query's result order."""

    def test_the_head_is_the_unique_latest_admissible_record_not_the_first_by_record_id(self):
        with scratch_root() as root:
            stores = build_stores(root)
            prices = [(1.91, 1.95), (1.9, 1.96), (1.92, 1.94), (1.93, 1.93), (1.89, 1.97)]
            entity = None
            for index, (over, under) in enumerate(prices):
                parsed, _, _ = capture(stores, priced(over, under), t1=iso(CAPTURE_1, seconds=60 * index))
                entity = head_book(parsed).entity_id
            decision_at = iso(CAPTURE_1, seconds=60 * len(prices))
            admissible = stores.pit.as_of_query(entity, decision_at, source_id=stores.source_id)
            self.assertEqual(len(admissible), len(prices))
            self.assertEqual([r.record_id for r in admissible], sorted(r.record_id for r in admissible))
            newest = max(admissible, key=lambda record: record.valid_from)
            position = [r.record_id for r in admissible].index(newest.record_id)
            self.assertNotIn(position, (0, len(prices) - 1))       # both naive picks ([0], [-1]) would be wrong
            result = admissible_head(entity, decision_at, stores=stores)
            self.assertIsInstance(result, UsableBook)
            self.assertEqual(result.record, newest)
            self.assertEqual(result.document["selections"]["OVER"]["odds_decimal"], "1.89")
            accepted, why = verifier_verdict(stores, [(newest, "OVER")], decision_at=decision_at, scratch=root)
            self.assertTrue(accepted, why)
            for other in admissible:
                if other != newest:
                    accepted, _ = verifier_verdict(stores, [(other, "OVER")], decision_at=decision_at, scratch=root,
                                                   label=other.record_id[-8:])
                    self.assertFalse(accepted)

    def test_f39_and_rdr02_a_head_published_after_the_cutoff_is_unusable_with_no_fallback(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, _ = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            tolerance = stores.policy.provider_future_tolerance_seconds
            late = small_payload()
            published = iso(CAPTURE_2, seconds=tolerance)                  # T1 + tolerance: accepted by the parser
            price_of(late, "pinnacle", "1010", "2001")["changedAt"] = published
            _, _, second = capture(stores, late, t1=CAPTURE_2)
            older, newer = record_at(stores, entity, CAPTURE_1), record_at(stores, entity, CAPTURE_2)
            self.assertEqual(newer.published_at, published)
            self.assertLess(second.t3, published)
            for decision_at in (second.t3, iso(published, micros=-1)):
                with self.subTest(decision_at):
                    result = admissible_head(entity, decision_at, stores=stores)
                    self.assertIsInstance(result, Unusable)
                    self.assertEqual(result.code, err.AdapterFailure.NOT_PUBLISHED_AT_CUTOFF)
                    self.assertEqual(result.pass_reason.value, "PASS_MISSING_EVIDENCE")
                    for label, record in (("newer", newer), ("older", older)):       # the verifier agrees: neither
                        accepted, why = verifier_verdict(stores, [(record, "OVER")], decision_at=decision_at,
                                                         scratch=root, label=label + decision_at[-9:-1])
                        self.assertFalse(accepted, f"{label}: {why}")
            usable = admissible_head(entity, published, stores=stores)
            self.assertIsInstance(usable, UsableBook)
            self.assertEqual(usable.record, newer)

    def test_a_newer_capture_that_expired_early_is_never_silently_replaced_by_an_older_price(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, _ = capture(stores, small_payload())                # kickoff two days away
            entity = head_book(parsed).entity_id
            guard = stores.policy.prematch_guard_seconds
            moved = small_payload()
            fixture_of(moved)["startTime"] = iso(CAPTURE_2, seconds=guard + 600)   # the kickoff moved much earlier
            capture(stores, moved, t1=CAPTURE_2)
            older, newer = record_at(stores, entity, CAPTURE_1), record_at(stores, entity, CAPTURE_2)
            self.assertLess(newer.valid_to, older.valid_to)
            decision_at = iso(newer.valid_to, seconds=60)                  # newer expired, older still in its TTL
            self.assertEqual(stores.pit.as_of_query(entity, decision_at, source_id=stores.source_id), (older,))
            result = admissible_head(entity, decision_at, stores=stores)
            self.assertIsInstance(result, Unusable)
            self.assertEqual(result.code, err.AdapterFailure.STALE)
            # the frozen verifier alone would accept the older record here: this refusal is adapter-only
            accepted, why = verifier_verdict(stores, [(older, "OVER")], decision_at=decision_at, scratch=root)
            self.assertTrue(accepted, why)

    def test_a_tie_between_the_two_latest_records_blocks_and_never_picks_one(self):
        # covered end to end by test_v05_pit PIT-03; here the reader must not rely on the frozen call raising
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, _ = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            record = record_at(stores, entity, CAPTURE_1)

            class Query:
                def __init__(self, inner):
                    self.inner = inner

                def __getattr__(self, name):
                    return getattr(self.inner, name)

                def as_of_query(self, entity_id, decision_at, *, source_id=None):
                    import dataclasses
                    twin = dataclasses.replace(record, record_id="pit:" + "f" * 64)
                    return (record, twin)                            # a tie the frozen store did not raise for

            import dataclasses as dc
            tied = dc.replace(stores, pit=Query(stores.pit))
            result = admissible_head(entity, iso(CAPTURE_1, seconds=5), stores=tied)
            self.assertEqual(result.code, err.AdapterFailure.AMBIGUOUS)


class SourceTests(unittest.TestCase):
    def test_f36_no_ready_source_is_data_capability_not_ready(self):
        with scratch_root() as root:
            stores = build_stores(root, ready=False)
            parsed, _, result = capture(stores, small_payload())
            verdict = admissible_head(head_book(parsed).entity_id, result.t3, stores=stores)
            self.assertEqual(verdict.code, err.AdapterFailure.DATA_CAPABILITY_NOT_READY)
            self.assertEqual(verdict.pass_reason.value, "PASS_DATA_CAPABILITY_NOT_READY")
            capability.register_downgrade(stores.capabilities, stores.source_id, status=OperationalStatus.UNKNOWN,
                                          at=CAPABILITY_TIME, reason="G2R")
            verdict = admissible_head(head_book(parsed).entity_id, result.t3, stores=stores)
            self.assertEqual(verdict.code, err.AdapterFailure.DATA_CAPABILITY_NOT_READY)

    def test_f36_two_ready_market_book_sources_fail_closed(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, result = capture(stores, small_payload())
            other = es.with_version(stores, "mb1-" + "0" * 16)
            es.approve_source(other, at=CAPABILITY_TIME)
            verdict = admissible_head(head_book(parsed).entity_id, result.t3, stores=stores)
            self.assertEqual(verdict.code, err.AdapterFailure.AMBIGUOUS_SOURCE)
            self.assertEqual(verdict.pass_reason.value, "PASS_DATA_CAPABILITY_NOT_READY")

    def test_rdr03_a_missing_binding_is_refused_like_the_verifier_refuses_it(self):
        with scratch_root() as root:
            stores = build_stores(root, ready=False)
            stores.capabilities.register(es.source_capability(stores, status=OperationalStatus.READY,
                                                              at=CAPABILITY_TIME, suffix="ready-1"))
            parsed, _, result = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            verdict = admissible_head(entity, result.t3, stores=stores)
            self.assertEqual(verdict.code, err.AdapterFailure.PARITY_FAILURE)
            accepted, why = verifier_verdict(stores, [(record_at(stores, entity, CAPTURE_1), "OVER")],
                                             decision_at=result.t3, scratch=root)
            self.assertFalse(accepted)
            self.assertIn("approved mapping", why)

    def test_rdr03_a_binding_to_another_contract_is_refused(self):
        with scratch_root() as root:
            stores = build_stores(root, ready=False)
            stores.capabilities.register(es.source_capability(stores, status=OperationalStatus.READY,
                                                              at=CAPABILITY_TIME, suffix="ready-1"))
            stores.bindings.register(source_id=stores.source_id, source_contract_id="oddspapi-v4-raw-response-v1",
                                     provider="oddspapi", approval_reference="synthetic-test-only-binding")
            parsed, _, result = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            self.assertEqual(admissible_head(entity, result.t3, stores=stores).code, err.AdapterFailure.PARITY_FAILURE)
            accepted, _ = verifier_verdict(stores, [(record_at(stores, entity, CAPTURE_1), "OVER")],
                                           decision_at=result.t3, scratch=root)
            self.assertFalse(accepted)

    def test_rdr03_a_capability_head_that_is_not_unique_at_the_cutoff_is_refused(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, result = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            twin = es.source_capability(stores, status=OperationalStatus.READY, at=CAPABILITY_TIME, suffix="ready-2")
            stores.capabilities.log.append({"record_type": "source_capability_registered", **twin.to_dict()})
            verdict = admissible_head(entity, result.t3, stores=stores)
            self.assertEqual(verdict.code, err.AdapterFailure.AMBIGUOUS_SOURCE)
            accepted, why = verifier_verdict(stores, [(record_at(stores, entity, CAPTURE_1), "OVER")],
                                             decision_at=result.t3, scratch=root)
            self.assertFalse(accepted)
            self.assertIn("capability head differs", why)

    def test_a_blocked_capability_stops_every_record_including_current_prices(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, result = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            t_fix = iso(result.t3, seconds=10)
            capability.register_downgrade(stores.capabilities, stores.source_id, status=OperationalStatus.BLOCKED,
                                          at=t_fix, reason="DERIVATION_DEFECT")
            self.assertIsInstance(admissible_head(entity, iso(t_fix, micros=-1), stores=stores), UsableBook)
            self.assertEqual(admissible_head(entity, t_fix, stores=stores).code,
                             err.AdapterFailure.DATA_CAPABILITY_NOT_READY)
            accepted, _ = verifier_verdict(stores, [(record_at(stores, entity, CAPTURE_1), "OVER")],
                                           decision_at=t_fix, scratch=root)
            self.assertFalse(accepted)


class ObservationParityTests(unittest.TestCase):
    def test_a_pit_record_that_outlives_its_observation_is_a_parity_failure_and_never_a_price(self):
        import dataclasses
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, result = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            genuine = record_at(stores, entity, CAPTURE_1)
            later = iso(CAPTURE_1, micros=1)
            forged = dataclasses.replace(genuine, record_id="pit:" + "e" * 64, available_at=later, retrieved_at=later,
                                         valid_from=later, valid_to=iso(genuine.valid_to, seconds=3600))
            stores.pit.append(forged)                              # a record that disagrees with its observation
            decision_at = iso(genuine.valid_to, seconds=60)
            verdict = admissible_head(entity, decision_at, stores=stores)
            self.assertIsInstance(verdict, Unusable)
            self.assertEqual(verdict.code, err.AdapterFailure.PARITY_FAILURE)
            self.assertIn("observation", verdict.detail)
            self.assertEqual(verdict.pass_reason.value, "PASS_GATE_ERROR")
            accepted, why = verifier_verdict(stores, [(forged, "OVER")], decision_at=decision_at, scratch=root)
            self.assertFalse(accepted)
            self.assertIn("not exact and ready at cutoff", why)


class AdapterOnlyRefusalTests(unittest.TestCase):
    def test_non_open_heads_are_unusable_with_their_state_and_reasons(self):
        with scratch_root() as root:
            stores = build_stores(root)
            payload = small_payload()
            price_of(payload, "pinnacle", "1010", "2002")["active"] = False
            del payload[0]["bookmakerOdds"]["pinnacle"]["markets"]["101"]["outcomes"]["102"]
            parsed, _, result = capture(stores, payload)
            ou = head_book(parsed)
            one = ps.one_book(parsed, family="SOCCER_1X2_FT")
            self.assertEqual((admissible_head(ou.entity_id, result.t3, stores=stores).code,
                              admissible_head(one.entity_id, result.t3, stores=stores).code),
                             (err.AdapterFailure.SUSPENDED, err.AdapterFailure.BLOCKED))
            self.assertEqual(admissible_head(one.entity_id, result.t3, stores=stores).reasons,
                             ("INCOMPLETE_SELECTIONS",))

    def test_a_failed_derivation_check_refuses_the_head(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, result = capture(stores, small_payload())
            entity = head_book(parsed).entity_id

            def failing(observation_id):
                raise ValueError("does not re-derive")

            verdict = admissible_head(entity, result.t3, stores=stores, derivation_check=failing)
            self.assertEqual(verdict.code, err.AdapterFailure.DERIVATION_UNVERIFIED)
            self.assertEqual(verdict.pass_reason.value, "PASS_GATE_ERROR")
            seen = []
            usable = admissible_head(entity, result.t3, stores=stores, derivation_check=seen.append)
            self.assertIsInstance(usable, UsableBook)
            self.assertEqual(seen, [usable.observation.observation_id])

    def test_the_reader_class_is_exactly_the_shared_predicate(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, result = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            for decision_at in (iso(result.t3, micros=-1), result.t3, iso(CAPTURE_1, seconds=3600)):
                self.assertEqual(reader.MarketBookReader(stores).head(entity, decision_at),
                                 admissible_head(entity, decision_at, stores=stores))

    def test_a_non_canonical_or_unparseable_cutoff_is_refused(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, result = capture(stores, small_payload())
            entity = head_book(parsed).entity_id
            self.assertEqual(admissible_head(entity, "yesterday", stores=stores).code, err.AdapterFailure.PARITY_FAILURE)
            self.assertEqual(admissible_head(entity, "2026-10-01T13:00:00", stores=stores).code,
                             err.AdapterFailure.PARITY_FAILURE)                         # naive
            self.assertIsInstance(admissible_head(entity, "2026-10-01T12:30:00Z", stores=stores), UsableBook)


class DifferentialParityTests(unittest.TestCase):
    """A-5: usable <=> the frozen verifier accepts a manifest pinning the head, unless an adapter-only
    refusal applies; and an unusable result never has a record the verifier would accept, except for the
    documented adapter-only refusals."""

    # refusals the frozen verifier does not make itself (design 12.3 step 7 plus the no-fallback rule)
    STALE_ONLY = {err.AdapterFailure.PREMATCH_WINDOW_CLOSED, err.AdapterFailure.DERIVATION_UNVERIFIED,
                  err.AdapterFailure.STALE}

    def scenario(self, root):
        stores = build_stores(root)
        parsed, _, _ = capture(stores, small_payload(bookmakers=("pinnacle", "fixture-book-a")))
        tolerance = stores.policy.provider_future_tolerance_seconds
        second = small_payload(bookmakers=("pinnacle", "fixture-book-a"))
        price_of(second, "pinnacle", "1010", "2001")["changedAt"] = iso(CAPTURE_2, seconds=tolerance)
        price_of(second, "fixture-book-a", "1010", "2002")["active"] = False
        capture(stores, second, t1=CAPTURE_2)
        return stores, [book.entity_id for book in parsed.books]

    def cutoffs(self, stores, entity):
        points = set()
        for record in records_of(stores, entity):
            for moment in (record.valid_from, record.ready_at, record.valid_to, record.published_at):
                if moment:
                    for delta in (-1, 0, 1):
                        points.add(iso(moment, micros=delta))
        return sorted(points)

    def test_a5_reader_and_frozen_verifier_agree_on_every_cutoff(self):
        with scratch_root() as root:
            stores, entities = self.scenario(root)
            checked, seen = 0, set()
            for entity in entities:
                family = es.doc_json(stores, records_of(stores, entity)[0].payload_hash)["market_family"]
                selection = "HOME" if family == "SOCCER_1X2_FT" else "OVER"
                for number, decision_at in enumerate(self.cutoffs(stores, entity)):
                    result = admissible_head(entity, decision_at, stores=stores)
                    candidates = [r for r in records_of(stores, entity) if r.admissible_at(decision_at)]
                    verdicts = {}
                    for record in candidates:
                        accepted, why = verifier_verdict(stores, [(record, selection)], decision_at=decision_at,
                                                         scratch=root, label=f"{entity[-6:]}-{number}-{record.record_id[-6:]}")
                        verdicts[record.record_id] = (accepted, why)
                    accepted_ids = {rid for rid, (ok, _) in verdicts.items() if ok}
                    if isinstance(result, UsableBook):
                        self.assertEqual(accepted_ids, {result.record.record_id}, decision_at)
                    elif result.code in self.STALE_ONLY:
                        self.assertLessEqual(len(accepted_ids), 1, decision_at)      # verifier looser, reader safe
                    else:
                        self.assertEqual(accepted_ids, set(), f"{decision_at} {result}")
                    seen.add(result.code if isinstance(result, Unusable) else "USABLE")
                    checked += 1
            self.assertGreater(checked, 20)
            self.assertLessEqual({"USABLE", err.AdapterFailure.MISSING_OR_STALE, err.AdapterFailure.SUSPENDED,
                                  err.AdapterFailure.NOT_PUBLISHED_AT_CUTOFF}, seen)


if __name__ == "__main__":
    unittest.main()
