"""Q01 (RA5-011 residual): does a restart change what a QUOTA_DIVERGENCE response yields?

Architecture 15 F-37 ("Quota divergence vs provider headers"): evidence retained = "acquisition + headers"; coverage
NOT_ATTEMPTED (QUOTA_DIVERGENCE); Observation / head = "none; halt". Section 15 default: "no usable observation".
HA-04 / 14.4: a restart converges to the durable history of an uninterrupted run.

For each usage header (a figure above the debit, and R6's newly halting unreadable forms):
  (a) uninterrupted: acquire -> AcquisitionHalt? PIT records for the response? pending_work? reader?
  (b) restart (reopen + resume, exactly what `cli run --mode G2R` does first): PIT records? documents? reader?
usage: q01_quota_divergence_restart.py
"""
from boot import *
from genesis_adapters.oddspapi import quiescence
from genesis_adapters.oddspapi.acquisition import AcquisitionHalt

def usage(value):
    return JSON + (("x-requests-used", value),)

def run(value):
    res = {}
    with scratch_root() as root:
        clock = FixedClock(START, step_micros=1000)
        rt = open_rt(root, clock=clock, script=[odds_response(), odds_response(headers=usage(value))])
        rt.acquire(odds_item("w1")); approve(rt)
        base_pit = len(pit_rows(rt))
        entities = sorted({r["entity_id"] for r in pit_rows(rt)})
        clock.advance(seconds=900)
        try:
            out = rt.acquire(odds_item("w2"))
            res["a_acquire"] = "returned %s" % (out.outcome.failure,)
            aid = out.outcome.acquisition_id
        except AcquisitionHalt as h:
            res["a_acquire"] = "AcquisitionHalt(%s)" % h
            aid = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_planned"][-1]["acquisition_id"]
        res["a_halts"] = [r["reason"] for r in acquisition_rows(rt) if r["record_type"] == "acq_halted"]
        res["a_new_pit_records_from_w2"] = len(pit_rows(rt)) - base_pit
        res["a_pending_work"] = list(quiescence.pending_work(rt.stores))
        decision = parp.iso_add(rt.clock.peek(), seconds=30)
        v = rt.reader().head(entities[0], decision)
        res["a_reader"] = type(v).__name__ + ":" + str(getattr(getattr(v, "code", None), "value", ""))
        rt2 = reopen(rt)
        rt2.resume()
        res["b_new_pit_records_from_w2_after_restart"] = len(pit_rows(rt2)) - base_pit
        res["b_w2_state"] = rt2.stores.acquisition.attempts()[aid].state
        from_w2 = [d for d in documents(rt2) if d["acquisition_id"] == aid]
        res["b_documents_from_w2"] = len(from_w2)
        res["b_open_documents_from_w2"] = sum(1 for d in from_w2 if d["market_state"] == "OPEN")
        decision = parp.iso_add(rt2.clock.peek(), seconds=30)
        v = rt2.reader().head(entities[0], decision)
        used = getattr(v, "document", None)
        res["b_reader"] = type(v).__name__ + (" from w2" if used and used.get("acquisition_id") == aid else "")
        res["b_halt_still_in_force"] = rt2.stores.acquisition.circuit_open("ODDS", decision)
    return res

for value in ("99999", "not a number", "1e5", "-5", "99,999", "９９", "1" * 300):
    r = run(value)
    print("x-requests-used=%r" % value[:20])
    for k, v in r.items():
        print("   ", k, "=", v)
    diverges = r["a_new_pit_records_from_w2"] == 0 and r["b_new_pit_records_from_w2_after_restart"] > 0
    print("    => %s" % ("RESTART-DEPENDENT: no observation in the uninterrupted run, usable observations after restart"
                         if diverges else "consistent"))
