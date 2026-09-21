"""Deterministic PASS-first qualification interface; no execution side effects."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Protocol

from .capabilities import MarketCapabilityRegistry
from .canonical import CandidateBet
from .decision import decision_hash_for_candidate
from .evidence import StructuredEvidenceStore
from .evidence_pack import EvidencePackStore
from .pit import PITStore
from .policy import (
    PolicySet,
    assess_price_sanity,
    matched_odds_profile,
    odds_profile_hash,
    parse_tier,
)
from .reasons import ReasonCode
from .registry import (
    AppendOnlyJsonl,
    RegistryConflict,
    StrategyDecisionContract,
    StrategyLifecycle,
    StrategyRegistry,
)
from .repro import canonical_json, sha256_bytes
from .time import iso_utc, parse_utc


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    reason: ReasonCode | None = None


@dataclass(frozen=True)
class SelectionDecision:
    candidate_id: str
    action: str
    gates: tuple[GateResult, ...]
    qualification_record_id: str | None = None

    @property
    def passed(self) -> bool:
        return self.action == "QUALIFY"

    @property
    def reason_codes(self) -> tuple[ReasonCode, ...]:
        return tuple(g.reason for g in self.gates if g.reason is not None)

    @property
    def final_reason(self) -> ReasonCode:
        return ReasonCode.QUALIFY_ALL_GATES_PASSED if self.passed else self.reason_codes[0]


@dataclass(frozen=True)
class QualificationFacts:
    """Explicit gate facts; None is UNKNOWN and therefore fails closed."""

    source_ready: bool | None = None
    identity_unambiguous: bool | None = None
    model_supported: bool | None = None
    calibration_supported: bool | None = None
    evidence_pack_frozen: bool | None = None
    evidence_reproducible: bool | None = None
    critical_evidence_fresh: bool | None = None
    no_contradiction: bool | None = None
    uncertainty_supported: bool | None = None
    odds_profile_ok: bool | None = None
    price_sanity_ok: bool | None = None
    liquidity_ok: bool | None = None
    risk_ok: bool | None = None
    correlation_ok: bool | None = None
    execution_available: bool | None = None
    strategy_approved: bool | None = None
    no_duplicate_order: bool | None = None
    no_kill_condition: bool | None = None


def _gate(name: str, value: bool | None, reason: ReasonCode) -> GateResult:
    if value is True:
        return GateResult(name, True, None)
    return GateResult(name, False, ReasonCode.PASS_UNKNOWN_STATE if value is None else reason)


def qualify_v04(candidate: CandidateBet, *, now: str, facts: QualificationFacts) -> SelectionDecision:
    """Legacy caller-facts path retained for audit replay; never authoritative."""

    del now, facts
    return SelectionDecision(
        candidate.candidate_id,
        "PASS",
        (GateResult("authoritative_qualification_required", False, ReasonCode.PASS_CONFIG_MISMATCH),),
    )


class QualificationRiskReadView(Protocol):
    def risk_ok(self, candidate: CandidateBet) -> bool | None: ...

    def correlation_ok(self, candidate: CandidateBet) -> bool | None: ...


class QualificationExecutionReadView(Protocol):
    def liquidity_ok(self, candidate: CandidateBet) -> bool | None: ...

    def execution_available(self, candidate: CandidateBet) -> bool | None: ...

    def no_duplicate_order(self, candidate: CandidateBet) -> bool | None: ...

    def no_kill_condition(self, candidate: CandidateBet) -> bool | None: ...


class FailClosedRiskReadView:
    """R3 production placeholder until the durable R5 owner replaces it."""

    def risk_ok(self, candidate: CandidateBet) -> None:
        del candidate
        return None

    def correlation_ok(self, candidate: CandidateBet) -> None:
        del candidate
        return None


class FailClosedExecutionReadView:
    """R3 production placeholder until the durable R6 owner replaces it."""

    def liquidity_ok(self, candidate: CandidateBet) -> None:
        del candidate
        return None

    def execution_available(self, candidate: CandidateBet) -> None:
        del candidate
        return None

    def no_duplicate_order(self, candidate: CandidateBet) -> None:
        del candidate
        return None

    def no_kill_condition(self, candidate: CandidateBet) -> None:
        del candidate
        return None


@dataclass(frozen=True)
class QualificationRecord:
    schema_version: str
    qualification_record_id: str
    candidate_id: str
    candidate_decision_hash: str
    strategy_id: str
    strategy_version: str
    strategy_decision_contract_hash: str
    approved_tier: str
    comparability_group_id: str
    active_policy_digest: str
    market_capability_id: str
    decision_at: str
    evaluated_at: str
    expires_at: str
    gate_results_digest: str
    action: str = "QUALIFY"

    def __post_init__(self) -> None:
        if self.schema_version != "qualification-record-v2" or self.action != "QUALIFY":
            raise ValueError("qualification records can only encode V2 QUALIFY authority")
        for name in (
            "qualification_record_id",
            "candidate_decision_hash",
            "strategy_decision_contract_hash",
            "active_policy_digest",
            "gate_results_digest",
        ):
            value = getattr(self, name)
            if len(value) != 64:
                raise ValueError(f"{name} must be a SHA-256 digest")
            int(value, 16)
        for value in (self.decision_at, self.evaluated_at, self.expires_at):
            parse_utc(value)
        if self.compute_id() != self.qualification_record_id:
            raise ValueError("qualification record ID mismatch")

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("qualification_record_id")
        for key in ("decision_at", "evaluated_at", "expires_at"):
            value[key] = iso_utc(value[key])
        return value

    def compute_id(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {"qualification_record_id": self.qualification_record_id, **self.unsigned_dict()}

    @classmethod
    def create(cls, **fields: Any) -> "QualificationRecord":
        normalized = dict(fields)
        normalized.setdefault("schema_version", "qualification-record-v2")
        normalized.setdefault("action", "QUALIFY")
        for key in ("decision_at", "evaluated_at", "expires_at"):
            normalized[key] = iso_utc(normalized[key])
        return cls(
            qualification_record_id=sha256_bytes(canonical_json(normalized)), **normalized
        )


class QualificationRecordStore:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    @staticmethod
    def _from_row(row: dict[str, Any]) -> QualificationRecord:
        fields = {key: row[key] for key in QualificationRecord.__dataclass_fields__}
        return QualificationRecord(**fields)

    def append(self, record: QualificationRecord) -> QualificationRecord:
        payload = {"record_type": "qualification_record", **record.to_dict()}

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            matches = [
                self._from_row(row)
                for row in rows
                if row.get("record_type") == "qualification_record"
                and row.get("qualification_record_id") == record.qualification_record_id
            ]
            if not matches:
                return payload
            if all(item == record for item in matches):
                return None
            raise RegistryConflict("qualification record ID conflict")

        self.log.transaction(build)
        return record

    def get(self, record_id: str) -> QualificationRecord:
        matches = [
            self._from_row(row)
            for row in self.log.records()
            if row.get("record_type") == "qualification_record"
            and row.get("qualification_record_id") == record_id
        ]
        if len(matches) != 1:
            raise RegistryConflict(f"unknown or ambiguous qualification record: {record_id}")
        return matches[0]

    def verify(self) -> int:
        rows = self.log.records()
        for row in rows:
            self._from_row(row)
        return len(rows)


class QualificationAuthority:
    """The only post-audit V0.4 qualification boundary."""

    def __init__(
        self,
        *,
        strategies: StrategyRegistry,
        market_capabilities: MarketCapabilityRegistry,
        pit: PITStore,
        evidence_packs: EvidencePackStore,
        structured_evidence: StructuredEvidenceStore,
        policy: PolicySet,
        risk_view: QualificationRiskReadView,
        execution_view: QualificationExecutionReadView,
        qualification_records: QualificationRecordStore,
    ):
        dependencies = {
            "strategies": strategies,
            "market_capabilities": market_capabilities,
            "pit": pit,
            "evidence_packs": evidence_packs,
            "structured_evidence": structured_evidence,
            "policy": policy,
            "risk_view": risk_view,
            "execution_view": execution_view,
            "qualification_records": qualification_records,
        }
        missing = [name for name, value in dependencies.items() if value is None]
        if missing:
            raise TypeError(f"qualification authority dependencies missing: {', '.join(missing)}")
        expected_types = (
            (strategies, StrategyRegistry),
            (market_capabilities, MarketCapabilityRegistry),
            (pit, PITStore),
            (evidence_packs, EvidencePackStore),
            (structured_evidence, StructuredEvidenceStore),
            (policy, PolicySet),
            (qualification_records, QualificationRecordStore),
        )
        if any(not isinstance(value, expected) for value, expected in expected_types):
            raise TypeError("qualification authority dependency has the wrong type")
        for owner, names in (
            (risk_view, ("risk_ok", "correlation_ok")),
            (
                execution_view,
                ("liquidity_ok", "execution_available", "no_duplicate_order", "no_kill_condition"),
            ),
        ):
            if any(not callable(getattr(owner, name, None)) for name in names):
                raise TypeError("qualification read view is incomplete")
        if evidence_packs.structured_evidence is not structured_evidence:
            raise ValueError("evidence pack and structured evidence authorities are not bound")
        self.strategies = strategies
        self.market_capabilities = market_capabilities
        self.pit = pit
        self.evidence_packs = evidence_packs
        self.structured_evidence = structured_evidence
        self.policy = policy
        self.risk_view = risk_view
        self.execution_view = execution_view
        self.qualification_records = qualification_records

    @staticmethod
    def _read(owner: Any, method: str, candidate: CandidateBet) -> bool | None:
        try:
            value = getattr(owner, method)(candidate)
        except Exception:
            return None
        return value if value in (True, False, None) else None

    def evaluate(self, candidate: CandidateBet, *, now: str) -> SelectionDecision:
        parse_utc(now)
        contract: StrategyDecisionContract | None = None
        artifact = None
        strategy_approved = False
        tier_valid = False
        try:
            if candidate.strategy_decision_contract_hash is None:
                raise ValueError("missing strategy decision contract hash")
            contract = self.strategies.get_decision_contract(
                candidate.strategy_decision_contract_hash
            )
            artifact = self.strategies.get(candidate.strategy_id, candidate.strategy_version)
            lifecycle = self.strategies.lifecycle_at(
                candidate.strategy_id, candidate.strategy_version, candidate.decision_at
            )
            tier = parse_tier(candidate.strategy_tier, policy=self.policy.risk)
            tier_valid = candidate.strategy_tier in contract.approved_tiers
            strategy_approved = (
                lifecycle == contract.required_lifecycle == StrategyLifecycle.PAPER
                and parse_utc(contract.created_at) <= parse_utc(candidate.decision_at)
                and artifact.config_digest == contract.strategy_config_hash
                and contract.strategy_id == candidate.strategy_id
                and contract.strategy_version == candidate.strategy_version
                and tier in self.policy.risk.stake_tiers
                and tier_valid
            )
        except Exception:
            strategy_approved = False

        market_ready = False
        source_ready = False
        if contract is not None:
            try:
                capability = self.market_capabilities.require_ready_at(
                    contract.market_capability_id, candidate.decision_at, live=False
                )
                market_ready = (
                    capability.sport == candidate.sport
                    and capability.market_family == (candidate.market_family or capability.market_family)
                )
                source_ready = bool(
                    self.pit.feature_view(
                        candidate.feature_manifest_hash or "missing-feature-manifest",
                        (candidate.event_id,),
                        candidate.decision_at,
                    )
                )
            except Exception:
                source_ready = False

        evidence_pack = None
        structured_rows: list[dict[str, Any]] = []
        pack_frozen = False
        evidence_reproducible = False
        try:
            if candidate.evidence_pack_id is None or len(candidate.evidence_pack_id) != 64:
                raise ValueError("candidate lacks an evidence-pack hash")
            evidence_pack = self.evidence_packs.get(candidate.evidence_pack_id)
            pack_frozen = True
            evidence_pack = self.evidence_packs.use_authoritatively(candidate.evidence_pack_id)
            structured_rows = [
                self.structured_evidence.verify(item)
                for item in evidence_pack.structured_evidence_hashes
            ]
            evidence_reproducible = True
        except Exception:
            evidence_reproducible = False

        profile = None
        profile_hash = None
        price_ok = False
        try:
            profile = matched_odds_profile(self.policy, candidate.observed_odds)
            profile_hash = odds_profile_hash(self.policy, profile)
            price_ok = assess_price_sanity(
                odds=candidate.observed_odds,
                model_probability=candidate.conservative_probability,
                policy=self.policy,
                strong_conditions=True,
            ).passed
        except Exception:
            pass

        model_supported = bool(
            contract
            and candidate.model_artifact_hash
            and candidate.model_artifact_hash == contract.model_artifact_hash
        )
        calibration_supported = bool(
            contract
            and candidate.calibration_artifact_hash
            and candidate.calibration_artifact_hash == contract.calibration_artifact_hash
        )
        odds_profile_ok = bool(contract and profile_hash == contract.odds_profile_hash)
        critical_fresh = bool(
            evidence_pack
            and parse_utc(evidence_pack.evidence_cutoff_ts) <= parse_utc(candidate.decision_at)
            and all(
                parse_utc(row["retrieved_at"]) <= parse_utc(candidate.decision_at)
                and (
                    row.get("ready_at") is None
                    or parse_utc(row["ready_at"]) <= parse_utc(candidate.decision_at)
                )
                and (
                    row.get("freshness_expires_at") is None
                    or parse_utc(row["freshness_expires_at"])
                    >= parse_utc(candidate.decision_at)
                )
                for row in structured_rows
            )
        )
        no_contradiction = bool(
            evidence_pack is not None
            and not evidence_pack.contradiction_links
            and all(
                row.get("status") != "contradicted" and not row.get("contradiction_ids")
                for row in structured_rows
            )
        )
        uncertainty_supported = bool(
            structured_rows
            and all(row.get("status") not in {"uncertain", "contradicted"} for row in structured_rows)
        )

        identity_unambiguous = False
        if contract is not None and artifact is not None and evidence_pack is not None and profile_hash:
            try:
                material_hashes = (
                    candidate.model_artifact_hash,
                    candidate.calibration_artifact_hash,
                    candidate.feature_manifest_hash,
                    candidate.gate_policy_hash,
                    candidate.config_digest,
                    candidate.strategy_decision_contract_hash,
                    candidate.candidate_decision_hash,
                )
                if any(value is None or len(value) != 64 for value in material_hashes):
                    raise ValueError("candidate identity is incomplete")
                expected_hash = decision_hash_for_candidate(
                    candidate,
                    strategy_config_hash=contract.strategy_config_hash,
                    odds_profile_hash=profile_hash,
                    sport_adapter_version=contract.sport_adapter_version,
                )
                identity_unambiguous = all(
                    (
                        candidate.candidate_version == "candidate-v2",
                        candidate.candidate_decision_hash == expected_hash,
                        candidate.config_digest == contract.strategy_config_hash,
                        candidate.feature_manifest_hash == contract.feature_manifest_hash,
                        candidate.feature_manifest_hash == evidence_pack.feature_manifest_hash,
                        candidate.gate_policy_hash == contract.gate_policy_hash,
                        candidate.comparability_group_id == contract.comparability_group_id,
                        candidate.strategy_decision_contract_hash == contract.contract_hash,
                        market_ready,
                        tier_valid,
                    )
                )
            except Exception:
                identity_unambiguous = False

        facts = QualificationFacts(
            strategy_approved=strategy_approved,
            source_ready=source_ready and market_ready,
            identity_unambiguous=identity_unambiguous,
            model_supported=model_supported,
            calibration_supported=calibration_supported,
            evidence_pack_frozen=pack_frozen,
            evidence_reproducible=evidence_reproducible,
            critical_evidence_fresh=critical_fresh,
            no_contradiction=no_contradiction,
            uncertainty_supported=uncertainty_supported,
            odds_profile_ok=odds_profile_ok,
            price_sanity_ok=price_ok,
            liquidity_ok=self._read(self.execution_view, "liquidity_ok", candidate),
            risk_ok=self._read(self.risk_view, "risk_ok", candidate),
            correlation_ok=self._read(self.risk_view, "correlation_ok", candidate),
            execution_available=self._read(
                self.execution_view, "execution_available", candidate
            ),
            no_duplicate_order=self._read(
                self.execution_view, "no_duplicate_order", candidate
            ),
            no_kill_condition=self._read(
                self.execution_view, "no_kill_condition", candidate
            ),
        )
        expired = parse_utc(now) > parse_utc(candidate.expires_at)
        gates = (
            _gate("strategy_approved", facts.strategy_approved, ReasonCode.PASS_STRATEGY_NOT_APPROVED),
            _gate("source_ready", facts.source_ready, ReasonCode.PASS_DATA_CAPABILITY_NOT_READY),
            _gate("identity_unambiguous", facts.identity_unambiguous, ReasonCode.PASS_IDENTITY_AMBIGUOUS),
            _gate("model_supported", facts.model_supported, ReasonCode.PASS_MODEL_OUT_OF_SUPPORT),
            _gate("calibration_supported", facts.calibration_supported, ReasonCode.PASS_CALIBRATION_UNSUPPORTED),
            _gate("evidence_pack_frozen", facts.evidence_pack_frozen, ReasonCode.PASS_MISSING_EVIDENCE),
            _gate("evidence_reproducible", facts.evidence_reproducible, ReasonCode.PASS_GATE_ERROR),
            _gate("critical_evidence_fresh", facts.critical_evidence_fresh, ReasonCode.PASS_STALE_EVIDENCE),
            _gate("no_contradiction", facts.no_contradiction, ReasonCode.PASS_CONTRADICTION),
            _gate("uncertainty_supported", facts.uncertainty_supported, ReasonCode.PASS_CRITICAL_UNCERTAINTY),
            _gate("odds_profile_ok", facts.odds_profile_ok, ReasonCode.PASS_ODDS_OUTSIDE_PROFILE),
            _gate("price_sanity_ok", facts.price_sanity_ok, ReasonCode.PASS_PRICE_SANITY_FAIL),
            _gate("liquidity_ok", facts.liquidity_ok, ReasonCode.PASS_LIQUIDITY_FAIL),
            _gate("risk_ok", facts.risk_ok, ReasonCode.PASS_RISK_LIMIT),
            _gate("correlation_ok", facts.correlation_ok, ReasonCode.PASS_CORRELATION_LIMIT),
            _gate("execution_available", facts.execution_available, ReasonCode.PASS_EXECUTION_UNAVAILABLE),
            _gate("no_duplicate_order", facts.no_duplicate_order, ReasonCode.PASS_UNKNOWN_STATE),
            _gate("no_kill_condition", facts.no_kill_condition, ReasonCode.PASS_RISK_LIMIT),
            GateResult("candidate_not_expired", not expired, None if not expired else ReasonCode.PASS_EXPIRED_CANDIDATE),
        )
        if not all(gate.passed for gate in gates):
            return SelectionDecision(candidate.candidate_id, "PASS", gates)

        assert contract is not None
        gate_results_digest = sha256_bytes(
            canonical_json(
                [
                    {"name": gate.name, "passed": gate.passed, "reason": gate.reason}
                    for gate in gates
                ]
            )
        )
        record = QualificationRecord.create(
            candidate_id=candidate.candidate_id,
            candidate_decision_hash=candidate.candidate_decision_hash,
            strategy_id=candidate.strategy_id,
            strategy_version=candidate.strategy_version,
            strategy_decision_contract_hash=contract.contract_hash,
            approved_tier=candidate.strategy_tier,
            comparability_group_id=contract.comparability_group_id,
            active_policy_digest=self.policy.digest,
            market_capability_id=contract.market_capability_id,
            decision_at=candidate.decision_at,
            evaluated_at=now,
            expires_at=candidate.expires_at,
            gate_results_digest=gate_results_digest,
        )
        self.qualification_records.append(record)
        return SelectionDecision(
            candidate.candidate_id, "QUALIFY", gates, record.qualification_record_id
        )


def qualify(
    candidate: CandidateBet,
    *,
    now: str,
    market_supported: bool,
    strategy_approved: bool,
    model_supported: bool,
    evidence_fresh: bool,
    price_sane: bool,
    execution_available: bool,
    risk_approved: bool,
) -> SelectionDecision:
    """Evaluate hard gates and return QUALIFY or PASS.

    This function never submits an order and never changes configuration.  It
    accepts explicit gate facts so later services cannot smuggle in hidden
    defaults or an LLM-generated override.
    """

    gates = (
        GateResult("market_supported", market_supported, None if market_supported else ReasonCode.UNSUPPORTED_MARKET),
        GateResult("strategy_approved", strategy_approved, None if strategy_approved else ReasonCode.STRATEGY_NOT_APPROVED),
        GateResult("model_supported", model_supported, None if model_supported else ReasonCode.MODEL_UNSUPPORTED),
        GateResult("evidence_fresh", evidence_fresh, None if evidence_fresh else ReasonCode.STALE_EVIDENCE),
        GateResult("decision_not_expired", parse_utc(now) <= parse_utc(candidate.expires_at), None if parse_utc(now) <= parse_utc(candidate.expires_at) else ReasonCode.EXPIRED),
        GateResult("price_sane", price_sane, None if price_sane else ReasonCode.PRICE_SANITY_FAILED),
        GateResult("execution_available", execution_available, None if execution_available else ReasonCode.EXECUTION_UNAVAILABLE),
        GateResult("risk_approved", risk_approved, None if risk_approved else ReasonCode.RISK_REJECTED),
        GateResult("evidence_complete", candidate.evidence_complete, None if candidate.evidence_complete else ReasonCode.MISSING_EVIDENCE),
        GateResult("no_critical_uncertainty", not candidate.critical_uncertainty_flags, None if not candidate.critical_uncertainty_flags else ReasonCode.CRITICAL_UNCERTAINTY),
    )
    return SelectionDecision(candidate.candidate_id, "QUALIFY" if all(g.passed for g in gates) else "PASS", gates)


def rank_qualified(candidates: Iterable[tuple[CandidateBet, SelectionDecision]]) -> list[CandidateBet]:
    qualified: list[CandidateBet] = []
    for candidate, decision in candidates:
        if not decision.passed:
            continue
        if decision.qualification_record_id is None:
            raise ValueError("ranking requires an authoritative qualification record")
        parse_tier(candidate.strategy_tier)
        if not candidate.comparability_group_id:
            raise ValueError("ranking requires an approved comparability group")
        qualified.append(candidate)

    def stable_identity(candidate: CandidateBet) -> str:
        return candidate.candidate_decision_hash or candidate.candidate_id

    result: list[CandidateBet] = []
    tiers = sorted(
        {parse_tier(candidate.strategy_tier) for candidate in qualified}, reverse=True
    )
    for tier_value in tiers:
        tier_candidates = [
            candidate
            for candidate in qualified
            if parse_tier(candidate.strategy_tier) == tier_value
        ]
        groups: dict[str, list[CandidateBet]] = {}
        for candidate in tier_candidates:
            assert candidate.comparability_group_id is not None
            groups.setdefault(candidate.comparability_group_id, []).append(candidate)
        queues = [
            sorted(
                members,
                key=lambda candidate: (
                    -Decimal(candidate.conservative_probability),
                    stable_identity(candidate),
                    candidate.candidate_id,
                ),
            )
            for members in groups.values()
        ]
        # Group names carry no quality meaning.  The minimum stable candidate
        # identity orders queues only to make diversification deterministic.
        queues.sort(key=lambda queue: min(stable_identity(item) for item in queue))
        while any(queues):
            for queue in queues:
                if queue:
                    result.append(queue.pop(0))
    return result
