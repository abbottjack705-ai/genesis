"""Durable, authority-derived offline risk and approval contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from .accounting import BetSide, MatchedFragment, money
from .policy import PolicySet, canonical_decimal, parse_tier
from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, sha256_bytes
from .selection import QualificationRecordStore
from .time import iso_utc, parse_utc


class ExposureState(StrEnum):
    MATCHED = "matched"
    PARTIALLY_MATCHED = "partially_matched"
    UNMATCHED = "unmatched"
    PENDING = "pending"
    UNKNOWN = "unknown"
    SETTLED = "settled"
    VOID = "void"


@dataclass(frozen=True)
class Exposure:
    exposure_id: str
    candidate_decision_hash: str
    liability: str
    state: ExposureState
    correlation_cluster_ids: tuple[str, ...] = ()
    dependency_group: str | None = None
    affected_scope: str | None = None

    def __post_init__(self) -> None:
        if len(self.candidate_decision_hash) != 64:
            raise ValueError("candidate_decision_hash must be a SHA-256 digest")
        if Decimal(self.liability) < 0:
            raise ValueError("liability cannot be negative")
        for cluster in self.correlation_cluster_ids:
            if not cluster:
                raise ValueError("correlation cluster IDs cannot be empty")

    @property
    def liability_amount(self) -> Decimal:
        return Decimal(self.liability)

    def to_dict(self) -> dict:
        value = asdict(self)
        value["state"] = self.state.value
        return value


@dataclass(frozen=True)
class BankrollSnapshot:
    snapshot_id: str
    bankroll: str
    captured_at: str
    rebase_reason: str
    parent_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        if Decimal(self.bankroll) <= 0:
            raise ValueError("bankroll must be positive")
        parse_utc(self.captured_at)
        if self.compute_id() != self.snapshot_id:
            raise ValueError("bankroll snapshot ID mismatch")

    def unsigned_dict(self) -> dict:
        value = asdict(self)
        value.pop("snapshot_id")
        value["bankroll"] = canonical_decimal(self.bankroll)
        value["captured_at"] = iso_utc(self.captured_at)
        return value

    def compute_id(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict:
        return {"snapshot_id": self.snapshot_id, **self.unsigned_dict()}

    @classmethod
    def create(
        cls,
        *,
        bankroll: str,
        captured_at: str,
        rebase_reason: str,
        parent_snapshot_id: str | None = None,
    ) -> "BankrollSnapshot":
        unsigned = {
            "bankroll": canonical_decimal(bankroll),
            "captured_at": iso_utc(captured_at),
            "rebase_reason": rebase_reason,
            "parent_snapshot_id": parent_snapshot_id,
        }
        return cls(snapshot_id=sha256_bytes(canonical_json(unsigned)), **unsigned)


class BankrollSnapshotStore:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    @staticmethod
    def _from_row(row: dict) -> BankrollSnapshot:
        return BankrollSnapshot(
            **{key: row[key] for key in BankrollSnapshot.__dataclass_fields__}
        )

    def history(self) -> tuple[BankrollSnapshot, ...]:
        history: list[BankrollSnapshot] = []
        for row in self.log.records():
            if (row.get("record_type"), row.get("schema_version")) != (
                "bankroll_snapshot_recorded", "bankroll-snapshot-v2"
            ):
                raise RegistryConflict("unsupported active bankroll event")
            try:
                snapshot = self._from_row(row)
            except (KeyError, TypeError, ValueError) as exc:
                raise RegistryConflict("incomplete active bankroll event") from exc
            if history:
                previous = history[-1]
                if (
                    snapshot.parent_snapshot_id != previous.snapshot_id
                    or parse_utc(snapshot.captured_at) <= parse_utc(previous.captured_at)
                ):
                    raise RegistryConflict("bankroll replay has an invalid head transition")
            elif snapshot.parent_snapshot_id is not None:
                raise RegistryConflict("initial bankroll replay has a parent")
            history.append(snapshot)
        return tuple(history)

    def current(self) -> BankrollSnapshot:
        history = self.history()
        if not history:
            raise RegistryConflict("bankroll authority has no current snapshot")
        return history[-1]

    def get(self, snapshot_id: str) -> BankrollSnapshot:
        matches = [item for item in self.history() if item.snapshot_id == snapshot_id]
        if len(matches) != 1:
            raise RegistryConflict(f"unknown or ambiguous bankroll snapshot: {snapshot_id}")
        return matches[0]

    def append(self, snapshot: BankrollSnapshot) -> BankrollSnapshot:
        payload = {
            "record_type": "bankroll_snapshot_recorded",
            "schema_version": "bankroll-snapshot-v2",
            **snapshot.to_dict(),
        }

        def build(rows: tuple[dict, ...]) -> dict | None:
            history = list(self.history())
            matches = [item for item in history if item.snapshot_id == snapshot.snapshot_id]
            if matches:
                if all(item == snapshot for item in matches):
                    return None
                raise RegistryConflict("bankroll snapshot ID conflict")
            current = history[-1] if history else None
            if current is None and snapshot.parent_snapshot_id is not None:
                raise RegistryConflict("initial bankroll snapshot cannot have a parent")
            if current is not None:
                if snapshot.parent_snapshot_id != current.snapshot_id:
                    raise RegistryConflict("bankroll snapshot does not extend the current head")
                if parse_utc(snapshot.captured_at) <= parse_utc(current.captured_at):
                    raise RegistryConflict("bankroll snapshot time must advance")
            return payload

        self.log.transaction(build)
        return snapshot


@dataclass(frozen=True)
class SafetyState:
    state_id: str
    kill_switch_active: bool
    recorded_at: str
    reason: str
    parent_state_id: str | None = None

    def __post_init__(self) -> None:
        parse_utc(self.recorded_at)
        if self.compute_id() != self.state_id:
            raise ValueError("safety state ID mismatch")

    def unsigned_dict(self) -> dict:
        value = asdict(self)
        value.pop("state_id")
        value["recorded_at"] = iso_utc(self.recorded_at)
        return value

    def compute_id(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    @classmethod
    def create(
        cls,
        *,
        kill_switch_active: bool,
        recorded_at: str,
        reason: str,
        parent_state_id: str | None = None,
    ) -> "SafetyState":
        unsigned = {
            "kill_switch_active": kill_switch_active,
            "recorded_at": iso_utc(recorded_at),
            "reason": reason,
            "parent_state_id": parent_state_id,
        }
        return cls(state_id=sha256_bytes(canonical_json(unsigned)), **unsigned)

    def to_dict(self) -> dict:
        return {"state_id": self.state_id, **self.unsigned_dict()}


class SafetyStateStore:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    @staticmethod
    def _from_row(row: dict) -> SafetyState:
        return SafetyState(**{key: row[key] for key in SafetyState.__dataclass_fields__})

    def history(self) -> tuple[SafetyState, ...]:
        history: list[SafetyState] = []
        for row in self.log.records():
            if (row.get("record_type"), row.get("schema_version")) != (
                "safety_mode_transition", "safety-state-v2"
            ):
                raise RegistryConflict("unsupported active safety event")
            try:
                state = self._from_row(row)
            except (KeyError, TypeError, ValueError) as exc:
                raise RegistryConflict("incomplete active safety event") from exc
            if history:
                previous = history[-1]
                if (
                    state.parent_state_id != previous.state_id
                    or parse_utc(state.recorded_at) <= parse_utc(previous.recorded_at)
                ):
                    raise RegistryConflict("safety replay has an invalid head transition")
            elif state.parent_state_id is not None:
                raise RegistryConflict("initial safety replay has a parent")
            history.append(state)
        return tuple(history)

    def current(self) -> SafetyState:
        history = self.history()
        if not history:
            raise RegistryConflict("safety authority has no current state")
        return history[-1]

    def append(self, state: SafetyState) -> SafetyState:
        payload = {
            "record_type": "safety_mode_transition",
            "schema_version": "safety-state-v2",
            **state.to_dict(),
        }

        def build(rows: tuple[dict, ...]) -> dict | None:
            history = list(self.history())
            matches = [item for item in history if item.state_id == state.state_id]
            if matches:
                if all(item == state for item in matches):
                    return None
                raise RegistryConflict("safety state ID conflict")
            current = history[-1] if history else None
            if current is None and state.parent_state_id is not None:
                raise RegistryConflict("initial safety state cannot have a parent")
            if current is not None:
                if state.parent_state_id != current.state_id:
                    raise RegistryConflict("safety state does not extend the current head")
                if parse_utc(state.recorded_at) <= parse_utc(current.recorded_at):
                    raise RegistryConflict("safety state time must advance")
            return payload

        self.log.transaction(build)
        return state


@dataclass(frozen=True)
class RiskRequest:
    candidate_decision_hash: str
    qualification_record_id: str
    bankroll_snapshot_id: str
    side: BetSide
    odds: str
    requested_at: str
    correlation_cluster_ids: tuple[str, ...] = ()
    affected_scope: str | None = None
    expected_tier: str | None = None
    expected_stake: str | None = None
    expected_liability: str | None = None

    def __post_init__(self) -> None:
        if len(self.candidate_decision_hash) != 64:
            raise ValueError("candidate decision hash must be a SHA-256 digest")
        if Decimal(self.odds) <= 1:
            raise ValueError("risk odds must be greater than 1")
        parse_utc(self.requested_at)


@dataclass(frozen=True)
class RiskDecision:
    passed: bool
    reason: str
    total_open_liability: str
    cluster_liability: str
    approval_id: str | None = None
    approved_stake: str | None = None
    approved_liability: str | None = None


@dataclass(frozen=True)
class RiskApproval:
    approval_id: str
    qualification_record_id: str
    candidate_decision_hash: str
    strategy_decision_contract_hash: str
    bankroll_snapshot_id: str
    bankroll_value: str
    approved_unit_tier: str
    approved_stake: str
    approved_liability: str
    side: BetSide
    odds: str
    risk_policy_version: str
    risk_policy_digest: str
    safety_state_id: str
    issued_at: str
    expires_at: str
    status: str = "APPROVED_NOT_CONSUMED"
    consumed_by_order_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "approval_id",
            "qualification_record_id",
            "candidate_decision_hash",
            "strategy_decision_contract_hash",
            "bankroll_snapshot_id",
            "risk_policy_digest",
            "safety_state_id",
        ):
            if len(getattr(self, name)) != 64:
                raise ValueError(f"{name} must be a SHA-256 digest")
        for value in (self.issued_at, self.expires_at):
            parse_utc(value)
        if Decimal(self.approved_stake) <= 0 or Decimal(self.approved_liability) < 0:
            raise ValueError("approved stake/liability is invalid")
        if self.compute_id() != self.approval_id:
            raise ValueError("risk approval ID mismatch")

    def identity_dict(self) -> dict:
        value = asdict(self)
        value.pop("approval_id")
        value.pop("status")
        value.pop("consumed_by_order_id")
        value["side"] = self.side.value
        value["bankroll_value"] = canonical_decimal(self.bankroll_value)
        value["approved_stake"] = canonical_decimal(self.approved_stake)
        value["approved_liability"] = canonical_decimal(self.approved_liability)
        value["odds"] = canonical_decimal(self.odds)
        value["issued_at"] = iso_utc(self.issued_at)
        value["expires_at"] = iso_utc(self.expires_at)
        return value

    def compute_id(self) -> str:
        return sha256_bytes(canonical_json(self.identity_dict()))

    def to_dict(self) -> dict:
        value = asdict(self)
        value["side"] = self.side.value
        return value

    @classmethod
    def create(cls, **fields) -> "RiskApproval":
        normalized = dict(fields)
        normalized["side"] = BetSide(normalized["side"])
        normalized["bankroll_value"] = canonical_decimal(normalized["bankroll_value"])
        normalized["approved_stake"] = canonical_decimal(normalized["approved_stake"])
        normalized["approved_liability"] = canonical_decimal(normalized["approved_liability"])
        normalized["odds"] = canonical_decimal(normalized["odds"])
        normalized["issued_at"] = iso_utc(normalized["issued_at"])
        normalized["expires_at"] = iso_utc(normalized["expires_at"])
        provisional = dict(normalized)
        provisional["side"] = normalized["side"].value
        return cls(approval_id=sha256_bytes(canonical_json(provisional)), **normalized)


@dataclass(frozen=True)
class RebaseDecision:
    previous_bankroll: str
    new_bankroll: str
    direction: str
    trigger: str
    policy_version: str
    snapshot_id: str


class RiskAuditLog:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    def append(self, event_type: str, payload: dict) -> str:
        return self.log.append({"record_type": event_type, **payload})

    def verify(self) -> int:
        return self.log.verify()


class RiskEngine:
    """Durable reservations derived only from qualification, bankroll and safety owners."""

    def __init__(
        self,
        *,
        policy: PolicySet,
        bankrolls: BankrollSnapshotStore,
        qualifications: QualificationRecordStore,
        safety: SafetyStateStore,
        audit_log: RiskAuditLog,
    ):
        dependencies = (policy, bankrolls, qualifications, safety, audit_log)
        if any(value is None for value in dependencies):
            raise TypeError("RiskEngine requires all durable authority dependencies")
        if not isinstance(policy, PolicySet):
            raise TypeError("risk policy must be a PolicySet")
        self.policy_set = policy
        self.policy = policy.risk
        self.bankrolls = bankrolls
        self.qualifications = qualifications
        self.safety = safety
        self.audit_log = audit_log
        # A hash-valid but semantically incompatible active event is not an
        # empty reservation. Validate the durable heads on startup as well as
        # at each later transactional replay.
        self.bankrolls.history()
        self.safety.history()
        self._exposures(self.audit_log.log.records())

    @staticmethod
    def _open(exposure: Exposure) -> bool:
        return exposure.state in {
            ExposureState.MATCHED,
            ExposureState.PARTIALLY_MATCHED,
            ExposureState.UNMATCHED,
            ExposureState.PENDING,
            ExposureState.UNKNOWN,
        }

    @staticmethod
    def _approval_from_row(row: dict) -> RiskApproval:
        fields = {key: row[key] for key in RiskApproval.__dataclass_fields__}
        fields["side"] = BetSide(fields["side"])
        return RiskApproval(**fields)

    @staticmethod
    def _exposure_from_row(row: dict) -> Exposure:
        fields = {key: row[key] for key in Exposure.__dataclass_fields__}
        fields["state"] = ExposureState(fields["state"])
        fields["correlation_cluster_ids"] = tuple(fields["correlation_cluster_ids"])
        return Exposure(**fields)

    def _exposures(self, rows: tuple[dict, ...] | list[dict]) -> list[Exposure]:
        latest: dict[str, Exposure] = {}
        approvals: dict[str, RiskApproval] = {}
        consumed: set[str] = set()
        candidate_hashes: set[str] = set()
        schemas = {
            "risk_exposure_recorded": "risk-exposure-v2",
            "risk_approval_created": "risk-approval-v2",
            "risk_approval_consumed": "risk-approval-v2",
            "risk_reservation_transition": "risk-reservation-v2",
        }
        for row in rows:
            event = row.get("record_type")
            if event not in schemas or row.get("schema_version") != schemas[event]:
                raise RegistryConflict("unsupported or missing active risk event schema")
            try:
                if event == "risk_exposure_recorded":
                    exposure = self._exposure_from_row(row)
                    parse_utc(row["recorded_at"])
                    if exposure.exposure_id in latest:
                        raise RegistryConflict("duplicate risk exposure identity")
                    latest[exposure.exposure_id] = exposure
                elif event == "risk_approval_created":
                    approval = self._approval_from_row(row)
                    clusters = row["correlation_cluster_ids"]
                    if not isinstance(clusters, list) or any(
                        not isinstance(cluster, str) or not cluster for cluster in clusters
                    ):
                        raise RegistryConflict("risk approval clusters are invalid")
                    if (
                        approval.status != "APPROVED_NOT_CONSUMED"
                        or approval.consumed_by_order_id is not None
                        or parse_utc(approval.issued_at) >= parse_utc(approval.expires_at)
                        or approval.approval_id in latest
                        or approval.candidate_decision_hash in candidate_hashes
                    ):
                        raise RegistryConflict("risk approval replay identity is invalid")
                    approvals[approval.approval_id] = approval
                    candidate_hashes.add(approval.candidate_decision_hash)
                    latest[approval.approval_id] = Exposure(
                        exposure_id=approval.approval_id,
                        candidate_decision_hash=approval.candidate_decision_hash,
                        liability=approval.approved_liability,
                        state=ExposureState.PENDING,
                        correlation_cluster_ids=tuple(clusters),
                        affected_scope=row["affected_scope"],
                    )
                elif event == "risk_approval_consumed":
                    approval_id = row["approval_id"]
                    if (
                        approval_id not in approvals
                        or approval_id in consumed
                        or latest[approval_id].state != ExposureState.PENDING
                        or row["candidate_decision_hash"]
                        != approvals[approval_id].candidate_decision_hash
                        or not isinstance(row["order_id"], str)
                        or not row["order_id"]
                    ):
                        raise RegistryConflict("risk approval consumption replay is invalid")
                    consumed_at = parse_utc(row["consumed_at"])
                    if consumed_at >= parse_utc(approvals[approval_id].expires_at):
                        raise RegistryConflict("risk approval was consumed after expiry")
                    consumed.add(approval_id)
                else:
                    approval_id = row["approval_id"]
                    if approval_id not in approvals or approval_id not in latest:
                        raise RegistryConflict("reservation transition has no approval")
                    current = latest[approval_id]
                    prior = ExposureState(row["from_state"])
                    target = ExposureState(row["to_state"])
                    if (
                        current.state != prior
                        or current.state in {ExposureState.SETTLED, ExposureState.VOID}
                        or target not in {
                            ExposureState.SETTLED, ExposureState.VOID, ExposureState.UNKNOWN
                        }
                    ):
                        raise RegistryConflict("reservation transition is invalid")
                    parse_utc(row["occurred_at"])
                    latest[approval_id] = replace(current, state=target)
            except (KeyError, TypeError, ValueError) as exc:
                if isinstance(exc, RegistryConflict):
                    raise
                raise RegistryConflict("incomplete or invalid active risk event") from exc
        return list(latest.values())

    def stake_for_units(self, bankroll: str, units: str) -> str:
        return canonical_decimal(self.policy.stake_amount(bankroll, parse_tier(units, policy=self.policy)))

    def record_exposure(self, exposure: Exposure, *, recorded_at: str) -> Exposure:
        payload = {
            "record_type": "risk_exposure_recorded",
            "schema_version": "risk-exposure-v2",
            **exposure.to_dict(),
            "recorded_at": iso_utc(recorded_at),
        }

        def build(rows: tuple[dict, ...]) -> dict | None:
            self._exposures(rows)
            matches = [
                row
                for row in rows
                if row.get("record_type") == "risk_exposure_recorded"
                and row.get("schema_version") == "risk-exposure-v2"
                and row.get("exposure_id") == exposure.exposure_id
            ]
            if not matches:
                return payload
            expected = exposure.to_dict()
            if all({key: row.get(key) for key in expected} == expected for row in matches):
                return None
            raise RegistryConflict("risk exposure ID conflict")

        self.audit_log.log.transaction(build)
        return exposure

    def approve(self, request: RiskRequest) -> RiskDecision:
        decision_holder: dict[str, RiskDecision] = {}

        def build(rows: tuple[dict, ...]) -> dict | None:
            # No mutable authority fact is captured before the coordinator
            # locks. Bankroll, safety and qualification writers use these same
            # per-log locks; risk owns the primary lock through its fsynced
            # approval append. JSONL, not SQLite, remains the business truth.
            all_exposures = self._exposures(rows)
            try:
                qualification = self.qualifications.get_for_new_risk(
                    request.qualification_record_id, at=request.requested_at,
                )
                bankroll = self.bankrolls.current()
                safety = self.safety.current()
            except Exception:
                decision_holder["value"] = RiskDecision(
                    False, "authority_unavailable", "0", "0"
                )
                return None
            if safety.kill_switch_active:
                decision_holder["value"] = RiskDecision(False, "kill_switch_active", "0", "0")
                return None
            if request.bankroll_snapshot_id != bankroll.snapshot_id:
                decision_holder["value"] = RiskDecision(False, "stale_bankroll_snapshot", "0", "0")
                return None
            if qualification.candidate_decision_hash != request.candidate_decision_hash:
                decision_holder["value"] = RiskDecision(False, "qualification_candidate_mismatch", "0", "0")
                return None
            if qualification.active_policy_digest != self.policy_set.digest:
                decision_holder["value"] = RiskDecision(False, "qualification_policy_mismatch", "0", "0")
                return None
            try:
                output = self.qualifications.outputs.get(qualification.decision_output_hash)
            except Exception:
                decision_holder["value"] = RiskDecision(False, "authority_unavailable", "0", "0")
                return None
            if (request.side.value != output["side"]
                    or Decimal(request.odds) < Decimal(output["requested_odds_min"])
                    or Decimal(request.odds) > Decimal(output["requested_odds_max"])):
                decision_holder["value"] = RiskDecision(
                    False, "decision_output_execution_mismatch", "0", "0"
                )
                return None
            if parse_utc(request.requested_at) >= parse_utc(qualification.expires_at):
                decision_holder["value"] = RiskDecision(False, "qualification_expired", "0", "0")
                return None
            try:
                tier = parse_tier(qualification.approved_tier, policy=self.policy)
            except ValueError:
                decision_holder["value"] = RiskDecision(False, "invalid_qualification_tier", "0", "0")
                return None
            if request.expected_tier is not None and request.expected_tier != qualification.approved_tier:
                decision_holder["value"] = RiskDecision(False, "caller_tier_mismatch", "0", "0")
                return None
            stake = self.policy.stake_amount(bankroll.bankroll, tier)
            fragment = MatchedFragment("risk-proposal", request.side, Decimal(request.odds), stake)
            liability = money(fragment.liability)
            if request.expected_stake is not None and Decimal(request.expected_stake) != stake:
                decision_holder["value"] = RiskDecision(False, "caller_stake_mismatch", "0", "0")
                return None
            if request.expected_liability is not None and Decimal(request.expected_liability) != liability:
                decision_holder["value"] = RiskDecision(False, "caller_liability_mismatch", "0", "0")
                return None
            approval = RiskApproval.create(
                qualification_record_id=qualification.qualification_record_id,
                candidate_decision_hash=request.candidate_decision_hash,
                strategy_decision_contract_hash=qualification.strategy_decision_contract_hash,
                bankroll_snapshot_id=bankroll.snapshot_id,
                bankroll_value=bankroll.bankroll,
                approved_unit_tier=qualification.approved_tier,
                approved_stake=canonical_decimal(stake),
                approved_liability=canonical_decimal(liability),
                side=request.side,
                odds=request.odds,
                risk_policy_version=self.policy.version,
                risk_policy_digest=self.policy.digest,
                safety_state_id=safety.state_id,
                issued_at=request.requested_at,
                expires_at=qualification.expires_at,
            )
            if any(
                row.get("record_type") == "risk_approval_created"
                and row.get("schema_version") == "risk-approval-v2"
                and row.get("candidate_decision_hash") == request.candidate_decision_hash
                for row in rows
            ):
                decision_holder["value"] = RiskDecision(
                    False, "duplicate_order_intent", "0", "0"
                )
                return None
            open_exposures = [item for item in all_exposures if self._open(item)]
            if any(item.state == ExposureState.UNKNOWN for item in open_exposures):
                decision_holder["value"] = RiskDecision(
                    False, "unknown_exposure_blocks_new_risk", "0", "0"
                )
                return None
            open_liability = sum(
                (item.liability_amount for item in open_exposures), Decimal("0")
            )
            proposed_total = open_liability + liability
            if proposed_total > Decimal(bankroll.bankroll) * self.policy.max_open_liability_fraction:
                decision_holder["value"] = RiskDecision(
                    False,
                    "open_liability_limit",
                    canonical_decimal(proposed_total),
                    "0",
                )
                return None
            requested_clusters = set(request.correlation_cluster_ids)
            cluster_liability = liability
            for item in open_exposures:
                if requested_clusters.intersection(item.correlation_cluster_ids):
                    cluster_liability += item.liability_amount
            if (
                requested_clusters
                and cluster_liability
                > Decimal(bankroll.bankroll) * self.policy.correlated_cluster_fraction
            ):
                decision_holder["value"] = RiskDecision(
                    False,
                    "correlation_cluster_limit",
                    canonical_decimal(proposed_total),
                    canonical_decimal(cluster_liability),
                )
                return None
            decision_holder["value"] = RiskDecision(
                True,
                "risk_approved",
                canonical_decimal(proposed_total),
                canonical_decimal(cluster_liability),
                approval.approval_id,
                approval.approved_stake,
                approval.approved_liability,
            )
            return {
                "record_type": "risk_approval_created",
                "schema_version": "risk-approval-v2",
                **approval.to_dict(),
                "correlation_cluster_ids": list(request.correlation_cluster_ids),
                "affected_scope": request.affected_scope,
            }

        self.audit_log.log.transaction(
            build,
            read_locks=(
                self.bankrolls.log, self.safety.log, self.qualifications.log,
                self.qualifications.bindings.log,
            ),
        )
        return decision_holder["value"]

    def get_approval(self, approval_id: str) -> RiskApproval:
        rows = self.audit_log.log.records()
        self._exposures(rows)
        matches = [
            self._approval_from_row(row)
            for row in rows
            if row.get("record_type") == "risk_approval_created"
            and row.get("schema_version") == "risk-approval-v2"
            and row.get("approval_id") == approval_id
        ]
        if len(matches) != 1:
            raise RegistryConflict(f"unknown or ambiguous risk approval: {approval_id}")
        approval = matches[0]
        consumptions = [
            row
            for row in rows
            if row.get("record_type") == "risk_approval_consumed"
            and row.get("approval_id") == approval_id
        ]
        if len(consumptions) > 1:
            raise RegistryConflict("risk approval has multiple consumption events")
        if consumptions:
            approval = replace(
                approval,
                status="CONSUMED",
                consumed_by_order_id=consumptions[0]["order_id"],
            )
        return approval

    def consume_for_order(
        self, approval_id: str, *, order_id: str, consumed_at: str
    ) -> RiskApproval:
        consumed_at = iso_utc(consumed_at)
        result: dict[str, RiskApproval] = {}

        def build(rows: tuple[dict, ...]) -> dict | None:
            self._exposures(rows)
            matches = [
                self._approval_from_row(row)
                for row in rows
                if row.get("record_type") == "risk_approval_created"
                and row.get("schema_version") == "risk-approval-v2"
                and row.get("approval_id") == approval_id
            ]
            if len(matches) != 1:
                raise RegistryConflict(f"unknown risk approval: {approval_id}")
            approval = matches[0]
            qualification = self.qualifications.get_for_new_risk(
                approval.qualification_record_id, at=consumed_at,
            )
            if qualification.candidate_decision_hash != approval.candidate_decision_hash:
                raise RegistryConflict("risk approval lacks exact V3 output lineage")
            consumptions = [
                row
                for row in rows
                if row.get("record_type") == "risk_approval_consumed"
                and row.get("approval_id") == approval_id
            ]
            if consumptions:
                if len(consumptions) == 1 and consumptions[0]["order_id"] == order_id:
                    result["value"] = replace(
                        approval, status="CONSUMED", consumed_by_order_id=order_id
                    )
                    return None
                raise RegistryConflict("risk approval is single-use")
            if parse_utc(consumed_at) >= parse_utc(approval.expires_at):
                raise RegistryConflict("risk approval is expired")
            result["value"] = replace(
                approval, status="CONSUMED", consumed_by_order_id=order_id
            )
            return {
                "record_type": "risk_approval_consumed",
                "schema_version": "risk-approval-v2",
                "approval_id": approval_id,
                "candidate_decision_hash": approval.candidate_decision_hash,
                "order_id": order_id,
                "consumed_at": consumed_at,
            }

        self.audit_log.log.transaction(
            build, read_locks=(self.qualifications.log, self.qualifications.bindings.log),
        )
        return result["value"]

    def reserved_exposures(self) -> tuple[Exposure, ...]:
        return tuple(
            item
            for item in self._exposures(self.audit_log.log.records())
            if self._open(item)
        )

    def transition_reservation(
        self,
        approval_id: str,
        state: ExposureState,
        *,
        occurred_at: str,
    ) -> Exposure:
        result: dict[str, Exposure] = {}

        def build(rows: tuple[dict, ...]) -> dict:
            exposures = {item.exposure_id: item for item in self._exposures(rows)}
            if approval_id not in exposures:
                raise RegistryConflict("unknown reservation")
            current = exposures[approval_id]
            if state not in {ExposureState.SETTLED, ExposureState.VOID, ExposureState.UNKNOWN}:
                raise RegistryConflict("unsupported reservation transition")
            if current.state in {ExposureState.SETTLED, ExposureState.VOID}:
                raise RegistryConflict("terminal reservation cannot transition")
            updated = replace(current, state=state)
            result["value"] = updated
            return {
                "record_type": "risk_reservation_transition",
                "schema_version": "risk-reservation-v2",
                "approval_id": approval_id,
                "from_state": current.state.value,
                "to_state": state.value,
                "occurred_at": iso_utc(occurred_at),
            }

        self.audit_log.log.transaction(build)
        return result["value"]

    def approval_still_valid(self, approval_id: str, *, at: str) -> bool:
        try:
            approval = self.get_approval(approval_id)
            qualification = self.qualifications.get_for_new_risk(
                approval.qualification_record_id, at=at,
            )
            if qualification.candidate_decision_hash != approval.candidate_decision_hash:
                return False
            if parse_utc(at) >= parse_utc(approval.expires_at):
                return False
            if self.safety.current().kill_switch_active:
                return False
            if self.bankrolls.current().snapshot_id != approval.bankroll_snapshot_id:
                return False
            rows = self.audit_log.log.records()
            # A reservation is derived from the approval event, not from the
            # approval's CONSUMED flag.  An explicit exposure reusing that ID
            # would make the coupled state ambiguous even if ordinary replay
            # happened to choose the approval-derived value.
            if any(
                row.get("record_type") == "risk_exposure_recorded"
                and row.get("exposure_id") == approval.approval_id
                for row in rows
            ):
                return False
            exposures = self._exposures(rows)
            own = [item for item in exposures if item.exposure_id == approval.approval_id]
            if len(own) != 1:
                return False
            reservation = own[0]
            if (
                reservation.state != ExposureState.PENDING
                or reservation.candidate_decision_hash != approval.candidate_decision_hash
                or reservation.liability_amount != Decimal(approval.approved_liability)
            ):
                return False
            if any(item.state == ExposureState.UNKNOWN for item in exposures):
                return False
            return approval.status in {"APPROVED_NOT_CONSUMED", "CONSUMED"}
        except Exception:
            return False

    def rebase(
        self,
        new_bankroll: str,
        *,
        captured_at: str,
        scheduled_weekly: bool,
        drawdown_triggered: bool,
    ) -> RebaseDecision:
        current = self.bankrolls.current()
        previous = Decimal(current.bankroll)
        new = Decimal(new_bankroll)
        if new <= 0:
            raise ValueError("bankroll values must be positive")
        if new > previous and not scheduled_weekly:
            raise ValueError("upward bankroll rebase is weekly only")
        if new < previous and not (scheduled_weekly or drawdown_triggered):
            raise ValueError("downward bankroll rebase requires schedule or trigger")
        direction = "upward" if new > previous else "downward" if new < previous else "unchanged"
        trigger = "weekly_checkpoint" if scheduled_weekly else "drawdown_trigger"
        snapshot = BankrollSnapshot.create(
            bankroll=canonical_decimal(new),
            captured_at=captured_at,
            rebase_reason=trigger,
            parent_snapshot_id=current.snapshot_id,
        )
        self.bankrolls.append(snapshot)
        return RebaseDecision(
            canonical_decimal(previous),
            canonical_decimal(new),
            direction,
            trigger,
            self.policy.version,
            snapshot.snapshot_id,
        )

    def risk_ok(self, candidate) -> bool | None:
        try:
            if self.safety.current().kill_switch_active:
                return False
            self.bankrolls.current()
            rows = self.audit_log.log.records()
            if any(item.state == ExposureState.UNKNOWN for item in self._exposures(rows)):
                return False
            if any(
                row.get("record_type") == "risk_approval_created"
                and row.get("schema_version") == "risk-approval-v2"
                and row.get("candidate_decision_hash") == candidate.candidate_decision_hash
                for row in rows
            ):
                return False
            return True
        except Exception:
            return None

    def correlation_ok(self, candidate) -> bool | None:
        return self.risk_ok(candidate)
