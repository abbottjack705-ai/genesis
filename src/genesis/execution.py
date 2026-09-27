"""Durable provider-neutral paper execution; no network or live adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Callable, Protocol

from .accounting import BetSide, MatchedFragment, money
from .config import OperationalMode
from .owner_binding import log_path
from .policy import PolicySet, matched_odds_profile, odds_profile_hash
from .registry import AppendOnlyJsonl, RegistryConflict, StrategyRegistry
from .repro import canonical_json, sha256_bytes
from .risk import RiskEngine, SafetyState, SafetyStateStore
from .selection import QualificationRecord
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
    OrderState.ORDER_INTENT_CREATED: {OrderState.REJECTED},
    OrderState.RISK_APPROVED: {OrderState.SUBMISSION_PENDING, OrderState.REJECTED},
    OrderState.SUBMISSION_PENDING: {
        OrderState.SUBMISSION_SENT,
        OrderState.UNKNOWN,
        OrderState.REJECTED,
    },
    OrderState.SUBMISSION_SENT: {
        OrderState.ACK_RECEIVED,
        OrderState.UNKNOWN,
        OrderState.REJECTED,
    },
    OrderState.ACK_RECEIVED: {
        OrderState.PARTIALLY_MATCHED,
        OrderState.FULLY_MATCHED,
        OrderState.UNMATCHED,
        OrderState.CANCEL_PENDING,
        OrderState.UNKNOWN,
    },
    OrderState.PARTIALLY_MATCHED: {
        OrderState.FULLY_MATCHED,
        OrderState.CANCEL_PENDING,
        OrderState.UNKNOWN,
        OrderState.SETTLED,
        OrderState.VOID,
    },
    OrderState.FULLY_MATCHED: {OrderState.SETTLED, OrderState.VOID, OrderState.UNKNOWN},
    OrderState.UNMATCHED: {
        OrderState.CANCEL_PENDING,
        OrderState.CANCELLED,
        OrderState.UNKNOWN,
    },
    OrderState.CANCEL_PENDING: {
        OrderState.CANCELLED,
        OrderState.CANCEL_FAILED,
        OrderState.UNKNOWN,
    },
    OrderState.CANCEL_FAILED: {OrderState.CANCEL_PENDING, OrderState.UNKNOWN},
    OrderState.UNKNOWN: {OrderState.RECONCILIATION_REQUIRED},
    OrderState.RECONCILIATION_REQUIRED: {
        OrderState.ACK_RECEIVED,
        OrderState.PARTIALLY_MATCHED,
        OrderState.FULLY_MATCHED,
        OrderState.UNMATCHED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
    },
    OrderState.SETTLED: set(),
    OrderState.VOID: set(),
    OrderState.REJECTED: set(),
    OrderState.CANCELLED: set(),
}


_RESTART_AMBIGUOUS = {
    OrderState.SUBMISSION_PENDING,
    OrderState.SUBMISSION_SENT,
    OrderState.UNKNOWN,
    OrderState.RECONCILIATION_REQUIRED,
}


@dataclass(frozen=True)
class CriticalEvidenceRefresh:
    candidate_decision_hash: str
    checked_at: str
    valid: bool
    material_change: bool
    refreshed_hashes: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if len(self.candidate_decision_hash) != 64:
            raise ValueError("refresh candidate hash must be a SHA-256 digest")
        parse_utc(self.checked_at)
        for digest in self.refreshed_hashes:
            if len(digest) != 64:
                raise ValueError("refreshed evidence hashes must be SHA-256 digests")

    @property
    def refresh_id(self) -> str:
        return sha256_bytes(canonical_json(self.to_dict()))

    def to_dict(self) -> dict:
        value = asdict(self)
        value["checked_at"] = iso_utc(self.checked_at)
        return value


class CriticalEvidenceRefreshStore:
    """Per-candidate critical-evidence refresh history (E2).

    A candidate's refreshes must advance ``checked_at``, and its first material
    change invalidates it for good: a new candidate is required. Both rules are
    derived from the whole durable history on every read, so they hold after
    restart and for rows that reached the log without ``append``; a history
    that does not advance fails closed.
    """

    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    @staticmethod
    def _from_row(row: dict) -> CriticalEvidenceRefresh:
        fields = {key: row[key] for key in CriticalEvidenceRefresh.__dataclass_fields__}
        fields["refreshed_hashes"] = tuple(fields["refreshed_hashes"])
        return CriticalEvidenceRefresh(**fields)

    @classmethod
    def _history(
        cls, rows: tuple[dict, ...] | list[dict], candidate_decision_hash: str,
    ) -> list[CriticalEvidenceRefresh]:
        history = [
            cls._from_row(row)
            for row in rows
            if row.get("record_type") == "critical_evidence_refresh"
            and row.get("schema_version") == "critical-evidence-refresh-v2"
            and row.get("candidate_decision_hash") == candidate_decision_hash
        ]
        for earlier, later in zip(history, history[1:]):
            if parse_utc(later.checked_at) <= parse_utc(earlier.checked_at):
                raise RegistryConflict("critical evidence refresh time must advance")
        return history

    def append(self, refresh: CriticalEvidenceRefresh) -> CriticalEvidenceRefresh:
        payload = {
            "record_type": "critical_evidence_refresh",
            "schema_version": "critical-evidence-refresh-v2",
            "refresh_id": refresh.refresh_id,
            **refresh.to_dict(),
        }

        def build(rows: tuple[dict, ...]) -> dict | None:
            history = self._history(rows, refresh.candidate_decision_hash)
            if any(item.refresh_id == refresh.refresh_id for item in history):
                return None
            if any(item.material_change for item in history):
                raise RegistryConflict(
                    "critical evidence changed materially; a new candidate is required"
                )
            self._history((*rows, payload), refresh.candidate_decision_hash)
            return payload

        self.log.transaction(build)
        return refresh

    def current(self, candidate_decision_hash: str) -> CriticalEvidenceRefresh:
        """The candidate's first material change, else its latest refresh."""

        history = self._history(self.log.records(), candidate_decision_hash)
        if not history:
            raise RegistryConflict("critical evidence refresh is unavailable")
        return next((item for item in history if item.material_change), history[-1])


@dataclass(frozen=True)
class ExecutionMarketSnapshot:
    snapshot_id: str
    candidate_decision_hash: str
    observed_at: str
    market_open: bool
    executable_odds: str
    available_liquidity: str

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "candidate_decision_hash"):
            if len(getattr(self, name)) != 64:
                raise ValueError(f"{name} must be a SHA-256 digest")
        parse_utc(self.observed_at)
        if Decimal(self.executable_odds) <= 1 or Decimal(self.available_liquidity) < 0:
            raise ValueError("execution market values are invalid")
        if self.compute_id() != self.snapshot_id:
            raise ValueError("execution market snapshot ID mismatch")

    def unsigned_dict(self) -> dict:
        value = asdict(self)
        value.pop("snapshot_id")
        value["observed_at"] = iso_utc(self.observed_at)
        return value

    def compute_id(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    @classmethod
    def create(cls, **fields) -> "ExecutionMarketSnapshot":
        unsigned = dict(fields)
        unsigned["observed_at"] = iso_utc(unsigned["observed_at"])
        return cls(snapshot_id=sha256_bytes(canonical_json(unsigned)), **unsigned)

    def to_dict(self) -> dict:
        return {"snapshot_id": self.snapshot_id, **self.unsigned_dict()}


class ExecutionMarketStateStore:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    @staticmethod
    def _from_row(row: dict) -> ExecutionMarketSnapshot:
        return ExecutionMarketSnapshot(
            **{key: row[key] for key in ExecutionMarketSnapshot.__dataclass_fields__}
        )

    def append(self, snapshot: ExecutionMarketSnapshot) -> ExecutionMarketSnapshot:
        payload = {
            "record_type": "execution_market_snapshot",
            "schema_version": "execution-market-snapshot-v2",
            **snapshot.to_dict(),
        }

        def build(rows: tuple[dict, ...]) -> dict | None:
            history = [
                self._from_row(row)
                for row in rows
                if row.get("record_type") == "execution_market_snapshot"
                and row.get("schema_version") == "execution-market-snapshot-v2"
                and row.get("candidate_decision_hash")
                == snapshot.candidate_decision_hash
            ]
            matches = [item for item in history if item.snapshot_id == snapshot.snapshot_id]
            if matches:
                return None
            if history and parse_utc(snapshot.observed_at) <= parse_utc(history[-1].observed_at):
                raise RegistryConflict("execution market snapshot time must advance")
            return payload

        self.log.transaction(build)
        return snapshot

    def current(self, candidate_decision_hash: str) -> ExecutionMarketSnapshot:
        history = [
            self._from_row(row)
            for row in self.log.records()
            if row.get("record_type") == "execution_market_snapshot"
            and row.get("schema_version") == "execution-market-snapshot-v2"
            and row.get("candidate_decision_hash") == candidate_decision_hash
        ]
        if not history:
            raise RegistryConflict("execution market snapshot is unavailable")
        return history[-1]


def _within_pinned_odds_profile(policy: PolicySet, output: dict, odds: str) -> bool:
    """E5: a price inside the output's requested bounds and its pinned active profile.

    The profile test is the one qualification applies: the active profile the
    price falls in must be the one the decision output pins.
    """

    try:
        price = Decimal(odds)
        return (
            Decimal(output["requested_odds_min"]) <= price <= Decimal(output["requested_odds_max"])
            and odds_profile_hash(policy, matched_odds_profile(policy, price))
            == output["odds_profile_hash"]
        )
    except Exception:
        return False


@dataclass(frozen=True)
class RecertificationResult:
    passed: bool
    reason: str
    requires_new_candidate: bool = False


class StrategyExecutionReadView(Protocol):
    def is_active(self, candidate_decision_hash: str, at: str) -> bool | None: ...


@dataclass(frozen=True)
class RegistryStrategyExecutionView:
    """Exact V3 qualification/output binding to a durable PAPER strategy head.

    A positive read authorizes a new action only while ``log`` is fenced by
    that action's append transaction. Historical decision-time lifecycle is
    deliberately separate from this current-head check.
    """

    registry: StrategyRegistry

    def __post_init__(self) -> None:
        if type(self.registry) is not StrategyRegistry:
            raise TypeError("strategy execution view requires a real registry")

    @property
    def log(self) -> AppendOnlyJsonl:
        return self.registry.log

    def require_active(
        self, qualification: QualificationRecord, output: dict,
        candidate_decision_hash: str,
    ) -> None:
        if any((
            qualification.candidate_decision_hash != candidate_decision_hash,
            output.get("strategy_id") != qualification.strategy_id,
            output.get("strategy_version") != qualification.strategy_version,
            output.get("strategy_decision_contract_hash")
            != qualification.strategy_decision_contract_hash,
        )):
            raise RegistryConflict("strategy/output/qualification identity differs")
        contract = self.registry.get_decision_contract(
            qualification.strategy_decision_contract_hash
        )
        if any((
            output.get("strategy_config_hash") != contract.strategy_config_hash,
            output.get("odds_profile_hash") != contract.odds_profile_hash,
            output.get("sport_adapter_version") != contract.sport_adapter_version,
            output.get("market_capability_id") != contract.market_capability_id,
            output.get("model_artifact_hash") != contract.model_artifact_hash,
            output.get("calibration_artifact_hash") != contract.calibration_artifact_hash,
            output.get("feature_manifest_hash") != contract.feature_manifest_hash,
            output.get("gate_policy_hash") != contract.gate_policy_hash,
            output.get("comparability_group_id") != contract.comparability_group_id,
            output.get("support_region_id") != contract.support_region,
            output.get("approved_tier") not in contract.approved_tiers,
        )):
            raise RegistryConflict("decision output does not match strategy contract")
        self.registry.require_current_paper_contract(
            qualification.strategy_id,
            qualification.strategy_version,
            qualification.strategy_decision_contract_hash,
        )


class FailClosedStrategyExecutionView:
    def is_active(self, candidate_decision_hash: str, at: str) -> None:
        del candidate_decision_hash, at
        return None


@dataclass(frozen=True)
class OrderIntent:
    candidate_decision_hash: str
    idempotency_key: str
    side: BetSide
    stake: str
    odds: str
    risk_approval_id: str
    created_at: str
    mode: OperationalMode = OperationalMode.PAPER

    def __post_init__(self) -> None:
        if (
            len(self.candidate_decision_hash) != 64
            or len(self.risk_approval_id) != 64
            or not self.idempotency_key
        ):
            raise ValueError("order intent identity is invalid")
        if Decimal(self.stake) <= 0 or Decimal(self.odds) <= 1:
            raise ValueError("order stake and odds are invalid")
        if self.mode != OperationalMode.PAPER:
            raise ValueError("V0.4 execution only supports PAPER mode")
        parse_utc(self.created_at)

    @property
    def liability(self) -> Decimal:
        return money(
            MatchedFragment(
                "execution-intent", self.side, Decimal(self.odds), Decimal(self.stake)
            ).liability
        )

    def to_dict(self) -> dict:
        value = asdict(self)
        value["side"] = self.side.value
        value["mode"] = self.mode.value
        value["created_at"] = iso_utc(self.created_at)
        return value

    @property
    def order_id(self) -> str:
        return sha256_bytes(canonical_json(self.to_dict()))


@dataclass(frozen=True)
class OrderRecord:
    intent: OrderIntent
    state: OrderState
    state_history: tuple[OrderState, ...]

    @property
    def order_id(self) -> str:
        return self.intent.order_id

    def transition(self, state: OrderState) -> "OrderRecord":
        if state not in _TRANSITIONS[self.state]:
            raise ValueError(f"invalid order transition {self.state} -> {state}")
        return replace(self, state=state, state_history=self.state_history + (state,))


class PaperExecutionAdapter:
    """Durable V2 PAPER order state machine with exact risk binding."""

    def __init__(
        self,
        audit_path: str | Path,
        *,
        risk: RiskEngine,
        markets: ExecutionMarketStateStore,
        refreshes: CriticalEvidenceRefreshStore,
        strategy_view: StrategyExecutionReadView | RegistryStrategyExecutionView,
        action_clock: Callable[[str], str] | None = None,
        modes: ModeStateStore | None = None,
    ):
        if any(value is None for value in (audit_path, risk, markets, refreshes, strategy_view)):
            raise TypeError("PaperExecutionAdapter requires every execution authority")
        if not (
            type(strategy_view) is RegistryStrategyExecutionView
            or callable(getattr(strategy_view, "is_active", None))
        ):
            raise TypeError("strategy execution read view is incomplete")
        self._audit = AppendOnlyJsonl(audit_path)
        self.risk = risk
        self.markets = markets
        self.refreshes = refreshes
        self.strategy_view = strategy_view
        self.modes = modes
        # The default is real UTC sampled inside the submission fence. An
        # explicit injected clock is solely for deterministic offline tests;
        # neither a caller's occurred_at nor a recertified flag is authority.
        self._action_clock = action_clock or (
            lambda _requested_at: iso_utc(datetime.now(timezone.utc))
        )
        base = self._replay(self._audit.records())
        self._startup_blocked: set[str] = {
            record.order_id for record in base.values() if record.state in _RESTART_AMBIGUOUS
        }
        for record in base.values():
            if record.state == OrderState.ORDER_INTENT_CREATED:
                try:
                    approval = self.risk.get_approval(record.intent.risk_approval_id)
                    if approval.consumed_by_order_id == record.order_id:
                        self._startup_blocked.add(record.order_id)
                except Exception:
                    pass
        # N2: one order log (with its market and refresh stores) per risk
        # authority. A later adapter over another log is refused at action time.
        self.risk.register_owners({
            "order": self._audit.path,
            "market": log_path(self.markets),
            "refresh": log_path(self.refreshes),
        }, anchors=("order",))

    def _execution_owner_paths(
        self,
        strategy_view: StrategyExecutionReadView | RegistryStrategyExecutionView,
        mode_states: ModeStateStore | None,
    ) -> dict[str, Path | None]:
        return {
            "order": self._audit.path,
            "market": log_path(self.markets),
            "refresh": log_path(self.refreshes),
            "strategy": (
                strategy_view.log.path
                if type(strategy_view) is RegistryStrategyExecutionView else None
            ),
            "mode": mode_states.log.path if type(mode_states) is ModeStateStore else None,
        }

    @staticmethod
    def _intent_from_row(row: dict) -> OrderIntent:
        required = {
            "candidate_decision_hash",
            "idempotency_key",
            "side",
            "stake",
            "odds",
            "risk_approval_id",
            "created_at",
            "mode",
        }
        if any(key not in row for key in required):
            raise RegistryConflict("active V2 order intent is incomplete")
        return OrderIntent(
            row["candidate_decision_hash"],
            row["idempotency_key"],
            BetSide(row["side"]),
            row["stake"],
            row["odds"],
            row["risk_approval_id"],
            row["created_at"],
            OperationalMode(row["mode"]),
        )

    def _replay(self, rows: tuple[dict, ...] | list[dict]) -> dict[str, OrderRecord]:
        records: dict[str, OrderRecord] = {}
        keys: set[str] = set()
        candidates: set[str] = set()
        for row in rows:
            if row.get("schema_version") != "order-event-v2":
                raise RegistryConflict("unsupported or missing active order event schema")
            event = row.get("record_type")
            if event == "order_intent_created":
                intent = self._intent_from_row(row)
                if row.get("order_id") != intent.order_id:
                    raise RegistryConflict("order intent ID mismatch")
                if (
                    intent.order_id in records
                    or intent.idempotency_key in keys
                    or intent.candidate_decision_hash in candidates
                ):
                    raise RegistryConflict("duplicate order lineage in replay")
                records[intent.order_id] = OrderRecord(
                    intent,
                    OrderState.ORDER_INTENT_CREATED,
                    (OrderState.ORDER_INTENT_CREATED,),
                )
                keys.add(intent.idempotency_key)
                candidates.add(intent.candidate_decision_hash)
            elif event == "order_state_transition":
                order_id = row.get("order_id")
                if order_id not in records:
                    raise RegistryConflict("order transition has no intent")
                record = records[order_id]
                prior = OrderState(row["from_state"])
                target = OrderState(row["to_state"])
                if record.state != prior:
                    raise RegistryConflict("order transition prior state mismatch")
                if target == OrderState.RISK_APPROVED:
                    if prior != OrderState.ORDER_INTENT_CREATED:
                        raise RegistryConflict("risk binding transition has invalid prior state")
                    records[order_id] = replace(
                        record,
                        state=target,
                        state_history=record.state_history + (target,),
                    )
                else:
                    records[order_id] = record.transition(target)
            else:
                raise RegistryConflict(f"unknown active order event: {event}")
        return records

    def _current_records(self) -> dict[str, OrderRecord]:
        records = self._replay(self._audit.records())
        for order_id in self._startup_blocked:
            if order_id in records and records[order_id].state != OrderState.RECONCILIATION_REQUIRED:
                record = records[order_id]
                records[order_id] = replace(
                    record,
                    state=OrderState.RECONCILIATION_REQUIRED,
                    state_history=record.state_history
                    + (OrderState.RECONCILIATION_REQUIRED,),
                )
        return records

    def create_intent(self, intent: OrderIntent) -> OrderRecord:
        result: dict[str, OrderRecord] = {}
        payload = {
            "record_type": "order_intent_created",
            "schema_version": "order-event-v2",
            "order_id": intent.order_id,
            **intent.to_dict(),
        }

        def build(rows: tuple[dict, ...]) -> dict | None:
            records = self._replay(rows)
            self.risk.require_bound_owners(
                self._execution_owner_paths(self.strategy_view, self.modes)
            )
            try:
                approval = self.risk.get_approval(intent.risk_approval_id)
                qualification = self.risk.qualifications.get_for_new_risk(
                    approval.qualification_record_id, at=intent.created_at,
                )
            except Exception as exc:
                raise RegistryConflict("new order requires exact V3 qualification") from exc
            if (approval.candidate_decision_hash != intent.candidate_decision_hash
                    or qualification.candidate_decision_hash != intent.candidate_decision_hash):
                raise RegistryConflict("order candidate/output lineage differs")
            by_key = {
                record.intent.idempotency_key: record for record in records.values()
            }
            by_candidate = {
                record.intent.candidate_decision_hash: record for record in records.values()
            }
            existing = by_key.get(intent.idempotency_key)
            if existing is not None:
                if existing.intent.to_dict() != intent.to_dict():
                    raise RegistryConflict("idempotency key reused for different intent")
                result["value"] = existing
                return None
            if intent.candidate_decision_hash in by_candidate:
                raise RegistryConflict("candidate already has an order-intent lineage")
            record = OrderRecord(
                intent,
                OrderState.ORDER_INTENT_CREATED,
                (OrderState.ORDER_INTENT_CREATED,),
            )
            result["value"] = record
            return payload

        self._audit.transaction(
            build, read_locks=(
                self.risk.audit_log.log, self.risk.qualifications.log,
                self.risk.qualifications.bindings.log,
                self.risk.qualifications.approvals.log,
                self.risk.qualifications.witnesses,
                self.risk.owner_binding.log,
            ),
        )
        return result["value"]

    def get(self, idempotency_key: str) -> OrderRecord:
        matches = [
            record
            for record in self._current_records().values()
            if record.intent.idempotency_key == idempotency_key
        ]
        if len(matches) != 1:
            raise RegistryConflict(f"unknown or ambiguous order key: {idempotency_key}")
        record = matches[0]
        if record.state == OrderState.ORDER_INTENT_CREATED:
            try:
                approval = self.risk.get_approval(record.intent.risk_approval_id)
                if approval.consumed_by_order_id == record.order_id:
                    return replace(
                        record,
                        state=OrderState.RECONCILIATION_REQUIRED,
                        state_history=record.state_history
                        + (OrderState.RECONCILIATION_REQUIRED,),
                    )
            except Exception:
                pass
        return record

    def bind_risk(
        self,
        idempotency_key: str,
        *,
        bound_at: str,
        fault_after_consume: bool = False,
    ) -> OrderRecord:
        record = self.get(idempotency_key)
        if record.state != OrderState.ORDER_INTENT_CREATED:
            if record.state == OrderState.RISK_APPROVED:
                return record
            raise RegistryConflict("order is not eligible for risk binding")
        approval = self.risk.get_approval(record.intent.risk_approval_id)
        qualification = self.risk.qualifications.get_for_new_risk(
            approval.qualification_record_id, at=bound_at,
        )
        if qualification.candidate_decision_hash != record.intent.candidate_decision_hash:
            raise RegistryConflict("order lacks exact V3 qualification lineage")
        if approval.status != "APPROVED_NOT_CONSUMED":
            raise RegistryConflict("risk approval is not available for binding")
        expected = (
            approval.candidate_decision_hash == record.intent.candidate_decision_hash,
            Decimal(approval.approved_stake) == Decimal(record.intent.stake),
            Decimal(approval.approved_liability) == record.intent.liability,
            approval.side == record.intent.side,
            Decimal(approval.odds) == Decimal(record.intent.odds),
            parse_utc(bound_at) < parse_utc(approval.expires_at),
        )
        if not all(expected):
            raise RegistryConflict("order intent does not exactly match risk approval")
        # The consuming order log must be the one bound to this risk authority.
        self.risk.require_bound_owners(
            self._execution_owner_paths(self.strategy_view, self.modes)
        )
        self.risk.consume_for_order(
            approval.approval_id, order_id=record.order_id, consumed_at=bound_at
        )
        if fault_after_consume:
            raise RuntimeError("injected crash after risk consumption")

        result: dict[str, OrderRecord] = {}

        def build(rows: tuple[dict, ...]) -> dict | None:
            records = self._replay(rows)
            current = records[record.order_id]
            if current.state == OrderState.RISK_APPROVED:
                result["value"] = current
                return None
            if current.state != OrderState.ORDER_INTENT_CREATED:
                raise RegistryConflict("order state changed during risk binding")
            updated = replace(
                current,
                state=OrderState.RISK_APPROVED,
                state_history=current.state_history + (OrderState.RISK_APPROVED,),
            )
            result["value"] = updated
            return {
                "record_type": "order_state_transition",
                "schema_version": "order-event-v2",
                "order_id": current.order_id,
                "from_state": current.state.value,
                "to_state": OrderState.RISK_APPROVED.value,
                "occurred_at": iso_utc(bound_at),
                "risk_approval_id": current.intent.risk_approval_id,
            }

        self._audit.transaction(build)
        return result["value"]

    def transition(
        self, idempotency_key: str, state: OrderState, *, occurred_at: str
    ) -> OrderRecord:
        if state == OrderState.RISK_APPROVED:
            raise RegistryConflict("RISK_APPROVED requires bind_risk()")
        result: dict[str, OrderRecord] = {}
        # Capture the exact owner used to choose the fence. A mutable adapter
        # attribute cannot switch from a legacy view to a bound view after the
        # lock set has been assembled.
        strategy_view = self.strategy_view
        mode_states = self.modes
        risk_mode_states = self.risk.modes
        release_proofs = self.risk.release_proofs
        if state in {OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT} \
                and type(mode_states) is not ModeStateStore:
            raise RegistryConflict("submission requires a durable mode authority")

        def build(rows: tuple[dict, ...]) -> dict:
            records = self._replay(rows)
            matches = [
                item
                for item in records.values()
                if item.intent.idempotency_key == idempotency_key
            ]
            if len(matches) != 1:
                raise RegistryConflict("unknown order")
            current = matches[0]
            if current.order_id in self._startup_blocked:
                raise RegistryConflict("order requires reconciliation after restart")
            if state in {OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT} \
                    and self.risk.release_proofs is not release_proofs:
                raise RegistryConflict("release proof owner changed before submission")
            if state in {OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT} \
                    and self.risk.modes is not risk_mode_states:
                raise RegistryConflict("risk mode owner changed before submission")
            action_at = iso_utc(self._action_clock(occurred_at)) if state in {
                OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT,
            } else iso_utc(occurred_at)
            if state in {OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT}:
                allowed_prior = (
                    OrderState.RISK_APPROVED
                    if state == OrderState.SUBMISSION_PENDING
                    else OrderState.SUBMISSION_PENDING
                )
                if current.state != allowed_prior:
                    raise RegistryConflict("submission has an invalid prior order state")
                recertification = self._recertify_record(
                    current, at=action_at, strategy_view=strategy_view,
                    mode_states=mode_states, release_fenced=True,
                )
                if not recertification.passed:
                    raise RegistryConflict(
                        f"submission recertification blocked: {recertification.reason}"
                    )
            updated = current.transition(state)
            result["value"] = updated
            return {
                "record_type": "order_state_transition",
                "schema_version": "order-event-v2",
                "order_id": current.order_id,
                "from_state": current.state.value,
                "to_state": state.value,
                "occurred_at": action_at,
            }

        read_locks = (
            self.risk.audit_log.log,
            self.risk.bankrolls.log,
            self.risk.safety.log,
            self.risk.qualifications.log,
            self.risk.qualifications.bindings.log,
            self.risk.qualifications.approvals.log,
            self.risk.qualifications.witnesses,
            self.markets.log,
            self.refreshes.log,
            *self.risk._release_read_locks_for(release_proofs),
            self.risk.owner_binding.log,
        ) if state in {OrderState.SUBMISSION_PENDING, OrderState.SUBMISSION_SENT} else ()
        if read_locks and type(strategy_view) is RegistryStrategyExecutionView:
            read_locks += (strategy_view.log,)
        if read_locks and type(mode_states) is ModeStateStore:
            read_locks += (mode_states.log,)
        self._audit.transaction(build, read_locks=read_locks)
        return result["value"]

    def mark_submission_timeout(
        self, idempotency_key: str, *, occurred_at: str
    ) -> OrderRecord:
        record = self.get(idempotency_key)
        if record.state == OrderState.SUBMISSION_PENDING:
            record = self.transition(
                idempotency_key, OrderState.UNKNOWN, occurred_at=occurred_at
            )
        if record.state == OrderState.UNKNOWN:
            record = self.transition(
                idempotency_key,
                OrderState.RECONCILIATION_REQUIRED,
                occurred_at=occurred_at,
            )
        return record

    def recertify(self, idempotency_key: str, *, at: str) -> RecertificationResult:
        strategy_view = self.strategy_view
        mode_states = self.modes
        risk_mode_states = self.risk.modes
        release_proofs = self.risk.release_proofs
        if type(strategy_view) is not RegistryStrategyExecutionView:
            return RecertificationResult(False, "strategy_authority_unfenced")
        if type(mode_states) is not ModeStateStore:
            return RecertificationResult(False, "mode_authority_unfenced")
        result: dict[str, RecertificationResult] = {}

        def inspect(rows: tuple[dict, ...]) -> None:
            if (
                self.strategy_view is not strategy_view
                or self.modes is not mode_states
                or self.risk.modes is not risk_mode_states
                or self.risk.release_proofs is not release_proofs
            ):
                raise RegistryConflict("recertification owner changed during fenced read")
            matches = [
                item for item in self._replay(rows).values()
                if item.intent.idempotency_key == idempotency_key
            ]
            if len(matches) != 1:
                raise RegistryConflict("unknown order")
            result["value"] = self._recertify_record(
                matches[0], at=iso_utc(self._action_clock(at)),
                strategy_view=strategy_view, mode_states=mode_states,
                release_fenced=True,
            )
            return None

        self._audit.transaction(
            inspect,
            read_locks=(
                self.risk.audit_log.log, self.risk.bankrolls.log,
                self.risk.safety.log, self.risk.qualifications.log,
                self.risk.qualifications.bindings.log,
                self.risk.qualifications.approvals.log,
                self.risk.qualifications.witnesses, self.markets.log,
                self.refreshes.log, strategy_view.log, mode_states.log,
                *self.risk._release_read_locks_for(release_proofs),
                self.risk.owner_binding.log,
            ),
        )
        return result["value"]

    def _recertify_record(
        self, record: OrderRecord, *, at: str,
        strategy_view: StrategyExecutionReadView | RegistryStrategyExecutionView | None = None,
        mode_states: ModeStateStore | None = None,
        release_fenced: bool = False,
    ) -> RecertificationResult:
        view = self.strategy_view if strategy_view is None else strategy_view
        if type(view) is not RegistryStrategyExecutionView:
            return RecertificationResult(False, "strategy_authority_unfenced")
        modes = self.modes if mode_states is None else mode_states
        if type(modes) is not ModeStateStore:
            return RecertificationResult(False, "mode_authority_unfenced")
        risk_modes = self.risk.modes
        if (
            type(risk_modes) is not ModeStateStore
            or risk_modes.log.coordinator_path.resolve()
            != modes.log.coordinator_path.resolve()
        ):
            return RecertificationResult(False, "mode_authority_mismatch")
        try:
            # N2: every owner this send reads (order, market, refresh,
            # strategy, mode and risk's own owners, plus release owners when
            # release-fenced) must be the risk authority's bound owner.
            if self.risk.owner_mismatches(
                self._execution_owner_paths(view, modes),
                release_proofs=self.risk.release_proofs if release_fenced else None,
            ):
                return RecertificationResult(False, "owner_authority_mismatch")
        except Exception:
            return RecertificationResult(False, "authority_unavailable")
        try:
            approval = self.risk.get_approval(record.intent.risk_approval_id)
            qualification = self.risk.qualifications.get_for_new_risk(
                approval.qualification_record_id, at=at,
            )
            assert qualification.decision_output_hash is not None
            output = self.risk.qualifications.outputs.get(
                qualification.decision_output_hash
            )
            refresh = self.refreshes.current(record.intent.candidate_decision_hash)
            market = self.markets.current(record.intent.candidate_decision_hash)
            mode_head = modes.current()
            safety_head = self.risk.safety.current()
            view.require_active(
                qualification, output, record.intent.candidate_decision_hash,
            )
        except Exception:
            return RecertificationResult(False, "authority_unavailable")
        executable_price_ok = (
            Decimal(market.executable_odds) >= Decimal(record.intent.odds)
            if record.intent.side == BetSide.BACK
            else Decimal(market.executable_odds) <= Decimal(record.intent.odds)
        )
        checks = (
            (
                approval.status == "CONSUMED"
                and approval.consumed_by_order_id == record.order_id
                and approval.candidate_decision_hash == record.intent.candidate_decision_hash
                and approval.side == record.intent.side
                and Decimal(approval.approved_stake) == Decimal(record.intent.stake)
                and Decimal(approval.approved_liability) == record.intent.liability
                and Decimal(approval.odds) == Decimal(record.intent.odds),
                "risk_approval_binding_invalid",
            ),
            (
                record.state in {OrderState.RISK_APPROVED, OrderState.SUBMISSION_PENDING},
                "order_not_submittable",
            ),
            (
                qualification.active_policy_digest == self.risk.policy_set.digest
                and approval.risk_policy_digest == self.risk.policy.digest,
                "policy_binding_invalid",
            ),
            (parse_utc(at) < parse_utc(approval.expires_at), "candidate_expired"),
            (parse_utc(refresh.checked_at) <= parse_utc(at), "refresh_not_yet_available"),
            (parse_utc(market.observed_at) <= parse_utc(at), "market_not_yet_observed"),
            (refresh.valid, "critical_evidence_refresh_failed"),
            (not refresh.material_change, "critical_evidence_changed"),
            (market.market_open, "market_closed"),
            (executable_price_ok, "executable_price_changed"),
            (
                all(
                    _within_pinned_odds_profile(self.risk.policy_set, output, odds)
                    for odds in (record.intent.odds, market.executable_odds)
                ),
                "executable_price_outside_odds_profile",
            ),
            (
                Decimal(market.available_liquidity) >= Decimal(record.intent.stake),
                "liquidity_unavailable",
            ),
            (
                self.risk.approval_still_valid(
                    approval.approval_id, at=at, release_fenced=release_fenced,
                ),
                "risk_or_safety_state_blocked",
            ),
            (
                mode_head.mode == OperationalMode.PAPER
                and not safety_head.kill_switch_active
                and iso_utc(mode_head.occurred_at) == iso_utc(safety_head.recorded_at)
                and safety_head.reason == "mode:paper",
                "mode_safety_head_not_coherent_paper",
            ),
        )
        for passed, reason in checks:
            if not passed:
                return RecertificationResult(
                    False, reason, reason == "critical_evidence_changed"
                )
        return RecertificationResult(True, "recertified")

    def liquidity_ok(self, candidate) -> bool | None:
        try:
            snapshot = self.markets.current(candidate.candidate_decision_hash)
            return snapshot.market_open and Decimal(snapshot.available_liquidity) > 0
        except Exception:
            return None

    def execution_available(self, candidate) -> bool | None:
        return self.liquidity_ok(candidate)

    def no_duplicate_order(self, candidate) -> bool | None:
        try:
            return not any(
                record.intent.candidate_decision_hash == candidate.candidate_decision_hash
                for record in self._current_records().values()
            )
        except Exception:
            return None

    def no_kill_condition(self, candidate) -> bool | None:
        del candidate
        try:
            return not self.risk.safety.current().kill_switch_active
        except Exception:
            return None


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


@dataclass(frozen=True)
class ModeState:
    state_id: str
    mode: OperationalMode
    occurred_at: str
    authorization_id: str | None
    parent_state_id: str | None

    def __post_init__(self) -> None:
        parse_utc(self.occurred_at)
        if self.mode in {OperationalMode.MICRO_LIVE, OperationalMode.LIVE}:
            raise ValueError("live modes are not implemented")
        if self.compute_id() != self.state_id:
            raise ValueError("mode state ID mismatch")

    def unsigned_dict(self) -> dict:
        value = asdict(self)
        value.pop("state_id")
        value["mode"] = self.mode.value
        value["occurred_at"] = iso_utc(self.occurred_at)
        return value

    def compute_id(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    @classmethod
    def create(cls, **fields) -> "ModeState":
        normalized = dict(fields)
        normalized["mode"] = OperationalMode(normalized["mode"])
        normalized["occurred_at"] = iso_utc(normalized["occurred_at"])
        unsigned = dict(normalized)
        unsigned["mode"] = normalized["mode"].value
        return cls(state_id=sha256_bytes(canonical_json(unsigned)), **normalized)

    def to_dict(self) -> dict:
        return {"state_id": self.state_id, **self.unsigned_dict()}


class ModeStateStore:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    @staticmethod
    def _from_row(row: dict) -> ModeState:
        fields = {key: row[key] for key in ModeState.__dataclass_fields__}
        fields["mode"] = OperationalMode(fields["mode"])
        return ModeState(**fields)

    def _history(self, rows: tuple[dict, ...] | list[dict]) -> tuple[ModeState, ...]:
        history: list[ModeState] = []
        for row in rows:
            if (row.get("record_type"), row.get("schema_version")) != (
                "safety_mode_transition", "mode-state-v2",
            ):
                raise RegistryConflict("unsupported active mode event")
            try:
                state = self._from_row(row)
            except (KeyError, TypeError, ValueError) as exc:
                raise RegistryConflict("incomplete active mode event") from exc
            if history:
                prior = history[-1]
                if (
                    state.parent_state_id != prior.state_id
                    or parse_utc(state.occurred_at) <= parse_utc(prior.occurred_at)
                ):
                    raise RegistryConflict("mode replay has an invalid head transition")
            elif state.parent_state_id is not None:
                raise RegistryConflict("initial mode replay has a parent")
            history.append(state)
        return tuple(history)

    def current(self) -> ModeState:
        history = self._history(self.log.records())
        if not history:
            raise RegistryConflict("mode authority has no current state")
        return history[-1]

    def append(self, state: ModeState) -> ModeState:
        payload = {
            "record_type": "safety_mode_transition",
            "schema_version": "mode-state-v2",
            **state.to_dict(),
        }

        def build(rows: tuple[dict, ...]) -> dict | None:
            history = self._history(rows)
            if any(item.state_id == state.state_id for item in history):
                return None
            current = history[-1] if history else None
            if current is None and state.parent_state_id is not None:
                raise RegistryConflict("initial mode state cannot have a parent")
            if current is not None:
                if state.parent_state_id != current.state_id:
                    raise RegistryConflict("mode state does not extend current head")
                if parse_utc(state.occurred_at) <= parse_utc(current.occurred_at):
                    raise RegistryConflict("mode state time must advance")
            return payload

        self.log.transaction(build)
        return state


class ModeController:
    def __init__(self, states: ModeStateStore, safety: SafetyStateStore):
        self.states = states
        self.safety = safety
        self.states.current()
        self.safety.current()

    @property
    def mode(self) -> OperationalMode:
        return self.states.current().mode

    @property
    def kill_switch_active(self) -> bool:
        return self.safety.current().kill_switch_active

    def transition(
        self,
        target: OperationalMode,
        authorization: AuthorizationArtifact | None = None,
        *,
        occurred_at: str,
    ) -> OperationalMode:
        if target in {OperationalMode.MICRO_LIVE, OperationalMode.LIVE}:
            raise ValueError("live modes are not implemented")
        if authorization is None and target not in {
            OperationalMode.DISABLED,
            OperationalMode.KILL_SWITCH_ACTIVE,
        }:
            raise PermissionError("mode transition requires explicit authorization")
        if authorization is not None and authorization.mode != target:
            raise ValueError("authorization mode does not match target")
        current = self.states.current()
        self.states.append(
            ModeState.create(
                mode=target,
                occurred_at=occurred_at,
                authorization_id=(authorization.authorization_id if authorization else None),
                parent_state_id=current.state_id,
            )
        )
        safety = self.safety.current()
        self.safety.append(
            SafetyState.create(
                kill_switch_active=target == OperationalMode.KILL_SWITCH_ACTIVE,
                recorded_at=occurred_at,
                reason=f"mode:{target.value}",
                parent_state_id=safety.state_id,
            )
        )
        return target

    def activate_kill_switch(self, *, occurred_at: str) -> OperationalMode:
        return self.transition(
            OperationalMode.KILL_SWITCH_ACTIVE, occurred_at=occurred_at
        )
