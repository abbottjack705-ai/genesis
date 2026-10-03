"""D01 (RA5-002): totality of the Date-header path.

Part 1 (pure): ``parse_http_date`` over a hostile corpus plus a seeded fuzz of date-shaped strings: it must return
None or an aware UTC datetime, never raise; ``RawCapture._skew_failure`` (which also subtracts) must never raise.
Part 2 (runner, live-like require_date=True and fixture mode): every unusable Date value -> a durable
``acq_completed{failure: CLOCK_SKEW}`` row, the quarantine row, the next-day suspension, no exception, and a restart
reconciles nothing (no orphan). Multiple Date headers are reported as observed (RFC 7231: Date is a singleton).
usage: d01_date_totality.py <seed> <fuzz_iterations>
"""
from boot import *
import random, sys, collections, datetime as dt
from genesis_adapters.oddspapi.raw_capture import parse_http_date
from genesis_adapters.oddspapi.acquisition import AcquisitionHalt

SEED, N = int(sys.argv[1]), int(sys.argv[2])
rng = random.Random(SEED)
GOOD = "Thu, 01 Oct 2026 12:00:30 GMT"
CORPUS = [
    "Mon, 01 Jan 99999999999 00:00:00 GMT", "Mon, 01 Jan 9999999999999999999999999 00:00:00 GMT",
    "Fri, 31 Dec 9999 23:59:59 GMT", "Sat, 01 Jan 10000 00:00:00 GMT", "Mon, 01 Jan 0001 00:00:00 GMT",
    "Mon, 01 Jan 0000 00:00:00 GMT", "Mon, 01 Jan -1 00:00:00 GMT", "Mon, 01 Jan 70 00:00:00 GMT",
    "Mon, 01 Jan 69 00:00:00 GMT", "Thu, 29 Feb 2026 12:00:00 GMT", "Tue, 29 Feb 2028 12:00:00 GMT",
    "Thu, 30 Feb 2026 12:00:00 GMT", "Thu, 01 Oct 2026 24:00:00 GMT", "Thu, 01 Oct 2026 23:59:60 GMT",
    "Thu, 01 Oct 2026 23:59:61 GMT", "Thu, 01 Oct 2026 12:00:30 UT", "Thu, 01 Oct 2026 12:00:30 UTC",
    "Thu, 01 Oct 2026 12:00:30 Z", "Thu, 01 Oct 2026 12:00:30 +0000", "Thu, 01 Oct 2026 12:00:30 -0000",
    "Thu, 01 Oct 2026 12:00:30 +0001", "Thu, 01 Oct 2026 12:00:30 EST", "Thu, 01 Oct 2026 12:00:30 +2400",
    "Thu, 01 Oct 2026 12:00:30 +9999", "Thu, 01 Oct 2026 12:00:30 -9999", "Thu, 01 Oct 2026 12:00:30",
    "Thursday, 01-Oct-26 12:00:30 GMT", "Thu Oct  1 12:00:30 2026", "2026-10-01T12:00:30Z", "", " ", "\t",
    "GMT", "Thu, 01 Oct 2026", "Thu, 01 Oct 2026 12:00:30 GMT\x00", "Thu, 01 Oct 2026 12:00:30 GMT\r\n",
    "Thu, 01 Oct 2026 12:00:30 GÉT", "Thu, 01 Oct 2026 12:00:30 ÿþ", "é" * 50,
    "Thu, 01 Oct " + "9" * 255 + " 12:00:30 GMT", "Thu, 01 Oct " + "9" * 5000 + " 12:00:30 GMT",
    "Thu, 01 Oct 2026 " + "9" * 400 + ":15:00 GMT", "Thu, 99999999999 Oct 2026 12:00:30 GMT",
    "Thu, 01 Oct 2026 12:00:30.999999 GMT", "Thu, 01 Oct 2026 12:00 GMT", "01 Oct 2026 12:00:30 GMT",
    "Thu, 01 Oct 2026 12:00:30 GMT GMT", "Thu, 01 Foo 2026 12:00:30 GMT", "Thu,, 01 Oct 2026 12:00:30 GMT",
    "Thu, 01 Oct 2026 12:00:30 +00:00", "Thu, 01 Oct 2026 12:00:30 +000000000000000000000000000000000",
    "Thu, 01 Oct 2026 -12:00:30 GMT", "Thu, -01 Oct 2026 12:00:30 GMT", "Thu, 1e9 Oct 2026 12:00:30 GMT",
    GOOD,
]

def pure(value):
    try:
        moment = parse_http_date(value)
    except BaseException as exc:
        return "RAISED:" + type(exc).__name__
    if moment is None:
        return "None"
    if moment.tzinfo is None or moment.utcoffset() != dt.timedelta(0):
        return "NOT_AWARE_UTC"
    return "aware"

stats = collections.Counter(); bad = []
for value in CORPUS:
    r = pure(value); stats[r] += 1
    if r.startswith(("RAISED", "NOT_AWARE")):
        bad.append((value[:60], r))
TOKENS = ["Mon", "Thu", ",", " ", "01", "1", "31", "32", "0", "-1", "Oct", "Feb", "XYZ", "2026", "99999999999",
          "9" * 30, "12:00:30", "24:00:00", "99:99:99", "12:00", "GMT", "UT", "+0000", "-0000", "+9999", "EST",
          "\x00", "é", ":", ".", "-", "+", "e", "9" * 400]
for _ in range(N):
    value = "".join(rng.choice(TOKENS) for _ in range(rng.randint(0, 12)))
    r = pure(value); stats[r] += 1
    if r.startswith(("RAISED", "NOT_AWARE")):
        bad.append((value[:60], r))
print("PART 1 pure parse_http_date: corpus=%d fuzz=%d seed=%d outcomes=%s" % (len(CORPUS), N, SEED, dict(stats)))
print("   escapes / non-UTC results:", bad[:10] if bad else "none")

def runner_case(date_headers, require_date):
    with scratch_root() as root:
        clock = FixedClock(START, step_micros=1000)
        headers = JSON + tuple(("Date", v) for v in date_headers)
        rt = open_rt(root, clock=clock, script=[odds_response(headers=headers)], require_date=require_date)
        try:
            out = rt.acquire(odds_item("w1"))
            res = "returned:%s" % (out.outcome.failure.value if out.outcome.failure else None)
        except AcquisitionHalt as h:
            res = "halt:%s" % h
        except BaseException as exc:
            res = "ESCAPE:%s" % type(exc).__name__
        rows = acquisition_rows(rt)
        kinds = [r["record_type"] for r in rows]
        completed = [r for r in rows if r["record_type"] == "acq_completed"]
        rt2 = reopen(rt)
        reconciled = rt2.runner.reconcile_after_restart()
        return {"result": res, "completed_failure": completed[-1]["failure"] if completed else "NO_COMPLETED_ROW",
                "quarantined": "acq_quarantined" in kinds, "suspended": "acq_sends_suspended" in kinds,
                "reconciled_on_restart": len(reconciled)}

print("PART 2 runner (T1 = 2026-10-01T12:00:00Z + transport stamps; the good value is within skew):")
outcomes = collections.Counter(); escapes = []
cases = [[v] for v in CORPUS] + [[GOOD, "garbage"], ["garbage", GOOD], ["X" * 300, GOOD], [GOOD, "X" * 300],
                                  [GOOD, "Mon, 01 Jan 99999999999 00:00:00 GMT"], ["Mon, 01 Jan 2001 00:00:00 GMT", GOOD]]
for req in (True, False):
    for dates in cases:
        r = runner_case(dates, req)
        usable = pure(dates[0]) == "aware" and len(dates[0]) <= 256
        key = (req, r["completed_failure"], r["quarantined"], r["suspended"], r["reconciled_on_restart"])
        outcomes[key] += 1
        if r["result"].startswith("ESCAPE") or r["completed_failure"] == "NO_COMPLETED_ROW" or r["reconciled_on_restart"]:
            escapes.append((dates, req, r))
        if len(dates) > 1 or dates[0] in (GOOD, "Fri, 31 Dec 9999 23:59:59 GMT", "X" * 300):
            print("   require_date=%s dates=%s -> %s" % (req, [d[:40] for d in dates], r))
print("   outcome classes (require_date, failure, quarantined, suspended, reconciled):")
for k, v in sorted(outcomes.items(), key=str):
    print("     %4d  %s" % (v, k))
print("   escapes / orphaned attempts:", escapes if escapes else "none")
