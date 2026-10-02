"""Fuzz the FIXTURES snapshot builder (feeds every ODDS normalization via the fixture join)."""
from boot import *
import random, copy, sys
from genesis_adapters.oddspapi import parser
from genesis_adapters.oddspapi.maps import maps_from_config
from genesis_adapters.config import load_adapter_config
cfg = load_adapter_config(CONFIG, allow_fixture_only=True, code_version="x")
maps = maps_from_config(cfg)
schema = cfg.schemas[cfg.endpoints["FIXTURES"].response_schema_id]
base = json.loads((FIXTURES / "fixtures.json").read_text())
rng = random.Random(5)
LITS = ["1E+999999999", "1E-999999999", "9" * 70, "9" * 400, "1" + "0" * 4200, '"\\ud800"', '"\\u0000"', "true", "null", "[]", "{}", '""', '"abc"', "-0", "0e0", "10", "-1",
        '"2026-10-03T14:00:00.000Z"', '"2026-02-30T14:00:00Z"', '"9999-12-31T23:59:59.999Z"', '"2026-10-03T14:00:00+99:99"', "1.5", '"x\\n"']
def paths(o, b=()):
    if isinstance(o, dict):
        for k, v in o.items(): yield b + (k,); yield from paths(v, b + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o): yield b + (i,); yield from paths(v, b + (i,))
def getp(o, p):
    for k in p: o = o[k]
    return o
allp = list(paths(base)); groups = {}
def where(e):
    tb = e.__traceback__; last = None
    while tb is not None:
        f = tb.tb_frame.f_code.co_filename
        if "genesis_adapters" in f or "/genesis/" in f: last = (f.split("/")[-1], tb.tb_lineno)
        tb = tb.tb_next
    return last
for i in range(6000):
    p = copy.deepcopy(base)
    for _ in range(rng.choice((1, 1, 2))):
        path = rng.choice(allp)
        try: getp(p, path[:-1])[path[-1]] = "@L%d" % rng.randrange(3)
        except Exception: pass
    text = json.dumps(p, sort_keys=True)
    for j in range(3): text = text.replace('"@L%d"' % j, rng.choice(LITS))
    raw = text.encode("ascii") if text.isascii() else text.encode("utf-8", "surrogatepass")
    try:
        parser.build_fixture_snapshot(raw, observation_id="0" * 64, retrieved_at="2026-10-01T12:00:00.000000Z", maps=maps, policy=cfg.policy, fixtures_schema=schema)
    except BaseException as e:
        k = (type(e).__name__, where(e))
        groups.setdefault(k, raw)
print("fixtures-fuzz escapes:", list(groups) or "none")
for k, raw in groups.items(): open(SP + "/out/fuzzfx_%s_%s_%s.json" % (k[0], k[1][0] if k[1] else "n", k[1][1] if k[1] else 0), "wb").write(raw)
