"""AREA B probes: hard send deadline (design 14.6 rule 3) at the real HttpsTransport and at the runner."""
from boot import *
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from genesis_adapters.oddspapi.transport_http import HttpsTransport
from genesis_adapters.secrets import Secret
from genesis_adapters.config import load_policy
from genesis_adapters.clock import ClockFault
from genesis_adapters.oddspapi import endpoints as ep
import ssl

pol = load_policy(CONFIG / "oddspapi_slice1_policy.json")
specs = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", pol)
req = ep.build_request(specs["META_SPORTS"])
TQ = "2026-10-03T10:00:00.000000Z"
DEADLINE = parp.iso_add(TQ, seconds=pol.request_timeout_seconds)
res = {}

class Conn:
    """Fake connection recording whether a request byte was written; lets a hook move the clock at each stage."""
    log = []
    def __init__(self, clock, hooks, body=b"{}"):
        self.clock, self.hooks, self.body, self.wrote, self.n = clock, hooks, body, False, 0
    def open(self, t): self.hooks.get("open", lambda: None)()
    def settimeout(self, t):
        self.n += 1
        self.hooks.get("settimeout", lambda n: None)(self.n)
    def write(self, m, t, h): self.wrote = True; self.hooks.get("write", lambda: None)()
    def read_head(self): self.hooks.get("head", lambda: None)(); return 200, [("content-type", "application/json")]
    def read_chunk(self, n):
        self.hooks.get("chunk", lambda: None)()
        b, self.body = self.body, b""; return b
    def finished(self): return self.body == b""
    def close(self): pass

def run(hooks, start_at, body=b"{}"):
    clock = FixedClock(start_at, step_micros=0)
    holder = {}
    def factory(host, port, ctx, addr):
        c = Conn(clock, {k: (lambda f=v: f(clock)) if k not in ("settimeout",) else (lambda n, f=v: f(clock, n)) for k, v in hooks.items()}, body)
        holder["c"] = c
        return c
    t = HttpsTransport(Secret("KEY-0123456789abcdefghij"), credential_param="apiKey", policy=pol, connection_factory=factory)
    try:
        r = t.send(req, clock=clock, deadline_at=DEADLINE)
        return holder.get("c"), r, None
    except BaseException as e:   # noqa
        return holder.get("c"), None, e

# a) clock exactly at the deadline at entry -> nothing opened
c, r, e = run({}, DEADLINE)
res["a_at_deadline_entry_no_open"] = (c is None, r.outcome if r else None)
# b) one microsecond before the deadline -> write happens (clock never advances)
c, r, e = run({}, parp.iso_add(DEADLINE, micros=-1))
res["b_deadline_minus_1us_writes"] = (bool(c and c.wrote), r.outcome if r else None)
# c) clock reaches the deadline inside open (slow connect/TLS) -> must NOT write
c, r, e = run({"open": lambda ck: ck.set(DEADLINE)}, parp.iso_add(DEADLINE, seconds=-5))
res["c_slow_connect_to_deadline_no_write"] = (bool(c.wrote), r.outcome)
# d) clock reaches deadline inside the 2nd settimeout (right before T0) -> must NOT write
c, r, e = run({"settimeout": lambda ck, n: ck.set(DEADLINE) if n == 1 else None}, parp.iso_add(DEADLINE, seconds=-5))
res["d_deadline_in_settimeout_no_write"] = (bool(c.wrote), r.outcome)
# e) clock passes the deadline DURING write (after the T0 check): the write is the boundary event
c, r, e = run({"write": lambda ck: ck.set(parp.iso_add(DEADLINE, seconds=1))}, parp.iso_add(DEADLINE, micros=-1))
res["e_deadline_crossed_during_write"] = (bool(c.wrote), r.outcome, r.sanitized_error)
# f) deadline crossed while reading the head -> NO_RESPONSE/TRUNCATED, never RESPONSE
c, r, e = run({"head": lambda ck: ck.set(parp.iso_add(DEADLINE, seconds=1))}, parp.iso_add(DEADLINE, seconds=-5))
res["f_deadline_during_read_head"] = (r.outcome, r.http_status, r.sanitized_error)
# g) response whose LAST chunk completes after the deadline (clock moves in read_chunk)
c, r, e = run({"chunk": lambda ck: ck.set(parp.iso_add(DEADLINE, seconds=2))}, parp.iso_add(DEADLINE, seconds=-5))
res["g_last_chunk_after_deadline"] = (r.outcome, r.response_received_at, DEADLINE)
print(json.dumps(res, indent=1, default=str))
