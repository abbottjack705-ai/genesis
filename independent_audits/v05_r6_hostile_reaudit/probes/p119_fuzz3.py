"""Fuzz 2: wider mutation operators; group escaping exceptions by (class, raising source line)."""
from boot import *
import random, collections, copy, traceback, sys
rng = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 12000
LITS = ["1E+999999999", "1E-999999999", "-1E+999999999", "1E+999999", "1E+1000000", "0E+999999999", "1e5", "-0", "-0.0", "0e0", "9" * 70, "9" * 400, "1" + "0" * 4200,
        '"2.5"', '"abc"', '""', "true", "false", "null", "[]", "{}", '"\\ud800"', '"\\udfff"', '"\\u0000"', '"\\n"', '"a\\nb"', '"\\u00e9"', '"\\ud83d\\ude00"', '"x" ',
        '"2026-10-03T14:00:00.000Z"', '"9999-12-31T23:59:59.999Z"', '"0001-01-01T00:00:00.000Z"', '"2026-10-03T14:00:00+99:99"', '"2026-02-30T14:00:00Z"', '"2026-10-03"',
        "10", "-1", "0", "1", "1000000000000000000000000", "18446744073709551616", "2.5", "1.0", "1.01", "1000.0001", '"1"', '"0"', "1.5", "[1,2]", '{"a":{"b":{"c":[]}}}',
        '"' + "A" * 100000 + '"', '"' + "\\ud800" * 10 + '"']
KEYS = ["x", "", "a" * 70, "\\ud800", "bookmakerOdds", "markets", "outcomes", "players", "price", "active", "fixtureId", "tournamentId"]
def paths(o, base=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield base + (k,); yield from paths(v, base + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield base + (i,); yield from paths(v, base + (i,))
def getp(o, path):
    for k in path: o = o[k]
    return o
def setp(o, path, v): getp(o, path[:-1])[path[-1]] = v
base = parp.odds_payload(); allp = list(paths(base))
groups = {}
def where(e):
    tb = e.__traceback__; last = None
    while tb is not None:
        f = tb.tb_frame.f_code.co_filename
        if "genesis_adapters" in f or "/genesis/" in f: last = (f.split("/")[-1], tb.tb_lineno)
        tb = tb.tb_next
    return last
for i in range(N):
    p = copy.deepcopy(base)
    ops = rng.choice((1, 1, 2, 3))
    for _ in range(ops):
        path = rng.choice(allp)
        try:
            op = rng.choice(("lit", "lit", "lit", "del", "addkey", "dupe"))
            if op == "lit": setp(p, path, "@L%d" % rng.randrange(3))
            elif op == "del":
                par = getp(p, path[:-1]) if len(path) > 1 else p
                if isinstance(par, dict): par.pop(path[-1], None)
            elif op == "addkey":
                tgt = getp(p, path)
                if isinstance(tgt, dict): tgt[rng.choice(KEYS)] = "@L%d" % rng.randrange(3)
            elif op == "dupe": setp(p, path, "@L0")
        except Exception: pass
    text = json.dumps(p, sort_keys=True)
    for j in range(3): text = text.replace('"@L%d"' % j, rng.choice(LITS))
    try: raw = text.encode("ascii") if text.isascii() else text.encode("utf-8", "surrogatepass")
    except Exception: continue
    try:
        _pr = parp.parse(raw)
        if _pr.failure is None: parp.documents(_pr)
    except BaseException as e:
        k = (type(e).__name__, where(e))
        if k not in groups: groups[k] = raw
print("iterations", N, "seed", sys.argv[1:] )
for k, raw in groups.items():
    print("ESCAPE", k, len(raw))
    open(SP + "/out/fuzz3_%s_%s_%s.json" % (k[0], k[1][0] if k[1] else "none", k[1][1] if k[1] else 0), "wb").write(raw)
