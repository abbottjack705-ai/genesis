"""AREAS D/E/F/G: crash at every emission checkpoint of a SECOND capture (older OPEN head exists), restart, converge."""
from boot import *
import hashlib
from genesis_adapters.oddspapi.reader import Unusable

def run_two(crash_step=None, crash_nth=1):
    with scratch_root() as root:
        seen = {"n": 0}
        def hook(name):
            if crash_step and name == crash_step:
                seen["n"] += 1
                if seen["n"] == crash_nth: raise Crash()
        clock = FixedClock(START, step_micros=1000)
        rt = open_rt(root, clock=clock, script=[odds_response(), odds_response(parp.odds_payload())], checkpoint=None)
        rt.acquire(odds_item("w1")); approve(rt)
        rt.checkpoint = hook
        rt.stores  # noqa
        clock.advance(seconds=900)
        crashed = False
        try:
            rt.acquire(odds_item("w2"))
        except Crash:
            crashed = True
        # reader BEFORE restart (state as left by the crash): must not hand out a half-published capture
        ents = sorted({r["entity_id"] for r in pit_rows(rt)})
        D = parp.iso_add(clock.peek(), seconds=30)
        pre = {}
        rt_pre = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=5), step_micros=1000)) if crashed else rt
        for e in ents[:3]:
            v = rt_pre.reader().head(e, D)
            pre[e[-6:]] = type(v).__name__ + ":" + str(getattr(v, "code", ""))
        rt2 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=10), step_micros=1000)) if crashed else rt
        if crashed:
            rt2.resume()
        D2 = parp.iso_add(rt2.clock.peek(), seconds=30)
        final = {}
        for e in ents:
            v = rt2.reader().head(e, D2)
            final[e[-8:]] = (type(v).__name__, str(getattr(v, "code", "")), (v.record.payload_hash[:8] if isinstance(v, UsableBook) else ""))
        obs = [r for r in read_jsonl(root / "evidence" / "manifest.jsonl")] if (root/"evidence"/"manifest.jsonl").exists() else []
        pits = pit_rows(rt2)
        sig = {"pit_count": len(pits), "uniq_record_ids": len({r["record_id"] for r in pits}),
               "uniq_payloads": len({r["payload_hash"] for r in pits}),
               "t3_distinct_per_response": sorted({r["ready_at"] for r in pits}),
               "acq_normalized_rows": sum(1 for r in acquisition_rows(rt2) if r["record_type"] == "acq_normalized"),
               "cov_ids": len({c["entry_id"] for c in coverage_rows(rt2)}), "cov_rows": len(coverage_rows(rt2))}
        return crashed, pre, final, sig

ref_crashed, _, ref_final, ref_sig = run_two()
print("REF", ref_sig["pit_count"], ref_sig["acq_normalized_rows"], len(ref_final))
steps = ["after_normalized_row", "after_identity", "after_t2", "after_observation:1", "after_observation:7", "after_structured:3",
         "after_t3", "after_pit:1", "after_pit:6", "after_pit:12", "after_coverage"]
for st in steps:
    crashed, pre, final, sig = run_two(st)
    same_final = {k: v[:2] for k, v in final.items()} == {k: v[:2] for k, v in ref_final.items()}
    same_payload_sets = sorted(v[2] for v in final.values()) == sorted(v[2] for v in ref_final.values())
    print(st, "crashed" if crashed else "NO-CRASH(step not reached)", "| pre-restart reader:", sorted(set(pre.values()))[:2],
          "| converged_states=", same_final, "payloads=", same_payload_sets,
          "| pit", sig["pit_count"], "uniq", sig["uniq_record_ids"], "norm_rows", sig["acq_normalized_rows"],
          "T3s", len(sig["t3_distinct_per_response"]), "cov", sig["cov_rows"], "/", sig["cov_ids"])
