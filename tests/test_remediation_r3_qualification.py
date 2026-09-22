from __future__ import annotations

import unittest
import json
from dataclasses import replace
from datetime import timedelta

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
from genesis.policy import PolicySet, canonical_decimal, matched_odds_profile, odds_profile_hash, parse_tier
from genesis.repro import canonical_json, sha256_bytes
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
from genesis.time import iso_utc, parse_utc
from ._support import SyntheticQualificationRecordStore as QualificationRecordStore, scratch_directory


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


class SyntheticS3Resolver:
    """Isolated fixture code; no production strategy/model/rule is approved."""

    def __init__(self, evidence: EvidenceStore, tier: str):
        self.evidence = evidence
        self.tier = tier
        self.artifact_hash = sha256_bytes(canonical_json({
            "domain": "genesis.synthetic-test-resolver.v1", "tier": tier,
            "model": "dry-weather-fixture-v1", "expiry": "pack-freeze+57-minutes",
        }))

    def reproduce(self, *, binding, manifest, pack, contract, policy):
        from genesis.decision_output import rule_binding_hash

        raw = json.loads(self.evidence.get_bytes(
            manifest["required_inputs"][0]["raw_artifact_hash"]
        ))
        profile = matched_odds_profile(policy, raw["odds"])
        decision_at = parse_utc(pack.frozen_at) + timedelta(minutes=7)
        expires_at = decision_at + timedelta(minutes=50)
        if raw["weather"] != "dry":
            raise ValueError("synthetic model has no support outside dry weather")
        return {
            "domain": "genesis.decision-output.v1",
            "schema_version": "decision-output-v1",
            "feature_manifest_hash": pack.feature_manifest_hash,
            "evidence_pack_hash": pack.pack_hash,
            "strategy_decision_contract_hash": contract.contract_hash,
            "strategy_config_hash": contract.strategy_config_hash,
            "odds_profile_hash": contract.odds_profile_hash,
            "sport_adapter_version": contract.sport_adapter_version,
            "market_capability_id": contract.market_capability_id,
            "model_artifact_hash": contract.model_artifact_hash,
            "calibration_artifact_hash": contract.calibration_artifact_hash,
            "gate_policy_hash": contract.gate_policy_hash,
            "model_runner_hash": binding["model_runner_hash"],
            "calibration_runner_hash": binding["calibration_runner_hash"],
            "tier_rule_hash": binding["tier_rule_hash"],
            "expiry_rule_hash": binding["expiry_rule_hash"],
            "resolver_binding_hash": rule_binding_hash(binding),
            "strategy_id": contract.strategy_id,
            "strategy_version": contract.strategy_version,
            "model_version": "model-v1",
            "sport": "football",
            "market_family": "match_winner",
            "event_id": raw["event_id"],
            "market_id": raw["market_id"],
            "selection_id": raw["selection_id"],
            "side": raw["side"],
            "evidence_cutoff_ts": iso_utc(pack.evidence_cutoff_ts),
            "decision_at": iso_utc(decision_at),
            "model_probability": "0.62",
            "calibrated_probability": "0.61",
            "conservative_probability": "0.6",
            "model_support_status": "supported",
            "calibration_status": "supported",
            "uncertainty_status": "supported",
            "critical_uncertainty_flags": [],
            "support_region_id": contract.support_region,
            "observed_odds": raw["odds"],
            "requested_odds_min": canonical_decimal(profile.minimum),
            "requested_odds_max": canonical_decimal(profile.maximum),
            "approved_tier": self.tier,
            "expires_at": iso_utc(expires_at),
            "comparability_group_id": contract.comparability_group_id,
            "selection_dependency_group": None,
            "correlation_cluster_ids": [],
            "meeting_id": None, "competition_id": None,
            "participant_ids": [], "shared_evidence_ids": [],
        }


def build_fixture(
    tmp,
    *,
    paper_at: str = "2026-01-01T00:05:00Z",
    market_recorded_at: str = "2026-01-01T00:04:00Z",
    fail_closed_views: bool = False,
    approved_tiers: tuple[str, ...] = ("1.0u", "1.5u", "2.0u", "2.5u", "3.0u"),
    comparability_group_id: str = "football-match-winner-v1",
    synthetic_tier: str = "2.0u",
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
        b'{"event_id":"event-1","market_id":"market-1","selection_id":"selection-1","side":"back","odds":"2","weather":"dry"}',
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
                "role": "feature", "input_key": name,
                "entity_id": "event-1", "event_id": "event-1",
                "market_id": "market-1", "source_id": "source-1",
                "source_contract_id": "source-contract-v1",
                "source_capability_version": "v1",
                "source_capability_record_hash": source_capabilities.log.records()[-1]["record_hash"],
                "raw_artifact_hash": observation.artifact_hash,
                "observation_id": observation.observation_id,
                "pit_record_id": "pit-1",
                "pit_record_hash": pit.log.records()[-1]["record_hash"],
                "field_id": f"$.{name}",
                "transform_artifact_hash": identity_transform_hash(f"$.{name}"),
            } for name in ("event_id", "market_id", "odds", "selection_id", "side", "weather")],
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
        requested_odds_min="1.5",
        requested_odds_max="3",
        observed_odds="2",
        model_probability="0.62",
        conservative_probability="0.6",
        model_version="model-v1",
        evidence_pack_id=frozen_pack.pack_hash,
        decision_at="2026-01-01T00:10:00Z",
        expires_at="2026-01-01T01:00:00Z",
        evidence_complete=True,
        candidate_version="candidate-v2",
        evidence_cutoff_ts=frozen_pack.evidence_cutoff_ts,
        market_family="match_winner",
        strategy_tier=synthetic_tier,
        model_artifact_hash=model_hash,
        calibration_artifact_hash=calibration_hash,
        feature_manifest_hash=feature_hash,
        gate_policy_hash=gate_hash,
        config_digest=config_hash,
        strategy_decision_contract_hash=contract.contract_hash,
        comparability_group_id=comparability_group_id,
        model_support_status="supported",
        calibration_status="supported",
        uncertainty_status="supported",
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
    try:
        from genesis.decision_output import (
            DecisionOutputStore, StrategyOutputRuleBindingStore,
            TrustedDecisionOutputAuthority, rule_binding_hash,
        )
        from genesis.decision import candidate_v3_decision_hash
    except ModuleNotFoundError:
        trusted_outputs = None
        output_body = None
        records = QualificationRecordStore(tmp / "qualifications.jsonl")
    else:
        class SyntheticTestOutputAuthority(TrustedDecisionOutputAuthority):
            def _validate_approval_reference(
                self, reference: str, *, binding_hash: str, decision_at: str,
            ) -> None:
                del binding_hash, decision_at
                if reference != "synthetic-test-only-not-operational":
                    raise ValueError("test resolver has no non-test approval")

        outputs = DecisionOutputStore(tmp / "decision-outputs")
        bindings = StrategyOutputRuleBindingStore(tmp / "strategy-output-bindings.jsonl")
        resolver = SyntheticS3Resolver(evidence, synthetic_tier)
        binding = {
            "domain": "genesis.strategy-output-rule-binding.v1",
            "schema_version": "strategy-output-rule-binding-v1",
            "strategy_decision_contract_hash": contract.contract_hash,
            "active_policy_digest": policy.digest,
            "approved_tier_policy_id": contract.approved_tier_policy_id,
            "model_artifact_hash": contract.model_artifact_hash,
            "calibration_artifact_hash": contract.calibration_artifact_hash,
            "feature_manifest_hash": contract.feature_manifest_hash,
            "gate_policy_hash": contract.gate_policy_hash,
            "model_runner_hash": digest("1"),
            "calibration_runner_hash": digest("2"),
            "tier_rule_hash": sha256_bytes(canonical_json({
                "domain": "synthetic-tier-rule", "tier": synthetic_tier,
            })),
            "expiry_rule_hash": digest("4"),
            "resolver_artifact_hash": resolver.artifact_hash,
            "scope": "PAPER",
            "valid_from": iso_utc("2026-01-01T00:00:00Z"),
            "valid_through": None,
            "human_approval_reference": "synthetic-test-only-not-operational",
        }
        bindings.register_approved(binding)
        output_body = resolver.reproduce(
            binding=binding,
            manifest=manifests.get(feature_hash),
            pack=frozen_pack,
            contract=contract,
            policy=policy,
        )
        output_hash = outputs.publish(output_body)
        candidate = replace(
            candidate,
            candidate_version="candidate-v3",
            decision_output_hash=output_hash,
            candidate_decision_hash=candidate_v3_decision_hash(
                strategy_decision_contract_hash=contract.contract_hash,
                feature_manifest_hash=feature_hash,
                evidence_pack_hash=frozen_pack.pack_hash,
                decision_output_hash=output_hash,
            ),
        )
        trusted_outputs = SyntheticTestOutputAuthority(
            outputs=outputs, bindings=bindings, resolver=resolver,
        )
        records = QualificationRecordStore(tmp / "qualifications.jsonl", outputs=outputs)
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
    if trusted_outputs is not None:
        authority_dependencies["decision_outputs"] = trusted_outputs
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
        "trusted_outputs": trusted_outputs,
        "output_body": output_body,
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
                decision_output_hash=None,
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
            for value in ("1.0u", "1.5u", "2.0u", "2.5u", "3.0u"):
                with self.subTest(value=value):
                    fixture = build_fixture(tmp / value.replace(".", "-"), synthetic_tier=value)
                    self.assertEqual(parse_tier(value), parse_tier(value))
                    decision = fixture["authority"].evaluate(
                        fixture["candidate"],
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
