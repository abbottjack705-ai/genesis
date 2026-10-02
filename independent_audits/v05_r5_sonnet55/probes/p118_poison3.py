"""NEW (HIGH): three schema-valid 200 responses each wedge the adapter permanently (poison pill)."""
from boot import *
def variant(mutator, literal_map):
    p = parp.odds_payload(); mutator(p)
    return parp.dump_with(p, **literal_map) if literal_map else json.dumps(p, sort_keys=True).encode("ascii")
def first_player(p):
    fx = parp.fixture_of(p); mk = next(iter(fx["bookmakerOdds"]["pinnacle"]["markets"].values()))
    return next(iter(next(iter(mk["outcomes"].values()))["players"].values()))
def m_overflow(p): first_player(p)["changedAt"] = "@big"
def m_surrogate(p): first_player(p)["active"] = "\ud800"
def m_hugeid(p): parp.fixture_of(p)["participant1Id"] = int("9" * 70)
CASES = {"A_changedAt_1E+999999999 (decimal.Overflow @parser.py:204)": (m_overflow, {"big": "1E+999999999"}),
         "B_active_lone_surrogate (UnicodeEncodeError @repro.py:29)": (m_surrogate, None),
         "C_participant1Id_70_digits (IdentityTypeError @ids.py:58)": (m_hugeid, None)}
for name, (mut, lits) in CASES.items():
    raw = variant(mut, lits)
    with scratch_root() as root:
        clock = FixedClock(START, step_micros=1000)
        rt = open_rt(root, clock=clock, script=[odds_response(), ok(raw, headers=JSON)])
        rt.acquire(odds_item("w1")); approve(rt)
        ents = sorted({r["entity_id"] for r in pit_rows(rt)})
        clock.advance(seconds=900)
        res = {}
        try: rt.acquire(odds_item("w2")); res["acquire"] = "returned"
        except BaseException as e: res["acquire"] = "RAISED " + type(e).__name__
        completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"][-1]
        res["completed_row"] = (completed["outcome"], completed["http_status"], completed["failure"], "raw_stored=" + str(completed["raw_observation_id"] is not None))
        rt2 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=100), step_micros=1000), transport=FakeTransport([odds_response()]))
        try: rt2.resume(); res["restart_resume"] = "ok"
        except BaseException as e: res["restart_resume"] = "RAISED " + type(e).__name__
        # a LATER healthy capture, then the reader
        rt3 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=900), step_micros=1000), transport=FakeTransport([odds_response()]))
        try: rt3.acquire(odds_item("w3")); res["later_healthy_capture"] = "ok"
        except BaseException as e: res["later_healthy_capture"] = "RAISED " + type(e).__name__
        rt4 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=1800), step_micros=1000))
        v = rt4.reader().head(ents[0], parp.iso_add(rt4.clock.peek(), seconds=30))
        res["reader_after_later_healthy_capture"] = type(v).__name__ + ":" + str(getattr(getattr(v, "code", None), "value", "")) + " | " + str(getattr(v, "detail", ""))[:70]
        print(name); [print("   ", k, "=", v) for k, v in res.items()]
