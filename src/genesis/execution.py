"""Provider-neutral paper execution contracts; no network or live adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from threading import Lock
from pathlib import Path

from .config import OperationalMode
from .registry import AppendOnlyJsonl
from .repro import canonical_json, sha256_bytes
from .time import iso_utc, parse_utc


class OrderState(StrEnum):
    ORDER_INTENT_CREATED = "ORDER_INTENT_CREATED"
    RISK_APPROVED = "RISK_APPROVED"
    SUBMISSION_PENDING = "SUBMISSION_PENDING"
    SUBMISSION_SENT = "SUBMISSION_SENT"
    ACK_RECEIVED = "ACK_RECEIVED"
    REJECTED = "REJECTED"
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"
    FULLY_MATCHED = "FULLY_MATCHED"
    UNMATCHED = "UNMATCHED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    CANCEL_FAILED = "CANCEL_FAILED"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    SETTLED = "SETTLED"
    VOID = "VOID"


_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.ORDER_INTENT_CREATED: {OrderState.RISK_APPROVED, OrderState.REJECTED},
    OrderState.RISK_APPROVED: {OrderState.SUBMISSION_PENDING, OrderState.REJECTED},
    OrderState.SUBMISSION_PENDING: {OrderState.SUBMISSION_SENT, OrderState.UNKNOWN, OrderState.REJECTED},
    OrderState.SUBMISSION_SENT: {OrderState.ACK_RECEIVED, OrderState.UNKNOWN, OrderState.REJECTED},
    OrderState.ACK_RECEIVED: {OrderState.PARTIALLY_MATCHED, OrderState.FULLY_MATCHED, OrderState.UNMATCHED, OrderState.CANCEL_PENDING, OrderState.UNKNOWN},
    OrderState.PARTIALLY_MATCHED: {OrderState.FULLY_MATCHED, OrderState.CANCEL_PENDING, OrderState.UNKNOWN, OrderState.SETTLED, OrderState.VOID},
    OrderState.FULLY_MATCHED: {OrderState.SETTLED, OrderState.VOID, OrderState.UNKNOWN},
    OrderState.UNMATCHED: {OrderState.CANCEL_PENDING, OrderState.CANCELLED, OrderState.UNKNOWN},
    OrderState.CANCEL_PENDING: {OrderState.CANCELLED, OrderState.CANCEL_FAILED, OrderState.UNKNOWN},
    OrderState.CANCEL_FAILED: {OrderState.CANCEL_PENDING, OrderState.UNKNOWN},
    OrderState.UNKNOWN: {OrderState.RECONCILIATION_REQUIRED},
    OrderState.RECONCILIATION_REQUIRED: {OrderState.ACK_RECEIVED, OrderState.PARTIALLY_MATCHED, OrderState.FULLY_MATCHED, OrderState.UNMATCHED, OrderState.CANCELLED, OrderState.REJECTED},
    OrderState.SETTLED: set(),
    OrderState.VOID: set(),
    OrderState.REJECTED: set(),
    OrderState.CANCELLED: set(),
}


@dataclass(frozen=True)
class CriticalEvidenceRefresh:
    checked_at: str
    valid: bool
    material_change: bool
    refreshed_hashes: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        parse_utc(self.checked_at)
        for digest in self.refreshed_hashes:
            if len(digest) != 64:
                raise ValueError("refreshed evidence hashes must be SHA-256 digests")


@dataclass(frozen=True)
class RecertificationResult:
    passed: bool
    reason: str
    requires_new_candidate: bool = False


def recertify(
    *,
    strategy_active: bool,
    candidate_not_expired: bool,
    refresh: CriticalEvidenceRefresh,
    market_open: bool,
    executable_price_ok: bool,
    liquidity_ok: bool,
    risk_ok: bool,
    no_kill_condition: bool,
    no_duplicate_intent: bool,
    no_unknown_state: bool,
) -> RecertificationResult:
    checks = (
        (strategy_active, "strategy_not_active"),
        (candidate_not_expired, "candidate_expired"),
        (refresh.valid, "critical_evidence_refresh_failed"),
        (not refresh.material_change, "critical_evidence_changed"),
        (market_open, "market_closed"),
        (executable_price_ok, "executable_price_changed"),
        (liquidity_ok, "liquidity_unavailable"),
        (risk_ok, "risk_limit"),
        (no_kill_condition, "kill_switch_active"),
        (no_duplicate_intent, "duplicate_order_intent"),
        (no_unknown_state, "unknown_order_state"),
    )
    for passed, reason in checks:
        if not passed:
            return RecertificationResult(False, reason, reason == "critical_evidence_changed")
    return RecertificationResult(True, "recertified")


@dataclass(frozen=True)
class OrderIntent:
    candidate_decision_hash: str
    idempotency_key: str
    stake: str
    odds: str
    created_at: str
    mode: OperationalMode = OperationalMode.PAPER

    def __post_init__(self) -> None:
        from decimal import Decimal

        if len(self.candidate_decision_hash) != 64 or not self.idempotency_key:
            raise ValueError("order intent identity is invalid")
        if Decimal(self.stake) <= 0 or Decimal(self.odds) <= 1:
            raise ValueError("order stake and odds are invalid")
        if self.mode != OperationalMode.PAPER:
            raise ValueError("foundation execution adapter only supports PAPER mode")
        parse_utc(self.created_at)


@dataclass(frozen=True)
class OrderRecord:
    intent: OrderIntent
    state: OrderState
    state_history: tuple[OrderState, ...]

    @property
    def order_id(self) -> str:
        return sha256_bytes(canonical_json({"key": self.intent.idempotency_key, "candidate": self.intent.candidate_decision_hash}))

    def transition(self, state: OrderState) -> "OrderRecord":
        if state not in _TRANSITIONS[self.state]:
            raise ValueError(f"invalid order transition {self.state} -> {state}")
        return replace(self, state=state, state_history=self.state_history + (state,))


class PaperExecutionAdapter:
    """Deterministic state machine for tests and paper mode only."""

    def __init__(self, audit_path: str | Path | None = None):
        self._lock = Lock()
        self._by_key: dict[str, OrderRecord] = {}
        self._audit = AppendOnlyJsonl(audit_path) if audit_path is not None else None

    def _audit_state(self, record: OrderRecord) -> None:
        if self._audit is not None:
            self._audit.append(
                {
                    "record_type": "order_state",
                    "order_id": record.order_id,
                    "idempotency_key": record.intent.idempotency_key,
                    "candidate_decision_hash": record.intent.candidate_decision_hash,
                    "state": record.state.value,
                }
            )

    def create_intent(self, intent: OrderIntent) -> OrderRecord:
        with self._lock:
            existing = self._by_key.get(intent.idempotency_key)
            if existing is not None:
                if existing.intent != intent:
                    raise ValueError("idempotency key reused for different intent")
                return existing
            record = OrderRecord(intent, OrderState.ORDER_INTENT_CREATED, (OrderState.ORDER_INTENT_CREATED,))
            self._by_key[intent.idempotency_key] = record
            self._audit_state(record)
            return record

    def transition(self, idempotency_key: str, state: OrderState) -> OrderRecord:
        with self._lock:
            record = self._by_key[idempotency_key]
            updated = record.transition(state)
            self._by_key[idempotency_key] = updated
            self._audit_state(updated)
            return updated

    def get(self, idempotency_key: str) -> OrderRecord:
        return self._by_key[idempotency_key]

    def mark_submission_timeout(self, idempotency_key: str) -> OrderRecord:
        record = self.get(idempotency_key)
        if record.state == OrderState.SUBMISSION_PENDING:
            record = self.transition(idempotency_key, OrderState.UNKNOWN)
        if record.state == OrderState.UNKNOWN:
            record = self.transition(idempotency_key, OrderState.RECONCILIATION_REQUIRED)
        return record


@dataclass(frozen=True)
class AuthorizationArtifact:
    authorization_id: str
    authorized_by: str
    mode: OperationalMode
    issued_at: str
    policy_digest: str

    def __post_init__(self) -> None:
        if not self.authorization_id or not self.authorized_by or len(self.policy_digest) != 64:
            raise ValueError("authorization artifact is invalid")
        parse_utc(self.issued_at)


class ModeController:
    def __init__(self, initial: OperationalMode = OperationalMode.OFFLINE_RESEARCH):
        if initial in {OperationalMode.MICRO_LIVE, OperationalMode.LIVE}:
            raise ValueError("live modes are disabled in the foundation")
        self.mode = initial
        self.kill_switch_active = False

    def transition(self, target: OperationalMode, authorization: AuthorizationArtifact | None = None) -> OperationalMode:
        if target in {OperationalMode.MICRO_LIVE, OperationalMode.LIVE}:
            raise ValueError("live modes are not implemented")
        if authorization is None and target not in {OperationalMode.DISABLED, OperationalMode.KILL_SWITCH_ACTIVE}:
            raise PermissionError("mode transition requires explicit authorization")
        if authorization is not None and authorization.mode != target:
            raise ValueError("authorization mode does not match target")
        self.mode = target
        self.kill_switch_active = target == OperationalMode.KILL_SWITCH_ACTIVE
        return self.mode

    def activate_kill_switch(self) -> OperationalMode:
        self.mode = OperationalMode.KILL_SWITCH_ACTIVE
        self.kill_switch_active = True
        return self.mode
