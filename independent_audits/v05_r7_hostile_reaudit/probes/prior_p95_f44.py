"""F-44: ordinary I/O failure while publishing the immutable RAW evidence (disk full)."""
from boot import *
import errno
from genesis.evidence import EvidenceStore
from genesis_adapters.errors import AcquisitionHalt
R = {}
with scratch_root() as root:
    rt = open_rt(root, script=[odds_response(), odds_response()])
    calls = {"n": 0}
    real = EvidenceStore.publish
    def boom(self, *a, **k):
        if k.get("contract_id", "").startswith("oddspapi-v4-raw"):
            calls["n"] += 1
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, *a, **k)
    EvidenceStore.publish = boom
    try:
        rt.acquire(odds_item("w1"))
        R["exception"] = None
    except BaseException as e:
        R["exception"] = type(e).__name__ + ":" + str(e)[:50]
    EvidenceStore.publish = real
    R["rows_after_failure"] = [r["record_type"] for r in acquisition_rows(rt)]
    R["coverage_rows_after_failure"] = [(c["status"], c.get("note")) for c in coverage_rows(rt)]
    R["sends"] = len(rt.runner.transport.calls)
    rt2 = reopen(rt, transport=rt.runner.transport)
    rec, em = rt2.resume()
    R["after_restart_rows"] = [r["record_type"] for r in acquisition_rows(rt2)]
    R["after_restart_coverage"] = [(c["status"], c.get("note")) for c in coverage_rows(rt2)]
    R["resend_on_same_item"] = (rt2.acquire(odds_item("w1")).outcome.outcome, len(rt2.runner.transport.calls))
    R["pit_rows"] = len(pit_rows(rt2))
    R["quota_debits"] = len([r for r in read_jsonl(root / "quota" / "ledger.jsonl") if r["record_type"] == "quota_billable_call"])
    R["completed_row_recorded_any_status_or_T1"] = any(r["record_type"] == "acq_completed" for r in acquisition_rows(rt2))
for k, v in R.items(): print(f"{k:42s}", v)
