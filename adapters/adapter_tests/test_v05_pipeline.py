"""The full fixture pipeline: EV-03 for every document, the fixture join, tombstones through the runtime,
A-3 crash resume at every step, F-31, F-41 and PIT-09 (rebuild into empty stores)."""

from __future__ import annotations

import json
import unittest

from genesis.provenance import AvailabilityClass
from genesis.repro import canonical_json

from genesis_adapters import errors as err
from genesis_adapters.oddspapi import derivation, pipeline, scope
from genesis_adapters.oddspapi.acquisition import AttemptOutcome

from . import parser_support as ps
from .parser_support import FIXTURE_A, fixture_of, price_of
from .pipeline_support import (
    JSON, START, acquisition_rows, copy_config, coverage_rows, documents, fixture_body, fixtures_item, meta_item,
    odds_item, odds_response, open_rt, pit_rows, reopen, run_rows, summary,
)
from .support import Crash, FixedClock, ok, scratch_root, status


def full_run(root, **kw):
    rt = open_rt(root, script=[ok(fixture_body("tournaments.json"), headers=JSON),
                               ok(fixture_body("fixtures.json"), headers=JSON), odds_response()], **kw)
    meta = rt.acquire(meta_item())
    fixtures = rt.acquire(fixtures_item())
    odds = rt.acquire(odds_item())
    return rt, meta, fixtures, odds


class EndToEndTests(unittest.TestCase):
    def test_ev03_the_pipeline_produces_twelve_books_and_every_document_rederives_byte_for_byte(self):
        with scratch_root() as root:
            rt, meta, fixtures, odds = full_run(root)
            self.assertEqual((meta.outcome.failure, fixtures.outcome.failure, odds.outcome.failure), (None, None, None))
            self.assertIsNone(meta.emitted)
            self.assertEqual(len(odds.emitted.observation_ids), 12)
            self.assertEqual(len(odds.emitted.structured_hashes), 12)
            self.assertEqual(rt.verify_all(), 12)
            for observation_id in odds.emitted.observation_ids:
                rt.verify_derivation(observation_id)
            self.assertEqual(len(rt.runner.transport.calls), 3)
            self.assertEqual([r["guard_verdict"] for r in run_rows(rt)], ["PASS"])
            normalized = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_normalized"]
            self.assertEqual(len(normalized), 1)
            self.assertEqual(normalized[0]["identity_registry_head"], {"sequence": 0, "record_hash": "0" * 64})
            self.assertIsNotNone(normalized[0]["expected_scope_hash"])
            self.assertEqual(scope.load_scope(root, normalized[0]["expected_scope_hash"]), {})
            self.assertEqual(len(rt.stores.identity.rows()), 6)           # 2 fixtures + 4 participants
            available = [r for r in coverage_rows(rt) if r["status"] == "available"]
            self.assertEqual(len(available), 12)

    def test_the_raw_captures_are_all_retained_under_the_raw_contract(self):
        with scratch_root() as root:
            rt, meta, fixtures, odds = full_run(root)
            completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"]
            self.assertEqual(len(completed), 3)
            for row in completed:
                observation = rt.stores.evidence.get_observation(row["raw_observation_id"])
                self.assertEqual((observation.contract_id, observation.availability_class),
                                 ("oddspapi-v4-raw-response-v1", AvailabilityClass.PROSPECTIVE_CAPTURED))
                self.assertEqual(observation.retrieved_at, row["T1"])


class FixtureJoinTests(unittest.TestCase):
    def test_a_missing_start_is_joined_from_the_newest_earlier_fixtures_capture_and_verifies(self):
        with scratch_root() as root:
            payload = ps.odds_payload()
            for item in payload:
                del item["startTime"]
            rt = open_rt(root, script=[ok(fixture_body("fixtures.json"), headers=JSON), odds_response(payload)])
            fixtures = rt.acquire(fixtures_item())
            odds = rt.acquire(odds_item())
            join_id = fixtures.outcome.captured.raw_observation_id
            docs = documents(rt)
            self.assertEqual({d["market_state"] for d in docs}, {"OPEN"})
            self.assertEqual({d["fixture_join_observation_id"] for d in docs}, {join_id})
            self.assertEqual(rt.verify_all(), 12)

    def test_without_an_earlier_fixtures_capture_the_events_are_blocked_as_stale_metadata(self):
        with scratch_root() as root:
            payload = ps.odds_payload()
            del fixture_of(payload, FIXTURE_A)["startTime"]
            rt = open_rt(root, script=[odds_response(payload)])
            rt.acquire(odds_item())
            states = {(d["provider_fixture_id"]["value"], d["market_state"], tuple(d["state_reasons"]))
                      for d in documents(rt)}
            self.assertIn((FIXTURE_A, "BLOCKED", ("EVENT_METADATA_STALE",)), states)
            self.assertEqual(rt.verify_all(), 12)


class TombstoneTests(unittest.TestCase):
    def test_an_expected_book_missing_from_a_later_complete_response_becomes_absent_and_verifies(self):
        with scratch_root() as root:
            second = ps.odds_payload()
            del fixture_of(second, FIXTURE_A)["bookmakerOdds"]["fixture-book-a"]["markets"]["101"]
            rt = open_rt(root, script=[odds_response(), odds_response(second)])
            rt.acquire(odds_item("w1"))
            rt.clock.advance(seconds=600)
            later = rt.acquire(odds_item("w2"))
            absent = [d for d in documents(rt) if d["market_state"] == "ABSENT"]
            self.assertEqual(len(absent), 1)
            self.assertEqual((absent[0]["bookmaker_id"], absent[0]["market_family"]),
                             ("bk.fixture-book-a", "SOCCER_1X2_FT"))
            normalized = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_normalized"][-1]
            expected = scope.load_scope(root, normalized["expected_scope_hash"])
            self.assertEqual(len(expected), 12)                                  # every book of the first capture
            self.assertEqual(absent[0]["expected_scope_hash"], normalized["expected_scope_hash"])
            self.assertEqual(rt.verify_all(), 24)
            self.assertEqual(len(later.emitted.observation_ids), 12)             # 11 books + 1 tombstone

    def test_a_rejected_response_leaves_the_earlier_heads_untouched(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response(), ok(b'{"not": "a list"}', headers=JSON)])
            rt.acquire(odds_item("w1"))
            before = pit_rows(rt)
            rt.clock.advance(seconds=600)
            rejected = rt.acquire(odds_item("w2"))
            self.assertEqual(rejected.outcome.failure, err.AdapterFailure.ENVELOPE_SCHEMA_MISMATCH)
            self.assertIsNone(rejected.emitted)
            self.assertEqual(pit_rows(rt), before)


def one_fixture_payload():
    """Fixture A with two declared bookmakers: every kind of emission step, few enough books to crash at each."""

    payload = [item for item in ps.odds_payload() if item["fixtureId"] == FIXTURE_A]
    payload[0]["bookmakerOdds"] = {key: value for key, value in payload[0]["bookmakerOdds"].items()
                                   if key in ("pinnacle", "fixture-book-a")}
    return payload


class CrashResumeTests(unittest.TestCase):
    """A-3 through the runtime: crash after any durable step, restart, resume -> the same history."""

    @classmethod
    def setUpClass(cls):
        with scratch_root() as root:
            names = []
            rt = open_rt(root, script=[odds_response(one_fixture_payload())], checkpoint=names.append)
            rt.acquire(odds_item())
            cls.names = names
            cls.baseline = summary(rt)
            cls.documents = len(pit_rows(rt))

    def test_a3_a_crash_at_any_emission_step_resumes_to_the_same_derivation(self):
        self.assertIn("after_identity", self.names)
        self.assertEqual(self.documents, 4)
        for name in self.names:
            with self.subTest(crash_after=name), scratch_root() as root:
                def hook(step, name=name):
                    if step == name:
                        raise Crash()

                rt = open_rt(root, script=[odds_response(one_fixture_payload())], checkpoint=hook)
                with self.assertRaises(Crash):
                    rt.acquire(odds_item())
                restarted = reopen(rt)
                reconciled, results = restarted.resume()
                self.assertEqual(reconciled, ())
                self.assertEqual(len(results), 1)
                self.assertEqual(summary(restarted), self.baseline, name)
                self.assertEqual(restarted.verify_all(), self.documents, name)
                self.assertEqual(len(restarted.runner.transport.calls), 0)          # nothing re-sent
                again_reconciled, again = restarted.resume()                       # idempotent
                self.assertEqual(summary(restarted), self.baseline)

    def test_a3_a_crash_inside_the_acquisition_is_reconciled_and_never_resent(self):
        for name in ("before_quota", "after_quota", "after_quota_decided", "after_sent", "after_raw"):
            with self.subTest(crash_after=name), scratch_root() as root:
                def hook(step, name=name):
                    if step == name:
                        raise Crash()

                rt = open_rt(root, script=[odds_response()], runner_checkpoint=hook)
                with self.assertRaises(Crash):
                    rt.acquire(odds_item())
                restarted = reopen(rt, script=[odds_response()])
                reconciled, results = restarted.resume()
                self.assertEqual(len(reconciled), 1)
                self.assertEqual(results, ())
                self.assertEqual(pit_rows(restarted), [])
                row = [r for r in acquisition_rows(restarted) if r["record_type"] == "acq_reconciled"][0]
                expected_state = "MAY_HAVE_BEEN_SENT" if name in ("after_sent", "after_raw") else "NOT_SENT"
                self.assertEqual(row["send_state"], expected_state)
                # a fresh identity and debit, as a conformant retry (design 14.3, hostile audit HA-10): RETRY
                # purpose, a stated window, and only after the backoff from the reconciliation
                restarted.clock.advance(seconds=restarted.config.policy.retry_min_backoff_seconds)
                retry = restarted.acquire(odds_item(attempt=2, purpose="RETRY",
                                                    not_after=ps.iso_add(restarted.clock.peek(), seconds=3600)))
                self.assertIsNone(retry.outcome.failure)
                self.assertEqual(len(retry.emitted.observation_ids), 12)


class ConfigurationTests(unittest.TestCase):
    def test_f31_a_configuration_change_during_a_run_halts_durably(self):
        with scratch_root() as root:
            config_dir = copy_config(root)
            rt = open_rt(root / "runtime", script=[odds_response(), odds_response()], config_dir=config_dir)
            rt.acquire(odds_item("w1"))
            policy_path = config_dir / "oddspapi_slice1_policy.json"
            original = policy_path.read_bytes()
            body = json.loads(original)
            body["price_ttl_seconds"] += 1
            policy_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaises(pipeline.PipelineHalt) as caught:
                rt.acquire(odds_item("w2"))
            self.assertEqual(caught.exception.code, err.AdapterFailure.CONFIG_DIGEST_MISMATCH)
            self.assertEqual([r["reason"] for r in acquisition_rows(rt) if r["record_type"] == "acq_halted"],
                             ["CONFIG_DIGEST_MISMATCH"])
            entry = coverage_rows(rt)[-1]
            self.assertEqual((entry["status"], entry["reason_codes"], entry["note"]),
                             ("not_attempted", ["configuration_mismatch"], "CONFIG_DIGEST_MISMATCH"))
            self.assertEqual(len(rt.runner.transport.calls), 1)
            policy_path.write_bytes(original)                                     # restoring does not un-halt
            again = rt.acquire(odds_item("w3"))
            self.assertEqual((again.outcome.outcome, again.outcome.failure),
                             (AttemptOutcome.REFUSED, err.AdapterFailure.CIRCUIT_OPEN))

    def test_f41_a_failing_provenance_guard_refuses_to_start_and_records_why(self):
        from genesis_adapters.provenance_guard import ModuleProvenanceError

        def failing():
            raise ModuleProvenanceError("SHADOWED_PACKAGE", "a competing genesis package is importable")

        with scratch_root() as root:
            with self.assertRaises(pipeline.PipelineHalt) as caught:
                open_rt(root, provenance_check=failing)
            self.assertEqual(caught.exception.code, err.AdapterFailure.MODULE_PROVENANCE)
            refused = [r for r in pipeline_runs(root)]
            self.assertEqual([(r["record_type"], r["reason"], r["guard_verdict"]) for r in refused],
                             [("run_refused", "MODULE_PROVENANCE", "ModuleProvenanceError")])
            entry = coverage_rows_at(root)[-1]
            self.assertEqual((entry["status"], entry["reason_codes"], entry["note"]),
                             ("not_attempted", ["configuration_mismatch"], "MODULE_PROVENANCE"))
            self.assertFalse((root / "acquisition.jsonl").exists())
            self.assertFalse((root / "evidence").exists())


def pipeline_runs(root):
    from genesis.registry import AppendOnlyJsonl
    return AppendOnlyJsonl(root / "runs.jsonl").records()


def coverage_rows_at(root):
    from .support import read_jsonl
    return read_jsonl(root / "coverage.jsonl")


class RebuildTests(unittest.TestCase):
    def test_pit09_rebuilding_into_empty_stores_gives_identical_artifacts_and_record_ids(self):
        with scratch_root() as root:
            second = ps.odds_payload()
            del fixture_of(second, FIXTURE_A)["bookmakerOdds"]["fixture-book-a"]["markets"]["101"]
            price_of(second, "pinnacle", "1010", "2001", FIXTURE_A)["price"] = 1.9
            no_start = ps.odds_payload()
            for item in no_start:
                del item["startTime"]
            rt = open_rt(root / "source", script=[ok(fixture_body("fixtures.json"), headers=JSON), odds_response(),
                                                  odds_response(second), odds_response(no_start)])
            rt.acquire(fixtures_item())
            for window in ("w1", "w2", "w3"):
                rt.acquire(odds_item(window))
                rt.clock.advance(seconds=600)
            target = pipeline.build_stores(root / "target", derivation_version=rt.config.derivation_version,
                                           policy=rt.config.policy, licensing_note=pipeline.FIXTURE_LICENSING_NOTE)
            rebuilt = pipeline.rebuild_into(rt, target, clock=FixedClock("2026-12-01T00:00:00.000000Z", step_micros=10))
            self.assertEqual(len(rebuilt), 3)
            key = lambda row: (row["entity_id"], row["available_at"], row["payload_hash"], row["record_id"])
            source_rows = sorted(key(r) for r in rt.stores.pit.log.records() if r.get("record_type") == "pit_record")
            target_rows = sorted(key(r) for r in target.pit.log.records() if r.get("record_type") == "pit_record")
            self.assertEqual(source_rows, target_rows)
            self.assertEqual(target.identity.head(), rt.stores.identity.head())
            self.assertTrue(all(r["ready_at"] >= "2026-12-01" for r in target.pit.log.records()
                                if r.get("record_type") == "pit_record"))               # new T3, same artifacts


class DerivationFailureTests(unittest.TestCase):
    def one_run(self, root):
        rt = open_rt(root, script=[odds_response(), odds_response(self.second())])
        rt.acquire(odds_item("w1"))
        rt.clock.advance(seconds=600)
        rt.acquire(odds_item("w2"))
        return rt

    @staticmethod
    def second():
        payload = ps.odds_payload()
        del fixture_of(payload, FIXTURE_A)["bookmakerOdds"]["fixture-book-a"]["markets"]["101"]
        return payload

    def observation_of_state(self, rt, state):
        for row in pit_rows(rt):
            document = json.loads(rt.stores.evidence.get_bytes(row["payload_hash"]))
            if document["market_state"] == state:
                return rt.stores.evidence.get_observations(row["payload_hash"])[0].observation_id
        raise AssertionError(state)

    def test_a_tampered_scope_artifact_fails_verification_of_the_documents_that_pin_it(self):
        with scratch_root() as root:
            rt = self.one_run(root)
            absent = self.observation_of_state(rt, "ABSENT")
            normalized = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_normalized"][-1]
            path = root / "scopes" / f"{normalized['expected_scope_hash']}.json"
            path.write_bytes(path.read_bytes().replace(b"FT_REGULAR", b"FT_REGULAX", 1))
            with self.assertRaises(scope.ScopeError):
                rt.verify_derivation(absent)

    def test_a_different_running_configuration_cannot_reproduce_old_documents(self):
        with scratch_root() as root:
            rt = self.one_run(root / "runtime")
            config_dir = copy_config(root)
            body = json.loads((config_dir / "oddspapi_slice1_policy.json").read_text(encoding="utf-8"))
            body["prematch_guard_seconds"] += 1
            (config_dir / "oddspapi_slice1_policy.json").write_text(json.dumps(body, indent=2, sort_keys=True) + "\n",
                                                                    encoding="utf-8")
            other = reopen(rt, config_dir=config_dir)
            self.assertNotEqual(other.config.derivation_version, rt.config.derivation_version)
            with self.assertRaisesRegex(derivation.DerivationError, "does not reproduce this derivation version"):
                derivation.verify_derivation(self.observation_of_state(rt, "OPEN"), stores=rt.stores,
                                             config=other.config, maps=other.maps)

    def test_an_unknown_derivation_kind_and_a_foreign_contract_are_failures(self):
        with scratch_root() as root:
            rt = self.one_run(root)
            observation = rt.stores.evidence.get_observation(self.observation_of_state(rt, "OPEN"))
            document = json.loads(rt.stores.evidence.get_bytes(observation.artifact_hash))
            document["derivation_kind"] = "GUESSWORK"
            forged = rt.stores.evidence.publish(
                canonical_json(document), contract_id=observation.contract_id,
                source_uri=observation.source_uri + ":forged", provider=observation.provider,
                source_type=observation.source_type, retrieved_at=observation.retrieved_at,
                parse_ready_at=observation.parse_ready_at, first_seen_at=observation.first_seen_at,
                parser_version=observation.parser_version, content_type=observation.content_type,
                licensing_note=observation.licensing_note, availability_class=observation.availability_class,
                upstream_version=observation.upstream_version, valid_from=observation.valid_from,
                valid_to=observation.valid_to)
            with self.assertRaises(derivation.DerivationError):
                rt.verify_derivation(forged.observation_id)
            raw_id = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"][0]["raw_observation_id"]
            with self.assertRaises(Exception):
                rt.verify_derivation(raw_id)

    def republish(self, rt, observation, data, *, uri_suffix=""):
        """``data`` as a new observation with EXACTLY the original's metadata (except an optional uri suffix)."""

        return rt.stores.evidence.publish(
            data, contract_id=observation.contract_id, source_uri=observation.source_uri + uri_suffix,
            provider=observation.provider, source_type=observation.source_type,
            retrieved_at=observation.retrieved_at, parse_ready_at=observation.parse_ready_at,
            first_seen_at=observation.first_seen_at, publisher_timestamp=observation.publisher_timestamp,
            parser_version=observation.parser_version, content_type=observation.content_type,
            licensing_note=observation.licensing_note, availability_class=observation.availability_class,
            upstream_version=observation.upstream_version, valid_from=observation.valid_from,
            valid_to=observation.valid_to).observation_id

    def forged(self, rt, **changes):
        observation = rt.stores.evidence.get_observation(self.observation_of_state(rt, "OPEN"))
        document = json.loads(rt.stores.evidence.get_bytes(observation.artifact_hash))
        document.update(changes)
        return self.republish(rt, observation, canonical_json(document))

    def test_a_document_whose_bytes_do_not_rederive_fails(self):
        with scratch_root() as root:
            rt = self.one_run(root)
            observation = rt.stores.evidence.get_observation(self.observation_of_state(rt, "OPEN"))
            document = json.loads(rt.stores.evidence.get_bytes(observation.artifact_hash))
            document["selections"]["OVER" if "OVER" in document["selections"] else "HOME"]["odds_decimal"] = "9.99"
            forged = self.republish(rt, observation, canonical_json(document))     # every metadata field matches
            with self.assertRaisesRegex(derivation.DerivationError, "differs from the stored bytes"):
                rt.verify_derivation(forged)
            with self.assertRaises(derivation.DerivationError):
                rt.verify_all()                                                   # 100% or nothing

    def test_the_same_bytes_under_other_metadata_fail(self):
        with scratch_root() as root:
            rt = self.one_run(root)
            observation = rt.stores.evidence.get_observation(self.observation_of_state(rt, "OPEN"))
            copy = self.republish(rt, observation, rt.stores.evidence.get_bytes(observation.artifact_hash),
                                  uri_suffix=":copy")
            with self.assertRaisesRegex(derivation.DerivationError, "observation metadata"):
                rt.verify_derivation(copy)

    def test_a_document_pinning_another_registry_prefix_fails_at_the_prefix_check(self):
        with scratch_root() as root:
            rt = self.one_run(root)
            head = rt.stores.identity.head()
            for label, pinned, message in (
                    ("unknown hash", {"sequence": head["sequence"], "record_hash": "1" * 64}, "not a prefix"),
                    ("beyond the registry", {"sequence": head["sequence"] + 5, "record_hash": "1" * 64}, "beyond")):
                with self.subTest(label):
                    with self.assertRaisesRegex(derivation.DerivationError, message):
                        rt.verify_derivation(self.forged(rt, identity_registry_head=pinned))

    def test_a_document_that_does_not_belong_to_its_acquisition_fails(self):
        with scratch_root() as root:
            rt = self.one_run(root)
            with self.assertRaisesRegex(derivation.DerivationError, "does not belong to its acquisition"):
                rt.verify_derivation(self.forged(rt, provider_request_hash="f" * 64))

    def test_the_fixture_join_never_selects_a_capture_received_after_the_response(self):
        with scratch_root() as root:
            later_fixtures = json.loads(fixture_body("fixtures.json"))
            for item in later_fixtures:
                item["startTime"] = "2026-10-09T09:00:00.000Z"
            rt = open_rt(root, script=[ok(fixture_body("fixtures.json"), headers=JSON), odds_response(),
                                       ok(json.dumps(later_fixtures).encode(), headers=JSON)])
            first = rt.acquire(fixtures_item("wf1"))
            odds = rt.acquire(odds_item())
            ttl = rt.config.policy.cache_ttl_seconds["FIXTURES"]
            rt.clock.advance(seconds=ttl + 1)                          # past the cache: a genuinely new capture
            second = rt.acquire(fixtures_item("wf2"))
            self.assertEqual(second.outcome.outcome, "RESPONSE")
            t1 = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"
                  and r["acquisition_id"] == odds.outcome.acquisition_id][0]["T1"]
            snapshot = derivation.fixture_snapshot_for(rt.stores, rt.config, rt.maps, at=t1)
            self.assertEqual(snapshot.observation_id, first.outcome.captured.raw_observation_id)
            later = derivation.fixture_snapshot_for(rt.stores, rt.config, rt.maps, at=ps.iso_add(t1, seconds=ttl + 3600))
            self.assertEqual(later.observation_id, second.outcome.captured.raw_observation_id)

    def test_a_rebuild_into_stores_whose_registry_diverged_is_refused(self):
        with scratch_root() as root:
            rt = open_rt(root / "source", script=[odds_response(), odds_response()])
            rt.acquire(odds_item("w1"))
            rt.clock.advance(seconds=600)
            rt.acquire(odds_item("w2"))
            target = pipeline.build_stores(root / "target", derivation_version=rt.config.derivation_version,
                                           policy=rt.config.policy, licensing_note=pipeline.FIXTURE_LICENSING_NOTE)
            stray = {key: value for key, value in rt.stores.identity.rows()[1].items()
                     if key not in ("previous_hash", "sequence", "record_hash")}
            self.assertEqual(stray["record_type"], "participant_seen")
            target.identity.apply([stray])                       # the target registry no longer starts empty
            with self.assertRaisesRegex(derivation.DerivationError, "diverged from the pinned head"):
                pipeline.rebuild_into(rt, target, clock=FixedClock("2026-12-01T00:00:00.000000Z", step_micros=10))


if __name__ == "__main__":
    unittest.main()
