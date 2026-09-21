"""Baseline-compatible hostile F14 probe; run only at pre-R8 checkpoint."""

from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
from pathlib import Path

from genesis.quota import QuotaLedger, QuotaPolicy


def _worker(path_text: str, barrier, worker: int) -> None:
    ledger = QuotaLedger(
        path_text,
        policy=QuotaPolicy(
            daily_billable_limit=7,
            monthly_billable_limit=250,
            monthly_reserve=0,
        ),
    )
    barrier.wait()
    decision = ledger.request(
        request_id=f"race-{worker}",
        occurred_at="2026-01-01T00:00:00Z",
    )
    os._exit(0 if decision.allowed else 2)


def main() -> int:
    policy = QuotaPolicy(
        daily_billable_limit=999,
        monthly_billable_limit=220,
        monthly_reserve=30,
    )
    quota = QuotaLedger(policy=policy)
    for index in range(190):
        assert quota.request(
            request_id=f"normal-{index}",
            occurred_at="2026-01-01T00:00:00Z",
        ).allowed
    call_191 = quota.request(
        request_id="normal-191",
        occurred_at="2026-01-01T00:00:00Z",
    )
    cache_bypass = quota.request(
        request_id="cache-without-evidence",
        occurred_at="2026-01-01T00:00:00Z",
        cached=True,
    )

    with tempfile.TemporaryDirectory(prefix="genesis-r8-red-") as root_text:
        path = Path(root_text) / "quota.jsonl"
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(9)
        processes = [
            context.Process(target=_worker, args=(str(path), barrier, worker))
            for worker in range(8)
        ]
        for process in processes:
            process.start()
        barrier.wait()
        for process in processes:
            process.join(30)
        exits = sorted(process.exitcode for process in processes)
        persisted = QuotaLedger(
            path,
            policy=QuotaPolicy(
                daily_billable_limit=7,
                monthly_billable_limit=250,
                monthly_reserve=0,
            ),
        ).usage("2026-01-01T12:00:00Z")

    result = {
        "normal_call_191_allowed": call_191.allowed,
        "monthly_used_after_191": call_191.monthly_used,
        "evidence_free_cached_true_allowed": cache_bypass.allowed,
        "concurrent_exit_codes": exits,
        "concurrent_usage": persisted,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    unsafe = (
        not call_191.allowed
        and call_191.monthly_used == 190
        and cache_bypass.allowed
        and exits == [0] * 8
        and persisted == (8, 8)
    )
    print("EXPECTED_F14_UNSAFE_BEHAVIOURS_REPRODUCED" if unsafe else "UNEXPECTED_RESULT")
    return 0 if unsafe else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
