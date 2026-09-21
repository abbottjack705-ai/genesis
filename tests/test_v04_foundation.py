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
    ModeController,
    OrderIntent,
    OrderState,
    PaperExecutionAdapter,
    recertify,
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
from genesis.protected import ProtectedAttemptLedger, ProtectedCampaign, ProtectedEvaluationBoundary
from genesis.evaluation import EvaluationRequest
from genesis.selection_evaluation import SelectionObservation, evaluate_selection_policy
from genesis.labels import DecisionFact, DecisionFrame, FutureOutcomeLabel
from genesis.provenance import AvailabilityClass, ProvenanceRef
from genesis.quota import QuotaLedger, QuotaPolicy
from genesis.risk import Exposure, ExposureState, RiskAuditLog, RiskEngine
from genesis.runtime import CostLedger, CostLedgerEntry
from genesis.selection import QualificationFacts, qualify_v04, rank_qualified
from ._support import scratch_directory


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
            store = PITStore(tmp / "pit.jsonl")
            store.append(BitemporalRecord("r1", "e1", "s1", digest(), "2025-12-31T23:00:00Z", None, "2025-12-31T23:01:00Z", "2025-12-31T23:02:00Z", "2025-12-31T23:00:00Z"))
            self.assertEqual(len(store.as_of_query("e1", "2026-01-01T00:00:00Z", capabilities=capabilities)), 1)
            store.append(BitemporalRecord("r2", "e2", "s1", digest("d"), "2026-01-01T00:00:00Z", None, "2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z", "2026-01-01T00:00:00Z"))
            self.assertEqual(store.as_of_query("e2", "2026-01-01T00:01:30Z", capabilities=capabilities), ())
            with self.assertRaises(SourceUnavailable):
                store.as_of_query("e1", "2026-01-01T00:00:00Z", source_id="unknown", capabilities=capabilities)

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
            "strategy_version", "strategy_config_hash", "odds_profile_hash", "sport_adapter_version", "event_id", "market_id", "selection_id", "side", "evidence_cutoff_ts", "candidate_decision_ts", "evidence_pack_hash", "feature_manifest_hash", "model_artifact_hash", "calibration_artifact_hash", "gate_policy_hash"))}
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
        store = PITStore()
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
        controller = ModeController()
        with self.assertRaises(PermissionError):
            controller.transition(OperationalMode.PAPER)
        auth = AuthorizationArtifact("auth-1", "human", OperationalMode.PAPER, "2026-01-01T00:00:00Z", digest("p"))
        self.assertEqual(controller.transition(auth.mode, auth), auth.mode)
        with self.assertRaises(ValueError):
            controller.transition(OperationalMode.LIVE, auth)

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
        self.assertEqual(qualify_v04(c, now="2026-01-01T00:10:00Z", facts=facts).action, "QUALIFY")
        low = candidate("c2", odds="2.80", probability="0.90", tier="1.0u")
        high = candidate("c3", odds="1.55", probability="0.60", tier="2.0u")
        decision = lambda item: qualify_v04(item, now="2026-01-01T00:10:00Z", facts=facts)
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
            engine = RiskEngine(audit_log=audit)
            self.assertEqual(engine.rebase("100", "110", scheduled_weekly=True, drawdown_triggered=False).direction, "upward")
            h1, h2 = digest("1"), digest("2")
            decision = engine.approve(candidate_decision_hash=h1, bankroll="100", requested_liability="5", correlation_cluster_ids=("cluster-1",))
            self.assertTrue(decision.passed)
            self.assertEqual(engine.consume(decision.approval_id).status, "CONSUMED")
            with self.assertRaises(ValueError):
                engine.consume(decision.approval_id)
            blocked = engine.approve(candidate_decision_hash=h2, bankroll="100", requested_liability="1", existing=(Exposure("x", digest("3"), "1", ExposureState.UNKNOWN),))
            self.assertFalse(blocked.passed)
            self.assertEqual(audit.verify(), 2)

    def test_paper_order_idempotency_and_unknown_reconciliation(self):
        adapter = PaperExecutionAdapter()
        intent = OrderIntent(digest("1"), "idem-1", "2.50", "2.00", "2026-01-01T00:00:00Z")
        adapter.create_intent(intent)
        self.assertEqual(adapter.create_intent(intent).state, OrderState.ORDER_INTENT_CREATED)
        adapter.transition("idem-1", OrderState.RISK_APPROVED)
        adapter.transition("idem-1", OrderState.SUBMISSION_PENDING)
        unknown = adapter.mark_submission_timeout("idem-1")
        self.assertEqual(unknown.state, OrderState.RECONCILIATION_REQUIRED)
        result = recertify(strategy_active=True, candidate_not_expired=True, refresh=CriticalEvidenceRefresh("2026-01-01T00:00:00Z", True, True), market_open=True, executable_price_ok=True, liquidity_ok=True, risk_ok=True, no_kill_condition=True, no_duplicate_intent=True, no_unknown_state=True)
        self.assertFalse(result.passed)
        self.assertTrue(result.requires_new_candidate)


class V04ProtectedLedgerQuotaTests(unittest.TestCase):
    def test_protected_attempt_is_consumed_on_suppression_and_failure(self):
        frame = DecisionFrame("d1", "e1", "2026-01-01T00:00:00Z", (DecisionFact("signal", 1, "2025-12-31T23:00:00Z", "2025-12-31T23:01:00Z", ref()),), "d1", digest("c"))
        label = FutureOutcomeLabel("l1", "e1", 1, "2026-01-01T01:00:00Z", ref(), "label-v1")
        campaign = ProtectedCampaign("camp", "family", 2, digest("e"), minimum_cell_size=2)
        attempts = ProtectedAttemptLedger()
        boundary = ProtectedEvaluationBoundary(campaign, [frame], [label], attempts)
        certificate = boundary.run(EvaluationRequest("camp", "strategy", digest("f"), "d1", digest("e")), lambda _: "0.5")
        self.assertEqual(certificate.metrics["suppressed"], "true")
        failing_campaign = ProtectedCampaign("camp-fail", "family", 1, digest("e"), minimum_cell_size=1)
        failing_boundary = ProtectedEvaluationBoundary(failing_campaign, [frame], [label], attempts)
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
        quota = QuotaLedger(policy=QuotaPolicy(daily_billable_limit=2, monthly_billable_limit=5, monthly_reserve=1))
        self.assertTrue(quota.request(request_id="1", occurred_at="2026-01-01T00:00:00Z").allowed)
        self.assertTrue(quota.request(request_id="2", occurred_at="2026-01-01T00:01:00Z").allowed)
        self.assertFalse(quota.request(request_id="3", occurred_at="2026-01-01T00:02:00Z").allowed)
        self.assertTrue(quota.request(request_id="4", occurred_at="2026-01-01T00:03:00Z", cached=True).allowed)
