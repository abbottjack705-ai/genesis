from boot import *
from genesis_adapters.oddspapi import emit
def kick_much_earlier(p):
    for f in p:
        if f["fixtureId"].endswith("1761301153"):
            f["startTime"] = "2026-10-01T12:20:00.000Z"
    return p
cm = scratch_root(); root = cm.__enter__()
clock = FixedClock(START, step_micros=1000)
rt = open_rt(root, clock=clock, script=[odds_response(), odds_response(kick_much_earlier(parp.odds_payload()))])
rt.acquire(odds_item("w1")); approve(rt)
clock.advance(seconds=600); out = rt.acquire(odds_item("w2"))
ent = [d["entity_id"] for d in documents(rt) if d["provider_fixture_id"]["value"].endswith("1761301153") and d["bookmaker_id"].endswith("pinnacle") and d["market_family"] == "SOCCER_1X2_FT"][0]
pits = sorted([r for r in pit_rows(rt) if r["entity_id"] == ent], key=lambda r: r["valid_from"])
print("states:", [json.loads(rt.stores.evidence.get_bytes(r["payload_hash"]))["market_state"] for r in pits], "valid_to:", [r["valid_to"] for r in pits])
rr = rt.reader()
for label, D in (("D in newer window", parp.iso_add(pits[-1]["ready_at"], seconds=5)), ("D after newer.valid_to, older still in TTL", parp.iso_add(pits[-1]["valid_to"], seconds=1))):
    v = rr.head(ent, D); print(label, type(v).__name__, getattr(getattr(v, "code", None), "value", ""))
