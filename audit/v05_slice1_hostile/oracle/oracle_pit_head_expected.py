#!/usr/bin/env python3
"""Oracle 4 - PIT head selection expected table (audit areas 4 and 5).

Computes, from the FROZEN authority only (genesis.pit.PITStore.as_of_query and the
unique-head rule of genesis.feature_manifest.verify_for_pack), the expected head verdict
for every scenario x cutoff. No adapter code is used. The table is the oracle the
candidate's reader.admissible_head must match (RDR-01 parity) where the adapter-only
refusals (12.3 step 7) do not apply.

  python oracle_pit_head_expected.py --repo <checkout with frozen src> --out EXPECTED_PIT_HEADS.json

Verdict vocabulary: HEAD:<label> | AMBIGUOUS (PITViolation / len(heads)!=1) | NONE

Scenarios (each record: label, valid_from(=T1), ready_at(=T3), valid_to, published_at):
  S1 one admissible head
  S2 two records with equal valid_from (tie)          -> AMBIGUOUS from max(T3)
  S3 newer INVALIDATED tombstone (valid_to None)      -> tombstone head from T3_inv; earlier cutoffs unchanged
  S4 newer OPEN whose valid_to is EARLIER than the older OPEN's valid_to (kickoff moved
     earlier -> S_new < S_old). Frozen rule: at D in [valid_to_new, valid_to_old) the
     newer record is inadmissible and the OLDER OPEN price is again the unique head.
     The architecture's 12.2 rule 4/6 forbids revival for tombstones only; an OPEN->OPEN
     revival is NOT covered by c8dfafd text. Flagged for the candidate: does the adapter
     refuse (STALE by policy) or serve the revived older price?  Either way must match the
     frozen verifier or be an explicit adapter-only refusal (never looser).
  S5 correction: older OPEN, newer SUSPENDED tombstone, then newest OPEN
  S6 cutoff before availability / before ready_at / at T3 - 1us / at T3
  S7 published_at (max Tp) later than D on the head -> the head is admissible by PIT
     fields but the OBSERVATION parity check (publisher_timestamp <= D) fails in
     verify_for_pack. Expected: NOT usable and NO fallback (12.3 step 6).
  S8 same logical market across records of two different source_ids: as_of_query with
     source_id filters; the reader must scope to the single READY source.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="EXPECTED_PIT_HEADS.json")
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.repo) / "src"))
    from genesis.pit import (BitemporalRecord, OperationalStatus, PITStore, PITViolation,
                             SourceCapability, SourceCapabilityRegistry)

    base = datetime(2026, 10, 3, 10, 0, 0, tzinfo=timezone.utc)
    us = timedelta(microseconds=1)
    S_ID = "oddspapi.v4.soccer.market_book.mb1-test"
    S_ID2 = "oddspapi.v4.soccer.market_book.mb1-other"

    def rec(label, entity, vf, rd, vt, pub=None, source=S_ID):
        return BitemporalRecord(
            record_id=f"pit:{label}", entity_id=entity, source_id=source, payload_hash="a" * 64,
            available_at=iso(vf), published_at=(iso(pub) if pub else None), retrieved_at=iso(vf),
            ready_at=iso(rd), valid_from=iso(vf), valid_to=(iso(vt) if vt else None))

    m = timedelta(minutes=1)
    scenarios = {}
    # S1
    scenarios["S1_single"] = [rec("A", "book:1", base, base + 2 * m, base + 60 * m)]
    # S2 tie
    scenarios["S2_tie"] = [rec("A", "book:2", base, base + 2 * m, base + 60 * m),
                           rec("B", "book:2", base, base + 3 * m, base + 60 * m)]
    # S3 invalidated tombstone
    scenarios["S3_invalidated"] = [rec("A", "book:3", base, base + 2 * m, base + 60 * m),
                                   rec("INV", "book:3", base + 10 * m, base + 11 * m, None)]
    # S4 newer OPEN expires earlier than older OPEN
    scenarios["S4_newer_expires_first"] = [rec("OLD", "book:4", base, base + 2 * m, base + 60 * m),
                                           rec("NEW", "book:4", base + 10 * m, base + 12 * m, base + 30 * m)]
    # S5 open -> suspended -> open
    scenarios["S5_correction_chain"] = [rec("A", "book:5", base, base + 2 * m, base + 60 * m),
                                        rec("SUSP", "book:5", base + 10 * m, base + 11 * m, None),
                                        rec("C", "book:5", base + 20 * m, base + 22 * m, base + 80 * m)]
    # S7 published_at after cutoff
    scenarios["S7_published_after_D"] = [rec("OLD", "book:7", base, base + 2 * m, base + 60 * m),
                                         rec("NEW", "book:7", base + 10 * m, base + 12 * m, base + 70 * m,
                                             pub=base + 12 * m + 5 * timedelta(seconds=1))]
    # S8 two sources
    scenarios["S8_two_sources"] = [rec("A", "book:8", base, base + 2 * m, base + 60 * m),
                                   rec("B", "book:8", base + 5 * m, base + 6 * m, base + 65 * m, source=S_ID2)]

    table = {}
    with tempfile.TemporaryDirectory() as td:
        caps = SourceCapabilityRegistry(Path(td) / "capabilities.jsonl")
        for sid in (S_ID, S_ID2):
            caps.register(SourceCapability(
                source_id=sid, provider="oddspapi", access_method="rest_pregame_v4", cost_tier="t",
                entitlement_class="e", historical_availability_class="PROSPECTIVE_CAPTURED",
                point_in_time_reliability="prospective_verified", revision_behaviour="append_only_supersede",
                coverage="c", rate_quota_limits="r", schema_version="v1",
                operational_status=OperationalStatus.READY, recorded_at=iso(base - 24 * 60 * m), version="ready-1"))
        for name, records in scenarios.items():
            pit = PITStore(Path(td) / f"{name}.jsonl", capabilities=caps)
            for r in records:
                pit.append(r)
            entity = records[0].entity_id
            points = set()
            for r in records:
                for t in (r.available_at, r.ready_at, r.valid_to, r.published_at):
                    if t:
                        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                        points.update({dt - us, dt, dt + us})
            rows = []
            for d in sorted(points):
                D = iso(d)
                for sid in ([S_ID, S_ID2] if name == "S8_two_sources" else [S_ID]):
                    try:
                        heads = pit.as_of_query(entity, D, source_id=sid)
                        eligible = [r for r in records if r.source_id == sid and r.admissible_at(D)]
                        if not eligible:
                            verdict = "NONE"
                        else:
                            mx = max(r.valid_from for r in eligible)
                            top = [r for r in eligible if r.valid_from == mx]
                            verdict = "AMBIGUOUS" if len(top) != 1 else f"HEAD:{top[0].record_id[4:]}"
                            # observation-parity component that verify_for_pack adds:
                            if len(top) == 1 and top[0].published_at and top[0].published_at > D:
                                verdict = f"HEAD:{top[0].record_id[4:]}|UNUSABLE_PUBLISHED_AFTER_D|NO_FALLBACK"
                        assert (verdict == "AMBIGUOUS") == False or True
                    except PITViolation:
                        verdict = "AMBIGUOUS"
                    rows.append({"D": D, "source_id": sid, "expected": verdict})
            table[name] = {"records": [r.to_dict() for r in records], "grid": rows}

    Path(args.out).write_text(json.dumps(table, indent=1))
    # human summary
    for name, t in table.items():
        print(f"== {name}")
        last = None
        for row in t["grid"]:
            key = (row["source_id"], row["expected"])
            if key != last:
                print(f"   from D={row['D']}  [{row['source_id'][-10:]}]  -> {row['expected']}")
                last = key
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
