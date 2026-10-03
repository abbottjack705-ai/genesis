"""A11 (RA5-001): high-volume seeded fuzz of the PURE stage, aimed past the capture-time checks.

For each mutated ODDS body:
  1. the capture-time content check (strict JSON with the policy bounds + closed envelope) - the HA-04 verdict;
  2. ``derivation.derive`` (the R6 total boundary) -> documents | failure (+ class name for DERIVATION_FAULT);
  3. determinism: derive again -> identical outcome and identical document bytes;
  4. stack-depth independence: derive again at a deep caller stack (recursion headroom ~120 frames) -> same outcome
     (a RecursionError that depends on the caller would make normalize-time and verify-time derivations disagree);
  5. emission preconditions on every document (what emit_documents constructs OUTSIDE the boundary): the frozen
     ``BitemporalRecord`` (valid_to > valid_from, ready_at >= available_at, timestamps parse) and, for OPEN books,
     ``ResearchEvidence`` and its claim; a failure here would raise out of ``normalize`` -> the RA5-001 wedge again.
Reports: outcome classes, everything the safety net caught (class names), any capture-PASS -> derive-reject pairs,
non-determinism, depth dependence, emission-precondition failures (DEFECT).
usage: a11_fuzz_pure.py <seed> <iterations>
"""
from boot import *
import copy, random, sys, collections, json as _json, threading
from genesis_adapters import jsonstrict, schema as schema_mod
from genesis_adapters.oddspapi import derivation, emit
from genesis.pit import BitemporalRecord
from genesis.canonical import ResearchEvidence, EvidenceStatus
from genesis.provenance import ProvenanceRef, AvailabilityClass
from genesis.repro import canonical_json, sha256_bytes

SEED, N = int(sys.argv[1]), int(sys.argv[2])
rng = random.Random(SEED)
POLICY = parp.POLICY
CTX = parp.make_ctx()
exec(open(str(HERE) + "/a10_fuzz_e2e.py").read().split("def paths(")[0].split("rng = random.Random(SEED)")[1])  # NUMS/STRS/OTHER/chain

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
ID_KEYS = {"fixtureId", "participant1Id", "participant2Id", "tournamentId", "sportId", "participant1Name",
           "participant2Name", "startTime", "changedAt", "price", "active", "statusId", "bookmakerOdds", "markets",
           "outcomes", "players", "handicap", "line", "bookmakerFixtureId", "fixturePath", "marketActive"}
TARGETED = [q for q in ALL if isinstance(q[-1], str) and q[-1] in ID_KEYS] + \
           [q for q in ALL if len(q) > 1 and q[-2] in ("bookmakerOdds", "markets", "outcomes", "players")]
# values that PASS the capture checks (within bounds, valid UTF-8, unique keys) but are hostile to the parser
PASSING = ["1E+999", "-1E+999", "1E-999", "9.999E+1000", "1" + "0" * 1000, "-" + "9" * 1001, "1." + "0" * 3000,
           "1." + "0" * 3000 + "1", "0." + "0" * 998 + "1", "1.0001", "1.00001", "1000.0000", "1000.00001", "1.01",
           "1.009999999999999999999999999999999999999999", "0", "-0", "1", "2", "1.5", "true", "null", '""',
           '"\\u0000"', '"\\ud83d\\ude00"', '"\\u2028"', '"A' + "a" * 63 + '"', '"A' + "a" * 64 + '"', '"x\\n"',
           '"' + "1" * 64 + '"', '"' + "1" * 65 + '"', '"2026-10-03T14:00:00Z"', '"2026-10-03T14:00:00.000000Z"',
           '"2026-10-01T12:00:05Z"', '"2026-10-01T12:00:06Z"', '"2026-10-01T11:59:59.999999Z"',
           '"2026-10-01T12:05:00Z"', '"2026-10-01T12:04:59Z"', '"2026-10-01T13:05:00Z"', '"9999-12-31T23:59:59Z"',
           '"0001-01-01T00:00:00Z"', '"2026-10-03T14:00:00+00:00"', '"2026-10-03T14:00:00-00:00"',
           '"2026-10-03T14:00:00+14:00"', '"2026-10-03T14:00:00.123456789Z"', '"2026-02-29T00:00:00Z"',
           str(2 ** 63), str(10 ** 64 - 1), str(10 ** 64), "[]", "{}", '{"a":{}}', "[1,2,3]"]
KEYS = ["A" + "a" * 63, "A" + "a" * 64, "x\n", "", " ", "é", "1" * 64, "1" * 65, "0", "-1", "999999999999",
        "2001", "2002", "2003", "1010", "pinnacle", "bk.x"]

def mutate():
    p = copy.deepcopy(BASE); lits = {}; ops = []
    for j in range(rng.choice((1, 1, 1, 2, 3))):
        path = rng.choice(TARGETED if rng.random() < 0.6 else ALL)
        marker = "@L%d" % j
        op = rng.choice(("lit", "lit", "lit", "depth", "key", "del", "dup"))
        try:
            parent = getp(p, path[:-1]) if len(path) > 1 else p
            if op == "del":
                if isinstance(parent, dict):
                    parent.pop(path[-1], None)
                ops.append(("del", path)); continue
            if op == "key" and isinstance(parent, dict) and path[-1] in parent:
                parent[rng.choice(KEYS)] = parent.pop(path[-1]); ops.append(("key", path)); continue
            if op == "dup" and isinstance(parent, list):
                parent.append(copy.deepcopy(parent[path[-1]])); ops.append(("dup", path)); continue
            if op == "depth":
                lit = chain(max(0, rng.choice((48, 49, 50)) - len(path)))
            else:
                lit = rng.choice(PASSING)
            parent[path[-1]] = marker; lits[marker] = lit; ops.append((op, path, lit[:30]))
        except (TypeError, KeyError, IndexError):
            pass
    text = _json.dumps(p, sort_keys=True)
    for marker, lit in lits.items():
        text = text.replace(_json.dumps(marker), lit, 1)
    return text.encode("utf-8"), ops

def capture_verdict(raw):
    try:
        payload = jsonstrict.loads_strict(raw, max_bytes=POLICY.max_response_bytes, max_depth=POLICY.json_max_depth,
                                          max_exponent=POLICY.json_max_number_exponent)
    except jsonstrict.StrictJsonError as exc:
        return "REJECT:" + exc.code
    env = [f for f in schema_mod.validate_closed(payload, parp.ODDS_SCHEMA) if f.scope == "RESPONSE"]
    return "REJECT:ENVELOPE" if env else "PASS"

def outcome(d):
    if d.failure is None:
        return ("DOCS", tuple(doc.data for doc in d.documents))
    return ("FAIL:%s%s" % (d.failure.value, (":" + d.detail) if d.detail else ""), ())

def at_depth(fn, frames):
    if frames <= 0:
        return fn()
    return at_depth(fn, frames - 1)

def emission_preconditions(docs):
    problems = []
    t1 = CTX.response_received_at
    for doc in docs:
        try:
            BitemporalRecord(record_id="pit:" + "0" * 64, entity_id=doc.entity_id, source_id="src",
                             payload_hash=doc.artifact_hash, available_at=t1, published_at=doc.publisher_timestamp,
                             retrieved_at=t1, ready_at=t1, valid_from=t1, valid_to=doc.valid_to, superseded_by=None,
                             superseded_at=None)
            if doc.state == "OPEN":
                body = _json.loads(doc.data)
                claim = canonical_json({"market_id": body["market_id"], "bookmaker_id": body["bookmaker_id"],
                                        "line": body["line"], "odds": {s: i["odds_decimal"] for s, i in sorted(body["selections"].items())}})
                ResearchEvidence(evidence_id="rev:" + "0" * 64, event_id=body["event_id"], category=emit.EVIDENCE_CATEGORY,
                                 normalized_claim=claim.decode("utf-8"),
                                 source_ref=ProvenanceRef(artifact_hash=doc.artifact_hash, contract_id="c", source_uri="u",
                                                          retrieved_at=t1, parse_ready_at=t1,
                                                          availability_class=AvailabilityClass.DERIVED,
                                                          parser_version="p", observation_id="0" * 64),
                                 source_timestamp=doc.publisher_timestamp, retrieved_at=t1,
                                 status=EvidenceStatus.CONFIRMED, freshness_expires_at=doc.valid_to,
                                 extractor_version="p", ready_at=t1)
        except Exception as exc:
            problems.append("%s: %s" % (type(exc).__name__, str(exc)[:60]))
    return problems

threading.stack_size(64 * 1024 * 1024)
classes = collections.Counter(); net = collections.Counter(); pass_then_reject = collections.Counter()
defects = collections.OrderedDict()
def body():
    import sys as _s
    for i in range(N):
        raw, ops = mutate()
        cap = capture_verdict(raw)
        d1 = derivation.derive(raw, CTX)
        o1 = outcome(d1)
        o2 = outcome(derivation.derive(raw, CTX))
        limit = _s.getrecursionlimit()
        import inspect
        depth_now = len(inspect.stack(0))
        o3 = at_depth(lambda: outcome(derivation.derive(raw, CTX)), max(0, limit - depth_now - 120))
        key = o1[0]
        classes[(cap, key)] += 1
        if key.startswith("FAIL:DERIVATION_FAULT"):
            net[key] += 1
        if cap == "PASS" and key.startswith("FAIL"):
            pass_then_reject[key] += 1
        problems = []
        if o1 != o2:
            problems.append("NONDETERMINISTIC")
        if o1[0] != o3[0] or o1 != o3:
            problems.append("STACK_DEPTH_DEPENDENT:%s->%s" % (o1[0], o3[0]))
        if d1.failure is None:
            problems += ["EMIT_PRECONDITION " + p for p in emission_preconditions(d1.documents)]
        for p in problems:
            k = p.split(":")[0][:60]
            if k not in defects:
                defects[k] = (i, ops, p)
                open(SP + "/out/a11_seed%d_case%d.json" % (SEED, i), "wb").write(raw)
t = threading.Thread(target=body); t.start(); t.join()
print("A11 seed=%d iterations=%d" % (SEED, N))
print("(capture verdict, derive outcome) classes:")
for k, v in classes.most_common():
    print("   %6d  %s" % (v, k))
print("safety net (DERIVATION_FAULT) caught:", dict(net) if net else "nothing")
print("capture PASS -> terminal derivation rejection:", dict(pass_then_reject) if pass_then_reject else "none")
print("defect classes:", len(defects))
for k, (i, ops, p) in defects.items():
    print("  DEFECT", k, "case", i, ops, p)
