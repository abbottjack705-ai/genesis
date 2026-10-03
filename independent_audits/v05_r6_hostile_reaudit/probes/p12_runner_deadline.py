"""AREA B/C at the runner: slow work between quota approval and send; ClockFault placement; late response."""
from boot import *
from genesis_adapters.clock import ClockFault
from genesis_adapters.errors import AcquisitionHalt
res = {}

def state(rt):
    return [r["record_type"] for r in acquisition_rows(rt)]

# 1. scope pinning (slow work after the debit) crosses the deadline -> must not send
with scratch_root() as root:
    clock = FixedClock(START, step_micros=1000)
    rt = open_rt(root, clock=clock, script=[odds_response()])
    orig = rt.runner.scope_pinner
    def slow(request, tq):
        h = orig(request, tq); clock.advance(seconds=61); return h
    rt.runner.scope_pinner = slow
    out = rt.runner.acquire(odds_item())
    res["1_slow_scope_61s"] = {"sent_calls": len(rt.runner.transport.calls), "outcome": out.outcome, "detail": out.detail,
                               "rows": state(rt)}
# 1b. 59.9 s -> sends, deadline_at passed correctly
with scratch_root() as root:
    clock = FixedClock(START, step_micros=1000)
    rt = open_rt(root, clock=clock, script=[odds_response()])
    orig = rt.runner.scope_pinner
    def slow(request, tq):
        h = orig(request, tq); clock.advance(seconds=59.9); return h
    rt.runner.scope_pinner = slow
    out = rt.runner.acquire(odds_item())
    c = rt.runner.transport.calls
    res["1b_slow_scope_59.9s"] = {"sent_calls": len(c), "deadline_at": c[0].deadline_at if c else None, "outcome": out.outcome}

# 2. response whose T1 is exactly the deadline / 1us before / after -> runner
for label, delta in (("t1_eq_deadline", 0), ("t1_deadline_minus_1us", -1), ("t1_deadline_plus_1us", 1)):
    with scratch_root() as root:
        clock = FixedClock(START, step_micros=1000)
        rt = open_rt(root, clock=clock)
        def step(clk):
            # force T1 relative to the deadline of this attempt = Tq + 60s ; Tq = first row's Tq
            tq = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_quota_decided"][-1]["Tq"]
            dl = parp.iso_add(tq, seconds=60, micros=delta)
            return Scripted(body=parp.dump(parp.odds_payload()), headers=JSON, t1=dl, latency=0)
        rt.runner.transport.script = [step]
        out = rt.runner.acquire(odds_item())
        res["2_" + label] = {"outcome": out.outcome, "failure": str(out.failure), "detail": out.detail}

# 3. ClockFault raised by the clock right after the debit (at the T0 read) -> state / exception type
class FaultClock(FixedClock):
    def __init__(self, *a, fault_on=None, **k):
        super().__init__(*a, **k); self.fault_on = fault_on
    def now(self):
        if self.fault_on is not None and self.calls + 1 == self.fault_on:
            self.calls += 1; raise ClockFault("WALL_CLOCK_JUMP")
        return super().now()
for n in range(2, 14):
    with scratch_root() as root:
        clock = FaultClock(START, step_micros=1000, fault_on=n)
        rt = None
        try:
            rt = open_rt(root, clock=clock, script=[odds_response()])
            out = rt.runner.acquire(odds_item())
            r = ("returned", out.outcome, str(out.failure))
        except AcquisitionHalt as h:
            r = ("AcquisitionHalt", str(h.args))
        except ClockFault as e:
            r = ("RAW ClockFault escaped", e.code)
        except BaseException as e:
            r = (type(e).__name__, str(e)[:80])
        rows = [x["record_type"] for x in read_jsonl(root / "acquisition.jsonl")]
        calls = len(rt.runner.transport.calls) if rt else None
        res[f"3_clockfault_on_read_{n}"] = {"result": r, "rows": rows, "transport_calls": calls}
print(json.dumps(res, indent=1, default=str))
