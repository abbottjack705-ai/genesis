"""R3 - acquisition state across crash and restart (controlling hostile audit hostile_audit_cfcff3d).

HA-04 (11.1, 14.4, 15 F-11/F-12/F-13): every content verdict of a response is decided BEFORE its attempt completes
    and is durable in the ``acq_completed`` row itself, so no resume path can treat a rejected response as a
    successful capture. A crash after ANY durable write that follows the completed row converges, on restart, to the
    durable history of an uninterrupted run: quarantine, suspension, halt, circuit, capability block, coverage and
    cache publication are completed idempotently before anything else can happen.
HA-09 (14.6 rule 5): after CLOCK_SKEW every ordinary send stays refused until the next UTC day AND a durable clean
    ``Date`` check; that check comes only from an explicit clock-check probe that passes every gate and is debited.
    The date alone never re-arms sends, and neither does an operator reset.
HA-10 (14.3): the production runner (and so the CLI) enforces the retry state machine against durable state:
    attempt sequencing, the RETRY purpose, a retryable prior outcome, max attempts, backoff, the window and quota
    headroom. A refused retry leaves nothing durable: no row, no debit, no send.
HA-11 (12.4): the expected scope of an ODDS request is computed at Tq and written immutably BEFORE the send, its
    hash on the ``acq_sent`` row; normalization and resume use exactly that scope, whatever the PIT log says later.

No failure message of these tests prints a form of the (public, test-only) sentinel.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from genesis.coverage import CoverageLedger
from genesis.pit import OperationalStatus, SourceCapabilityRegistry
from genesis.quota import VerifiedCacheStore
from genesis.time import iso_utc

from genesis_adapters import cli
from genesis_adapters.clock import ClockFault
from genesis_adapters import errors as err
from genesis_adapters.oddspapi import derivation
from genesis_adapters.oddspapi import scope as scope_mod
from genesis_adapters.oddspapi import transport_http as th
from genesis_adapters.oddspapi.acquisition import AcquisitionLedger
from genesis_adapters.oddspapi.transport import TransportResult
from genesis_adapters.secrets import Secret

from . import parser_support as ps
from .pipeline_support import (
    JSON, SPECS, fixture_body, fixtures_item, later_than, odds_item, odds_response, open_rt, pit_rows, reopen,
)
from .support import (
    CONFIG, SENTINEL_KEY, Crash, FixedClock, build_rig, http_date, no_response, ok, read_jsonl, scratch_root, status,
    test_quota_policy,
)
from .support import odds_item as rig_item

F = err.AdapterFailure
_VOLATILE = frozenset({"recorded_at", "previous_hash", "sequence", "record_hash"})


def strip(row: dict) -> dict:
    return {key: value for key, value in row.items() if key not in _VOLATILE}


def dated(offset_seconds: int, response=None):
    """A scripted response whose ``Date`` header is the transport clock plus ``offset_seconds``."""

    def step(clock):
        headers = JSON + (("date", http_date(ps.iso_add(clock.peek(), seconds=offset_seconds))),)
        return odds_response(headers=headers) if response is None else response(headers)
    return step


def acq_rows(root) -> list[dict]:
    return read_jsonl(root / "acquisition.jsonl")


def rows_of(root, kind: str) -> list[dict]:
    return [row for row in acq_rows(root) if row["record_type"] == kind]


def quota_rows(root) -> list[dict]:
    path = root / "quota" / "ledger.jsonl"
    return read_jsonl(path) if path.exists() else []


def durable_history(rt) -> dict:
    """Everything durable about the attempt, without times and hash-chain fields."""

    root = rt.root

    def rows(name: str) -> list[dict]:
        path = root / name
        return [strip(row) for row in read_jsonl(path)] if path.exists() else []

    capabilities: dict[str, list[str]] = {}                 # every status row: a repeated block would show
    for row in rows("capabilities.jsonl"):
        if row.get("record_type") == "source_capability_registered":
            capabilities.setdefault(row["source_id"], []).append(row["operational_status"])
    return {"acquisition": rows("acquisition.jsonl"), "coverage": rows("coverage.jsonl"),
            "quarantine": rows("quarantine.jsonl"), "capabilities": capabilities,
            "cache": [strip(row) for row in rt.gate.cache.log.records()],
            "cache_index": rows("quota/cache-index.jsonl"), "pit": len(pit_rows(rt)),
            "evidence": sorted(path.name for path in (root / "evidence").rglob("*") if path.is_file())}


class CrashAfterCompleted:
    """Raise ``Crash`` right after the n-th durable write that follows an attempt's ``acq_completed`` row (0: right
    after the completed row itself). Durable writes: acquisition rows, coverage entries, capability rows and cache
    entries. ``n=None`` only counts."""

    def __init__(self, n: int | None):
        self.n = n
        self.after: int | None = None
        self.crashed = False

    def _seen(self, kind: str) -> None:
        if self.after is None:
            if kind != "acq_completed":
                return
            self.after = 0
        else:
            self.after += 1
        if self.n is not None and not self.crashed and self.after == self.n:
            self.crashed = True
            raise Crash()

    def _wrap(self, owner, name, kind_of):
        real = getattr(owner, name)
        counter = self

        def wrapped(obj, *args, **kwargs):
            result = real(obj, *args, **kwargs)
            counter._seen(kind_of(args))
            return result
        return mock.patch.object(owner, name, wrapped)

    @contextlib.contextmanager
    def active(self):
        with self._wrap(AcquisitionLedger, "append", lambda args: args[0]), \
                self._wrap(CoverageLedger, "append", lambda args: "coverage"), \
                self._wrap(SourceCapabilityRegistry, "register", lambda args: "capability"), \
                self._wrap(VerifiedCacheStore, "publish", lambda args: "cache"):
            yield self


# ---------------------------------------------------------------------------------------------------------
# HA-04
# ---------------------------------------------------------------------------------------------------------
def rejection_cases():
    skew = ps.POLICY.clock_skew_max_seconds
    echo = b'[{"note": "' + SENTINEL_KEY.encode("ascii") + b'"}]'
    return {
        "wrong content type": (odds_response(headers=(("content-type", "text/plain"),)), {}, F.WRONG_CONTENT_TYPE),
        "not JSON": (ok(b"{not json", headers=JSON), {}, F.NOT_JSON),
        "envelope mismatch": (ok(b'{"not": "a list"}', headers=JSON), {}, F.ENVELOPE_SCHEMA_MISMATCH),
        "unsupported encoding": (ok(b"not-brotli", headers=JSON + (("content-encoding", "br"),)), {},
                                 F.UNINSPECTABLE_BODY),
        "clock skew": (dated(skew + 5), {"require_date": True}, F.CLOCK_SKEW),
        "missing Date (live rule)": (odds_response(), {"require_date": True}, F.CLOCK_SKEW),
        "secret echo": (ok(echo, headers=JSON), {"secret": Secret(SENTINEL_KEY)}, F.SECRET_ECHO),
        "401": (status(401), {}, F.AUTH_REJECTED),
        "429": (status(429), {}, F.RATE_LIMITED),
        "503": (status(503), {}, F.PROVIDER_ERROR),
    }


def follow_up(options: dict):
    return dated(0) if options.get("require_date") else odds_response()


class DurableVerdictTests(unittest.TestCase):
    def acquire(self, rt, item):
        try:
            return rt.acquire(item).outcome
        except err.AcquisitionHalt as halt:
            return halt

    def test_ha04_the_verdict_is_durable_in_the_completed_row_itself(self):
        for label, (step, options, failure) in rejection_cases().items():
            with self.subTest(label), scratch_root() as root:
                rt = open_rt(root, script=[step], **options)
                self.acquire(rt, odds_item())
                completed = rows_of(root, "acq_completed")
                self.assertEqual(len(completed), 1)
                self.assertEqual(completed[0]["failure"], failure.value)

    def test_ha04_a_rejected_response_stays_rejected_across_a_clean_restart(self):
        # the audit's reproduction: no crash at all, just a restart and resume()
        for label, (step, options, failure) in rejection_cases().items():
            with self.subTest(label), scratch_root() as root:
                rt = open_rt(root, script=[step], **options)
                self.acquire(rt, odds_item())
                halts = len(rows_of(root, "acq_halted"))
                restarted = reopen(rt, **options)
                restarted.resume()                                            # neither halts nor normalizes
                self.assertEqual(len(pit_rows(restarted)), 0)
                self.assertEqual(rows_of(root, "acq_normalized"), [])
                self.assertEqual(len(rows_of(root, "acq_halted")), halts)

    def run_case(self, root, step, options, crash_at):
        rt = open_rt(root, script=[step], **options)
        counter = CrashAfterCompleted(crash_at)
        with counter.active():
            try:
                rt.acquire(odds_item())
            except (Crash, err.AcquisitionHalt):
                pass
        restarted = reopen(rt, script=[follow_up(options)], **options)
        restarted.resume()
        history = durable_history(restarted)
        sends_before = len(restarted.runner.transport.calls)
        after = self.acquire(restarted, odds_item("w2"))
        outcome = (type(after).__name__, getattr(after, "outcome", None),
                   getattr(after, "failure", None) if not isinstance(after, err.AcquisitionHalt) else str(after),
                   getattr(after, "detail", None))
        return counter, history, (outcome, len(restarted.runner.transport.calls) - sends_before)

    def test_ha04_a_crash_after_any_write_following_the_completed_row_converges_to_an_uninterrupted_run(self):
        for label, (step, options, failure) in rejection_cases().items():
            with scratch_root() as root:
                counter, expected, expected_next = self.run_case(root, step, options, None)
            writes = counter.after
            with self.subTest(label, check="the completed row was written"):
                self.assertIsNotNone(writes)
            for crash_at in range(0, (writes or 0) + 1):
                with self.subTest(label, crash_after_write=crash_at), scratch_root() as root:
                    counter, history, following = self.run_case(root, step, options, crash_at)
                    self.assertTrue(counter.crashed, "the crash was not injected")
                    self.assertEqual(history["pit"], 0)                       # never revived
                    if history != expected:
                        differing = sorted(key for key in expected if history.get(key) != expected[key])
                        self.fail(f"restart did not converge: {differing} differ from an uninterrupted run")
                    self.assertEqual(following, expected_next)

    def test_ha04_after_a_crash_following_a_secret_echo_nothing_more_is_sent(self):
        step, options, _ = rejection_cases()["secret echo"]
        with scratch_root() as root:
            _, history, (outcome, sends) = self.run_case(root, step, options, 0)
        self.assertEqual(sends, 0)                                            # the key is never used again
        self.assertEqual(outcome[2], F.CIRCUIT_OPEN)
        self.assertEqual(outcome[3], F.SECRET_ECHO.value)
        self.assertEqual({statuses[-1] for statuses in history["capabilities"].values()},
                         {OperationalStatus.BLOCKED.value})

    def test_ha04_the_next_attempt_settles_the_previous_verdict_first_even_without_a_resume(self):
        step, options, _ = rejection_cases()["secret echo"]
        with scratch_root() as root:
            rt = open_rt(root, script=[step], **options)
            with CrashAfterCompleted(0).active(), self.assertRaises(Crash):
                rt.acquire(odds_item())
            restarted = reopen(rt, script=[odds_response()], **options)     # no resume(): straight to a send
            after = restarted.runner.acquire(odds_item("w2"))
            self.assertEqual((after.failure, after.detail), (F.CIRCUIT_OPEN, F.SECRET_ECHO.value))
            self.assertEqual(restarted.runner.transport.calls, [])
            self.assertEqual([row["reason"] for row in rows_of(root, "acq_halted")], [F.SECRET_ECHO.value])

    def test_ha04_a_settled_capability_block_is_never_applied_again(self):
        # the verdict's block was applied once; a later settle (every acquire) must not undo a human re-approval
        step, options, _ = rejection_cases()["secret echo"]
        with scratch_root() as root:
            rt = open_rt(root, script=[step], **options)
            with self.assertRaises(err.AcquisitionHalt):
                rt.acquire(odds_item())
            from .emit_support import set_capability
            set_capability(rt.stores, OperationalStatus.READY, at=later_than(rt), suffix="re-approved")
            restarted = reopen(rt, script=[odds_response()], **options)
            restarted.acquire(odds_item("w2"))                                # refused by the halt; settles nothing
            statuses = durable_history(restarted)["capabilities"][restarted.stores.source_id]
            self.assertEqual(statuses[-1], OperationalStatus.READY.value)

    def test_ha04_after_a_crash_following_a_clock_skew_sends_stay_suspended(self):
        step, options, _ = rejection_cases()["clock skew"]
        with scratch_root() as root:
            _, history, (outcome, sends) = self.run_case(root, step, options, 0)
        self.assertEqual(sends, 0)
        self.assertEqual(outcome[2], F.CIRCUIT_OPEN)
        self.assertEqual([row["reason"] for row in history["quarantine"]], [F.CLOCK_SKEW.value])

    def test_ha04_a_clock_fault_during_the_exchange_halts_and_converges_after_a_crash(self):
        class OutOfOrder:                                                     # T1 does not follow T0
            def __init__(self):
                self.calls = []

            def send(self, request, *, clock, deadline_at):
                self.calls.append(request.provider_request_hash)
                t0 = clock.now()
                return TransportResult("RESPONSE", 200, JSON, b"[]", None, t0, t0)

        class Faulting(OutOfOrder):                                           # the trusted clock faults mid-send
            def send(self, request, *, clock, deadline_at):
                self.calls.append(request.provider_request_hash)
                raise ClockFault("CLOCK_REGRESSION")

        for label, transport in (("clock order violated", OutOfOrder), ("clock fault in the send", Faulting)):
            with self.subTest(label):
                with scratch_root() as root:
                    rt = open_rt(root, transport=transport())
                    with self.assertRaises(err.AcquisitionHalt) as caught:
                        rt.acquire(odds_item())
                    self.assertEqual(caught.exception.code, F.CLOCK_FAULT)
                    restarted = reopen(rt)
                    restarted.resume()
                    expected = durable_history(restarted)
                halts = [row["reason"] for row in expected["acquisition"] if row["record_type"] == "acq_halted"]
                self.assertEqual(halts, [F.CLOCK_FAULT.value])
                with scratch_root() as root:
                    rt = open_rt(root, transport=transport())
                    with CrashAfterCompleted(0).active(), self.assertRaises(Crash):
                        rt.acquire(odds_item())
                    restarted = reopen(rt)
                    restarted.resume()
                    self.assertEqual(durable_history(restarted), expected)

    def test_ha04_a_rejected_fixtures_capture_is_never_used_for_the_fixture_join(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[ok(fixture_body("fixtures.json"), headers=(("content-type", "text/plain"),))])
            first = rt.acquire(fixtures_item("wf1"))
            self.assertEqual(first.outcome.failure, F.WRONG_CONTENT_TYPE)
            t1 = rows_of(root, "acq_completed")[0]["T1"]
            self.assertIsNone(derivation.fixture_snapshot_for(rt.stores, rt.config, rt.maps,
                                                              at=ps.iso_add(t1, seconds=1)))

    def test_ha04_a_metadata_capture_whose_cache_entry_was_lost_in_a_crash_is_cached_on_restart(self):
        fixtures = ok(fixture_body("fixtures.json"), headers=JSON)
        with scratch_root() as root:
            rt = open_rt(root, script=[fixtures])
            rt.acquire(fixtures_item("wf1"))
            expected = [strip(row) for row in rt.gate.cache.log.records()]
        with scratch_root() as root:
            rt = open_rt(root, script=[fixtures])
            with CrashAfterCompleted(0).active():
                with self.assertRaises(Crash):
                    rt.acquire(fixtures_item("wf1"))
            self.assertEqual(list(rt.gate.cache.log.records()), [])
            restarted = reopen(rt, script=[fixtures])
            restarted.resume()
            self.assertEqual([strip(row) for row in restarted.gate.cache.log.records()], expected)
            again = restarted.acquire(fixtures_item("wf2"))                 # served from the cache, not re-sent
            self.assertEqual(again.outcome.outcome, "CACHE_HIT")
            self.assertEqual(restarted.runner.transport.calls, [])
            self.assertEqual(len(read_jsonl(root / "quota" / "cache-index.jsonl")), 1)   # indexed exactly once
            ttl = restarted.config.policy.cache_ttl_seconds["FIXTURES"]
            restarted.clock.advance(seconds=ttl + 1)                         # past the cache: a genuinely new capture
            fresh = restarted.acquire(fixtures_item("wf3"))
            self.assertEqual(fresh.outcome.outcome, "RESPONSE")
            self.assertEqual(len(read_jsonl(root / "quota" / "cache-index.jsonl")), 2)   # and it is cached too


# ---------------------------------------------------------------------------------------------------------
# HA-09
# ---------------------------------------------------------------------------------------------------------
class ClockSkewRearmTests(unittest.TestCase):
    SKEW = ps.POLICY.clock_skew_max_seconds
    DAY1 = "2026-10-01T12:00:00.000000Z"
    DAY2 = "2026-10-02T00:05:00.000000Z"                                 # a new UTC day, outside the guard zone

    def skewed_rig(self, root, script):
        clock = FixedClock(self.DAY1, step_micros=1000)
        rig = build_rig(root, capture=True, require_date=True, clock=clock,
                        script=[self.step(self.SKEW + 5)] + list(script))
        self.assertEqual(rig.runner.acquire(rig_item(window="d1")).failure, F.CLOCK_SKEW)
        return rig, clock

    @staticmethod
    def step(offset):
        def response(clock):
            return ok(b"[]", headers=JSON + (("date", http_date(ps.iso_add(clock.peek(), seconds=offset))),))
        return response

    def test_ha09_the_next_utc_day_alone_does_not_rearm_ordinary_sends(self):
        with scratch_root() as root:
            rig, clock = self.skewed_rig(root, [self.step(0)])
            clock.set(self.DAY2)
            refused = rig.runner.acquire(rig_item(window="d2"))
            self.assertEqual(refused.failure, F.CIRCUIT_OPEN)
            self.assertIn("CLOCK_SKEW", refused.detail)
            self.assertEqual(len(rig.transport.calls), 1)                     # only the skewed response

    def test_ha09_a_clean_date_check_by_an_explicit_probe_rearms_then_ordinary_sends_resume(self):
        with scratch_root() as root:
            rig, clock = self.skewed_rig(root, [self.step(0), self.step(0)])
            clock.set(self.DAY2)
            probe = rig.runner.acquire(rig_item(window="d2-probe"), clock_check=True)
            self.assertIsNone(probe.failure)
            self.assertEqual(len(rig.transport.calls), 2)
            rearmed = rows_of(root, "acq_clock_rearmed")
            self.assertEqual([row["acquisition_id"] for row in rearmed], [probe.acquisition_id])
            debits = [row for row in quota_rows(root) if row["record_type"] == "quota_billable_call"]
            self.assertEqual(len(debits), 2)                                  # the probe is debited like any send
            ordinary = rig.runner.acquire(rig_item(window="d2"))
            self.assertIsNone(ordinary.failure)
            self.assertEqual(len(rig.transport.calls), 3)

    def test_ha09_a_probe_before_the_next_utc_day_is_refused_and_not_sent(self):
        with scratch_root() as root:
            rig, clock = self.skewed_rig(root, [self.step(0)])
            clock.set("2026-10-01T23:00:00.000000Z")
            refused = rig.runner.acquire(rig_item(window="d1-probe"), clock_check=True)
            self.assertEqual(refused.failure, F.CIRCUIT_OPEN)
            self.assertEqual(len(rig.transport.calls), 1)
            self.assertEqual(rows_of(root, "acq_clock_rearmed"), [])

    def test_ha09_a_probe_whose_date_is_missing_or_skewed_does_not_rearm(self):
        for label, response in (("skewed", self.step(self.SKEW + 5)),
                                ("missing", lambda clock: ok(b"[]", headers=JSON))):
            with self.subTest(label), scratch_root() as root:
                rig, clock = self.skewed_rig(root, [response, self.step(0)])
                clock.set(self.DAY2)
                probe = rig.runner.acquire(rig_item(window="d2-probe"), clock_check=True)
                self.assertEqual(probe.failure, F.CLOCK_SKEW)
                self.assertEqual(rows_of(root, "acq_clock_rearmed"), [])
                later = rig.runner.acquire(rig_item(window="d2"))
                self.assertEqual(later.failure, F.CIRCUIT_OPEN)
                self.assertEqual(len(rig.transport.calls), 2)

    def test_ha09_without_a_date_header_no_probe_rearms_even_in_fixture_mode(self):
        with scratch_root() as root:
            clock = FixedClock(self.DAY1, step_micros=1000)
            rig = build_rig(root, capture=True, require_date=True, clock=clock, script=[self.step(self.SKEW + 5)])
            rig.runner.acquire(rig_item(window="d1"))
            fixture_mode = build_rig(root, capture=True, require_date=False, clock=clock,
                                     quota_ledger=rig.quota_ledger, cache=rig.cache,
                                     script=[lambda c: ok(b"[]", headers=JSON)])
            clock.set(self.DAY2)
            probe = fixture_mode.runner.acquire(rig_item(window="d2-probe"), clock_check=True)
            self.assertEqual(rows_of(root, "acq_clock_rearmed"), [])          # no Date: nothing was checked
            self.assertIsNotNone(probe)
            refused = fixture_mode.runner.acquire(rig_item(window="d2"))
            self.assertEqual(refused.failure, F.CIRCUIT_OPEN)

    def test_ha09_an_operator_reset_does_not_clear_a_skew_suspension(self):
        with scratch_root() as root:
            rig, clock = self.skewed_rig(root, [self.step(0)])
            AcquisitionLedger(root / "acquisition.jsonl").append(
                "acq_operator_reset", recorded_at="2026-10-01T13:00:00.000000Z",
                approval_reference="adr:synthetic-test-only", reason="test")
            for moment in ("2026-10-01T14:00:00.000000Z", self.DAY2):
                clock.set(moment)
                refused = rig.runner.acquire(rig_item(window="w-" + moment[:13]))
                self.assertEqual(refused.failure, F.CIRCUIT_OPEN, moment)
            self.assertEqual(len(rig.transport.calls), 1)

    def test_ha09_the_probe_still_passes_every_other_gate(self):
        with scratch_root() as root:
            rig, clock = self.skewed_rig(root, [self.step(0)])
            clock.set("2026-10-02T23:59:30.000000Z")                          # inside the day-boundary guard zone
            refused = rig.runner.acquire(rig_item(window="guard-probe"), clock_check=True)
            self.assertEqual(refused.failure, F.WINDOW_BOUNDARY_GUARD)
            self.assertEqual(len(rig.transport.calls), 1)

    def test_ha09_a_rearm_survives_a_restart(self):
        with scratch_root() as root:
            rig, clock = self.skewed_rig(root, [self.step(0)])
            clock.set(self.DAY2)
            rig.runner.acquire(rig_item(window="d2-probe"), clock_check=True)
            again = build_rig(root, capture=True, require_date=True, clock=clock, quota_ledger=rig.quota_ledger,
                              cache=rig.cache, script=[self.step(0)])
            self.assertIsNone(again.runner.acquire(rig_item(window="d2")).failure)


# ---------------------------------------------------------------------------------------------------------
# HA-10
# ---------------------------------------------------------------------------------------------------------
BASE = "2026-10-01T12:00:00.000000Z"
NOT_AFTER = "2026-10-01T18:00:00.000000Z"


class RetryStateMachineTests(unittest.TestCase):
    def rig(self, root, script):
        return build_rig(root, script=list(script), clock=FixedClock(BASE, step_micros=1000), capture=True)

    def snapshot(self, root, rig):
        return (len(acq_rows(root)), len(quota_rows(root)), len(rig.transport.calls))

    def refused(self, root, rig, item, reason):
        before = self.snapshot(root, rig)
        try:
            rig.runner.acquire(item)
        except Exception as exc:                                              # the expected refusal, checked below
            refusal = exc
        else:
            refusal = None
        self.assertEqual(self.snapshot(root, rig), before,                    # nothing durable, nothing sent
                         "the plan item left an acquisition row, a debit or a send")
        self.assertIsInstance(refusal, err.PlanRefused)
        self.assertEqual(refusal.reason, reason)
        return refusal

    def retry(self, attempt=2, not_after=NOT_AFTER, purpose="RETRY", window="w1"):
        return rig_item(window=window, attempt=attempt, purpose=purpose, not_after=not_after)

    def test_ha10_no_retry_after_a_non_retryable_outcome(self):
        for label, scripted in (("404", status(404)), ("429", status(429)), ("401", status(401)),
                                ("schema", ok(b'{"not": "a list"}', headers=JSON))):
            with self.subTest(label), scratch_root() as root:
                rig = self.rig(root, [scripted, ok()])
                rig.runner.acquire(rig_item(window="w1"))
                rig.clock.advance(seconds=rig.policy.retry_min_backoff_seconds + 1)
                self.refused(root, rig, self.retry(), "NOT_RETRYABLE")
                self.assertEqual(len(rig.transport.calls), 1)

    def test_ha10_a_later_attempt_must_be_a_retry_and_a_first_attempt_cannot_be(self):
        with scratch_root() as root:
            rig = self.rig(root, [no_response(), ok()])
            self.refused(root, rig, self.retry(attempt=1), "RETRY_WITHOUT_PRIOR_ATTEMPT")
            rig.runner.acquire(rig_item(window="w1"))
            rig.clock.advance(seconds=rig.policy.retry_min_backoff_seconds + 1)
            self.refused(root, rig, self.retry(purpose="SCHEDULED"), "RETRY_PURPOSE_REQUIRED")

    def test_ha10_a_retry_needs_its_immediate_predecessor_and_a_window(self):
        with scratch_root() as root:
            rig = self.rig(root, [no_response(), ok()])
            rig.runner.acquire(rig_item(window="w1"))
            rig.clock.advance(seconds=rig.policy.retry_min_backoff_seconds + 1)
            self.refused(root, rig, self.retry(attempt=3), "NO_PRIOR_ATTEMPT")
            self.refused(root, rig, self.retry(not_after=None), "RETRY_WINDOW_REQUIRED")

    def test_ha10_a_premature_retry_is_refused_until_the_backoff_has_passed(self):
        with scratch_root() as root:
            rig = self.rig(root, [no_response(), ok()])
            rig.runner.acquire(rig_item(window="w1"))
            refusal = self.refused(root, rig, self.retry(), "BACKOFF")
            self.assertIsNotNone(refusal.not_before)
            rig.clock.set(refusal.not_before)
            second = rig.runner.acquire(self.retry())
            self.assertIsNone(second.failure)
            debits = [row for row in quota_rows(root) if row["record_type"] == "quota_billable_call"]
            self.assertEqual(len(debits), 2)                                  # a fresh debit
            self.assertNotEqual(debits[0]["request_id"], debits[1]["request_id"])   # under a fresh identity
            self.assertEqual(len(rig.transport.calls), 2)

    def test_ha10_retries_stop_at_the_per_window_limit(self):
        limit = ps.POLICY.max_retries_per_window
        with scratch_root() as root:
            rig = self.rig(root, [no_response()] * (limit + 2))
            rig.runner.acquire(rig_item(window="w1"))
            for attempt in range(2, limit + 2):
                rig.clock.advance(seconds=rig.policy.retry_min_backoff_seconds + 1)
                self.assertEqual(rig.runner.acquire(self.retry(attempt=attempt)).failure, F.NO_RESPONSE)
            rig.clock.advance(seconds=rig.policy.retry_min_backoff_seconds + 1)
            self.refused(root, rig, self.retry(attempt=limit + 2), "RETRY_LIMIT_REACHED")

    def test_ha10_no_retry_without_quota_headroom(self):
        with scratch_root() as root:
            rig = build_rig(root, script=[no_response(), ok()], clock=FixedClock(BASE, step_micros=1000), capture=True,
                            quota_policy=test_quota_policy(daily=1))
            rig.runner.acquire(rig_item(window="w1"))                         # the day's only unit is spent
            rig.clock.advance(seconds=rig.policy.retry_min_backoff_seconds + 1)
            self.refused(root, rig, self.retry(), "NO_QUOTA_HEADROOM")

    def test_ha10_no_retry_once_the_window_has_closed(self):
        with scratch_root() as root:
            rig = self.rig(root, [status(503), ok()])
            rig.runner.acquire(rig_item(window="w1"))
            rig.clock.set(NOT_AFTER)
            self.refused(root, rig, self.retry(), "WINDOW_CLOSED")

    def test_ha10_a_prior_attempt_still_open_after_a_crash_must_be_reconciled_first(self):
        with scratch_root() as root:
            def crash(step):
                if step == "after_sent":
                    raise Crash()
            rig = build_rig(root, checkpoint=crash, clock=FixedClock(BASE, step_micros=1000))
            with self.assertRaises(Crash):
                rig.runner.acquire(rig_item(window="w1"))
            fresh = build_rig(root, script=[ok()], quota_ledger=rig.quota_ledger, cache=rig.cache,
                              clock=FixedClock("2026-10-01T12:05:00.000000Z", step_micros=1000))
            self.refused(root, fresh, self.retry(), "PRIOR_ATTEMPT_OPEN")
            fresh.runner.reconcile_after_restart()
            fresh.clock.advance(seconds=fresh.policy.retry_min_backoff_seconds + 1)
            self.assertIsNone(fresh.runner.acquire(self.retry()).failure)     # an orphan is retryable once

    def test_ha10_the_cli_run_enforces_the_retry_state_machine(self):
        from genesis_adapters.oddspapi import endpoints as ep

        from .test_v05_tx01 import PARAMS, prepare
        with scratch_root() as base:
            root, plan, env = prepare(base)
            authority = root / "authority.jsonl"
            rows = read_jsonl(authority)
            g2 = [row for row in rows if row["gate"] == "G2"][0]
            now = datetime.now(timezone.utc)
            # a G2 envelope of two pinned requests (max_calls must equal their number): the gate alone would let a
            # second send of the FIRST request through, so only the retry state machine can refuse it
            other = ep.build_request(SPECS["ODDS"], **dict(PARAMS, tournamentIds=[8])).provider_request_hash
            extra = dict(g2, max_calls=2, request_hashes=sorted(g2["request_hashes"] + [other]),
                         approval_reference="adr:synthetic-test-only-g2-retry",
                         granted_at=iso_utc(now - timedelta(minutes=30)))
            for key in ("previous_hash", "sequence", "record_hash"):
                extra.pop(key, None)
            from genesis_adapters.oddspapi.authority import AdapterAuthorityLedger, load_gate_limits
            AdapterAuthorityLedger(authority, limits=load_gate_limits(CONFIG)).append(extra)
            not_after = iso_utc(now + timedelta(hours=1))
            plan.write_text(json.dumps([
                {"role": "ODDS", "params": PARAMS, "window": "cli"},
                {"role": "ODDS", "params": PARAMS, "window": "cli", "attempt": 2, "purpose": "RETRY",
                 "not_after": not_after}]), encoding="utf-8")
            calls = []

            class Scripted404(th.HttpsTransport):
                def send(self, request, *, clock, deadline_at):
                    calls.append(request.provider_request_hash)
                    t0 = clock.now()
                    return TransportResult("RESPONSE", 404, (("content-type", "application/json"),), b"{}", None,
                                           t0, ps.iso_add(t0, micros=1000))

            err_out, out = io.StringIO(), io.StringIO()
            synchronized = {"synchronized": True, "method": "test", "source": "test"}
            with mock.patch.object(th, "HttpsTransport", Scripted404), \
                    mock.patch.object(cli, "time_sync_attestation", lambda: synchronized), \
                    mock.patch.dict(os.environ, {"GENESIS_ODDSPAPI_CREDENTIAL_FILE":
                                                 env["GENESIS_ODDSPAPI_CREDENTIAL_FILE"]}), \
                    contextlib.redirect_stderr(err_out), contextlib.redirect_stdout(out):
                code = cli.cmd_run(SimpleNamespace(config=None, root=str(root), plan=str(plan), mode="G2"))
            self.assertEqual(code, cli.EXIT_REFUSED)
            self.assertIn("NOT_RETRYABLE", err_out.getvalue())
            self.assertEqual(len(calls), 1)                                   # the 404 only; the retry never went out
            debits = [row for row in quota_rows(root) if row["record_type"] == "quota_billable_call"]
            self.assertEqual(len(debits), 1)


# ---------------------------------------------------------------------------------------------------------
# HA-11
# ---------------------------------------------------------------------------------------------------------
class PinnedScopeTests(unittest.TestCase):
    def test_ha11_the_scope_is_published_and_pinned_before_the_send(self):
        with scratch_root() as root:
            seen = {}
            base = open_rt(root, script=[odds_response()])
            base.acquire(odds_item("w0"))                                     # books with OPEN heads exist now
            rt = reopen(base, script=[odds_response()])
            real = rt.runner.transport.send

            def watching(request, **kw):
                seen["at_send"] = rows_of(root, "acq_sent")[-1]
                return real(request, **kw)

            rt.runner.transport = SimpleNamespace(send=watching, calls=[])
            rt.acquire(odds_item("w1"))
            sent = seen["at_send"]
            self.assertIn("expected_scope_hash", sent)
            digest = sent["expected_scope_hash"]
            self.assertIsInstance(digest, str)
            books = scope_mod.load_scope(root, digest)                        # immutable, hash-verified, non-empty
            self.assertTrue(books)
            normalized = rows_of(root, "acq_normalized")[-1]
            self.assertEqual(normalized["expected_scope_hash"], digest)

    def test_ha11_resume_uses_the_pinned_scope_even_after_the_pit_log_changed(self):
        with scratch_root() as root:
            base = open_rt(root, script=[odds_response()])
            base.acquire(odds_item("w0"))
            crashing = reopen(base, script=[odds_response()])
            with CrashAfterCompleted(0).active(), self.assertRaises(Crash):   # completed, not yet normalized
                crashing.acquire(odds_item("w1"))
            pinned = rows_of(root, "acq_sent")[-1].get("expected_scope_hash")
            self.assertIsNotNone(pinned, "no scope was pinned before the send")
            calls = []
            real = derivation.expected_scope_at

            def changed(*args, **kwargs):                                     # the PIT view at resume differs
                calls.append(1)
                return {}
            with mock.patch.object(derivation, "expected_scope_at", changed):
                restarted = reopen(crashing)
                restarted.resume()
            self.assertEqual(calls, [])                                       # never recomputed after the send
            normalized = [row for row in rows_of(root, "acq_normalized")][-1]
            self.assertEqual(normalized["expected_scope_hash"], pinned)
            self.assertIs(real, derivation.expected_scope_at)

    def test_ha11_a_capture_without_a_pinned_scope_is_never_normalized(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response()])
            rt.runner.scope_pinner = None                                     # e.g. a raw-only (G2) capture
            with self.assertRaises(derivation.DerivationError):
                rt.acquire(odds_item("w1"))
            self.assertEqual(len(pit_rows(rt)), 0)
            self.assertEqual(rows_of(root, "acq_normalized"), [])
            self.assertIsNone(rows_of(root, "acq_sent")[-1]["expected_scope_hash"])

    def test_ha11_metadata_requests_pin_no_scope(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[ok(fixture_body("fixtures.json"), headers=JSON)])
            rt.acquire(fixtures_item("wf"))
            self.assertIsNone(rows_of(root, "acq_sent")[-1]["expected_scope_hash"])


if __name__ == "__main__":
    unittest.main()
