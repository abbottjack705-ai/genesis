"""FM-00 .. FM-43 (design 15): for every failure row, through the real runtime, assert the evidence retained, the
coverage status / frozen reason / adapter note, and the effect on the observation head."""

from __future__ import annotations

import dataclasses
import gzip
import json
import unittest

from genesis.pit import BitemporalRecord

from genesis_adapters import errors as err
from genesis_adapters.clock import SystemUtcClock
from genesis_adapters.oddspapi import emit, normalize, parser, pipeline
from genesis_adapters.oddspapi.quota_gate import open_operational_ledger
from genesis_adapters.oddspapi.reader import Unusable, admissible_head
from genesis_adapters.provenance_guard import ModuleProvenanceError
from genesis_adapters.secrets import Secret

from . import parser_support as ps
from .parser_support import FIXTURE_A, FIXTURE_B, fixture_of, market_of, price_of
from .pipeline_support import (
    JSON, START, acquisition_rows, approve, coverage_rows, documents, fixture_body, meta_item, odds_item,
    odds_response, open_rt, pit_rows, reopen,
)
from .support import (
    SENTINEL_KEY, Crash, FakeTransport, FixedClock, http_date, no_response, ok, read_jsonl, scratch_root, status,
    test_quota_policy, truncated,
)

A = err.AdapterFailure


def notes(rt, note):
    """(status, reasons) of every coverage entry whose note is ``note`` or an aggregate ``note:<count>``."""

    return {(row["status"], tuple(row["reason_codes"])) for row in coverage_rows(rt)
            if row["note"] == note or row["note"].startswith(note + ":")}


def states(rt, fixture=None):
    return {(d["market_state"], tuple(d["state_reasons"])) for d in documents(rt)
            if fixture is None or d["provider_fixture_id"]["value"] == fixture}


def raw_count(rt):
    return sum(1 for row in acquisition_rows(rt) if row["record_type"] == "acq_completed"
               and row["raw_observation_id"] is not None)


def quota_rows(rt):
    return [row for row in read_jsonl(rt.root / "quota" / "ledger.jsonl") if row["record_type"].startswith("quota_")]


class NoGate:
    def require_gate(self, gate, *, at, **pins):
        raise err.GateMissing(gate)


class FailureMatrixTests(unittest.TestCase):
    def assert_notes(self, rt, note, status, reason):
        self.assertEqual(notes(rt, note), {(status, (reason,))}, note)

    # -- FM-00 ---------------------------------------------------------------------------------
    def test_fm00_every_detail_code_maps_to_exactly_one_frozen_reason(self):
        for failure in A:
            self.assertIn(failure, err.REASON_CODE_MAP)
            self.assertEqual(err.reason_code(failure), err.REASON_CODE_MAP[failure])
        self.assertEqual(len(err.REASON_CODE_MAP), len(A))
        for code in ("GATE_MISSING", "QUOTA_BLOCKED", "CLOCK_FAULT", "CREDENTIAL_MISSING", "NO_RESPONSE",
                     "TRUNCATED_BODY", "REDIRECT_REFUSED", "AUTH_REJECTED", "RATE_LIMITED", "PROVIDER_ERROR",
                     "SECRET_ECHO", "UNINSPECTABLE_BODY", "CLOCK_SKEW", "NOT_JSON", "ENVELOPE_SCHEMA_MISMATCH",
                     "PARTIAL_RESPONSE", "OUT_OF_SCOPE_COMPETITION", "CONTRADICTORY_DUPLICATE", "INCOMPLETE_SELECTIONS",
                     "INVALID_PRICE", "IDENTITY_CONFLICT", "PARTICIPANT_AMBIGUOUS", "UNKNOWN_EVENT_STATUS",
                     "CONTRADICTORY_STATUS", "OUTCOME_INACTIVE", "EVENT_NOT_PREMATCH", "PREMATCH_WINDOW_CLOSED",
                     "TIMESTAMP_NAIVE", "EVENT_METADATA_STALE", "BOOK_ABSENT", "CONFIG_DIGEST_MISMATCH",
                     "EVIDENCE_CONFLICT", "PIT_APPEND_CONFLICT", "CACHE_MISS", "ORPHANED_RESERVATION",
                     "DATA_CAPABILITY_NOT_READY", "QUOTA_DIVERGENCE", "SCHEMA_DRIFT", "NOT_PUBLISHED_AT_CUTOFF",
                     "INVALIDATED", "MODULE_PROVENANCE", "QUOTA_REPLAY_BROKEN", "WINDOW_BOUNDARY_GUARD"):
            A(code)

    # -- F-01 .. F-04: nothing is sent ---------------------------------------------------------
    def test_fm01_a_missing_gate_refuses_before_any_quota_call(self):
        with scratch_root() as root:
            ledger, cache = open_operational_ledger(root)
            rt = open_rt(root, live=True, clock=SystemUtcClock(drift_max_ms=1000), quota_ledger=ledger, cache=cache,
                         authority=NoGate(), secret=Secret(SENTINEL_KEY))
            result = rt.acquire(odds_item())
            self.assertEqual((result.outcome.outcome, result.outcome.failure), ("REFUSED", A.GATE_MISSING))
            self.assert_notes(rt, "GATE_MISSING", "not_attempted", "configuration_mismatch")
            self.assertEqual((quota_rows(rt), rt.runner.transport.calls, raw_count(rt), pit_rows(rt)), ([], [], 0, []))

    def test_fm02_a_blocked_quota_is_recorded_and_nothing_is_sent(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response()], quota_policy=test_quota_policy(daily=1))
            rt.acquire(odds_item("w1"))
            blocked = rt.acquire(odds_item("w2"))
            self.assertEqual(blocked.outcome.failure, A.QUOTA_BLOCKED)
            self.assert_notes(rt, "QUOTA_BLOCKED", "not_attempted", "attempt_budget_exhausted")
            self.assertEqual([r["record_type"] for r in quota_rows(rt)], ["quota_billable_call", "quota_request_blocked"])
            self.assertEqual(len(rt.runner.transport.calls), 1)
            self.assertEqual(len(pit_rows(rt)), 12)                               # earlier heads simply age out

    def test_fm03_a_clock_behind_the_ledger_halts(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response()])
            rt.acquire(odds_item("w1"))
            rt.clock.set(ps.iso_add(START, seconds=-60))
            with self.assertRaises(err.AcquisitionHalt) as caught:
                rt.acquire(odds_item("w2"))
            self.assertEqual(caught.exception.code, A.CLOCK_FAULT)
            self.assert_notes(rt, "CLOCK_FAULT", "not_attempted", "configuration_mismatch")
            self.assertEqual(len(quota_rows(rt)), 1)

    def test_fm04_a_credential_problem_refuses_and_halts(self):
        def check():
            raise err.CredentialProblem("CREDENTIAL_FINGERPRINT_MISMATCH")

        with scratch_root() as root:
            rt = open_rt(root, credential_check=check)
            with self.assertRaises(err.AcquisitionHalt):
                rt.acquire(odds_item())
            self.assert_notes(rt, "CREDENTIAL_FINGERPRINT_MISMATCH", "not_attempted", "configuration_mismatch")
            self.assertEqual((quota_rows(rt), rt.runner.transport.calls), ([], []))

    # -- F-05 .. F-14: transport and body ------------------------------------------------------
    def test_fm05_a_transport_error_keeps_the_debit_and_is_missing_evidence(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[no_response("ConnectionResetError", 104)])
            result = rt.acquire(odds_item())
            self.assertEqual(result.outcome.failure, A.NO_RESPONSE)
            self.assert_notes(rt, "NO_RESPONSE", "missing", "missing_evidence")
            self.assertEqual([r["record_type"] for r in quota_rows(rt)], ["quota_billable_call"])
            self.assertEqual((raw_count(rt), pit_rows(rt)), (0, []))

    def test_fm06_a_truncated_body_is_raw_evidence_only(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[truncated(b'[{"fixtureId":', headers=JSON)])
            result = rt.acquire(odds_item())
            self.assertEqual(result.outcome.failure, A.TRUNCATED_BODY)
            self.assert_notes(rt, "TRUNCATED_BODY", "rejected", "schema_rejected")
            self.assertEqual((raw_count(rt), pit_rows(rt)), (1, []))

    def test_fm07_a_redirect_is_refused_and_its_body_kept(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[status(302, b"moved", headers=JSON + (("location", "https://x.example/"),))])
            self.assertEqual(rt.acquire(odds_item()).outcome.failure, A.REDIRECT_REFUSED)
            self.assert_notes(rt, "REDIRECT_REFUSED", "rejected", "source_contract_violation")
            self.assertEqual((raw_count(rt), pit_rows(rt), len(rt.runner.transport.calls)), (1, [], 1))

    def test_fm08_auth_rejection_blocks_every_market_book_capability_and_opens_the_circuit(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[status(401, b"no")])
            approve(rt)
            self.assertEqual(rt.acquire(odds_item("w1")).outcome.failure, A.AUTH_REJECTED)
            self.assert_notes(rt, "AUTH_REJECTED", "rejected", "configuration_mismatch")
            self.assertEqual(rt.blocked, ["AUTH_REJECTED"])
            self.assertFalse(rt.stores.capabilities.history(rt.stores.source_id)[-1].is_ready())
            self.assertEqual(rt.acquire(odds_item("w2")).outcome.failure, A.CIRCUIT_OPEN)
            self.assertEqual(raw_count(rt), 1)

    def test_fm09_rate_limiting_is_budget_exhaustion_with_the_retry_after_header_kept(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[status(429, b"slow", headers=JSON + (("retry-after", "120"),))])
            self.assertEqual(rt.acquire(odds_item("w1")).outcome.failure, A.RATE_LIMITED)
            self.assert_notes(rt, "RATE_LIMITED", "not_attempted", "attempt_budget_exhausted")
            completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"][0]
            self.assertIn(["retry-after", "120"], completed["headers"])
            self.assertEqual(rt.acquire(odds_item("w2")).outcome.failure, A.CIRCUIT_OPEN)

    def test_fm10_a_server_error_is_missing_evidence_with_its_body_kept(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[status(503, b"busy")])
            self.assertEqual(rt.acquire(odds_item()).outcome.failure, A.PROVIDER_ERROR)
            self.assert_notes(rt, "PROVIDER_ERROR", "missing", "missing_evidence")
            self.assertEqual((raw_count(rt), pit_rows(rt)), (1, []))

    def test_fm11_a_secret_echo_keeps_no_body_quarantines_halts_and_blocks(self):
        with scratch_root() as root:
            rt = open_rt(root, secret=Secret(SENTINEL_KEY),
                         script=[ok(b'[{"echo":"' + SENTINEL_KEY.encode() + b'"}]', headers=JSON)])
            approve(rt)
            with self.assertRaises(err.AcquisitionHalt) as caught:
                rt.acquire(odds_item())
            self.assertEqual(caught.exception.code, A.SECRET_ECHO)
            self.assert_notes(rt, "SECRET_ECHO", "quarantined", "artifact_tampered")
            self.assertEqual((raw_count(rt), rt.stores.evidence.verify_manifest()), (0, 0))
            self.assertEqual([q["reason"] for q in read_jsonl(root / "quarantine.jsonl")], ["SECRET_ECHO"])
            self.assertEqual(rt.blocked, ["SECRET_ECHO"])

    def test_fm11b_an_uninspectable_body_is_quarantined_metadata_only_without_a_halt(self):
        with scratch_root() as root:
            rt = open_rt(root, secret=Secret(SENTINEL_KEY),
                         script=[ok(b"\x00\x01", headers=JSON + (("content-encoding", "br"),)), odds_response()])
            self.assertEqual(rt.acquire(odds_item("w1")).outcome.failure, A.UNINSPECTABLE_BODY)
            self.assert_notes(rt, "UNINSPECTABLE_BODY", "quarantined", "schema_rejected")
            self.assertEqual((raw_count(rt), rt.stores.evidence.verify_manifest(), pit_rows(rt)), (0, 0, []))
            self.assertIsNone(rt.acquire(odds_item("w2")).outcome.failure)             # no halt

    def test_fm12_clock_skew_quarantines_keeps_raw_and_suspends_sends(self):
        with scratch_root() as root:
            skewed = http_date(ps.iso_add(START, seconds=3600))
            rt = open_rt(root, require_date=True, script=[odds_response(headers=JSON + (("date", skewed),))])
            self.assertEqual(rt.acquire(odds_item("w1")).outcome.failure, A.CLOCK_SKEW)
            self.assert_notes(rt, "CLOCK_SKEW", "quarantined", "critical_uncertainty")
            self.assertEqual((raw_count(rt), pit_rows(rt)), (1, []))
            self.assertEqual(rt.acquire(odds_item("w2")).outcome.failure, A.CIRCUIT_OPEN)

    def test_fm13_and_fm14_bad_json_or_envelope_keep_raw_and_emit_nothing(self):
        for body, code in ((b"{", "NOT_JSON"), (b'[{"a":1,"a":2}]', "DUPLICATE_KEYS"), (b"[NaN]", "NONFINITE_NUMBER"),
                           (b'{"fixtures": []}', "ENVELOPE_SCHEMA_MISMATCH")):
            with self.subTest(code), scratch_root() as root:
                rt = open_rt(root, script=[odds_response(), ok(body, headers=JSON)])
                rt.acquire(odds_item("w1"))
                before = pit_rows(rt)
                rt.clock.advance(seconds=600)
                self.assertEqual(rt.acquire(odds_item("w2")).outcome.failure, A(code))
                self.assert_notes(rt, code, "rejected", "schema_rejected")
                self.assertEqual((raw_count(rt), pit_rows(rt)), (2, before))        # no tombstones either

    # -- F-15 .. F-30: content ------------------------------------------------------------------
    def run_pair(self, root, second, **kw):
        rt = open_rt(root, script=[odds_response(), odds_response(second)], **kw)
        rt.acquire(odds_item("w1"))
        rt.clock.advance(seconds=600)
        rt.acquire(odds_item("w2"))
        return rt

    def second_states(self, rt, fixture=FIXTURE_A):
        later = max(row["available_at"] for row in pit_rows(rt))
        return {(d["market_state"], tuple(d["state_reasons"])) for d, row in zip(documents(rt), pit_rows(rt))
                if row["available_at"] == later and d["provider_fixture_id"]["value"] == fixture}

    def test_fm15_a_partial_payload_emits_present_books_and_no_tombstones(self):
        with scratch_root() as root:
            second = ps.odds_payload()
            del fixture_of(second, FIXTURE_B)["bookmakerOdds"]["pinnacle"]["markets"]
            rt = self.run_pair(root, second)
            self.assert_notes(rt, "PARTIAL_RESPONSE", "rejected", "missing_evidence")
            self.assertNotIn("ABSENT", {d["market_state"] for d in documents(rt)})
            self.assertEqual(self.second_states(rt), {("OPEN", ())})

    def test_fm16_and_fm17_out_of_scope_content_is_counted_never_normalized(self):
        with scratch_root() as root:
            payload = ps.odds_payload()
            fixture_of(payload, FIXTURE_B)["tournamentId"] = 999
            fixture_of(payload)["bookmakerOdds"]["pinnacle"]["markets"]["9999"] = \
                fixture_of(payload)["bookmakerOdds"]["pinnacle"]["markets"]["101"]
            rt = open_rt(root, script=[odds_response(payload)])
            rt.acquire(odds_item())
            self.assert_notes(rt, "OUT_OF_SCOPE_COMPETITION", "rejected", "unsupported_market")
            for code in ("OUT_OF_SCOPE_BOOKMAKER", "OUT_OF_SCOPE_MARKET", "OUT_OF_SCOPE_LINE"):
                self.assert_notes(rt, code, "rejected", "unsupported_market")
            self.assertEqual({d["provider_fixture_id"]["value"] for d in documents(rt)}, {FIXTURE_A})

    def blocked_case(self, edit, code, status_, reason):
        with scratch_root() as root:
            payload = ps.odds_payload()
            edit(payload)
            rt = open_rt(root, script=[odds_response(payload)])
            rt.acquire(odds_item())
            self.assert_notes(rt, code, status_, reason)
            self.assertIn(("BLOCKED", (code,)), states(rt))
            return rt

    def test_fm18_a_differing_duplicate_blocks_the_book(self):
        def edit(p):
            markets = fixture_of(p)["bookmakerOdds"]["pinnacle"]["markets"]
            markets["1011"] = json.loads(json.dumps(markets["1010"]))
            markets["1011"]["outcomes"]["2002"]["players"]["0"]["price"] = 1.96
        self.blocked_case(edit, "CONTRADICTORY_DUPLICATE", "rejected", "contradictory_evidence")

    def test_fm19_an_incomplete_outcome_set_blocks_the_book(self):
        self.blocked_case(lambda p: market_of(p, "pinnacle", "101")["outcomes"].pop("102"),
                          "INCOMPLETE_SELECTIONS", "rejected", "schema_rejected")

    def test_fm20_invalid_or_incoherent_prices_block_the_book(self):
        self.blocked_case(lambda p: price_of(p, "pinnacle", "1010", "2001").__setitem__("price", 5000),
                          "INVALID_PRICE", "rejected", "price_sanity_failed")
        def incoherent(p):
            price_of(p, "pinnacle", "1010", "2001")["price"] = 1.2
            price_of(p, "pinnacle", "1010", "2002")["price"] = 1.2
        self.blocked_case(incoherent, "PRICE_INCOHERENT", "rejected", "contradictory_evidence")

    def test_fm21_an_identity_conflict_blocks_known_books_and_quarantines_the_event(self):
        with scratch_root() as root:
            second = ps.odds_payload()
            fixture_of(second)["participant1Id"] = 99
            rt = self.run_pair(root, second)
            self.assert_notes(rt, "IDENTITY_CONFLICT", "ambiguous", "ambiguous_identity")
            self.assert_notes(rt, "EVENT_QUARANTINED", "quarantined", "ambiguous_identity")
            self.assertEqual(self.second_states(rt), {("BLOCKED", ("IDENTITY_CONFLICT",))})

    def test_fm22_an_ambiguous_participant_blocks_the_event(self):
        self.blocked_case(lambda p: fixture_of(p).__setitem__("participant2Id", fixture_of(p)["participant1Id"]),
                          "PARTICIPANT_AMBIGUOUS", "ambiguous", "ambiguous_identity")

    def test_fm23_an_unknown_status_blocks(self):
        self.blocked_case(lambda p: fixture_of(p).__setitem__("statusId", 42), "UNKNOWN_EVENT_STATUS", "rejected",
                          "critical_uncertainty")

    def test_fm24_a_contradictory_status_blocks(self):
        self.blocked_case(lambda p: fixture_of(p).__setitem__("statusId", 2), "CONTRADICTORY_STATUS", "rejected",
                          "contradictory_evidence")

    def test_fm25_a_suspension_is_available_state_with_a_suspended_head(self):
        with scratch_root() as root:
            payload = ps.odds_payload()
            price_of(payload, "pinnacle", "1010", "2002")["active"] = False
            rt = open_rt(root, script=[odds_response(payload)])
            rt.acquire(odds_item())
            self.assertEqual(notes(rt, "SUSPENDED"), {("available", ())})
            self.assertIn(("SUSPENDED", ("OUTCOME_INACTIVE",)), states(rt))

    def test_fm26_an_event_that_is_no_longer_pre_match_blocks(self):
        def edit(p):
            fixture_of(p)["statusId"] = 2
            for bookmaker in ("pinnacle", "fixture-book-a", "fixture-book-b"):
                for market in fixture_of(p)["bookmakerOdds"][bookmaker]["markets"].values():
                    for outcome in market["outcomes"].values():
                        outcome["players"]["0"]["active"] = False
        self.blocked_case(edit, "EVENT_NOT_PREMATCH", "rejected", "expired")

    def test_fm27_a_capture_inside_the_guard_emits_nothing_for_the_event(self):
        with scratch_root() as root:
            payload = ps.odds_payload()
            fixture_of(payload, FIXTURE_B)["startTime"] = ps.iso_add(START, seconds=240)
            rt = open_rt(root, script=[odds_response(payload)])
            rt.acquire(odds_item())
            self.assert_notes(rt, "PREMATCH_WINDOW_CLOSED", "rejected", "expired")
            self.assertEqual(states(rt, FIXTURE_B), set())

    def test_fm28_a_provider_timestamp_anomaly_blocks(self):
        self.blocked_case(lambda p: price_of(p, "pinnacle", "1010", "2001").__setitem__("changedAt", "2026-10-01T11:00:00"),
                          "TIMESTAMP_NAIVE", "rejected", "not_available_at_decision")

    def test_fm29_a_missing_fixture_join_is_stale_metadata(self):
        self.blocked_case(lambda p: fixture_of(p).pop("startTime"), "EVENT_METADATA_STALE", "missing", "stale_evidence")

    def test_fm30_an_expected_book_absent_from_a_complete_response_gets_an_absent_head(self):
        with scratch_root() as root:
            second = ps.odds_payload()
            del fixture_of(second)["bookmakerOdds"]["pinnacle"]["markets"]["1010"]
            rt = self.run_pair(root, second)
            self.assertEqual(notes(rt, "BOOK_ABSENT"), {("available", ())})
            self.assertIn(("ABSENT", ("BOOK_ABSENT",)), self.second_states(rt))

    # -- F-31 .. F-43: integrity, cache, capability, drift, invalidation, boundary -----------------
    def test_fm31_a_configuration_change_halts(self):
        from .pipeline_support import copy_config
        with scratch_root() as root:
            config_dir = copy_config(root)
            rt = open_rt(root / "rt", config_dir=config_dir, script=[odds_response()])
            (config_dir / "oddspapi_v4_status_map.json").write_bytes(
                (config_dir / "oddspapi_v4_status_map.json").read_bytes().replace(b"Finished", b"Ended"))
            with self.assertRaises(pipeline.PipelineHalt):
                rt.acquire(odds_item())
            self.assert_notes(rt, "CONFIG_DIGEST_MISMATCH", "not_attempted", "configuration_mismatch")
            self.assertEqual((quota_rows(rt), pit_rows(rt)), ([], []))

    def test_fm32_an_evidence_conflict_halts_and_never_rewrites_existing_bytes(self):
        with scratch_root() as root:                                     # at raw capture
            rt = open_rt(root, script=[odds_response(), odds_response()])
            first = rt.acquire(odds_item("w1"))
            digest = rt.stores.evidence.get_observation(first.outcome.captured.raw_observation_id).artifact_hash
            path = root / "evidence" / "objects" / digest[:2] / digest
            path.write_bytes(b"tampered")
            rt.clock.advance(seconds=600)
            with self.assertRaises(err.AcquisitionHalt):
                rt.acquire(odds_item("w2"))
            self.assertEqual(path.read_bytes(), b"tampered")
            self.assert_notes(rt, "EVIDENCE_CONFLICT", "quarantined", "artifact_tampered")
        with scratch_root() as root:                                     # at emission, on resume
            def hook(step):
                if step == "after_observation:0":
                    raise Crash()
            rt = open_rt(root, script=[odds_response()], checkpoint=hook)
            with self.assertRaises(Crash):
                rt.acquire(odds_item())
            published = [p for p in (root / "evidence" / "objects").rglob("*") if p.is_file()]
            normalized = [p for p in published if b"market-book.v1" in p.read_bytes()]
            normalized[0].write_bytes(b"tampered")
            restarted = reopen(rt)
            with self.assertRaises(pipeline.PipelineHalt) as caught:
                restarted.resume()
            self.assertEqual(caught.exception.code, A.EVIDENCE_CONFLICT)
            self.assert_notes(restarted, "EVIDENCE_CONFLICT", "quarantined", "artifact_tampered")
            self.assertEqual(pit_rows(restarted), [])

    def test_fm33_a_pit_append_conflict_halts(self):
        with scratch_root() as root:
            def hook(step):
                if step == "after_pit:0":
                    raise Crash()
            rt = open_rt(root, script=[odds_response()], checkpoint=hook)
            with self.assertRaises(Crash):
                rt.acquire(odds_item())
            restarted = reopen(rt)
            aid = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"][0]["acquisition_id"]
            inputs = restarted._inputs(aid)
            docs = normalize.build_documents(parser.parse_odds_response(inputs.raw, inputs.ctx), inputs.ctx)
            victim = docs[1]
            t1 = inputs.ctx.response_received_at
            restarted.stores.pit.append(BitemporalRecord(
                record_id=emit.pit_record_id(restarted.stores.source_id, victim.artifact_hash),
                entity_id=victim.entity_id, source_id=restarted.stores.source_id, payload_hash=victim.artifact_hash,
                available_at=t1, published_at=None, retrieved_at=t1, ready_at=ps.iso_add(t1, seconds=5),
                valid_from=t1, valid_to=None))                             # differs from the intended record
            with self.assertRaises(pipeline.PipelineHalt) as caught:
                restarted.resume()
            self.assertEqual(caught.exception.code, A.PIT_APPEND_CONFLICT)
            self.assert_notes(restarted, "PIT_APPEND_CONFLICT", "quarantined", "artifact_tampered")
            self.assertEqual(restarted.acquire(odds_item("w9")).outcome.failure, A.CIRCUIT_OPEN)

    def test_fm34_a_metadata_cache_miss_is_a_recorded_genesis_debit(self):
        with scratch_root() as root:
            body = fixture_body("tournaments.json")
            rt = open_rt(root, script=[ok(body, headers=JSON), ok(body, headers=JSON)])
            rt.acquire(meta_item(window="m1"))
            self.assertEqual(rt.acquire(meta_item(window="m2")).outcome.outcome, "CACHE_HIT")
            rt.clock.advance(seconds=rt.config.policy.cache_ttl_seconds["META_TOURNAMENTS"] + 1)
            miss = rt.acquire(meta_item(window="m3"))
            self.assertIsNone(miss.outcome.failure)
            decided = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_quota_decided"][-1]
            self.assertEqual((decided["genesis_units_debited"], decided["cache_miss_reason"]),
                             (1, "CACHE_EXPIRED_OR_INVALIDATED"))
            self.assertEqual([r["record_type"] for r in quota_rows(rt)],
                             ["quota_billable_call", "quota_verified_cache_hit", "quota_billable_call"])

    def test_fm35_an_orphaned_reservation_is_missing_evidence(self):
        with scratch_root() as root:
            def hook(step):
                if step == "after_sent":
                    raise Crash()
            rt = open_rt(root, script=[odds_response()], runner_checkpoint=hook)
            with self.assertRaises(Crash):
                rt.acquire(odds_item())
            restarted = reopen(rt)
            restarted.resume()
            self.assert_notes(restarted, "ORPHANED_RESERVATION", "missing", "missing_evidence")
            self.assertEqual(len(quota_rows(restarted)), 1)                           # the debit stands

    def test_fm36_no_ready_or_two_ready_sources_are_unusable(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response()])
            rt.acquire(odds_item())
            entity, later = pit_rows(rt)[0]["entity_id"], ps.iso_add(START, seconds=60)
            self.assertEqual(admissible_head(entity, later, stores=rt.stores).code, A.DATA_CAPABILITY_NOT_READY)
            approve(rt)
            from .emit_support import approve_source, with_version
            approve_source(with_version(rt.stores, "mb1-" + "3" * 16), at="2026-09-30T00:00:01.000000Z")
            self.assertEqual(admissible_head(entity, later, stores=rt.stores).code, A.AMBIGUOUS_SOURCE)

    def test_fm37_and_q09_provider_usage_above_the_genesis_debit_halts(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response(headers=JSON + (("x-requests-used", "1"),)),
                                       odds_response(headers=JSON + (("x-requests-used", "9"),))])
            first = rt.acquire(odds_item("w1"))
            self.assertIsNone(first.outcome.failure)
            completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"]
            self.assertEqual(completed[0]["provider_reported_usage"],
                             {"header": "x-requests-used", "reported": 1, "genesis_debited": 1, "window": "utc_month"})
            before = pit_rows(rt)
            rt.clock.advance(seconds=600)
            with self.assertRaises(err.AcquisitionHalt) as caught:
                rt.acquire(odds_item("w2"))
            self.assertEqual(caught.exception.code, A.QUOTA_DIVERGENCE)
            self.assert_notes(rt, "QUOTA_DIVERGENCE", "not_attempted", "configuration_mismatch")
            self.assertEqual((raw_count(rt), pit_rows(rt)), (2, before))              # headers kept, nothing derived
            last = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"][-1]
            self.assertIn(["x-requests-used", "9"], last["headers"])

    def test_fm38_schema_drift_blocks_at_its_scope_and_rejects_at_the_envelope(self):
        def drift(p):
            price_of(p, "pinnacle", "1010", "2001")["surprise"] = 1
        self.blocked_case(drift, "SCHEMA_DRIFT", "rejected", "schema_rejected")
        with scratch_root() as root:
            body = fixture_body("tournaments.json").replace(b'"categoryName"', b'"surprise": 1, "categoryName"', 1)
            rt = open_rt(root, script=[ok(body, headers=JSON)])
            self.assertEqual(rt.acquire(meta_item()).outcome.failure, A.SCHEMA_DRIFT)
            self.assert_notes(rt, "SCHEMA_DRIFT", "rejected", "schema_rejected")
            self.assertEqual((raw_count(rt), pit_rows(rt)), (1, []))

    def test_fm39_a_head_published_after_the_cutoff_is_unusable_with_no_fallback(self):
        with scratch_root() as root:
            second = ps.odds_payload()
            rt = open_rt(root, script=[odds_response(), self.published_late(second)])
            approve(rt)
            rt.acquire(odds_item("w1"))
            rt.clock.advance(seconds=600)
            rt.acquire(odds_item("w2"))
            late = [r for r in pit_rows(rt) if r["published_at"] and r["published_at"] > r["ready_at"]]
            self.assertTrue(late)
            verdict = admissible_head(late[0]["entity_id"], late[0]["ready_at"], stores=rt.stores)
            self.assertEqual(verdict.code, A.NOT_PUBLISHED_AT_CUTOFF)

    @staticmethod
    def published_late(payload):
        def step(clock):
            price_of(payload, "pinnacle", "1010", "2001")["changedAt"] = ps.iso_add(clock.peek(), seconds=5)
            return odds_response(payload)
        return step

    def test_fm40_an_invalidation_quarantines_and_heads_the_scope(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response()])
            approve(rt)
            rt.acquire(odds_item())
            row = pit_rows(rt)[0]
            observation = rt.stores.evidence.get_observations(row["payload_hash"])[0]
            t_inv = ps.iso_add(START, seconds=600)
            from .support import SequenceClock
            emit.emit_invalidation(invalidated_observation_id=observation.observation_id,
                                   invalidation_class="OPERATOR", reason="OPERATOR_INVALIDATION", actor="OPERATOR",
                                   evidence_refs=("op-1",), stores=rt.stores,
                                   clock=SequenceClock([t_inv, ps.iso_add(t_inv, seconds=1), ps.iso_add(t_inv, seconds=2),
                                                        ps.iso_add(t_inv, seconds=3)]))
            self.assert_notes(rt, "INVALIDATED", "quarantined", "contradictory_evidence")
            verdict = admissible_head(row["entity_id"], ps.iso_add(t_inv, seconds=5), stores=rt.stores)
            self.assertEqual(verdict.code, A.INVALIDATED)
            self.assertIsInstance(admissible_head(row["entity_id"], ps.iso_add(t_inv, seconds=1), stores=rt.stores),
                                  type(admissible_head(row["entity_id"], ps.iso_add(START, seconds=60),
                                                       stores=rt.stores)))

    def test_fm41_a_module_provenance_failure_refuses_to_start(self):
        def failing():
            raise ModuleProvenanceError("MODULE_BYTES_DIFFER", "genesis.pit")

        with scratch_root() as root:
            with self.assertRaises(pipeline.PipelineHalt):
                open_rt(root, provenance_check=failing)
            entry = read_jsonl(root / "coverage.jsonl")[-1]
            self.assertEqual((entry["status"], entry["reason_codes"], entry["note"]),
                             ("not_attempted", ["configuration_mismatch"], "MODULE_PROVENANCE"))

    def test_fm42_an_altered_cache_object_halts_every_acquisition(self):
        with scratch_root() as root:
            body = fixture_body("tournaments.json")
            rt = open_rt(root, script=[ok(body, headers=JSON)])
            rt.acquire(meta_item(window="m1"))
            self.assertEqual(rt.acquire(meta_item(window="m2")).outcome.outcome, "CACHE_HIT")
            for path in (root / "quota" / "cache").rglob("*"):
                if path.is_file() and path.read_bytes() == body:
                    path.write_bytes(b"altered")
            with self.assertRaises(err.AcquisitionHalt) as caught:
                rt.acquire(meta_item(window="m3"))
            self.assertEqual(caught.exception.code, A.QUOTA_REPLAY_BROKEN)
            self.assert_notes(rt, "QUOTA_REPLAY_BROKEN", "quarantined", "artifact_tampered")
            self.assertEqual(rt.acquire(odds_item()).outcome.failure, A.CIRCUIT_OPEN)

    def test_fm43_the_boundary_guard_refuses_before_any_quota_row(self):
        with scratch_root() as root:
            rt = open_rt(root, clock=FixedClock("2026-10-01T23:59:00.000000Z", step_micros=1000))
            result = rt.acquire(odds_item())
            self.assertEqual((result.outcome.outcome, result.outcome.failure), ("REFUSED", A.WINDOW_BOUNDARY_GUARD))
            self.assert_notes(rt, "WINDOW_BOUNDARY_GUARD", "not_attempted", "attempt_budget_exhausted")
            self.assertEqual((quota_rows(rt), rt.runner.transport.calls), ([], []))


if __name__ == "__main__":
    unittest.main()
