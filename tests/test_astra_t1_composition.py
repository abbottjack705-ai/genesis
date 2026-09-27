"""Cross-finding B1/B2/B3/B7 adversarial PAPER-only compositions.

The fixtures are synthetic and nonoperational.  They approve no model, tier
rule, expiry rule, adapter, campaign, shadow research or live-money path.
"""

from __future__ import annotations

import inspect
import unittest
from dataclasses import asdict
from decimal import Decimal

from genesis.accounting import BetSide, SettlementKind
from genesis.config import OperationalMode
from genesis.decision import candidate_v3_decision_hash
from genesis.execution import (
    CriticalEvidenceRefresh,
    CriticalEvidenceRefreshStore,
    ExecutionMarketSnapshot,
    ExecutionMarketStateStore,
    ModeState,
    ModeStateStore,
    OrderIntent,
    OrderState,
    PaperExecutionAdapter,
)
from genesis.ledger import FillRecord, SettlementLedger
from genesis.registry import AppendOnlyJsonl, RegistryConflict, StrategyLifecycle
from genesis.risk import Exposure, ExposureState, SafetyState
from genesis.selection import QualificationRecord

from ._support import scratch_directory
from .test_remediation_r5_risk import build_risk, request as risk_request
from .test_remediation_r6_execution import (
    ActiveStrategyView, build_execution, restart_adapter, restart_risk,
)


def _trusted_clusters(fixture: dict, clusters: tuple[str, ...]) -> QualificationRecord:
    """Publish a distinct, correctly hashed synthetic output/qualification."""

    old = fixture["qualification"]
    body = fixture["qualifications"].outputs.get(old.decision_output_hash)
    body["correlation_cluster_ids"] = sorted(set(clusters))
    output_hash = fixture["qualifications"].outputs.publish(body)
    fields = asdict(old)
    fields.pop("qualification_record_id")
    fields["decision_output_hash"] = output_hash
    fields["candidate_decision_hash"] = candidate_v3_decision_hash(
        strategy_decision_contract_hash=old.strategy_decision_contract_hash,
        feature_manifest_hash=old.feature_manifest_hash,
        evidence_pack_hash=body["evidence_pack_hash"],
        decision_output_hash=output_hash,
    )
    record = fixture["qualifications"].record_fixture_qualification(
        QualificationRecord.create(**fields)
    )
    fixture["qualification"] = record
    fixture["candidate_hash"] = record.candidate_decision_hash
    return record


def _second_qualification(fixture: dict, label: str = "second") -> QualificationRecord:
    """A second independent candidate under the same synthetic rule binding."""

    old = fixture["qualification"]
    body = fixture["qualifications"].outputs.get(old.decision_output_hash)
    body["event_id"] = f"event-{label}"
    body["selection_id"] = f"selection-{label}"
    output_hash = fixture["qualifications"].outputs.publish(body)
    fields = asdict(old)
    fields.pop("qualification_record_id")
    fields["candidate_id"] = label
    fields["decision_output_hash"] = output_hash
    fields["candidate_decision_hash"] = candidate_v3_decision_hash(
        strategy_decision_contract_hash=old.strategy_decision_contract_hash,
        feature_manifest_hash=old.feature_manifest_hash,
        evidence_pack_hash=body["evidence_pack_hash"],
        decision_output_hash=output_hash,
    )
    return fixture["qualifications"].record_fixture_qualification(
        QualificationRecord.create(**fields)
    )


def _bound_clustered_order(root, clusters=("shared",)):
    """Build one valid PAPER order whose pre-approval output has dependence."""

    risk_fixture = build_risk(root / "risk")
    _trusted_clusters(risk_fixture, clusters)
    risk_decision = risk_fixture["engine"].approve(risk_request(risk_fixture))
    if not risk_decision.passed:
        raise AssertionError(f"synthetic clustered approval setup: {risk_decision.reason}")
    markets = ExecutionMarketStateStore(root / "markets.jsonl")
    markets.append(ExecutionMarketSnapshot.create(
        candidate_decision_hash=risk_fixture["candidate_hash"],
        observed_at="2026-01-01T00:11:00Z", market_open=True,
        executable_odds="2", available_liquidity="100",
    ))
    refreshes = CriticalEvidenceRefreshStore(root / "refreshes.jsonl")
    refreshes.append(CriticalEvidenceRefresh(
        risk_fixture["candidate_hash"], "2026-01-01T00:11:00Z", True, False,
    ))
    # The sealed checkpoint used an unfenced boolean view.  The repair adds a
    # durable registry view and an injectable deterministic offline clock.
    import genesis.execution as execution_module

    registry_view = getattr(execution_module, "RegistryStrategyExecutionView", None)
    view = (
        registry_view(risk_fixture["strategies"])
        if registry_view is not None and "strategies" in risk_fixture
        else ActiveStrategyView()
    )
    options = {
        "risk": risk_fixture["engine"], "markets": markets,
        "refreshes": refreshes, "strategy_view": view,
    }
    if "action_clock" in inspect.signature(PaperExecutionAdapter).parameters:
        options["action_clock"] = lambda requested_at: requested_at
    adapter = PaperExecutionAdapter(root / "orders.jsonl", **options)
    intent = OrderIntent(
        risk_fixture["candidate_hash"], "key-a", BetSide.BACK,
        risk_decision.approved_stake, "2", risk_decision.approval_id,
        "2026-01-01T00:12:00Z",
    )
    case = {
        "risk_fixture": risk_fixture, "risk_decision": risk_decision,
        "markets": markets, "refreshes": refreshes,
        "adapter": adapter, "intent": intent, "root": root,
    }
    _paper_mode_adapter(case)
    case["adapter"].create_intent(intent)
    case["adapter"].bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
    return case


def _paper_mode_adapter(case):
    """Attach only a synthetic coherent PAPER/safety head when supported."""

    if "modes" not in inspect.signature(PaperExecutionAdapter).parameters:
        return case["adapter"]
    # Current T1 requires risk admission and execution to share the exact same
    # durable mode owner.  The fallback keeps this hostile test importable on
    # the sealed pre-B7 checkpoint, whose build_risk fixture had no mode owner.
    modes = case["risk_fixture"].get("modes")
    if modes is None:
        modes = ModeStateStore(case["root"] / "mode-admission.jsonl")
        modes.append(ModeState.create(
            mode=OperationalMode.PAPER,
            occurred_at="2026-01-01T00:01:00Z",
            authorization_id="synthetic-test-only-paper",
            parent_state_id=None,
        ))
        safety = case["risk_fixture"]["safety"]
        safety.append(SafetyState.create(
            kill_switch_active=False,
            recorded_at="2026-01-01T00:01:00Z",
            reason="mode:paper",
            parent_state_id=safety.current().state_id,
        ))
    case["adapter"] = PaperExecutionAdapter(
        case["root"] / "orders.jsonl",
        risk=case["risk_fixture"]["engine"],
        markets=case["markets"], refreshes=case["refreshes"],
        strategy_view=case["adapter"].strategy_view,
        action_clock=lambda requested_at: requested_at,
        modes=modes,
    )
    return case["adapter"]


def _sent(case):
    case["adapter"].transition(
        "key-a", OrderState.SUBMISSION_PENDING,
        occurred_at="2026-01-01T00:14:00Z",
    )
    case["adapter"].transition(
        "key-a", OrderState.SUBMISSION_SENT,
        occurred_at="2026-01-01T00:15:00Z",
    )


def _reserved(case):
    approval_id = case["risk_decision"].approval_id
    return [item for item in case["risk_fixture"]["engine"].reserved_exposures()
            if item.exposure_id == approval_id]


def _withdraw_strategy(case, at="2026-01-01T00:18:00Z"):
    registry = case["risk_fixture"].get("strategies")
    if registry is not None:
        registry.transition("strategy", "v1", StrategyLifecycle.RETIRED,
                            occurred_at=at)
    else:
        # Sealed R6 had no durable strategy owner.  A separate durable head
        # makes that historical omission visible without faking an approval.
        log = AppendOnlyJsonl(case["root"] / "withdrawal.jsonl")
        log.append({"strategy_id": "strategy", "active": False,
                    "occurred_at": at})


class AstraCrossFindingCompositionTests(unittest.TestCase):
    def test_c01_erased_caller_clusters_and_late_correlated_exposure_block_sent(self):
        with scratch_directory() as root:
            case = _bound_clustered_order(root)
            self.assertEqual(case["risk_fixture"]["qualifications"].outputs.get(
                case["risk_fixture"]["qualification"].decision_output_hash
            )["correlation_cluster_ids"], ["shared"])
            case["adapter"].transition(
                "key-a", OrderState.SUBMISSION_PENDING,
                occurred_at="2026-01-01T00:14:00Z",
            )
            # An independent, later fill joins the trusted cluster.  The
            # caller's omitted tuple at risk approval must not erase it.
            case["risk_fixture"]["engine"].record_exposure(
                Exposure("late-correlated", "f" * 64, "6", ExposureState.MATCHED,
                         ("shared",)), recorded_at="2026-01-01T00:15:30Z",
            )
            self.assertEqual(_reserved(case)[0].correlation_cluster_ids, ("shared",))
            self.assertFalse(case["adapter"].recertify(
                "key-a", at="2026-01-01T00:16:00Z",
            ).passed, "7.5 plus 6 breaches the 12.5 trusted cluster cap")
            before = len(case["adapter"]._audit.records())
            with self.assertRaises(RegistryConflict):
                case["adapter"].transition(
                    "key-a", OrderState.SUBMISSION_SENT,
                    occurred_at="2026-01-01T00:16:00Z",
                )
            self.assertEqual(len(case["adapter"]._audit.records()), before)
            self.assertEqual(case["adapter"].get("key-a").state,
                             OrderState.SUBMISSION_PENDING)

    def test_c02_bare_release_cannot_fabricate_capacity_for_second_approval(self):
        with scratch_directory() as root:
            case = build_execution(root)
            adapter = case["adapter"]
            adapter.create_intent(case["intent"])
            adapter.bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
            _paper_mode_adapter(case)
            adapter = case["adapter"]
            _sent(case)
            risk = case["risk_fixture"]["engine"]
            risk.record_exposure(
                Exposure("independent", "f" * 64, "52.5", ExposureState.MATCHED),
                recorded_at="2026-01-01T00:15:30Z",
            )
            self.assertEqual(sum((item.liability_amount for item in
                                  risk.reserved_exposures()), Decimal("0")),
                             Decimal("60"))
            second = _second_qualification(case["risk_fixture"])
            try:
                risk.transition_reservation(
                    case["risk_decision"].approval_id, ExposureState.SETTLED,
                    occurred_at="2026-01-01T00:16:00Z",
                )
            except (RegistryConflict, TypeError):
                pass  # Bare terminal text lacks a proof; it cannot release.
            before = len(case["risk_fixture"]["audit"].log.records())
            result = risk.approve(risk_request(
                case["risk_fixture"],
                candidate_hash=second.candidate_decision_hash,
                qualification_record_id=second.qualification_record_id,
                requested_at="2026-01-01T00:17:00Z",
            ))
            self.assertFalse(result.passed,
                             "unproved terminal text funded a second approval")
            self.assertEqual(len(case["risk_fixture"]["audit"].log.records()), before)
            self.assertEqual(len(_reserved(case)), 1)
            self.assertEqual(adapter.get("key-a").state, OrderState.SUBMISSION_SENT)

    def test_c03_partial_fill_correction_late_fill_restart_keeps_envelope(self):
        with scratch_directory() as root:
            case = build_execution(root)
            case["adapter"].create_intent(case["intent"])
            case["adapter"].bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
            _paper_mode_adapter(case)
            _sent(case)
            case["adapter"].transition("key-a", OrderState.ACK_RECEIVED,
                                       occurred_at="2026-01-01T00:15:10Z")
            case["adapter"].transition("key-a", OrderState.PARTIALLY_MATCHED,
                                       occurred_at="2026-01-01T00:15:20Z")
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(FillRecord(
                "partial-1", case["intent"].order_id,
                case["intent"].candidate_decision_hash,
                BetSide.BACK, "2", "2.50", "2026-01-01T00:15:30Z",
            ))
            ledger.settle(event_id="win-1", fill_id="partial-1",
                          kind=SettlementKind.WIN,
                          occurred_at="2026-01-01T00:16:00Z")
            correction = ledger.settle(
                event_id="loss-correction", fill_id="partial-1",
                kind=SettlementKind.LOSS,
                occurred_at="2026-01-01T00:17:00Z", correction_of="win-1",
            )
            self.assertEqual(ledger.head("partial-1"), correction)
            self.assertEqual(ledger.total_pnl(), "-2.50")
            try:
                case["risk_fixture"]["engine"].transition_reservation(
                    case["risk_decision"].approval_id, ExposureState.SETTLED,
                    occurred_at="2026-01-01T00:18:00Z",
                )
            except (RegistryConflict, TypeError):
                pass
            ledger.record_fill(FillRecord(
                "late-2", case["intent"].order_id,
                case["intent"].candidate_decision_hash,
                BetSide.BACK, "2", "2.50", "2026-01-01T00:19:00Z",
            ))
            restarted = restart_risk(root)
            own = [item for item in restarted.reserved_exposures()
                   if item.exposure_id == case["risk_decision"].approval_id]
            self.assertEqual(len(own), 1,
                             "partial settlement and correction cannot release a live remainder")
            self.assertEqual(own[0].liability_amount,
                             Decimal(case["risk_decision"].approved_liability))
            self.assertEqual(SettlementLedger(root / "ledger.jsonl").total_pnl(), "-2.50")
            self.assertEqual(SettlementLedger(root / "ledger.jsonl").verify(), 4)

    def test_c04_late_exposure_and_durable_withdrawal_both_precede_send(self):
        with scratch_directory() as root:
            case = build_execution(root)
            case["adapter"].create_intent(case["intent"])
            case["adapter"].bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
            _paper_mode_adapter(case)
            case["adapter"].transition("key-a", OrderState.SUBMISSION_PENDING,
                                       occurred_at="2026-01-01T00:14:00Z")
            case["risk_fixture"]["engine"].record_exposure(
                Exposure("late-independent", "f" * 64, "55", ExposureState.MATCHED),
                recorded_at="2026-01-01T00:15:00Z",
            )
            _withdraw_strategy(case, at="2026-01-01T00:15:30Z")
            self.assertEqual(sum((item.liability_amount for item in
                                  case["risk_fixture"]["engine"].reserved_exposures()),
                                 Decimal("0")), Decimal("62.5"))
            before = len(case["adapter"]._audit.records())
            with self.assertRaises(RegistryConflict):
                case["adapter"].transition("key-a", OrderState.SUBMISSION_SENT,
                                           occurred_at="2026-01-01T00:16:00Z")
            self.assertEqual(len(case["adapter"]._audit.records()), before)
            self.assertEqual(case["adapter"].get("key-a").state,
                             OrderState.SUBMISSION_PENDING)

    def test_c05_unknown_rebase_withdrawal_restart_preserves_lineage(self):
        with scratch_directory() as root:
            case = _bound_clustered_order(root)
            _sent(case)
            adapter = case["adapter"]
            adapter.transition("key-a", OrderState.ACK_RECEIVED,
                               occurred_at="2026-01-01T00:15:10Z")
            adapter.transition("key-a", OrderState.PARTIALLY_MATCHED,
                               occurred_at="2026-01-01T00:15:20Z")
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(FillRecord(
                "partial", case["intent"].order_id,
                case["intent"].candidate_decision_hash,
                BetSide.BACK, "2", "2.50", "2026-01-01T00:15:30Z",
            ))
            adapter.transition("key-a", OrderState.CANCEL_PENDING,
                               occurred_at="2026-01-01T00:15:40Z")
            adapter.transition("key-a", OrderState.UNKNOWN,
                               occurred_at="2026-01-01T00:15:50Z")
            engine = case["risk_fixture"]["engine"]
            engine.transition_reservation(
                case["risk_decision"].approval_id, ExposureState.UNKNOWN,
                occurred_at="2026-01-01T00:16:00Z",
            )
            engine.rebase("50", captured_at="2026-01-01T00:17:00Z",
                          scheduled_weekly=False, drawdown_triggered=True)
            _withdraw_strategy(case)
            restarted = restart_risk(root)
            own = [item for item in restarted.reserved_exposures()
                   if item.exposure_id == case["risk_decision"].approval_id]
            self.assertEqual(len(own), 1)
            self.assertEqual(own[0].state, ExposureState.UNKNOWN)
            self.assertEqual(own[0].correlation_cluster_ids, ("shared",))
            self.assertEqual(own[0].liability_amount,
                             Decimal(case["risk_decision"].approved_liability))
            self.assertEqual(restarted.bankrolls.current().bankroll, "50")
            self.assertEqual(SettlementLedger(root / "ledger.jsonl").verify(), 1)
            self.assertFalse(restarted.approval_still_valid(
                case["risk_decision"].approval_id,
                at="2026-01-01T00:19:00Z",
            ))
            recovered = restart_adapter(root, restarted)
            self.assertEqual(recovered.get("key-a").state,
                             OrderState.RECONCILIATION_REQUIRED)
            second = _second_qualification(case["risk_fixture"])
            decision = restarted.approve(risk_request(
                case["risk_fixture"],
                candidate_hash=second.candidate_decision_hash,
                qualification_record_id=second.qualification_record_id,
                bankroll_snapshot_id=restarted.bankrolls.current().snapshot_id,
                requested_at="2026-01-01T00:19:00Z",
            ))
            self.assertFalse(decision.passed,
                             "UNKNOWN plus stale/withdrawn heads cannot fund new risk")
            self.assertFalse(any(
                row.get("to_state") == OrderState.SUBMISSION_SENT.value
                for row in recovered._audit.records()
                if row.get("occurred_at", "") > "2026-01-01T00:15:00Z"
            ))


if __name__ == "__main__":
    unittest.main()
