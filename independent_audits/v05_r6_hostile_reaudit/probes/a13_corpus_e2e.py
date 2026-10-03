"""A13 (RA5-001): deterministic end-to-end corpus of the known poison classes and the exact R6 bounds.

Each case goes through A10's ``run_case`` (acquire -> restart + resume x2 -> verify_all -> reader -> a LATER healthy
capture -> reader again -> pending_work) and is classified. Expected: no escape anywhere, a terminal verdict, nothing
pending, and the reader usable again after the later healthy capture.
usage: a13_corpus_e2e.py
"""
import sys
sys.argv = [sys.argv[0], "13", "0"]
from boot import *
src = open(str(HERE) + "/a10_fuzz_e2e.py").read().split("classes = collections.Counter()")[0]
exec(compile(src.split("from boot import *")[1], "a10", "exec"))

def first_player(p):
    fx = parp.fixture_of(p); mk = next(iter(fx["bookmakerOdds"]["pinnacle"]["markets"].values()))
    return next(iter(next(iter(mk["outcomes"].values()))["players"].values()))
def with_lit(mut, lit):
    p = parp.odds_payload(); mut(p, "@x"); return parp.dump_with(p, x=lit)
def set_player(key):
    return lambda p, v: first_player(p).__setitem__(key, v)
def set_fixture(key):
    return lambda p, v: parp.fixture_of(p).__setitem__(key, v)
def deep_at(total):
    path_len = 9                                  # containers enclosing a player field in the fixture
    k = max(0, total - path_len)
    return "[" * k + "1" + "]" * k
CASES = {
    "R5-A changedAt 1E+999999999": with_lit(set_player("changedAt"), "1E+999999999"),
    "R5-B active lone high surrogate": with_lit(set_player("active"), '"\\ud800"'),
    "R5-C participant1Id 70 digits": with_lit(set_fixture("participant1Id"), "9" * 70),
    "R5-D betslip 600 nested arrays": with_lit(set_player("betslip"), "[" * 600 + "]" * 600),
    "fifth class fixtureId 'not a valid id'": with_lit(set_fixture("fixtureId"), '"not a valid id"'),
    "fixtureId 64 chars": with_lit(set_fixture("fixtureId"), '"' + "i" * 64 + '"'),
    "fixtureId 65 chars": with_lit(set_fixture("fixtureId"), '"' + "i" * 65 + '"'),
    "fixtureId trailing LF": with_lit(set_fixture("fixtureId"), '"id1000001761301153\\n"'),
    "participant1Id 64 digits": with_lit(set_fixture("participant1Id"), "9" * 64),
    "participant1Id 65 digits": with_lit(set_fixture("participant1Id"), "9" * 65),
    "participant1Id negative": with_lit(set_fixture("participant1Id"), "-5"),
    "price 1E+1000 (at bound)": with_lit(set_player("price"), "1E+1000"),
    "price 1E+1001 (one over)": with_lit(set_player("price"), "1E+1001"),
    "price 1E-1000 (at bound)": with_lit(set_player("price"), "1E-1000"),
    "price 1E-1001 (one over)": with_lit(set_player("price"), "1E-1001"),
    "price int 1001 digits (at bound)": with_lit(set_player("price"), "1" + "0" * 1000),
    "price int 1002 digits (one over)": with_lit(set_player("price"), "1" + "0" * 1001),
    "price 1.91 + 3000 zeros": with_lit(set_player("price"), "1.91" + "0" * 3000),
    "price 1.9 + 3000 zeros + 1": with_lit(set_player("price"), "1.9" + "0" * 3000 + "1"),
    "price 1E+999999999999999999999 (beyond Decimal)": with_lit(set_player("price"), "1E+999999999999999999999"),
    "betslip depth exactly 50": with_lit(set_player("betslip"), deep_at(50)),
    "betslip depth 51": with_lit(set_player("betslip"), deep_at(51)),
    "name with escaped surrogate PAIR (valid)": with_lit(set_fixture("participant1Name"), '"X\\ud83d\\ude00"'),
    "name with lone LOW surrogate": with_lit(set_fixture("participant1Name"), '"X\\ude00"'),
    "name with reversed pair": with_lit(set_fixture("participant1Name"), '"X\\ude00\\ud83d"'),
    "key with lone surrogate": with_lit(set_player("betslip"), '{"\\udbff":1}'),
    "changedAt T1+5s (tolerance)": with_lit(set_player("changedAt"), '"2026-10-01T12:15:05.000Z"'),
    "startTime +00:00 offset": with_lit(set_fixture("startTime"), '"2026-10-03T14:00:00+00:00"'),
    "broad array 200000 zeros in betslip": with_lit(set_player("betslip"), "[" + ",".join(["0"] * 200000) + "]"),
}
results = {}
for name, raw in CASES.items():
    rec = run_case(raw)
    d = defects(rec)
    results[name] = (rec, d)
    print("%-50s class=%-45s later=%s reads_after=%s %s" % (
        name[:50], rec["class"][:45], rec.get("later_healthy"), rec.get("reads_after_later_healthy"),
        ("DEFECT " + str(d)) if d else "ok"))
print("A13 corpus: %d cases, %d with defects" % (len(results), sum(1 for r in results.values() if r[1])))
