from boot import *
def first_player(p):
    fx = parp.fixture_of(p); mk = next(iter(fx["bookmakerOdds"]["pinnacle"]["markets"].values()))
    return fx, mk, next(iter(mk["outcomes"].values())), 
def states(raw, **ov):
    r = parp.parse(raw, **ov)
    out = {}
    for b in r.books:
        if b.entity_id and parp.FIXTURE_A and True:
            out.setdefault((b.state, tuple(b.reasons)), 0); out[(b.state, tuple(b.reasons))] += 1
    return r.failure, dict(out)
p = parp.odds_payload(); fx = parp.fixture_of(p)
del fx["startTime"]
print("startTime absent, no join      ->", states(parp.dump(p)))
p = parp.odds_payload(); parp.fixture_of(p)["startTime"] = None
print("startTime null, no join        ->", states(parp.dump(p)))
p = parp.odds_payload(); parp.fixture_of(p)["startTime"] = "2026-10-03T14:00:00+01:00"
print("startTime +01:00 offset        ->", states(parp.dump(p)))
p = parp.odds_payload(); fx = parp.fixture_of(p)
mk = fx["bookmakerOdds"]["pinnacle"]["markets"]; m1 = next(iter(mk.values())); oc = next(iter(m1["outcomes"].values())); pl = next(iter(oc["players"].values()))
pl["price"] = None
print("ACTIVE outcome price null      ->", states(parp.dump(p)))
pl["active"] = False
print("INACTIVE outcome price null    ->", states(parp.dump(p)))
p = parp.odds_payload(); fx = parp.fixture_of(p); fx["bookmakerOdds"]["pinnacle"]["bookmakerIsActive"] = False
print("bookmakerIsActive false        ->", states(parp.dump(p)))
p = parp.odds_payload(); fx = parp.fixture_of(p); fx["bookmakerOdds"]["pinnacle"]["bookmakerIsActive"] = "yes"
print("bookmakerIsActive 'yes'        ->", states(parp.dump(p)))
p = parp.odds_payload(); fx = parp.fixture_of(p); fx["bookmakerOdds"]["pinnacle"].pop("bookmakerIsActive", None)
print("bookmakerIsActive absent       ->", states(parp.dump(p)))
