"""NEW: a schema-valid 200 response whose price literal overflows the parser's Decimal context wedges the runtime."""
from boot import *
R = {}
def poisoned(literal="1E+999999999"):
    p = parp.odds_payload(); fx = parp.fixture_of(p)
    mk = next(iter(fx["bookmakerOdds"]["pinnacle"]["markets"].values())); oc = next(iter(mk["outcomes"].values())); pl = next(iter(oc["players"].values()))
    pl["price"] = "@big"
    return parp.dump_with(p, big=literal)
with scratch_root() as root:
    clock = FixedClock(START, step_micros=1000)
    rt = open_rt(root, clock=clock, script=[odds_response(), ok(poisoned(), headers=JSON), odds_response()])
    rt.acquire(odds_item("w1")); approve(rt)
    ents = sorted({r["entity_id"] for r in pit_rows(rt)})
    R["healthy_before"] = type(rt.reader().head(ents[0], parp.iso_add(clock.peek(), seconds=1))).__name__
    clock.advance(seconds=900)
    try:
        rt.acquire(odds_item("w2")); R["poison_acquire"] = "returned"
    except BaseException as e:
        R["poison_acquire"] = "RAISED " + type(e).__name__
    R["acq_rows"] = [r["record_type"] + (":" + str(r.get("failure")) if r["record_type"] == "acq_completed" else "") for r in acquisition_rows(rt)][-4:]
    # restart, as the operator would
    for n in (1, 2):
        try:
            rt2 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=100 * n), step_micros=1000))
            rt2.resume(); R[f"restart_{n}_resume"] = "ok"
        except BaseException as e:
            R[f"restart_{n}_resume"] = "RAISED " + type(e).__name__
    # reader after restart
    try:
        rt3 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=500), step_micros=1000))
        v = rt3.reader().head(ents[0], parp.iso_add(rt3.clock.peek(), seconds=30))
        R["reader_after_restart"] = type(v).__name__ + ":" + str(getattr(getattr(v, "code", None), "value", "")) + " " + str(getattr(v, "detail", ""))[:60]
    except BaseException as e:
        R["reader_after_restart"] = "RAISED " + type(e).__name__
    # can a later healthy capture be taken at all?
    try:
        rt4 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=800), step_micros=1000), transport=FakeTransport([odds_response()]))
        out = rt4.acquire(odds_item("w3")); R["next_healthy_capture_after_wedge"] = out.outcome.outcome
    except BaseException as e:
        R["next_healthy_capture_after_wedge"] = "RAISED " + type(e).__name__
for k, v in R.items(): print(f"{k:34s}", v)
