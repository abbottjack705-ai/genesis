"""BND-07 (design 14.6 rule 5): after a CLOCK_SKEW quarantine every send is refused until the next UTC day AND a
clean ``Date`` check. The date alone re-arms nothing (hostile audit HA-09): from the next UTC day on, only an
explicit clock-check probe (gated and debited like any send) may go out, and only its clean ``Date`` check re-arms
ordinary sends; a skewed response of the new day suspends sends again."""

from __future__ import annotations

import unittest

from genesis_adapters import errors as err
from genesis_adapters.oddspapi import acquisition as acq

from . import parser_support as ps
from .support import FixedClock, build_rig, http_date, odds_item, ok, read_jsonl, scratch_root

JSON = (("content-type", "application/json"),)


def dated(offset_seconds: int):
    def step(clock):
        return ok(b"[]", headers=JSON + (("date", http_date(ps.iso_add(clock.peek(), seconds=offset_seconds))),))
    return step


class Bnd07Tests(unittest.TestCase):
    def test_bnd07_sends_stay_suspended_until_the_next_utc_day_and_a_clean_date_check(self):
        skew = ps.POLICY.clock_skew_max_seconds
        with scratch_root() as root:
            clock = FixedClock("2026-10-01T12:00:00.000000Z", step_micros=1000)
            rig = build_rig(root, capture=True, require_date=True, clock=clock,
                            script=[dated(skew + 5), dated(0), dated(0), dated(skew + 5)])
            self.assertEqual(rig.runner.acquire(odds_item(window="d1-a")).failure, err.AdapterFailure.CLOCK_SKEW)
            clock.set("2026-10-01T23:00:00.000000Z")
            later = rig.runner.acquire(odds_item(window="d1-b"))
            self.assertEqual((later.failure, later.detail), (err.AdapterFailure.CIRCUIT_OPEN, "CLOCK_SKEW"))
            self.assertEqual(len(rig.transport.calls), 1)
            clock.set("2026-10-02T00:05:00.000000Z")                      # a new UTC day, outside the guard zone
            pending = rig.runner.acquire(odds_item(window="d2-a"))       # the date alone re-arms nothing
            self.assertEqual((pending.failure, pending.detail),
                             (err.AdapterFailure.CIRCUIT_OPEN, acq.CLOCK_CHECK_PENDING))
            self.assertEqual(len(rig.transport.calls), 1)
            probe = rig.runner.acquire(odds_item(window="d2-probe"), clock_check=True)
            self.assertIsNone(probe.failure)                             # the probe passed a clean Date check
            clean = rig.runner.acquire(odds_item(window="d2-b"))
            self.assertIsNone(clean.failure)
            skewed = rig.runner.acquire(odds_item(window="d2-c"))
            self.assertEqual(skewed.failure, err.AdapterFailure.CLOCK_SKEW)
            clock.set("2026-10-02T18:00:00.000000Z")
            again = rig.runner.acquire(odds_item(window="d2-d"))
            self.assertEqual((again.failure, again.detail), (err.AdapterFailure.CIRCUIT_OPEN, "CLOCK_SKEW"))
            suspended = [r["until"] for r in read_jsonl(rig.acq_path) if r["record_type"] == "acq_sends_suspended"]
            self.assertEqual(suspended, ["2026-10-02T00:00:00.000000Z", "2026-10-03T00:00:00.000000Z"])
            self.assertEqual(len(rig.transport.calls), 4)


if __name__ == "__main__":
    unittest.main()
