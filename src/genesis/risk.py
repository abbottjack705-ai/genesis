"""Deterministic offline risk, exposure, correlation, and approval contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Iterable
from pathlib import Path

from .policy import PolicySet, RiskPolicy
from .registry import AppendOnlyJsonl
from .repro import canonical_json, sha256_bytes


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
        from decimal import Decimal

        if len(self.candidate_decision_hash) != 64:
            raise ValueError("candidate_decision_hash must be a SHA-256 digest")
        if Decimal(self.liability) < 0:
            raise ValueError("liability cannot be negative")
        for cluster in self.correlation_cluster_ids:
            if not cluster:
                raise ValueError("correlation cluster IDs cannot be empty")

    @property
    def liability_amount(self):
        from decimal import Decimal

        return Decimal(self.liability)


@dataclass(frozen=True)
class BankrollSnapshot:
    snapshot_id: str
    bankroll: str
    captured_at: str
    rebase_reason: str

    def __post_init__(self) -> None:
        from decimal import Decimal
        from .time import parse_utc

        if Decimal(self.bankroll) <= 0:
            raise ValueError("bankroll must be positive")
        parse_utc(self.captured_at)


@dataclass(frozen=True)
class RiskDecision:
    passed: bool
    reason: str
    total_open_liability: str
    cluster_liability: str
    approval_id: str | None = None


@dataclass(frozen=True)
class RiskApproval:
    approval_id: str
    candidate_decision_hash: str
    liability: str
    risk_policy_version: str
    status: str = "APPROVED_NOT_CONSUMED"


@dataclass(frozen=True)
class RebaseDecision:
    previous_bankroll: str
    new_bankroll: str
    direction: str
    trigger: str
    policy_version: str


class RiskAuditLog:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    def append(self, event_type: str, payload: dict) -> str:
        return self.log.append({"record_type": event_type, **payload})

    def verify(self) -> int:
        return self.log.verify()


class RiskEngine:
    """Synchronous reservation model; reservations count before consumption."""

    def __init__(self, policy: RiskPolicy | None = None, audit_log: RiskAuditLog | None = None):
        self.policy = policy or PolicySet().risk
        self.audit_log = audit_log
        self._lock = Lock()
        self._approvals: dict[str, RiskApproval] = {}
        self._reserved: dict[str, Exposure] = {}

    def stake_for_units(self, bankroll: str, units: str) -> str:
        return format(self.policy.stake_amount(bankroll, units), "f")

    @staticmethod
    def _open(exposure: Exposure) -> bool:
        return exposure.state in {
            ExposureState.MATCHED,
            ExposureState.PARTIALLY_MATCHED,
            ExposureState.UNMATCHED,
            ExposureState.PENDING,
            ExposureState.UNKNOWN,
        }

    def approve(
        self,
        *,
        candidate_decision_hash: str,
        bankroll: str,
        requested_liability: str,
        existing: Iterable[Exposure] = (),
        correlation_cluster_ids: tuple[str, ...] = (),
        affected_scope: str | None = None,
        kill_switch_active: bool = False,
    ) -> RiskDecision:
        from decimal import Decimal

        amount = Decimal(requested_liability)
        bank = Decimal(bankroll)
        if amount < 0 or bank <= 0:
            return RiskDecision(False, "invalid_risk_input", "0", "0")
        with self._lock:
            existing_items = list(existing)
            if kill_switch_active:
                return RiskDecision(False, "kill_switch_active", "0", "0")
            if candidate_decision_hash in self._approvals or candidate_decision_hash in {item.candidate_decision_hash for item in existing_items}:
                return RiskDecision(False, "duplicate_order_intent", "0", "0")
            all_exposures = [item for item in existing_items if self._open(item)] + list(self._reserved.values())
            if any(item.state == ExposureState.UNKNOWN for item in all_exposures):
                return RiskDecision(False, "unknown_exposure_blocks_new_risk", "0", "0")
            open_liability = sum((item.liability_amount for item in all_exposures), Decimal("0"))
            proposed_total = open_liability + amount
            max_liability = bank * self.policy.max_open_liability_fraction
            if proposed_total > max_liability:
                return RiskDecision(False, "open_liability_limit", format(proposed_total, "f"), "0")
            requested_clusters = set(correlation_cluster_ids)
            cluster_liability = amount
            for item in all_exposures:
                if requested_clusters.intersection(item.correlation_cluster_ids):
                    cluster_liability += item.liability_amount
            max_cluster = bank * self.policy.correlated_cluster_fraction
            if requested_clusters and cluster_liability > max_cluster:
                return RiskDecision(False, "correlation_cluster_limit", format(proposed_total, "f"), format(cluster_liability, "f"))
            approval_id = sha256_bytes(
                canonical_json(
                    {
                        "candidate_decision_hash": candidate_decision_hash,
                        "liability": format(amount, "f"),
                        "policy": self.policy.version,
                    }
                )
            )
            approval = RiskApproval(approval_id, candidate_decision_hash, format(amount, "f"), self.policy.version)
            self._approvals[candidate_decision_hash] = approval
            self._reserved[candidate_decision_hash] = Exposure(
                exposure_id=approval_id,
                candidate_decision_hash=candidate_decision_hash,
                liability=format(amount, "f"),
                state=ExposureState.PENDING,
                correlation_cluster_ids=correlation_cluster_ids,
                affected_scope=affected_scope,
            )
            if self.audit_log is not None:
                self.audit_log.append("risk_approval", {"approval_id": approval_id, "candidate_decision_hash": candidate_decision_hash, "liability": format(amount, "f"), "status": approval.status})
            return RiskDecision(True, "risk_approved", format(proposed_total, "f"), format(cluster_liability, "f"), approval_id)

    def consume(self, approval_id: str) -> RiskApproval:
        with self._lock:
            for candidate_hash, approval in self._approvals.items():
                if approval.approval_id == approval_id:
                    if approval.status != "APPROVED_NOT_CONSUMED":
                        raise ValueError("risk approval is single-use")
                    consumed = RiskApproval(approval.approval_id, approval.candidate_decision_hash, approval.liability, approval.risk_policy_version, "CONSUMED")
                    self._approvals[candidate_hash] = consumed
                    if self.audit_log is not None:
                        self.audit_log.append("risk_approval_consumed", {"approval_id": approval_id, "candidate_decision_hash": candidate_hash})
                    return consumed
        raise KeyError("unknown risk approval")

    def reserved_exposures(self) -> tuple[Exposure, ...]:
        with self._lock:
            return tuple(self._reserved.values())

    def rebase(self, previous_bankroll: str, new_bankroll: str, *, scheduled_weekly: bool, drawdown_triggered: bool) -> RebaseDecision:
        from decimal import Decimal

        previous = Decimal(previous_bankroll)
        new = Decimal(new_bankroll)
        if previous <= 0 or new <= 0:
            raise ValueError("bankroll values must be positive")
        if new > previous and not scheduled_weekly:
            raise ValueError("upward bankroll rebase is weekly only")
        if new < previous and not (scheduled_weekly or drawdown_triggered):
            raise ValueError("downward bankroll rebase requires schedule or trigger")
        direction = "upward" if new > previous else "downward" if new < previous else "unchanged"
        trigger = "weekly_checkpoint" if scheduled_weekly else "drawdown_trigger"
        return RebaseDecision(format(previous, "f"), format(new, "f"), direction, trigger, self.policy.version)
