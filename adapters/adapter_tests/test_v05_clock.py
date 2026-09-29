"""CLK-01: SystemUtcClock is monotonic, drift-checked and floor-checked."""

from __future__ import annotations

import unittest

from genesis_adapters import clock as clk
from genesis_adapters.config import load_policy

from .support import CONFIG

POLICY = load_policy(CONFIG / "oddspapi_slice1_policy.json")
BASE_WALL_NS = 1_790_000_000 * 10 ** 9      # 2026-09-21 in ns


class Sources:
    """Injectable wall/monotonic sources."""

    def __init__(self):
        self.wall = BASE_WALL_NS
        self.mono = 5 * 10 ** 9

    def wall_ns(self):
        return self.wall

    def mono_ns(self):
        return self.mono

    def tick(self, ns, *, wall_extra=0):
        self.wall += ns + wall_extra
        self.mono += ns


class SystemClockTests(unittest.TestCase):
    def make(self, sources, **kw):
        return clk.SystemUtcClock(drift_max_ms=POLICY.wall_monotonic_drift_max_ms,
                                  wall_ns=sources.wall_ns, mono_ns=sources.mono_ns, **kw)

    def test_clk01_real_clock_is_non_decreasing_and_canonical(self):
        clock = clk.SystemUtcClock(drift_max_ms=POLICY.wall_monotonic_drift_max_ms)
        seen = [clock.now() for _ in range(2000)]
        self.assertEqual(seen, sorted(seen))
        for value in seen[:3]:
            self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")

    def test_clk01_wall_jump_just_above_the_drift_bound_raises(self):
        sources = Sources()
        clock = self.make(sources)
        first = clock.now()
        bound_ns = POLICY.wall_monotonic_drift_max_ms * 10 ** 6
        sources.tick(10 ** 6, wall_extra=bound_ns)               # exactly at the bound: allowed
        later = clock.now()
        self.assertGreater(later, first)
        sources.tick(10 ** 6, wall_extra=bound_ns + 1)           # cumulative drift is now above it
        with self.assertRaises(clk.ClockFault):
            clock.now()

    def test_clk01_just_below_the_drift_bound_is_fine(self):
        sources = Sources()
        clock = self.make(sources)
        clock.now()
        bound_ns = POLICY.wall_monotonic_drift_max_ms * 10 ** 6
        sources.tick(10 ** 6, wall_extra=bound_ns - 1)
        clock.now()

    def test_clk01_backwards_wall_clock_raises_even_within_the_drift_bound(self):
        sources = Sources()
        clock = self.make(sources)
        clock.now()
        sources.wall -= 10 ** 6                                   # 1 ms backwards, mono unchanged
        with self.assertRaises(clk.ClockFault):
            clock.now()

    def test_clk01_equal_reads_are_allowed_but_never_earlier(self):
        sources = Sources()
        clock = self.make(sources)
        one = clock.now()
        two = clock.now()
        self.assertEqual(one, two)

    def test_clk01_floor_below_durable_heads_raises(self):
        sources = Sources()
        floor = "2099-01-01T00:00:00.000000Z"
        clock = self.make(sources, floor=floor)
        with self.assertRaises(clk.ClockFault):
            clock.now()
        sources2 = Sources()
        ok = self.make(sources2, floor="2001-01-01T00:00:00.000000Z")
        ok.now()

    def test_clk01_require_not_before_checks_every_durable_head(self):
        clk.require_not_before("2026-10-01T12:00:00.000000Z", None,
                               "2026-10-01T11:59:59.999999Z", "2026-10-01T12:00:00.000000Z")
        with self.assertRaises(clk.ClockFault):
            clk.require_not_before("2026-10-01T12:00:00.000000Z", "2026-10-01T12:00:00.000001Z")
        with self.assertRaises(clk.ClockFault):
            clk.require_not_before("2026-10-01T12:00:00.000000Z", "not a time")

    def test_production_clock_check(self):
        self.assertTrue(clk.is_production_clock(clk.SystemUtcClock(
            drift_max_ms=POLICY.wall_monotonic_drift_max_ms)))

        class Imposter:
            def now(self):
                return "2026-10-01T12:00:00.000000Z"

        self.assertFalse(clk.is_production_clock(Imposter()))

    def test_constructor_validates_the_drift_bound(self):
        for bad in (0, -1, True, "1"):
            with self.assertRaises((ValueError, TypeError)):
                clk.SystemUtcClock(drift_max_ms=bad)


if __name__ == "__main__":
    unittest.main()
