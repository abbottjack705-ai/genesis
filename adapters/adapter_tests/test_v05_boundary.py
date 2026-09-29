"""BND-01, BND-02, BND-03, BND-05 and F-43: the UTC day/month boundary guard (design 14.6)."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from genesis_adapters import config as cfg
from genesis_adapters import errors as err
from genesis_adapters.oddspapi import acquisition as acq

from .support import (
    CONFIG, FixedClock, build_rig, odds_item, read_jsonl, scratch_root,
)

POLICY = cfg.load_policy(CONFIG / "oddspapi_slice1_policy.json")
TIMEOUT = timedelta(seconds=POLICY.request_timeout_seconds)
SKEW = timedelta(seconds=POLICY.clock_skew_max_seconds)
M = TIMEOUT + SKEW
UTC = timezone.utc
MICRO = timedelta(microseconds=1)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def guard(moment: datetime, boundaries=None) -> acq.GuardDecision:
    return acq.boundary_guard(iso(moment), POLICY, boundaries=boundaries)


class NoDayBoundaries(acq.UtcBoundaries):
    """Day boundaries pushed out of reach so only the MONTH conditions can bind."""

    def next_day(self, moment):
        return moment + timedelta(days=100000)

    def day_start(self, moment):
        return moment - timedelta(days=100000)


class NoMonthBoundaries(acq.UtcBoundaries):
    """Month boundaries pushed out of reach so only the DAY conditions can bind."""

    def next_month(self, moment):
        return moment + timedelta(days=100000)

    def month_start(self, moment):
        return moment - timedelta(days=100000)


class DayEdgeTests(unittest.TestCase):
    midnight = datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)

    def edges(self, midnight, boundaries=None):
        return [
            (midnight - M - MICRO, True), (midnight - M, False),
            (midnight - TIMEOUT, False), (midnight - MICRO, False), (midnight, False),
            (midnight + SKEW - MICRO, False), (midnight + SKEW, True),
        ]

    def test_bnd01_exact_day_edges_from_the_policy_values(self):
        for moment, permitted in self.edges(self.midnight):
            decision = guard(moment)
            self.assertEqual(decision.permitted, permitted, iso(moment))
            if not permitted:
                self.assertIn(decision.failed, {"W1", "W3"})
                self.assertIsNotNone(decision.next_permitted)
                self.assertGreater(decision.next_permitted, iso(moment))

    def test_bnd01_which_condition_fails_at_each_refused_edge(self):
        self.assertEqual(guard(self.midnight - M).failed, "W1")
        self.assertEqual(guard(self.midnight - TIMEOUT).failed, "W1")
        self.assertEqual(guard(self.midnight - MICRO).failed, "W1")
        self.assertEqual(guard(self.midnight).failed, "W3")
        self.assertEqual(guard(self.midnight + SKEW - MICRO).failed, "W3")

    def test_bnd01_the_next_permitted_instant_is_the_boundary_plus_the_skew_margin(self):
        for moment in (self.midnight - M, self.midnight - MICRO, self.midnight, self.midnight + SKEW - MICRO):
            decision = guard(moment)
            self.assertEqual(decision.next_permitted, iso(self.midnight + SKEW), iso(moment))
            self.assertTrue(guard(datetime.fromisoformat(decision.next_permitted[:-1] + "+00:00")).permitted)

    def test_bnd01_day_conditions_bind_alone_when_month_boundaries_are_out_of_reach(self):
        for moment, permitted in self.edges(self.midnight):
            self.assertEqual(guard(moment, NoMonthBoundaries()).permitted, permitted, iso(moment))

    def test_the_middle_of_the_day_is_always_permitted(self):
        for hour in (1, 6, 12, 18, 23):
            moment = datetime(2026, 10, 1, hour, 0, 0, tzinfo=UTC)
            if hour == 23:
                moment = datetime(2026, 10, 1, 23, 0, 0, tzinfo=UTC)
            self.assertTrue(guard(moment).permitted)


class MonthEdgeTests(unittest.TestCase):
    starts = {
        "30->31 day months": datetime(2026, 10, 1, tzinfo=UTC),
        "31->30 day months": datetime(2026, 11, 1, tzinfo=UTC),
        "28 Feb (non-leap)": datetime(2027, 3, 1, tzinfo=UTC),
        "29 Feb (leap)": datetime(2028, 3, 1, tzinfo=UTC),
        "31 Dec -> 1 Jan": datetime(2027, 1, 1, tzinfo=UTC),
        "31 Jan -> 1 Feb": datetime(2027, 2, 1, tzinfo=UTC),
    }

    def grid(self, boundary):
        return [
            (boundary - M - MICRO, True), (boundary - M, False), (boundary - TIMEOUT, False),
            (boundary - MICRO, False), (boundary, False), (boundary + SKEW - MICRO, False),
            (boundary + SKEW, True),
        ]

    def test_bnd02_exact_month_edges_at_every_rollover(self):
        for label, boundary in self.starts.items():
            for moment, permitted in self.grid(boundary):
                self.assertEqual(guard(moment).permitted, permitted, f"{label} {iso(moment)}")

    def test_bnd02_month_conditions_bind_alone_when_day_boundaries_are_out_of_reach(self):
        for label, boundary in self.starts.items():
            for moment, permitted in self.grid(boundary):
                decision = guard(moment, NoDayBoundaries())
                self.assertEqual(decision.permitted, permitted, f"{label} {iso(moment)}")
                if not permitted:
                    self.assertIn(decision.failed, {"W2", "W4"}, f"{label} {iso(moment)}")

    def test_bnd02_leap_february_has_a_29th_day(self):
        late_28 = datetime(2028, 2, 28, 23, 58, tzinfo=UTC)      # inside the guard zone of the DAY edge
        self.assertFalse(guard(late_28).permitted)
        late_29 = datetime(2028, 2, 29, 23, 58, tzinfo=UTC)
        decision = guard(late_29, NoDayBoundaries())
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.next_permitted, iso(datetime(2028, 3, 1, tzinfo=UTC) + SKEW))
        non_leap = datetime(2027, 2, 28, 23, 58, tzinfo=UTC)
        self.assertEqual(guard(non_leap, NoDayBoundaries()).failed, "W2")
        self.assertEqual(guard(non_leap, NoDayBoundaries()).next_permitted,
                         iso(datetime(2027, 3, 1, tzinfo=UTC) + SKEW))

    def test_bnd02_calculator_arithmetic(self):
        calc = acq.UtcBoundaries()
        self.assertEqual(calc.next_month(datetime(2027, 12, 31, 12, tzinfo=UTC)), datetime(2028, 1, 1, tzinfo=UTC))
        self.assertEqual(calc.month_start(datetime(2028, 2, 29, 23, 59, tzinfo=UTC)), datetime(2028, 2, 1, tzinfo=UTC))
        self.assertEqual(calc.next_day(datetime(2027, 2, 28, 23, 59, tzinfo=UTC)), datetime(2027, 3, 1, tzinfo=UTC))
        self.assertEqual(calc.day_start(datetime(2026, 10, 1, 0, 0, tzinfo=UTC)), datetime(2026, 10, 1, tzinfo=UTC))
        self.assertEqual(calc.next_day(datetime(2026, 10, 1, 0, 0, tzinfo=UTC)), datetime(2026, 10, 2, tzinfo=UTC))


class RunnerBoundaryTests(unittest.TestCase):
    def test_bnd03_a_refused_send_makes_no_quota_call_and_writes_no_quota_row(self):
        midnight = datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)
        with scratch_root() as root:
            rig = build_rig(root, clock=FixedClock(iso(midnight - TIMEOUT), step_micros=1000))
            outcome = rig.runner.acquire(odds_item())
            self.assertEqual(outcome.outcome, "REFUSED")
            self.assertEqual(outcome.failure, err.AdapterFailure.WINDOW_BOUNDARY_GUARD)
            self.assertEqual(outcome.next_not_before, iso(midnight + SKEW))
            self.assertEqual(rig.transport.calls, [])
            self.assertFalse((root / "quota" / "ledger.jsonl").exists())
            rows = read_jsonl(rig.acq_path)
            self.assertEqual([r["record_type"] for r in rows], ["acq_planned", "acq_refused"])
            self.assertEqual(rows[1]["reason"], "WINDOW_BOUNDARY_GUARD")
            self.assertEqual(rows[1]["not_before"], iso(midnight + SKEW))
            entries = read_jsonl(rig.coverage_path)
            self.assertEqual([(e["status"], e["reason_codes"], e["note"]) for e in entries],
                             [("not_attempted", ["attempt_budget_exhausted"], "WINDOW_BOUNDARY_GUARD")])

    def test_bnd03_for_a_permitted_send_the_guard_time_and_the_ledger_time_are_one_value(self):
        with scratch_root() as root:
            clock = FixedClock("2026-10-01T12:00:00.000000Z", step_micros=1000)
            rig = build_rig(root, clock=clock)
            rig.runner.acquire(odds_item())
            planned, decided = read_jsonl(rig.acq_path)[:2]
            quota = [r for r in read_jsonl(root / "quota" / "ledger.jsonl")
                     if r["record_type"] == "quota_billable_call"][0]
            self.assertEqual(planned["recorded_at"], decided["Tq"])
            self.assertEqual(decided["Tq"], quota["occurred_at"])
            self.assertEqual(rig.transport.calls[0].deadline_at,
                             iso(datetime.fromisoformat(decided["Tq"][:-1] + "+00:00") + TIMEOUT))

    def test_bnd03_the_guard_runs_on_the_same_read_that_reaches_the_ledger(self):
        reads = []

        class Counting(FixedClock):
            def now(self):
                value = super().now()
                reads.append(value)
                return value

        with scratch_root() as root:
            rig = build_rig(root, clock=Counting("2026-10-01T12:00:00.000000Z", step_micros=1000))
            rig.runner.acquire(odds_item())
            quota = [r for r in read_jsonl(root / "quota" / "ledger.jsonl")
                     if r["record_type"] == "quota_billable_call"][0]
            self.assertEqual(reads.count(quota["occurred_at"]), 1)   # Tq was read exactly once

    def test_f43_every_condition_refuses_at_runner_level(self):
        month_end = datetime(2026, 10, 31, 23, 58, 0, tzinfo=UTC)        # W1 and W2
        month_start = datetime(2026, 11, 1, 0, 0, 30, tzinfo=UTC)        # W3 and W4
        for moment in (month_end, month_start):
            with self.subTest(iso(moment)), scratch_root() as root:
                rig = build_rig(root, clock=FixedClock(iso(moment), step_micros=1000))
                outcome = rig.runner.acquire(odds_item())
                self.assertEqual(outcome.failure, err.AdapterFailure.WINDOW_BOUNDARY_GUARD)
                self.assertEqual(rig.transport.calls, [])


class TimeoutPolicyTests(unittest.TestCase):
    def test_bnd05_request_timeout_alone_changes_every_downstream_identity(self):
        body = json.loads((CONFIG / "oddspapi_slice1_policy.json").read_text())
        digests = cfg.load_config_digests(CONFIG)
        base = cfg.parse_policy(body)
        body["request_timeout_seconds"] += 1
        changed = cfg.parse_policy(body)
        self.assertNotEqual(changed.digest, base.digest)
        v1, v2 = (cfg.derivation_version("c", digests, p) for p in (base, changed))
        self.assertNotEqual(v1, v2)
        self.assertNotEqual(cfg.normalized_contract_id(v1), cfg.normalized_contract_id(v2))
        self.assertNotEqual(cfg.market_book_source_id(v1), cfg.market_book_source_id(v2))

    def test_bnd05_loader_rejects_nonpositive_missing_and_wide_guard_zone(self):
        body = json.loads((CONFIG / "oddspapi_slice1_policy.json").read_text())
        for bad in (0, -1):
            b = dict(body, request_timeout_seconds=bad)
            with self.assertRaises(cfg.PolicyError):
                cfg.parse_policy(b)
        b = dict(body)
        del b["request_timeout_seconds"]
        with self.assertRaises(cfg.PolicyError):
            cfg.parse_policy(b)
        hour = int(timedelta(hours=1).total_seconds())
        widest_ok = hour - 2 * body["clock_skew_max_seconds"] - 1
        cfg.parse_policy(dict(body, request_timeout_seconds=widest_ok))
        with self.assertRaises(cfg.PolicyError):
            cfg.parse_policy(dict(body, request_timeout_seconds=widest_ok + 1))

    def test_the_guard_uses_the_policy_values_it_is_given(self):
        body = json.loads((CONFIG / "oddspapi_slice1_policy.json").read_text())
        body["request_timeout_seconds"] = 10
        body["clock_skew_max_seconds"] = 5
        small = cfg.parse_policy(body)
        midnight = datetime(2026, 10, 2, tzinfo=UTC)
        m = timedelta(seconds=15)
        self.assertTrue(acq.boundary_guard(iso(midnight - m - MICRO), small).permitted)
        self.assertFalse(acq.boundary_guard(iso(midnight - m), small).permitted)
        self.assertTrue(acq.boundary_guard(iso(midnight + timedelta(seconds=5)), small).permitted)
        self.assertFalse(acq.boundary_guard(iso(midnight + timedelta(seconds=5) - MICRO), small).permitted)


if __name__ == "__main__":
    unittest.main()
