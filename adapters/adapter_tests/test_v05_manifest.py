"""EV-05, EV-06 and RDR-01: manifests built through the shared predicate verify with the REAL frozen
verifier exactly when the reader says usable (public frozen interfaces only)."""

from __future__ import annotations

import json
import unittest

from genesis.evidence_pack import EvidencePack
from genesis.feature_manifest import FeatureInputManifestStore
from genesis.pit import BitemporalRecord

from genesis_adapters import errors as err
from genesis_adapters.oddspapi import emit, manifest
from genesis_adapters.oddspapi.reader import UsableBook, Unusable, admissible_head

from . import parser_support as ps
from .parity_support import verifier_verdict
from .parser_support import FIXTURE_A, FIXTURE_B, fixture_of, price_of
from .pipeline_support import approve, documents, odds_item, odds_response, open_rt, pit_rows
from .support import SequenceClock, scratch_root

OU = "SOCCER_TOTAL_GOALS_OU_FT"
ZERO = "0" * 64


def records(rt, entity_id=None):
    found = [BitemporalRecord(**{key: row[key] for key in BitemporalRecord.__dataclass_fields__})
             for row in pit_rows(rt) if entity_id is None or row["entity_id"] == entity_id]
    return sorted(found, key=lambda record: record.valid_from)


def doc_of(rt, record):
    return json.loads(rt.stores.evidence.get_bytes(record.payload_hash))


def ou_entities(rt, fixture=FIXTURE_A):
    seen = {}
    for record in records(rt):
        document = doc_of(rt, record)
        if document["market_family"] == OU and document["provider_fixture_id"]["value"] == fixture:
            seen[record.entity_id] = document
    return seen


def verify_body(rt, root, body, label):
    store = FeatureInputManifestStore(root / f"manifests-{label}", bindings=rt.stores.bindings)
    digest = store.publish(body)
    pack = EvidencePack.freeze(
        pack_id=f"pack-{label}", evidence_cutoff_ts=body["evidence_cutoff_ts"], frozen_at=body["evidence_cutoff_ts"],
        source_artifact_hashes=tuple(sorted({ref["raw_artifact_hash"] for ref in body["required_inputs"]})),
        extractor_versions=(rt.config.derivation_version,), prompt_schema_hash=ZERO, contradiction_links=(),
        freshness_state=(), feature_manifest_hash=digest,
        structured_evidence_hashes=tuple(body["structured_evidence_hashes"]))
    return store.verify_for_pack(pack, event_id=body["event_id"], market_id=body["market_id"], pit=rt.stores.pit,
                                 evidence=rt.stores.evidence, structured_evidence=rt.stores.structured)


class BuildTests(unittest.TestCase):
    def ready(self, root, script=None):
        rt = open_rt(root / "runtime", script=script or [odds_response()])
        approve(rt)
        rt.acquire(odds_item())
        return rt

    def test_ev05_a_manifest_built_at_d_passes_the_frozen_verifier_unchanged(self):
        with scratch_root() as root:
            rt = self.ready(root)
            decision_at = ps.iso_add(records(rt)[0].ready_at, seconds=10)
            entities = ou_entities(rt)
            books = [admissible_head(entity, decision_at, stores=rt.stores) for entity in sorted(entities)]
            self.assertTrue(all(isinstance(book, UsableBook) for book in books))
            first = books[0].document
            body = manifest.build_manifest_body(event_id=first["event_id"], market_id=first["market_id"],
                                                decision_at=decision_at, books=books, selections=("OVER", "UNDER"),
                                                stores=rt.stores)
            self.assertEqual(len(body["required_inputs"]), 6)
            self.assertEqual(len(body["structured_evidence_hashes"]), 3)
            for ref in body["required_inputs"]:
                self.assertEqual(ref["raw_artifact_hash"], next(
                    book.observation.artifact_hash for book in books if book.entity_id == ref["entity_id"]))
                self.assertTrue(ref["input_key"].startswith("odds.bk."))
            verified = verify_body(rt, root, body, "ev05")
            self.assertEqual({record.record_id for record in verified}, {book.record.record_id for book in books})
            published = manifest.publish_manifest(body, stores=rt.stores, root=root / "manifests")
            self.assertEqual(len(published), 64)

    def test_ev06_manifests_pinning_a_non_open_head_or_a_superseded_record_fail_the_verifier(self):
        with scratch_root() as root:
            second = ps.odds_payload()
            price_of(second, "pinnacle", "1010", "2002")["active"] = False                   # SUSPENDED
            del fixture_of(second)["bookmakerOdds"]["fixture-book-a"]["markets"]["1010"]     # ABSENT
            fixture_of(second)["bookmakerOdds"]["fixture-book-b"]["markets"]["1010"]["outcomes"]["2001"][
                "players"]["0"]["active"] = "?"                                                # BLOCKED
            rt = self.ready(root, script=[odds_response(), odds_response(second)])
            rt.clock.advance(seconds=600)
            rt.acquire(odds_item("w2"))
            decision_at = ps.iso_add(records(rt)[-1].ready_at, seconds=10)
            by_state = {}
            for entity in ou_entities(rt):
                history = records(rt, entity)
                by_state[doc_of(rt, history[-1])["market_state"]] = history
            self.assertEqual(set(by_state), {"SUSPENDED", "ABSENT", "BLOCKED"})
            for state, history in by_state.items():
                with self.subTest(state):
                    verdict = admissible_head(history[-1].entity_id, decision_at, stores=rt.stores)
                    self.assertIsInstance(verdict, Unusable)
                    accepted, why = verifier_verdict(rt.stores, [(history[-1], "OVER")], decision_at=decision_at,
                                                     scratch=root, label=f"head-{state}")
                    self.assertFalse(accepted)
                    self.assertIn("absent from exact bytes", why)
                    accepted, why = verifier_verdict(rt.stores, [(history[0], "OVER")], decision_at=decision_at,
                                                     scratch=root, label=f"old-{state}")
                    self.assertFalse(accepted)
                    self.assertIn("unique as-of head", why)

    def test_the_builder_refuses_anything_but_current_usable_heads_of_one_event_and_market(self):
        with scratch_root() as root:
            rt = self.ready(root, script=[odds_response(), odds_response(self.repriced())])
            early = ps.iso_add(records(rt)[0].ready_at, seconds=10)
            entities = sorted(ou_entities(rt))
            book = admissible_head(entities[0], early, stores=rt.stores)
            other_event = admissible_head(sorted(ou_entities(rt, FIXTURE_B))[0], early, stores=rt.stores)
            document = book.document
            with self.assertRaises(manifest.ManifestError):                   # another event
                manifest.build_manifest_body(event_id=document["event_id"], market_id=document["market_id"],
                                             decision_at=early, books=[book, other_event], selections=("OVER",),
                                             stores=rt.stores)
            with self.assertRaises(manifest.ManifestError):                   # no such selection
                manifest.build_manifest_body(event_id=document["event_id"], market_id=document["market_id"],
                                             decision_at=early, books=[book], selections=("HOME",), stores=rt.stores)
            with self.assertRaises(manifest.ManifestError):                   # nothing to pin
                manifest.build_manifest_body(event_id=document["event_id"], market_id=document["market_id"],
                                             decision_at=early, books=[], selections=("OVER",), stores=rt.stores)
            rt.clock.advance(seconds=600)
            rt.acquire(odds_item("w2"))                                        # a newer price for every book
            later = ps.iso_add(records(rt)[-1].ready_at, seconds=10)
            with self.assertRaises(manifest.ManifestError):                   # the old head is no longer usable
                manifest.build_manifest_body(event_id=document["event_id"], market_id=document["market_id"],
                                             decision_at=later, books=[book], selections=("OVER",), stores=rt.stores)
            fresh = admissible_head(entities[0], later, stores=rt.stores)
            body = manifest.build_manifest_body(event_id=document["event_id"], market_id=document["market_id"],
                                                decision_at=later, books=[fresh], selections=("OVER",),
                                                stores=rt.stores)
            self.assertEqual(len(verify_body(rt, root, body, "fresh")), 1)

    @staticmethod
    def repriced():
        payload = ps.odds_payload()
        for key in ("pinnacle", "fixture-book-a", "fixture-book-b"):
            price_of(payload, key, "1010", "2001")["price"] = 1.9
        return payload


class ParityGridTests(unittest.TestCase):
    """RDR-01: for every scenario and a grid of cutoffs around T1, T3, published_at, valid_to and T_inv,
    ``admissible_head`` is usable iff a manifest the builder makes from it passes the frozen verifier and no
    adapter-only refusal applies; an unusable result never has a verifier-accepted record, except for the
    documented adapter-only refusals (STALE: at most the older record the verifier alone would accept)."""

    STALE_ONLY = {err.AdapterFailure.STALE, err.AdapterFailure.PREMATCH_WINDOW_CLOSED,
                  err.AdapterFailure.DERIVATION_UNVERIFIED}

    def scenario(self, root):
        tolerance = 5
        second = ps.odds_payload()
        price_of(second, "pinnacle", "1010", "2001")["changedAt"] = "@late"
        price_of(second, "fixture-book-a", "1010", "2002")["active"] = False
        fixture_of(second, FIXTURE_B)["startTime"] = "2026-10-01T12:40:00.000Z"          # kickoff moved earlier
        rt = open_rt(root / "runtime", script=[odds_response(), self.late(second, tolerance)])
        approve(rt)
        rt.acquire(odds_item("w1"))
        rt.clock.advance(seconds=600)
        rt.acquire(odds_item("w2"))
        victim = [r for r in records(rt) if doc_of(rt, r)["bookmaker_id"] == "bk.fixture-book-b"
                  and doc_of(rt, r)["market_family"] == OU and doc_of(rt, r)["provider_fixture_id"]["value"] == FIXTURE_A][-1]
        observation = [o for o in rt.stores.evidence.get_observations(victim.payload_hash)
                       if o.contract_id == rt.stores.contract_id][0]
        t_inv = ps.iso_add(victim.ready_at, seconds=120)
        emit.emit_invalidation(invalidated_observation_id=observation.observation_id,
                               invalidation_class="PROVIDER_ERROR_NOTICE", reason="PROVIDER_ERROR_NOTICE",
                               actor="OPERATOR", evidence_refs=("notice",), stores=rt.stores,
                               clock=SequenceClock([t_inv, ps.iso_add(t_inv, seconds=0.5), ps.iso_add(t_inv, seconds=1),
                                                    ps.iso_add(t_inv, seconds=1.5)]))
        return rt

    @staticmethod
    def late(payload, tolerance):
        def step(clock):
            from .support import ok
            text = ps.dump(payload).decode().replace('"@late"', json.dumps(ps.iso_add(clock.peek(), seconds=tolerance)))
            return ok(text.encode(), headers=(("content-type", "application/json"),))
        return step

    def cutoffs(self, history):
        points = set()
        for record in history:
            for moment in (record.valid_from, record.ready_at, record.valid_to, record.published_at):
                if moment:
                    for delta in (-1, 0, 1):
                        points.add(ps.iso_add(moment, micros=delta))
        return sorted(points)

    def test_rdr01_reader_builder_and_frozen_verifier_agree_on_the_whole_grid(self):
        with scratch_root() as root:
            rt = self.scenario(root)
            outcomes, checked = set(), 0
            entities = sorted({record.entity_id for record in records(rt)})
            for entity in entities:
                history = records(rt, entity)
                family = doc_of(rt, history[0])["market_family"]
                selection = "OVER" if family == OU else "HOME"
                for number, decision_at in enumerate(self.cutoffs(history)):
                    result = admissible_head(entity, decision_at, stores=rt.stores)
                    label = f"{entity[-6:]}-{number}"
                    if isinstance(result, UsableBook):
                        body = manifest.build_manifest_body(
                            event_id=result.document["event_id"], market_id=result.document["market_id"],
                            decision_at=decision_at, books=[result], selections=(selection,), stores=rt.stores)
                        verified = verify_body(rt, root, body, label)
                        self.assertEqual([r.record_id for r in verified], [result.record.record_id])
                        outcomes.add("USABLE")
                    else:
                        outcomes.add(result.code)
                        accepted = [r for r in history if r.admissible_at(decision_at) and verifier_verdict(
                            rt.stores, [(r, selection)], decision_at=decision_at, scratch=root,
                            label=f"{label}-{r.record_id[-6:]}")[0]]
                        if result.code in self.STALE_ONLY:
                            self.assertLessEqual(len(accepted), 1, f"{decision_at} {result}")
                        else:
                            self.assertEqual(accepted, [], f"{decision_at} {result}")
                    checked += 1
            self.assertGreater(checked, 100)
            self.assertLessEqual({"USABLE", err.AdapterFailure.MISSING_OR_STALE, err.AdapterFailure.SUSPENDED,
                                  err.AdapterFailure.NOT_PUBLISHED_AT_CUTOFF, err.AdapterFailure.INVALIDATED,
                                  err.AdapterFailure.STALE}, outcomes)


if __name__ == "__main__":
    unittest.main()
