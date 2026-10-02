"""Fuzz the FULL pipeline (acquire -> capture -> parse -> emit) excluding the three known poison classes."""
from boot import *
import random, copy, sys, collections
rng = random.Random(int(sys.argv[1])); N = int(sys.argv[2])
LITS = ["1E-999999999", "-1E+99", "1E+5", "-0", "0e0", "9" * 60, '"2.5"', '"abc"', '""', "true", "false", "null", "[]", "{}", '"\\u0000"', '"a\\nb"', '"\\u00e9"', '"\\ud83d\\ude00"',
        '"2026-10-03T14:00:00.000Z"', '"9999-12-31T23:59:59.999Z"', '"0001-01-01T00:00:00.000Z"', '"2026-10-03T14:00:00+99:99"', '"2026-02-30T14:00:00Z"', "10", "-1", "0", "1", "2.5", "1.0", "1.01",
        "1000.0001", '"1"', "[1,2]", '{"a":{"b":[]}}', '"' + "A" * 50000 + '"', "1.9", "2.04", "3.1", "1.91"]
def paths(o, b=()):
    if isinstance(o, dict):
        for k, v in o.items(): yield b + (k,); yield from paths(v, b + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o): yield b + (i,); yield from paths(v, b + (i,))
def getp(o, p):
    for k in p: o = o[k]
    return o
base = parp.odds_payload(); allp = list(paths(base)); groups = {}
for i in range(N):
    p = copy.deepcopy(base)
    for _ in range(rng.choice((1, 2, 3))):
        path = rng.choice(allp)
        try:
            op = rng.choice(("lit", "lit", "del"))
            par = getp(p, path[:-1]) if len(path) > 1 else p
            if op == "lit": par[path[-1]] = "@L%d" % rng.randrange(3)
            elif isinstance(par, dict): par.pop(path[-1], None)
        except Exception: pass
    text = json.dumps(p, sort_keys=True)
    for j in range(3): text = text.replace('"@L%d"' % j, rng.choice(LITS))
    raw = text.encode("ascii")
    with scratch_root() as root:
        clock = FixedClock(START, step_micros=1000)
        rt = open_rt(root, clock=clock, script=[odds_response(), ok(raw, headers=JSON)])
        try:
            rt.acquire(odds_item("w1")); approve(rt); clock.advance(seconds=900)
            out = rt.acquire(odds_item("w2"))
            rt2 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=60), step_micros=1000)); rt2.resume()
            rt2.verify_all()
        except BaseException as e:
            tb = e.__traceback__; last = None
            while tb is not None:
                f = tb.tb_frame.f_code.co_filename
                if "genesis_adapters" in f or "/genesis/" in f: last = (f.split("/")[-1], tb.tb_lineno)
                tb = tb.tb_next
            k = (type(e).__name__, last, str(e)[:50])
            groups.setdefault(k, raw)
print("pipeline fuzz iterations", N)
for k, raw in groups.items():
    print("ESCAPE", k)
    open(SP + "/out/fuzzp_%s_%s.json" % (k[0], k[1][1] if k[1] else 0), "wb").write(raw)
if not groups: print("none")
