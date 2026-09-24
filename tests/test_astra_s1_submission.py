"""Astra A1: paper submission must own immediate recertification."""

from __future__ import annotations

import unittest
import multiprocessing
import os
from threading import Event, Thread
from pathlib import Path

from genesis.execution import (
    CriticalEvidenceRefresh,
    ExecutionMarketSnapshot,
    OrderState,
)
from genesis.registry import RegistryConflict, StrategyLifecycle
from genesis.risk import SafetyState
from genesis.risk import ExposureState

from ._support import scratch_directory
from .test_remediation_r6_execution import (
    build_execution,
    restart_adapter,
    restart_risk,
)


READY = "2026-01-01T00:14:00Z"
CHANGED = "2026-01-01T00:15:00Z"
ACTION = "2026-01-01T00:16:00Z"


def bound_case(root):
    case = build_execution(root)
    case["adapter"].create_intent(case["intent"])
    case["adapter"].bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
    return case


def invalidate(case, cause: str) -> str:
    if cause == "kill":
        safety = case["risk_fixture"]["safety"]
        safety.append(
            SafetyState.create(
                kill_switch_active=True,
                recorded_at=CHANGED,
                reason="Astra S1 kill",
                parent_state_id=safety.current().state_id,
            )
        )
    elif cause in {"refresh_invalid", "refresh_material"}:
        case["refreshes"].append(
            CriticalEvidenceRefresh(
                case["intent"].candidate_decision_hash,
                CHANGED,
                cause != "refresh_invalid",
                cause == "refresh_material",
            )
        )
    elif cause == "strategy_withdrawn":
        case["risk_fixture"]["strategies"].transition(
            "strategy", "v1", StrategyLifecycle.RETIRED, occurred_at=CHANGED,
        )
    elif cause in {"market_closed", "price_changed", "liquidity_low"}:
        case["markets"].append(
            ExecutionMarketSnapshot.create(
                candidate_decision_hash=case["intent"].candidate_decision_hash,
                observed_at=CHANGED,
                market_open=cause != "market_closed",
                executable_odds="1.90" if cause == "price_changed" else "2.00",
                available_liquidity="0" if cause == "liquidity_low" else "100",
            )
        )
    elif cause == "expiry":
        return "2026-01-01T01:00:00Z"
    else:
        raise AssertionError(cause)
    return ACTION


def _crash_while_fenced(root_text: str) -> None:
    root = Path(root_text)
    adapter = restart_adapter(root, restart_risk(root))

    def exit_during_fenced_recertification(_record, *, at, **_bound_heads):
        del at
        os._exit(91)

    adapter._recertify_record = exit_during_fenced_recertification
    adapter.transition("key-a", OrderState.SUBMISSION_PENDING, occurred_at=ACTION)
    os._exit(0)


class AstraSubmissionGateTests(unittest.TestCase):
    def test_each_failed_owner_check_blocks_pending_and_sent(self):
        causes = (
            "kill", "expiry", "refresh_invalid", "refresh_material",
            "strategy_withdrawn", "market_closed", "price_changed",
            "liquidity_low",
        )
        with scratch_directory() as root:
            for phase in (OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT):
                for cause in causes:
                    with self.subTest(phase=phase.value, cause=cause):
                        case = bound_case(root / f"{phase.value}-{cause}")
                        adapter = case["adapter"]
                        if phase == OrderState.SUBMISSION_SENT:
                            adapter.transition(
                                "key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY
                            )
                        self.assertTrue(adapter.recertify("key-a", at=READY).passed)
                        at = invalidate(case, cause)
                        self.assertFalse(adapter.recertify("key-a", at=at).passed)
                        before = len(adapter._audit.records())
                        with self.assertRaises(RegistryConflict):
                            adapter.transition("key-a", phase, occurred_at=at)
                        self.assertEqual(len(adapter._audit.records()), before)

    def test_unchanged_authorities_allow_one_paper_submission(self):
        with scratch_directory() as root:
            case = bound_case(root)
            adapter = case["adapter"]
            self.assertEqual(
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY
                ).state,
                OrderState.SUBMISSION_PENDING,
            )
            self.assertEqual(
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_SENT, occurred_at=ACTION
                ).state,
                OrderState.SUBMISSION_SENT,
            )
            with self.assertRaises(Exception):
                adapter.transition("key-a", OrderState.SUBMISSION_SENT, occurred_at=ACTION)
            self.assertEqual(
                sum(
                    row.get("to_state") == OrderState.SUBMISSION_SENT.value
                    for row in adapter._audit.records()
                ),
                1,
            )

    def test_stale_success_and_between_phase_kill_do_not_certify_send(self):
        with scratch_directory() as root:
            case = bound_case(root)
            adapter = case["adapter"]
            self.assertTrue(adapter.recertify("key-a", at=READY).passed)
            adapter.transition("key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY)
            at = invalidate(case, "kill")
            before = len(adapter._audit.records())
            with self.assertRaises(RegistryConflict):
                adapter.transition("key-a", OrderState.SUBMISSION_SENT, occurred_at=at)
            self.assertEqual(len(adapter._audit.records()), before)

    def test_change_at_transaction_entry_is_observed_not_reused(self):
        with scratch_directory() as root:
            for phase in (OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT):
                with self.subTest(phase=phase.value):
                    case = bound_case(root / phase.value)
                    adapter = case["adapter"]
                    if phase == OrderState.SUBMISSION_SENT:
                        adapter.transition(
                            "key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY
                        )
                    self.assertTrue(adapter.recertify("key-a", at=READY).passed)
                    original = adapter._audit.transaction
                    changed = False

                    def change_before_builder(builder, **kwargs):
                        nonlocal changed
                        if not changed:
                            changed = True
                            invalidate(case, "kill")
                        return original(builder, **kwargs)

                    adapter._audit.transaction = change_before_builder
                    before = len(adapter._audit.records())
                    with self.assertRaises(RegistryConflict):
                        adapter.transition("key-a", phase, occurred_at=ACTION)
                    self.assertTrue(changed)
                    self.assertEqual(len(adapter._audit.records()), before)

    def test_restart_preserves_pre_submission_gate_and_pending_ambiguity(self):
        with scratch_directory() as root:
            pre = bound_case(root / "pre")
            invalidate(pre, "market_closed")
            replayed = restart_adapter(root / "pre", restart_risk(root / "pre"))
            before = len(replayed._audit.records())
            with self.assertRaises(RegistryConflict):
                replayed.transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at=ACTION
                )
            self.assertEqual(len(replayed._audit.records()), before)

            pending = bound_case(root / "pending")
            pending["adapter"].transition(
                "key-a", OrderState.SUBMISSION_PENDING, occurred_at=READY
            )
            replayed = restart_adapter(root / "pending", restart_risk(root / "pending"))
            self.assertEqual(replayed.get("key-a").state, OrderState.RECONCILIATION_REQUIRED)
            with self.assertRaises(RegistryConflict):
                replayed.transition("key-a", OrderState.SUBMISSION_SENT, occurred_at=ACTION)

    def test_cross_thread_authority_writer_waits_until_submission_is_durable(self):
        with scratch_directory() as root:
            for authority in ("safety", "reservation"):
                with self.subTest(authority=authority):
                    case = bound_case(root / authority)
                    adapter = case["adapter"]
                    attempted = Event()
                    completed = Event()
                    errors = []
                    if authority == "safety":
                        store = case["risk_fixture"]["safety"]
                        original_transaction = store.log.transaction

                        def write():
                            state = store.current()
                            store.append(SafetyState.create(
                                kill_switch_active=True,
                                recorded_at=CHANGED,
                                reason="concurrent stop",
                                parent_state_id=state.state_id,
                            ))
                    else:
                        store = case["risk_fixture"]["engine"]
                        original_transaction = store.audit_log.log.transaction

                        def write():
                            store.transition_reservation(
                                case["risk_decision"].approval_id,
                                ExposureState.UNKNOWN,
                                occurred_at=CHANGED,
                            )

                    def mark_attempt(builder, **kwargs):
                        attempted.set()
                        return original_transaction(builder, **kwargs)

                    if authority == "safety":
                        store.log.transaction = mark_attempt
                    else:
                        store.audit_log.log.transaction = mark_attempt

                    def worker():
                        try:
                            write()
                        except Exception as exc:
                            errors.append(exc)
                        finally:
                            completed.set()

                    original_recertify = getattr(adapter, "_recertify_record", None)
                    original_public_recertify = adapter.recertify
                    workers = []
                    completed_inside_check = []

                    def race_after_check(result):
                        thread = Thread(target=worker, daemon=True)
                        workers.append(thread)
                        thread.start()
                        self.assertTrue(attempted.wait(5), "writer never reached its transaction")
                        completed_inside_check.append(completed.wait(0.25))
                        return result

                    if original_recertify is None:
                        # R10 has only a separately callable public check. The
                        # transition's failure to invoke it is an assertion
                        # failure, not a missing-method/setup error.
                        def check_public(key, *, at):
                            return race_after_check(original_public_recertify(key, at=at))

                        adapter.recertify = check_public
                    else:
                        def check_record(record, *, at, **bound_heads):
                            return race_after_check(
                                original_recertify(record, at=at, **bound_heads)
                            )

                        adapter._recertify_record = check_record
                    adapter.transition(
                        "key-a", OrderState.SUBMISSION_PENDING, occurred_at=ACTION
                    )
                    if original_recertify is None:
                        adapter.recertify = original_public_recertify
                    else:
                        adapter._recertify_record = original_recertify
                    self.assertEqual(len(workers), 1, "submission bypassed recertification")
                    for thread in workers:
                        thread.join(5)
                        self.assertFalse(thread.is_alive(), "authority writer did not finish")
                    self.assertEqual(errors, [])
                    self.assertEqual(completed_inside_check, [False])
                    self.assertFalse(adapter.recertify("key-a", at=ACTION).passed)

    def test_process_death_inside_fenced_check_leaves_no_pending_event_or_lock(self):
        with scratch_directory() as root:
            case = bound_case(root)
            before = len(case["adapter"]._audit.records())
            process = multiprocessing.get_context("spawn").Process(
                target=_crash_while_fenced, args=(str(root),)
            )
            process.start()
            process.join(20)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 91)
            self.assertEqual(len(case["adapter"]._audit.records()), before)
            self.assertFalse(any(
                row.get("to_state") == OrderState.SUBMISSION_SENT.value
                for row in case["adapter"]._audit.records()
            ))
            safety = case["risk_fixture"]["safety"]
            safety.append(SafetyState.create(
                kill_switch_active=True,
                recorded_at=CHANGED,
                reason="post-crash stop",
                parent_state_id=safety.current().state_id,
            ))
            replayed = restart_adapter(root, restart_risk(root))
            self.assertEqual(replayed.get("key-a").state, OrderState.RISK_APPROVED)
            with self.assertRaises(RegistryConflict):
                replayed.transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at=ACTION
                )


if __name__ == "__main__":
    unittest.main()
