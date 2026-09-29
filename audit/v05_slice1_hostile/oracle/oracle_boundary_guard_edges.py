#!/usr/bin/env python3
"""Oracle 7 - UTC boundary guard W1-W4 expected verdicts (audit area 7, BND-01/02).

Independent implementation of c8dfafd 14.6:
  W1  Tq + timeout + skew < next UTC midnight strictly after Tq
  W2  Tq + timeout + skew < next first-of-month UTC midnight strictly after Tq
  W3  Tq - skew >= start of Tq's UTC day
  W4  Tq - skew >= start of Tq's UTC month
Produces the exact-edge grid for day and month boundaries (30/31-day months, 28 Feb
non-leap, 29 Feb leap, 31 Dec -> 1 Jan) with microsecond edges, the guard zone with the
provisional values, and a JSON file the candidate's guard can be compared against.

  python oracle_boundary_guard_edges.py [--timeout 60] [--skew 120] --out EXPECTED_BOUNDARY_EDGES.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone


def iso(dt):
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")


def next_midnight(t: datetime) -> datetime:
    return (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def next_month_start(t: datetime) -> datetime:
    y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
    return datetime(y, m, 1, tzinfo=timezone.utc)


def guard(tq: datetime, timeout: int, skew: int) -> dict:
    to, sk = timedelta(seconds=timeout), timedelta(seconds=skew)
    w1 = tq + to + sk < next_midnight(tq)
    w2 = tq + to + sk < next_month_start(tq)
    w3 = tq - sk >= tq.replace(hour=0, minute=0, second=0, microsecond=0)
    w4 = tq - sk >= tq.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return {"W1": w1, "W2": w2, "W3": w3, "W4": w4, "send": w1 and w2 and w3 and w4}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--skew", type=int, default=120)
    ap.add_argument("--out", default="EXPECTED_BOUNDARY_EDGES.json")
    a = ap.parse_args()
    us = timedelta(microseconds=1)
    m = timedelta(seconds=a.timeout + a.skew)
    boundaries = {
        "day_plain": datetime(2026, 10, 4, tzinfo=timezone.utc),
        "month_30_to_31": datetime(2026, 10, 1, tzinfo=timezone.utc),      # Sep(30) -> Oct
        "month_31_to_30": datetime(2026, 12, 1, tzinfo=timezone.utc),      # Nov(30)->Dec; also 31->30 at Nov 1
        "feb_nonleap_2027": datetime(2027, 3, 1, tzinfo=timezone.utc),     # 28 Feb 2027 -> 1 Mar
        "feb_leap_2028": datetime(2028, 3, 1, tzinfo=timezone.utc),        # 29 Feb 2028 -> 1 Mar
        "year_end": datetime(2027, 1, 1, tzinfo=timezone.utc),             # 31 Dec 2026 -> 1 Jan 2027
    }
    grid = {}
    for name, B in boundaries.items():
        cases = {
            "B - m - 1us": B - m - us, "B - m": B - m, "B - timeout": B - timedelta(seconds=a.timeout),
            "B - 1us": B - us, "B": B, "B + skew - 1us": B + timedelta(seconds=a.skew) - us,
            "B + skew": B + timedelta(seconds=a.skew),
        }
        grid[name] = {label: {"Tq": iso(tq), **guard(tq, a.timeout, a.skew)} for label, tq in cases.items()}
    expected_pattern = [True, False, False, False, False, False, True]
    consistent = all([v["send"] for v in g.values()] == expected_pattern for g in grid.values())
    zone_start = datetime(2026, 10, 3, tzinfo=timezone.utc) + timedelta(days=1) - m
    zone_end = datetime(2026, 10, 4, tzinfo=timezone.utc) + timedelta(seconds=a.skew)
    out = {"policy": {"request_timeout_seconds": a.timeout, "clock_skew_max_seconds": a.skew},
           "guard_zone_each_day_utc": f"[{zone_start.time()} , {zone_end.time()})",
           "expected_send_pattern_per_boundary": dict(zip(
               ["B - m - 1us", "B - m", "B - timeout", "B - 1us", "B", "B + skew - 1us", "B + skew"], expected_pattern)),
           "pattern_consistent_across_boundaries": consistent, "grid": grid,
           "sanity_bound": {"zone_seconds": a.timeout + 2 * a.skew, "must_be_lt_3600": a.timeout + 2 * a.skew < 3600}}
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "grid"}, indent=2))
    for name, g in grid.items():
        print(name, [("SEND" if v["send"] else "refuse") for v in g.values()])
    return 0 if consistent else 1


if __name__ == "__main__":
    sys.exit(main())
