"""EV-01, EV-02, EV-07, F-06, F-12, F-13, F-14, F-38 (response level), CLK-04, F-32 (raw publish),
the F-44 gap and A-3 at the raw boundary."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from genesis.provenance import AvailabilityClass
from genesis.repro import ImmutableConflict, immutable_write

from genesis_adapters import config as cfg
from genesis_adapters import errors as err
from genesis_adapters.oddspapi import endpoints as ep

from . import support as sup
from .support import (
    Crash, FakeTransport, FixedClock, build_rig, http_date, meta_item, odds_item, ok, read_jsonl, scratch_root, status, truncated,
)

BASE = "2026-10-01T12:00:00.000000Z"
UTC = timezone.utc
JSON = (("content-type", "application/json"),)
GOOD_TOURNAMENTS = (b'[{"tournamentId":17,"tournamentName":"Premier League","categoryName":"England",'
                    b'"tournamentSlug":"premier-league","categorySlug":"england","futureFixtures":0,'
                    b'"upcomingFixtures":0,"liveFixtures":0}]')


def rows_of(rig, record_type):
    return [r for r in read_jsonl(rig.acq_path) if r["record_type"] == record_type]


def coverage(rig):
    return read_jsonl(rig.coverage_path)


def cov_tuple(rig):
    entry = coverage(rig)[-1]
    return entry["status"], entry["reason_codes"], entry["note"]


def small_policy(**over):
    body = json.loads((sup.CONFIG / "oddspapi_slice1_policy.json").read_text())
    body.update(over)
    return cfg.parse_policy(body)


class RawEvidenceTests(unittest.TestCase):
    def test_ev01_raw_bytes_are_stored_byte_exact_under_the_raw_contract(self):
        body = b"[ \n]\n"
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(body, headers=JSON)])
            item = odds_item()
            outcome = rig.runner.acquire(item)
            self.assertIsNone(outcome.failure)
            done = rows_of(rig, "acq_completed")[0]
            obs = rig.evidence.get_observation(done["raw_observation_id"])
            self.assertEqual(rig.evidence.get_bytes(obs.artifact_hash), body)
            self.assertEqual(obs.artifact_hash, hashlib.sha256(body).hexdigest())
            self.assertEqual(len(obs.artifact_hash), 64)
            self.assertEqual(obs.byte_length, len(body))
            self.assertEqual(obs.contract_id, ep.RAW_CONTRACT_ID)
            self.assertEqual(obs.source_uri, item.request.source_uri)
            self.assertEqual((obs.provider, obs.source_type, obs.parser_version),
                             ("oddspapi", "oddspapi_v4_rest_response", "raw-capture-v1"))
            self.assertEqual(obs.content_type, "application/json")
            self.assertEqual(obs.availability_class, AvailabilityClass.PROSPECTIVE_CAPTURED)
            self.assertEqual((obs.retrieved_at, obs.first_seen_at, obs.parse_ready_at),
                             (done["T1"],) * 3)
            self.assertEqual(obs.upstream_version, "v4")
            self.assertIsNone(obs.publisher_timestamp)
            self.assertEqual(obs.licensing_note, "FIXTURE-ONLY-NO-PROVIDER-TERMS")
            self.assertEqual(done["byte_length"], len(body))
            self.assertIn(["content-type", "application/json"], done["headers"])
            self.assertEqual(rig.evidence.verify_manifest(), 1)

    def test_ev01_identical_bytes_received_twice_are_two_observations_of_one_object(self):
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(b"[]", headers=JSON), ok(b"[]", headers=JSON)])
            rig.runner.acquire(odds_item(window="w1"))
            rig.runner.acquire(odds_item(window="w2"))
            first, second = (r["raw_observation_id"] for r in rows_of(rig, "acq_completed"))
            self.assertNotEqual(first, second)
            a, b = rig.evidence.get_observation(first), rig.evidence.get_observation(second)
            self.assertEqual(a.artifact_hash, b.artifact_hash)
            self.assertEqual(len(rig.evidence.get_observations(a.artifact_hash)), 2)
            self.assertLess(a.retrieved_at, b.retrieved_at)

    def test_ev02_tampering_is_detected_and_conflicting_republication_is_refused(self):
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(b"[]", headers=JSON)])
            rig.runner.acquire(odds_item())
            done = rows_of(rig, "acq_completed")[0]
            obs = rig.evidence.get_observation(done["raw_observation_id"])
            digest = obs.artifact_hash
            path = root / "evidence" / "objects" / digest[:2] / digest
            with self.assertRaises(ImmutableConflict):
                immutable_write(path, b"[1]")
            path.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                rig.evidence.get_bytes(digest)
            with self.assertRaises(ValueError):
                rig.evidence.verify_manifest()

    def test_evidence_manifest_only_lists_stored_responses(self):
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[status(503, b"oops"), ok(b"[]", headers=JSON)])
            rig.runner.acquire(odds_item(window="w1"))
            rig.runner.acquire(odds_item(window="w2"))
            self.assertEqual(rig.evidence.verify_manifest(), 2)         # error bodies are retained too


class ContentValidationTests(unittest.TestCase):
    def run_case(self, scripted, *, item=None, policy=None, role_item=None):
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[scripted], policy=policy)
            outcome = rig.runner.acquire(role_item or item or odds_item())
            done = rows_of(rig, "acq_completed")[0]
            return rig, outcome, done, cov_tuple(rig), self._copy(rig, done)

    def _copy(self, rig, done):
        if done["raw_observation_id"] is None:
            return None
        obs = rig.evidence.get_observation(done["raw_observation_id"])
        return rig.evidence.get_bytes(obs.artifact_hash)

    def test_ev07_and_f13_malformed_payloads_keep_raw_and_reject_coverage(self):
        cases = [
            ("NOT_JSON", b'{"a":'), ("NOT_JSON", b""), ("NOT_JSON", b"[1] [2]"),
            ("DUPLICATE_KEYS", b'[{"a":1,"a":2}]'), ("NONFINITE_NUMBER", b"[NaN]"),
            ("NONFINITE_NUMBER", b"[Infinity]"), ("INVALID_UTF8", b"[\xff]"),
        ]
        for code, body in cases:
            with self.subTest(code=code, body=body):
                with scratch_root() as root:
                    rig = build_rig(root, capture=True, script=[ok(body, headers=JSON)])
                    outcome = rig.runner.acquire(odds_item())
                    done = rows_of(rig, "acq_completed")[0]
                    self.assertEqual(outcome.failure, err.AdapterFailure(code))
                    obs = rig.evidence.get_observation(done["raw_observation_id"])
                    self.assertEqual(rig.evidence.get_bytes(obs.artifact_hash), body)
                    self.assertEqual(cov_tuple(rig), ("rejected", ["schema_rejected"], code))
                    self.assertEqual(rig.evidence.verify_manifest(), 1)

    def test_ev07_wrong_or_missing_content_type(self):
        for headers in ((("content-type", "text/html"),), (("content-type", "application/jsonx"),), ()):
            with self.subTest(headers=headers), scratch_root() as root:
                rig = build_rig(root, capture=True, script=[ok(b"[]", headers=headers)])
                outcome = rig.runner.acquire(odds_item())
                self.assertEqual(outcome.failure, err.AdapterFailure.WRONG_CONTENT_TYPE)
                self.assertEqual(cov_tuple(rig), ("rejected", ["schema_rejected"], "WRONG_CONTENT_TYPE"))
                self.assertIsNotNone(rows_of(rig, "acq_completed")[0]["raw_observation_id"])
        with scratch_root() as root:                                            # charset parameter is fine
            rig = build_rig(root, capture=True,
                            script=[ok(b"[]", headers=(("content-type", "application/json; charset=utf-8"),))])
            self.assertIsNone(rig.runner.acquire(odds_item()).failure)

    def test_ev07_oversize_is_retained_truncated_at_the_cap(self):
        policy = small_policy(max_response_bytes=64)
        body = b"[" + b" " * 100 + b"]"
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(body, headers=JSON)], policy=policy)
            outcome = rig.runner.acquire(odds_item())
            self.assertEqual(outcome.failure, err.AdapterFailure.OVERSIZE_BODY)
            done = rows_of(rig, "acq_completed")[0]
            obs = rig.evidence.get_observation(done["raw_observation_id"])
            self.assertEqual(rig.evidence.get_bytes(obs.artifact_hash), body[:64])
            self.assertEqual(done["byte_length"], 64)
            self.assertEqual(cov_tuple(rig), ("rejected", ["schema_rejected"], "OVERSIZE_BODY"))

    def test_f06_truncated_partial_bytes_are_stored_as_raw(self):
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[truncated(b'[{"fixtureId"', headers=JSON)])
            outcome = rig.runner.acquire(odds_item())
            self.assertEqual((outcome.outcome, outcome.failure),
                             ("TRUNCATED", err.AdapterFailure.TRUNCATED_BODY))
            done = rows_of(rig, "acq_completed")[0]
            obs = rig.evidence.get_observation(done["raw_observation_id"])
            self.assertEqual(rig.evidence.get_bytes(obs.artifact_hash), b'[{"fixtureId"')
            self.assertEqual(cov_tuple(rig), ("rejected", ["schema_rejected"], "TRUNCATED_BODY"))
            self.assertEqual(len(coverage(rig)), 1)

    def test_f14_envelope_mismatch_rejects_the_whole_response(self):
        cases = [b'{"not":"a list"}', b"[5]", b'[{"fixtureId":5}]', b'[{"participant1Id":1}]', b'"text"']
        for body in cases:
            with self.subTest(body=body), scratch_root() as root:
                rig = build_rig(root, capture=True, script=[ok(body, headers=JSON)])
                outcome = rig.runner.acquire(odds_item())
                self.assertEqual(outcome.failure, err.AdapterFailure.ENVELOPE_SCHEMA_MISMATCH)
                self.assertEqual(cov_tuple(rig), ("rejected", ["schema_rejected"], "ENVELOPE_SCHEMA_MISMATCH"))
                self.assertIsNotNone(rows_of(rig, "acq_completed")[0]["raw_observation_id"])

    def test_f14_event_level_problems_are_not_an_envelope_failure(self):
        body = b'[{"fixtureId":"id1","sportId":10}]'                    # required event keys missing
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(body, headers=JSON)])
            outcome = rig.runner.acquire(odds_item())
            self.assertIsNone(outcome.failure)                          # per-scope handling is S4's job
            self.assertEqual(outcome.parsed, json.loads(body, parse_float=__import__("decimal").Decimal))

    def test_f38_response_level_drift_in_a_closed_envelope_rejects_the_response(self):
        body = GOOD_TOURNAMENTS.replace(b'"liveFixtures":0', b'"liveFixtures":0,"extra":1')
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(body, headers=JSON)])
            outcome = rig.runner.acquire(meta_item())
            self.assertEqual(outcome.failure, err.AdapterFailure.SCHEMA_DRIFT)
            self.assertEqual(cov_tuple(rig), ("rejected", ["schema_rejected"], "SCHEMA_DRIFT"))
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(GOOD_TOURNAMENTS, headers=JSON)])
            self.assertIsNone(rig.runner.acquire(meta_item()).failure)

    def test_error_responses_keep_their_raw_body(self):
        for code, failure in ((302, err.AdapterFailure.REDIRECT_REFUSED), (401, err.AdapterFailure.AUTH_REJECTED),
                              (429, err.AdapterFailure.RATE_LIMITED), (500, err.AdapterFailure.PROVIDER_ERROR)):
            with self.subTest(code), scratch_root() as root:
                rig = build_rig(root, capture=True, script=[status(code, b"<html>nope</html>",
                                                                   headers=(("content-type", "text/html"),))])
                outcome = rig.runner.acquire(odds_item())
                self.assertEqual(outcome.failure, failure)
                done = rows_of(rig, "acq_completed")[0]
                obs = rig.evidence.get_observation(done["raw_observation_id"])
                self.assertEqual(rig.evidence.get_bytes(obs.artifact_hash), b"<html>nope</html>")
                self.assertEqual(obs.content_type, "text/html")
                self.assertEqual(len(coverage(rig)), 1)                  # the HTTP failure row only

    def test_a_successful_response_returns_the_strictly_decoded_payload_in_memory_only(self):
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(b"[]", headers=JSON)])
            outcome = rig.runner.acquire(odds_item())
            self.assertEqual(outcome.parsed, [])
            self.assertEqual(coverage(rig), [])


class ClockSkewTests(unittest.TestCase):
    def rig(self, root, delta_seconds: int | None, *, require_date: bool = False, raw_date=None):
        skew = cfg.load_policy(sup.CONFIG / "oddspapi_slice1_policy.json").clock_skew_max_seconds

        def step(clock):
            t1 = datetime.fromisoformat(clock.peek()[:-1] + "+00:00") + timedelta(seconds=1)
            headers = list(JSON)
            if raw_date is not None:
                headers.append(("date", raw_date))
            elif delta_seconds is not None:
                headers.append(("date", http_date((t1 + timedelta(seconds=delta_seconds)).isoformat(
                    timespec="microseconds").replace("+00:00", "Z"))))
            return ok(b"[]", headers=tuple(headers), latency=1.0)

        clock = FixedClock(BASE, step_micros=0)
        return build_rig(root, capture=True, script=[step], clock=clock, require_date=require_date), skew

    def test_clk04_the_skew_boundary_is_exact_in_both_directions(self):
        skew = cfg.load_policy(sup.CONFIG / "oddspapi_slice1_policy.json").clock_skew_max_seconds
        for delta, accepted in ((skew, True), (-skew, True), (skew + 1, False), (-(skew + 1), False), (0, True)):
            with self.subTest(delta=delta), scratch_root() as root:
                rig, _ = self.rig(root, delta)
                outcome = rig.runner.acquire(odds_item())
                if accepted:
                    self.assertIsNone(outcome.failure, delta)
                else:
                    self.assertEqual(outcome.failure, err.AdapterFailure.CLOCK_SKEW, delta)

    def test_f12_skew_quarantines_the_response_keeps_raw_and_suspends_sends_until_the_next_utc_day(self):
        skew = cfg.load_policy(sup.CONFIG / "oddspapi_slice1_policy.json").clock_skew_max_seconds
        with scratch_root() as root:
            rig, _ = self.rig(root, skew + 1)
            outcome = rig.runner.acquire(odds_item())
            self.assertEqual(outcome.failure, err.AdapterFailure.CLOCK_SKEW)
            done = rows_of(rig, "acq_completed")[0]
            self.assertIsNotNone(done["raw_observation_id"])                     # raw retained
            self.assertEqual(cov_tuple(rig), ("quarantined", ["critical_uncertainty"], "CLOCK_SKEW"))
            self.assertEqual(len(rows_of(rig, "acq_quarantined")), 1)
            suspended = rows_of(rig, "acq_sends_suspended")
            self.assertEqual([(r["reason"], r["until"]) for r in suspended],
                             [("CLOCK_SKEW", "2026-10-02T00:00:00.000000Z")])
            again = rig.runner.acquire(odds_item(window="w2"))
            self.assertEqual(again.failure, err.AdapterFailure.CIRCUIT_OPEN)
            self.assertEqual(again.detail, "CLOCK_SKEW")
            self.assertEqual(len(rig.transport.calls), 1)
            quarantine = read_jsonl(root / "quarantine.jsonl")
            self.assertEqual([q["reason"] for q in quarantine], ["CLOCK_SKEW"])
            self.assertEqual(quarantine[0]["detection_classes"], [])

    def test_clk04_missing_or_unparseable_date_quarantines_only_in_live_capture_mode(self):
        for kwargs in (dict(delta_seconds=None), dict(delta_seconds=None, raw_date="not a date"),
                       dict(delta_seconds=None, raw_date="Thu, 01 Oct 2026 12:00:01")):
            with self.subTest(kwargs), scratch_root() as root:
                rig, _ = self.rig(root, require_date=True, **kwargs)
                self.assertEqual(rig.runner.acquire(odds_item()).failure, err.AdapterFailure.CLOCK_SKEW)
            with scratch_root() as root:
                rig, _ = self.rig(root, require_date=False, **kwargs)
                outcome = rig.runner.acquire(odds_item())
                if kwargs.get("raw_date") == "not a date":
                    self.assertEqual(outcome.failure, err.AdapterFailure.CLOCK_SKEW)   # present but unusable
                elif kwargs.get("raw_date"):                                          # naive/GMT-less date
                    self.assertEqual(outcome.failure, err.AdapterFailure.CLOCK_SKEW)
                else:
                    self.assertIsNone(outcome.failure)


class RawPublicationFailureTests(unittest.TestCase):
    """A valid response whose immutable raw publication fails (F-32), the F-44 gap and A-3."""

    def later(self, rig, root, **kwargs):
        """A restarted runner over the same durable state, five minutes later."""

        return build_rig(root, capture=True, quota_ledger=rig.quota_ledger, cache=rig.cache,
                         clock=FixedClock("2026-10-01T12:05:00.000000Z", step_micros=1000), **kwargs)

    def test_f32_a_publication_conflict_halts_quarantines_and_never_rewrites_existing_bytes(self):
        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(b"[]", headers=JSON), ok(b"[]", headers=JSON)])
            rig.runner.acquire(odds_item(window="w1"))
            first = rows_of(rig, "acq_completed")[0]
            digest = rig.evidence.get_observation(first["raw_observation_id"]).artifact_hash
            path = root / "evidence" / "objects" / digest[:2] / digest
            path.write_bytes(b"tampered")                 # the stored object no longer matches its address
            with self.assertRaises(err.AcquisitionHalt) as caught:
                rig.runner.acquire(odds_item(window="w2"))
            self.assertEqual(caught.exception.code, err.AdapterFailure.EVIDENCE_CONFLICT)
            self.assertEqual(path.read_bytes(), b"tampered")   # existing bytes are left exactly as found
            second = rows_of(rig, "acq_completed")[1]
            self.assertEqual((second["failure"], second["raw_observation_id"], second["byte_length"]),
                             ("EVIDENCE_CONFLICT", None, None))
            self.assertEqual(cov_tuple(rig), ("quarantined", ["artifact_tampered"], "EVIDENCE_CONFLICT"))
            self.assertEqual(rows_of(rig, "acq_halted")[-1]["reason"], "EVIDENCE_CONFLICT")
            again = rig.runner.acquire(odds_item(window="w3"))     # the halt is durable: nothing is sent
            self.assertEqual((again.outcome, again.failure), ("REFUSED", err.AdapterFailure.CIRCUIT_OPEN))
            self.assertEqual(len(rig.transport.calls), 2)

    def test_f44_gap_a_plain_io_failure_while_publishing_is_a_crash_and_never_a_verdict(self):
        """c8dfafd has no distinct row for a non-conflict I/O failure during raw publication.

        Current behaviour (documented in adapters/evidence/S7/SUMMARY.md): the failure propagates out of
        ``acquire`` (nothing is swallowed and no taxonomy code is invented), the durable state is exactly
        ``planned, quota_decided, sent`` with the Genesis debit standing, and the next start reconciles the
        attempt as an ORPHANED_RESERVATION (F-35) that is never re-sent.
        """

        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(b"[]", headers=JSON)])
            item = odds_item()

            def failing(*args, **kwargs):
                raise OSError(28, "No space left on device")

            rig.evidence.publish = failing
            with self.assertRaises(OSError):
                rig.runner.acquire(item)
            self.assertEqual([r["record_type"] for r in read_jsonl(rig.acq_path)],
                             ["acq_planned", "acq_quota_decided", "acq_sent"])
            debits = [r for r in read_jsonl(root / "quota" / "ledger.jsonl")
                      if r["record_type"] == "quota_billable_call"]
            self.assertEqual(len(debits), 1)
            fresh = self.later(rig, root, script=[])
            self.assertEqual(fresh.evidence.verify_manifest(), 0)          # nothing was published
            fresh.runner.reconcile_after_restart()
            row = rows_of(fresh, "acq_reconciled")[0]
            self.assertEqual((row["outcome"], row["send_state"]), ("ORPHANED_RESERVATION", "MAY_HAVE_BEEN_SENT"))
            self.assertEqual(cov_tuple(fresh), ("missing", ["missing_evidence"], "ORPHANED_RESERVATION"))
            again = fresh.runner.acquire(item)
            self.assertEqual((again.outcome, again.failure), ("REFUSED", err.AdapterFailure.ORPHANED_RESERVATION))
            self.assertEqual(fresh.transport.calls, [])

    def test_a3_a_crash_after_the_raw_publication_keeps_one_object_and_never_duplicates_history(self):
        def hook(name):
            if name == "after_raw":
                raise Crash()

        with scratch_root() as root:
            rig = build_rig(root, capture=True, script=[ok(b"[]", headers=JSON)], checkpoint=hook)
            with self.assertRaises(Crash):
                rig.runner.acquire(odds_item())
            self.assertEqual(rig.evidence.verify_manifest(), 1)               # the raw object is durable
            self.assertEqual([r["record_type"] for r in read_jsonl(rig.acq_path)],
                             ["acq_planned", "acq_quota_decided", "acq_sent"])
            fresh = self.later(rig, root, script=[ok(b"[]", headers=JSON)])
            fresh.runner.reconcile_after_restart()
            row = rows_of(fresh, "acq_reconciled")[0]
            self.assertEqual((row["outcome"], row["send_state"]), ("ORPHANED_RESERVATION", "MAY_HAVE_BEEN_SENT"))
            self.assertEqual(fresh.evidence.verify_manifest(), 1)             # nothing re-published
            self.assertEqual(fresh.runner.reconcile_after_restart(), ())     # idempotent
            self.assertEqual(fresh.transport.calls, [])
            retry = odds_item(attempt=2, purpose="RETRY",                     # a fresh identity and debit
                              not_after="2026-10-01T23:00:00.000000Z")         # a stated window (14.3, HA-10)
            fresh.clock.advance(seconds=fresh.policy.retry_min_backoff_seconds)
            self.assertIsNone(fresh.runner.acquire(retry).failure)
            self.assertEqual(fresh.evidence.verify_manifest(), 2)             # a separate capture, not a duplicate
            observations = [fresh.evidence.get_observation(r["raw_observation_id"])
                            for r in rows_of(fresh, "acq_completed")]
            self.assertEqual(len(observations), 1)
            self.assertEqual(len(fresh.evidence.get_observations(observations[0].artifact_hash)), 2)


if __name__ == "__main__":
    unittest.main()
