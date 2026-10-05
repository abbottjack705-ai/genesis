from __future__ import annotations
import contextlib, sys
from pathlib import Path

repo = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo / "adapters"))
import adapter_tests
from adapter_tests.crash_support import cut
from adapter_tests.pipeline_support import JSON, acquisition_rows, coverage_rows, documents, odds_item, ok, open_rt, reopen
from adapter_tests.support import Crash, scratch_root
from genesis_adapters.errors import AdapterFailure, AcquisitionHalt
from genesis_adapters.oddspapi.acquisition import AcquisitionLedger

with scratch_root() as root:
    rt = open_rt(root, script=[ok(b"{", headers=JSON + (("x-requests-used", "garbage"),))])
    hit = lambda args, kwargs: args[0] == "acq_completed"
    with cut(AcquisitionLedger, hit, where="after") as state:
        with contextlib.suppress(Crash):
            rt.runner.acquire(odds_item("w1"))
    assert state["fired"] == 1
    completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"]
    assert len(completed) == 1 and completed[0]["failure"] == AdapterFailure.NOT_JSON.value
    print("after durable verdict before effects:", completed[0]["failure"], completed[0]["provider_reported_usage"])
    for n in (1, 2, 3):
        rt = reopen(rt)
        rt.resume()
        rows = acquisition_rows(rt)
        halts = [r["reason"] for r in rows if r["record_type"] == "acq_halted"]
        notes = [r["note"] for r in coverage_rows(rt)]
        from_attempt = [d for d in documents(rt) if d["acquisition_id"] == completed[0]["acquisition_id"]]
        print(f"restart {n}: halts={halts} coverage={notes} documents={len(from_attempt)}")
        assert halts == [AdapterFailure.QUOTA_DIVERGENCE.value]
        assert sorted(notes) == sorted([AdapterFailure.NOT_JSON.value, AdapterFailure.QUOTA_DIVERGENCE.value])
        assert from_attempt == []
