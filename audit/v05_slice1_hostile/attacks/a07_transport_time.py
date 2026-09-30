"""Area 7 (HA-008, TX-01, BND-01/02/04): transport exception boundary, deadline and time rules.

1. The candidate's ``boundary_guard`` against ``oracle/EXPECTED_BOUNDARY_EDGES.json`` (every boundary,
   every edge, the permit verdict, a failing W named by the oracle, the reschedule instant).
2. In-process TX-01 variant with an auditor fault-injecting connection: ordinary failures carrying the keyed
   URL (message, args, notes, cause, context, ``url``/``filename`` attributes, a warning) at every stage;
   ``KeyboardInterrupt(url)``; ``SystemExit(37)``, ``SystemExit(url)``, ``SystemExit(None)``.
3. Hard deadline: ``T0 >= deadline`` writes nothing; a server that is too slow is cut at the deadline.
4. HA-008: a stuck clock never yields ``T1 <= T0`` silently (the runner halts ``CLOCK_FAULT``); a coarse
   16 ms clock yields ``T1 > T0``; a stuck wall clock under ``SystemUtcClock`` raises ``ClockFault``.

    python -B attacks/a07_transport_time.py --repo <candidate> --edges oracle/EXPECTED_BOUNDARY_EDGES.json
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import sys
import time
import traceback
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402


def forms(key: str) -> list[bytes]:
    raw = key.encode()
    out = [raw, raw.lower(), key.encode("utf-16-le"), raw.hex().encode(), base64.b64encode(raw).rstrip(b"="),
           "".join(f"%{b:02X}" for b in raw).encode()]
    width = max(8, -(-len(key) // 3))
    out += [key[i:i + width].encode() for i in range(0, len(key) - width + 1, 4)]
    return out


def dirty(text: str, key: str) -> bool:
    data = text.encode("utf-8", "replace")
    low = data.lower()
    return any(f.lower() in low for f in forms(key))


class FaultConnection:
    """Auditor connection: fails at ``stage`` with ``make(target_seen)``; otherwise serves ``body``."""

    def __init__(self, stage, make, body=b"[]", clock=None, slow_until=None):
        self.stage, self.make, self.body, self.clock, self.slow_until = stage, make, body, clock, slow_until
        self.target = None
        self.sent = 0
        self.closed = False

    def __call__(self, host, port, context, address):
        return self

    def _maybe(self, stage):
        if stage == self.stage:
            raise self.make(self.target or "https://api.oddspapi.io/v4/odds?apiKey=" + c.SENTINEL)

    def open(self, timeout):
        self._maybe("connect")

    def settimeout(self, timeout):
        pass

    def write(self, method, target, headers):
        self.target = target
        self.sent += 1
        if self.stage == "warn":
            warnings.warn("request to " + target)
        self._maybe("write")

    def read_head(self):
        self._maybe("read_head")
        return 200, [("Content-Type", "application/json"), ("Content-Length", str(len(self.body)))]

    def read_chunk(self, size):
        self._maybe("read_body")
        if self.slow_until is not None:
            self.clock.jump(self.slow_until)
        size = min(size, 100)                          # small chunks so a slow server spans the deadline
        data, self.body = self.body[:size], self.body[size:]
        return data

    def finished(self):
        return not self.body

    def close(self):
        self.closed = True


def ordinary(url):
    exc = OSError(5, "boom " + url)
    exc.url = url
    exc.filename = url
    exc.add_note(url)
    try:
        try:
            raise ValueError(url)
        except ValueError as inner:
            raise exc from inner
    except OSError as chained:
        return chained


def transport(repo, clock, conn):
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi.transport_http import HttpsTransport
    from genesis_adapters.secrets import Secret

    policy = load_policy(repo / "adapters" / "config" / "oddspapi_slice1_policy.json")
    return HttpsTransport(Secret(c.SENTINEL), credential_param="apiKey", policy=policy, connection_factory=conn), policy


def boundary(repo: Path, edges: dict) -> None:
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi.acquisition import boundary_guard

    policy = load_policy(repo / "adapters" / "config" / "oddspapi_slice1_policy.json")
    c.check("A7", "policy timeout/skew equal the oracle's edge-table inputs",
            (policy.request_timeout_seconds, policy.clock_skew_max_seconds)
            == (edges["policy"]["request_timeout_seconds"], edges["policy"]["clock_skew_max_seconds"]))
    bad = []
    for name, grid in edges["grid"].items():
        for label, row in grid.items():
            got = boundary_guard(row["Tq"], policy)
            failing = [w for w in ("W1", "W2", "W3", "W4") if not row[w]]
            if got.permitted != row["send"] or (not got.permitted and got.failed not in failing):
                bad.append((name, label, got.permitted, got.failed, row["send"], failing))
            if not got.permitted:
                # reschedule: first permitted instant = boundary + skew, and it must itself be permitted
                nxt = got.next_permitted
                if nxt is None or not boundary_guard(nxt, policy).permitted \
                        or boundary_guard(c.add(nxt, micros=-1), policy).permitted:
                    bad.append((name, label, "reschedule", nxt))
    c.check("A7", "boundary_guard equals the oracle W1-W4 table at every edge of 6 boundaries (and reschedules "
                  "to the first permitted microsecond)", not bad, mismatches=bad[:8])


def tx01(repo: Path) -> None:
    for stage in ("connect", "write", "read_head", "read_body"):
        clock = c.StepClock()
        conn = FaultConnection(stage, ordinary)
        tr, _ = transport(repo, clock, conn)
        request = c.odds_item(repo).request
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            result = tr.send(request, clock=clock, deadline_at=c.add(c.START, seconds=60))
        text = repr(result) + json.dumps(result.sanitized_error)
        c.check("A7", f"TX-01 ordinary failure at {stage} -> sanitized result, class/errno only, nothing leaks",
                result.outcome in ("NO_RESPONSE", "TRUNCATED") and set(result.sanitized_error) == {"class", "errno"}
                and not dirty(text, c.SENTINEL) and not seen,
                outcome=result.outcome, error=result.sanitized_error, warnings=len(seen))
    clock = c.StepClock()
    tr, _ = transport(repo, clock, FaultConnection("warn", lambda url: None))
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        result = tr.send(c.odds_item(repo).request, clock=clock, deadline_at=c.add(c.START, seconds=60))
    c.check("A7", "TX-01 a warning naming the keyed URL is swallowed inside the send path",
            not seen and result.outcome == "RESPONSE", outcome=result.outcome, warnings=len(seen))

    cases = [("KeyboardInterrupt(url)", lambda url: KeyboardInterrupt(url), KeyboardInterrupt, ()),
             ("SystemExit(37)", lambda url: SystemExit(37), SystemExit, (37,)),
             ("SystemExit(url)", lambda url: SystemExit(url), SystemExit, (1,)),
             ("SystemExit(None)", lambda url: SystemExit(None), SystemExit, ())]
    for label, make, kind, args in cases:
        def maker(url, make=make):
            exc = make(url)
            exc.add_note(url)
            exc.__cause__ = ValueError(url)
            return exc
        clock = c.StepClock()
        tr, _ = transport(repo, clock, FaultConnection("write", maker))
        caught = None
        try:
            tr.send(c.odds_item(repo).request, clock=clock, deadline_at=c.add(c.START, seconds=60))
        except BaseException as exc:                      # the auditor harness is the "top level" here
            caught = exc
        leak = False
        frames = []
        tb = caught.__traceback__ if caught is not None else None
        while tb is not None:
            for name, value in tb.tb_frame.f_locals.items():
                try:
                    if dirty(repr(value), c.SENTINEL):
                        leak = True
                        frames.append((tb.tb_frame.f_code.co_name, name))
                except Exception:
                    pass
            tb = tb.tb_next
        ok = (type(caught) is kind and caught.args == args and caught.__cause__ is None
              and caught.__context__ is None and not getattr(caught, "__notes__", None) and not leak
              and caught.__suppress_context__)
        c.check("A7", f"TX-01 {label} arrives as a fresh {kind.__name__}{args} from None; no keyed frame local",
                ok, got=type(caught).__name__ if caught else None, args=getattr(caught, "args", None),
                cause=repr(getattr(caught, "__cause__", None)), context=repr(getattr(caught, "__context__", None)),
                notes=getattr(caught, "__notes__", None), leaking_locals=frames)


def deadline(repo: Path) -> None:
    clock = c.StepClock()
    conn = FaultConnection(None, None)
    tr, _ = transport(repo, clock, conn)
    result = tr.send(c.odds_item(repo).request, clock=clock, deadline_at=c.START)   # T0 == deadline
    c.check("A7", "BND-04: T0 at/after the deadline -> nothing written, NO_RESPONSE",
            conn.sent == 0 and result.outcome == "NO_RESPONSE", sent=conn.sent, outcome=result.outcome)
    clock = c.StepClock()
    conn = FaultConnection(None, None, body=b"[" + b"1," * 5000 + b"1]", clock=clock, slow_until=30)
    tr, _ = transport(repo, clock, conn)
    result = tr.send(c.odds_item(repo).request, clock=clock, deadline_at=c.add(c.START, seconds=60))
    c.check("A7", "BND-04: a slow body is cut at the deadline (TRUNCATED/NO_RESPONSE, never a late RESPONSE)",
            result.outcome in ("TRUNCATED", "NO_RESPONSE"), outcome=result.outcome, error=result.sanitized_error)


def clocks(repo: Path) -> None:
    from genesis_adapters.clock import ClockFault, SystemUtcClock
    from genesis_adapters.oddspapi.transport_http import _reading_after

    stuck = c.StuckClock(c.START)
    started = time.monotonic()
    value = _reading_after(stuck, c.START, 300)
    waited = time.monotonic() - started
    c.check("A7", "HA-008: a stuck clock is re-read only within the drift budget and returned as read (no invented T1)",
            value == c.START and waited < 2.0, waited_s=round(waited, 3), reads=stuck.reads)

    class Coarse:
        def __init__(self, tick_ms=16):
            self.tick = tick_ms * 10 ** 6

        def now(self):
            ns = (time.time_ns() // self.tick) * self.tick
            return c.iso(c.parse("1970-01-01T00:00:00.000000Z") + __import__("datetime").timedelta(microseconds=ns // 1000))

    coarse = Coarse()
    t0 = coarse.now()
    t1 = _reading_after(coarse, t0, 1000)
    c.check("A7", "HA-008: a 16 ms clock yields T1 strictly after T0", c.parse(t1) > c.parse(t0), t0=t0, t1=t1)

    frozen_wall = time.time_ns()
    clock = SystemUtcClock(drift_max_ms=200, wall_ns=lambda: frozen_wall, mono_ns=time.monotonic_ns)
    fault = None
    try:
        _reading_after(clock, clock.now(), 5000)
    except ClockFault as exc:
        fault = exc.code
    c.check("A7", "HA-008: a stuck wall clock under SystemUtcClock raises ClockFault within the drift budget",
            fault == "WALL_CLOCK_JUMP", fault=fault)

    # runner level: a transport whose T1 equals T0 must halt the runner, never record a RESPONSE
    from genesis_adapters.errors import AcquisitionHalt
    from genesis_adapters.oddspapi.transport import TransportResult

    class EqualTimes:
        sends = 0

        def send(self, request, *, clock, deadline_at):
            self.sends += 1
            t = clock.now()
            return TransportResult("RESPONSE", 200, c.JSON_HEADERS, b"[]", None, t, t)

    root = c.scratch("clk-")
    rt = c.open_runtime(repo, root, clock=c.StepClock(), transport=EqualTimes())
    halted = None
    try:
        rt.acquire(c.odds_item(repo))
    except AcquisitionHalt as exc:
        halted = str(getattr(exc, "code", exc))
    rows = c.jsonl(root / "acquisition.jsonl")
    kinds = [r["record_type"] for r in rows]
    c.check("A7", "HA-008: T1 == T0 from a transport halts the runner CLOCK_FAULT; no RESPONSE row, no evidence",
            halted is not None and "CLOCK_FAULT" in halted and "acq_halted" in kinds
            and not any(r.get("outcome") == "RESPONSE" for r in rows)
            and not (root / "evidence" / "objects").exists(), halted=halted, rows=kinds)
    c.remove(root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--edges", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    boundary(repo, json.loads(Path(args.edges).read_text(encoding="utf-8")))
    tx01(repo)
    deadline(repo)
    clocks(repo)
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
