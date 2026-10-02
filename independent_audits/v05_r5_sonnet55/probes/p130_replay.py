"""Deterministic replay: two independent runs (own roots, same fixed clock/script) must produce byte-identical durable state."""
from boot import *
import hashlib, os
def run_once():
    cm = scratch_root(); root = cm.__enter__()
    clock = FixedClock(START, step_micros=1000)
    rt = open_rt(root, clock=clock, script=[fixtures_response if False else odds_response(), odds_response(), odds_response()])
    rt.acquire(odds_item("w1")); approve(rt); clock.advance(seconds=900); rt.acquire(odds_item("w2"))
    clock.advance(seconds=900); rt.acquire(odds_item("w3"))
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f); rel = os.path.relpath(p, root)
            if rel == "run.lock": continue
            out[rel] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    cm.__exit__(None, None, None); return out
a, b = run_once(), run_once()
diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
print("files run A:", len(a), "run B:", len(b), "| differing:", diff[:5] or "none")
