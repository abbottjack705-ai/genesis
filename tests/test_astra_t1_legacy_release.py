"""Audit-only legacy-v2 settlement proofs required by ADR-0002.

These tests never make a legacy identity eligible for a new action.  They
exercise only an already-recorded synthetic PAPER approval/order/fill history.
"""

from __future__ import annotations

import unittest

from genesis.accounting import BetSide, SettlementKind
from genesis.execution import (
    CriticalEvidenceRefreshStore,
    ExecutionMarketStateStore,
    ModeStateStore,
    OrderIntent,
    OrderState,
    PaperExecutionAdapter,
)
from genesis.ledger import FillRecord, SettlementLedger
from genesis.registry import AppendOnlyJsonl, RegistryConflict, StrategyRegistry
from genesis.release_proof import OfflinePaperReleaseProofStore
from genesis.repro import canonical_json, sha256_bytes
from genesis.risk import (
    BankrollSnapshotStore,
    ExposureState,
    RiskApproval,
    RiskAuditLog,
    RiskEngine,
    SafetyStateStore,
)
from genesis.selection import QualificationRecord, QualificationRecordStore

from ._support import scratch_directory
from .test_astra_t1_release_proof import _full_settlement
from .test_remediation_r5_risk import build_risk, digest


class _HistoricalActiveView:
    def is_active(self, _candidate_hash, _at):
        return True


def _legacy_method(owner: OfflinePaperReleaseProofStore):
    method = getattr(owner, "issue_legacy_full_settlement", None)
    if not callable(method):
        raise AssertionError(
            "B3 requires a separate audit-only legacy-v2 settlement proof operation"
        )
    return method


def _legacy_history(root, *, with_fill: bool = True):
    risk_root = root / "risk"
    fixture = build_risk(risk_root)
    legacy = fixture["qualifications"].append(QualificationRecord.create(
        candidate_id="legacy", candidate_decision_hash=digest("9"),
        strategy_id="strategy", strategy_version="v1",
        strategy_decision_contract_hash=digest("a"), approved_tier="2.0u",
        comparability_group_id="group",
        active_policy_digest=fixture["policy"].digest,
        market_capability_id="capability-v1",
        decision_at="2026-01-01T00:00:00Z",
        evaluated_at="2026-01-01T00:01:00Z",
        expires_at="2026-01-01T01:00:00Z",
        gate_results_digest=digest("b"),
    ))
    qualification_row = next(
        row for row in fixture["qualifications"].log.records()
        if row.get("qualification_record_id") == legacy.qualification_record_id
    )
    approval = RiskApproval.create(
        qualification_record_id=legacy.qualification_record_id,
        candidate_decision_hash=legacy.candidate_decision_hash,
        strategy_decision_contract_hash=legacy.strategy_decision_contract_hash,
        bankroll_snapshot_id=fixture["snapshot"].snapshot_id,
        bankroll_value="100", approved_unit_tier="2.0u",
        approved_stake="5", approved_liability="5", side=BetSide.BACK,
        odds="2", risk_policy_version=fixture["policy"].risk.version,
        risk_policy_digest=fixture["policy"].risk.digest,
        safety_state_id=fixture["safety"].current().state_id,
        issued_at="2026-01-01T00:02:00Z", expires_at=legacy.expires_at,
    )
    fixture["audit"].log.append({
        "record_type": "risk_approval_created",
        "schema_version": "risk-approval-v2",
        **approval.to_dict(),
        "correlation_cluster_ids": [],
        "affected_scope": None,
    })
    intent = OrderIntent(
        legacy.candidate_decision_hash, "legacy-key", BetSide.BACK,
        "5", "2", approval.approval_id, "2026-01-01T00:03:00Z",
    )
    fixture["audit"].log.append({
        "record_type": "risk_approval_consumed",
        "schema_version": "risk-approval-v2",
        "approval_id": approval.approval_id,
        "candidate_decision_hash": legacy.candidate_decision_hash,
        "order_id": intent.order_id,
        "consumed_at": "2026-01-01T00:04:00Z",
    })
    order_log = AppendOnlyJsonl(root / "orders.jsonl")
    order_log.append({
        "record_type": "order_intent_created",
        "schema_version": "order-event-v2",
        "order_id": intent.order_id,
        **intent.to_dict(),
    })
    previous = OrderState.ORDER_INTENT_CREATED
    for target, at in (
        (OrderState.RISK_APPROVED, "2026-01-01T00:04:30Z"),
        (OrderState.SUBMISSION_PENDING, "2026-01-01T00:05:00Z"),
        (OrderState.SUBMISSION_SENT, "2026-01-01T00:05:30Z"),
        (OrderState.ACK_RECEIVED, "2026-01-01T00:05:40Z"),
        (OrderState.FULLY_MATCHED, "2026-01-01T00:07:00Z"),
    ):
        order_log.append({
            "record_type": "order_state_transition",
            "schema_version": "order-event-v2",
            "order_id": intent.order_id,
            "from_state": previous.value,
            "to_state": target.value,
            "occurred_at": at,
        })
        previous = target
    adapter = PaperExecutionAdapter(
        root / "orders.jsonl", risk=fixture["engine"],
        markets=ExecutionMarketStateStore(root / "markets.jsonl"),
        refreshes=CriticalEvidenceRefreshStore(root / "refreshes.jsonl"),
        strategy_view=_HistoricalActiveView(), modes=fixture["modes"],
        action_clock=lambda requested_at: requested_at,
    )
    ledger = SettlementLedger(root / "ledger.jsonl")
    if with_fill:
        ledger.record_fill(FillRecord(
            fill_id="legacy-fill", order_id=intent.order_id,
            candidate_decision_hash=legacy.candidate_decision_hash,
            side=BetSide.BACK, odds="2", stake="5",
            filled_at="2026-01-01T00:06:00Z",
        ))
        ledger.settle(
            event_id="legacy-settlement", fill_id="legacy-fill",
            kind=SettlementKind.WIN, occurred_at="2026-01-01T00:30:00Z",
        )
    adapter.transition(
        "legacy-key", OrderState.SETTLED,
        occurred_at="2026-01-01T00:40:00Z",
    )
    owner = OfflinePaperReleaseProofStore(
        root / "release-proofs.jsonl",
        risk=fixture["engine"], execution=adapter, ledger=ledger,
    )
    return {
        "root": root, "risk_root": risk_root, "fixture": fixture,
        "legacy": legacy, "qualification_row": qualification_row,
        "approval": approval, "intent": intent, "adapter": adapter,
        "ledger": ledger, "owner": owner,
    }


def _restart(case):
    risk_root = case["risk_root"]
    fixture = case["fixture"]
    risk = RiskEngine(
        policy=fixture["policy"],
        bankrolls=BankrollSnapshotStore(risk_root / "bankroll.jsonl"),
        qualifications=QualificationRecordStore(risk_root / "qualifications.jsonl"),
        safety=SafetyStateStore(risk_root / "safety.jsonl"),
        audit_log=RiskAuditLog(risk_root / "risk.jsonl"),
        strategies=StrategyRegistry(risk_root / "strategies.jsonl"),
        modes=ModeStateStore(risk_root / "mode.jsonl"),
        action_clock=lambda requested_at: requested_at,
    )
    adapter = PaperExecutionAdapter(
        case["root"] / "orders.jsonl", risk=risk,
        markets=ExecutionMarketStateStore(case["root"] / "markets.jsonl"),
        refreshes=CriticalEvidenceRefreshStore(case["root"] / "refreshes.jsonl"),
        strategy_view=_HistoricalActiveView(),
        modes=ModeStateStore(risk_root / "mode.jsonl"),
        action_clock=lambda requested_at: requested_at,
    )
    ledger = SettlementLedger(case["root"] / "ledger.jsonl")
    owner = OfflinePaperReleaseProofStore(
        case["root"] / "release-proofs.jsonl",
        risk=risk, execution=adapter, ledger=ledger,
    )
    risk.attach_release_proofs(owner)
    return risk, owner, ledger


def _forge(case, proof, **changes):
    owner = OfflinePaperReleaseProofStore(
        case["root"] / f"forged-{len(changes)}-{next(iter(changes), 'none')}.jsonl",
        risk=case["fixture"]["engine"], execution=case["adapter"],
        ledger=case["ledger"],
    )
    payload = {
        key: value for key, value in proof.items()
        if key not in {"previous_hash", "sequence", "record_hash", "proof_id"}
    }
    payload.update(changes)
    payload["proof_id"] = sha256_bytes(canonical_json(payload))
    # Forged durable bytes: the proof owner's storage refuses rows its replay
    # rejects (E4), so they are written as a raw writer outside it would.
    return owner, AppendOnlyJsonl(owner.log.path).append(payload)


class AstraLegacyV2ReleaseTests(unittest.TestCase):
    def test_valid_legacy_full_settlement_releases_once_and_restarts(self):
        with scratch_directory() as root:
            case = _legacy_history(root)
            issue = _legacy_method(case["owner"])
            proof_hash = issue(
                case["intent"].order_id,
                occurred_at="2026-01-01T00:41:00Z",
            )
            proof = case["owner"].validate_current(proof_hash)
            self.assertEqual(proof["scope"], "LEGACY_AUDIT_SETTLEMENT_ONLY")
            self.assertEqual(
                proof["legacy_qualification_record_hash"],
                case["qualification_row"]["record_hash"],
            )
            self.assertNotIn("decision_output_hash", proof)
            engine = case["fixture"]["engine"]
            engine.attach_release_proofs(case["owner"])
            released = engine.release_with_proof(
                proof_hash, occurred_at="2026-01-01T00:42:00Z",
            )
            self.assertEqual(released.state, ExposureState.SETTLED)
            self.assertEqual(engine.reserved_exposures(), ())
            self.assertEqual(
                engine.release_with_proof(
                    proof_hash, occurred_at="2026-01-01T00:42:00Z",
                ),
                released,
            )
            rows = [row for row in engine.audit_log.log.records()
                    if row.get("record_type") == "risk_reservation_legacy_release"]
            self.assertEqual(len(rows), 1)
            self.assertNotIn("decision_output_hash", rows[0])

            restarted, restarted_owner, _ = _restart(case)
            self.assertEqual(restarted.reserved_exposures(), ())
            self.assertEqual(
                restarted_owner.validate_current(proof_hash)["record_hash"], proof_hash,
            )

    def test_v2_and_v3_proof_paths_never_cross_or_fabricate_lineage(self):
        with scratch_directory() as root:
            case = _legacy_history(root / "v2")
            with self.assertRaises(RegistryConflict):
                case["owner"].issue_full_settlement(
                    case["intent"].order_id,
                    occurred_at="2026-01-01T00:41:00Z",
                )
            proof_hash = _legacy_method(case["owner"])(
                case["intent"].order_id,
                occurred_at="2026-01-01T00:41:00Z",
            )
            proof = case["owner"].validate_current(proof_hash)
            for changes in (
                {"legacy_qualification_record_hash": digest("f")},
                {"decision_output_hash": digest("e")},
                {"candidate_decision_hash": digest("d")},
            ):
                forged, forged_hash = _forge(case, proof, **changes)
                with self.assertRaises(RegistryConflict):
                    forged.validate_current(forged_hash)

            v3, v3_ledger = _full_settlement(root / "v3")
            v3_owner = OfflinePaperReleaseProofStore(
                root / "v3" / "release-proofs.jsonl",
                risk=v3["risk_fixture"]["engine"],
                execution=v3["adapter"], ledger=v3_ledger,
            )
            with self.assertRaises(RegistryConflict):
                _legacy_method(v3_owner)(
                    v3["intent"].order_id,
                    occurred_at="2026-01-01T00:41:00Z",
                )

    def test_missing_fill_or_terminal_head_never_creates_legacy_release(self):
        with scratch_directory() as root:
            case = _legacy_history(root, with_fill=False)
            before_proofs = len(case["owner"].log.records())
            before_risk = len(case["fixture"]["audit"].log.records())
            with self.assertRaises(RegistryConflict):
                _legacy_method(case["owner"])(
                    case["intent"].order_id,
                    occurred_at="2026-01-01T00:41:00Z",
                )
            self.assertEqual(len(case["owner"].log.records()), before_proofs)
            self.assertEqual(len(case["fixture"]["audit"].log.records()), before_risk)
            self.assertEqual(
                [item.state for item in case["fixture"]["engine"].reserved_exposures()],
                [ExposureState.PENDING],
            )

    def test_late_fill_invalidates_legacy_release_and_restores_full_charge(self):
        with scratch_directory() as root:
            case = _legacy_history(root)
            proof_hash = _legacy_method(case["owner"])(
                case["intent"].order_id,
                occurred_at="2026-01-01T00:41:00Z",
            )
            engine = case["fixture"]["engine"]
            engine.attach_release_proofs(case["owner"])
            engine.release_with_proof(
                proof_hash, occurred_at="2026-01-01T00:42:00Z",
            )
            case["ledger"].record_fill(FillRecord(
                fill_id="legacy-late-fill", order_id=case["intent"].order_id,
                candidate_decision_hash=case["legacy"].candidate_decision_hash,
                side=BetSide.BACK, odds="2", stake="0.5",
                filled_at="2026-01-01T00:43:00Z",
            ))
            with self.assertRaises(RegistryConflict):
                case["owner"].validate_current(proof_hash)
            reserved = engine.reserved_exposures()
            self.assertEqual(len(reserved), 1)
            self.assertEqual(reserved[0].state, ExposureState.UNKNOWN)
            self.assertEqual(reserved[0].liability, "5")


if __name__ == "__main__":
    unittest.main()
