"""AREA E: every rejected/quarantined 200-class outcome must stay unusable after restart (HA-04 class)."""
import gzip
from boot import *
from genesis_adapters.errors import AcquisitionHalt
from genesis_adapters.oddspapi import quiescence
from genesis_adapters.secrets import Secret
KEY = "AUD1T-Zq8vLm2XpR7tYk4WnB9cD3fHsJ"
base = parp.dump(parp.odds_payload())
def env_bad():
    p = parp.odds_payload(); return json.dumps({"data": p}).encode()
def date_skewed(): return JSON + (("date", http_date(parp.iso_add(START, seconds=-3600))),)
CASES = {
 "wrong content-type": ok(base, headers=(("content-type", "text/html"),)),
 "malformed JSON": ok(b"[{", headers=JSON), "empty body": ok(b"", headers=JSON), "duplicate keys": ok(b'[{"a":1,"a":2}]', headers=JSON),
 "NaN": ok(b'[{"a":NaN}]', headers=JSON), "invalid UTF-8": ok(b"[\xff\xfe]", headers=JSON),
 "envelope wrong type (object not list)": ok(env_bad(), headers=JSON),
 "oversize body": ok(b"[" + b"0," * 5_000_000 + b"0]", headers=JSON),
 "clock skew (Date -1h)": ok(base, headers=date_skewed()),
 "secret echo": ok(base + b" " + KEY.encode(), headers=JSON),
 "nested content-encoding": ok(gzip.compress(base), headers=JSON + (("content-encoding", "gzip, gzip"),)),
 "HTTP 301": status(301, b"{}", headers=JSON), "HTTP 401": status(401, b"{}", headers=JSON), "HTTP 429": status(429, b"{}", headers=JSON),
 "HTTP 500 w/ valid body": status(500, base, headers=JSON), "TRUNCATED transport": truncated(base[:-5], headers=JSON),
}
for name, scripted in CASES.items():
    with scratch_root() as root:
        clock = FixedClock(START, step_micros=1000)
        sec = Secret(KEY)
        rt = open_rt(root, clock=clock, secret=sec, script=[odds_response(), scripted])
        rt.acquire(odds_item("w1")); approve(rt); n_before = len(pit_rows(rt)); clock.advance(seconds=900)
        try: out = rt.acquire(odds_item("w2")); first = (out.outcome.outcome, str(out.outcome.failure))
        except AcquisitionHalt as h: first = ("HALT", str(h.args[0]))
        except BaseException as e: first = ("EXC", type(e).__name__)
        rt2 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=120), step_micros=1000), secret=sec)
        try: rt2.resume(); rs = "ok"
        except BaseException as e: rs = "resume RAISED " + type(e).__name__
        rows = acquisition_rows(rt2)
        new_pit = len(pit_rows(rt2)) - n_before
        normalized = sum(1 for r in rows if r["record_type"] == "acq_normalized") - 1
        pend = quiescence.pending_work(rt2.stores)
        ent = sorted({r["entity_id"] for r in pit_rows(rt2)})[0]
        v = rt2.reader().head(ent, parp.iso_add(rt2.clock.peek(), seconds=5))
        print(f"{name:40s} first={first!s:46s} newPIT={new_pit} newNormalized={normalized} pending={bool(pend)} resume={rs} reader={type(v).__name__}:{getattr(getattr(v,'code',None),'value','')}")
