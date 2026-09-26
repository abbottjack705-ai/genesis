"""Durable, authority-derived offline risk and approval contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .accounting import BetSide, MatchedFragment, money
from .decision import candidate_v3_decision_hash
from .owner_binding import RiskOwnerBinding, log_path
from .policy import PolicySet, canonical_decimal, parse_tier
from .registry import AppendOnlyJsonl, RegistryConflict, StrategyRegistry
from .repro import canonical_json, sha256_bytes
from .selection import QualificationRecordStore
from .time import iso_utc, parse_utc

if TYPE_CHECKING:
    from .release_proof import OfflinePaperReleaseProofStore


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


class _ReplayChecked:
    """A risk-log builder whose row its engine replays with the history first (N3).

    The replayed row is the one every later reader gets: parsed and verified
    from the exact line the append writes. That same row, not the builder's
    object, is what the storage then appends, and it is replayed after the
    verified history, not a copy the builder was handed (T6 F-3).
    """

    def __init__(self, engine: RiskEngine, build: Callable[[tuple[dict, ...]], dict | None]):
        self.engine = engine
        self.build = build

    def __call__(self, rows: tuple[dict, ...]) -> dict | None:
        record = self.build(deepcopy(rows))
        if not isinstance(record, dict):
            return record
        row = AppendOnlyJsonl.appended_row(rows, record)
        self.engine._exposures((*rows, row))
        return {
            key: value for key, value in row.items()
            if key not in {"previous_hash", "record_hash"}
        }


class _RiskLogStorage(AppendOnlyJsonl):
    """Risk-log storage that appends only rows its engine has replayed (F-3a).

    RiskEngine actions pass their own replay-checked builders. Any other
    builder, such as a direct ``append``, is replayed by the engine composed
    over this storage before a byte is written; with no engine the storage
    appends nothing.
    """

    def __init__(self, path: str | Path):
        super().__init__(path)
        self._engine: RiskEngine | None = None

    def transaction(
        self,
        build_record: Callable[[tuple[dict, ...]], dict | None],
        *,
        read_locks: tuple[AppendOnlyJsonl, ...] = (),
    ) -> str | None:
        engine = self._engine
        if isinstance(build_record, _ReplayChecked) and build_record.engine is engine:
            checked = build_record
        elif engine is not None:
            checked = _ReplayChecked(engine, build_record)
        else:
            def checked(rows: tuple[dict, ...]) -> None:
                if build_record(rows) is not None:
                    raise RegistryConflict("risk log without its risk engine appends nothing")
                return None
        return super().transaction(checked, read_locks=read_locks)


class RiskAuditLog:
    """The durable risk log. It has no generic event append (T6 F-3a).

    Risk rows are written by RiskEngine actions; its storage appends no row
    that the log's engine has not first replayed with the exact history.
    """

    def __init__(self, path: str | Path):
        self.log = _RiskLogStorage(path)

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
        strategies: StrategyRegistry | None = None,
        modes: object | None = None,
        action_clock: Callable[[str], str] | None = None,
    ):
        dependencies = (policy, bankrolls, qualifications, safety, audit_log)
        if any(value is None for value in dependencies):
            raise TypeError("RiskEngine requires all durable authority dependencies")
        if not isinstance(policy, PolicySet):
            raise TypeError("risk policy must be a PolicySet")
        if not isinstance(audit_log.log, _RiskLogStorage):
            raise TypeError("risk audit log must be a replay-checked RiskAuditLog")
        self.policy_set = policy
        self.policy = policy.risk
        self.bankrolls = bankrolls
        self.qualifications = qualifications
        self.safety = safety
        self.audit_log = audit_log
        self.strategies = strategies
        self.modes = modes
        self.release_proofs: OfflinePaperReleaseProofStore | None = None
        # Real UTC is the default new-action clock. An explicit alternate
        # clock is for synthetic offline tests; request timestamps alone are
        # never production expiry/strategy authority.
        self._action_clock = action_clock or (
            lambda _requested_at: iso_utc(datetime.now(timezone.utc))
        )
        # A hash-valid but semantically incompatible active event is not an
        # empty reservation. Validate the durable heads on startup as well as
        # at each later transactional replay.
        self.bankrolls.history()
        self.safety.history()
        if self.modes is not None:
            self.modes.current()
        self._exposures(self.audit_log.log.records())
        # N2: bind each presented owner kind on first use; every later action
        # verifies its owners against this durable binding.
        self.owner_binding = RiskOwnerBinding(self.audit_log.log)
        self.owner_binding.register(self._risk_owner_paths())
        # F-3a: the first engine composed over this log object replays every
        # append made through its storage by anyone other than itself.
        if self.audit_log.log._engine is None:
            self.audit_log.log._engine = self

    def _risk_owner_paths(self) -> dict[str, Path | None]:
        from .execution import ModeStateStore

        qualifications = self.qualifications
        outputs = getattr(qualifications, "outputs", None)
        return {
            "bankroll": log_path(self.bankrolls),
            "safety": log_path(self.safety),
            "qualification": log_path(qualifications),
            "qualification_binding": log_path(getattr(qualifications, "bindings", None)),
            "qualification_approval": log_path(getattr(qualifications, "approvals", None)),
            "decision_output": getattr(outputs, "root", None),
            "strategy": log_path(self.strategies),
            "mode": self.modes.log.path if type(self.modes) is ModeStateStore else None,
        }

    @staticmethod
    def _release_owner_paths(
        proofs: OfflinePaperReleaseProofStore | None,
    ) -> dict[str, Path | None]:
        if proofs is None:
            return {}
        return {
            "release_proof": log_path(proofs),
            "ledger": log_path(proofs.ledger),
            "order": proofs.execution._audit.path,
        }

    def owner_mismatches(
        self,
        *owner_sets: dict[str, Path | None],
        release_proofs: OfflinePaperReleaseProofStore | None = None,
    ) -> tuple[str, ...]:
        """Owner kinds an action would use that are not this authority's owners."""

        if release_proofs is not None and release_proofs.risk is not self:
            return ("release_proof",)
        return self.owner_binding.mismatches(
            self._risk_owner_paths(),
            self._release_owner_paths(release_proofs),
            *owner_sets,
        )

    def require_bound_owners(
        self,
        *owner_sets: dict[str, Path | None],
        release_proofs: OfflinePaperReleaseProofStore | None = None,
    ) -> None:
        mismatched = self.owner_mismatches(*owner_sets, release_proofs=release_proofs)
        if mismatched:
            raise RegistryConflict(
                f"risk authority owner is not the bound owner: {', '.join(mismatched)}"
            )

    def register_owners(
        self, owners: dict[str, Path | None], *, anchors: tuple[str, ...] = (),
    ) -> None:
        """First-use binding for owners composed after risk construction."""

        self.owner_binding.register(owners, anchors=anchors)

    def attach_release_proofs(self, proofs: OfflinePaperReleaseProofStore) -> None:
        """Install the exact PAPER proof owner after risk/execution construction.

        No release can create spendable capacity while this owner is absent.
        An owner may be installed only once, and its risk identity and audit
        path must match this engine's durable risk log. Its proof log, ledger
        and order log must be this authority's bound owners.
        """
        if proofs.risk is not self:
            raise RegistryConflict("release proof owner is mismatched")

        def bind(rows: tuple[dict, ...]) -> None:
            if self.release_proofs is not None:
                raise RegistryConflict("release proof owner is already installed")
            self.require_bound_owners(release_proofs=proofs)
            self.release_proofs = proofs
            try:
                self._exposures(rows, release_fenced=True)
            except BaseException:
                self.release_proofs = None
                raise
            return None

        try:
            self.audit_log.log.transaction(
                bind, read_locks=(
                    self.owner_binding.log, *self._release_read_locks_for(proofs),
                ),
            )
        except BaseException:
            if self.release_proofs is proofs:
                self.release_proofs = None
            raise

    @staticmethod
    def _release_read_locks_for(
        proofs: OfflinePaperReleaseProofStore | None,
    ) -> tuple[AppendOnlyJsonl, ...]:
        if proofs is None:
            return ()
        return (proofs.log, *proofs.authority_logs)

    def _release_read_locks(self) -> tuple[AppendOnlyJsonl, ...]:
        return self._release_read_locks_for(self.release_proofs)

    @staticmethod
    def _mode_lock_for(modes: object | None) -> tuple[AppendOnlyJsonl, ...]:
        from .execution import ModeStateStore

        return (modes.log,) if type(modes) is ModeStateStore else ()

    @staticmethod
    def _coherent_paper_mode(modes: object | None, safety: SafetyState) -> bool:
        from .config import OperationalMode
        from .execution import ModeStateStore

        if type(modes) is not ModeStateStore:
            return False
        try:
            head = modes.current()
            return (
                head.mode == OperationalMode.PAPER
                and not safety.kill_switch_active
                and iso_utc(head.occurred_at) == iso_utc(safety.recorded_at)
                and safety.reason == "mode:paper"
            )
        except Exception:
            return False

    @staticmethod
    def _open(exposure: Exposure) -> bool:
        return exposure.state in {
            ExposureState.MATCHED,
            ExposureState.PARTIALLY_MATCHED,
            ExposureState.UNMATCHED,
            ExposureState.PENDING,
            ExposureState.UNKNOWN,
        }

    def _portfolio_capacity(
        self,
        exposures: list[Exposure],
        *,
        bankroll: Decimal,
        proposed_clusters: set[str],
        extra_liability: Decimal = Decimal("0"),
    ) -> tuple[str | None, Decimal, Decimal]:
        """Check current capacity without charging an owned reservation twice.

        At approval ``extra_liability`` is the not-yet-reserved proposal. At
        pending/send it is zero because the exact approval reservation is
        already one of ``exposures``. An unrelated factual exposure remains
        additive. Existing breached positions are retained, never erased to
        create apparent new capacity.
        """

        open_items = [item for item in exposures if self._open(item)]
        total = sum((item.liability_amount for item in open_items), Decimal("0")) + extra_liability
        if total > bankroll * self.policy.max_open_liability_fraction:
            return "open_liability_limit", total, Decimal("0")
        cluster_limit = bankroll * self.policy.correlated_cluster_fraction
        for cluster in sorted({name for item in open_items for name in item.correlation_cluster_ids}):
            current_cluster = sum(
                (item.liability_amount for item in open_items
                 if cluster in item.correlation_cluster_ids), Decimal("0"),
            )
            if current_cluster > cluster_limit:
                return "existing_correlation_cluster_limit", total, current_cluster
        selected_cluster = extra_liability + sum(
            (item.liability_amount for item in open_items
             if proposed_clusters.intersection(item.correlation_cluster_ids)),
            Decimal("0"),
        )
        if proposed_clusters and selected_cluster > cluster_limit:
            return "correlation_cluster_limit", total, selected_cluster
        return None, total, selected_cluster

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

    def _bound_approval_clusters(self, approval: RiskApproval) -> tuple[str, ...] | None:
        """Reconstruct v3 reservation membership from its immutable output.

        Historical v2 qualifications have no decision-output identity. They
        remain readable for audit and settlement, but cannot authorize new
        risk through ``get_for_new_risk``. A v3 approval must be coherent with
        its exact qualification and content-addressed output on every replay;
        a copied cluster list in the approval event is never authority.
        """

        try:
            qualification = self.qualifications.get(approval.qualification_record_id)
            if qualification.schema_version == "qualification-record-v2":
                if (
                    qualification.candidate_decision_hash != approval.candidate_decision_hash
                    or qualification.strategy_decision_contract_hash
                    != approval.strategy_decision_contract_hash
                ):
                    raise RegistryConflict("historical approval qualification mismatch")
                return None
            if qualification.schema_version != "qualification-record-v3":
                raise RegistryConflict("unsupported approval qualification schema")
            output = self.qualifications.outputs.get(qualification.decision_output_hash)
            expected_candidate_hash = candidate_v3_decision_hash(
                strategy_decision_contract_hash=qualification.strategy_decision_contract_hash,
                feature_manifest_hash=qualification.feature_manifest_hash,
                evidence_pack_hash=output["evidence_pack_hash"],
                decision_output_hash=qualification.decision_output_hash,
            )
            if any((
                approval.candidate_decision_hash != qualification.candidate_decision_hash,
                approval.strategy_decision_contract_hash
                != qualification.strategy_decision_contract_hash,
                qualification.candidate_decision_hash != expected_candidate_hash,
                qualification.feature_manifest_hash != output["feature_manifest_hash"],
                qualification.strategy_decision_contract_hash
                != output["strategy_decision_contract_hash"],
                qualification.approved_tier != output["approved_tier"],
                iso_utc(qualification.expires_at) != output["expires_at"],
                iso_utc(qualification.decision_at) != output["decision_at"],
                qualification.comparability_group_id != output["comparability_group_id"],
                qualification.market_capability_id != output["market_capability_id"],
            )):
                raise RegistryConflict("v3 approval/output lineage mismatch")
            return tuple(output["correlation_cluster_ids"])
        except RegistryConflict:
            raise
        except Exception as exc:
            raise RegistryConflict("approval dependence authority unavailable") from exc

    def _exposures(
        self, rows: tuple[dict, ...] | list[dict], *, release_fenced: bool = False,
    ) -> list[Exposure]:
        latest: dict[str, Exposure] = {}
        approvals: dict[str, RiskApproval] = {}
        consumed: set[str] = set()
        raw_states: dict[str, ExposureState] = {}
        release_rows: dict[str, dict] = {}
        candidate_hashes: set[str] = set()
        schemas = {
            "risk_exposure_recorded": "risk-exposure-v2",
            "risk_approval_created": "risk-approval-v2",
            "risk_approval_consumed": "risk-approval-v2",
            "risk_reservation_transition": "risk-reservation-v2",
            "risk_reservation_release": "risk-reservation-release-v1",
            "risk_reservation_legacy_release": "risk-reservation-legacy-release-v1",
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
                    bound_clusters = self._bound_approval_clusters(approval)
                    if bound_clusters is not None and clusters != list(bound_clusters):
                        raise RegistryConflict(
                            "risk approval clusters differ from bound decision output"
                        )
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
                    raw_states[approval.approval_id] = ExposureState.PENDING
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
                elif event == "risk_reservation_transition":
                    approval_id = row["approval_id"]
                    if approval_id not in approvals or approval_id not in latest:
                        raise RegistryConflict("reservation transition has no approval")
                    current = latest[approval_id]
                    prior = ExposureState(row["from_state"])
                    target = ExposureState(row["to_state"])
                    if (
                        raw_states[approval_id] != prior
                        or approval_id in release_rows
                        or raw_states[approval_id] in {ExposureState.SETTLED, ExposureState.VOID}
                        or target not in {
                            ExposureState.SETTLED, ExposureState.VOID, ExposureState.UNKNOWN
                        }
                    ):
                        raise RegistryConflict("reservation transition is invalid")
                    parse_utc(row["occurred_at"])
                    raw_states[approval_id] = target
                    # A historical bare terminal event is audit history, not
                    # proof of no further fills. Keep its full liability charged.
                    latest[approval_id] = replace(current, state=ExposureState.UNKNOWN)
                else:
                    approval_id = row["approval_id"]
                    approval = approvals.get(approval_id)
                    legacy_release = event == "risk_reservation_legacy_release"
                    unconsumed_release = not legacy_release and row["order_id"] is None
                    consumption_invalid = (
                        approval_id in consumed if unconsumed_release
                        else approval_id not in consumed
                    )
                    order_identity_invalid = (
                        row["order_head_record_hash"] is not None
                        or row["release_reason"] != "UNSENT_REJECTED"
                        or row["to_state"] != ExposureState.VOID.value
                    ) if unconsumed_release else (
                        not isinstance(row["order_id"], str)
                        or not row["order_id"]
                        or not isinstance(row["order_head_record_hash"], str)
                        or len(row["order_head_record_hash"]) != 64
                    )
                    common_release_fields = {
                        "record_type", "schema_version", "approval_id",
                        "qualification_record_id", "candidate_decision_hash",
                        "order_id", "from_state", "to_state", "release_reason",
                        "order_head_record_hash", "fill_proofs",
                        "reconciliation_proof_hash", "occurred_at",
                        "previous_hash", "sequence", "record_hash",
                    }
                    lineage_field = (
                        "legacy_qualification_record_hash"
                        if legacy_release else "decision_output_hash"
                    )
                    allowed_reasons = (
                        {"FILLS_SETTLED", "FILLS_VOID"}
                        if legacy_release else {
                            "UNSENT_REJECTED", "UNMATCHED_CANCEL_CONFIRMED",
                            "FILLS_SETTLED", "FILLS_VOID",
                        }
                    )
                    if (
                        set(row) != common_release_fields | {lineage_field}
                        or
                        approval is None or consumption_invalid
                        or approval_id in release_rows
                        or raw_states[approval_id] not in {
                            ExposureState.PENDING, ExposureState.UNKNOWN,
                            ExposureState.SETTLED, ExposureState.VOID,
                        }
                        or row["from_state"] != latest[approval_id].state.value
                        or row["to_state"] not in {
                            ExposureState.SETTLED.value, ExposureState.VOID.value,
                        }
                        or row["candidate_decision_hash"]
                        != approval.candidate_decision_hash
                        or row["qualification_record_id"]
                        != approval.qualification_record_id
                        or order_identity_invalid
                        or row["release_reason"] not in allowed_reasons
                        or not isinstance(row["reconciliation_proof_hash"], str)
                        or len(row["reconciliation_proof_hash"]) != 64
                        or not isinstance(row[lineage_field], str)
                        or len(row[lineage_field]) != 64
                    ):
                        raise RegistryConflict("reservation release lineage is invalid")
                    fill_proofs = row["fill_proofs"]
                    if (
                        not isinstance(fill_proofs, list)
                        or [item.get("fill_id") for item in fill_proofs]
                        != sorted({item.get("fill_id") for item in fill_proofs})
                        or any(
                            not isinstance(item, dict)
                            or set(item) != {
                                "fill_id", "fill_record_hash",
                                "current_head_event_id", "current_head_record_hash",
                            }
                            or not isinstance(item["fill_id"], str)
                            or not item["fill_id"]
                            or not isinstance(item["current_head_event_id"], str)
                            or not item["current_head_event_id"]
                            or any(
                                not isinstance(item[name], str) or len(item[name]) != 64
                                for name in ("fill_record_hash", "current_head_record_hash")
                            )
                            for item in fill_proofs
                        )
                        or (row["release_reason"] in {"FILLS_SETTLED", "FILLS_VOID"}
                            and not fill_proofs)
                        or (row["release_reason"] in {
                            "UNSENT_REJECTED", "UNMATCHED_CANCEL_CONFIRMED",
                        } and fill_proofs)
                    ):
                        raise RegistryConflict("reservation release fill proof is invalid")
                    parse_utc(row["occurred_at"])
                    release_rows[approval_id] = row
                    raw_states[approval_id] = ExposureState(row["to_state"])
                    latest[approval_id] = replace(
                        latest[approval_id], state=ExposureState.UNKNOWN,
                    )
            except (KeyError, TypeError, ValueError) as exc:
                if isinstance(exc, RegistryConflict):
                    raise
                raise RegistryConflict("incomplete or invalid active risk event") from exc
        if release_rows and release_fenced and self.release_proofs is not None:
            proof_rows = tuple(self.release_proofs.log.records())
            qualification_rows = tuple(self.qualifications.log.records())
            order_rows = tuple(self.release_proofs.execution._audit.records())
            ledger_rows = tuple(self.release_proofs.ledger.log.records())
            for approval_id, row in release_rows.items():
                try:
                    legacy_release = (
                        row["record_type"] == "risk_reservation_legacy_release"
                    )
                    proof = self.release_proofs.validate_current_locked(
                        row["reconciliation_proof_hash"], proof_rows=proof_rows,
                        risk_rows=tuple(rows),
                        qualification_rows=qualification_rows,
                        order_rows=order_rows, ledger_rows=ledger_rows,
                    )
                    if (
                        proof["approval_id"] != approval_id
                        or proof["order_id"] != row["order_id"]
                        or proof["qualification_record_id"]
                        != row["qualification_record_id"]
                        or proof["candidate_decision_hash"]
                        != row["candidate_decision_hash"]
                        or proof["record_type"] != (
                            "offline_paper_legacy_release_proof"
                            if legacy_release else "offline_paper_release_proof"
                        )
                        or proof.get(
                            "legacy_qualification_record_hash"
                            if legacy_release else "decision_output_hash"
                        ) != row[
                            "legacy_qualification_record_hash"
                            if legacy_release else "decision_output_hash"
                        ]
                        or proof["release_reason"] != row["release_reason"]
                        or proof["order_head_record_hash"]
                        != row["order_head_record_hash"]
                        or [
                            {
                                "fill_id": item["fill_id"],
                                "fill_record_hash": item["fill_record_hash"],
                                "current_head_event_id": item["head_event_id"],
                                "current_head_record_hash": item["head_record_hash"],
                            }
                            for item in proof["fill_proofs"]
                        ] != row["fill_proofs"]
                        or (ExposureState.VOID.value
                            if proof["release_reason"] in {
                                "FILLS_VOID", "UNSENT_REJECTED",
                                "UNMATCHED_CANCEL_CONFIRMED",
                            } else ExposureState.SETTLED.value) != row["to_state"]
                        or parse_utc(row["occurred_at"])
                        < parse_utc(proof["occurred_at"])
                    ):
                        raise RegistryConflict("reservation release proof binding changed")
                except (RegistryConflict, KeyError, TypeError, ValueError):
                    # Preserve the event, but do not mint new capacity from a
                    # stale/false proof or a late fill after issuance.
                    continue
                latest[approval_id] = replace(
                    latest[approval_id], state=ExposureState(row["to_state"]),
                )
        return list(latest.values())

    def _replay_checked(
        self, build: Callable[[tuple[dict, ...]], dict | None],
    ) -> Callable[[tuple[dict, ...]], dict | None]:
        """N3: refuse any risk append after which the log would not replay.

        Factual exposures and approval-derived reservations share one identity
        namespace. The exact row the append would write (chain fields
        included) is replayed with the verified history, under the same
        coordinator locks and before any byte is written, so a collision in
        either order is refused instead of committing a row that permanently
        bricks admission, consumption, send, release and exposure recording.
        The replayed row is parsed and verified from the exact appended line,
        and the log's storage applies the same check to every other writer (F-3).
        """

        return _ReplayChecked(self, build)

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

        self.audit_log.log.transaction(self._replay_checked(build))
        return exposure

    def approve(self, request: RiskRequest) -> RiskDecision:
        decision_holder: dict[str, RiskDecision] = {}
        release_proofs = self.release_proofs
        mode_states = self.modes
        owner_paths = self._risk_owner_paths()

        def build(rows: tuple[dict, ...]) -> dict | None:
            # No mutable authority fact is captured before the coordinator
            # locks. Bankroll, safety and qualification writers use these same
            # per-log locks; risk owns the primary lock through its fsynced
            # approval append. JSONL, not SQLite, remains the business truth.
            if self.release_proofs is not release_proofs:
                raise RegistryConflict("release proof owner changed during risk admission")
            if self.modes is not mode_states:
                raise RegistryConflict("mode owner changed during risk admission")
            if self._risk_owner_paths() != owner_paths:
                raise RegistryConflict("risk owner changed during risk admission")
            if self.owner_mismatches(release_proofs=release_proofs):
                decision_holder["value"] = RiskDecision(
                    False, "owner_authority_mismatch", "0", "0"
                )
                return None
            all_exposures = self._exposures(rows, release_fenced=True)
            action_at = iso_utc(self._action_clock(request.requested_at))
            try:
                qualification = self.qualifications.get_for_new_risk(
                    request.qualification_record_id, at=action_at,
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
            if not self._coherent_paper_mode(mode_states, safety):
                decision_holder["value"] = RiskDecision(
                    False, "mode_safety_head_not_coherent_paper", "0", "0"
                )
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
            if self.strategies is None:
                decision_holder["value"] = RiskDecision(
                    False, "strategy_authority_unavailable", "0", "0"
                )
                return None
            try:
                output = self.qualifications.outputs.get(qualification.decision_output_hash)
                if (output["strategy_id"] != qualification.strategy_id
                        or output["strategy_version"] != qualification.strategy_version
                        or output["strategy_decision_contract_hash"]
                        != qualification.strategy_decision_contract_hash):
                    raise RegistryConflict("strategy/output identity mismatch")
                self.strategies.require_current_paper_contract(
                    qualification.strategy_id, qualification.strategy_version,
                    qualification.strategy_decision_contract_hash,
                )
            except Exception:
                decision_holder["value"] = RiskDecision(False, "authority_unavailable", "0", "0")
                return None
            trusted_clusters = tuple(output["correlation_cluster_ids"])
            # The legacy request field defaults to (), which cannot distinguish
            # omission from an explicitly empty copy. Empty therefore means no
            # comparison; every nonempty copy must equal the trusted set.
            if request.correlation_cluster_ids and (
                set(request.correlation_cluster_ids) != set(trusted_clusters)
            ):
                decision_holder["value"] = RiskDecision(
                    False, "caller_correlation_mismatch", "0", "0"
                )
                return None
            if (request.side.value != output["side"]
                    or Decimal(request.odds) < Decimal(output["requested_odds_min"])
                    or Decimal(request.odds) > Decimal(output["requested_odds_max"])):
                decision_holder["value"] = RiskDecision(
                    False, "decision_output_execution_mismatch", "0", "0"
                )
                return None
            if parse_utc(action_at) >= parse_utc(qualification.expires_at):
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
                issued_at=action_at,
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
            if any(item.exposure_id == approval.approval_id for item in all_exposures):
                decision_holder["value"] = RiskDecision(
                    False, "risk_identity_collision", "0", "0"
                )
                return None
            open_exposures = [item for item in all_exposures if self._open(item)]
            if any(item.state == ExposureState.UNKNOWN for item in open_exposures):
                decision_holder["value"] = RiskDecision(
                    False, "unknown_exposure_blocks_new_risk", "0", "0"
                )
                return None
            requested_clusters = set(trusted_clusters)
            capacity_reason, proposed_total, cluster_liability = self._portfolio_capacity(
                all_exposures,
                bankroll=Decimal(bankroll.bankroll),
                proposed_clusters=requested_clusters,
                extra_liability=liability,
            )
            if capacity_reason is not None:
                decision_holder["value"] = RiskDecision(
                    False,
                    capacity_reason,
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
                "correlation_cluster_ids": list(trusted_clusters),
                "affected_scope": request.affected_scope,
            }

        self.audit_log.log.transaction(
            self._replay_checked(build),
            read_locks=(
                self.bankrolls.log, self.safety.log, self.qualifications.log,
                self.qualifications.bindings.log,
                self.qualifications.approvals.log, self.qualifications.witnesses,
                *((self.strategies.log,) if self.strategies is not None else ()),
                *self._mode_lock_for(mode_states),
                *self._release_read_locks_for(release_proofs),
                self.owner_binding.log,
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
        result: dict[str, RiskApproval] = {}
        release_proofs = self.release_proofs
        mode_states = self.modes
        owner_paths = self._risk_owner_paths()

        def build(rows: tuple[dict, ...]) -> dict | None:
            if self.release_proofs is not release_proofs:
                raise RegistryConflict("release proof owner changed during consumption")
            if self.modes is not mode_states:
                raise RegistryConflict("mode owner changed during consumption")
            if self._risk_owner_paths() != owner_paths:
                raise RegistryConflict("risk owner changed during consumption")
            self.require_bound_owners(release_proofs=release_proofs)
            action_at = iso_utc(self._action_clock(consumed_at))
            self._exposures(rows, release_fenced=True)
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
                approval.qualification_record_id, at=action_at,
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
            if not self.approval_still_valid(
                approval_id, at=action_at, release_fenced=True,
            ):
                raise RegistryConflict("risk approval is not currently valid")
            result["value"] = replace(
                approval, status="CONSUMED", consumed_by_order_id=order_id
            )
            return {
                "record_type": "risk_approval_consumed",
                "schema_version": "risk-approval-v2",
                "approval_id": approval_id,
                "candidate_decision_hash": approval.candidate_decision_hash,
                "order_id": order_id,
                "consumed_at": action_at,
            }

        self.audit_log.log.transaction(
            self._replay_checked(build), read_locks=(
                self.qualifications.log, self.qualifications.bindings.log,
                self.qualifications.approvals.log, self.qualifications.witnesses,
                self.bankrolls.log, self.safety.log,
                *((self.strategies.log,) if self.strategies is not None else ()),
                *self._mode_lock_for(mode_states),
                *self._release_read_locks_for(release_proofs),
                self.owner_binding.log,
            ),
        )
        return result["value"]

    def reserved_exposures(self) -> tuple[Exposure, ...]:
        result: dict[str, tuple[Exposure, ...]] = {}
        release_proofs = self.release_proofs

        def inspect(rows: tuple[dict, ...]) -> None:
            if self.release_proofs is not release_proofs:
                raise RegistryConflict("release proof owner changed during replay")
            # Release capacity is derived from the proof, order and ledger
            # owners; only the bound owners may mint it.
            self.require_bound_owners(release_proofs=release_proofs)
            result["value"] = tuple(
                item for item in self._exposures(rows, release_fenced=True)
                if self._open(item)
            )
            return None

        self.audit_log.log.transaction(
            inspect, read_locks=(
                *self._release_read_locks_for(release_proofs), self.owner_binding.log,
            ),
        )
        return result["value"]

    def transition_reservation(
        self,
        approval_id: str,
        state: ExposureState,
        *,
        occurred_at: str,
    ) -> Exposure:
        if state in {ExposureState.SETTLED, ExposureState.VOID}:
            raise RegistryConflict("terminal reservation requires exact release proof")
        result: dict[str, Exposure] = {}

        def build(rows: tuple[dict, ...]) -> dict:
            exposures = {item.exposure_id: item for item in self._exposures(rows)}
            if approval_id not in exposures:
                raise RegistryConflict("unknown reservation")
            current = exposures[approval_id]
            if state != ExposureState.UNKNOWN:
                raise RegistryConflict("unsupported reservation transition")
            if current.state in {ExposureState.SETTLED, ExposureState.VOID, ExposureState.UNKNOWN}:
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

        self.audit_log.log.transaction(self._replay_checked(build))
        return result["value"]

    def release_with_proof(self, proof_record_hash: str, *, occurred_at: str) -> Exposure:
        """Release a fully reconciled synthetic PAPER order, never a caller label.

        The risk append and exact proof/order/fill head validation are fenced
        together. A later changed head makes the old release conservatively
        UNKNOWN on authoritative replay, restoring the full charge.
        """

        release_proofs = self.release_proofs
        if release_proofs is None:
            raise RegistryConflict("release proof owner is unavailable")
        occurred_at = iso_utc(occurred_at)
        result: dict[str, Exposure] = {}

        def build(rows: tuple[dict, ...]) -> dict | None:
            if self.release_proofs is not release_proofs:
                raise RegistryConflict("release proof owner changed during release")
            self.require_bound_owners(release_proofs=release_proofs)
            proof_rows = tuple(release_proofs.log.records())
            proof = release_proofs.validate_current_locked(
                proof_record_hash,
                proof_rows=proof_rows,
                risk_rows=rows,
                qualification_rows=tuple(self.qualifications.log.records()),
                order_rows=tuple(release_proofs.execution._audit.records()),
                ledger_rows=tuple(release_proofs.ledger.log.records()),
            )
            approval_id = proof["approval_id"]
            exposures = {
                item.exposure_id: item
                for item in self._exposures(rows, release_fenced=True)
            }
            current = exposures.get(approval_id)
            if current is None:
                raise RegistryConflict("release proof has no exact reservation")
            if parse_utc(occurred_at) < parse_utc(proof["occurred_at"]):
                raise RegistryConflict("release event predates its proof")
            legacy_release = (
                proof["record_type"] == "offline_paper_legacy_release_proof"
            )
            previous = [
                row for row in rows
                if row.get("record_type") in {
                    "risk_reservation_release", "risk_reservation_legacy_release",
                }
                and row.get("approval_id") == approval_id
            ]
            target = (
                ExposureState.VOID if proof["release_reason"] in {
                    "FILLS_VOID", "UNSENT_REJECTED", "UNMATCHED_CANCEL_CONFIRMED",
                }
                else ExposureState.SETTLED
            )
            if previous:
                if (len(previous) == 1
                        and previous[0]["reconciliation_proof_hash"]
                        == proof_record_hash
                        and current.state == target):
                    result["value"] = current
                    return None
                raise RegistryConflict("reservation already has a different release")
            if current.state not in {ExposureState.PENDING, ExposureState.UNKNOWN}:
                raise RegistryConflict("reservation cannot be released")
            result["value"] = replace(current, state=target)
            payload = {
                "record_type": (
                    "risk_reservation_legacy_release"
                    if legacy_release else "risk_reservation_release"
                ),
                "schema_version": (
                    "risk-reservation-legacy-release-v1"
                    if legacy_release else "risk-reservation-release-v1"
                ),
                "approval_id": approval_id,
                "qualification_record_id": proof["qualification_record_id"],
                "candidate_decision_hash": proof["candidate_decision_hash"],
                "order_id": proof["order_id"],
                "from_state": current.state.value,
                "to_state": target.value,
                "release_reason": proof["release_reason"],
                "order_head_record_hash": proof["order_head_record_hash"],
                "fill_proofs": [
                    {
                        "fill_id": item["fill_id"],
                        "fill_record_hash": item["fill_record_hash"],
                        "current_head_event_id": item["head_event_id"],
                        "current_head_record_hash": item["head_record_hash"],
                    }
                    for item in proof["fill_proofs"]
                ],
                "reconciliation_proof_hash": proof_record_hash,
                "occurred_at": occurred_at,
            }
            payload[
                "legacy_qualification_record_hash"
                if legacy_release else "decision_output_hash"
            ] = proof[
                "legacy_qualification_record_hash"
                if legacy_release else "decision_output_hash"
            ]
            return payload

        self.audit_log.log.transaction(
            self._replay_checked(build), read_locks=(
                *self._release_read_locks_for(release_proofs), self.owner_binding.log,
            ),
        )
        return result["value"]

    def approval_still_valid(
        self, approval_id: str, *, at: str, release_fenced: bool = False,
    ) -> bool:
        try:
            if self.owner_mismatches(
                release_proofs=self.release_proofs if release_fenced else None,
            ):
                return False
            approval = self.get_approval(approval_id)
            qualification = self.qualifications.get_for_new_risk(
                approval.qualification_record_id, at=at,
            )
            if qualification.candidate_decision_hash != approval.candidate_decision_hash:
                return False
            if self.strategies is None:
                return False
            output = self.qualifications.outputs.get(qualification.decision_output_hash)
            if (output["strategy_id"] != qualification.strategy_id
                    or output["strategy_version"] != qualification.strategy_version
                    or output["strategy_decision_contract_hash"]
                    != qualification.strategy_decision_contract_hash):
                return False
            self.strategies.require_current_paper_contract(
                qualification.strategy_id, qualification.strategy_version,
                qualification.strategy_decision_contract_hash,
            )
            if parse_utc(at) >= parse_utc(approval.expires_at):
                return False
            safety = self.safety.current()
            if safety.kill_switch_active:
                return False
            if not self._coherent_paper_mode(self.modes, safety):
                return False
            if self.bankrolls.current().snapshot_id != approval.bankroll_snapshot_id:
                return False
            if (approval.risk_policy_version != self.policy.version
                    or approval.risk_policy_digest != self.policy.digest
                    or qualification.active_policy_digest != self.policy_set.digest):
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
            exposures = self._exposures(rows, release_fenced=release_fenced)
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
            capacity_reason, _, _ = self._portfolio_capacity(
                exposures,
                bankroll=Decimal(self.bankrolls.current().bankroll),
                proposed_clusters=set(reservation.correlation_cluster_ids),
            )
            if capacity_reason is not None:
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
        # Only this authority's own bankroll may be rebased through it.
        self.require_bound_owners()
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
        result: dict[str, bool] = {}
        release_proofs = self.release_proofs
        mode_states = self.modes

        def inspect(rows: tuple[dict, ...]) -> None:
            if self.release_proofs is not release_proofs:
                raise RegistryConflict("release proof owner changed during risk gate")
            if self.modes is not mode_states:
                raise RegistryConflict("mode owner changed during risk gate")
            self.require_bound_owners(release_proofs=release_proofs)
            safety = self.safety.current()
            if safety.kill_switch_active:
                result["value"] = False
                return None
            if not self._coherent_paper_mode(mode_states, safety):
                result["value"] = False
                return None
            self.bankrolls.current()
            if any(
                item.state == ExposureState.UNKNOWN
                for item in self._exposures(rows, release_fenced=True)
            ):
                result["value"] = False
                return None
            result["value"] = not any(
                row.get("record_type") == "risk_approval_created"
                and row.get("schema_version") == "risk-approval-v2"
                and row.get("candidate_decision_hash") == candidate.candidate_decision_hash
                for row in rows
            )
            return None

        try:
            self.audit_log.log.transaction(
                inspect,
                read_locks=(
                    self.safety.log, self.bankrolls.log,
                    *self._mode_lock_for(mode_states),
                    *self._release_read_locks_for(release_proofs),
                    self.owner_binding.log,
                ),
            )
            return result["value"]
        except Exception:
            return None

    def correlation_ok(self, candidate) -> bool | None:
        return self.risk_ok(candidate)
