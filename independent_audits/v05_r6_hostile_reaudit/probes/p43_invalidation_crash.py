"""AREA G: crash inside emit_invalidation at every checkpoint, restart (also crash DURING the restart's completion), never revive."""
from boot import *
from genesis_adapters.oddspapi import emit
STEPS = ["after_recorded", "after_invalidation_observation", "after_invalidation_pit"]
def setup():
    cm = scratch_root(); root = cm.__enter__()
    clock = FixedClock(START, step_micros=1000)
    rt = open_rt(root, clock=clock, script=[odds_response()])
    rt.acquire(odds_item("w1")); approve(rt)
    row = sorted(pit_rows(rt), key=lambda r: r["entity_id"])[0]
    obs = [o for o in rt.stores.evidence.get_observations(row["payload_hash"]) if o.contract_id == rt.stores.contract_id][0]
    clock.advance(seconds=60)
    return cm, root, rt, clock, row, obs
def hook(step, nth=1):
    seen = {"n": 0}
    def h(name):
        if name == step:
            seen["n"] += 1
            if seen["n"] == nth: raise Crash()
    return h
for first in STEPS:
    for second in (None,) + tuple(STEPS):
        cm, root, rt, clock, row, obs = setup()
        try:
            emit.emit_invalidation(invalidated_observation_id=obs.observation_id, invalidation_class="OPERATOR", reason="INVALIDATED", actor="OPERATOR",
                                   evidence_refs=("p43",), stores=rt.stores, clock=clock, checkpoint=hook(first))
        except Crash: pass
        pre = [type(rt.reader().head(row["entity_id"], parp.iso_add(clock.peek(), seconds=k))).__name__ for k in (1, 5)]
        res = []
        for attempt in range(3):                      # restart(s); the first may itself crash at `second`
            rt2 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=100 * (attempt + 1)), step_micros=1000))
            try:
                emit.complete_pending_invalidations(rt2.stores, clock=rt2.clock) if not (second and attempt == 0) else (_ for _ in ()).throw(RuntimeError)
            except RuntimeError:
                try: emit.emit_invalidation(invalidated_observation_id=obs.observation_id, invalidation_class="OPERATOR", reason="INVALIDATED", actor="OPERATOR", evidence_refs=("p43",), stores=rt2.stores, clock=rt2.clock, checkpoint=hook(second))
                except Crash: res.append("crash@" + second)
        rt3 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=1000), step_micros=1000))
        emit.complete_pending_invalidations(rt3.stores, clock=rt3.clock)
        D = parp.iso_add(rt3.clock.peek(), seconds=30)
        v = rt3.reader().head(row["entity_id"], D)
        hist = rt3.reader().head(row["entity_id"], parp.iso_add(row["ready_at"], seconds=1))
        pitn = len([r for r in pit_rows(rt3) if r["entity_id"] == row["entity_id"]])
        print(f"crash1={first:32s} crash2={str(second):32s} preRestartReader={pre} final={type(v).__name__}:{getattr(getattr(v,'code',None),'value','')} history={type(hist).__name__} pit_rows_for_entity={pitn} invalidations={len(rt3.stores.invalidations.state())}")
        cm.__exit__(None, None, None)
