"""AREA F: older usable + newer stale/suspended/invalidated; cutoffs around availability; no fallback."""
from boot import *
from genesis_adapters.oddspapi import emit
import copy
R = {}
def setup(second_mod):
    cm = scratch_root(); root = cm.__enter__()
    clock = FixedClock(START, step_micros=1000)
    rt = open_rt(root, clock=clock, script=[odds_response(), odds_response(second_mod(parp.odds_payload()))])
    rt.acquire(odds_item("w1")); approve(rt)
    clock.advance(seconds=600)
    rt.acquire(odds_item("w2"))
    return cm, root, rt, clock
def book_entity(rt, fixture_suffix="1761301153", bk="pinnacle"):
    for d in documents(rt):
        if d.get("provider_fixture_id", {}).get("value", "").endswith(fixture_suffix) and d["bookmaker_id"].endswith(bk) and d["market_family"] == "SOCCER_1X2_FT":
            return d["entity_id"]
def reads(rt, entity, cutoffs):
    rr = rt.reader()
    out = {}
    for label, D in cutoffs:
        v = rr.head(entity, D)
        out[label] = type(v).__name__ + (":" + v.code.value if hasattr(v, "code") else "")
    return out
# 1) newer capture SUSPENDED
def suspend(p):
    for o in p[0]["bookmakerOdds"]["pinnacle"]["markets"].values():
        for oc in o["outcomes"].values():
            for pl in oc["players"].values() if "players" in oc else []: pass
    return p
rows1 = None
cm, root, rt, clock = setup(lambda p: p)   # identical second capture -> newer OPEN
ent = book_entity(rt)
pits = [r for r in pit_rows(rt) if r["entity_id"] == ent]
t1a, t1b = sorted(r["valid_from"] for r in pits)[:2]
t3b = max(r["ready_at"] for r in pits)
R["1_two_open_captures_cutoffs"] = reads(rt, ent, [("D<T3_new", parp.iso_add(t3b, micros=-1)), ("D=T3_new", t3b), ("D>T3_new", parp.iso_add(t3b, seconds=1))])
# valid_to / TTL edges for the newer head
doc_new = [d for d in documents(rt) if d["entity_id"] == ent and d["valid_from"] == t1b][0]
vt = doc_new["valid_to"]
R["1b_ttl_edges"] = reads(rt, ent, [("vt-1us", parp.iso_add(vt, micros=-1)), ("vt", vt), ("vt+1us", parp.iso_add(vt, micros=1))])
cm.__exit__(None, None, None)
# 2) newer capture with kickoff moved EARLIER so newer valid_to < older valid_to (older still inside its TTL)
def kick_earlier(p):
    for f in p:
        if f["fixtureId"].endswith("1761301153"):
            f["startTime"] = "2026-10-01T13:30:00.000Z"      # S = 13:30, guard 300s -> valid_to 13:25 ; T1_new ~12:10
    return p
cm, root, rt, clock = setup(kick_earlier)
ent = book_entity(rt)
pits = sorted([r for r in pit_rows(rt) if r["entity_id"] == ent], key=lambda r: r["valid_from"])
old, new = pits[0], pits[-1]
R["2_newer_valid_to"] = (new["valid_to"], "older_valid_to", old["valid_to"])
mid = parp.iso_add(new["valid_to"], seconds=1)
R["2_older_usable_newer_expired"] = reads(rt, ent, [("D=newer.valid_to+1s (older still in TTL)", mid)])
cm.__exit__(None, None, None)
# 3) newer capture where the event is no longer pre-match (blocked)
def not_prematch(p):
    for f in p:
        if f["fixtureId"].endswith("1761301153"): f["statusId"] = 1; f["statusName"] = "Live"
    return p
cm, root, rt, clock = setup(not_prematch)
ent = book_entity(rt)
pits = sorted([r for r in pit_rows(rt) if r["entity_id"] == ent], key=lambda r: r["valid_from"])
R["3_newer_blocked_event_not_prematch"] = reads(rt, ent, [("after", parp.iso_add(pits[-1]["ready_at"], seconds=2))]) , [json.loads(rt.stores.evidence.get_bytes(r["payload_hash"]))["market_state"] for r in pits]
cm.__exit__(None, None, None)
# 4) invalidation then restart: old price must not revive
cm, root, rt, clock = setup(lambda p: p)
ent = book_entity(rt)
pits = sorted([r for r in pit_rows(rt) if r["entity_id"] == ent], key=lambda r: r["valid_from"])
head = pits[-1]
obs = [o for o in rt.stores.evidence.get_observations(head["payload_hash"]) if o.contract_id == rt.stores.contract_id][0]
clock.advance(seconds=30)
res = emit.emit_invalidation(invalidated_observation_id=obs.observation_id, invalidation_class="OPERATOR", reason=F.INVALIDATED.value if hasattr(F, "INVALIDATED") else "INVALIDATED", actor="OPERATOR", evidence_refs=("probe",), stores=rt.stores, clock=clock)
R["4_invalidated_head_effect"] = res.head_effect
rt2 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=100), step_micros=1000))
rt2.resume()
D = parp.iso_add(rt2.clock.peek(), seconds=10)
R["4_after_restart_new_head"] = reads(rt2, ent, [("D>T3_inv", D), ("D=just after first capture T3 (history)", parp.iso_add(pits[0]["ready_at"], seconds=1)),
                                                 ("D between newer.T3 and T3_inv (history)", parp.iso_add(head["ready_at"], seconds=1))])
# older record cannot revive: query the older record's entity at far later cutoff within its TTL
R["4_older_price_never_revives_within_ttl"] = reads(rt2, ent, [("D=T3_inv+1s", parp.iso_add(res.t_inv, seconds=1))])
cm.__exit__(None, None, None)
for k, v in R.items(): print(f"{k:44s}", v)
