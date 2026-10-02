from boot import *
import time, resource
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
def one(label, literal, where="price"):
    p = parp.odds_payload()
    fx = parp.fixture_of(p)
    outs = parp.market_of(p, "pinnacle", "101")["outcomes"] if "101" in fx["bookmakerOdds"]["pinnacle"]["markets"] else None
    print(label[:48], end=" ")
    # find first price field
    mk = next(iter(fx["bookmakerOdds"]["pinnacle"]["markets"].values()))
    oc = next(iter(mk["outcomes"].values()))
    pl = next(iter(oc["players"].values()))
    pl["price"] = "@big"
    raw = parp.dump_with(p, big=literal)
    t = time.time()
    try:
        r = parp.parse(raw)
        print("parsed OK in", round(time.time() - t, 2), "s;", [b.state for b in r.books][:4])
    except BaseException as e:
        print("EXC", type(e).__name__, str(e)[:60], round(time.time() - t, 2), "s")
for lbl, lit in (("price 1E+999999999", "1E+999999999"), ("price 1E-999999999", "1E-999999999"), ("price 9"+"9"*3000, "9"+"9"*3000),
                 ("price 1.0000000000000000000000000000000001", "1.0000000000000000000000000000000001"), ("price -0", "-0"), ("price 1e0", "1e0")):
    one(lbl, lit)
