"""Q-01, Q-02, Q-04..Q-07, BILL-01..03, CLK-03, REQ-06, F-01..F-05, F-07..F-10, F-35 (F-02 is the Q-02 test)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import unittest
from datetime import datetime, timedelta

from genesis.quota import QuotaLedger, VerifiedCacheStore
from genesis.registry import RegistryConflict
from genesis.time import iso_utc, parse_utc

from genesis_adapters import errors as err
from genesis_adapters.clock import SystemUtcClock
from genesis_adapters.oddspapi import acquisition as acq
from genesis_adapters.oddspapi import endpoints as ep

from . import support as sup
from .support import (
    Crash, FixedClock, build_rig, crash, meta_item, no_response, odds_item, ok, raises, read_jsonl,
    scratch_root, status, test_quota_policy, truncated,
)

BASE = "2026-10-01T12:00:00.000000Z"
SECRET_URL = "https://api.oddspapi.io/v4/odds?apiKey=" + sup.SENTINEL_KEY


def canon(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def acquisition_id(request_hash: str, window: str, attempt: int) -> str:
    return hashlib.sha256(canon({"domain": "genesis.adapters.oddspapi.attempt.v1",
                                 "provider_request_hash": request_hash, "window_id": window,
                                 "attempt": attempt})).hexdigest()


def kinds(rig, acq_id=None) -> list[str]:
    rows = read_jsonl(rig.acq_path)
    return [r["record_type"] for r in rows if acq_id is None or r.get("acquisition_id") == acq_id]


def rows_of(rig, record_type: str) -> list[dict]:
    return [r for r in read_jsonl(rig.acq_path) if r["record_type"] == record_type]


def coverage(rig) -> list[dict]:
    return read_jsonl(rig.coverage_path)


def quota_rows(rig) -> list[dict]:
    return [r for r in read_jsonl(rig.root / "quota" / "ledger.jsonl") if r["record_type"].startswith("quota_")]


class HappyPathTests(unittest.TestCase):
    def test_q01_every_sent_acquisition_has_exactly_one_prior_allowed_quota_row(self):
        with scratch_root() as root:
            rig = build_rig(root, clock=FixedClock(BASE, step_micros=1000))
            items = [odds_item(window=f"w{i}") for i in range(3)]
            outcomes = [rig.runner.acquire(item) for item in items]
            self.assertTrue(all(o.outcome == "RESPONSE" for o in outcomes))
            rows = read_jsonl(rig.acq_path)
            quota = {r["request_id"]: r for r in quota_rows(rig)}
            for item, outcome in zip(items, outcomes):
                aid = acquisition_id(item.request.provider_request_hash, item.window_id, 1)
                self.assertEqual(outcome.acquisition_id, aid)
                request_id = f"oddspapi-attempt:{aid}"
                mine = [r for r in rows if r.get("acquisition_id") == aid]
                order = [r["record_type"] for r in mine]
                self.assertEqual(order, ["acq_planned", "acq_quota_decided", "acq_sent", "acq_completed"])
                matching = [r for r in quota_rows(rig) if r["request_id"] == request_id]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0]["record_type"], "quota_billable_call")
                self.assertTrue(matching[0]["allowed"])
                # the frozen fingerprint binds the provider_request_hash: recompute it independently
                fingerprint = hashlib.sha256(canon({
                    "provider_id": "oddspapi", "occurred_at": matching[0]["occurred_at"],
                    "billable_units": 1, "budget_class": "normal", "authorization_id": None,
                    "cache_entry_id": None,
                    "provider_request_hash": item.request.provider_request_hash,
                    "quota_policy_version": rig.quota_ledger.policy.version,
                    "quota_policy_digest": rig.quota_ledger.policy.policy_digest})).hexdigest()
                self.assertEqual(matching[0]["request_fingerprint"], fingerprint)
                self.assertEqual(mine[1]["Tq"], matching[0]["occurred_at"])
            self.assertEqual(len(rig.transport.calls), 3)
            self.assertEqual(len(quota), 3)

    def test_planned_row_carries_the_metering_fields_and_completed_the_http_facts(self):
        with scratch_root() as root:
            rig = build_rig(root, script=[ok(b'["x"]', headers=(("content-type", "application/json"),
                                                                 ("date", "Thu, 01 Oct 2026 12:00:00 GMT")))])
            outcome = rig.runner.acquire(odds_item())
            planned = rows_of(rig, "acq_planned")[0]
            self.assertEqual(planned["role"], "ODDS")
            self.assertEqual(planned["provider_metering"], "PER_REQUEST")
            self.assertEqual(planned["provider_request_weight"], 1)
            self.assertIs(planned["provider_documented_billable"], True)
            self.assertEqual(planned["genesis_debit_units"], 1)
            self.assertEqual(planned["request_id"], f"oddspapi-attempt:{planned['acquisition_id']}")
            self.assertEqual(planned["recorded_at"], rows_of(rig, "acq_quota_decided")[0]["Tq"])
            done = rows_of(rig, "acq_completed")[0]
            self.assertEqual((done["outcome"], done["http_status"], done["byte_length"]), ("RESPONSE", 200, 5))
            self.assertIsNone(done["failure"])
            self.assertIsNone(outcome.failure)
            self.assertEqual(outcome.result.body, b'["x"]')

    def test_canonical_request_bytes_are_stored_content_addressed(self):
        with scratch_root() as root:
            rig = build_rig(root)
            item = odds_item()
            rig.runner.acquire(item)
            path = root / "requests" / f"{item.request.provider_request_hash}.json"
            self.assertEqual(path.read_bytes(), item.request.canonical_bytes())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item.request.provider_request_hash)

    def test_repeating_a_completed_plan_item_is_idempotent_and_never_resends(self):
        with scratch_root() as root:
            rig = build_rig(root)
            item = odds_item()
            first = rig.runner.acquire(item)
            again = rig.runner.acquire(item)
            self.assertEqual(again.acquisition_id, first.acquisition_id)
            self.assertEqual(again.outcome, "DUPLICATE")
            self.assertEqual(len(rig.transport.calls), 1)
            self.assertEqual(len(quota_rows(rig)), 1)


class QuotaBehaviourTests(unittest.TestCase):
    def test_q02_f02_eighth_request_of_a_utc_day_is_blocked_and_never_sent(self):
        with scratch_root() as root:
            rig = build_rig(root)
            outcomes = [rig.runner.acquire(odds_item(window=f"w{i}")) for i in range(8)]
            self.assertEqual([o.outcome for o in outcomes], ["RESPONSE"] * 7 + ["QUOTA_BLOCKED"])
            self.assertEqual(len(rig.transport.calls), 7)
            self.assertEqual(outcomes[7].failure, err.AdapterFailure.QUOTA_BLOCKED)
            self.assertEqual(outcomes[7].charge.reason, "daily_quota_exhausted")
            blocked = [r for r in quota_rows(rig) if r["record_type"] == "quota_request_blocked"]
            self.assertEqual([r["reason"] for r in blocked], ["daily_quota_exhausted"])
            entries = coverage(rig)
            self.assertEqual(len(entries), 1)
            self.assertEqual((entries[0]["status"], entries[0]["reason_codes"], entries[0]["note"]),
                             ("not_attempted", ["attempt_budget_exhausted"], "QUOTA_BLOCKED"))
            self.assertEqual(kinds(rig, outcomes[7].acquisition_id),
                             ["acq_planned", "acq_quota_decided"])

    def test_q03_the_runner_only_ever_requests_normal_budget_without_authorization(self):
        calls = []

        class Spy:
            def __init__(self, inner):
                self._inner = inner

            def request(self, **kwargs):
                calls.append(kwargs)
                return self._inner.request(**kwargs)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        with scratch_root() as root:
            cache = VerifiedCacheStore(root / "quota" / "cache")
            real = QuotaLedger(root / "quota" / "ledger.jsonl", policy=test_quota_policy(),
                               allow_test_policy=True, cache_store=cache)
            rig = build_rig(root, quota_ledger=Spy(real), cache=cache)
            for index in range(3):
                rig.runner.acquire(odds_item(window=f"w{index}"))
            self.assertEqual(len(calls), 3)
            for call in calls:
                self.assertEqual(str(call["budget_class"]), "normal")
                self.assertIsNone(call["authorization_id"])
                self.assertEqual(call["provider_id"], "oddspapi")
                self.assertEqual(call["billable_units"], 1)
                self.assertEqual(len(call["provider_request_hash"]), 64)

    def test_q04_failures_keep_their_debit_and_a_retry_is_debited_again(self):
        cases = [("timeout", no_response("TimeoutError")), ("5xx", status(503)), ("429", status(429)),
                 ("401", status(401))]
        for label, scripted in cases:
            with self.subTest(label), scratch_root() as root:
                rig = build_rig(root, script=[scripted, ok()], clock=FixedClock(BASE, step_micros=1000))
                first = rig.runner.acquire(odds_item(window="w1"))
                self.assertIsNotNone(first.failure, label)
                debit = [r for r in quota_rows(rig) if r["record_type"] == "quota_billable_call"]
                self.assertEqual(len(debit), 1, label)
                self.assertEqual(debit[0]["billable_units"], 1)
                rig.clock.advance(seconds=rig.policy.retry_min_backoff_seconds)
                # a retry is a NEW attempt: new request_id, debited again (401/429 are then refused
                # by the circuit before any debit, so they use a different role for the follow-up)
                retry_item = odds_item(window="w1", attempt=2)
                second = rig.runner.acquire(retry_item)
                if label in {"401", "429"}:
                    self.assertEqual(second.failure, err.AdapterFailure.CIRCUIT_OPEN, label)
                    self.assertEqual(len([r for r in quota_rows(rig)
                                          if r["record_type"] == "quota_billable_call"]), 1)
                else:
                    self.assertIsNone(second.failure, label)
                    rows = [r for r in quota_rows(rig) if r["record_type"] == "quota_billable_call"]
                    self.assertEqual(len(rows), 2, label)
                    self.assertNotEqual(rows[0]["request_id"], rows[1]["request_id"])
                    self.assertEqual(second.acquisition_id,
                                     acquisition_id(retry_item.request.provider_request_hash, "w1", 2))

    def test_bill01_metering_fields_are_separate_from_the_genesis_debit(self):
        with scratch_root() as root:
            rig = build_rig(root)
            spec = dataclasses.replace(rig.specs["ODDS"], provider_metering=ep.Metering.NON_METERED,
                                       provider_request_weight=0, provider_documented_billable=False,
                                       genesis_debit_units=1)
            rig.runner.config.endpoints["ODDS"] = spec
            rig.runner.acquire(odds_item(window="nm", specs=rig.specs))
            planned = rows_of(rig, "acq_planned")[0]
            self.assertEqual((planned["provider_metering"], planned["provider_request_weight"],
                              planned["provider_documented_billable"], planned["genesis_debit_units"]),
                             ("NON_METERED", 0, False, 1))
            decided = rows_of(rig, "acq_quota_decided")[0]
            self.assertEqual(decided["genesis_units_debited"], 1)
            self.assertGreaterEqual(decided["genesis_units_debited"], 1)
            done = rows_of(rig, "acq_completed")[0]
            self.assertIn("provider_reported_usage", done)
            self.assertIsNone(done["provider_reported_usage"])
            self.assertNotIn("billed", json.dumps(read_jsonl(rig.acq_path)).lower())

    def test_bill02_fixed_weight_role_debits_its_units_in_one_frozen_request(self):
        with scratch_root() as root:
            rig = build_rig(root)
            spec = dataclasses.replace(rig.specs["ODDS"], provider_metering=ep.Metering.FIXED_WEIGHT,
                                       provider_request_weight=2, provider_documented_billable=True,
                                       genesis_debit_units=3)
            rig.runner.config.endpoints["ODDS"] = spec
            rig.runner.acquire(odds_item(window="fw", specs=rig.specs))
            debits = [r for r in quota_rows(rig) if r["record_type"] == "quota_billable_call"]
            self.assertEqual(len(debits), 1)
            self.assertEqual((debits[0]["billable_units"], debits[0]["daily_used"]), (3, 3))
            self.assertEqual(rows_of(rig, "acq_quota_decided")[0]["genesis_units_debited"], 3)
            self.assertEqual(rows_of(rig, "acq_planned")[0]["provider_request_weight"], 2)
            body = json.loads((sup.CONFIG / "oddspapi_v4_endpoints.json").read_text())
            body["endpoints"][5].update(provider_metering="FIXED_WEIGHT", provider_request_weight=2,
                                        genesis_debit_units=1)
            with self.assertRaises(ep.SpecError):
                ep.parse_endpoints(body, rig.policy)

    def test_bill03_variable_and_unknown_metering_roles_are_refused_and_never_sent(self):
        for metering in (ep.Metering.VARIABLE, ep.Metering.UNKNOWN):
            with self.subTest(metering), scratch_root() as root:
                rig = build_rig(root)
                spec = dataclasses.replace(rig.specs["ODDS"], provider_metering=metering,
                                           provider_request_weight=None,
                                           provider_documented_billable=None)
                rig.runner.config.endpoints["ODDS"] = spec
                outcome = rig.runner.acquire(odds_item(window="v", specs=rig.specs))
                self.assertEqual(outcome.outcome, "REFUSED")
                self.assertEqual(outcome.failure, err.AdapterFailure.ROLE_NOT_USABLE)
                self.assertEqual(rig.transport.calls, [])
                self.assertEqual(quota_rows(rig), [])
                self.assertEqual(kinds(rig), ["acq_planned", "acq_refused"])
                with self.assertRaises(ep.RoleNotUsable):
                    acq.validate_plan_item(odds_item(window="v", specs=rig.specs), rig.runner.config)


class RetryPolicyTests(unittest.TestCase):
    def setUp(self):
        from genesis_adapters.config import load_policy
        self.policy = load_policy(sup.CONFIG / "oddspapi_slice1_policy.json")
        self.failed = "2026-10-01T12:00:00.000000Z"
        self.backoff = self.policy.retry_min_backoff_seconds

    def decide(self, **over):
        args = dict(outcome="NO_RESPONSE", http_status=None, failure=err.AdapterFailure.NO_RESPONSE,
                    attempt=1, policy=self.policy, failed_at=self.failed,
                    now="2026-10-01T12:10:00.000000Z", not_after=None, quota_headroom=True,
                    circuit_open=False)
        args.update(over)
        return acq.retry_decision(**args)

    def test_q05_only_no_response_and_5xx_are_retryable(self):
        yes = [dict(outcome="NO_RESPONSE", http_status=None, failure=err.AdapterFailure.NO_RESPONSE),
               dict(outcome="RESPONSE", http_status=500, failure=err.AdapterFailure.PROVIDER_ERROR),
               dict(outcome="RESPONSE", http_status=503, failure=err.AdapterFailure.PROVIDER_ERROR),
               dict(outcome="RESPONSE", http_status=599, failure=err.AdapterFailure.PROVIDER_ERROR),
              dict(outcome="ORPHANED", http_status=None, failure=err.AdapterFailure.ORPHANED_RESERVATION)]
        no = [dict(outcome="ORPHANED", http_status=None, failure=None),
              dict(outcome="RESPONSE", http_status=200, failure=None),
              dict(outcome="RESPONSE", http_status=301, failure=err.AdapterFailure.REDIRECT_REFUSED),
              dict(outcome="RESPONSE", http_status=302, failure=err.AdapterFailure.REDIRECT_REFUSED),
              dict(outcome="RESPONSE", http_status=400, failure=err.AdapterFailure.PROVIDER_ERROR),
              dict(outcome="RESPONSE", http_status=404, failure=err.AdapterFailure.PROVIDER_ERROR),
              dict(outcome="RESPONSE", http_status=401, failure=err.AdapterFailure.AUTH_REJECTED),
              dict(outcome="RESPONSE", http_status=403, failure=err.AdapterFailure.AUTH_REJECTED),
              dict(outcome="RESPONSE", http_status=429, failure=err.AdapterFailure.RATE_LIMITED),
              dict(outcome="TRUNCATED", http_status=200, failure=err.AdapterFailure.TRUNCATED_BODY),
              dict(outcome="RESPONSE", http_status=200, failure=err.AdapterFailure.SCHEMA_DRIFT),
              dict(outcome="RESPONSE", http_status=200, failure=err.AdapterFailure.NOT_JSON),
              dict(outcome="RESPONSE", http_status=200, failure=err.AdapterFailure.SECRET_ECHO),
              dict(outcome="RESPONSE", http_status=200, failure=err.AdapterFailure.CLOCK_SKEW),
              dict(outcome="REFUSED", http_status=None, failure=err.AdapterFailure.WINDOW_BOUNDARY_GUARD),
              dict(outcome="QUOTA_BLOCKED", http_status=None, failure=err.AdapterFailure.QUOTA_BLOCKED)]
        for case in yes:
            self.assertTrue(self.decide(**case).retry, case)
        for case in no:
            decision = self.decide(**case)
            self.assertFalse(decision.retry, case)
            self.assertTrue(decision.reason)

    def at(self, *, seconds: int = 0, micros: int = 0) -> str:
        base = datetime.fromisoformat(self.failed[:-1] + "+00:00")
        moment = base + timedelta(seconds=seconds, microseconds=micros)
        return moment.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def test_q05_attempt_limit_backoff_window_headroom_and_circuit(self):
        limit = self.policy.max_retries_per_window
        self.assertTrue(self.decide(attempt=limit).retry)              # the last permitted retry
        self.assertFalse(self.decide(attempt=limit + 1).retry)
        edge = self.at(seconds=self.backoff)
        early = self.decide(now=self.at(seconds=self.backoff, micros=-1))
        self.assertFalse(early.retry)
        self.assertEqual(early.earliest, edge)
        self.assertTrue(self.decide(now=edge).retry)
        self.assertTrue(self.decide(now=edge, not_after=self.at(seconds=self.backoff, micros=1)).retry)
        self.assertFalse(self.decide(now=edge, not_after=edge).retry)
        self.assertFalse(self.decide(quota_headroom=False).retry)
        self.assertFalse(self.decide(circuit_open=True).retry)

    def test_q05_zero_retries_configured_means_never(self):
        body = json.loads((sup.CONFIG / "oddspapi_slice1_policy.json").read_text())
        body["max_retries_per_window"] = 0
        from genesis_adapters.config import parse_policy
        self.assertFalse(acq.retry_decision(
            outcome="NO_RESPONSE", http_status=None, failure=err.AdapterFailure.NO_RESPONSE, attempt=1,
            policy=parse_policy(body), failed_at=self.failed, now=self.at(seconds=self.backoff * 100),
            not_after=None, quota_headroom=True, circuit_open=False).retry)


class CrashAndRestartTests(unittest.TestCase):
    def crash_at(self, step: str):
        def hook(name):
            if name == step:
                raise Crash()
        return hook

    def test_q06_crash_after_send_becomes_an_orphaned_reservation_and_is_never_resent(self):
        with scratch_root() as root:
            rig = build_rig(root, script=[crash()])
            item = odds_item()
            with self.assertRaises(Crash):
                rig.runner.acquire(item)
            aid = acquisition_id(item.request.provider_request_hash, "w1", 1)
            self.assertEqual(kinds(rig, aid), ["acq_planned", "acq_quota_decided", "acq_sent"])
            before = quota_rows(rig)
            self.assertEqual(len(before), 1)
            fresh = build_rig(root, transport=sup.FakeTransport(), quota_ledger=rig.quota_ledger,
                              cache=rig.cache, clock=FixedClock("2026-10-01T12:05:00.000000Z", step_micros=1000))
            reconciled = fresh.runner.reconcile_after_restart()
            self.assertEqual(reconciled, (aid,))
            row = rows_of(fresh, "acq_reconciled")[0]
            self.assertEqual((row["outcome"], row["quota_row_found"], row["send_state"]),
                             ("ORPHANED_RESERVATION", True, "MAY_HAVE_BEEN_SENT"))
            self.assertEqual(quota_rows(fresh), before)                       # the debit stands
            again = fresh.runner.acquire(item)                                  # same plan item
            self.assertEqual(again.outcome, "REFUSED")
            self.assertEqual(again.failure, err.AdapterFailure.ORPHANED_RESERVATION)
            self.assertEqual(again.detail, "MAY_HAVE_BEEN_SENT")
            self.assertEqual(fresh.transport.calls, [])                        # never re-sent
            self.assertEqual(quota_rows(fresh), before)
            self.assertEqual(fresh.runner.reconcile_after_restart(), ())        # idempotent

    def test_f35_orphan_coverage_is_missing_evidence(self):
        with scratch_root() as root:
            rig = build_rig(root, script=[crash()])
            with self.assertRaises(Crash):
                rig.runner.acquire(odds_item())
            fresh = build_rig(root, quota_ledger=rig.quota_ledger, cache=rig.cache,
                              clock=FixedClock("2026-10-01T12:05:00.000000Z", step_micros=1000))
            fresh.runner.reconcile_after_restart()
            entries = coverage(fresh)
            self.assertEqual([(e["status"], e["reason_codes"], e["note"]) for e in entries],
                             [("missing", ["missing_evidence"], "ORPHANED_RESERVATION")])

    def test_q06_same_request_id_with_a_new_time_makes_the_frozen_ledger_halt(self):
        with scratch_root() as root:
            rig = build_rig(root)
            item = odds_item()
            rig.runner.acquire(item)
            aid = acquisition_id(item.request.provider_request_hash, "w1", 1)
            spec = rig.specs["ODDS"]
            with self.assertRaises(RegistryConflict):
                rig.gate.reserve(request=item.request, request_id=f"oddspapi-attempt:{aid}",
                                 occurred_at="2026-10-01T12:30:00.000000Z",
                                 billable_units=spec.genesis_debit_units)

    def test_crash_points_before_and_after_the_quota_row(self):
        # ``acq_sent`` is durable before the transport is called: no sent row => never handed to it
        for step, expected_kinds, quota_count, found, send_state in (
                ("before_quota", ["acq_planned"], 0, False, "NOT_SENT"),
                ("after_quota", ["acq_planned"], 1, True, "NOT_SENT"),
                ("after_quota_decided", ["acq_planned", "acq_quota_decided"], 1, True, "NOT_SENT"),
                ("after_sent", ["acq_planned", "acq_quota_decided", "acq_sent"], 1, True,
                 "MAY_HAVE_BEEN_SENT")):
            with self.subTest(step), scratch_root() as root:
                rig = build_rig(root, checkpoint=self.crash_at(step))
                item = odds_item()
                with self.assertRaises(Crash):
                    rig.runner.acquire(item)
                aid = acquisition_id(item.request.provider_request_hash, "w1", 1)
                self.assertEqual(kinds(rig, aid), expected_kinds)
                self.assertEqual(len(quota_rows(rig)), quota_count)
                fresh = build_rig(root, quota_ledger=rig.quota_ledger, cache=rig.cache,
                                  clock=FixedClock("2026-10-01T12:05:00.000000Z", step_micros=1000))
                fresh.runner.reconcile_after_restart()
                row = rows_of(fresh, "acq_reconciled")[0]
                self.assertEqual(row["quota_row_found"], found)
                self.assertEqual(row["outcome"], "ORPHANED_RESERVATION" if found else "NOT_RESERVED")
                self.assertEqual(row["send_state"], send_state)
                self.assertEqual(len(quota_rows(fresh)), quota_count)
                self.assertEqual(fresh.transport.calls, [])

    def test_a2_reconciliation_rows_cannot_contradict_the_durable_sent_row(self):
        with scratch_root() as root:
            rig = build_rig(root, checkpoint=self.crash_at("after_quota_decided"))
            with self.assertRaises(Crash):
                rig.runner.acquire(odds_item())
            aid = acquisition_id(odds_item().request.provider_request_hash, "w1", 1)
            base = dict(acquisition_id=aid, outcome="ORPHANED_RESERVATION", quota_row_found=True,
                        recorded_at="2026-10-01T12:06:00.000000Z", record_type="acq_reconciled",
                        schema_version=acq.SCHEMA_VERSION)
            rows = read_jsonl(rig.acq_path)
            for bad in (dict(send_state="MAY_HAVE_BEEN_SENT"),      # claims a send no sent row proves
                        dict(send_state="SOMETIMES"), dict(send_state=None)):
                with self.subTest(bad), self.assertRaises(acq.LedgerInvariantError):
                    acq._replay([{k: v for k, v in r.items() if k not in ("previous_hash", "sequence",
                                                                            "record_hash")} for r in rows]
                                + [{**base, **bad}])
            good = {**base, "send_state": "NOT_SENT"}
            acq._replay([{k: v for k, v in r.items() if k not in ("previous_hash", "sequence", "record_hash")}
                         for r in rows] + [good])

    def test_a2_a_reconciled_orphan_is_retried_only_under_a_fresh_identity_and_debit(self):
        for step, send_state in (("after_quota_decided", "NOT_SENT"), ("after_sent", "MAY_HAVE_BEEN_SENT")):
            with self.subTest(step), scratch_root() as root:
                rig = build_rig(root, checkpoint=self.crash_at(step))
                first = odds_item(window="w1")
                with self.assertRaises(Crash):
                    rig.runner.acquire(first)
                fresh = build_rig(root, script=[ok()], quota_ledger=rig.quota_ledger, cache=rig.cache,
                                  clock=FixedClock("2026-10-01T12:05:00.000000Z", step_micros=1000))
                fresh.runner.reconcile_after_restart()
                row = rows_of(fresh, "acq_reconciled")[0]
                self.assertEqual(row["send_state"], send_state)
                debits_before = [r for r in quota_rows(fresh) if r["record_type"] == "quota_billable_call"]
                self.assertEqual(len(debits_before), 1)
                # the orphan itself is terminal: the same identity is never re-sent or re-debited
                again = fresh.runner.acquire(first)
                self.assertEqual((again.outcome, again.failure, again.detail),
                                 ("REFUSED", err.AdapterFailure.ORPHANED_RESERVATION, send_state))
                self.assertEqual(fresh.transport.calls, [])
                # the retry policy treats it like a no-response attempt: one more attempt is allowed
                earliest = iso_utc(parse_utc(row["recorded_at"])
                                   + timedelta(seconds=fresh.policy.retry_min_backoff_seconds))
                decision = acq.retry_decision(
                    outcome=acq.AttemptOutcome.ORPHANED, http_status=None,
                    failure=err.AdapterFailure.ORPHANED_RESERVATION, attempt=1, policy=fresh.policy,
                    failed_at=row["recorded_at"], now=earliest,
                    not_after=None, quota_headroom=True, circuit_open=False)
                self.assertTrue(decision.retry, decision)
                self.assertEqual(decision.earliest, earliest)
                fresh.clock.set(decision.earliest)
                retry = odds_item(window="w1", attempt=2, purpose="RETRY")
                second = fresh.runner.acquire(retry)
                self.assertIsNone(second.failure)
                self.assertNotEqual(second.acquisition_id, again.acquisition_id)
                self.assertEqual(second.acquisition_id,
                                 acquisition_id(retry.request.provider_request_hash, "w1", 2))
                debits = [r for r in quota_rows(fresh) if r["record_type"] == "quota_billable_call"]
                self.assertEqual(len(debits), 2)                           # the old debit stands; a new one
                self.assertNotEqual(debits[0]["request_id"], debits[1]["request_id"])
                self.assertEqual(len(fresh.transport.calls), 1)            # only the retry went out


class ClockTests(unittest.TestCase):
    def test_q07_clock_behind_the_ledger_head_is_a_clock_fault_halt(self):
        with scratch_root() as root:
            rig = build_rig(root, clock=FixedClock(BASE, step_micros=1000))
            rig.runner.acquire(odds_item(window="w1"))
            behind = build_rig(root, quota_ledger=rig.quota_ledger, cache=rig.cache,
                               clock=FixedClock("2026-10-01T11:00:00.000000Z", step_micros=1000))
            quota_before = quota_rows(behind)
            with self.assertRaises(err.AcquisitionHalt) as caught:
                behind.runner.acquire(odds_item(window="w2"))
            self.assertEqual(caught.exception.code, err.AdapterFailure.CLOCK_FAULT)
            self.assertEqual(behind.transport.calls, [])
            self.assertEqual(quota_rows(behind), quota_before)
            self.assertEqual(kinds(behind)[-3:], ["acq_planned", "acq_refused", "acq_halted"])
            refused = rows_of(behind, "acq_refused")[-1]
            self.assertEqual(refused["reason"], "CLOCK_FAULT")
            self.assertEqual(rows_of(behind, "acq_halted")[-1]["reason"], "CLOCK_FAULT")
            last = coverage(behind)[-1]
            self.assertEqual((last["status"], last["reason_codes"], last["note"]),
                             ("not_attempted", ["configuration_mismatch"], "CLOCK_FAULT"))
            # the halt is durable: the next call is refused by the breaker, not re-evaluated
            after = behind.runner.acquire(odds_item(window="w3"))
            self.assertEqual(after.failure, err.AdapterFailure.CIRCUIT_OPEN)

    def test_f03_quota_time_regression_reported_by_the_frozen_ledger_halts(self):
        from genesis_adapters.oddspapi.quota_gate import QuotaCharge

        class Regressed:
            def __init__(self, inner):
                self.inner = inner
                self.ledger = inner.ledger

            def reserve(self, *, request, request_id, occurred_at, billable_units):
                return QuotaCharge(request_id, "quota_event_time_regressed", False, 0, 0, 0, 0, 0, None,
                                   None)

            def find_request(self, request_id):
                return self.inner.find_request(request_id)

            def head_time(self):
                return None

            def headroom(self, at, units):
                return True

        with scratch_root() as root:
            rig = build_rig(root)
            rig.runner.quota = Regressed(rig.gate)
            with self.assertRaises(err.AcquisitionHalt) as caught:
                rig.runner.acquire(odds_item())
            self.assertEqual(caught.exception.code, err.AdapterFailure.CLOCK_FAULT)
            self.assertEqual(rig.transport.calls, [])
            self.assertEqual(rows_of(rig, "acq_halted")[-1]["reason"], "CLOCK_FAULT")
            last = coverage(rig)[-1]
            self.assertEqual((last["status"], last["reason_codes"], last["note"]),
                             ("not_attempted", ["configuration_mismatch"], "CLOCK_FAULT"))

    def test_clk03_replay_rejects_rows_that_violate_the_time_ordering(self):
        with scratch_root() as root:
            ledger = acq.AcquisitionLedger(root / "acquisition.jsonl")
            base = dict(request_id="oddspapi-attempt:" + "a" * 64, window_id="w", purpose="SCHEDULED",
                        attempt=1, provider_request_hash="b" * 64, role="ODDS",
                        provider_metering="PER_REQUEST", provider_request_weight=1,
                        provider_documented_billable=True, genesis_debit_units=1)
            aid = "a" * 64
            ledger.append("acq_planned", acquisition_id=aid, recorded_at=BASE, **base)
            ledger.append("acq_quota_decided", acquisition_id=aid, Tq=BASE,
                          frozen_ledger_reason="billable_call_reserved", allowed=True,
                          genesis_units_debited=1, cache_entry_id=None, cache_miss_reason=None,
                          recorded_at=BASE)
            with self.assertRaises(RegistryConflict):                      # T0 < Tq
                ledger.append("acq_sent", acquisition_id=aid, T0="2026-10-01T11:59:59.999999Z",
                              recorded_at="2026-10-01T12:00:00.000001Z")
            ledger.append("acq_sent", acquisition_id=aid, T0="2026-10-01T12:00:00.000001Z",
                          recorded_at="2026-10-01T12:00:00.000001Z")
            completed = dict(acquisition_id=aid, outcome="RESPONSE", http_status=200, headers=[],
                             content_encoding=None, byte_length=2, raw_observation_id=None,
                             sanitized_error=None, provider_reported_usage=None, failure=None)
            for t1 in ("2026-10-01T12:00:00.000001Z", "2026-10-01T12:00:00.000000Z"):
                with self.assertRaises(RegistryConflict):                  # T1 must be > T0
                    ledger.append("acq_completed", T1=t1, recorded_at="2026-10-01T12:00:00.000002Z",
                                  **completed)
            with self.assertRaises(RegistryConflict):                      # recorded_at regresses
                ledger.append("acq_completed", T1="2026-10-01T12:00:00.000003Z",
                              recorded_at="2026-10-01T12:00:00.000000Z", **completed)
            ledger.append("acq_completed", T1="2026-10-01T12:00:00.000003Z",
                          recorded_at="2026-10-01T12:00:00.000003Z", **completed)
            normalized = dict(acquisition_id=aid, derivation_version="mb1-0000000000000000",
                              expected_scope_hash=None,
                              identity_registry_head={"sequence": 0, "record_hash": "0" * 64},
                              normalized_observation_ids=[], pit_record_ids=[], coverage_entry_ids=[])
            for t2, t3 in (("2026-10-01T12:00:00.000002Z", "2026-10-01T12:00:00.000004Z"),   # T2 < T1
                           ("2026-10-01T12:00:00.000005Z", "2026-10-01T12:00:00.000004Z")):  # T3 < T2
                with self.assertRaises(RegistryConflict):
                    ledger.append("acq_normalized", T2=t2, T3=t3,
                                  recorded_at="2026-10-01T12:00:00.000006Z", **normalized)
            ledger.append("acq_normalized", T2="2026-10-01T12:00:00.000004Z",
                          T3="2026-10-01T12:00:00.000004Z", recorded_at="2026-10-01T12:00:00.000006Z",
                          **normalized)

    def test_ledger_state_machine_and_closed_keys(self):
        with scratch_root() as root:
            ledger = acq.AcquisitionLedger(root / "acquisition.jsonl")
            aid = "c" * 64
            with self.assertRaises(RegistryConflict):                      # sent without a quota decision
                ledger.append("acq_sent", acquisition_id=aid, T0=BASE, recorded_at=BASE)
            planned = dict(acquisition_id=aid, request_id="oddspapi-attempt:" + aid, window_id="w",
                           purpose="SCHEDULED", attempt=1, provider_request_hash="d" * 64, role="ODDS",
                           provider_metering="PER_REQUEST", provider_request_weight=1,
                           provider_documented_billable=True, genesis_debit_units=1, recorded_at=BASE)
            with self.assertRaises(RegistryConflict):                      # unknown extra key
                ledger.append("acq_planned", surprise=1, **planned)
            with self.assertRaises(RegistryConflict):                      # missing key
                ledger.append("acq_planned", **{k: v for k, v in planned.items() if k != "role"})
            with self.assertRaises(RegistryConflict):                      # unknown record type
                ledger.append("acq_unknown", acquisition_id=aid, recorded_at=BASE)
            ledger.append("acq_planned", **planned)
            with self.assertRaises(RegistryConflict):                      # duplicate planned
                ledger.append("acq_planned", **planned)
            blocked = dict(acquisition_id=aid, Tq=BASE, frozen_ledger_reason="daily_quota_exhausted",
                           allowed=False, genesis_units_debited=0, cache_entry_id=None,
                           cache_miss_reason=None, recorded_at=BASE)
            ledger.append("acq_quota_decided", **blocked)
            with self.assertRaises(RegistryConflict):                      # blocked is terminal
                ledger.append("acq_sent", acquisition_id=aid, T0=BASE, recorded_at=BASE)


class RefusalTests(unittest.TestCase):
    def assert_refused(self, rig, outcome, failure):
        self.assertEqual(outcome.outcome, "REFUSED")
        self.assertEqual(outcome.failure, failure)
        self.assertEqual(rig.transport.calls, [])
        self.assertEqual(quota_rows(rig), [])
        self.assertEqual(kinds(rig)[-2:], ["acq_planned", "acq_refused"])
        self.assertEqual(rows_of(rig, "acq_refused")[-1]["reason"], failure.value)
        entry = coverage(rig)[-1]
        self.assertEqual((entry["status"], entry["reason_codes"], entry["note"]),
                         ("not_attempted", ["configuration_mismatch"], failure.value))
        self.assertTrue(entry["entity_id"].startswith("oddspapi-request:"))

    def test_f01_live_mode_refuses_a_non_system_clock(self):
        with scratch_root() as root:
            rig = build_rig(root, live=True, clock=FixedClock(BASE, step_micros=1000))
            self.assert_refused(rig, rig.runner.acquire(odds_item()), err.AdapterFailure.LIVE_CLOCK_REQUIRED)

    def test_f01_live_mode_refuses_a_test_quota_policy(self):
        with scratch_root() as root:
            clock = SystemUtcClock(drift_max_ms=1000)
            rig = build_rig(root, live=True, clock=clock)
            self.assert_refused(rig, rig.runner.acquire(odds_item()), err.AdapterFailure.TEST_POLICY_IN_LIVE)

    def test_f01_live_mode_refuses_when_the_gate_record_is_missing(self):
        class NoGate:
            def require_gate(self, gate, *, at, **pins):
                raise err.GateMissing(gate)

        from genesis_adapters.oddspapi.quota_gate import open_operational_ledger
        with scratch_root() as root:
            ledger, cache = open_operational_ledger(root)
            rig = build_rig(root, live=True, clock=SystemUtcClock(drift_max_ms=1000), quota_ledger=ledger,
                            cache=cache, authority=NoGate())
            self.assert_refused(rig, rig.runner.acquire(odds_item()), err.AdapterFailure.GATE_MISSING)

    def test_f01_an_open_circuit_refuses_before_any_quota_call(self):
        with scratch_root() as root:
            rig = build_rig(root, script=[status(401)])
            rig.runner.acquire(odds_item(window="w1"))                       # opens the circuit
            quota_before = quota_rows(rig)
            outcome = rig.runner.acquire(odds_item(window="w2"))
            self.assertEqual(outcome.failure, err.AdapterFailure.CIRCUIT_OPEN)
            self.assertEqual(len(rig.transport.calls), 1)
            self.assertEqual(quota_rows(rig), quota_before)

    def test_f04_credential_problems_refuse_and_halt(self):
        for code in ("CREDENTIAL_MISSING", "CREDENTIAL_PERMISSIONS", "CREDENTIAL_FINGERPRINT_MISMATCH"):
            with self.subTest(code), scratch_root() as root:
                def check(code=code):
                    raise err.CredentialProblem(code)

                rig = build_rig(root, credential_check=check)
                with self.assertRaises(err.AcquisitionHalt) as caught:
                    rig.runner.acquire(odds_item())
                self.assertEqual(caught.exception.code, err.AdapterFailure(code))
                self.assertEqual(rig.transport.calls, [])
                self.assertEqual(quota_rows(rig), [])                        # checked BEFORE any debit
                self.assertEqual(rows_of(rig, "acq_refused")[-1]["reason"], code)
                self.assertEqual(rows_of(rig, "acq_halted")[-1]["reason"], code)
                entry = coverage(rig)[-1]
                self.assertEqual((entry["status"], entry["reason_codes"], entry["note"]),
                                 ("not_attempted", ["configuration_mismatch"], code))


class HttpFailureTests(unittest.TestCase):
    def cov(self, rig):
        entry = coverage(rig)[-1]
        return entry["status"], entry["reason_codes"], entry["note"]

    def test_f05_no_response_keeps_the_debit_and_is_missing_evidence(self):
        with scratch_root() as root:
            rig = build_rig(root, script=[no_response("ConnectionResetError", 104)])
            outcome = rig.runner.acquire(odds_item())
            self.assertEqual((outcome.outcome, outcome.failure),
                             ("NO_RESPONSE", err.AdapterFailure.NO_RESPONSE))
            self.assertEqual(len(quota_rows(rig)), 1)
            done = rows_of(rig, "acq_completed")[0]
            self.assertEqual(done["sanitized_error"], {"class": "ConnectionResetError", "errno": 104})
            self.assertIsNone(done["T1"])
            self.assertIsNone(done["http_status"])
            self.assertEqual(self.cov(rig), ("missing", ["missing_evidence"], "NO_RESPONSE"))

    def test_f07_redirects_are_refused_never_followed(self):
        with scratch_root() as root:
            rig = build_rig(root, script=[status(302, headers=(("location", "https://elsewhere.example/x"),))])
            outcome = rig.runner.acquire(odds_item())
            self.assertEqual(outcome.failure, err.AdapterFailure.REDIRECT_REFUSED)
            self.assertEqual(len(rig.transport.calls), 1)
            self.assertEqual(self.cov(rig), ("rejected", ["source_contract_violation"], "REDIRECT_REFUSED"))
            self.assertEqual(len(quota_rows(rig)), 1)

    def test_f08_auth_failures_open_the_circuit_for_all_roles_and_block_capabilities(self):
        for code in (401, 403):
            with self.subTest(code), scratch_root() as root:
                blocked = []
                rig = build_rig(root, script=[status(code)], capability_blocker=blocked.append)
                outcome = rig.runner.acquire(odds_item())
                self.assertEqual(outcome.failure, err.AdapterFailure.AUTH_REJECTED)
                self.assertEqual(self.cov(rig), ("rejected", ["configuration_mismatch"], "AUTH_REJECTED"))
                circuit = rows_of(rig, "acq_circuit_opened")
                self.assertEqual(len(circuit), 1)
                self.assertEqual((circuit[0]["scope"], circuit[0]["role"], circuit[0]["until"],
                                  circuit[0]["reason"]), ("ALL", None, None, "AUTH_REJECTED"))
                self.assertEqual(blocked, ["AUTH_REJECTED"])
                for role_item in (odds_item(window="w2"), meta_item()):
                    again = rig.runner.acquire(role_item)
                    self.assertEqual(again.failure, err.AdapterFailure.CIRCUIT_OPEN)
                self.assertEqual(len(rig.transport.calls), 1)

    def test_f09_429_opens_the_role_circuit_until_the_next_utc_day(self):
        with scratch_root() as root:
            rig = build_rig(root, script=[status(429, headers=(("retry-after", "30"),)), ok(), ok(), ok()],
                            clock=FixedClock(BASE, step_micros=1000))
            first = rig.runner.acquire(odds_item(window="w1"))
            self.assertEqual(first.failure, err.AdapterFailure.RATE_LIMITED)
            self.assertEqual(self.cov(rig), ("not_attempted", ["attempt_budget_exhausted"], "RATE_LIMITED"))
            circuit = rows_of(rig, "acq_circuit_opened")[0]
            self.assertEqual((circuit["scope"], circuit["role"], circuit["until"]),
                             ("ROLE", "ODDS", "2026-10-02T00:00:00.000000Z"))
            self.assertEqual(rig.runner.acquire(odds_item(window="w2")).failure,
                             err.AdapterFailure.CIRCUIT_OPEN)
            other_role = rig.runner.acquire(meta_item())                    # another role is unaffected
            self.assertIsNone(other_role.failure)
            rig.clock.set("2026-10-02T09:00:00.000000Z")                    # next UTC day
            self.assertIsNone(rig.runner.acquire(odds_item(window="w3")).failure)

    def test_f09_two_429s_in_one_utc_day_open_every_role_until_the_next_day(self):
        with scratch_root() as root:
            rig = build_rig(root, script=[status(429), status(429), ok()],
                            clock=FixedClock(BASE, step_micros=1000))
            rig.runner.acquire(odds_item(window="w1"))
            rig.runner.acquire(meta_item())                                   # different role: allowed once
            circuits = rows_of(rig, "acq_circuit_opened")
            self.assertEqual([(c["scope"], c["role"]) for c in circuits], [("ROLE", "ODDS"),
                                                                            ("ALL", None)])
            self.assertEqual(circuits[1]["until"], "2026-10-02T00:00:00.000000Z")
            self.assertEqual(rig.runner.acquire(meta_item("META_MARKETS")).failure,
                             err.AdapterFailure.CIRCUIT_OPEN)
            rig.clock.set("2026-10-02T09:00:00.000000Z")
            self.assertIsNone(rig.runner.acquire(meta_item("META_MARKETS", window="wm-next-day")).failure)

    def test_f10_server_and_client_errors_are_provider_errors(self):
        for code in (500, 503, 400, 404, 201):
            with self.subTest(code), scratch_root() as root:
                rig = build_rig(root, script=[status(code)])
                outcome = rig.runner.acquire(odds_item())
                self.assertEqual(outcome.failure, err.AdapterFailure.PROVIDER_ERROR, code)
                self.assertEqual(self.cov(rig), ("missing", ["missing_evidence"], "PROVIDER_ERROR"))
                self.assertEqual(len(quota_rows(rig)), 1)
                self.assertEqual(rows_of(rig, "acq_circuit_opened"), [])

    def test_f06_partial_body_is_recorded_as_truncated(self):
        with scratch_root() as root:
            rig = build_rig(root, script=[truncated(b"[1,")])
            outcome = rig.runner.acquire(odds_item())
            self.assertEqual((outcome.outcome, outcome.failure),
                             ("TRUNCATED", err.AdapterFailure.TRUNCATED_BODY))
            self.assertEqual(rows_of(rig, "acq_completed")[0]["outcome"], "TRUNCATED")
            self.assertEqual(self.cov(rig), ("rejected", ["schema_rejected"], "TRUNCATED_BODY"))


class CredentialHygieneTests(unittest.TestCase):
    def test_req06_an_exception_naming_the_keyed_url_leaves_only_class_and_errno(self):
        from genesis_adapters import secrets as sec
        from genesis_adapters.config import load_policy

        class Leaky(OSError):
            pass

        error = Leaky(104, SECRET_URL)
        error.filename = SECRET_URL
        error.url = SECRET_URL
        error.add_note(SECRET_URL)
        error.__cause__ = ValueError(SECRET_URL)
        with scratch_root() as root:
            rig = build_rig(root, script=[raises(error)])
            outcome = rig.runner.acquire(odds_item())
            self.assertEqual(outcome.failure, err.AdapterFailure.NO_RESPONSE)
            done = rows_of(rig, "acq_completed")[0]
            self.assertEqual(done["sanitized_error"], {"class": "Leaky", "errno": 104})
            secret = sec.Secret(sup.SENTINEL_KEY)
            policy = load_policy(sup.CONFIG / "oddspapi_slice1_policy.json")
            from genesis_adapters.oddspapi import verify
            self.assertEqual(verify.scan_runtime_for_secret(root, secret, policy=policy), ())


if __name__ == "__main__":
    unittest.main()
