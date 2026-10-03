"""Totality fuzz of the PURE parser: any exception escaping parse_odds_response on provider-controlled JSON is a poison pill."""
from boot import *
import random, collections, copy, traceback
rng = random.Random(20261002)
LITS = ["1E+999999999", "1E-999999999", "-1E+999999999", "1E+999999", "1E+999998", "0E+999999999", "1E+1000000", "1.5E+999999",
        "0.0000000000000000000000000000000000000000000000001", "123456789012345678901234567890123456789012345678901234567890.5",
        "1e5", "-0", "-0.0", "0e0", "2.5000000000000000000000000000000000000001", "9" * 400, "1" + "0" * 4200, "1.5E+10", "2.50", "1e2", "1E400",
        '"2.5"', '"abc"', '""', "true", "false", "null", "[]", "{}", '"\\u0000"', '"\\ud800"', '"1E+999999999"', '"2.5\\n"', "[1E+999999999]", '{"a":1E+999999999}',
        '"2026-10-03T14:00:00.000Z"', '"9999-12-31T23:59:59.999Z"', '"0001-01-01T00:00:00.000Z"', '"2026-10-03T14:00:00+99:99"', '"2026-02-30T14:00:00Z"',
        "10", "-1", "1000000000000000000000000", "18446744073709551616"]
def paths(o, base=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield base + (k,); yield from paths(v, base + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield base + (i,); yield from paths(v, base + (i,))
def setp(o, path, v):
    for k in path[:-1]: o = o[k]
    o[path[-1]] = v
base = parp.odds_payload()
allp = list(paths(base))
seen = collections.defaultdict(list)
N = 6000
for i in range(N):
    p = copy.deepcopy(base)
    lit = rng.choice(LITS)
    for _ in range(rng.choice((1, 1, 1, 2, 3))):
        path = rng.choice(allp)
        try: setp(p, path, "@L%d" % rng.randrange(3))
        except Exception: pass
    text = json.dumps(p, sort_keys=True)
    for j in range(3): text = text.replace('"@L%d"' % j, rng.choice(LITS))
    raw = text.encode("utf-8")
    try:
        parp.parse(raw)
    except BaseException as e:
        key = type(e).__module__ + "." + type(e).__name__
        if len(seen[key]) < 3: seen[key].append(raw[:0] + b"" or None)
        seen[key].append(1) if False else None
        # keep a minimal repro: first occurrence text diff
        if not any(isinstance(x, bytes) for x in seen[key]):
            seen[key].append(raw)
print("iterations", N)
for k, v in seen.items():
    sample = [x for x in v if isinstance(x, bytes)][0]
    print("ESCAPED EXCEPTION CLASS:", k, "(sample repro bytes: %d)" % len(sample))
    open(SP + "/out/fuzz_" + k.split(".")[-1] + ".json", "wb").write(sample)
if not seen: print("no exception escaped")
