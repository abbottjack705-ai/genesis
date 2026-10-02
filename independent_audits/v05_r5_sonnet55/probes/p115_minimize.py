from boot import *
import copy, collections
OUT = SP + "/out/"
base = parp.odds_payload()
def paths(o, base_=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield base_ + (k,); yield from paths(v, base_ + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield base_ + (i,); yield from paths(v, base_ + (i,))
def getp(o, path):
    for k in path: o = o[k]
    return o
def setp(o, path, v):
    for k in path[:-1]: o = o[k]
    o[path[-1]] = v
def exc_of(rawbytes):
    try: parp.parse(rawbytes); return None
    except BaseException as e: return type(e).__name__
def load_raw_literal_doc(raw: bytes):
    # parse with Decimal so numeric literals survive exactly; keep as Python objects, re-dump with a Decimal-aware encoder
    import json as j, decimal
    return j.loads(raw.decode("utf-8", "surrogatepass"), parse_float=decimal.Decimal, parse_int=int)
class Enc(json.JSONEncoder):
    def default(self, o):
        import decimal
        if isinstance(o, decimal.Decimal): return json.RawJSON(str(o)) if hasattr(json, "RawJSON") else float(o)
        return super().default(o)
def dumps(doc):
    import decimal
    def enc(o):
        if isinstance(o, dict): return "{" + ",".join(json.dumps(k) + ":" + enc(v) for k, v in sorted(o.items())) + "}"
        if isinstance(o, list): return "[" + ",".join(enc(v) for v in o) + "]"
        if isinstance(o, decimal.Decimal): return format(o, "E") if o.as_tuple().exponent != 0 else str(o)
        return json.dumps(o)
    return enc(doc).encode("utf-8", "surrogatepass") if False else enc(doc).encode("ascii", "backslashreplace")
for name in ("Overflow", "UnicodeEncodeError", "IdentityTypeError"):
    raw = open(OUT + f"fuzz_{name}.json", "rb").read()
    doc = load_raw_literal_doc(raw)
    target = exc_of(raw)
    diff = [p for p in paths(doc) if (p not in set(paths(base))) or getp(doc, p) != getp(base, p) if not isinstance(getp(doc, p), (dict, list))] if True else []
    # robust diff over leaf values
    leafs = [p for p in paths(doc) if not isinstance(getp(doc, p), (dict, list))]
    changed = []
    for p in leafs:
        try: b = getp(base, p)
        except Exception: b = object()
        if getp(doc, p) != b: changed.append(p)
    # structural differences (containers replaced) 
    structural = [p for p in paths(doc) if isinstance(getp(doc, p), (dict, list)) and (lambda p: (lambda b: type(b) != type(getp(doc, p)))(getp(base, p)) if True else False)(p) if True] if False else []
    cur = copy.deepcopy(doc)
    # revert each changed path to base value while the exception stays the same
    for p in list(changed):
        trial = copy.deepcopy(cur)
        try: setp(trial, p, copy.deepcopy(getp(base, p)))
        except Exception: continue
        if exc_of(dumps(trial)) == target: cur = trial
    remaining = []
    for p in [p for p in paths(cur)]:
        try: b = getp(base, p)
        except Exception: b = object()
        v = getp(cur, p)
        if not isinstance(v, (dict, list)) and v != b: remaining.append((p, v))
    print(name, "->", exc_of(dumps(cur)), "| minimal differing leaves:", [(list(p), (repr(v)[:70])) for p, v in remaining])
