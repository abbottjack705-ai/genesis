"""A10 (RA5-001): seeded end-to-end fuzz of the WHOLE pipeline with restart, not only of the pure stage.

For each case: a healthy capture w1 (normalized, approved), then the mutated ODDS body as w2 through
``AdapterRuntime.acquire``; then a restart (``reopen`` + ``resume`` twice), ``verify_all`` and a reader read of every
entity. The outcome is CLASSIFIED (not only "did something escape"):
  NORMALIZED            documents emitted
  CAPTURE_REJECTED:<f>  failure in the completed row (HA-04 path)
  DERIV_REJECTED:<f>    terminal acq_derivation_rejected (R6 path); DERIVATION_FAULT also records the class name
  HALT:<code>           PipelineHalt / AcquisitionHalt
DEFECTS: any other exception from acquire / restart / verify_all / reader; pending_work non-empty after restart;
the attempt's state changing across restart; a DERIVATION_FAULT (the safety net) catching anything (reported, not a
defect by itself: the implementer claims the net never catches a known class).

usage: a10_fuzz_e2e.py <seed> <iterations> [out.jsonl]
"""
from boot import *
import copy, random, sys, collections, traceback
from genesis_adapters.oddspapi import quiescence
from genesis_adapters.oddspapi.pipeline import PipelineHalt
from genesis_adapters.oddspapi.acquisition import AcquisitionHalt

SEED, N = int(sys.argv[1]), int(sys.argv[2])
OUT = open(sys.argv[3], "a") if len(sys.argv) > 3 else None
rng = random.Random(SEED)

def chain(k, leaf="1"):
    """k nested containers around ``leaf``, alternating list/object at random (deterministic per rng)."""
    text = leaf
    for _ in range(k):
        text = ("[" + text + "]") if rng.random() < 0.5 else ('{"k":' + text + "}")
    return text

NUMS = ["1E+1000", "1E+1001", "1E-1000", "1E-1001", "-1E+1000", "-1E+1001", "0E+1000", "0E+1001", "0E-1001",
        "9.99E+1000", "1.0E+1000", "10E+999", "10E+1000", "0.1E+1002", "0.1E+1001", "1" + "0" * 1000,
        "1" + "0" * 1001, "-" + "9" * 1001, "-" + "9" * 1002, "1." + "0" * 5000, "1." + "0" * 5000 + "1",
        "0." + "0" * 999 + "1", "0." + "0" * 1000 + "1", "1E+999999999999999999999", "1E-999999999999999999999",
        "1e1000", "1e+0001000", "1E+01001", "-0", "-0.0", "0e0", "1.01", "1000", "1000.0001", "2.5", "2.50",
        "1E+2", "1.91E0", "191E-2", "12345678901234567890123456789012345678901234567890.5", str(2 ** 64),
        str(-2 ** 63), "1E+999", "1E-999"]
STRS = ['"\\ud800"', '"\\udfff"', '"\\udbff\\udfff"', '"\\ud83d\\ude00"', '"\\ude00\\ud83d"', '"a\\ud800b"',
        '"\\u0000"', '"\\u2028"', '"\\ufeff"', '"x\\n"', '"x\\r\\n"', '"A' + "a" * 63 + '"', '"A' + "a" * 64 + '"',
        '"' + "1" * 64 + '"', '"' + "1" * 65 + '"', '"a.b:c-d_e"', '"\\u00e9"', '"\\u0661"', '" id1"',
        '"id1 "', '""', '"' + "Z" * 300000 + '"', '"2026-10-03T14:00:00.000Z"', '"2026-10-03T14:00:00Z"',
        '"2026-10-03T14:00:00.000000Z"', '"9999-12-31T23:59:59.999999Z"', '"0001-01-01T00:00:00Z"',
        '"2026-10-03T14:00:00+00:00"', '"2026-10-03T14:00:00.0000000Z"', '"2026-10-03 14:00:00Z"',
        '"2026-10-03T14:00:00.000Z\\n"', '"2026-02-29T00:00:00Z"', '"2028-02-29T00:00:00Z"', '"true"',
        '"1"', '"1.01"', '"OPEN"', '"open"']
OTHER = ["true", "false", "null", "[]", "{}", '{"a":1,"a":2}', '{"\\ud800":1}', '{"k":1,"K":2}',
         "[" + ",".join(["0"] * 200000) + "]", '{"' + '":1,"'.join("k%d" % i for i in range(20000)) + '":1}']

def paths(o, b=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield b + (k,)
            yield from paths(v, b + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield b + (i,)
            yield from paths(v, b + (i,))

def getp(o, p):
    for k in p:
        o = o[k]
    return o

BASE = parp.odds_payload()
ALL = list(paths(BASE))
MAPKEYS = [p for p in ALL if isinstance(getp(BASE, p[:-1]) if len(p) > 1 else BASE, dict)]

def mutate():
    p = copy.deepcopy(BASE)
    lits = {}
    ops = []
    for j in range(rng.choice((1, 1, 2, 3))):
        path = rng.choice(ALL)
        op = rng.choice(("num", "num", "str", "str", "depth", "depth", "other", "del", "key"))
        marker = "@L%d" % j
        try:
            parent = getp(p, path[:-1]) if len(path) > 1 else p
            if op == "del":
                if isinstance(parent, dict):
                    parent.pop(path[-1], None)
                ops.append(("del", path))
                continue
            if op == "key" and isinstance(parent, dict) and path[-1] in parent:
                value = parent.pop(path[-1])
                key = rng.choice(['A' + "a" * 63, 'A' + "a" * 64, "\ud800", "x\n", "", " ", "é", "1" * 65])
                parent[key] = value
                ops.append(("key", path, repr(key)[:20]))
                continue
            if op == "num":
                lit = rng.choice(NUMS)
            elif op == "str":
                lit = rng.choice(STRS)
            elif op == "other":
                lit = rng.choice(OTHER)
            else:                                          # land the total nesting exactly at/around the bound
                enclosing = len(path)                      # containers that hold the leaf (root list included)
                total = rng.choice((49, 50, 50, 51, 51, 52, 60))
                lit = chain(max(0, total - enclosing))
            parent[path[-1]] = marker
            lits[marker] = lit
            ops.append((op, path, lit[:40]))
        except (TypeError, KeyError, IndexError):
            pass
    text = json.dumps(p, sort_keys=True, ensure_ascii=True)
    for marker, lit in lits.items():
        text = text.replace(json.dumps(marker), lit, 1)
    return text.encode("utf-8", "surrogatepass"), ops

def classify(rt, aid):
    rows = [r for r in acquisition_rows(rt) if r.get("acquisition_id") == aid]
    kinds = [r["record_type"] for r in rows]
    completed = next((r for r in rows if r["record_type"] == "acq_completed"), None)
    if "acq_normalized" in kinds:
        return "NORMALIZED"
    rej = [r for r in rows if r["record_type"] == "acq_derivation_rejected"]
    if rej:
        r = rej[-1]
        return "DERIV_REJECTED:%s%s" % (r["failure"], (":" + r["detail"]) if r["detail"] else "")
    if completed is not None and completed["failure"] is not None:
        return "CAPTURE_REJECTED:%s" % completed["failure"]
    return "OTHER:" + ",".join(kinds)

def where(exc):
    tb = exc.__traceback__; last = None
    while tb is not None:
        f = tb.tb_frame.f_code.co_filename
        if "genesis_adapters" in f or "/genesis/" in f:
            last = "%s:%d" % (f.split("/")[-1], tb.tb_lineno)
        tb = tb.tb_next
    return last

def run_case(raw):
    rec = {}
    with scratch_root() as root:
        clock = FixedClock(START, step_micros=1000)
        rt = open_rt(root, clock=clock, script=[odds_response(), ok(raw, headers=JSON)])
        rt.acquire(odds_item("w1")); approve(rt)
        entities = sorted({r["entity_id"] for r in pit_rows(rt)})
        clock.advance(seconds=900)
        aid = None
        try:
            out = rt.acquire(odds_item("w2"))
            aid = out.outcome.acquisition_id
            rec["acquire"] = "returned:%s" % (out.outcome.failure.value if out.outcome.failure else None)
        except (PipelineHalt, AcquisitionHalt) as e:
            rec["acquire"] = "HALT:%s" % getattr(e, "code", e)
        except BaseException as e:
            rec["acquire"] = "ESCAPE:%s@%s" % (type(e).__name__, where(e))
        attempts = rt.stores.acquisition.attempts()
        if aid is None:
            aid = [a for a in attempts][-1]
        rec["class"] = classify(rt, aid)
        state_before = attempts[aid].state
        rt2 = reopen(rt, script=[odds_response()])
        for n in (1, 2):
            try:
                rt2.resume()
                rec["resume%d" % n] = "ok"
            except (PipelineHalt, AcquisitionHalt) as e:
                rec["resume%d" % n] = "HALT:%s" % getattr(e, "code", e)
            except BaseException as e:
                rec["resume%d" % n] = "ESCAPE:%s@%s" % (type(e).__name__, where(e))
        rec["state"] = (state_before, rt2.stores.acquisition.attempts()[aid].state)
        rec["pending"] = list(quiescence.pending_work(rt2.stores))
        try:
            rec["verify_all"] = rt2.verify_all()
        except BaseException as e:
            rec["verify_all"] = "ESCAPE:%s@%s" % (type(e).__name__, where(e))
        reads = collections.Counter()
        for entity in entities:
            try:
                v = rt2.reader().head(entity, parp.iso_add(rt2.clock.peek(), seconds=30))
                reads[type(v).__name__ + ":" + str(getattr(getattr(v, "code", None), "value", ""))] += 1
            except BaseException as e:
                reads["ESCAPE:%s@%s" % (type(e).__name__, where(e))] += 1
        rec["reads"] = dict(reads)
        # a LATER healthy capture after the restart: pin_scope reads the mutated case's documents (if any)
        rt2.clock.advance(seconds=900)
        try:
            out3 = rt2.acquire(odds_item("w3"))
            rec["later_healthy"] = "returned:%s" % (out3.outcome.failure.value if out3.outcome.failure else None)
        except (PipelineHalt, AcquisitionHalt) as e:
            rec["later_healthy"] = "HALT:%s" % getattr(e, "code", e)
        except BaseException as e:
            rec["later_healthy"] = "ESCAPE:%s@%s" % (type(e).__name__, where(e))
        later = collections.Counter()
        for entity in entities:
            try:
                v = rt2.reader().head(entity, parp.iso_add(rt2.clock.peek(), seconds=30))
                later[type(v).__name__] += 1
            except BaseException as e:
                later["ESCAPE:%s" % type(e).__name__] += 1
        rec["reads_after_later_healthy"] = dict(later)
        rec["pending_end"] = list(quiescence.pending_work(rt2.stores))
    return rec

def defects(rec):
    out = []
    for key in ("acquire", "resume1", "resume2", "verify_all", "later_healthy"):
        if isinstance(rec.get(key), str) and rec[key].startswith("ESCAPE"):
            out.append(key + "=" + rec[key])
    if rec["pending"]:
        out.append("pending=" + "|".join(rec["pending"]))
    if rec["state"][0] != rec["state"][1] and rec["state"][0] != "COMPLETED":
        out.append("state_changed=%s->%s" % rec["state"])
    if rec["class"].startswith("OTHER"):
        out.append("unclassified_terminal_state")
    if any(k.startswith("ESCAPE") for k in rec["reads"]):
        out.append("reader_escape")
    if rec.get("later_healthy", "").startswith("HALT"):
        out.append("later_healthy_capture_halted=" + rec["later_healthy"])
    if rec.get("reads_after_later_healthy") and set(rec["reads_after_later_healthy"]) != {"UsableBook"}:
        out.append("reader_not_usable_after_later_healthy_capture=" + str(rec["reads_after_later_healthy"]))
    if rec.get("pending_end"):
        out.append("pending_at_end")
    return out

classes = collections.Counter(); found = collections.OrderedDict(); net = collections.OrderedDict()
for i in range(N):
    raw, ops = mutate()
    try:
        rec = run_case(raw)
    except BaseException as e:                              # the harness itself (a healthy w1 must not fail)
        rec = {"class": "HARNESS:%s@%s" % (type(e).__name__, where(e)), "state": ("?", "?"), "pending": [],
               "reads": {}}
    classes[rec["class"]] += 1
    d = defects(rec) if not rec["class"].startswith("HARNESS") else ["harness"]
    if rec["class"].startswith("DERIV_REJECTED:DERIVATION_FAULT"):
        net.setdefault(rec["class"], (i, ops))
    if d:
        key = tuple(sorted(x.split("@")[0] for x in d))
        if key not in found:
            found[key] = (i, ops, rec)
            open(SP + "/out/a10_seed%d_case%d.json" % (SEED, i), "wb").write(raw)
    if OUT:
        OUT.write(json.dumps({"seed": SEED, "i": i, "ops": [list(map(str, o)) for o in ops], **{k: (list(v) if isinstance(v, tuple) else v) for k, v in rec.items()}, "defects": d}) + "\n")
print("A10 seed=%d iterations=%d" % (SEED, N))
print("outcome classes:")
for k, v in classes.most_common():
    print("   %6d  %s" % (v, k))
print("safety-net (DERIVATION_FAULT) first examples:", dict(net) if net else "none")
print("defect classes:", len(found))
for key, (i, ops, rec) in found.items():
    print("  DEFECT", key, "case", i, "ops", ops, "rec", rec)
