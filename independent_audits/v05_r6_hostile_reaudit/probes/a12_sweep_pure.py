"""A12 (RA5-001): EXHAUSTIVE single-substitution sweep of the pure stage (deterministic, no randomness).

Every leaf of the base ODDS fixture is replaced, one at a time, by every literal of A11's capture-passing hostile
pool, and every map key is renamed to every hostile key, plus nesting chains landing the total depth at 49/50/51 at
every leaf. For each body: the capture-time verdict, ``derivation.derive`` outcome (safety-net catches recorded),
emission preconditions for every document; every 7th body also checks determinism and stack-depth independence.
usage: a12_sweep_pure.py
"""
import sys
sys.argv = [sys.argv[0], "0", "0"]
from boot import *
src = open(str(HERE) + "/a11_fuzz_pure.py").read()
exec(compile(src.split("threading.stack_size(")[0].split("from boot import *")[1], "a11", "exec"))
import collections, json as _json, threading, inspect

def bodies():
    for path in ALL:
        for lit in PASSING + ["DEPTH49", "DEPTH50", "DEPTH51"]:
            p = copy.deepcopy(BASE)
            parent = getp(p, path[:-1]) if len(path) > 1 else p
            parent[path[-1]] = "@L"
            text = _json.dumps(p, sort_keys=True)
            if lit.startswith("DEPTH"):
                k = max(0, int(lit[5:]) - len(path))
                lit = "[" * k + "1" + "]" * k
            yield ("leaf", path, lit[:30]), text.replace(_json.dumps("@L"), lit, 1).encode("utf-8")
        parent = getp(BASE, path[:-1]) if len(path) > 1 else BASE
        if isinstance(parent, dict):
            for key in KEYS:
                p = copy.deepcopy(BASE)
                par = getp(p, path[:-1]) if len(path) > 1 else p
                if key in par:
                    continue
                par[key] = par.pop(path[-1])
                yield ("key", path, key[:20]), _json.dumps(p, sort_keys=True).encode("utf-8")

threading.stack_size(64 * 1024 * 1024)
classes = collections.Counter(); net = collections.Counter(); pass_reject = collections.Counter()
defects = collections.OrderedDict(); count = [0]
def run():
    for n, (desc, raw) in enumerate(bodies()):
        count[0] += 1
        cap = capture_verdict(raw)
        d = derivation.derive(raw, CTX)
        o = outcome(d)
        classes[(cap, o[0].split(":")[0] + ":" + (o[0].split(":")[1] if ":" in o[0] else ""))] += 1
        if o[0].startswith("FAIL:DERIVATION_FAULT"):
            net[o[0]] += 1
        if cap == "PASS" and o[0].startswith("FAIL"):
            pass_reject[(o[0], desc[0], str(desc[1][-1]))] += 1
        problems = []
        if d.failure is None:
            problems += ["EMIT_PRECONDITION " + x for x in emission_preconditions(d.documents)]
        if n % 7 == 0:
            if outcome(derivation.derive(raw, CTX)) != o:
                problems.append("NONDETERMINISTIC")
            depth_now = len(inspect.stack(0))
            o3 = at_depth(lambda: outcome(derivation.derive(raw, CTX)), max(0, sys.getrecursionlimit() - depth_now - 120))
            if o3 != o:
                problems.append("STACK_DEPTH_DEPENDENT")
        for x in problems:
            k = x.split(":")[0][:60]
            if k not in defects:
                defects[k] = (desc, x)
                open(SP + "/out/a12_%d.json" % n, "wb").write(raw)
t = threading.Thread(target=run); t.start(); t.join()
print("A12 exhaustive single-substitution sweep: %d bodies (%d leaf paths)" % (count[0], len(ALL)))
for k, v in classes.most_common():
    print("   %7d  %s" % (v, k))
print("safety net (DERIVATION_FAULT) caught:", dict(net) if net else "nothing")
print("capture PASS -> terminal derivation rejection (failure, kind, field):")
for k, v in sorted(pass_reject.items()):
    print("   %5d  %s" % (v, k))
print("defects:", dict(defects) if defects else "none")
