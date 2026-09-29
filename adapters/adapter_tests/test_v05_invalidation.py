"""INV-01 .. INV-04, PIT-06, F-40: append-only invalidation with its own admissible time."""

from __future__ import annotations

import json
import unittest

from genesis.pit import BitemporalRecord
from genesis.provenance import AvailabilityClass
from genesis.registry import RegistryConflict
from genesis.repro import canonical_json

from genesis_adapters import errors as err
from genesis_adapters.clock import ClockFault
from genesis_adapters.oddspapi import emit, invalidation as inv
from genesis_adapters.oddspapi.reader import UsableBook, Unusable, admissible_head

from . import emit_support as es
from .emit_support import CAPTURE_1, CAPTURE_2, build_stores, capture, coverage_rows, head_book, iso, pit_rows, small_payload
from .parity_support import manifest_body, verifier_verdict
from .parser_support import price_of
from .support import Crash, SequenceClock, scratch_root

T_INV = iso(CAPTURE_1, seconds=600)                 # 12:10
T2_INV, T3_INV, APPLIED = iso(T_INV, seconds=0.5), iso(T_INV, seconds=1), iso(T_INV, seconds=1.000001)


def record_at(stores, entity_id, t1):
    rows = [row for row in pit_rows(stores) if row["entity_id"] == entity_id and row["available_at"] == t1]
    assert len(rows) == 1
    return BitemporalRecord(**{key: rows[0][key] for key in BitemporalRecord.__dataclass_fields__})


def observation_of(stores, record):
    found = [o for o in stores.evidence.get_observations(record.payload_hash) if o.contract_id == stores.contract_id]
    assert len(found) == 1
    return found[0]


def invalidate(stores, observation_id, *, clock=None, cls="PROVIDER_ERROR_NOTICE", reason="PROVIDER_ERROR_NOTICE",
               actor="OPERATOR", refs=("notice-1",), checkpoint=None):
    return emit.emit_invalidation(invalidated_observation_id=observation_id, invalidation_class=cls, reason=reason,
                                  actor=actor, evidence_refs=refs, stores=stores,
                                  clock=clock or SequenceClock([T_INV, T2_INV, T3_INV, APPLIED]),
                                  checkpoint=checkpoint)


def one_capture(root):
    stores = build_stores(root)
    parsed, _, result = capture(stores, small_payload())
    entity = head_book(parsed).entity_id
    record = record_at(stores, entity, CAPTURE_1)
    return stores, entity, record, observation_of(stores, record)


class CurrentHeadTests(unittest.TestCase):
    def test_inv01_and_pit06_invalidating_the_current_head_changes_only_cutoffs_after_t3_inv(self):
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            before_cutoff = iso(CAPTURE_1, seconds=300)
            accepted, why = verifier_verdict(stores, [(record, "OVER")], decision_at=before_cutoff, scratch=root,
                                             label="early")
            self.assertTrue(accepted, why)
            early_manifest, _ = manifest_body(stores, [(record, "OVER")], decision_at=before_cutoff)
            result = invalidate(stores, observation.observation_id)
            self.assertEqual((result.head_effect, result.t_inv), (inv.EFFECT_EMITTED, T_INV))
            invalidated = record_at(stores, entity, T_INV)
            self.assertEqual((invalidated.ready_at, invalidated.valid_to, invalidated.published_at),
                             (T3_INV, None, None))
            self.assertEqual(invalidated.record_id, result.invalidation_pit_record_id)
            for decision_at in (before_cutoff, T_INV, iso(T3_INV, micros=-1)):      # D < T3_inv: unchanged
                with self.subTest(decision_at):
                    usable = admissible_head(entity, decision_at, stores=stores)
                    self.assertIsInstance(usable, UsableBook)
                    self.assertEqual(usable.record, record)
                    accepted, why = verifier_verdict(stores, [(record, "OVER")], decision_at=decision_at,
                                                     scratch=root, label="before" + decision_at[-12:-1])
                    self.assertTrue(accepted, why)
            accepted, why = verifier_verdict(stores, [(record, "OVER")], decision_at=before_cutoff, scratch=root,
                                             label="early-again")
            self.assertTrue(accepted, why)                                    # the early manifest still verifies
            self.assertEqual(manifest_body(stores, [(record, "OVER")], decision_at=before_cutoff)[0], early_manifest)
            for decision_at in (T3_INV, iso(T3_INV, seconds=86400 * 7)):
                with self.subTest(decision_at):
                    verdict = admissible_head(entity, decision_at, stores=stores)
                    self.assertIsInstance(verdict, Unusable)
                    self.assertEqual((verdict.code, verdict.reasons),
                                     (err.AdapterFailure.INVALIDATED, ("PROVIDER_ERROR_NOTICE",)))
                    self.assertEqual(verdict.pass_reason.value, "PASS_CONTRADICTION")
            accepted, why = verifier_verdict(stores, [(record, "OVER")], decision_at=T3_INV, scratch=root, label="late")
            self.assertFalse(accepted)
            self.assertIn("unique as-of head", why)
            accepted, why = verifier_verdict(stores, [(invalidated, "OVER")], decision_at=T3_INV, scratch=root,
                                             label="inv")
            self.assertFalse(accepted)                                        # an INVALIDATED head has no price

    def test_the_invalidation_document_and_observation_follow_design_9_1a_and_11_3(self):
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            result = invalidate(stores, observation.observation_id)
            published = stores.evidence.get_observation(result.invalidation_observation_id)
            document = json.loads(stores.evidence.get_bytes(published.artifact_hash))
            target = json.loads(stores.evidence.get_bytes(record.payload_hash))
            row = stores.invalidations.state()[result.invalidation_id]["recorded"]
            self.assertEqual((document["derivation_kind"], document["market_state"], document["state_reasons"]),
                             ("INVALIDATION", "INVALIDATED", ["PROVIDER_ERROR_NOTICE"]))
            self.assertNotIn("selections", document)
            self.assertEqual((document["valid_from"], document["valid_to"], document["times"]),
                             (T_INV, None, {"invalidation_recorded_at": T_INV}))
            for key in ("derivation_version", "entity_id", "event_id", "market_id", "bookmaker_id", "line", "period",
                        "scheduled_start_as_known", "competition_id", "side"):
                self.assertEqual(document[key], target[key], key)
            self.assertEqual((document["invalidated_observation_id"], document["invalidated_artifact_hash"],
                              document["invalidated_pit_record_id"]),
                             (observation.observation_id, record.payload_hash, record.record_id))
            self.assertEqual(document["invalidation_ledger_head"],
                             {"sequence": row["sequence"], "record_hash": row["record_hash"]})
            self.assertEqual((published.retrieved_at, published.first_seen_at, published.valid_from,
                              published.valid_to, published.publisher_timestamp, published.parse_ready_at),
                             (T_INV, T_INV, T_INV, None, None, T2_INV))
            self.assertEqual(published.availability_class, AvailabilityClass.DERIVED)
            self.assertEqual(published.source_uri,
                             f"genesis-derived:oddspapi-v4-market-book:{stores.derivation_version}:{entity}"
                             f":invalidation:{result.invalidation_id}")
            self.assertEqual(stores.evidence.get_bytes(published.artifact_hash),
                             inv.build_invalidation_document(
                                 {k: v for k, v in row.items() if k not in ("previous_hash", "sequence", "record_hash")},
                                 target, ledger_head=document["invalidation_ledger_head"]))


class SupersededTests(unittest.TestCase):
    def test_inv02_invalidating_a_superseded_record_writes_no_pit_record_and_changes_no_cutoff(self):
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            newer = small_payload()
            price_of(newer, "pinnacle", "1010", "2001")["price"] = 1.9
            capture(stores, newer, t1=CAPTURE_2)
            grid = [iso(CAPTURE_1, seconds=1), iso(CAPTURE_2, seconds=0.5), iso(CAPTURE_2, seconds=1),
                    iso(CAPTURE_2, seconds=3600), iso(CAPTURE_2, seconds=86400)]
            before = [admissible_head(entity, d, stores=stores) for d in grid]
            rows_before = pit_rows(stores)
            result = invalidate(stores, observation.observation_id,
                                clock=SequenceClock([iso(CAPTURE_2, seconds=60), iso(CAPTURE_2, seconds=61)]))
            self.assertEqual(result.head_effect, inv.EFFECT_SUPERSEDED)
            self.assertIsNone(result.invalidation_pit_record_id)
            self.assertEqual(pit_rows(stores), rows_before)
            self.assertEqual([admissible_head(entity, d, stores=stores) for d in grid], before)
            applied = stores.invalidations.state()[result.invalidation_id]["applied"]
            self.assertEqual((applied["head_effect"], applied["invalidation_observation_id"],
                              applied["invalidation_pit_record_id"]), ("NONE_ALREADY_SUPERSEDED", None, None))


class DerivationTests(unittest.TestCase):
    def emitted(self, root):
        stores, entity, record, observation = one_capture(root)
        result = invalidate(stores, observation.observation_id)
        return stores, entity, record, result

    def test_inv03_the_invalidation_document_rebuilds_byte_for_byte(self):
        with scratch_root() as root:
            stores, entity, record, result = self.emitted(root)
            inv.verify_invalidation_derivation(result.invalidation_observation_id, stores=stores)

    def test_inv03_a_tampered_ledger_row_fails_verification(self):
        with scratch_root() as root:
            stores, entity, record, result = self.emitted(root)
            path = root / "invalidations.jsonl"
            path.write_bytes(path.read_bytes().replace(b"notice-1", b"notice-2"))
            with self.assertRaises(RegistryConflict):
                inv.verify_invalidation_derivation(result.invalidation_observation_id, stores=stores)

    def forged(self, stores, result, **changes):
        published = stores.evidence.get_observation(result.invalidation_observation_id)
        document = json.loads(stores.evidence.get_bytes(published.artifact_hash))
        document.update(changes)
        return stores.evidence.publish(
            canonical_json(document), contract_id=stores.contract_id,
            source_uri=published.source_uri + ":forged", provider="oddspapi", source_type=published.source_type,
            retrieved_at=published.retrieved_at, parse_ready_at=published.parse_ready_at,
            first_seen_at=published.first_seen_at, parser_version=published.parser_version,
            content_type=published.content_type, licensing_note=published.licensing_note,
            availability_class=published.availability_class, upstream_version=published.upstream_version,
            valid_from=published.valid_from, valid_to=None).observation_id

    def test_inv03_a_wrong_target_hash_or_pit_record_fails_verification(self):
        with scratch_root() as root:
            stores, entity, record, result = self.emitted(root)
            for label, changes in (("target hash", {"invalidated_artifact_hash": "0" * 64}),
                                   ("pit record", {"invalidated_pit_record_id": "pit:" + "0" * 64}),
                                   ("reason", {"invalidation_reason": "OPERATOR_INVALIDATION"}),
                                   ("ledger head", {"invalidation_ledger_head": {"sequence": 9, "record_hash": "0" * 64}}),
                                   ("unknown invalidation", {"invalidation_id": "1" * 64})):
                with self.subTest(label), self.assertRaises(inv.InvalidationDerivationError):
                    inv.verify_invalidation_derivation(self.forged(stores, result, **changes), stores=stores)

    def test_inv03_a_response_document_is_not_an_invalidation_document(self):
        with scratch_root() as root:
            stores, entity, record, result = self.emitted(root)
            with self.assertRaises(inv.InvalidationDerivationError):
                inv.verify_invalidation_derivation(observation_of(stores, record).observation_id, stores=stores)


class TimingTests(unittest.TestCase):
    def test_inv04_a_t_inv_equal_to_the_latest_valid_from_is_read_again_until_strictly_later(self):
        with scratch_root() as root:
            stores = build_stores(root)
            parsed, _, _ = capture(stores, small_payload(), t2=CAPTURE_1, t3=CAPTURE_1)     # T1 = T2 = T3
            entity = head_book(parsed).entity_id
            record = record_at(stores, entity, CAPTURE_1)
            later = iso(CAPTURE_1, micros=1)
            clock = SequenceClock([CAPTURE_1, CAPTURE_1, later, iso(later, micros=1), iso(later, micros=2),
                                   iso(later, micros=3)])
            result = invalidate(stores, observation_of(stores, record).observation_id, clock=clock)
            self.assertEqual(result.t_inv, later)
            self.assertEqual(record_at(stores, entity, later).valid_from, later)

    def test_a_clock_behind_the_durable_heads_is_a_fault_and_writes_nothing(self):
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            with self.assertRaises(ClockFault):
                invalidate(stores, observation.observation_id, clock=SequenceClock([iso(CAPTURE_1, micros=-1)]))
            self.assertEqual(stores.invalidations.rows(), ())

    def test_t_inv_is_never_before_what_is_already_durable(self):
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            between = iso(record.valid_from, seconds=0.5)                   # after valid_from, before ready_at
            self.assertLess(between, record.ready_at)
            with self.assertRaises(ClockFault):
                invalidate(stores, observation.observation_id, clock=SequenceClock([between]))
            self.assertEqual(stores.invalidations.rows(), ())
            invalidate(stores, observation.observation_id)                  # recorded at T_INV, applied just after
            other_entity = next(row["entity_id"] for row in pit_rows(stores) if row["entity_id"] != entity)
            other = observation_of(stores, record_at(stores, other_entity, CAPTURE_1))
            behind_ledger = iso(T_INV, seconds=-60)                          # after that book's ready_at ...
            self.assertLess(record_at(stores, other_entity, CAPTURE_1).ready_at, behind_ledger)
            with self.assertRaises(ClockFault):                              # ... but behind the invalidation ledger
                invalidate(stores, other.observation_id, refs=("n2",), clock=SequenceClock([behind_ledger]))
            self.assertEqual(len(stores.invalidations.rows()), 2)

    def test_inv04_a_later_genuine_capture_supersedes_the_invalidated_head(self):
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            invalidate(stores, observation.observation_id)
            self.assertEqual(admissible_head(entity, iso(CAPTURE_2, seconds=5), stores=stores).code,
                             err.AdapterFailure.INVALIDATED)
            newer = small_payload()
            price_of(newer, "pinnacle", "1010", "2001")["price"] = 1.9
            _, _, result = capture(stores, newer, t1=CAPTURE_2)
            usable = admissible_head(entity, result.t3, stores=stores)
            self.assertIsInstance(usable, UsableBook)
            self.assertEqual(usable.document["selections"]["OVER"]["odds_decimal"], "1.9")

    def test_inv04_a_failed_derivation_check_invalidates_the_head_automatically(self):
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            passed = emit.invalidate_if_underivable(observation.observation_id, check=lambda _: None, stores=stores,
                                                    clock=SequenceClock([]))
            self.assertIsNone(passed)
            self.assertEqual(stores.invalidations.rows(), ())

            def failing(_):
                raise ValueError("the raw bytes re-derive to a different document")

            result = emit.invalidate_if_underivable(observation.observation_id, check=failing, stores=stores,
                                                    clock=SequenceClock([T_INV, T2_INV, T3_INV, APPLIED]))
            row = stores.invalidations.state()[result.invalidation_id]["recorded"]
            self.assertEqual((row["invalidation_class"], row["reason"], row["actor"]),
                             ("DERIVATION_DEFECT", "DERIVATION_UNVERIFIED", "ADAPTER_AUTOMATIC"))
            verdict = admissible_head(entity, T3_INV, stores=stores)
            self.assertEqual((verdict.code, verdict.reasons),
                             (err.AdapterFailure.INVALIDATED, ("DERIVATION_UNVERIFIED",)))


class CoverageAndRefusalTests(unittest.TestCase):
    def test_f40_invalidation_coverage_is_quarantined_with_the_class_reason(self):
        for cls, reason, expected in (("PROVIDER_ERROR_NOTICE", "PROVIDER_ERROR_NOTICE", "contradictory_evidence"),
                                      ("OPERATOR", "OPERATOR_INVALIDATION", "contradictory_evidence"),
                                      ("OBSERVATION_DEFECT", "INVALIDATED", "contradictory_evidence"),
                                      ("DERIVATION_DEFECT", "DERIVATION_UNVERIFIED", "artifact_tampered")):
            with self.subTest(cls), scratch_root() as root:
                stores, entity, record, observation = one_capture(root)
                invalidate(stores, observation.observation_id, cls=cls, reason=reason)
                rows = [r for r in coverage_rows(stores) if r["note"].startswith("INVALIDATED:")]
                self.assertEqual([(r["status"], r["reason_codes"], r["entity_id"]) for r in rows],
                                 [("quarantined", [expected], entity)])

    def test_only_a_known_response_observation_with_a_pit_record_can_be_invalidated(self):
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            with self.assertRaises(emit.InvalidationRefused):
                invalidate(stores, "0" * 64)
            result = invalidate(stores, observation.observation_id)
            with self.assertRaises(emit.InvalidationRefused):               # an INVALIDATION document itself
                invalidate(stores, result.invalidation_observation_id, refs=("other",))

    def test_the_same_invalidation_is_idempotent(self):
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            first = invalidate(stores, observation.observation_id)
            rows = stores.invalidations.rows()
            again = invalidate(stores, observation.observation_id, clock=SequenceClock([]))
            self.assertEqual(again, first)
            self.assertEqual(stores.invalidations.rows(), rows)

    def test_a3_a_crash_at_every_invalidation_checkpoint_resumes_without_duplicates(self):
        names = []
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            invalidate(stores, observation.observation_id, checkpoint=names.append)
            baseline = (len(stores.invalidations.rows()), len(pit_rows(stores)), stores.evidence.verify_manifest())
        self.assertEqual(names, ["after_recorded", "after_invalidation_observation", "after_invalidation_pit"])
        for name in names:
            with self.subTest(name), scratch_root() as root:
                stores, entity, record, observation = one_capture(root)

                def hook(step, name=name):
                    if step == name:
                        raise Crash()

                with self.assertRaises(Crash):
                    invalidate(stores, observation.observation_id, checkpoint=hook)
                restarted = es.reopen(stores)
                result = invalidate(restarted, observation.observation_id,
                                    clock=SequenceClock([iso(T_INV, seconds=5), iso(T_INV, seconds=6),
                                                         iso(T_INV, seconds=7), iso(T_INV, seconds=8)]))
                self.assertEqual(result.head_effect, inv.EFFECT_EMITTED)
                self.assertEqual(result.t_inv, T_INV)                         # the recorded time stands
                self.assertEqual((len(restarted.invalidations.rows()), len(pit_rows(restarted)),
                                  restarted.evidence.verify_manifest()), baseline)
                inv.verify_invalidation_derivation(result.invalidation_observation_id, stores=restarted)
                self.assertEqual(admissible_head(entity, iso(T_INV, seconds=86400), stores=restarted).code,
                                 err.AdapterFailure.INVALIDATED)


class LedgerTests(unittest.TestCase):
    def row(self, **changes):
        base = inv.recorded_row(
            invalidated_observation_id="a" * 64, invalidated_artifact_hash="b" * 64,
            invalidated_pit_record_id="pit:" + "c" * 64, entity_id="book:" + "d" * 64, source_id="s",
            invalidation_class="OPERATOR", reason="OPERATOR_INVALIDATION", recorded_at=T_INV, actor="OPERATOR",
            evidence_refs=["x"])
        base.update(changes)
        return base

    def test_replay_rejects_every_malformed_history(self):
        good = self.row()
        inv.replay([good])
        applied = inv.applied_row(invalidation_id=good["invalidation_id"], head_effect=inv.EFFECT_SUPERSEDED,
                                  invalidation_observation_id=None, invalidation_pit_record_id=None, applied_at=T_INV)
        inv.replay([good, applied])
        bad = {
            "id does not match": [self.row(reason="PROVIDER_ERROR_NOTICE")],
            "unknown class": [inv.recorded_row(**{**{k: v for k, v in good.items() if k not in (
                "record_type", "schema_version", "invalidation_id")}, "invalidation_class": "WHIM"})],
            "unknown reason": [inv.recorded_row(**{**{k: v for k, v in good.items() if k not in (
                "record_type", "schema_version", "invalidation_id")}, "reason": "BECAUSE"})],
            "recorded twice": [good, good],
            "applied without recording": [applied],
            "applied twice": [good, applied, applied],
            "effect disagrees": [good, {**applied, "invalidation_observation_id": "e" * 64}],
            "applied before recorded": [good, {**applied, "applied_at": iso(T_INV, micros=-1)}],
            "extra key": [{**good, "surprise": 1}],
        }
        for label, rows in bad.items():
            with self.subTest(label), self.assertRaises(inv.InvalidationLedgerInvalid):
                inv.replay(rows)


if __name__ == "__main__":
    unittest.main()
