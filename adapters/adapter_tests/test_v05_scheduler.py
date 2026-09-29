"""Q-08 and BND-06: the pure scheduler keeps every cap and pool, drops from the lowest priority up, never plans
inside a UTC guard zone, and admits a conditional refresh only when every design 14.5 condition holds."""

from __future__ import annotations

import dataclasses
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone

from genesis.time import iso_utc, parse_utc

from genesis_adapters.oddspapi import scheduler as sch
from genesis_adapters.oddspapi.acquisition import boundary_guard

from . import parser_support as ps

POLICY = ps.POLICY
MONTH = "2026-10"
START = "2026-10-01T00:00:00.000000Z"


def kickoffs(*items):
    return [sch.Kickoff(fixture_id, start) for fixture_id, start in items]


def season():
    """Two competitions, weekend clusters through October 2026 (Saturdays and Sundays)."""

    items = []
    day = datetime(2026, 10, 3, tzinfo=timezone.utc)
    number = 0
    while day.month == 10:
        for hour in (11, 14, 14, 16, 19):
            items.append((f"f{number}", iso_utc(day.replace(hour=hour, minute=30 if hour == 11 else 0))))
            number += 1
        sunday = day + timedelta(days=1)
        for hour in (13, 15, 18, 20):
            items.append((f"f{number}", iso_utc(sunday.replace(hour=hour))))
            number += 1
        day += timedelta(days=7)
    return kickoffs(*items)


class PlanTests(unittest.TestCase):
    def plan(self, fixtures, **used):
        return sch.plan_month(fixtures, policy=POLICY, month=MONTH,
                              used=sch.QuotaUsage(as_of=used.pop("as_of", START), monthly_used=used.pop("monthly", 0),
                                                  by_pool=used.pop("by_pool", {})))

    def test_q08_the_plan_keeps_the_daily_cap_every_pool_and_the_monthly_projection(self):
        plan = self.plan(season())
        per_day = Counter(parse_utc(w.at).date() for w in plan.windows)
        self.assertLessEqual(max(per_day.values()), POLICY.scheduled_daily_max)
        per_pool = Counter(w.pool for w in plan.windows)
        for pool, ceiling in POLICY.budget_pools.items():
            self.assertLessEqual(per_pool.get(pool, 0), ceiling, pool)
        self.assertLessEqual(len(plan.windows), sum(POLICY.budget_pools.values()))
        self.assertEqual(per_pool["metadata"], 4)
        self.assertTrue(all(w.at.startswith(MONTH) for w in plan.windows))
        self.assertEqual(self.plan(season()).digest, plan.digest)                    # deterministic

    def test_q08_drops_come_from_the_lowest_priority_up(self):
        crowded = kickoffs(*[(f"x{n}", f"2026-10-10T{8 + 3 * n:02d}:00:00.000000Z") for n in range(6)])
        plan = self.plan(crowded)
        day = [w for w in plan.windows if w.at.startswith("2026-10-10")]
        self.assertEqual(len(day), POLICY.scheduled_daily_max)
        dropped = [c for c in plan.changes if c.what == "DROPPED:DAILY_CAP"]
        self.assertTrue(dropped)
        kept_worst = max(w.priority for w in day)
        by_id = {w.window_id: w for w in sch._candidates(crowded, POLICY, datetime(2026, 10, 1, tzinfo=timezone.utc),
                                                            datetime(2026, 11, 1, tzinfo=timezone.utc))}
        for change in dropped:
            self.assertGreaterEqual(by_id[change.window_id].priority, kept_worst)

    def test_q08_used_units_shrink_the_plan_and_the_projection_is_never_exceeded(self):
        total = sum(POLICY.budget_pools.values())
        plan = self.plan(season(), monthly=total - 3)
        self.assertLessEqual(len(plan.windows), 3)
        self.assertTrue(any(c.what == "DROPPED:PROJECTION" for c in plan.changes))
        pooled = self.plan(season(), by_pool={"scheduled_odds": POLICY.budget_pools["scheduled_odds"] - 1})
        self.assertLessEqual(sum(1 for w in pooled.windows if w.pool == "scheduled_odds"), 1)

    def test_bnd06_no_window_is_ever_planned_inside_a_guard_zone(self):
        near_midnight = kickoffs(("late", "2026-10-11T01:15:00.000000Z"),        # prekick lands on 00:00
                                 ("month", "2026-11-01T01:00:00.000000Z"))       # a month boundary too
        plan = sch.plan_month(near_midnight + season(), policy=POLICY, month=MONTH,
                              used=sch.QuotaUsage(as_of=START, monthly_used=0))
        for window in plan.windows:
            self.assertTrue(boundary_guard(window.at, POLICY).permitted, window)
        shifted = [c for c in plan.changes if c.what == "SHIFTED"]
        self.assertTrue(shifted)
        for change in shifted:
            before, after = change.detail.split("->")
            self.assertTrue(boundary_guard(after, POLICY).permitted)
            self.assertFalse(boundary_guard(before, POLICY).permitted)

    def test_odds_windows_at_or_after_the_prematch_guard_are_dropped(self):
        guard = POLICY.prematch_guard_seconds
        tight = dataclasses.replace(POLICY, schedule_prekick_offset_minutes=max(1, guard // 60 - 1))
        plan = sch.plan_month(kickoffs(("k", "2026-10-12T15:00:00.000000Z")), policy=tight, month=MONTH,
                              used=sch.QuotaUsage(as_of=START, monthly_used=0))
        self.assertTrue(any(c.what == "DROPPED:AFTER_PREMATCH_GUARD" for c in plan.changes))
        for window in plan.windows:
            if window.role == "ODDS":
                self.assertLess(parse_utc(window.at), parse_utc("2026-10-12T15:00:00.000000Z") - timedelta(seconds=guard))


class ConditionalRefreshTests(unittest.TestCase):
    def state(self, **over):
        values = dict(policy=POLICY, conditional_used_today=0, conditional_used_month=0, ledger_daily_used=0,
                      ledger_daily_cap=7, ledger_normal_used=0, ledger_normal_cap=220, monthly_used=0,
                      remaining_scheduled=0, circuit_open=False)
        values.update(over)
        return sch.SchedulerState(**values)

    def request(self, code="MISSING_OR_STALE", kickoff="2026-10-12T15:00:00.000000Z"):
        return sch.RefreshRequest("evt:1", "mkt:1", code, kickoff)

    def test_q08_admitted_only_when_every_condition_holds(self):
        now = "2026-10-12T12:00:00.000000Z"
        self.assertEqual(sch.admit_conditional_refresh(self.request(), state=self.state(), now=now),
                         sch.RefreshDecision(True, "ADMITTED"))
        lead = POLICY.prematch_guard_seconds + POLICY.conditional_refresh_min_lead_seconds
        edge = iso_utc(parse_utc("2026-10-12T15:00:00.000000Z") - timedelta(seconds=lead))
        self.assertTrue(sch.admit_conditional_refresh(self.request(), state=self.state(), now=edge).admitted)
        cases = [
            (self.request("SUSPENDED"), self.state(), now, "HEAD_NOT_STALE_OR_MISSING"),
            (self.request("BLOCKED"), self.state(), now, "HEAD_NOT_STALE_OR_MISSING"),
            (self.request(), self.state(), iso_utc(parse_utc(edge) + timedelta(microseconds=1)), "TOO_CLOSE_TO_KICKOFF"),
            (self.request(), self.state(conditional_used_today=POLICY.conditional_daily_max), now,
             "CONDITIONAL_DAILY_CAP"),
            (self.request(), self.state(conditional_used_month=POLICY.budget_pools["conditional"]), now,
             "CONDITIONAL_POOL_EXHAUSTED"),
            (self.request(), self.state(ledger_daily_used=7), now, "FROZEN_LEDGER_WOULD_BLOCK"),
            (self.request(), self.state(ledger_normal_used=220), now, "FROZEN_LEDGER_WOULD_BLOCK"),
            (self.request(), self.state(monthly_used=sum(POLICY.budget_pools.values())), now, "PROJECTION_WOULD_BREAK"),
            (self.request(), self.state(circuit_open=True), now, "CIRCUIT_OPEN"),
            (self.request(kickoff="2026-10-13T12:00:00.000000Z"), self.state(), "2026-10-12T23:59:00.000000Z",
             "WINDOW_BOUNDARY_GUARD"),
        ]
        for request, state, at, reason in cases:
            with self.subTest(reason=reason, at=at):
                self.assertEqual(sch.admit_conditional_refresh(request, state=state, now=at),
                                 sch.RefreshDecision(False, reason))


if __name__ == "__main__":
    unittest.main()
