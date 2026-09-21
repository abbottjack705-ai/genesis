from __future__ import annotations

import multiprocessing
import os
import unittest

from genesis.execution import OrderState
from genesis.registry import AppendOnlyJsonl
from genesis.risk import Exposure, ExposureState

from ._support import scratch_directory
from .test_remediation_r5_risk import build_risk, digest
from .test_remediation_r6_execution import (
    build_execution,
    restart_adapter,
    restart_risk,
)


def _crash_inside_append_transaction(path: str) -> None:
    log = AppendOnlyJsonl(path)

    def terminate_after_verified_read(_records):
        os._exit(91)

    log.transaction(terminate_after_verified_read)


ORDER_PATHS: dict[OrderState, tuple[OrderState, ...]] = {
    OrderState.RISK_APPROVED: (),
    OrderState.SUBMISSION_PENDING: (OrderState.SUBMISSION_PENDING,),
    OrderState.SUBMISSION_SENT: (
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMISSION_SENT,
    ),
    OrderState.ACK_RECEIVED: (
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMISSION_SENT,
        OrderState.ACK_RECEIVED,
    ),
    OrderState.PARTIALLY_MATCHED: (
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMISSION_SENT,
        OrderState.ACK_RECEIVED,
        OrderState.PARTIALLY_MATCHED,
    ),
    OrderState.FULLY_MATCHED: (
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMISSION_SENT,
        OrderState.ACK_RECEIVED,
        OrderState.FULLY_MATCHED,
    ),
    OrderState.UNMATCHED: (
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMISSION_SENT,
        OrderState.ACK_RECEIVED,
        OrderState.UNMATCHED,
    ),
    OrderState.CANCEL_PENDING: (
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMISSION_SENT,
        OrderState.ACK_RECEIVED,
        OrderState.CANCEL_PENDING,
    ),
    OrderState.CANCELLED: (
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMISSION_SENT,
        OrderState.ACK_RECEIVED,
        OrderState.CANCEL_PENDING,
        OrderState.CANCELLED,
    ),
    OrderState.CANCEL_FAILED: (
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMISSION_SENT,
        OrderState.ACK_RECEIVED,
        OrderState.CANCEL_PENDING,
        OrderState.CANCEL_FAILED,
    ),
    OrderState.UNKNOWN: (
        OrderState.SUBMISSION_PENDING,
        OrderState.UNKNOWN,
    ),
    OrderState.RECONCILIATION_REQUIRED: (
        OrderState.SUBMISSION_PENDING,
        OrderState.UNKNOWN,
        OrderState.RECONCILIATION_REQUIRED,
    ),
    OrderState.SETTLED: (
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMISSION_SENT,
        OrderState.ACK_RECEIVED,
        OrderState.FULLY_MATCHED,
        OrderState.SETTLED,
    ),
    OrderState.VOID: (
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMISSION_SENT,
        OrderState.ACK_RECEIVED,
        OrderState.FULLY_MATCHED,
        OrderState.VOID,
    ),
}


class R10IntegratedRecoveryTests(unittest.TestCase):
    def test_process_death_inside_append_transaction_preserves_valid_head(self):
        with scratch_directory() as root:
            path = root / "crash.jsonl"
            log = AppendOnlyJsonl(path)
            log.append({"record_type": "before-crash"})

            context = multiprocessing.get_context("spawn")
            process = context.Process(
                target=_crash_inside_append_transaction,
                args=(str(path),),
            )
            process.start()
            process.join(30)
            self.assertEqual(process.exitcode, 91)
            self.assertEqual(log.verify(), 1)

            log.append({"record_type": "after-crash"})
            self.assertEqual(log.verify(), 2)
            self.assertEqual(
                [row["record_type"] for row in log.records()],
                ["before-crash", "after-crash"],
            )

    def test_every_order_state_has_an_explicit_restart_disposition(self):
        ambiguous = {
            OrderState.SUBMISSION_PENDING,
            OrderState.SUBMISSION_SENT,
            OrderState.UNKNOWN,
            OrderState.RECONCILIATION_REQUIRED,
        }
        with scratch_directory() as root:
            for index, target in enumerate(OrderState):
                with self.subTest(state=target.value):
                    case = root / f"order-{index:02d}"
                    fixture = build_execution(case)
                    adapter = fixture["adapter"]
                    adapter.create_intent(fixture["intent"])

                    if target == OrderState.REJECTED:
                        adapter.transition(
                            "key-a",
                            target,
                            occurred_at="2026-01-01T00:13:00Z",
                        )
                    elif target != OrderState.ORDER_INTENT_CREATED:
                        adapter.bind_risk(
                            "key-a",
                            bound_at="2026-01-01T00:13:00Z",
                        )
                        for offset, state in enumerate(ORDER_PATHS[target], start=14):
                            adapter.transition(
                                "key-a",
                                state,
                                occurred_at=f"2026-01-01T00:{offset:02d}:00Z",
                            )

                    restarted = restart_adapter(case, restart_risk(case))
                    expected = (
                        OrderState.RECONCILIATION_REQUIRED
                        if target in ambiguous
                        else target
                    )
                    self.assertEqual(restarted.get("key-a").state, expected)

    def test_every_risk_exposure_state_replays_open_or_terminal_exactly(self):
        open_states = {
            ExposureState.MATCHED,
            ExposureState.PARTIALLY_MATCHED,
            ExposureState.UNMATCHED,
            ExposureState.PENDING,
            ExposureState.UNKNOWN,
        }
        with scratch_directory() as root:
            for index, state in enumerate(ExposureState, start=2):
                with self.subTest(state=state.value):
                    case = root / f"risk-{index:02d}"
                    fixture = build_risk(case / "risk")
                    exposure = Exposure(
                        exposure_id=f"external-{state.value}",
                        candidate_decision_hash=digest(str(index)),
                        liability="1",
                        state=state,
                    )
                    fixture["engine"].record_exposure(
                        exposure,
                        recorded_at="2026-01-01T00:05:00Z",
                    )

                    restarted = restart_risk(case)
                    replayed = {
                        item.exposure_id: item
                        for item in restarted._exposures(
                            restarted.audit_log.log.records()
                        )
                    }
                    self.assertEqual(replayed[exposure.exposure_id], exposure)
                    reserved_ids = {
                        item.exposure_id for item in restarted.reserved_exposures()
                    }
                    self.assertEqual(
                        exposure.exposure_id in reserved_ids,
                        state in open_states,
                    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
