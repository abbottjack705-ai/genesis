from __future__ import annotations

import multiprocessing
import os
import unittest
from pathlib import Path

from genesis.accounting import BetSide
from genesis.config import OperationalMode
from genesis.execution import (
    AuthorizationArtifact,
    CriticalEvidenceRefresh,
    CriticalEvidenceRefreshStore,
    ExecutionMarketSnapshot,
    ExecutionMarketStateStore,
    ModeController,
    ModeState,
    ModeStateStore,
    OrderIntent,
    OrderState,
    PaperExecutionAdapter,
    RegistryStrategyExecutionView,
)
from genesis.policy import PolicySet
from genesis.ledger import SettlementLedger
from genesis.release_proof import OfflinePaperReleaseProofStore
from genesis.registry import AppendOnlyJsonl, RegistryConflict, StrategyRegistry
from genesis.risk import (
    BankrollSnapshotStore,
    ExposureState,
    RiskAuditLog,
    RiskEngine,
    SafetyState,
    SafetyStateStore,
)
from genesis.selection import QualificationRecordStore
from ._support import SyntheticQualificationRecordStore as QualificationRecordStore, scratch_directory
from .test_remediation_r5_risk import build_risk, request as risk_request


def digest(character: str) -> str:
    return character * 64


class ActiveStrategyView:
    def is_active(self, candidate_decision_hash: str, at: str) -> bool:
        return True


class InactiveStrategyView:
    def is_active(self, candidate_decision_hash: str, at: str) -> bool:
        return False


def restart_risk(root: Path) -> RiskEngine:
    return RiskEngine(
        policy=PolicySet(),
        bankrolls=BankrollSnapshotStore(root / "risk" / "bankroll.jsonl"),
        qualifications=QualificationRecordStore(root / "risk" / "qualifications.jsonl"),
        safety=SafetyStateStore(root / "risk" / "safety.jsonl"),
        audit_log=RiskAuditLog(root / "risk" / "risk.jsonl"),
        strategies=StrategyRegistry(root / "risk" / "strategies.jsonl"),
        modes=ModeStateStore(root / "risk" / "mode.jsonl"),
        action_clock=lambda requested_at: requested_at,  # synthetic offline time
    )


def restart_adapter(root: Path, risk: RiskEngine, strategy_view=None) -> PaperExecutionAdapter:
    return PaperExecutionAdapter(
        root / "orders.jsonl",
        risk=risk,
        markets=ExecutionMarketStateStore(root / "markets.jsonl"),
        refreshes=CriticalEvidenceRefreshStore(root / "refreshes.jsonl"),
        strategy_view=strategy_view or RegistryStrategyExecutionView(
            StrategyRegistry(root / "risk" / "strategies.jsonl")
        ),
        modes=ModeStateStore(root / "risk" / "mode.jsonl"),
        action_clock=lambda requested_at: requested_at,  # synthetic offline test time
    )


def build_execution(
    root: Path,
    *,
    side: BetSide = BetSide.BACK,
    odds: str = "2.00",
    expires_at: str = "2026-01-01T01:00:00Z",
):
    risk_fixture = build_risk(
        root / "risk", expires_at=expires_at, side=side, odds=odds,
    )
    risk_decision = risk_fixture["engine"].approve(
        risk_request(risk_fixture, side=side, odds=odds)
    )
    if not risk_decision.passed:
        raise AssertionError(risk_decision.reason)
    markets = ExecutionMarketStateStore(root / "markets.jsonl")
    markets.append(
        ExecutionMarketSnapshot.create(
            candidate_decision_hash=risk_fixture["candidate_hash"],
            observed_at="2026-01-01T00:11:00Z",
            market_open=True,
            executable_odds=odds,
            available_liquidity="100",
        )
    )
    refreshes = CriticalEvidenceRefreshStore(root / "refreshes.jsonl")
    refreshes.append(
        CriticalEvidenceRefresh(
            risk_fixture["candidate_hash"],
            "2026-01-01T00:11:00Z",
            True,
            False,
        )
    )
    modes = risk_fixture["modes"]
    adapter = PaperExecutionAdapter(
        root / "orders.jsonl",
        risk=risk_fixture["engine"],
        markets=markets,
        refreshes=refreshes,
        strategy_view=RegistryStrategyExecutionView(risk_fixture["strategies"]),
        modes=modes,
        action_clock=lambda requested_at: requested_at,  # synthetic offline test time
    )
    intent = OrderIntent(
        risk_fixture["candidate_hash"],
        "key-a",
        side,
        risk_decision.approved_stake,
        odds,
        risk_decision.approval_id,
        "2026-01-01T00:12:00Z",
    )
    return {
        "risk_fixture": risk_fixture,
        "risk_decision": risk_decision,
        "markets": markets,
        "refreshes": refreshes,
        "modes": modes,
        "adapter": adapter,
        "intent": intent,
        "root": root,
    }


def _concurrent_intent_worker(root_text: str, key: str) -> None:
    root = Path(root_text)
    risk = restart_risk(root)
    approval_rows = [
        row
        for row in risk.audit_log.log.records()
        if row.get("record_type") == "risk_approval_created"
    ]
    row = approval_rows[0]
    adapter = restart_adapter(root, risk)
    intent = OrderIntent(
        row["candidate_decision_hash"],
        key,
        BetSide(row["side"]),
        row["approved_stake"],
        row["odds"],
        row["approval_id"],
        "2026-01-01T00:12:00Z",
    )
    try:
        adapter.create_intent(intent)
    except RegistryConflict:
        os._exit(2)
    os._exit(0)


class R6OrderUniquenessTests(unittest.TestCase):
    def test_one_candidate_has_one_lineage_across_replay_terminal_and_restart(self):
        with scratch_directory() as tmp:
            fixture = build_execution(tmp)
            adapter = fixture["adapter"]
            intent = fixture["intent"]
            created = adapter.create_intent(intent)
            self.assertEqual(adapter.create_intent(intent).order_id, created.order_id)
            with self.assertRaises(RegistryConflict):
                adapter.create_intent(
                    OrderIntent(
                        intent.candidate_decision_hash,
                        intent.idempotency_key,
                        intent.side,
                        intent.stake,
                        "2.10",
                        intent.risk_approval_id,
                        intent.created_at,
                    )
                )
            with self.assertRaises(RegistryConflict):
                adapter.create_intent(
                    OrderIntent(
                        intent.candidate_decision_hash,
                        "key-b",
                        intent.side,
                        intent.stake,
                        intent.odds,
                        intent.risk_approval_id,
                        intent.created_at,
                    )
                )
            adapter.transition(
                "key-a", OrderState.REJECTED, occurred_at="2026-01-01T00:13:00Z"
            )
            restarted = restart_adapter(tmp, restart_risk(tmp))
            self.assertEqual(restarted.get("key-a").state, OrderState.REJECTED)
            with self.assertRaises(RegistryConflict):
                restarted.create_intent(
                    OrderIntent(
                        intent.candidate_decision_hash,
                        "key-b",
                        intent.side,
                        intent.stake,
                        intent.odds,
                        intent.risk_approval_id,
                        intent.created_at,
                    )
                )

    def test_cross_process_candidate_creation_is_atomic(self):
        with scratch_directory() as tmp:
            build_execution(tmp)
            context = multiprocessing.get_context("spawn")
            processes = [
                context.Process(
                    target=_concurrent_intent_worker, args=(str(tmp), key)
                )
                for key in ("key-a", "key-b")
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(20)
            self.assertEqual(sorted(process.exitcode for process in processes), [0, 2])
            adapter = restart_adapter(tmp, restart_risk(tmp))
            records = adapter._current_records()
            self.assertEqual(len(records), 1)


class R6RiskBindingTests(unittest.TestCase):
    def test_direct_transition_fake_approval_and_submission_without_binding_fail(self):
        with scratch_directory() as tmp:
            fixture = build_execution(tmp)
            adapter = fixture["adapter"]
            intent = fixture["intent"]
            adapter.create_intent(intent)
            with self.assertRaises(RegistryConflict):
                adapter.transition(
                    "key-a",
                    OrderState.RISK_APPROVED,
                    occurred_at="2026-01-01T00:13:00Z",
                )
            with self.assertRaises(Exception):
                adapter.transition(
                    "key-a",
                    OrderState.SUBMISSION_PENDING,
                    occurred_at="2026-01-01T00:13:00Z",
                )

            fake = build_execution(tmp / "fake")
            fake_intent = replace_intent(
                fake["intent"], risk_approval_id=digest("9")
            )
            with self.assertRaises(RegistryConflict):
                fake["adapter"].create_intent(fake_intent)

    def test_candidate_stake_and_lay_liability_mismatches_fail(self):
        with scratch_directory() as tmp:
            candidate = build_execution(tmp / "candidate")
            with self.assertRaises(RegistryConflict):
                candidate["adapter"].create_intent(
                    replace_intent(
                        candidate["intent"], candidate_decision_hash=digest("8")
                    )
                )

            stake = build_execution(tmp / "stake")
            stake["adapter"].create_intent(
                replace_intent(stake["intent"], stake="7.49")
            )
            with self.assertRaises(RegistryConflict):
                stake["adapter"].bind_risk(
                    "key-a", bound_at="2026-01-01T00:13:00Z"
                )

            lay = build_execution(tmp / "lay", side=BetSide.LAY, odds="2.00")
            lay["adapter"].create_intent(replace_intent(lay["intent"], odds="3.00"))
            with self.assertRaises(RegistryConflict):
                lay["adapter"].bind_risk(
                    "key-a", bound_at="2026-01-01T00:13:00Z"
                )

    def test_exact_binding_consumes_once_and_expiry_boundary_is_strict(self):
        with scratch_directory() as tmp:
            fixture = build_execution(tmp / "success")
            fixture["adapter"].create_intent(fixture["intent"])
            bound = fixture["adapter"].bind_risk(
                "key-a", bound_at="2026-01-01T00:59:59Z"
            )
            self.assertEqual(bound.state, OrderState.RISK_APPROVED)
            approval = fixture["risk_fixture"]["engine"].get_approval(
                fixture["risk_decision"].approval_id
            )
            self.assertEqual(approval.status, "CONSUMED")
            self.assertEqual(approval.consumed_by_order_id, bound.order_id)
            with self.assertRaises(RegistryConflict):
                fixture["risk_fixture"]["engine"].consume_for_order(
                    approval.approval_id,
                    order_id="different-order",
                    consumed_at="2026-01-01T00:59:59Z",
                )

            expired = build_execution(tmp / "expired")
            expired["adapter"].create_intent(expired["intent"])
            with self.assertRaises(RegistryConflict):
                expired["adapter"].bind_risk(
                    "key-a", bound_at="2026-01-01T01:00:00Z"
                )

    def test_crash_between_consume_and_binding_is_reconciliation_blocking(self):
        with scratch_directory() as tmp:
            fixture = build_execution(tmp)
            fixture["adapter"].create_intent(fixture["intent"])
            with self.assertRaises(RuntimeError):
                fixture["adapter"].bind_risk(
                    "key-a",
                    bound_at="2026-01-01T00:13:00Z",
                    fault_after_consume=True,
                )
            restarted = restart_adapter(tmp, restart_risk(tmp))
            self.assertEqual(
                restarted.get("key-a").state, OrderState.RECONCILIATION_REQUIRED
            )
            with self.assertRaises(RegistryConflict):
                restarted.bind_risk("key-a", bound_at="2026-01-01T00:14:00Z")
            with self.assertRaises(RegistryConflict):
                restarted.transition(
                    "key-a",
                    OrderState.SUBMISSION_PENDING,
                    occurred_at="2026-01-01T00:14:00Z",
                )


class R6RestartAndRecertificationTests(unittest.TestCase):
    def test_submission_pending_restart_never_blindly_resends(self):
        with scratch_directory() as tmp:
            fixture = build_execution(tmp)
            adapter = fixture["adapter"]
            adapter.create_intent(fixture["intent"])
            adapter.bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
            adapter.transition(
                "key-a",
                OrderState.SUBMISSION_PENDING,
                occurred_at="2026-01-01T00:14:00Z",
            )
            restarted = restart_adapter(tmp, restart_risk(tmp))
            self.assertEqual(
                restarted.get("key-a").state, OrderState.RECONCILIATION_REQUIRED
            )
            with self.assertRaises(RegistryConflict):
                restarted.transition(
                    "key-a",
                    OrderState.SUBMISSION_SENT,
                    occurred_at="2026-01-01T00:15:00Z",
                )

    def test_recertification_uses_market_refresh_strategy_and_safety_owners(self):
        with scratch_directory() as tmp:
            ready = build_execution(tmp / "ready")
            ready["adapter"].create_intent(ready["intent"])
            ready["adapter"].bind_risk(
                "key-a", bound_at="2026-01-01T00:13:00Z"
            )
            self.assertTrue(
                ready["adapter"].recertify(
                    "key-a", at="2026-01-01T00:14:00Z"
                ).passed
            )
            with self.assertRaises(TypeError):
                ready["adapter"].recertify(  # type: ignore[call-arg]
                    "key-a", at="2026-01-01T00:14:00Z", executable_price_ok=True
                )

            ready["markets"].append(
                ExecutionMarketSnapshot.create(
                    candidate_decision_hash=ready["risk_fixture"]["candidate_hash"],
                    observed_at="2026-01-01T00:15:00Z",
                    market_open=True,
                    executable_odds="1.90",
                    available_liquidity="100",
                )
            )
            self.assertEqual(
                ready["adapter"].recertify(
                    "key-a", at="2026-01-01T00:16:00Z"
                ).reason,
                "executable_price_changed",
            )

            changed = build_execution(tmp / "changed")
            changed["adapter"].create_intent(changed["intent"])
            changed["adapter"].bind_risk(
                "key-a", bound_at="2026-01-01T00:13:00Z"
            )
            changed["refreshes"].append(
                CriticalEvidenceRefresh(
                    changed["risk_fixture"]["candidate_hash"],
                    "2026-01-01T00:15:00Z",
                    True,
                    True,
                )
            )
            result = changed["adapter"].recertify(
                "key-a", at="2026-01-01T00:16:00Z"
            )
            self.assertEqual(result.reason, "critical_evidence_changed")
            self.assertTrue(result.requires_new_candidate)

            killed = build_execution(tmp / "killed")
            killed["adapter"].create_intent(killed["intent"])
            killed["adapter"].bind_risk(
                "key-a", bound_at="2026-01-01T00:13:00Z"
            )
            current = killed["risk_fixture"]["safety"].current()
            killed["risk_fixture"]["safety"].append(
                SafetyState.create(
                    kill_switch_active=True,
                    recorded_at="2026-01-01T00:15:00Z",
                    reason="stop",
                    parent_state_id=current.state_id,
                )
            )
            self.assertEqual(
                killed["adapter"].recertify(
                    "key-a", at="2026-01-01T00:16:00Z"
                ).reason,
                "risk_or_safety_state_blocked",
            )

    def test_terminal_reservation_mode_and_corrupt_state_replay_fail_safe(self):
        with scratch_directory() as tmp:
            fixture = build_execution(tmp / "terminal")
            adapter = fixture["adapter"]
            adapter.create_intent(fixture["intent"])
            adapter.bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
            adapter.transition(
                "key-a", OrderState.REJECTED, occurred_at="2026-01-01T00:14:00Z"
            )
            ledger = SettlementLedger(tmp / "terminal" / "ledger.jsonl")
            proof_owner = OfflinePaperReleaseProofStore(
                tmp / "terminal" / "release-proofs.jsonl",
                risk=fixture["risk_fixture"]["engine"],
                execution=adapter,
                ledger=ledger,
            )
            proof_hash = proof_owner.issue_unsent_rejection(
                fixture["intent"].order_id,
                occurred_at="2026-01-01T00:14:30Z",
            )
            fixture["risk_fixture"]["engine"].attach_release_proofs(proof_owner)
            fixture["risk_fixture"]["engine"].release_with_proof(
                proof_hash, occurred_at="2026-01-01T00:15:00Z",
            )
            restarted_risk = restart_risk(tmp / "terminal")
            restarted = restart_adapter(tmp / "terminal", restarted_risk)
            restarted_risk.attach_release_proofs(OfflinePaperReleaseProofStore(
                tmp / "terminal" / "release-proofs.jsonl",
                risk=restarted_risk,
                execution=restarted,
                ledger=SettlementLedger(tmp / "terminal" / "ledger.jsonl"),
            ))
            self.assertEqual(restarted.get("key-a").state, OrderState.REJECTED)
            self.assertEqual(restarted_risk.reserved_exposures(), ())

            mode_root = tmp / "mode"
            modes = ModeStateStore(mode_root / "mode.jsonl")
            modes.append(
                ModeState.create(
                    mode=OperationalMode.OFFLINE_RESEARCH,
                    occurred_at="2026-01-01T00:00:00Z",
                    authorization_id=None,
                    parent_state_id=None,
                )
            )
            safety = SafetyStateStore(mode_root / "safety.jsonl")
            safety.append(
                SafetyState.create(
                    kill_switch_active=False,
                    recorded_at="2026-01-01T00:00:00Z",
                    reason="initial",
                )
            )
            controller = ModeController(modes, safety)
            controller.activate_kill_switch(occurred_at="2026-01-01T00:01:00Z")
            replayed = ModeController(
                ModeStateStore(mode_root / "mode.jsonl"),
                SafetyStateStore(mode_root / "safety.jsonl"),
            )
            self.assertEqual(replayed.mode, OperationalMode.KILL_SWITCH_ACTIVE)
            self.assertTrue(replayed.kill_switch_active)

            corrupt = build_execution(tmp / "corrupt")
            corrupt["adapter"].create_intent(corrupt["intent"])
            AppendOnlyJsonl(tmp / "corrupt" / "orders.jsonl").append(
                {
                    "record_type": "order_state_transition",
                    "schema_version": "unsupported",
                    "order_id": corrupt["intent"].order_id,
                }
            )
            with self.assertRaises(RegistryConflict):
                restart_adapter(tmp / "corrupt", restart_risk(tmp / "corrupt"))


def replace_intent(intent: OrderIntent, **changes) -> OrderIntent:
    values = intent.to_dict()
    values.update(changes)
    values["side"] = BetSide(values["side"])
    values["mode"] = OperationalMode(values["mode"])
    return OrderIntent(**values)


if __name__ == "__main__":
    unittest.main()
