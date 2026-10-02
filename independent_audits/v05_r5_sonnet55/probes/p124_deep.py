from boot import *
import sys
def first_player(p):
    fx = parp.fixture_of(p); mk = next(iter(fx["bookmakerOdds"]["pinnacle"]["markets"].values()))
    return next(iter(next(iter(mk["outcomes"].values()))["players"].values()))
print("recursionlimit", sys.getrecursionlimit())
for depth in (50, 200, 400, 480, 600, 900, 990):
    p = parp.odds_payload()
    nest = "0"
    text_nest = "[" * depth + "0" + "]" * depth
    first_player(p)["betslip"] = "@deep"
    raw = parp.dump_with(p, deep=text_nest)
    try:
        r = parp.parse(raw); st = "parsed failure=%s" % (r.failure,)
        if r.failure is None: parp.documents(r)
    except BaseException as e:
        st = "ESCAPED " + type(e).__name__
    print("depth", depth, st)
