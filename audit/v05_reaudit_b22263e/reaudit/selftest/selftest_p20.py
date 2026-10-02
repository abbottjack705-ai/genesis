#!/usr/bin/env python3
"""Self-test of probes/p20_deadline_stages.py against mock transports (no candidate needed).

A CORRECT mock implements c8dfafd §14.6 rule 3 / §6.2 literally. Four BROKEN mocks each carry one classic
deadline defect. The probe must pass CORRECT and fail each BROKEN mock on the check that names its defect:
  GT        refuses only when now > deadline (sends AT the deadline)            -> D1
  EARLY_T0  reads T0 before connecting and checks only that                     -> D1, D3
  ZERO_TO   clamps the remaining time to 0 and hands it to settimeout          -> D1, D2
  LATE_READ never checks the deadline while reading                             -> D4
"""

from __future__ import annotations

import sys
from pathlib import Path

PROBES = Path(__file__).resolve().parent.parent / "probes"
sys.path.insert(0, str(PROBES))
import _common_37b86fb as c  # noqa: E402
import p20_deadline_stages as p20  # noqa: E402


class Result:
    def __init__(self, outcome, t0, t1):
        self.outcome, self.request_started_at, self.response_received_at = outcome, t0, t1
        self.sanitized_error = None


class MockTransport:
    def __init__(self, conn, mode="CORRECT"):
        self.conn, self.mode = conn, mode

    def remaining(self, clock, deadline):
        return (c.parse(deadline) - c.parse(clock.now())).total_seconds()

    def send(self, request, *, clock, deadline_at):
        conn = self.conn("h", 443, None, None)
        early_t0 = clock.now() if self.mode == "EARLY_T0" else None
        left = self.remaining(clock, deadline_at)
        if left <= 0:
            return Result("NO_RESPONSE", None, None)
        conn.open(timeout=left)
        if self.mode == "EARLY_T0":
            t0 = early_t0
            if not c.parse(t0) < c.parse(deadline_at):
                return Result("NO_RESPONSE", None, None)
        else:
            t0 = clock.now()
            if self.mode == "GT":
                if c.parse(t0) > c.parse(deadline_at):
                    return Result("NO_RESPONSE", None, None)
            elif self.mode == "ZERO_TO":
                conn.settimeout(max(0.0, (c.parse(deadline_at) - c.parse(t0)).total_seconds()))
            elif not c.parse(t0) < c.parse(deadline_at):
                conn.close()
                return Result("NO_RESPONSE", None, None)
        conn.write("GET", "/v4/odds", [])
        body = b""
        if self.mode != "LATE_READ":
            left = self.remaining(clock, deadline_at)
            if left <= 0:
                conn.close()
                return Result("NO_RESPONSE", t0, None)
            conn.settimeout(left)
        conn.read_head()
        while not conn.finished():
            if self.mode != "LATE_READ":
                left = self.remaining(clock, deadline_at)
                if left <= 0:
                    conn.close()
                    return Result("TRUNCATED", t0, None)
                conn.settimeout(left)
            body += conn.read_chunk(100)
        t1 = clock.now()
        if self.mode != "LATE_READ" and not c.parse(t1) < c.parse(deadline_at):
            return Result("TRUNCATED", t0, None)
        return Result("RESPONSE", t0, t1)


class Req:
    provider_request_hash = "0" * 64


def run(mode: str) -> list[dict]:
    del c.RESULTS[:]
    p20.run_scenarios(lambda conn: MockTransport(conn, mode), Req())
    return [r for r in c.RESULTS if not r["pass"]]


def main() -> int:
    expectations = {"CORRECT": set(), "GT": {"D1"}, "EARLY_T0": {"D1", "D3"}, "ZERO_TO": {"D1", "D2"},
                    "LATE_READ": {"D4"}}
    ok = True
    for mode, wanted in expectations.items():
        failed = run(mode)
        families = {r["check"].split()[0] for r in failed}
        good = families == wanted if mode == "CORRECT" else wanted <= families
        ok &= good
        print(f"[{'OK ' if good else 'BAD'}] {mode:9} expected failing {sorted(wanted) or 'none'}; probe failed "
              f"{sorted(families) or 'none'}")
        for r in failed:
            print(f"        - {r['check']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
