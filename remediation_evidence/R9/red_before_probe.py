"""Baseline-compatible hostile F13 probe; run only at pre-R9 checkpoint."""

from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
from pathlib import Path

from genesis.evaluation import EvaluationRequest
from genesis.labels import DecisionFact, DecisionFrame, FutureOutcomeLabel
from genesis.protected import ProtectedAttemptLedger, ProtectedCampaign, ProtectedEvaluationBoundary
from genesis.provenance import AvailabilityClass, ProvenanceRef
from genesis.registry import AppendOnlyJsonl, RegistryConflict


def digest(character: str) -> str:
    return character * 64


def ref() -> ProvenanceRef:
    return ProvenanceRef(
        digest("a"),
        "synthetic-v1",
        "synthetic://red-before",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:01Z",
        AvailabilityClass.PROSPECTIVE_CAPTURED,
        "test-v1",
    )


def _reserve_worker(path_text: str, barrier, worker: int) -> None:
    campaign = ProtectedCampaign("race", "family", 1, digest("e"), minimum_cell_size=1)
    ledger = ProtectedAttemptLedger(path_text)
    barrier.wait()
    try:
        ledger.reserve(campaign, family_limit=1, note=f"worker-{worker}")
    except RegistryConflict:
        os._exit(2)
    os._exit(0)


def main() -> int:
    frame = DecisionFrame(
        "frame",
        "entity",
        "2026-01-01T00:00:00Z",
        (
            DecisionFact(
                "signal",
                1,
                "2025-12-31T23:00:00Z",
                "2025-12-31T23:01:00Z",
                ref(),
            ),
        ),
        "dataset-v1",
        digest("b"),
    )
    label = FutureOutcomeLabel(
        "label",
        "entity",
        1,
        "2026-01-01T01:00:00Z",
        ref(),
        "label-v1",
    )
    campaign = ProtectedCampaign("campaign", "family", 1, digest("e"), minimum_cell_size=1)
    boundary = ProtectedEvaluationBoundary(
        campaign,
        [frame],
        [label],
        ProtectedAttemptLedger(),
    )
    directly_leaked = getattr(
        boundary._service,
        "_ProtectedEvaluationService__labels",
    )[0].outcome_value
    callback_details: dict[str, object] = {}

    def hostile_callback(_frame: DecisionFrame) -> str:
        callback_details["pid"] = os.getpid()
        callback_details["label"] = getattr(
            boundary._service,
            "_ProtectedEvaluationService__labels",
        )[0].outcome_value
        return "0.5"

    boundary.run(
        EvaluationRequest("campaign", "strategy", digest("c"), "dataset-v1", digest("e")),
        hostile_callback,
    )

    with tempfile.TemporaryDirectory(prefix="genesis-r9-red-") as root_text:
        attempt_path = Path(root_text) / "attempts.jsonl"
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(3)
        processes = [
            context.Process(
                target=_reserve_worker,
                args=(str(attempt_path), barrier, worker),
            )
            for worker in range(2)
        ]
        for process in processes:
            process.start()
        barrier.wait()
        for process in processes:
            process.join(30)
        exits = sorted(process.exitcode for process in processes)
        persisted_attempt_rows = AppendOnlyJsonl(attempt_path).verify()

    result = {
        "directly_introspected_label": directly_leaked,
        "callback_introspected_label": callback_details.get("label"),
        "callback_pid": callback_details.get("pid"),
        "label_owner_pid": os.getpid(),
        "concurrent_exit_codes": exits,
        "persisted_attempt_rows": persisted_attempt_rows,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    unsafe = (
        directly_leaked == 1
        and callback_details.get("label") == 1
        and callback_details.get("pid") == os.getpid()
        and exits == [0, 0]
        and persisted_attempt_rows == 2
    )
    print("EXPECTED_F13_UNSAFE_BEHAVIOURS_REPRODUCED" if unsafe else "UNEXPECTED_RESULT")
    return 0 if unsafe else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
