"""A01 (RA5-001 crash idempotency): a derivation rejection written for an attempt that is NOT the newest planned
attempt, with a crash between the ``acq_derivation_rejected`` row and its coverage entry.

Flow modelled on the operator CLI: G2 (``rt.runner.acquire``: raw only, nothing normalized) captures a poisoned ODDS
body (w2) and then a healthy one (w3); the first G2R start (``rt.resume()``) derives both in ledger order. The crash
is injected at the runner checkpoint ``after_derivation_rejected`` (the row is durable, its settlement is not).
Claim under test (R6 SUMMARY 2, acquisition.reject_derivation docstring): "idempotent across a crash at every write:
... after it, settle_last completes the coverage entry".

CONTROL: the same crash when the poisoned capture IS the newest planned attempt.
"""
from boot import *

class Crash(BaseException):
    pass

def crash_at(name):
    def checkpoint(step):
        if step == name:
            raise Crash()
    return checkpoint

def poisoned():
    p = parp.odds_payload()
    parp.fixture_of(p)["fixtureId"] = "not a valid id"          # the R6 "fifth class" (a terminal derivation rejection)
    return parp.dump(p)

def rejection_coverage(rt, aid):
    """The coverage entry the rejection verdict calls for (its id is keyed on the attempt and the failure code)."""
    rejected = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_derivation_rejected"
                and r["acquisition_id"] == aid]
    if not rejected:
        return None
    note = rejected[-1]["failure"]
    return [(r["note"], r["status"]) for r in coverage_rows(rt)
            if r["entry_id"] == gid("cov", acquisition_id=aid, note=note)]

def scenario(newest_is_poisoned):
    with scratch_root() as root:
        clock = FixedClock(START, step_micros=1000)
        script = [odds_response(), ok(poisoned(), headers=JSON)] + ([] if newest_is_poisoned else [odds_response()])
        rt = open_rt(root, clock=clock, script=script)
        rt.acquire(odds_item("w1")); approve(rt)                      # healthy, normalized (gives an expected scope)
        clock.advance(seconds=900)
        out2 = rt.runner.acquire(odds_item("w2"))                     # G2: raw only
        aid2 = out2.acquisition_id
        if not newest_is_poisoned:
            clock.advance(seconds=900)
            rt.runner.acquire(odds_item("w3"))                        # G2: raw only, a NEWER attempt
        rt2 = reopen(rt, runner_checkpoint=crash_at("after_derivation_rejected"))
        crashed = False
        try:
            rt2.resume()
        except Crash:
            crashed = True
        rows_after_crash = [r["record_type"] for r in acquisition_rows(rt2) if r.get("acquisition_id") == aid2]
        rt3 = reopen(rt2)
        rt3.resume()                                                  # the restart: settle_last + derive the rest
        rt3.resume()                                                  # and again
        state = rt3.stores.acquisition.attempts()[aid2].state
        cov = rejection_coverage(rt3, aid2)
        pending = quiescence_pending(rt3)
        return dict(crashed=crashed, rows_for_poisoned_attempt_after_crash=rows_after_crash, final_state=state,
                    rejection_coverage_entries=cov, pending_work=pending)

def quiescence_pending(rt):
    from genesis_adapters.oddspapi import quiescence
    return list(quiescence.pending_work(rt.stores))

from genesis_adapters.ids import gid
for label, flag in (("CONTROL poisoned capture is the newest attempt", True),
                    ("ATTACK  a newer attempt follows the poisoned capture (G2 -> G2R)", False)):
    res = scenario(flag)
    print(label)
    for k, v in res.items():
        print("   ", k, "=", v)
    verdict = "HELD" if res["rejection_coverage_entries"] else "DEFECT: rejection row durable, REJECTED coverage entry never written"
    print("    =>", verdict)
