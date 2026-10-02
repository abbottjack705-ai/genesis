"""Attack area 8 - hard deadline equality at EVERY blocking stage (c8dfafd §14.6 rule 3, §6.2 T0, BND-04).

The prior audit (37b86fb a07) tested only ``deadline_at == T0`` at the start of ``send``. This probe moves the
trusted clock to exactly the deadline (and +/-1 us) *during* connect, write, read-head and read-body, and
checks, for the candidate's real ``HttpsTransport`` with an auditor connection factory:

  D1  no request byte is written when the clock at the write is >= deadline;
  D2  every timeout handed to a blocking operation is > 0 and <= the remaining time (a 0 timeout makes a
      Python socket NON-BLOCKING, and None makes it wait forever - neither is "refuse");
  D3  T0 (request_started_at) is read after the connection is established, immediately before the write
      (§6.2), and is < deadline whenever a write happened;
  D4  no RESPONSE outcome whose last byte arrived at/after the deadline (T1 < deadline for RESPONSE);
  D5  runner level: deadline_at == Tq + request_timeout_seconds, with Tq the quota/guard instant.

    python -B p20_deadline_stages.py --repo <candidate> [--out p20.json]
    python -B selftest/selftest_p20.py      (proves D1-D4 discriminate, against mock transports)
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _probe as p  # noqa: E402
from _probe import c  # noqa: E402

AREA = "P20"


class ProbeClock:
    """Each now() returns the current instant then advances by ``step_us``; a connection may move it."""

    def __init__(self, start: str, step_us: int = 1):
        self.t = c.parse(start)
        self.step = timedelta(microseconds=step_us)

    def now(self) -> str:
        value = self.t
        self.t = self.t + self.step
        return c.iso(value)

    def peek(self):
        return self.t

    def move_to(self, moment) -> None:
        if moment > self.t:
            self.t = moment


class StageConnection:
    """Auditor connection (same protocol as 37b86fb a07 FaultConnection). At ``stage`` it moves the clock
    to ``deadline + delta``. Every call records (operation, clock at call, timeout argument)."""

    def __init__(self, clock: ProbeClock, deadline: str, stage: str | None, delta_us: int, body: bytes = b"[]"):
        self.clock, self.deadline, self.stage = clock, c.parse(deadline), stage
        self.delta = timedelta(microseconds=delta_us)
        self.body = body
        self.events: list[tuple[str, object, object]] = []
        self.writes = 0
        self.open_done_at = None

    def __call__(self, host, port, context, address):
        return self

    def _at(self, op: str, timeout=None) -> None:
        self.events.append((op, self.clock.peek(), timeout))
        if op == self.stage:
            self.clock.move_to(self.deadline + self.delta)

    def open(self, timeout):
        self._at("open", timeout)
        self.open_done_at = self.clock.peek()

    def settimeout(self, timeout):
        self.events.append(("settimeout", self.clock.peek(), timeout))

    def write(self, method, target, headers):
        self.writes += 1
        self.events.append(("write-begins", self.clock.peek(), None))
        self._at("write")

    def read_head(self):
        self._at("read_head")
        return 200, [("Content-Type", "application/json"), ("Content-Length", str(len(self.body)))]

    def read_chunk(self, size):
        self._at("read_body")
        data, self.body = self.body[:size], self.body[size:]
        return data

    def finished(self):
        return not self.body

    def close(self):
        self.events.append(("close", self.clock.peek(), None))


SCENARIOS = [
    # (label, stage at which the clock jumps, delta from deadline in us)
    ("deadline reached exactly during connect", "open", 0),
    ("deadline passed by 1us during connect", "open", 1),
    ("connect ends 5us before the deadline", "open", -5),
    ("deadline reached exactly during the request write", "write", 0),
    ("deadline reached exactly while reading the status line", "read_head", 0),
    ("deadline reached exactly while reading the body", "read_body", 0),
]


def run_scenarios(make_transport, request) -> None:
    start = c.START
    deadline = c.add(start, seconds=60)
    for label, stage, delta in SCENARIOS:
        clock = ProbeClock(start)
        conn = StageConnection(clock, deadline, stage, delta)
        transport = make_transport(conn)
        result = transport.send(request, clock=clock, deadline_at=deadline)
        dl = c.parse(deadline)
        writes_late = [e for e in conn.events if e[0] == "write-begins" and e[1] >= dl]
        c.check(AREA, f"D1 {label}: no request byte written at/after the deadline", not writes_late,
                writes=conn.writes, late=[str(e[1]) for e in writes_late], outcome=result.outcome)
        bad_timeouts = []
        for op, at, timeout in conn.events:
            if op in ("open", "settimeout"):
                remaining = (dl - at).total_seconds()
                if timeout is None or timeout <= 0 or timeout > remaining + 1e-3:
                    bad_timeouts.append((op, str(at), timeout, round(remaining, 6)))
        c.check(AREA, f"D2 {label}: every blocking timeout is > 0 and <= the remaining time", not bad_timeouts,
                bad=bad_timeouts)
        if conn.writes:
            t0 = c.parse(result.request_started_at) if result.request_started_at else None
            ok = t0 is not None and t0 < dl and (conn.open_done_at is None or t0 >= conn.open_done_at)
            c.check(AREA, f"D3 {label}: T0 read after connect and before the write, and < deadline", ok,
                    T0=result.request_started_at, connect_done=str(conn.open_done_at))
        if result.outcome == "RESPONSE":
            t1 = c.parse(result.response_received_at)
            c.check(AREA, f"D4 {label}: a RESPONSE completed strictly before the deadline", t1 < dl,
                    T1=result.response_received_at, deadline=deadline)
        else:
            c.check(AREA, f"D4 {label}: outcome after the deadline is NO_RESPONSE/TRUNCATED",
                    result.outcome in ("NO_RESPONSE", "TRUNCATED"), outcome=result.outcome)


@p.guarded(AREA, "candidate transport binding")
def candidate(repo: Path) -> None:
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi.transport_http import HttpsTransport
    from genesis_adapters.secrets import Secret

    policy = load_policy(repo / "adapters" / "config" / "oddspapi_slice1_policy.json")
    request = c.odds_item(repo).request

    def make(conn):
        return HttpsTransport(Secret(c.SENTINEL), credential_param="apiKey", policy=policy, connection_factory=conn)

    run_scenarios(make, request)


@p.guarded(AREA, "D5 runner deadline binding")
def runner_level(repo: Path) -> None:
    from genesis_adapters.config import load_policy

    policy = load_policy(repo / "adapters" / "config" / "oddspapi_slice1_policy.json")
    seen = {}
    body = c.fixture_bytes(repo, "odds_by_tournaments.json")

    class Recording(c.CountingTransport):
        def send(self, request, *, clock, deadline_at):
            seen["deadline_at"] = deadline_at
            return super().send(request, clock=clock, deadline_at=deadline_at)

    root = c.scratch("p20-")
    rt = c.open_runtime(repo, root, clock=c.StepClock(), transport=Recording(default=(200, c.JSON_HEADERS, body)))
    rt.acquire(c.odds_item(repo))
    rows = c.jsonl(root / "acquisition.jsonl")
    decided = next(r for r in rows if r["record_type"] == "acq_quota_decided")
    tq = decided.get("Tq") or decided.get("occurred_at")
    quota_row = next(r for r in c.quota_rows(root))
    c.check(AREA, "D5 deadline_at == Tq + request_timeout_seconds, Tq == the quota occurred_at",
            seen.get("deadline_at") == c.add(tq, seconds=policy.request_timeout_seconds)
            and quota_row.get("occurred_at") == tq,
            deadline_at=seen.get("deadline_at"), Tq=tq, quota_occurred_at=quota_row.get("occurred_at"),
            timeout_s=policy.request_timeout_seconds)
    c.remove(root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    candidate(repo)
    runner_level(repo)
    return p.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
