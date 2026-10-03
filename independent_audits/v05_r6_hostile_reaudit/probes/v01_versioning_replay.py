"""V01: derivation-version propagation, stale pins, cross-version roots, deterministic replay of R6 evidence.

  A  derivation_version / policy_digest of the base (b22263e) and of the candidate (each computed by its own code).
  B  a G2R record pinned to the BASE derivation_version/policy_digest: does the candidate's LiveGate refuse it?
  C  a runtime root written by the BASE code (a normalized capture) opened by the CANDIDATE code: what does start
     (open_runtime + resume, the first thing `cli run --mode G2R` does) do?
  D  R6-created evidence (healthy + rejected-at-derivation + capture-rejected captures) replays byte-identically:
     two fresh roots, same clock and script -> every durable file identical.
  E  a rejected observation stays rejected across 3 restarts and a PIT-09 rebuild; restart cannot change taxonomy.
usage: v01_versioning_replay.py <candidate_dir> <base_dir>   (writes BASE root via a child process of the base code)
"""
import hashlib, json, os, subprocess, sys, tempfile, pathlib
CAND, BASE = sys.argv[1], sys.argv[2]
HERE = pathlib.Path(__file__).resolve().parent
os.environ["CAND_DIR"] = CAND
sys.argv = [sys.argv[0]]
sys.path.insert(0, str(HERE))
from boot import *                                         # noqa: candidate code
from genesis_adapters.config import load_adapter_config
from genesis_adapters.oddspapi import normalize, pipeline as pl
from genesis_adapters.oddspapi.authority import AdapterAuthorityLedger, LiveGate, load_gate_limits
from genesis_adapters.errors import GateMissing

def version_of(cand):
    code = ("import sys,os,json; sys.path.insert(0, sys.argv[1]+'/adapters'); os.chdir(sys.argv[1]); import adapter_tests;"
            "from adapter_tests.support import CONFIG; from genesis_adapters.config import load_adapter_config;"
            "from genesis_adapters.oddspapi import normalize as n;"
            "c=load_adapter_config(CONFIG, allow_fixture_only=True, code_version=n.CODE_VERSION);"
            "print(json.dumps([n.CODE_VERSION, c.derivation_version, c.policy.digest]))")
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp()); env.pop("PYTHONPATH", None)
    return json.loads(subprocess.check_output([sys.executable, "-B", "-c", code, cand], env=env).decode().splitlines()[-1])

base_v, cand_v = version_of(BASE), version_of(CAND)
print("A  base     :", base_v)
print("A  candidate:", cand_v)
print("A  new derivation source:", base_v[1] != cand_v[1] and base_v[2] != cand_v[2])

# B: stale G2R pin
from datetime import datetime, timedelta, timezone
from genesis.time import iso_utc
with scratch_root() as root:
    limits = load_gate_limits(CONFIG)
    led = AdapterAuthorityLedger(root / "authority.jsonl", limits=limits)
    now = datetime.now(timezone.utc)
    from adapter_tests.test_v05_authority import g1, g2r                 # the suite's own record shapes
    led.append(g1(now - timedelta(hours=1)))
    led.append(g2r(now - timedelta(hours=1), derivation=base_v[1], policy=base_v[2]))
    try:
        led.require_gate("G2R", at=iso_utc(now), derivation_version=cand_v[1], policy_digest=cand_v[2])
        print("B  stale G2R pin: ACCEPTED by the candidate's pins  -> DEFECT")
    except GateMissing as exc:
        print("B  stale G2R pin (base version) under the candidate's version: refused (GateMissing)")
    led.require_gate("G2R", at=iso_utc(now), derivation_version=base_v[1], policy_digest=base_v[2])
    print("B  control: the same record satisfies the BASE pins (the record itself is valid)")

# C: a base-written root opened by the candidate
child = r'''
import sys, os
sys.path.insert(0, sys.argv[2]); os.environ["CAND_DIR"] = sys.argv[1]; sys.argv = [sys.argv[0]] + sys.argv[3:]
from boot import *
root = __import__("pathlib").Path(sys.argv[1 + 0] if False else os.environ["V01_ROOT"])
clock = FixedClock(START, step_micros=1000)
rt = open_rt(root, clock=clock, script=[odds_response(), odds_response()])
rt.acquire(odds_item("w1")); approve(rt); clock.advance(seconds=900); rt.acquire(odds_item("w2"))
print("base wrote", len(pit_rows(rt)), "PIT rows", rt.config.derivation_version)
'''
croot = pathlib.Path(tempfile.mkdtemp(prefix="v01-base-root-"))
env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(), V01_ROOT=str(croot), CAND_DIR=BASE); env.pop("PYTHONPATH", None)
out = subprocess.run([sys.executable, "-B", "-c", child, BASE, str(HERE)], env=env, capture_output=True, timeout=600)
print("C  base child:", out.stdout.decode().strip()[-200:], out.stderr.decode()[-300:] if out.returncode else "")
from genesis_adapters.oddspapi.pipeline import PipelineHalt
from genesis.quota import QuotaLedger, VerifiedCacheStore
try:
    cache = VerifiedCacheStore(croot / "quota" / "cache")
    ql = QuotaLedger(croot / "quota" / "ledger.jsonl", policy=test_quota_policy(), allow_test_policy=True, cache_store=cache)
    rt = open_rt(croot, clock=FixedClock("2026-10-01T13:00:00.000000Z", step_micros=1000), quota_ledger=ql, cache=cache)
    try:
        rt.resume()
        print("C  candidate start on a base root: resume OK (derivation", rt.config.derivation_version, ")")
    except PipelineHalt as h:
        halts = [r["reason"] for r in acquisition_rows(rt) if r["record_type"] == "acq_halted"]
        cov = [(r["note"], r["status"]) for r in coverage_rows(rt) if r["note"] == h.code.value]
        print("C  candidate start on a base root: PipelineHalt(%s); durable halts=%s; coverage=%s" % (h.code, halts, cov[-1:]))
        rt2 = reopen(rt)
        try:
            rt2.resume(); print("C  second start: resume OK")
        except PipelineHalt as h2:
            print("C  second start: PipelineHalt(%s) again (every start halts on the old root)" % h2.code)
except Exception as exc:
    print("C  candidate start on a base root: %s: %s" % (type(exc).__name__, str(exc)[:200]))

# D / E
def poisoned():
    p = parp.odds_payload(); parp.fixture_of(p)["fixtureId"] = "not a valid id"; return parp.dump(p)
def deep():
    p = parp.odds_payload(); parp.fixture_of(p)["participant1Name"] = "@d"
    return parp.dump_with(p, d="[" * 60 + "]" * 60)
def overflow():
    p = parp.odds_payload(); parp.fixture_of(p)["participant1Id"] = int("9" * 70); return parp.dump(p)
SCRIPT = [odds_response(), ok(poisoned(), headers=JSON), ok(deep(), headers=JSON), ok(overflow(), headers=JSON),
          odds_response()]
def build(root):
    clock = FixedClock(START, step_micros=1000)
    rt = open_rt(root, clock=clock, script=list(SCRIPT))
    for i, w in enumerate(("w1", "w2", "w3", "w4", "w5")):
        rt.acquire(odds_item(w))
        if i == 0:
            approve(rt)
        clock.advance(seconds=900)
    return rt
def digest_tree(root):
    out = {}
    for p in sorted(pathlib.Path(root).rglob("*")):
        if p.is_file() and p.name != ".adapter-run.lock" and "lock" not in p.name:
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out
with scratch_root() as r1, scratch_root() as r2:
    rt1 = build(r1); rt2 = build(r2)
    d1, d2 = digest_tree(r1), digest_tree(r2)
    diff = sorted(k for k in set(d1) | set(d2) if d1.get(k) != d2.get(k))
    states = {a: s.state + ":" + str(s.failure) for a, s in rt1.stores.acquisition.attempts().items()}
    print("D  two fresh roots, same script: %d durable files, %d differ %s" % (len(d1), len(diff), diff[:5]))
    print("D  attempt verdicts:", sorted(states.values()))
    before = {a: (s.state, s.failure) for a, s in rt1.stores.acquisition.attempts().items()}
    rt = rt1
    for n in range(3):
        rt = reopen(rt); rt.resume()
    after = {a: (s.state, s.failure) for a, s in rt.stores.acquisition.attempts().items()}
    print("E  3 restarts: verdicts unchanged:", before == after)
    with scratch_root() as tgt:
        target = pl.build_stores(tgt, derivation_version=rt.config.derivation_version, policy=rt.config.policy,
                                 licensing_note=pl.FIXTURE_LICENSING_NOTE)
        rebuilt = pl.rebuild_into(rt, target, clock=FixedClock("2026-10-02T00:00:00.000000Z", step_micros=1000))
        src = sorted(r["payload_hash"] for r in pit_rows(rt))
        dst = sorted(r["payload_hash"] for r in target.pit.log.records() if r.get("record_type") == "pit_record")
        print("E  PIT-09 rebuild: %d emissions; identical artifact set: %s" % (len(rebuilt), src == dst))
