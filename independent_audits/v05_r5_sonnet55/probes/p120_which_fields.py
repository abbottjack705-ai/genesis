from boot import *
import copy
base = parp.odds_payload()
def paths(o, b=()):
    if isinstance(o, dict):
        for k, v in o.items(): yield b + (k,); yield from paths(v, b + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o): yield b + (i,); yield from paths(v, b + (i,))
def getp(o, p):
    for k in p: o = o[k]
    return o
leafs = [p for p in paths(base) if not isinstance(getp(base, p), (dict, list))]
import collections
res = collections.defaultdict(list)
for lit_name, lit in (("lone_surrogate", "\ud800"),):
    for p in leafs:
        q = copy.deepcopy(base); getp(q, p[:-1])[p[-1]] = lit
        raw = json.dumps(q, sort_keys=True).encode("ascii")
        try:
            r = parp.parse(raw)
            if r.failure is None: parp.documents(r)
        except BaseException as e:
            res[type(e).__name__].append("/".join(map(str, p[-3:])))
for k, v in res.items(): print(k, len(v), sorted(set(v))[:12])
print("leaf count", len(leafs))
