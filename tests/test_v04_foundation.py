from __future__ import annotations

import unittest
from decimal import Decimal

from genesis.accounting import BetSide, SettlementKind
from genesis.candidate_runs import CandidateRunRecord, CandidateRunStore, SearchCoverageSummary
from genesis.canonical import CandidateBet, MarketSide
from genesis.capabilities import CapabilityUnavailable, MarketCapability, MarketCapabilityRegistry
from genesis.decision import ReproducibilityManifest, candidate_decision_hash
from genesis.evidence_pack import EvidencePack, EvidencePackStore
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
)
from genesis.ledger import FillRecord, SettlementLedger
from genesis.policy import PolicySet, assess_price_sanity, break_even_probability
from genesis.pit import (
    BitemporalRecord,
    OperationalStatus,
    PITStore,
    SourceCapability,
    SourceCapabilityRegistry,
    SourceUnavailable,
)
from genesis.protected import LegacyUnsafeProtectedEvaluationBoundary, ProtectedAttemptLedger, ProtectedCampaign
from genesis.evaluation import EvaluationRequest
from genesis.selection_evaluation import SelectionObservation, evaluate_selection_policy
from genesis.labels import DecisionFact, DecisionFrame, FutureOutcomeLabel
from genesis.provenance import AvailabilityClass, ProvenanceRef
from genesis.quota import QuotaInterpretation, QuotaLedger, QuotaPolicy, VerifiedCacheStore
from genesis.registry import RegistryConflict
from genesis.risk import (
    BankrollSnapshot,
    BankrollSnapshotStore,
    Exposure,
    ExposureState,
    RiskAuditLog,
    RiskEngine,
    RiskRequest,
    SafetyState,
    SafetyStateStore,
)
from genesis.runtime import CostLedger, CostLedgerEntry
from genesis.selection import (
    QualificationFacts,
    QualificationRecord,
    QualificationRecordStore,
    SelectionDecision,
    qualify_v04,
    rank_qualified,
)
from ._support import SyntheticQualificationRecordStore as QualificationRecordStore, scratch_directory
from .test_remediation_r5_risk import (
    build_risk, qualification as risk_qualification, request as risk_request,
)
from .test_remediation_r6_execution import build_execution


def digest(char: str = "a") -> str:
    return char * 64


def ref() -> ProvenanceRef:
    return ProvenanceRef(digest("b"), "synthetic-v1", "synthetic://fixture", "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", AvailabilityClass.PROSPECTIVE_CAPTURED, "test-v1")


def candidate(candidate_id: str, *, odds: str = "2.00", probability: str = "0.55", tier: str | None = "2.0u", decision_hash: str | None = digest("c")) -> CandidateBet:
    return CandidateBet(
        candidate_id, "strategy", "v1", "football", "event", "market", candidate_id, MarketSide.BACK,
        "1.50", "3.00", odds, probability, "0.52", "model-v1", "pack-1",
        "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", True,
        strategy_tier=tier, market_family="match_winner", candidate_decision_hash=decision_hash,
        comparability_group_id="default-comparability",
    )


class V04PolicyAndPITTests(unittest.TestCase):
    def test_policy_is_versioned_and_daily_ranges_are_not_caps(self):
        policy = PolicySet()
        self.assertFalse(policy.daily_aims[0].is_quota)
        self.assertFalse(policy.daily_aims[0].is_cap)
        self.assertEqual(policy.daily_aim(__import__("datetime").date(2026, 9, 19)).maximum, 13)
        self.assertEqual(policy.risk.stake_amount("100", "3.0"), Decimal("7.50"))

    def test_price_sanity_uses_provisional_near_fair_tolerance(self):
        policy = PolicySet()
        break_even = break_even_probability("2.00")
        near = assess_price_sanity(
            odds="2.00", model_probability=break_even - Decimal("0.01"),
            policy=policy, strong_conditions=True,
        )
        self.assertTrue(near.passed)
        self.assertTrue(near.provisional)
        self.assertFalse(assess_price_sanity(odds="1.45", model_probability="0.68", policy=policy).passed)
        self.assertFalse(assess_price_sanity(odds="2.00", model_probability=break_even - Decimal("0.01"), policy=policy).passed)

    def test_pit_query_rejects_unknown_capability_and_future_ready_record(self):
        with scratch_directory() as tmp:
            capabilities = SourceCapabilityRegistry(tmp / "sources.jsonl")
            capabilities.register(SourceCapability("s1", "synthetic", "fixture", "free", "test", "prospective", "verified", "append", "fixture", "7/day", "v1", OperationalStatus.READY, "2026-01-01T00:00:00Z", "v1"))
            store = PITStore(tmp / "pit.jsonl", capabilities=capabilities)
            store.append(BitemporalRecord("r1", "e1", "s1", digest(), "2025-12-31T23:00:00Z", None, "2025-12-31T23:01:00Z", "2025-12-31T23:02:00Z", "2025-12-31T23:00:00Z"))
            self.assertEqual(len(store.as_of_query("e1", "2026-01-01T00:00:00Z")), 1)
            store.append(BitemporalRecord("r2", "e2", "s1", digest("d"), "2026-01-01T00:00:00Z", None, "2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z", "2026-01-01T00:00:00Z"))
            self.assertEqual(store.as_of_query("e2", "2026-01-01T00:01:30Z"), ())
            with self.assertRaises(SourceUnavailable):
                store.as_of_query("e1", "2026-01-01T00:00:00Z", source_id="unknown")

    def test_evidence_pack_and_decision_hash_are_immutable(self):
        pack = EvidencePack.freeze(
            pack_id="pack-1", evidence_cutoff_ts="2026-01-01T00:00:00Z", frozen_at="2026-01-01T00:01:00Z",
            source_artifact_hashes=(digest("a"),), extractor_versions=("extract-v1",), prompt_schema_hash=digest("b"),
            contradiction_links=(), freshness_state=("fresh",), feature_manifest_hash=digest("c"),
        )
        with scratch_directory() as tmp:
            store = EvidencePackStore(tmp / "packs")
            store.freeze(pack)
            self.assertEqual(store.get(pack.pack_hash), pack)
            self.assertEqual(store.verify_manifest(), 1)
        inputs = {field: digest(chr(100 + i)) if "hash" in field else field for i, field in enumerate((
            "strategy_version", "strategy_config_hash", "strategy_decision_contract_hash", "odds_profile_hash", "sport_adapter_version", "event_id", "market_id", "selection_id", "side", "evidence_cutoff_ts", "candidate_decision_ts", "evidence_pack_hash", "feature_manifest_hash", "model_artifact_hash", "calibration_artifact_hash", "gate_policy_hash"))}
        first = candidate_decision_hash(inputs)
        inputs["gate_policy_hash"] = digest("z")
        self.assertNotEqual(first, candidate_decision_hash(inputs))
        manifest = ReproducibilityManifest(
            git_commit_hash=digest("a"), dependency_lock_hash=digest("b"), runtime_hash=digest("c"),
            config_hash=digest("d"), dataset_release_hash=digest("e"), model_hashes=(digest("f"),),
            calibration_hashes=(digest("g"),), prompt_template_hash=digest("h"), extractor_schema_hash=digest("i"),
            evidence_pack_hash=digest("j"), feature_manifest_hash=digest("k"), random_seeds=("seed-1",),
            timezone_policy="UTC", command="pytest", run_mode="offline",
        )
        self.assertEqual(len(manifest.digest), 64)

    def test_source_supersession_is_honoured_at_the_requested_time(self):
        with scratch_directory() as tmp:
            capabilities = SourceCapabilityRegistry(tmp / "sources.jsonl")
            capabilities.register(SourceCapability("s1", "synthetic", "fixture", "free", "test", "prospective", "verified", "append", "fixture", "7/day", "v1", OperationalStatus.READY, "2025-12-31T22:00:00Z", "v1"))
            store = PITStore(None, capabilities=capabilities)
            store.append(BitemporalRecord("old", "e1", "s1", digest("a"), "2025-12-31T23:00:00Z", None, "2025-12-31T23:01:00Z", "2025-12-31T23:02:00Z", "2025-12-31T23:00:00Z", superseded_by="new", superseded_at="2026-01-01T00:00:00Z"))
            store.append(BitemporalRecord("new", "e1", "s1", digest("b"), "2026-01-01T00:00:00Z", None, "2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z", "2026-01-01T00:00:00Z"))
            self.assertEqual([row.record_id for row in store.as_of_query("e1", "2025-12-31T23:30:00Z")], ["old"])
            self.assertEqual([row.record_id for row in store.as_of_query("e1", "2026-01-01T00:03:00Z")], ["new"])

    def test_market_capability_and_mode_authority_fail_closed(self):
        with scratch_directory() as tmp:
            registry = MarketCapabilityRegistry(tmp / "markets.jsonl")
            capability = MarketCapability("cap-1", "football", "match_winner", True, True, False, True, True, True, False, "v1", "2026-01-01T00:00:00Z")
            registry.register(capability)
            with self.assertRaises(Exception):
                registry.require_ready("cap-1")
        with scratch_directory() as tmp:
            mode_states = ModeStateStore(tmp / "mode.jsonl")
            mode_states.append(ModeState.create(mode=OperationalMode.OFFLINE_RESEARCH, occurred_at="2026-01-01T00:00:00Z", authorization_id=None, parent_state_id=None))
            safety = SafetyStateStore(tmp / "safety.jsonl")
            safety.append(SafetyState.create(kill_switch_active=False, recorded_at="2026-01-01T00:00:00Z", reason="initial"))
            controller = ModeController(mode_states, safety)
            with self.assertRaises(PermissionError):
                controller.transition(OperationalMode.PAPER, occurred_at="2026-01-01T00:01:00Z")
            auth = AuthorizationArtifact("auth-1", "human", OperationalMode.PAPER, "2026-01-01T00:00:00Z", digest("p"))
            self.assertEqual(controller.transition(auth.mode, auth, occurred_at="2026-01-01T00:01:00Z"), auth.mode)
            with self.assertRaises(ValueError):
                controller.transition(OperationalMode.LIVE, auth, occurred_at="2026-01-01T00:02:00Z")

    def test_runtime_cost_budget_is_fail_closed(self):
        ledger = CostLedger()
        ledger.record(CostLedgerEntry("c1", "2026-01-01T00:00:00Z", "subscription", Decimal("10.01"), True))
        self.assertFalse(ledger.can_deploy())


class V04CandidateRiskExecutionTests(unittest.TestCase):
    def test_v04_gates_fail_closed_on_unknown_and_rank_uses_tiers(self):
        c = candidate("c1")
        unknown = qualify_v04(c, now="2026-01-01T00:10:00Z", facts=QualificationFacts())
        self.assertEqual(unknown.action, "PASS")
        facts = QualificationFacts(**{field: True for field in QualificationFacts.__dataclass_fields__})
        self.assertEqual(qualify_v04(c, now="2026-01-01T00:10:00Z", facts=facts).action, "PASS")
        low = candidate("c2", odds="2.80", probability="0.90", tier="1.0u")
        high = candidate("c3", odds="1.55", probability="0.60", tier="2.0u")
        decision = lambda item: SelectionDecision(item.candidate_id, "QUALIFY", (), digest("q"))
        ranked = rank_qualified([(low, decision(low)), (high, decision(high))])
        self.assertEqual([item.candidate_id for item in ranked], ["c3", "c2"])

    def test_candidate_run_retention_and_non_quota_summary(self):
        with scratch_directory() as tmp:
            store = CandidateRunStore(tmp / "runs.jsonl")
            store.append(CandidateRunRecord("run", "c1", "2026-01-01T00:00:00Z", "qualified", "PASS", near_miss=True))
            self.assertEqual(store.verify(), 1)
        summary = SearchCoverageSummary("run", "2026-09-19", 4, 3, 3, 3, 3, 14, (("PASS_PRICE_SANITY_FAIL", 1),), 1, (("football", 3),))
        self.assertTrue(summary.is_above_nominal_range())
        self.assertFalse(summary.to_dict()["targets_are_quota_or_cap"])

    def test_selected_set_calibration_and_pass_reasons_are_aggregated(self):
        rows = [
            SelectionObservation("c1", "0.8", 1, True, True, "normal", "supported", "event-1"),
            SelectionObservation("c2", "0.2", 0, False, False, "normal", "supported", "event-1", "PASS_PRICE_SANITY_FAIL"),
            SelectionObservation("c3", "0.7", 1, False, True, "exceptional", "supported", "event-2", "PASS_CORRELATION_LIMIT"),
        ]
        report = evaluate_selection_policy(rows, policy_hash=digest("p"), minimum_cell_size=1)
        self.assertEqual(report.all_candidates.n_observations, 3)
        self.assertEqual(report.qualified_candidates.n_observations, 2)
        self.assertEqual(report.selected_candidates.n_observations, 1)
        self.assertEqual(report.pass_count, 2)
        self.assertEqual(report.dependence_groups, 2)

    def test_risk_counts_pending_and_unknown_and_approvals_are_single_use(self):
        with scratch_directory() as tmp:
            audit = RiskAuditLog(tmp / "risk.jsonl")
            policy = PolicySet()
            bankrolls = BankrollSnapshotStore(tmp / "bankroll.jsonl")
            initial = BankrollSnapshot.create(bankroll="100", captured_at="2026-01-01T00:00:00Z", rebase_reason="initial")
            bankrolls.append(initial)
            safety = SafetyStateStore(tmp / "safety.jsonl")
            safety.append(SafetyState.create(kill_switch_active=False, recorded_at="2026-01-01T00:00:00Z", reason="test"))
            qualifications = QualificationRecordStore(tmp / "qualifications.jsonl")
            q1 = risk_qualification(
                qualifications, policy, candidate_hash=digest("1"), tier="2.0u",
                candidate_id="c1",
            )
            q2 = risk_qualification(
                qualifications, policy, candidate_hash=digest("2"), tier="2.0u",
                candidate_id="c2",
            )
            engine = RiskEngine(policy=policy, bankrolls=bankrolls, qualifications=qualifications, safety=safety, audit_log=audit)
            self.assertEqual(engine.rebase("110", captured_at="2026-01-01T00:02:00Z", scheduled_weekly=True, drawdown_triggered=False).direction, "upward")
            h1, h2 = q1.candidate_decision_hash, q2.candidate_decision_hash
            current = bankrolls.current()
            decision = engine.approve(RiskRequest(h1, q1.qualification_record_id, current.snapshot_id, BetSide.BACK, "2.00", "2026-01-01T00:03:00Z", ("cluster-1",)))
            self.assertTrue(decision.passed)
            self.assertEqual(engine.consume_for_order(decision.approval_id, order_id="order-1", consumed_at="2026-01-01T00:04:00Z").status, "CONSUMED")
            with self.assertRaises(ValueError):
                engine.consume_for_order(decision.approval_id, order_id="order-2", consumed_at="2026-01-01T00:05:00Z")
            engine.record_exposure(Exposure("x", digest("3"), "1", ExposureState.UNKNOWN), recorded_at="2026-01-01T00:05:00Z")
            blocked = engine.approve(RiskRequest(h2, q2.qualification_record_id, current.snapshot_id, BetSide.BACK, "2.00", "2026-01-01T00:06:00Z"))
            self.assertFalse(blocked.passed)
            self.assertEqual(audit.verify(), 3)

    def test_paper_order_idempotency_and_unknown_reconciliation(self):
        with scratch_directory() as tmp:
            fixture = build_risk(tmp / "risk")
            approval = fixture["engine"].approve(risk_request(fixture))
            markets = ExecutionMarketStateStore(tmp / "markets.jsonl")
            markets.append(ExecutionMarketSnapshot.create(candidate_decision_hash=fixture["candidate_hash"], observed_at="2026-01-01T00:11:00Z", market_open=True, executable_odds="2.00", available_liquidity="100"))
            refreshes = CriticalEvidenceRefreshStore(tmp / "refreshes.jsonl")
            refreshes.append(CriticalEvidenceRefresh(fixture["candidate_hash"], "2026-01-01T00:11:00Z", True, True))
            class Active:
                def is_active(self, candidate_decision_hash, at):
                    return True
            adapter = PaperExecutionAdapter(tmp / "orders.jsonl", risk=fixture["engine"], markets=markets, refreshes=refreshes, strategy_view=Active())
            intent = OrderIntent(fixture["candidate_hash"], "idem-1", BetSide.BACK, approval.approved_stake, "2.00", approval.approval_id, "2026-01-01T00:12:00Z")
            adapter.create_intent(intent)
            self.assertEqual(adapter.create_intent(intent).state, OrderState.ORDER_INTENT_CREATED)
            adapter.bind_risk("idem-1", bound_at="2026-01-01T00:13:00Z")
            result = adapter.recertify("idem-1", at="2026-01-01T00:14:00Z")
            self.assertFalse(result.passed)
            self.assertTrue(result.requires_new_candidate)
            before = len(adapter._audit.records())
            with self.assertRaises(RegistryConflict):
                adapter.transition("idem-1", OrderState.SUBMISSION_PENDING, occurred_at="2026-01-01T00:14:00Z")
            self.assertEqual(len(adapter._audit.records()), before)

            safe = build_execution(tmp / "timeout")
            safe_adapter = safe["adapter"]
            safe_adapter.create_intent(safe["intent"])
            safe_adapter.bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
            safe_adapter.transition("key-a", OrderState.SUBMISSION_PENDING, occurred_at="2026-01-01T00:14:00Z")
            unknown = safe_adapter.mark_submission_timeout("key-a", occurred_at="2026-01-01T00:15:00Z")
            self.assertEqual(unknown.state, OrderState.RECONCILIATION_REQUIRED)
            result = safe_adapter.recertify("key-a", at="2026-01-01T00:16:00Z")
            self.assertFalse(result.passed)


class V04ProtectedLedgerQuotaTests(unittest.TestCase):
    def test_protected_attempt_is_consumed_on_suppression_and_failure(self):
        frame = DecisionFrame("d1", "e1", "2026-01-01T00:00:00Z", (DecisionFact("signal", 1, "2025-12-31T23:00:00Z", "2025-12-31T23:01:00Z", ref()),), "d1", digest("c"))
        label = FutureOutcomeLabel("l1", "e1", 1, "2026-01-01T01:00:00Z", ref(), "label-v1")
        campaign = ProtectedCampaign("camp", "family", 2, digest("e"), minimum_cell_size=2)
        attempts = ProtectedAttemptLedger()
        boundary = LegacyUnsafeProtectedEvaluationBoundary(
            campaign, [frame], [label], attempts, legacy_test_only=True
        )
        certificate = boundary.run(EvaluationRequest("camp", "strategy", digest("f"), "d1", digest("e")), lambda _: "0.5")
        self.assertEqual(certificate.metrics["suppressed"], "true")
        failing_campaign = ProtectedCampaign("camp-fail", "family", 1, digest("e"), minimum_cell_size=1)
        failing_boundary = LegacyUnsafeProtectedEvaluationBoundary(
            failing_campaign, [frame], [label], attempts, legacy_test_only=True
        )
        with self.assertRaises(Exception):
            failing_boundary.run(EvaluationRequest("camp-fail", "strategy", digest("f"), "d1", digest("e")), lambda _: 2)
        boundary.run(EvaluationRequest("camp", "strategy", digest("f"), "d1", digest("e")), lambda _: "0.5")
        with self.assertRaises(Exception):
            boundary.run(EvaluationRequest("camp", "strategy", digest("f"), "d1", digest("e")), lambda _: "0.5")

    def test_ledger_is_source_of_truth_and_quota_fails_closed(self):
        with scratch_directory() as tmp:
            ledger = SettlementLedger(tmp / "ledger.jsonl")
            fill = FillRecord("fill-1", "order-1", digest("1"), BetSide.BACK, "2.00", "2.50", "2026-01-01T00:00:00Z")
            ledger.record_fill(fill)
            event = ledger.settle(event_id="settle-1", fill_id="fill-1", kind=SettlementKind.WIN, occurred_at="2026-01-01T02:00:00Z")
            self.assertEqual(event.pnl, "2.50")
            corrected = ledger.settle(event_id="settle-2", fill_id="fill-1", kind=SettlementKind.LOSS, occurred_at="2026-01-01T03:00:00Z", correction_of="settle-1")
            self.assertEqual(corrected.pnl, "-5.00")
            self.assertEqual(ledger.total_pnl(), "-2.50")
            self.assertEqual(ledger.verify(), 3)
        with scratch_directory() as tmp:
            policy = QuotaPolicy.test_fixture(
                QuotaInterpretation.A,
                provider_monthly_allowance=5,
                normal_monthly_budget=4,
                reserve_units=1,
                daily_billable_budget=2,
            )
            cache_store = VerifiedCacheStore(tmp / "cache-authority")
            quota = QuotaLedger(
                tmp / "quota.jsonl", policy=policy, allow_test_policy=True,
                cache_store=cache_store,
            )
            self.assertTrue(quota.request(request_id="1", occurred_at="2026-01-01T00:00:00Z").allowed)
            self.assertTrue(quota.request(request_id="2", occurred_at="2026-01-01T00:01:00Z").allowed)
            self.assertFalse(quota.request(request_id="3", occurred_at="2026-01-01T00:02:00Z").allowed)
            request_hash = digest("8")
            cache = cache_store.publish(
                b"current-event", cache_key="event-current",
                provider_request_hash=request_hash, provider_id=policy.provider_id,
                quota_policy_digest=policy.policy_digest,
                captured_at="2026-01-01T00:00:00Z",
                expires_at="2026-01-01T01:00:00Z",
            )
            self.assertTrue(
                quota.request(
                    request_id="4",
                    occurred_at="2026-01-01T00:03:00Z",
                    cache=cache,
                    provider_request_hash=request_hash,
                ).allowed
            )
