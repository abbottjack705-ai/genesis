from __future__ import annotations

import unittest
from dataclasses import replace

import genesis.selection as selection_module
from genesis.canonical import CandidateBet, EvidenceStatus, MarketSide, ResearchEvidence
from genesis.capabilities import MarketCapability, MarketCapabilityRegistry
from genesis.decision import decision_hash_for_candidate
from genesis.evidence import EvidenceStore, StructuredEvidenceStore
from genesis.evidence_pack import EvidencePack, EvidencePackStore
from genesis.pit import (
    BitemporalRecord,
    OperationalStatus,
    PITStore,
    SourceCapability,
    SourceCapabilityRegistry,
)
from genesis.policy import PolicySet, matched_odds_profile, odds_profile_hash, parse_tier
from genesis.provenance import (
    AvailabilityClass,
    ProvenanceRef,
    SourceContract,
    SourceContractRegistry,
)
from genesis.reasons import ReasonCode
from genesis.registry import (
    StrategyArtifact,
    StrategyDecisionContract,
    StrategyLifecycle,
    StrategyRegistry,
)
from genesis.selection import (
    FailClosedExecutionReadView,
    FailClosedRiskReadView,
    QualificationAuthority,
    QualificationFacts,
    QualificationRecordStore,
    SelectionDecision,
    qualify_v04,
    rank_qualified,
)
from genesis.time import iso_utc
from ._support import scratch_directory


def digest(character: str) -> str:
    return character * 64


class ReadyRiskView:
    def risk_ok(self, candidate):
        return True

    def correlation_ok(self, candidate):
        return True


class ReadyExecutionView:
    def liquidity_ok(self, candidate):
        return True

    def execution_available(self, candidate):
        return True

    def no_duplicate_order(self, candidate):
        return True

    def no_kill_condition(self, candidate):
        return True


def build_fixture(
    tmp,
    *,
    paper_at: str = "2026-01-01T00:05:00Z",
    market_recorded_at: str = "2026-01-01T00:04:00Z",
    fail_closed_views: bool = False,
    approved_tiers: tuple[str, ...] = ("1.0u", "1.5u", "2.0u", "2.5u", "3.0u"),
    comparability_group_id: str = "football-match-winner-v1",
):
    policy = PolicySet()
    source_contracts = SourceContractRegistry(tmp / "source-contracts.jsonl")
    source_contracts.register(
        SourceContract(
            "source-contract-v1",
            "synthetic",
            "fixture",
            "synthetic://*",
            AvailabilityClass.PROSPECTIVE_CAPTURED,
            "seconds",
            "parse_ready_at",
            "parser-v1",
            "synthetic",
            supports_prospective_capture=True,
        )
    )
    evidence = EvidenceStore(tmp / "evidence", contracts=source_contracts)
    observation = evidence.publish(
        b'{"weather":"dry"}',
        contract_id="source-contract-v1",
        source_uri="synthetic://weather/1",
        provider="synthetic",
        source_type="fixture",
        retrieved_at="2026-01-01T00:01:00Z",
        parse_ready_at="2026-01-01T00:01:01Z",
        parser_version="parser-v1",
        content_type="application/json",
        licensing_note="synthetic",
        availability_class=AvailabilityClass.PROSPECTIVE_CAPTURED,
    )
    source_ref = ProvenanceRef(
        observation.artifact_hash,
        observation.contract_id,
        observation.source_uri,
        observation.retrieved_at,
        observation.parse_ready_at,
        observation.availability_class,
        observation.parser_version,
        "$.weather",
        observation.observation_id,
    )
    research = ResearchEvidence(
        "research-1",
        "event-1",
        "weather",
        "dry",
        source_ref,
        "2026-01-01T00:00:00Z",
        observation.retrieved_at,
        EvidenceStatus.CONFIRMED,
        "2026-01-01T01:00:00Z",
        "extract-v1",
        (),
        observation.parse_ready_at,
        "$.weather",
        digest("a"),
    )
    structured = StructuredEvidenceStore(tmp / "structured", evidence=evidence)
    structured_hash = structured.publish(research)
    source_capabilities = SourceCapabilityRegistry(tmp / "source-capabilities.jsonl")
    source_capabilities.register(
        SourceCapability(
            "source-1",
            "synthetic",
            "fixture",
            "free",
            "test",
            "prospective",
            "verified",
            "append-only",
            "fixture",
            "7/day",
            "schema-v1",
            OperationalStatus.READY,
            "2026-01-01T00:00:00Z",
            "v1",
        )
    )
    pit = PITStore(tmp / "pit.jsonl", capabilities=source_capabilities)
    pit.append(
        BitemporalRecord(
            "pit-1",
            "event-1",
            "source-1",
            observation.artifact_hash,
            "2026-01-01T00:01:00Z",
            None,
            observation.retrieved_at,
            observation.parse_ready_at,
            "2026-01-01T00:00:00Z",
        )
    )

    # The sealed baseline has no manifest owner. Keep its fixture importable
    # for independent RED replay; current S3a fixtures publish an exact object.
    try:
        from genesis.feature_manifest import (
            FeatureInputManifestStore, SourceInputBindingStore,
            identity_transform_hash,
        )
    except ModuleNotFoundError:
        manifests = None
        feature_hash = digest("b")
    else:
        bindings = SourceInputBindingStore(tmp / "source-bindings.jsonl")
        bindings.register(
            source_id="source-1", source_contract_id="source-contract-v1",
            provider="synthetic", approval_reference="synthetic-test-only",
        )
        manifests = FeatureInputManifestStore(tmp / "feature-manifests", bindings=bindings)
        manifest_body = {
            "domain": "genesis.feature-input-manifest.v1",
            "schema_version": "feature-input-manifest-v1",
            "event_id": "event-1",
            "market_id": "market-1",
            "evidence_cutoff_ts": iso_utc("2026-01-01T00:02:00Z"),
            "required_inputs": [{
                "role": "feature", "input_key": "weather",
                "entity_id": "event-1", "event_id": "event-1",
                "market_id": "market-1", "source_id": "source-1",
                "source_contract_id": "source-contract-v1",
                "source_capability_version": "v1",
                "source_capability_record_hash": source_capabilities.log.records()[-1]["record_hash"],
                "raw_artifact_hash": observation.artifact_hash,
                "observation_id": observation.observation_id,
                "pit_record_id": "pit-1",
                "pit_record_hash": pit.log.records()[-1]["record_hash"],
                "field_id": "$.weather",
                "transform_artifact_hash": identity_transform_hash("$.weather"),
            }],
            "structured_evidence_hashes": [structured_hash],
        }
        feature_hash = manifests.publish(manifest_body)

    frozen_pack = EvidencePack.freeze(
        pack_id="pack-v2",
        evidence_cutoff_ts="2026-01-01T00:02:00Z",
        frozen_at="2026-01-01T00:03:00Z",
        source_artifact_hashes=(observation.artifact_hash,),
        extractor_versions=("extract-v1",),
        prompt_schema_hash=digest("a"),
        contradiction_links=(),
        freshness_state=("fresh",),
        feature_manifest_hash=feature_hash,
        structured_evidence_hashes=(structured_hash,),
    )
    packs = EvidencePackStore(tmp / "packs", structured_evidence=structured)
    packs.freeze(frozen_pack)

    market_capabilities = MarketCapabilityRegistry(tmp / "market-capabilities.jsonl")
    market = MarketCapability(
        "football-match-winner-cap-v1",
        "football",
        "match_winner",
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        "v1",
        market_recorded_at,
    )
    market_capabilities.register(market)

    config_hash = digest("c")
    model_hash = digest("d")
    calibration_hash = digest("e")
    gate_hash = digest("f")
    strategies = StrategyRegistry(tmp / "strategies.jsonl")
    strategies.register(
        StrategyArtifact(
            "strategy-1",
            "v1",
            StrategyLifecycle.IDEA,
            digest("1"),
            config_hash,
            model_hash,
            "football-match-winner",
            "2026-01-01T00:00:00Z",
        )
    )
    for lifecycle, occurred_at in (
        (StrategyLifecycle.EXPLORATION, "2026-01-01T00:01:00Z"),
        (StrategyLifecycle.WALK_FORWARD, "2026-01-01T00:02:00Z"),
        (StrategyLifecycle.PROTECTED, "2026-01-01T00:03:00Z"),
        (StrategyLifecycle.PROSPECTIVE_SHADOW, "2026-01-01T00:04:00Z"),
        (StrategyLifecycle.PAPER, paper_at),
    ):
        strategies.transition(
            "strategy-1", "v1", lifecycle, occurred_at=occurred_at
        )

    profile_hash = odds_profile_hash(policy, matched_odds_profile(policy, "2.00"))
    contract = StrategyDecisionContract.create(
        strategy_id="strategy-1",
        strategy_version="v1",
        strategy_config_hash=config_hash,
        odds_profile_hash=profile_hash,
        sport_adapter_version="synthetic-offline-v0.4",
        market_capability_id=market.capability_id,
        required_lifecycle=StrategyLifecycle.PAPER,
        support_region="football-match-winner",
        comparability_group_id=comparability_group_id,
        model_artifact_hash=model_hash,
        calibration_artifact_hash=calibration_hash,
        feature_manifest_hash=feature_hash,
        gate_policy_hash=gate_hash,
        approved_tier_policy_id=policy.risk.version,
        approved_tiers=approved_tiers,
        created_at="2026-01-01T00:04:30Z",
    )
    strategies.register_decision_contract(contract)

    candidate = CandidateBet(
        candidate_id="candidate-1",
        strategy_id="strategy-1",
        strategy_version="v1",
        sport="football",
        event_id="event-1",
        market_id="market-1",
        selection_id="selection-1",
        side=MarketSide.BACK,
        requested_odds_min="1.50",
        requested_odds_max="3.00",
        observed_odds="2.00",
        model_probability="0.62",
        conservative_probability="0.60",
        model_version="model-v1",
        evidence_pack_id=frozen_pack.pack_hash,
        decision_at="2026-01-01T00:10:00Z",
        expires_at="2026-01-01T01:00:00Z",
        evidence_complete=True,
        candidate_version="candidate-v2",
        evidence_cutoff_ts=frozen_pack.evidence_cutoff_ts,
        market_family="match_winner",
        strategy_tier="2.0u",
        model_artifact_hash=model_hash,
        calibration_artifact_hash=calibration_hash,
        feature_manifest_hash=feature_hash,
        gate_policy_hash=gate_hash,
        config_digest=config_hash,
        strategy_decision_contract_hash=contract.contract_hash,
        comparability_group_id=comparability_group_id,
    )
    candidate = replace(
        candidate,
        candidate_decision_hash=decision_hash_for_candidate(
            candidate,
            strategy_config_hash=config_hash,
            odds_profile_hash=profile_hash,
            sport_adapter_version=contract.sport_adapter_version,
        ),
    )
    records = QualificationRecordStore(tmp / "qualifications.jsonl")
    authority_dependencies = dict(
        strategies=strategies,
        market_capabilities=market_capabilities,
        pit=pit,
        evidence_packs=packs,
        structured_evidence=structured,
        policy=policy,
        risk_view=FailClosedRiskReadView() if fail_closed_views else ReadyRiskView(),
        execution_view=(
            FailClosedExecutionReadView() if fail_closed_views else ReadyExecutionView()
        ),
        qualification_records=records,
    )
    if manifests is not None:
        authority_dependencies["feature_manifests"] = manifests
    authority = QualificationAuthority(**authority_dependencies)
    return {
        "authority": authority,
        "candidate": candidate,
        "contract": contract,
        "strategies": strategies,
        "records": records,
        "policy": policy,
        "profile_hash": profile_hash,
        "feature_manifests": manifests,
        "observation": observation,
    }


class R3QualificationAuthorityTests(unittest.TestCase):
    def test_all_true_caller_facts_and_legacy_candidate_cannot_qualify(self):
        with scratch_directory() as tmp:
            fixture = build_fixture(tmp)
            legacy = replace(
                fixture["candidate"],
                candidate_version="candidate-v1",
                model_artifact_hash=None,
                calibration_artifact_hash=None,
                feature_manifest_hash=None,
                gate_policy_hash=None,
                strategy_decision_contract_hash=None,
                candidate_decision_hash=None,
            )
            facts = QualificationFacts(
                **{name: True for name in QualificationFacts.__dataclass_fields__}
            )
            self.assertEqual(
                qualify_v04(legacy, now="2026-01-01T00:11:00Z", facts=facts).action,
                "PASS",
            )
            self.assertEqual(
                fixture["authority"].evaluate(legacy, now="2026-01-01T00:11:00Z").action,
                "PASS",
            )
            self.assertEqual(fixture["records"].verify(), 0)

    def test_success_is_deterministic_and_persists_one_immutable_record(self):
        with scratch_directory() as tmp:
            fixture = build_fixture(tmp)
            first = fixture["authority"].evaluate(
                fixture["candidate"], now="2026-01-01T00:11:00Z"
            )
            second = fixture["authority"].evaluate(
                fixture["candidate"], now="2026-01-01T00:11:00Z"
            )
            self.assertEqual(first, second)
            self.assertEqual(first.action, "QUALIFY")
            self.assertIsNotNone(first.qualification_record_id)
            record = fixture["records"].get(first.qualification_record_id)
            self.assertEqual(record.approved_tier, "2.0u")
            self.assertEqual(record.candidate_decision_hash, fixture["candidate"].candidate_decision_hash)
            self.assertEqual(fixture["records"].verify(), 1)

    def test_missing_or_mismatched_identity_and_corrupt_pack_fail_without_record(self):
        with scratch_directory() as tmp:
            fixture = build_fixture(tmp)
            candidate = fixture["candidate"]
            variants = (
                replace(candidate, evidence_pack_id=digest("9")),
                replace(candidate, model_artifact_hash=digest("8")),
                replace(candidate, calibration_artifact_hash=None),
                replace(candidate, gate_policy_hash=digest("7")),
                replace(candidate, config_digest=digest("6")),
                replace(candidate, candidate_decision_hash=digest("5")),
            )
            decisions = [
                fixture["authority"].evaluate(item, now="2026-01-01T00:11:00Z")
                for item in variants
            ]
            self.assertTrue(all(item.action == "PASS" for item in decisions))
            multi_failure = replace(
                candidate, evidence_pack_id=digest("9"), model_artifact_hash=None
            )
            first = fixture["authority"].evaluate(
                multi_failure, now="2026-01-01T00:11:00Z"
            )
            second = fixture["authority"].evaluate(
                multi_failure, now="2026-01-01T00:11:00Z"
            )
            self.assertEqual(first.final_reason, second.final_reason)
            self.assertEqual(fixture["records"].verify(), 0)

    def test_corrupt_structured_evidence_makes_existing_pack_non_authoritative(self):
        with scratch_directory() as tmp:
            fixture = build_fixture(tmp)
            pack = fixture["authority"].evidence_packs.get(
                fixture["candidate"].evidence_pack_id
            )
            path = fixture["authority"].structured_evidence.root / (
                pack.structured_evidence_hashes[0] + ".json"
            )
            path.write_bytes(b"{}")
            decision = fixture["authority"].evaluate(
                fixture["candidate"], now="2026-01-01T00:11:00Z"
            )
            self.assertEqual(decision.action, "PASS")
            self.assertIn(ReasonCode.PASS_GATE_ERROR, decision.reason_codes)
            self.assertEqual(fixture["records"].verify(), 0)

    def test_lifecycle_and_market_capability_are_resolved_at_decision_time(self):
        with scratch_directory() as tmp:
            lifecycle = build_fixture(tmp / "lifecycle", paper_at="2026-01-01T00:20:00Z")
            decision = lifecycle["authority"].evaluate(
                lifecycle["candidate"], now="2026-01-01T00:11:00Z"
            )
            self.assertEqual(decision.final_reason, ReasonCode.PASS_STRATEGY_NOT_APPROVED)

            market = build_fixture(
                tmp / "market", market_recorded_at="2026-01-01T00:20:00Z"
            )
            decision = market["authority"].evaluate(
                market["candidate"], now="2026-01-01T00:11:00Z"
            )
            self.assertEqual(decision.final_reason, ReasonCode.PASS_DATA_CAPABILITY_NOT_READY)

    def test_required_dependencies_and_fail_closed_stage_views_cannot_be_bypassed(self):
        with scratch_directory() as tmp:
            fixture = build_fixture(tmp, fail_closed_views=True)
            decision = fixture["authority"].evaluate(
                fixture["candidate"], now="2026-01-01T00:11:00Z"
            )
            self.assertEqual(decision.action, "PASS")
            self.assertIn(ReasonCode.PASS_UNKNOWN_STATE, decision.reason_codes)
            with self.assertRaises(TypeError):
                QualificationAuthority(
                    strategies=fixture["strategies"],
                    market_capabilities=None,  # type: ignore[arg-type]
                    pit=fixture["authority"].pit,
                    evidence_packs=fixture["authority"].evidence_packs,
                    feature_manifests=fixture["feature_manifests"],
                    structured_evidence=fixture["authority"].structured_evidence,
                    policy=fixture["policy"],
                    risk_view=ReadyRiskView(),
                    execution_view=ReadyExecutionView(),
                    qualification_records=fixture["records"],
                )

    def test_authority_does_not_route_through_legacy_qualify(self):
        with scratch_directory() as tmp:
            fixture = build_fixture(tmp)
            original = selection_module.qualify
            try:
                selection_module.qualify = lambda *args, **kwargs: (_ for _ in ()).throw(
                    AssertionError("legacy route called")
                )
                decision = fixture["authority"].evaluate(
                    fixture["candidate"], now="2026-01-01T00:11:00Z"
                )
            finally:
                selection_module.qualify = original
            self.assertEqual(decision.action, "QUALIFY")

    def test_contract_material_changes_propagate_to_candidate_identity(self):
        with scratch_directory() as tmp:
            fixture = build_fixture(tmp)
            first = fixture["contract"]
            second = StrategyDecisionContract.create(
                **(
                    first.unsigned_dict()
                    | {"comparability_group_id": "different-comparability-group"}
                )
            )
            self.assertNotEqual(first.contract_hash, second.contract_hash)
            changed_candidate = replace(
                fixture["candidate"],
                strategy_decision_contract_hash=second.contract_hash,
                comparability_group_id=second.comparability_group_id,
            )
            changed_hash = decision_hash_for_candidate(
                changed_candidate,
                strategy_config_hash=second.strategy_config_hash,
                odds_profile_hash=second.odds_profile_hash,
                sport_adapter_version=second.sport_adapter_version,
            )
            self.assertNotEqual(fixture["candidate"].candidate_decision_hash, changed_hash)


class R3StrictTierTests(unittest.TestCase):
    def test_missing_malformed_unsupported_and_above_max_tiers_pass(self):
        with scratch_directory() as tmp:
            fixture = build_fixture(tmp)
            for value in (None, "", "garbage", "2.25u", "3.5u"):
                with self.subTest(value=value):
                    decision = fixture["authority"].evaluate(
                        replace(fixture["candidate"], strategy_tier=value),
                        now="2026-01-01T00:11:00Z",
                    )
                    self.assertEqual(decision.action, "PASS")
            self.assertEqual(fixture["records"].verify(), 0)

    def test_each_policy_tier_qualifies_when_the_strategy_contract_allows_it(self):
        with scratch_directory() as tmp:
            fixture = build_fixture(tmp)
            for value in ("1.0u", "1.5u", "2.0u", "2.5u", "3.0u"):
                with self.subTest(value=value):
                    self.assertEqual(parse_tier(value), parse_tier(value))
                    decision = fixture["authority"].evaluate(
                        replace(fixture["candidate"], strategy_tier=value),
                        now="2026-01-01T00:11:00Z",
                    )
                    self.assertEqual(decision.action, "QUALIFY")

    def test_contract_disallowed_tier_passes_and_rank_rejects_bypass(self):
        with scratch_directory() as tmp:
            fixture = build_fixture(tmp, approved_tiers=("1.0u",))
            self.assertEqual(
                fixture["authority"].evaluate(
                    fixture["candidate"], now="2026-01-01T00:11:00Z"
                ).action,
                "PASS",
            )
            forged = SelectionDecision(
                fixture["candidate"].candidate_id,
                "QUALIFY",
                (),
                digest("a"),
            )
            with self.assertRaises(ValueError):
                rank_qualified(
                    [(replace(fixture["candidate"], strategy_tier="garbage"), forged)]
                )


if __name__ == "__main__":
    unittest.main()
