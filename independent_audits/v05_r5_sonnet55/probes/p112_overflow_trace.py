from boot import *
import traceback
p = parp.odds_payload(); fx = parp.fixture_of(p)
mk = next(iter(fx["bookmakerOdds"]["pinnacle"]["markets"].values())); oc = next(iter(mk["outcomes"].values())); pl = next(iter(oc["players"].values()))
pl["price"] = "@big"
raw = parp.dump_with(p, big="1E+999999999")
try:
    parp.parse(raw)
except BaseException:
    traceback.print_exc()
