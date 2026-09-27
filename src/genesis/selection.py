"""Deterministic PASS-first qualification interface; no execution side effects."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from .capabilities import MarketCapabilityRegistry
from .canonical import CandidateBet
from .decision import candidate_v3_decision_hash, decision_hash_for_candidate
from .decision_output import (
    APPROVAL_V2_PREFIX, DecisionOutputStore, StrategyOutputApprovalStore,
    StrategyOutputRuleBindingStore, TrustedDecisionOutputAuthority,
)
from .evidence import StructuredEvidenceStore
from .evidence_pack import EvidencePackStore
from .feature_manifest import FeatureInputManifestStore
from .owner_binding import owner_identity, same_owner_identity
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


def _candidate_matches_output(candidate: CandidateBet, output: dict) -> bool:
    """Candidate copies are comparison-only; they never supply V3 authority."""

    try:
        scalars = {
            "strategy_id": candidate.strategy_id,
            "strategy_version": candidate.strategy_version,
            "model_version": candidate.model_version,
            "sport": candidate.sport,
            "market_family": candidate.market_family,
            "event_id": candidate.event_id,
            "market_id": candidate.market_id,
            "selection_id": candidate.selection_id,
            "side": candidate.side.value,
            "model_probability": candidate.model_probability,
            "conservative_probability": candidate.conservative_probability,
            "model_support_status": candidate.model_support_status,
            "calibration_status": candidate.calibration_status,
            "uncertainty_status": candidate.uncertainty_status,
            "observed_odds": candidate.observed_odds,
            "requested_odds_min": candidate.requested_odds_min,
            "requested_odds_max": candidate.requested_odds_max,
            "approved_tier": candidate.strategy_tier,
            "comparability_group_id": candidate.comparability_group_id,
            "selection_dependency_group": candidate.selection_dependency_group,
            "meeting_id": candidate.meeting_id,
            "competition_id": candidate.competition_id,
            "feature_manifest_hash": candidate.feature_manifest_hash,
            "evidence_pack_hash": candidate.evidence_pack_id,
            "strategy_decision_contract_hash": candidate.strategy_decision_contract_hash,
            "strategy_config_hash": candidate.config_digest,
            "model_artifact_hash": candidate.model_artifact_hash,
            "calibration_artifact_hash": candidate.calibration_artifact_hash,
            "gate_policy_hash": candidate.gate_policy_hash,
        }
        if any(output[key] != value for key, value in scalars.items()):
            return False
        for key, values in (
            ("critical_uncertainty_flags", candidate.critical_uncertainty_flags),
            ("correlation_cluster_ids", candidate.correlation_cluster_ids),
            ("participant_ids", candidate.participant_ids),
            ("shared_evidence_ids", candidate.shared_evidence_ids),
        ):
            if tuple(output[key]) != tuple(values):
                return False
        return all((
            output["evidence_cutoff_ts"] == iso_utc(candidate.evidence_cutoff_ts),
            output["decision_at"] == iso_utc(candidate.decision_at),
            output["expires_at"] == iso_utc(candidate.expires_at),
        ))
    except Exception:
        return False


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
    decision_output_hash: str | None = None
    feature_manifest_hash: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version not in {"qualification-record-v2", "qualification-record-v3"} or self.action != "QUALIFY":
            raise ValueError("unsupported qualification record authority")
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
        if self.schema_version == "qualification-record-v2":
            if self.decision_output_hash is not None or self.feature_manifest_hash is not None:
                raise ValueError("historical V2 qualification cannot carry V3 lineage")
        else:
            for name in ("decision_output_hash", "feature_manifest_hash"):
                value = getattr(self, name)
                if not isinstance(value, str) or len(value) != 64:
                    raise ValueError(f"V3 qualification lacks {name}")
                int(value, 16)
        if self.compute_id() != self.qualification_record_id:
            raise ValueError("qualification record ID mismatch")

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("qualification_record_id")
        if self.schema_version == "qualification-record-v2":
            value.pop("decision_output_hash")
            value.pop("feature_manifest_hash")
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


APPROVAL_WITNESS_SCHEMA = "qualification-approval-witness-v1"
_WITNESS_FIELDS = frozenset({
    "record_type", "schema_version", "qualification_record_id", "decision_output_hash",
    "decision_at", "binding_hash", "approval_reference", "approval_ledger",
    "grant_record_hash", "grant_sequence",
})
_CHAIN_FIELDS = frozenset({"previous_hash", "sequence", "record_hash"})


def _same_ledger(left: object, right: object) -> bool:
    """E7: witness ledgers compare as N2 compares owner identities."""

    if left is None or right is None:
        return left is None and right is None
    return (
        isinstance(left, str) and isinstance(right, str)
        and same_owner_identity(left, right)
    )


def _same_witness(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _same_ledger(left["approval_ledger"], right["approval_ledger"]) and all(
        left[key] == right[key] for key in _WITNESS_FIELDS - {"approval_ledger"}
    )


class _WitnessRecording:
    """The witness builder of one authority recording of a V3 qualification (E1)."""

    def __init__(
        self, store: QualificationRecordStore,
        build: Callable[[tuple[dict[str, Any], ...]], dict[str, Any] | None],
    ):
        self.store = store
        self.build = build

    def __call__(self, rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
        return self.build(rows)


class _ApprovalWitnessLog(AppendOnlyJsonl):
    """Witness storage that appends only the recording path's own witness (F-2).

    Only the authority's recording of a V3 qualification writes a witness
    (E1); any other builder, such as a direct ``append``, appends nothing.
    Every append runs under the qualification-log and ledger locks. It must be
    the first witness for its record and ledger, for a record that does not
    exist yet, and exactly the witness of a grant that exists now. A witness
    can therefore never follow its record.
    """

    def __init__(self, path: str | Path, store: QualificationRecordStore):
        super().__init__(path)
        self._store = store

    def transaction(
        self,
        build_record: Callable[[tuple[dict[str, Any], ...]], dict[str, Any] | None],
        *,
        read_locks: tuple[AppendOnlyJsonl, ...] = (),
    ) -> str | None:
        store = self._store
        recording = isinstance(build_record, _WitnessRecording) and build_record.store is store

        def checked(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            row = build_record(rows)
            if row is not None:
                if not recording:
                    raise RegistryConflict(
                        "an approval witness is written only by its qualification's recording"
                    )
                store._require_new_witness(rows, row)
            return row

        return super().transaction(checked, read_locks=(
            *read_locks, store.log, store.bindings.log, store.approvals.log,
        ))


class QualificationRecordStore:
    """Qualification records plus the durable witness of each V3 record's grant.

    T6 F-2: a V3 record admits new risk only with its approval witness. The
    recording path writes it, under the qualification-log and ledger locks,
    only while the record does not yet exist and its exact unrevoked grant
    does. The witness names that grant row and the ledger it is in, relative to
    this log. Risk requires the witness for the risk-bound ledger to equal that
    grant as the ledger holds it, so a grant appended after the record, even a
    byte-identical copy of one made in another ledger, never admits it. The
    witness is a sidecar, so qualification rows and identities are unchanged.

    E1: that recording path is ``QualificationAuthority.evaluate``'s alone, so
    a caller-constructed or copied V3 record never gets a witness.
    """

    def __init__(
        self, path: str | Path, *, outputs: DecisionOutputStore | None = None,
        bindings: StrategyOutputRuleBindingStore | None = None,
        approvals: StrategyOutputApprovalStore | None = None,
    ):
        self.log = AppendOnlyJsonl(path, reader=self._replay)
        self.witnesses = _ApprovalWitnessLog(
            Path(path).with_name(f"{Path(path).name}.approval-witness.jsonl"), self,
        )
        self.outputs = outputs or DecisionOutputStore(Path(path).parent / "decision-outputs")
        self.bindings = bindings or StrategyOutputRuleBindingStore(
            Path(path).parent / "strategy-output-bindings.jsonl"
        )
        self.approval_root = Path(path).parent / "strategy-output-approvals"
        self.approvals = approvals or StrategyOutputApprovalStore(
            Path(path).parent / "strategy-output-approvals-v2.jsonl"
        )

    def _require_separate_approval(
        self, reference: str, *, binding_hash: str, decision_at: str,
    ) -> None:
        TrustedDecisionOutputAuthority(
            outputs=self.outputs, bindings=self.bindings, resolver=None,
            approval_root=self.approval_root,
            approvals=self.approvals,
        )._validate_approval_reference(
            reference, binding_hash=binding_hash, decision_at=decision_at,
        )

    @staticmethod
    def _from_row(row: dict[str, Any]) -> QualificationRecord:
        schema = row.get("schema_version")
        expected = set(QualificationRecord.__dataclass_fields__)
        if schema == "qualification-record-v2":
            expected -= {"decision_output_hash", "feature_manifest_hash"}
        if set(row) != expected | {"record_type", "previous_hash", "sequence", "record_hash"} \
                or row.get("record_type") != "qualification_record":
            raise RegistryConflict("qualification record has an unsupported active schema")
        fields = {key: row[key] for key in QualificationRecord.__dataclass_fields__ if key in row}
        return QualificationRecord(**fields)

    def append(
        self,
        record: QualificationRecord,
        *,
        verify: Callable[[], bool] | None = None,
        read_locks: tuple[AppendOnlyJsonl, ...] = (),
    ) -> QualificationRecord:
        """Append a historical V2 qualification, which never admits new risk.

        E1: a V3 qualification is recorded only by ``QualificationAuthority.evaluate``.
        """

        if record.schema_version != "qualification-record-v2":
            raise RegistryConflict(
                "a V3 qualification is recorded only by QualificationAuthority.evaluate"
            )
        return self._append(record, verify=verify, read_locks=read_locks)

    def _require_recording_authority(self, authority: object) -> None:
        """E1: only this store's own qualification authority records a V3 record."""

        if not isinstance(authority, QualificationAuthority) \
                or authority.qualification_records is not self:
            raise RegistryConflict(
                "a V3 qualification is recorded only by its store's QualificationAuthority"
            )

    def _record_evaluated(
        self,
        authority: object,
        record: QualificationRecord,
        *,
        verify: Callable[[], bool] | None,
        read_locks: tuple[AppendOnlyJsonl, ...],
    ) -> QualificationRecord:
        """Record the V3 qualification the authority has just evaluated (E1).

        This is the only path that writes an approval witness, so a V3 row that
        reaches the log any other way stays audit-only for new risk.
        """

        self._require_recording_authority(authority)
        if record.schema_version != "qualification-record-v3":
            raise RegistryConflict("the qualification authority records only V3 qualifications")
        self._record_witness(record)
        return self._append(record, verify=verify, read_locks=read_locks)

    def _append(
        self,
        record: QualificationRecord,
        *,
        verify: Callable[[], bool] | None,
        read_locks: tuple[AppendOnlyJsonl, ...],
    ) -> QualificationRecord:
        payload = {"record_type": "qualification_record", **record.to_dict()}

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            if verify is not None and not verify():
                raise RegistryConflict("qualification proof changed before append")
            matches = [
                self._from_row(row)
                for row in rows
                if row.get("record_type") == "qualification_record"
                and row.get("qualification_record_id") == record.qualification_record_id
            ]
            if not matches:
                if record.schema_version == "qualification-record-v3":
                    self._require_witnessed(self._require_prior_grant(record))
                return payload
            if all(item == record for item in matches):
                return None
            raise RegistryConflict("qualification record ID conflict")

        # The binding and approval ledgers are fenced with the append, so the
        # grant checked here is the grant that exists when the record exists.
        self.log.transaction(
            build, read_locks=(
                *read_locks, self.bindings.log, self.approvals.log, self.witnesses,
            ),
        )
        return record

    def _recorded(self, record_id: str) -> bool:
        return any(
            row.get("record_type") == "qualification_record"
            and row.get("qualification_record_id") == record_id
            for row in self.log.records()
        )

    def _record_witness(self, record: QualificationRecord) -> None:
        """F-2: witness the exact prior grant while the record does not exist yet."""

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            if self._recorded(record.qualification_record_id):
                return None
            witness = self._require_prior_grant(record)
            existing = self._witnesses_like(rows, witness)
            if existing:
                if len(existing) == 1 and _same_witness(existing[0], witness):
                    return None
                raise RegistryConflict("conflicting qualification approval witness")
            return witness

        self.witnesses.transaction(_WitnessRecording(self, build))

    def _require_new_witness(
        self, rows: tuple[dict[str, Any], ...], row: dict[str, Any],
    ) -> None:
        """Witness-storage guard: only the recording path's witness, before its record."""

        if not isinstance(row, dict) or set(row) != _WITNESS_FIELDS:
            raise RegistryConflict("qualification approval witness is malformed")
        if self._recorded(row["qualification_record_id"]):
            raise RegistryConflict("a qualification approval witness cannot follow its record")
        if self._witnesses_like(rows, row):
            raise RegistryConflict("qualification approval is already witnessed")
        if row != self._prior_grant_witness(
            row["qualification_record_id"], row["decision_output_hash"], row["decision_at"],
        ):
            raise RegistryConflict("qualification approval witness is not the exact prior grant")

    def _require_prior_grant(self, record: QualificationRecord) -> dict[str, Any]:
        """O-5: a V3 record needs its exact unrevoked human grant to exist first.

        Returns the approval witness of that grant. A grant appended later,
        even with a backdated ``approved_at``, can never be the grant that
        admits this qualification to new risk.
        """

        return self._prior_grant_witness(
            record.qualification_record_id, record.decision_output_hash, record.decision_at,
        )

    def _prior_grant_witness(
        self, record_id: str, output_hash: str | None, decision_at: str,
    ) -> dict[str, Any]:
        try:
            output = self.outputs.get(output_hash)
            binding_hash = output["resolver_binding_hash"]
            binding = self.bindings.require_active(binding_hash, decision_at)
            return self._approval_witness(
                record_id, output_hash, decision_at, binding_hash=binding_hash,
                reference=binding["human_approval_reference"],
            )
        except RegistryConflict:
            raise
        except Exception as exc:
            raise RegistryConflict(
                "V3 qualification has no exact prior human approval grant"
            ) from exc

    def _approval_witness(
        self, record_id: str, output_hash: str | None, decision_at: str, *,
        binding_hash: str, reference: str,
    ) -> dict[str, Any]:
        """The exact approval a V3 record relies on, as this store's ledger holds it."""

        self._require_separate_approval(
            reference, binding_hash=binding_hash, decision_at=decision_at,
        )
        ledger = grant_hash = grant_sequence = None
        if reference.startswith(APPROVAL_V2_PREFIX):
            grant = StrategyOutputApprovalStore._replay(
                self.approvals.log.records()
            )["grants"].get(reference)
            if grant is None:
                raise RegistryConflict("V3 qualification has no exact prior human approval grant")
            ledger = owner_identity(self.approvals.log.path, self.log.path.parent)
            grant_hash, grant_sequence = grant["record_hash"], grant["sequence"]
        return {
            "record_type": "qualification_approval_witnessed",
            "schema_version": APPROVAL_WITNESS_SCHEMA,
            "qualification_record_id": record_id,
            "decision_output_hash": output_hash,
            "decision_at": iso_utc(decision_at),
            "binding_hash": binding_hash,
            "approval_reference": reference,
            "approval_ledger": ledger,
            "grant_record_hash": grant_hash,
            "grant_sequence": grant_sequence,
        }

    @staticmethod
    def _witnesses_like(
        rows: tuple[dict[str, Any], ...] | list[dict[str, Any]], witness: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Witnesses for ``witness``'s record that name the same ledger (E7: as N2 does)."""

        found = []
        for row in rows:
            if (set(row) != _WITNESS_FIELDS | _CHAIN_FIELDS
                    or row.get("record_type") != "qualification_approval_witnessed"
                    or row.get("schema_version") != APPROVAL_WITNESS_SCHEMA):
                raise RegistryConflict("unsupported qualification approval witness history")
            if (
                row["qualification_record_id"] == witness["qualification_record_id"]
                and _same_ledger(row["approval_ledger"], witness["approval_ledger"])
            ):
                found.append({key: row[key] for key in _WITNESS_FIELDS})
        return found

    def _require_witnessed(self, expected: dict[str, Any]) -> None:
        found = self._witnesses_like(self.witnesses.records(), expected)
        if len(found) != 1 or not _same_witness(found[0], expected):
            raise RegistryConflict("V3 qualification lacks its exact prior approval witness")

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

    def get_for_new_risk(self, record_id: str, *, at: str | None = None) -> QualificationRecord:
        self.verify()
        record = self.get(record_id)
        if record.schema_version != "qualification-record-v3":
            raise RegistryConflict("legacy qualification is audit-only for new risk")
        assert record.decision_output_hash is not None
        assert record.feature_manifest_hash is not None
        output = self.outputs.get(record.decision_output_hash)
        binding = self.bindings.require_active(
            output["resolver_binding_hash"], at or record.evaluated_at,
        )
        # F-2: the grant must be the one witnessed before the record existed.
        self._require_witnessed(self._approval_witness(
            record.qualification_record_id, record.decision_output_hash, record.decision_at,
            binding_hash=output["resolver_binding_hash"],
            reference=binding["human_approval_reference"],
        ))
        expected_hash = candidate_v3_decision_hash(
            strategy_decision_contract_hash=record.strategy_decision_contract_hash,
            feature_manifest_hash=record.feature_manifest_hash,
            evidence_pack_hash=output["evidence_pack_hash"],
            decision_output_hash=record.decision_output_hash,
        )
        if any((
            record.candidate_decision_hash != expected_hash,
            record.feature_manifest_hash != output["feature_manifest_hash"],
            record.strategy_decision_contract_hash != output["strategy_decision_contract_hash"],
            record.approved_tier != output["approved_tier"],
            iso_utc(record.expires_at) != output["expires_at"],
            iso_utc(record.decision_at) != output["decision_at"],
            record.comparability_group_id != output["comparability_group_id"],
            record.market_capability_id != output["market_capability_id"],
            binding["strategy_decision_contract_hash"] != record.strategy_decision_contract_hash,
            binding["active_policy_digest"] != record.active_policy_digest,
            binding["feature_manifest_hash"] != record.feature_manifest_hash,
            binding["model_artifact_hash"] != output["model_artifact_hash"],
            binding["calibration_artifact_hash"] != output["calibration_artifact_hash"],
            binding["gate_policy_hash"] != output["gate_policy_hash"],
            any(binding[name] != output[name] for name in (
                "model_runner_hash", "calibration_runner_hash", "tier_rule_hash",
                "expiry_rule_hash",
            )),
        )):
            raise RegistryConflict("V3 qualification/output lineage mismatch")
        return record

    @classmethod
    def _replay(cls, rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> None:
        """Every qualification row, as ``verify`` and ``get`` read it (E4)."""

        for row in rows:
            cls._from_row(row)

    def verify(self) -> int:
        rows = self.log.records()
        self._replay(rows)
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
        feature_manifests: FeatureInputManifestStore,
        structured_evidence: StructuredEvidenceStore,
        policy: PolicySet,
        risk_view: QualificationRiskReadView,
        execution_view: QualificationExecutionReadView,
        qualification_records: QualificationRecordStore,
        decision_outputs: TrustedDecisionOutputAuthority | None = None,
    ):
        dependencies = {
            "strategies": strategies,
            "market_capabilities": market_capabilities,
            "pit": pit,
            "evidence_packs": evidence_packs,
            "feature_manifests": feature_manifests,
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
            (feature_manifests, FeatureInputManifestStore),
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
        self.feature_manifests = feature_manifests
        self.structured_evidence = structured_evidence
        self.policy = policy
        self.risk_view = risk_view
        self.execution_view = execution_view
        self.qualification_records = qualification_records
        self.decision_outputs = decision_outputs

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
            except Exception:
                market_ready = False

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
            source_ready = bool(
                self.feature_manifests.verify_for_pack(
                    evidence_pack,
                    event_id=candidate.event_id,
                    market_id=candidate.market_id,
                    pit=self.pit,
                    evidence=self.structured_evidence.evidence,
                    structured_evidence=self.structured_evidence,
                )
            )
        except Exception:
            evidence_reproducible = False

        output: dict | None = None
        if candidate.candidate_version == "candidate-v3" and evidence_pack is not None \
                and source_ready and self.decision_outputs is not None:
            try:
                if candidate.decision_output_hash is None:
                    raise ValueError("missing decision output identity")
                if self.decision_outputs.outputs.root.resolve() != \
                        self.qualification_records.outputs.root.resolve():
                    raise ValueError("qualification and output stores are not bound")
                manifest = self.feature_manifests.get(evidence_pack.feature_manifest_hash)
                output = self.decision_outputs.verify(
                    candidate.decision_output_hash, manifest=manifest,
                    pack=evidence_pack, contract=contract, policy=self.policy,
                )
                binding = self.decision_outputs.bindings.require_active(
                    output["resolver_binding_hash"], output["decision_at"],
                )
                if binding["human_approval_reference"].startswith(APPROVAL_V2_PREFIX):
                    approvals = self.decision_outputs.approvals
                    if approvals is None or approvals.log.path.resolve() != \
                            self.qualification_records.approvals.log.path.resolve():
                        raise ValueError("qualification approval authorities are not bound")
                if not _candidate_matches_output(candidate, output):
                    output = None
            except Exception:
                output = None

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
            and output is not None
            and output["model_support_status"] == "supported"
        )
        calibration_supported = bool(
            contract
            and candidate.calibration_artifact_hash
            and candidate.calibration_artifact_hash == contract.calibration_artifact_hash
            and output is not None
            and output["calibration_status"] == "supported"
        )
        odds_profile_ok = bool(contract and profile_hash == contract.odds_profile_hash)
        critical_fresh = bool(
            evidence_pack
            and parse_utc(evidence_pack.evidence_cutoff_ts) <= parse_utc(candidate.decision_at)
            and parse_utc(evidence_pack.frozen_at) <= parse_utc(candidate.decision_at)
            and all(
                parse_utc(row["retrieved_at"]) <= parse_utc(evidence_pack.evidence_cutoff_ts)
                and (
                    row.get("ready_at") is None
                    or parse_utc(row["ready_at"]) <= parse_utc(evidence_pack.evidence_cutoff_ts)
                )
                and (
                    row.get("freshness_expires_at") is None
                    or parse_utc(row["freshness_expires_at"])
                    >= parse_utc(evidence_pack.evidence_cutoff_ts)
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
            and output is not None
            and output["uncertainty_status"] == "supported"
            and not output["critical_uncertainty_flags"]
        )

        identity_unambiguous = False
        if contract is not None and artifact is not None and evidence_pack is not None and profile_hash and output is not None:
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
                expected_hash = candidate_v3_decision_hash(
                    strategy_decision_contract_hash=contract.contract_hash,
                    feature_manifest_hash=evidence_pack.feature_manifest_hash,
                    evidence_pack_hash=evidence_pack.pack_hash,
                    decision_output_hash=candidate.decision_output_hash,
                )
                identity_unambiguous = all(
                    (
                        candidate.candidate_version == "candidate-v3",
                        candidate.candidate_decision_hash == expected_hash,
                        candidate.config_digest == contract.strategy_config_hash,
                        candidate.feature_manifest_hash == contract.feature_manifest_hash,
                        candidate.feature_manifest_hash == evidence_pack.feature_manifest_hash,
                        candidate.gate_policy_hash == contract.gate_policy_hash,
                        candidate.comparability_group_id == contract.comparability_group_id,
                        candidate.strategy_decision_contract_hash == contract.contract_hash,
                        market_ready,
                        tier_valid,
                        _candidate_matches_output(candidate, output),
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
            _gate("trusted_decision_output", output is not None, ReasonCode.PASS_IDENTITY_AMBIGUOUS),
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
        assert output is not None
        gate_results_digest = sha256_bytes(
            canonical_json(
                [
                    {"name": gate.name, "passed": gate.passed, "reason": gate.reason}
                    for gate in gates
                ]
            )
        )
        record = QualificationRecord.create(
            schema_version="qualification-record-v3",
            candidate_id=candidate.candidate_id,
            candidate_decision_hash=candidate.candidate_decision_hash,
            strategy_id=candidate.strategy_id,
            strategy_version=candidate.strategy_version,
            strategy_decision_contract_hash=contract.contract_hash,
            approved_tier=output["approved_tier"],
            comparability_group_id=contract.comparability_group_id,
            active_policy_digest=self.policy.digest,
            market_capability_id=contract.market_capability_id,
            decision_at=candidate.decision_at,
            evaluated_at=now,
            expires_at=output["expires_at"],
            gate_results_digest=gate_results_digest,
            decision_output_hash=candidate.decision_output_hash,
            feature_manifest_hash=evidence_pack.feature_manifest_hash,
        )
        assert evidence_pack is not None
        assert self.pit.log is not None

        def verify_frozen_inputs() -> bool:
            try:
                current_pack = self.evidence_packs.use_authoritatively(
                    candidate.evidence_pack_id
                )
                if current_pack != evidence_pack:
                    return False
                self.feature_manifests.verify_for_pack(
                    current_pack,
                    event_id=candidate.event_id,
                    market_id=candidate.market_id,
                    pit=self.pit,
                    evidence=self.structured_evidence.evidence,
                    structured_evidence=self.structured_evidence,
                )
                current_output = self.decision_outputs.verify(
                    candidate.decision_output_hash,
                    manifest=self.feature_manifests.get(current_pack.feature_manifest_hash),
                    pack=current_pack, contract=contract, policy=self.policy,
                )
                if current_output != output or not _candidate_matches_output(candidate, current_output):
                    return False
                return True
            except Exception:
                return False

        proof_locks = (
            self.pit.log,
            self.pit.capabilities.log,
            self.feature_manifests.bindings.log,
            self.structured_evidence.evidence.contracts.log,
            self.decision_outputs.bindings.log,
            self.qualification_records.approvals.log,
        )
        try:
            self.qualification_records._record_evaluated(
                self, record, verify=verify_frozen_inputs, read_locks=proof_locks
            )
        except RegistryConflict:
            stale_gates = tuple(
                _gate("source_ready", False, ReasonCode.PASS_DATA_CAPABILITY_NOT_READY)
                if gate.name == "source_ready" else gate
                for gate in gates
            )
            return SelectionDecision(candidate.candidate_id, "PASS", stale_gates)
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
    """Historical/pure ranking diagnostic; V3 requires the authority-aware path."""

    items = list(candidates)
    if any(candidate.candidate_version == "candidate-v3" for candidate, _ in items):
        raise ValueError("candidate-v3 ranking requires exact output authority")
    return _rank_qualified_items(items)


def rank_qualified_v3(
    candidates: Iterable[tuple[CandidateBet, SelectionDecision]],
    *,
    qualification_records: QualificationRecordStore,
) -> list[CandidateBet]:
    """Rank only reproduced V3 outputs with their exact qualification lineage."""

    verified: list[tuple[CandidateBet, SelectionDecision]] = []
    seen: set[str] = set()
    for candidate, decision in candidates:
        if not decision.passed:
            continue
        if candidate.candidate_version != "candidate-v3" or decision.qualification_record_id is None:
            raise ValueError("V3 ranking requires authoritative qualification")
        record = qualification_records.get_for_new_risk(decision.qualification_record_id)
        output = qualification_records.outputs.get(record.decision_output_hash)
        if (record.candidate_decision_hash != candidate.candidate_decision_hash
                or record.candidate_id != candidate.candidate_id
                or not _candidate_matches_output(candidate, output)):
            raise ValueError("candidate and trusted ranking output differ")
        if record.candidate_decision_hash in seen:
            raise ValueError("one decision identity cannot be ranked twice")
        seen.add(record.candidate_decision_hash)
        trusted = replace(
            candidate,
            strategy_tier=output["approved_tier"],
            conservative_probability=output["conservative_probability"],
            observed_odds=output["observed_odds"],
            comparability_group_id=output["comparability_group_id"],
        )
        verified.append((trusted, decision))
    return _rank_qualified_items(verified)


def _rank_qualified_items(candidates: Iterable[tuple[CandidateBet, SelectionDecision]]) -> list[CandidateBet]:
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
