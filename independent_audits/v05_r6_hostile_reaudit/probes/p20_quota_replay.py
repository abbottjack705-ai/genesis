"""AREA C: crash at every runner checkpoint; restart; same request id; retry id; no automatic re-send under old debit."""
from boot import *
from genesis.quota import QuotaLedger
from genesis_adapters.errors import PlanRefused, AcquisitionHalt
res = {}
STEPS = ["before_quota", "after_quota", "after_quota_decided", "after_scope", "after_sent", "after_raw", "after_completed"]

def quota_rows(root):
    return [(r["record_type"], r.get("request_id", "")[-8:], r.get("billable_units")) for r in read_jsonl(root / "quota" / "ledger.jsonl")]

for step in STEPS:
    with scratch_root() as root:
        def hook(name, step=step):
            if name == step: raise Crash()
        t = FakeTransport([odds_response(), odds_response(), odds_response()])
        rt = open_rt(root, transport=t, runner_checkpoint=hook)
        crashed = False
        try:
            rt.acquire(odds_item())
        except Crash:
            crashed = True
        calls_before = len(t.calls)
        # restart: new runtime object over same root, SAME transport double so we can count sends
        rt2 = reopen(rt, transport=t)
        rec, emitted = rt2.resume()
        # automatic re-send attempt with the same plan item (same window, attempt 1)
        try:
            again = rt2.acquire(odds_item())
            again_r = (again.outcome.outcome, str(again.outcome.failure), again.outcome.detail)
        except BaseException as e:
            again_r = ("EXC", type(e).__name__)
        resent = len(t.calls) - calls_before
        # fresh retry attempt 2 (explicit RETRY, new id)
        clock_later = parp.iso_add(rt2.stores.acquisition.rows()[-1]["recorded_at"], seconds=600)
        rt2.clock.set(clock_later) if hasattr(rt2.clock, "set") else None
        try:
            retry = rt2.acquire(odds_item(attempt=2, purpose="RETRY", not_after=parp.iso_add(clock_later, seconds=3600)))
            retry_r = (retry.outcome.outcome, str(retry.outcome.failure), retry.outcome.detail)
        except PlanRefused as p:
            retry_r = ("PlanRefused", p.reason)
        except BaseException as e:
            retry_r = ("EXC", type(e).__name__)
        rows = [r["record_type"] + ":" + r["acquisition_id"][:6] if "acquisition_id" in r else r["record_type"] for r in acquisition_rows(rt2)]
        res[step] = {"crashed": crashed, "sends_before_crash": calls_before, "reconciled": [x[:6] for x in rec],
                     "resent_by_same_item": resent, "same_item_result": again_r, "retry_result": retry_r,
                     "total_sends": len(t.calls), "quota_rows": quota_rows(root)}
for k, v in res.items():
    print(k, json.dumps(v, default=str))
