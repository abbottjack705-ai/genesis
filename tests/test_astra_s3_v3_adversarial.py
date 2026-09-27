"""Astra A4 adversaries for trusted v3 output and downstream lineage."""

from __future__ import annotations

import multiprocessing
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from genesis.selection import QualificationRecord

from ._support import SyntheticQualificationRecordStore, scratch_directory
from .test_remediation_r3_qualification import build_fixture, digest


NOW = "2026-01-01T00:11:00Z"


def _forced_collision_worker(root, source_root, body, entered, release, results):
    sys.path.insert(0, str(source_root))
    import genesis.decision_output as output_module

    output_module.sha256_bytes = lambda _value: "f" * 64
    entered.set()
    release.wait(20)
    try:
        value = output_module.DecisionOutputStore(root).publish(body)
        results.put(("ok", value))
    except Exception as exc:
        results.put(("error", type(exc).__name__))


class AstraV3AdversarialTests(unittest.TestCase):
    def _fixture(self, root):
        fixture = build_fixture(root)
        self.assertEqual(
            fixture["candidate"].candidate_version, "candidate-v3",
            "no v3 trusted decision authority exists",
        )
        return fixture

    def _pass_without_record(self, fixture):
        result = fixture["authority"].evaluate(fixture["candidate"], now=NOW)
        self.assertEqual(result.action, "PASS")
        self.assertIsNone(result.qualification_record_id)
        self.assertEqual(fixture["records"].verify(), 0)

    def test_exact_v3_replay_survives_restart_without_new_identity(self):
        with scratch_directory() as root:
            fixture = self._fixture(root)
            from genesis.decision_output import (
                DecisionOutputStore, StrategyOutputRuleBindingStore,
            )
            from genesis.selection import QualificationRecordStore

            first = fixture["authority"].evaluate(fixture["candidate"], now=NOW)
            self.assertEqual(first.action, "QUALIFY")
            existing = fixture["trusted_outputs"]
            reopened_outputs = DecisionOutputStore(root / "decision-outputs")
            fixture["authority"].decision_outputs = type(existing)(
                outputs=reopened_outputs,
                bindings=StrategyOutputRuleBindingStore(root / "strategy-output-bindings.jsonl"),
                resolver=existing.resolver,
            )
            fixture["authority"].qualification_records = SyntheticQualificationRecordStore(
                root / "qualifications.jsonl", outputs=reopened_outputs,
            )
            second = fixture["authority"].evaluate(fixture["candidate"], now=NOW)
            self.assertEqual(second, first)
            self.assertEqual(fixture["authority"].qualification_records.verify(), 1)
            self.assertEqual(
                fixture["authority"].qualification_records.get_for_new_risk(
                    first.qualification_record_id
                ).decision_output_hash,
                fixture["candidate"].decision_output_hash,
            )

    def test_each_copied_v3_material_field_swap_fails_before_record(self):
        changes = (
            {"model_probability": "0.63"},
            {"conservative_probability": "0.61"},
            {"uncertainty_status": "uncertain"},
            {"critical_uncertainty_flags": ("late-news",)},
            {"observed_odds": "2.01"},
            {"requested_odds_min": "1.6"},
            {"strategy_tier": "2.5u"},
            {"expires_at": "2026-01-01T02:00:00Z"},
            {"correlation_cluster_ids": ("other",)},
            {"shared_evidence_ids": ("other-evidence",)},
            {"model_version": "other-model"},
        )
        with scratch_directory() as root:
            for index, change in enumerate(changes):
                with self.subTest(change=change):
                    fixture = self._fixture(root / str(index))
                    fixture["candidate"] = replace(fixture["candidate"], **change)
                    self._pass_without_record(fixture)

    def test_self_hashed_changed_output_and_new_candidate_hash_are_not_trusted(self):
        changes = (
            ("model_probability", "0.63", "model_probability"),
            ("conservative_probability", "0.61", "conservative_probability"),
            ("observed_odds", "2.01", "observed_odds"),
            ("requested_odds_min", "1.6", "requested_odds_min"),
            ("approved_tier", "2.5u", "strategy_tier"),
            ("expires_at", "2026-01-01T02:00:00.000000Z", "expires_at"),
            ("correlation_cluster_ids", ["other"], "correlation_cluster_ids"),
            ("tier_rule_hash", digest("9"), None),
        )
        with scratch_directory() as root:
            for index, (field, value, copy_field) in enumerate(changes):
                with self.subTest(field=field):
                    fixture = self._fixture(root / str(index))
                    from genesis.decision import candidate_v3_decision_hash
                    body = dict(fixture["output_body"], **{field: value})
                    changed_hash = fixture["trusted_outputs"].outputs.publish(body)
                    candidate = fixture["candidate"]
                    if copy_field is not None:
                        candidate_value = tuple(value) if isinstance(value, list) else value
                        candidate = replace(candidate, **{copy_field: candidate_value})
                    candidate = replace(
                        candidate, decision_output_hash=changed_hash,
                        candidate_decision_hash=candidate_v3_decision_hash(
                            strategy_decision_contract_hash=body["strategy_decision_contract_hash"],
                            feature_manifest_hash=body["feature_manifest_hash"],
                            evidence_pack_hash=body["evidence_pack_hash"],
                            decision_output_hash=changed_hash,
                        ),
                    )
                    fixture["candidate"] = candidate
                    self._pass_without_record(fixture)

    def test_revoked_ambiguous_or_unavailable_binding_and_resolver_fail(self):
        with scratch_directory() as root:
            for case in ("revoked", "ambiguous", "resolver-missing", "production-copy"):
                with self.subTest(case=case):
                    fixture = self._fixture(root / case)
                    authority = fixture["trusted_outputs"]
                    rows = authority.bindings.log.records()
                    body = dict(rows[0]["binding"])
                    if case == "revoked":
                        authority.bindings.revoke(rows[0]["binding_hash"], revoked_at=NOW)
                    elif case == "ambiguous":
                        authority.bindings.register_approved(dict(body, tier_rule_hash=digest("9")))
                    elif case == "resolver-missing":
                        authority.resolver = None
                    else:
                        from genesis.decision_output import TrustedDecisionOutputAuthority

                        fixture["authority"].decision_outputs = TrustedDecisionOutputAuthority(
                            outputs=authority.outputs,
                            bindings=authority.bindings,
                            resolver=authority.resolver,
                        )
                    self._pass_without_record(fixture)

    def test_v3_ranking_uses_record_and_output_not_caller_copies(self):
        with scratch_directory() as root:
            fixture = self._fixture(root)
            import genesis.selection as selection

            decision = fixture["authority"].evaluate(fixture["candidate"], now=NOW)
            self.assertEqual(decision.action, "QUALIFY")
            ranked = selection.rank_qualified_v3(
                [(fixture["candidate"], decision)], qualification_records=fixture["records"],
            )
            self.assertEqual(ranked[0].candidate_decision_hash, fixture["candidate"].candidate_decision_hash)
            with self.assertRaises(ValueError):
                selection.rank_qualified([(fixture["candidate"], decision)])
            with self.assertRaises(ValueError):
                selection.rank_qualified_v3(
                    [(replace(fixture["candidate"], conservative_probability="0.61"), decision)],
                    qualification_records=fixture["records"],
                )
            with self.assertRaises(ValueError):
                selection.rank_qualified_v3(
                    [(fixture["candidate"], decision), (fixture["candidate"], decision)],
                    qualification_records=fixture["records"],
                )

    def test_legacy_or_mismatched_v3_qualification_cannot_approve_new_risk(self):
        with scratch_directory() as root:
            self._fixture(root / "v3-existence")
            from genesis.accounting import BetSide
            from genesis.risk import RiskRequest
            from .test_remediation_r5_risk import build_risk

            fixture = build_risk(root / "risk")
            legacy = fixture["qualifications"].append(QualificationRecord.create(
                candidate_id="legacy", candidate_decision_hash=digest("9"),
                strategy_id="strategy", strategy_version="v1",
                strategy_decision_contract_hash=digest("a"), approved_tier="2.0u",
                comparability_group_id="group", active_policy_digest=fixture["policy"].digest,
                market_capability_id="capability-v1",
                decision_at="2026-01-01T00:00:00Z", evaluated_at="2026-01-01T00:01:00Z",
                expires_at="2026-01-01T01:00:00Z", gate_results_digest=digest("b"),
            ))
            request = RiskRequest(
                legacy.candidate_decision_hash, legacy.qualification_record_id,
                fixture["snapshot"].snapshot_id, BetSide.BACK, "2", NOW,
            )
            result = fixture["engine"].approve(request)
            self.assertFalse(result.passed)
            self.assertEqual(result.reason, "authority_unavailable")
            original = fixture["qualification"]
            forged = fixture["qualifications"].record_fixture_qualification(QualificationRecord.create(
                schema_version="qualification-record-v3",
                candidate_id="forged", candidate_decision_hash=original.candidate_decision_hash,
                strategy_id=original.strategy_id, strategy_version=original.strategy_version,
                strategy_decision_contract_hash=original.strategy_decision_contract_hash,
                approved_tier="2.5u", comparability_group_id=original.comparability_group_id,
                active_policy_digest=original.active_policy_digest,
                market_capability_id=original.market_capability_id,
                decision_at=original.decision_at, evaluated_at=original.evaluated_at,
                expires_at=original.expires_at, gate_results_digest=original.gate_results_digest,
                decision_output_hash=original.decision_output_hash,
                feature_manifest_hash=original.feature_manifest_hash,
            ))
            forged_request = RiskRequest(
                forged.candidate_decision_hash, forged.qualification_record_id,
                fixture["snapshot"].snapshot_id, BetSide.BACK, "2", NOW,
            )
            self.assertEqual(fixture["engine"].approve(forged_request).reason, "authority_unavailable")

    def test_binding_revocation_after_qualification_blocks_new_risk_and_pending(self):
        with scratch_directory() as root:
            self._fixture(root / "v3-existence")
            from .test_remediation_r5_risk import build_risk, request
            from .test_remediation_r6_execution import build_execution
            from genesis.execution import OrderState

            fresh = build_risk(root / "fresh")
            fresh_output = fresh["qualifications"].outputs.get(
                fresh["qualification"].decision_output_hash
            )
            fresh["qualifications"].bindings.revoke(
                fresh_output["resolver_binding_hash"], revoked_at=NOW,
            )
            decision = fresh["engine"].approve(request(fresh, requested_at="2026-01-01T00:12:00Z"))
            self.assertFalse(decision.passed)
            self.assertEqual(decision.reason, "authority_unavailable")
            self.assertEqual(fresh["audit"].log.records(), [])

            order = build_execution(root / "order")
            adapter = order["adapter"]
            intent = order["intent"]
            adapter.create_intent(intent)
            adapter.bind_risk(intent.idempotency_key, bound_at="2026-01-01T00:12:00Z")
            qualifications = order["risk_fixture"]["qualifications"]
            output = qualifications.outputs.get(order["risk_fixture"]["qualification"].decision_output_hash)
            qualifications.bindings.revoke(output["resolver_binding_hash"], revoked_at=NOW)
            with self.assertRaises(Exception):
                adapter.transition(
                    intent.idempotency_key, OrderState.SUBMISSION_PENDING,
                    occurred_at="2026-01-01T00:13:00Z",
                )
            self.assertEqual(adapter.get(intent.idempotency_key).state, OrderState.RISK_APPROVED)

    def test_risk_request_cannot_change_trusted_side_or_leave_output_price_band(self):
        with scratch_directory() as root:
            self._fixture(root / "v3-existence")
            from genesis.accounting import BetSide
            from .test_remediation_r5_risk import build_risk, request

            fixture = build_risk(root / "risk")
            for side, odds in ((BetSide.LAY, "2"), (BetSide.BACK, "3.01")):
                with self.subTest(side=side, odds=odds):
                    decision = fixture["engine"].approve(request(fixture, side=side, odds=odds))
                    self.assertFalse(decision.passed)
                    self.assertEqual(decision.reason, "decision_output_execution_mismatch")
            self.assertEqual(fixture["audit"].log.records(), [])

    def test_manually_appended_v3_without_separate_operator_approval_cannot_reach_risk(self):
        with scratch_directory() as root:
            self._fixture(root / "v3-existence")
            from genesis.policy import PolicySet
            from genesis.risk import (
                BankrollSnapshotStore, RiskAuditLog, RiskEngine, SafetyStateStore,
            )
            from genesis.selection import QualificationRecordStore
            from .test_remediation_r5_risk import build_risk, request

            fixture = build_risk(root / "risk")
            base = RiskEngine(
                policy=PolicySet(),
                bankrolls=BankrollSnapshotStore(root / "risk" / "bankroll.jsonl"),
                qualifications=QualificationRecordStore(root / "risk" / "qualifications.jsonl"),
                safety=SafetyStateStore(root / "risk" / "safety.jsonl"),
                audit_log=RiskAuditLog(root / "risk" / "risk.jsonl"),
            )
            decision = base.approve(request(fixture))
            self.assertFalse(decision.passed)
            self.assertEqual(decision.reason, "authority_unavailable")
            self.assertEqual(fixture["audit"].log.records(), [])

    def test_output_without_qualification_after_crash_cannot_reach_risk(self):
        with scratch_directory() as root:
            fixture = self._fixture(root)
            log = fixture["records"].log
            original = log.transaction

            def crash(_builder, **_kwargs):
                raise OSError("synthetic crash before qualification append")

            log.transaction = crash
            try:
                with self.assertRaises(OSError):
                    fixture["authority"].evaluate(fixture["candidate"], now=NOW)
            finally:
                log.transaction = original
            self.assertEqual(fixture["records"].verify(), 0)
            self.assertEqual(
                fixture["trusted_outputs"].outputs.get(fixture["candidate"].decision_output_hash),
                fixture["output_body"],
            )
            self.assertEqual(fixture["authority"].evaluate(fixture["candidate"], now=NOW).action,
                             "QUALIFY")
            self.assertEqual(fixture["records"].verify(), 1)

    def test_legacy_order_is_audit_replay_only_but_can_finish_settlement(self):
        with scratch_directory() as root:
            self._fixture(root / "v3-existence")
            from genesis.accounting import BetSide, SettlementKind
            from genesis.execution import (
                CriticalEvidenceRefreshStore, ExecutionMarketStateStore,
                OrderIntent, OrderState, PaperExecutionAdapter,
            )
            from genesis.ledger import FillRecord, SettlementLedger
            from genesis.registry import AppendOnlyJsonl, RegistryConflict
            from genesis.release_proof import OfflinePaperReleaseProofStore
            from genesis.risk import ExposureState, RiskApproval
            from .test_remediation_r5_risk import build_risk

            fixture = build_risk(root / "risk")
            legacy = fixture["qualifications"].append(QualificationRecord.create(
                candidate_id="legacy", candidate_decision_hash=digest("9"),
                strategy_id="strategy", strategy_version="v1",
                strategy_decision_contract_hash=digest("a"), approved_tier="2.0u",
                comparability_group_id="group", active_policy_digest=fixture["policy"].digest,
                market_capability_id="capability-v1",
                decision_at="2026-01-01T00:00:00Z", evaluated_at="2026-01-01T00:01:00Z",
                expires_at="2026-01-01T01:00:00Z", gate_results_digest=digest("b"),
            ))
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
                "record_type": "risk_approval_created", "schema_version": "risk-approval-v2",
                **approval.to_dict(), "correlation_cluster_ids": [], "affected_scope": None,
            })
            intent = OrderIntent(
                legacy.candidate_decision_hash, "legacy-key", BetSide.BACK,
                "5", "2", approval.approval_id, "2026-01-01T00:03:00Z",
            )
            class Active:
                def is_active(self, _candidate_hash, _at):
                    return True

            adapter = PaperExecutionAdapter(
                root / "orders.jsonl", risk=fixture["engine"],
                markets=ExecutionMarketStateStore(root / "markets.jsonl"),
                refreshes=CriticalEvidenceRefreshStore(root / "refreshes.jsonl"),
                strategy_view=Active(),
            )
            with self.assertRaises(RegistryConflict):
                adapter.create_intent(intent)
            with self.assertRaises(RegistryConflict):
                fixture["engine"].consume_for_order(
                    approval.approval_id, order_id=intent.order_id,
                    consumed_at="2026-01-01T00:04:00Z",
                )
            self.assertEqual(fixture["qualifications"].get(legacy.qualification_record_id), legacy)
            # The following rows represent a *pre-activation* sent/matched
            # history, not a new submission through current APIs.
            fixture["audit"].log.append({
                "record_type": "risk_approval_consumed", "schema_version": "risk-approval-v2",
                "approval_id": approval.approval_id,
                "candidate_decision_hash": legacy.candidate_decision_hash,
                "order_id": intent.order_id, "consumed_at": "2026-01-01T00:04:00Z",
            })
            order_log = AppendOnlyJsonl(root / "orders.jsonl")
            order_log.append({"record_type": "order_intent_created",
                              "schema_version": "order-event-v2", "order_id": intent.order_id,
                              **intent.to_dict()})
            previous = OrderState.ORDER_INTENT_CREATED
            for target in (
                OrderState.RISK_APPROVED, OrderState.SUBMISSION_PENDING,
                OrderState.SUBMISSION_SENT, OrderState.ACK_RECEIVED,
                OrderState.FULLY_MATCHED,
            ):
                order_log.append({
                    "record_type": "order_state_transition", "schema_version": "order-event-v2",
                    "order_id": intent.order_id, "from_state": previous.value,
                    "to_state": target.value, "occurred_at": "2026-01-01T00:05:00Z",
                })
                previous = target
            reopened = PaperExecutionAdapter(
                root / "orders.jsonl", risk=fixture["engine"],
                markets=ExecutionMarketStateStore(root / "markets.jsonl"),
                refreshes=CriticalEvidenceRefreshStore(root / "refreshes.jsonl"),
                strategy_view=Active(),
            )
            self.assertEqual(reopened.get("legacy-key").state, OrderState.FULLY_MATCHED)
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(FillRecord(
                fill_id="legacy-fill", order_id=intent.order_id,
                candidate_decision_hash=legacy.candidate_decision_hash,
                side=BetSide.BACK, odds="2", stake="5",
                filled_at="2026-01-01T00:06:00Z",
            ))
            ledger.settle(
                event_id="legacy-settlement", fill_id="legacy-fill",
                kind=SettlementKind.WIN,
                occurred_at="2026-01-01T00:30:00Z",
            )
            self.assertEqual(
                reopened.transition("legacy-key", OrderState.SETTLED,
                                    occurred_at="2026-01-01T00:40:00Z").state,
                OrderState.SETTLED,
            )
            release_proofs = OfflinePaperReleaseProofStore(
                root / "release-proofs.jsonl", risk=fixture["engine"],
                execution=reopened, ledger=ledger,
            )
            proof_hash = release_proofs.issue_legacy_full_settlement(
                intent.order_id, occurred_at="2026-01-01T00:41:00Z",
            )
            proof = release_proofs.validate_current(proof_hash)
            qualification_row = next(
                row for row in fixture["qualifications"].log.records()
                if row.get("qualification_record_id") == legacy.qualification_record_id
            )
            self.assertEqual(
                proof["legacy_qualification_record_hash"],
                qualification_row["record_hash"],
            )
            self.assertNotIn("decision_output_hash", proof)
            fixture["engine"].attach_release_proofs(release_proofs)
            self.assertEqual(
                fixture["engine"].release_with_proof(
                    proof_hash, occurred_at="2026-01-01T00:42:00Z",
                ).state,
                ExposureState.SETTLED,
            )
            self.assertEqual(fixture["engine"].reserved_exposures(), ())

    def test_two_processes_cannot_publish_different_bytes_at_one_output_id(self):
        with scratch_directory() as root:
            fixture = self._fixture(root / "fixture")
            first = dict(fixture["output_body"])
            second = dict(first, approved_tier="2.5u")
            context = multiprocessing.get_context("spawn")
            first_entered, second_entered = context.Event(), context.Event()
            release, results = context.Event(), context.Queue()
            source_root = Path(__file__).resolve().parents[1] / "src"
            target_root = root / "collision"
            workers = (
                context.Process(target=_forced_collision_worker,
                                args=(target_root, source_root, first, first_entered, release, results)),
                context.Process(target=_forced_collision_worker,
                                args=(target_root, source_root, second, second_entered, release, results)),
            )
            for worker in workers:
                worker.start()
            try:
                self.assertTrue(first_entered.wait(20))
                self.assertTrue(second_entered.wait(20))
                release.set()
                outcomes = [results.get(timeout=20) for _ in workers]
                self.assertEqual(sorted(item[0] for item in outcomes), ["error", "ok"])
                self.assertEqual(sum(item[1] == "ImmutableConflict" for item in outcomes), 1)
            finally:
                release.set()
                for worker in workers:
                    worker.join(20)
                    if worker.is_alive():
                        worker.terminate()
                        worker.join(5)
            self.assertEqual(len(list(target_root.glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
