"""Area 10 (F-32/F-33/F-40, PIT-04/05/06, INV-01/02, HA-012): immutability, corrections, tombstones.

    python -B attacks/a10_immutability.py --repo <candidate>
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

CAP_TIME = "2026-09-30T00:00:00.000000Z"


def approve(rt, at=CAP_TIME):
    """READY + binding in the scratch registries (what a G3 operator action produces; test roots only)."""

    from genesis.pit import OperationalStatus, SourceCapability

    rt.stores.capabilities.register(SourceCapability(
        source_id=rt.stores.source_id, provider="oddspapi", access_method="rest_pregame_v4", cost_tier="t",
        entitlement_class="e", historical_availability_class="none", point_in_time_reliability="prospective_verified",
        revision_behaviour="append_only_supersede", coverage="c", rate_quota_limits="r", schema_version="v1",
        operational_status=OperationalStatus.READY, recorded_at=at, version=rt.stores.derivation_version + "-ready-1"))
    rt.stores.bindings.register(source_id=rt.stores.source_id, source_contract_id=rt.stores.contract_id,
                                provider="oddspapi", approval_reference="synthetic-test-only-audit")


def pit_rows(rt):
    return [r for r in rt.stores.pit.log.records() if r.get("record_type") == "pit_record"]


def doc(rt, row):
    return json.loads(rt.stores.evidence.get_bytes(row["payload_hash"]))


def runtime(repo, root, clock, bodies):
    responses = [(200, c.JSON_HEADERS, b) for b in bodies]
    return c.open_runtime(repo, root, clock=clock, transport=c.CountingTransport(responses=responses))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    from genesis_adapters.errors import AcquisitionHalt
    from genesis_adapters.oddspapi import emit, pipeline, reader

    body = c.fixture_bytes(repo, "odds_by_tournaments.json")
    payload = json.loads(body)
    digest = __import__("hashlib").sha256(body).hexdigest()

    # F-32: a different object already at the raw path -> halt, existing bytes untouched
    root = c.scratch("f32-")
    rt = runtime(repo, root, c.StepClock(), [body])
    planted = root / "evidence" / "objects" / digest[:2] / digest
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_bytes(b"not the response")
    halted = None
    try:
        rt.acquire(c.odds_item(repo))
    except (AcquisitionHalt, pipeline.PipelineHalt) as exc:
        halted = str(getattr(exc, "code", exc))
    c.check("A10", "F-32: conflicting bytes at the raw object path -> EVIDENCE_CONFLICT halt, bytes untouched, no PIT",
            halted is not None and "EVIDENCE_CONFLICT" in halted and planted.read_bytes() == b"not the response"
            and not pit_rows(rt), halted=halted)
    c.remove(root)

    # F-33: a PIT row already exists under a record id with different content -> halt, never replaced
    root = c.scratch("f33-")
    clock = c.StepClock()
    rt = runtime(repo, root, clock, [body])
    rt.acquire(c.odds_item(repo))
    rows = pit_rows(rt)
    target = next(r for r in rows if r["valid_to"] is not None)       # an OPEN record (finite valid_to)
    root2 = c.scratch("f33b-")
    rt2 = runtime(repo, root2, c.StepClock(), [body])
    from genesis.pit import BitemporalRecord

    fields = {k: target[k] for k in BitemporalRecord.__dataclass_fields__}
    fields["valid_to"] = None                                   # same record_id, different content
    rt2.stores.pit.append(BitemporalRecord(**fields))
    halted = None
    try:
        rt2.acquire(c.odds_item(repo))
    except (AcquisitionHalt, pipeline.PipelineHalt) as exc:
        halted = str(getattr(exc, "code", exc))
    same = [r for r in pit_rows(rt2) if r["record_id"] == target["record_id"]]
    c.check("A10", "F-33: PIT record id already used with other content -> PIT_APPEND_CONFLICT halt, row not replaced",
            halted is not None and "PIT_APPEND_CONFLICT" in halted and len(same) == 1 and same[0]["valid_to"] is None,
            halted=halted, rows=len(same))
    c.remove(root2)

    # EV-02 / automatic invalidation: tamper the raw bytes of an emitted capture
    approve(rt)
    raw_obs = [r for r in c.jsonl(root / "acquisition.jsonl") if r["record_type"] == "acq_completed"][0]["raw_observation_id"]
    raw_hash = rt.stores.evidence.get_observation(raw_obs).artifact_hash
    raw_path = root / "evidence" / "objects" / raw_hash[:2] / raw_hash
    os.chmod(raw_path, stat.S_IWRITE | stat.S_IREAD)
    original = raw_path.read_bytes()
    raw_path.write_bytes(original.replace(b"2.05", b"9.05", 1))
    failed = None
    try:
        rt.verify_all()
    except Exception as exc:
        failed = type(exc).__name__
    c.check("A10", "EV-02: tampered raw bytes make verify_all fail (never a pass by omission)", failed is not None,
            error=failed)
    open_row = next(r for r in pit_rows(rt) if doc(rt, r)["market_state"] == "OPEN")
    obs = [o for o in rt.stores.evidence.get_observations(open_row["payload_hash"])
           if o.contract_id == rt.stores.contract_id][0]
    clock.jump(60)
    result = emit.invalidate_if_underivable(obs.observation_id, check=rt.verify_derivation, stores=rt.stores,
                                            clock=clock)
    c.check("A10", "INV-04: a head whose derivation no longer verifies is invalidated automatically",
            result is not None and result.head_effect == "INVALIDATED_HEAD_EMITTED",
            effect=getattr(result, "head_effect", None))
    t3_inv = next(r["ready_at"] for r in pit_rows(rt) if doc(rt, r)["market_state"] == "INVALIDATED")
    before = reader.admissible_head(open_row["entity_id"], c.add(t3_inv, micros=-1), stores=rt.stores)
    after = reader.admissible_head(open_row["entity_id"], t3_inv, stores=rt.stores)
    c.check("A10", "PIT-06/INV-01: at T3_inv - 1us the original head is still usable; at T3_inv it is INVALIDATED",
            isinstance(before, reader.UsableBook) and before.record.record_id == open_row["record_id"]
            and isinstance(after, reader.Unusable) and after.code.value == "INVALIDATED",
            before=type(before).__name__, after=getattr(after, "code", None))
    raw_path.write_bytes(original)
    c.remove(root)

    # PIT-04: a SUSPENDED head blocks an older OPEN still inside its TTL, and keeps blocking after its valid_to
    root = c.scratch("pit04-")
    clock = c.StepClock()
    suspended = copy.deepcopy(payload)
    for item in suspended:
        for block in item["bookmakerOdds"].values():
            block["bookmakerIsActive"] = False
    rt = runtime(repo, root, clock, [body, json.dumps(suspended).encode()])
    approve(rt)
    rt.acquire(c.odds_item(repo, window="w1"))
    first = {r["entity_id"]: r for r in pit_rows(rt)}
    clock.jump(600)
    rt.acquire(c.odds_item(repo, window="w2"))
    second = [r for r in pit_rows(rt) if r["record_id"] not in {x["record_id"] for x in first.values()}]
    entity = second[0]["entity_id"]
    t3_2 = second[0]["ready_at"]
    at_mid = reader.admissible_head(entity, t3_2, stores=rt.stores)
    late = c.add(first[entity]["valid_to"], seconds=1)
    at_late = reader.admissible_head(entity, late, stores=rt.stores)
    c.check("A10", "PIT-04/ST-05: SUSPENDED head blocks the older OPEN inside its TTL and after its valid_to",
            isinstance(at_mid, reader.Unusable) and at_mid.code.value == "SUSPENDED"
            and isinstance(at_late, reader.Unusable) and at_late.code.value == "SUSPENDED",
            mid=getattr(at_mid, "code", None), late=getattr(at_late, "code", None))
    c.remove(root)

    # HA-012: expected scope and ABSENT tombstones while the source is NOT READY (G2R)
    root = c.scratch("ha012-")
    clock = c.StepClock()
    missing = copy.deepcopy(payload)
    dropped = next(k for k in c.DECLARED[::-1] if k in missing[0]["bookmakerOdds"])     # a DECLARED bookmaker
    for item in missing:
        item["bookmakerOdds"].pop(dropped, None)
    rt = runtime(repo, root, clock, [body, json.dumps(missing).encode()])
    rt.acquire(c.odds_item(repo, window="w1"))
    clock.jump(600)
    rt.acquire(c.odds_item(repo, window="w2"))
    caps = [r for r in c.jsonl(root / "capabilities.jsonl") if r.get("record_type") == "source_capability_registered"]
    absent = [doc(rt, r) for r in pit_rows(rt) if doc(rt, r)["market_state"] == "ABSENT"]
    scope_rows = [r for r in c.jsonl(root / "acquisition.jsonl") if r["record_type"] == "acq_normalized"]
    c.check("A10", "HA-012: with no READY capability (G2R) a complete response lacking a bookmaker yields ABSENT "
                   "tombstones for its expected books",
            not any(r["operational_status"].upper() == "READY" for r in caps) and absent
            and all(d["provider_bookmaker_key"] == dropped for d in absent),
            capability_rows=len(caps), absent=len(absent), dropped=dropped,
            scope_hashes=[r["expected_scope_hash"] is not None for r in scope_rows])
    c.remove(root)

    # INV-02: invalidating a superseded record writes no PIT record
    root = c.scratch("inv02-")
    clock = c.StepClock()
    rt = runtime(repo, root, clock, [body, body])
    rt.acquire(c.odds_item(repo, window="w1"))
    old = {r["record_id"] for r in pit_rows(rt)}
    clock.jump(600)
    rt.acquire(c.odds_item(repo, window="w2"))
    old_open = next(r for r in pit_rows(rt) if r["record_id"] in old and doc(rt, r)["market_state"] == "OPEN")
    obs = [o for o in rt.stores.evidence.get_observations(old_open["payload_hash"])
           if o.contract_id == rt.stores.contract_id][0]
    count = len(pit_rows(rt))
    clock.jump(60)
    result = emit.emit_invalidation(invalidated_observation_id=obs.observation_id, invalidation_class="OPERATOR",
                                    reason="INVALIDATED", actor="OPERATOR", evidence_refs=("audit",), stores=rt.stores,
                                    clock=clock)
    c.check("A10", "INV-02: invalidating an already-superseded record -> NONE_ALREADY_SUPERSEDED, no PIT record",
            result.head_effect == "NONE_ALREADY_SUPERSEDED" and len(pit_rows(rt)) == count,
            effect=result.head_effect)
    c.remove(root)
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
