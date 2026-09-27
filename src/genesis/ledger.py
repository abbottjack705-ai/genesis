"""Append-only fill and single-head settlement ledger.

The JSONL is the authority.  Every write replays and validates the complete
history while holding the shared append lock, so fill-head uniqueness is an
inter-process invariant rather than an in-memory convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .accounting import BetSide, MatchedFragment, SettlementKind, settle_back, settle_lay
from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, sha256_bytes
from .time import iso_utc, parse_utc


FILL_SCHEMA_VERSION = "fill-record-v2"
LEDGER_EVENT_SCHEMA_VERSION = "ledger-event-v2"


def _decimal(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RegistryConflict(f"ledger {field} is not a decimal") from exc
    if not number.is_finite():
        raise RegistryConflict(f"ledger {field} must be finite")
    return number


def _decimal_text(value: Decimal | str) -> str:
    return format(Decimal(str(value)), "f")


@dataclass(frozen=True)
class FillRecord:
    fill_id: str
    order_id: str
    candidate_decision_hash: str
    side: BetSide
    odds: str
    stake: str
    filled_at: str

    def __post_init__(self) -> None:
        if not self.fill_id or not self.order_id or len(self.candidate_decision_hash) != 64:
            raise ValueError("fill identity is invalid")
        int(self.candidate_decision_hash, 16)
        object.__setattr__(self, "side", BetSide(self.side))
        object.__setattr__(self, "odds", str(self.odds))
        object.__setattr__(self, "stake", str(self.stake))
        if Decimal(str(self.odds)) <= 1 or Decimal(str(self.stake)) <= 0:
            raise ValueError("fill odds/stake are invalid")
        parse_utc(self.filled_at)
        object.__setattr__(self, "filled_at", iso_utc(self.filled_at))

    def fragment(self) -> MatchedFragment:
        """Return the exact accounting fragment represented by this fill."""

        return MatchedFragment(
            self.fill_id,
            BetSide(self.side),
            Decimal(str(self.odds)),
            Decimal(str(self.stake)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "candidate_decision_hash": self.candidate_decision_hash,
            "side": BetSide(self.side).value,
            "odds": str(self.odds),
            "stake": str(self.stake),
            "filled_at": iso_utc(self.filled_at),
        }


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    event_type: str
    occurred_at: str
    fill_id: str
    settlement_kind: SettlementKind
    dead_heat_fraction: str = "1"
    commission_rate: str = "0"
    delta_pnl: str = "0"
    effective_pnl: str = "0"
    correction_of: str | None = None
    schema_version: str = LEDGER_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.event_id or self.event_type not in {"settlement", "cancellation"}:
            raise ValueError("ledger event identity/type is invalid")
        if not self.fill_id:
            raise ValueError("settlement fill identity is required")
        if self.schema_version not in {LEDGER_EVENT_SCHEMA_VERSION, "legacy-ledger-event-v1"}:
            raise ValueError("unsupported ledger event schema")
        object.__setattr__(self, "settlement_kind", SettlementKind(self.settlement_kind))
        parse_utc(self.occurred_at)
        object.__setattr__(self, "occurred_at", iso_utc(self.occurred_at))
        for name in ("dead_heat_fraction", "commission_rate", "delta_pnl", "effective_pnl"):
            value = Decimal(str(getattr(self, name)))
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")
            object.__setattr__(self, name, _decimal_text(value))
        if self.event_type == "cancellation" and self.settlement_kind != SettlementKind.VOID:
            raise ValueError("cancellation must use VOID settlement semantics")

    @property
    def pnl(self) -> str:
        """Compatibility alias: event P/L means the ledger delta, never the head."""

        return self.delta_pnl

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": iso_utc(self.occurred_at),
            "fill_id": self.fill_id,
            "settlement_kind": SettlementKind(self.settlement_kind).value,
            "dead_heat_fraction": str(self.dead_heat_fraction),
            "commission_rate": str(self.commission_rate),
            "delta_pnl": str(self.delta_pnl),
            "effective_pnl": str(self.effective_pnl),
            "correction_of": self.correction_of,
        }


@dataclass(frozen=True)
class _LedgerState:
    fills: dict[str, FillRecord]
    events: dict[str, LedgerEvent]
    heads: dict[str, LedgerEvent]


class SettlementLedger:
    """P/L authority derived only from verified fills and settlement lineages."""

    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path, reader=self._replay)
        self._replay(tuple(self.log.records()))

    @staticmethod
    def _fill_from_row(row: dict[str, Any]) -> FillRecord:
        schema = row.get("schema_version")
        if schema not in {None, FILL_SCHEMA_VERSION}:
            raise RegistryConflict("unsupported fill schema")
        try:
            return FillRecord(
                fill_id=row["fill_id"],
                order_id=row["order_id"],
                candidate_decision_hash=row["candidate_decision_hash"],
                side=BetSide(row["side"]),
                odds=row["odds"],
                stake=row["stake"],
                filled_at=row["filled_at"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryConflict("invalid fill record") from exc

    @staticmethod
    def _economic_result(
        fill: FillRecord,
        kind: SettlementKind,
        commission_rate: str,
        dead_heat_fraction: str,
    ) -> Decimal:
        try:
            if fill.side == BetSide.BACK:
                result = settle_back(
                    fill.stake,
                    fill.odds,
                    kind=kind,
                    commission_rate=commission_rate,
                    dead_heat_fraction=dead_heat_fraction,
                )
            else:
                result = settle_lay(
                    fill.stake,
                    fill.odds,
                    kind=kind,
                    commission_rate=commission_rate,
                )
        except (InvalidOperation, ValueError) as exc:
            raise RegistryConflict("invalid settlement arithmetic inputs") from exc
        return result.pnl

    @classmethod
    def _event_from_row(
        cls,
        row: dict[str, Any],
        *,
        fill: FillRecord,
        prior: LedgerEvent | None,
    ) -> LedgerEvent:
        schema = row.get("schema_version")
        if schema == LEDGER_EVENT_SCHEMA_VERSION:
            required = {
                "event_id",
                "event_type",
                "occurred_at",
                "fill_id",
                "settlement_kind",
                "dead_heat_fraction",
                "commission_rate",
                "delta_pnl",
                "effective_pnl",
                "correction_of",
            }
            if not required.issubset(row):
                raise RegistryConflict("V2 settlement record is incomplete")
            try:
                return LedgerEvent(
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    occurred_at=row["occurred_at"],
                    fill_id=row["fill_id"],
                    settlement_kind=SettlementKind(row["settlement_kind"]),
                    dead_heat_fraction=row["dead_heat_fraction"],
                    commission_rate=row["commission_rate"],
                    delta_pnl=row["delta_pnl"],
                    effective_pnl=row["effective_pnl"],
                    correction_of=row["correction_of"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RegistryConflict("invalid V2 settlement record") from exc
        if schema is not None:
            raise RegistryConflict("unsupported settlement schema")

        # Explicit, conservative migration for the audited legacy schema.  A
        # single initial result and one valid direct correction are derivable;
        # duplicate unlinked results and deeper legacy chains are ambiguous.
        if row.get("record_type") != "settlement":
            raise RegistryConflict("legacy cancellation has no economic lineage")
        try:
            correction_of = row.get("correction_of")
            if prior is not None and prior.schema_version == "legacy-ledger-event-v1":
                if prior.correction_of is not None:
                    raise RegistryConflict("multi-level legacy correction is ambiguous")
            legacy_delta = _decimal(row["pnl"], "legacy pnl")
            effective = legacy_delta if prior is None else _decimal(prior.effective_pnl, "effective pnl") + legacy_delta
            return LedgerEvent(
                event_id=row["event_id"],
                event_type=row.get("event_type", "settlement"),
                occurred_at=row["occurred_at"],
                fill_id=row["fill_id"],
                settlement_kind=SettlementKind(row["settlement_kind"]),
                dead_heat_fraction=row.get("dead_heat_fraction", "1"),
                commission_rate=row.get("commission_rate", "0"),
                delta_pnl=_decimal_text(legacy_delta),
                effective_pnl=_decimal_text(effective),
                correction_of=correction_of,
                schema_version="legacy-ledger-event-v1",
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, RegistryConflict):
                raise
            raise RegistryConflict("invalid legacy settlement record") from exc

    @classmethod
    def _replay(cls, rows: tuple[dict[str, Any], ...]) -> _LedgerState:
        fills: dict[str, FillRecord] = {}
        events: dict[str, LedgerEvent] = {}
        heads: dict[str, LedgerEvent] = {}

        for row in rows:
            record_type = row.get("record_type")
            if record_type == "fill":
                fill = cls._fill_from_row(row)
                existing = fills.get(fill.fill_id)
                if existing is not None:
                    if existing == fill:
                        raise RegistryConflict("duplicate fill record")
                    raise RegistryConflict("fill ID was rewritten")
                fills[fill.fill_id] = fill
                continue
            if record_type not in {"settlement", "cancellation"}:
                raise RegistryConflict(f"unknown ledger record type: {record_type!r}")

            fill_id = row.get("fill_id")
            if fill_id not in fills:
                raise RegistryConflict("settlement references an unknown fill")
            event_id = row.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise RegistryConflict("settlement event ID is missing")
            if event_id in events:
                raise RegistryConflict("duplicate settlement event ID")

            prior = heads.get(fill_id)
            correction_of = row.get("correction_of")
            if prior is None:
                if correction_of is not None:
                    raise RegistryConflict("initial settlement cannot be a correction")
            elif correction_of is None:
                raise RegistryConflict("fill has duplicate unlinked settlements")
            elif correction_of != prior.event_id:
                raise RegistryConflict("correction must reference the current same-fill head")

            event = cls._event_from_row(row, fill=fills[fill_id], prior=prior)
            if event.fill_id != fill_id:
                raise RegistryConflict("settlement fill identity is inconsistent")
            if prior is not None and parse_utc(event.occurred_at) <= parse_utc(prior.occurred_at):
                raise RegistryConflict("settlement corrections must advance in time")
            if prior is None and parse_utc(event.occurred_at) < parse_utc(fills[fill_id].filled_at):
                raise RegistryConflict("settlement predates its fill")

            expected_effective = cls._economic_result(
                fills[fill_id],
                event.settlement_kind,
                event.commission_rate,
                event.dead_heat_fraction,
            )
            expected_delta = expected_effective
            if prior is not None:
                expected_delta -= _decimal(prior.effective_pnl, "prior effective pnl")
            if _decimal(event.effective_pnl, "effective pnl") != expected_effective:
                raise RegistryConflict("settlement effective P/L disagrees with fill arithmetic")
            if _decimal(event.delta_pnl, "delta pnl") != expected_delta:
                raise RegistryConflict("settlement delta P/L violates lineage conservation")

            events[event.event_id] = event
            heads[fill_id] = event

        delta_total = sum((_decimal(event.delta_pnl, "delta pnl") for event in events.values()), Decimal("0"))
        head_total = sum((_decimal(event.effective_pnl, "effective pnl") for event in heads.values()), Decimal("0"))
        if delta_total != head_total:
            raise RegistryConflict("settlement ledger does not conserve P/L")
        return _LedgerState(fills, events, heads)

    def record_fill(self, fill: FillRecord) -> str:
        existing_hash: str | None = None

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            nonlocal existing_hash
            state = self._replay(rows)
            existing = state.fills.get(fill.fill_id)
            if existing is None:
                return {"record_type": "fill", "schema_version": FILL_SCHEMA_VERSION, **fill.to_dict()}
            if existing != fill:
                raise RegistryConflict("fill ID cannot be rewritten")
            existing_hash = next(
                row["record_hash"]
                for row in rows
                if row.get("record_type") == "fill" and row.get("fill_id") == fill.fill_id
            )
            return None

        result = self.log.transaction(build)
        return result or existing_hash or sha256_bytes(canonical_json(fill.to_dict()))

    @staticmethod
    def _same_request(
        event: LedgerEvent,
        *,
        event_type: str,
        fill_id: str,
        kind: SettlementKind,
        occurred_at: str,
        commission_rate: str,
        dead_heat_fraction: str,
        correction_of: str | None,
    ) -> bool:
        return (
            event.event_type == event_type
            and event.fill_id == fill_id
            and event.settlement_kind == kind
            and event.occurred_at == iso_utc(occurred_at)
            and _decimal(event.commission_rate, "commission rate") == Decimal(str(commission_rate))
            and _decimal(event.dead_heat_fraction, "dead heat fraction") == Decimal(str(dead_heat_fraction))
            and event.correction_of == correction_of
        )

    def _settle(
        self,
        *,
        event_id: str,
        event_type: str,
        fill_id: str,
        kind: SettlementKind,
        occurred_at: str,
        commission_rate: str,
        dead_heat_fraction: str,
        correction_of: str | None,
    ) -> LedgerEvent:
        selected: LedgerEvent | None = None

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            nonlocal selected
            state = self._replay(rows)
            existing = state.events.get(event_id)
            if existing is not None:
                if not self._same_request(
                    existing,
                    event_type=event_type,
                    fill_id=fill_id,
                    kind=kind,
                    occurred_at=occurred_at,
                    commission_rate=commission_rate,
                    dead_heat_fraction=dead_heat_fraction,
                    correction_of=correction_of,
                ):
                    raise RegistryConflict("settlement event ID cannot be reused with a different payload")
                selected = existing
                return None

            fill = state.fills.get(fill_id)
            if fill is None:
                raise RegistryConflict("cannot settle unknown fill")
            head = state.heads.get(fill_id)
            if head is None:
                if correction_of is not None:
                    raise RegistryConflict("initial settlement cannot reference a correction")
            elif correction_of != head.event_id:
                if correction_of is None:
                    raise RegistryConflict("fill already has a settlement head")
                raise RegistryConflict("correction must reference the current same-fill head")
            if head is not None and parse_utc(occurred_at) <= parse_utc(head.occurred_at):
                raise RegistryConflict("settlement corrections must advance in time")
            if head is None and parse_utc(occurred_at) < parse_utc(fill.filled_at):
                raise RegistryConflict("settlement predates its fill")

            effective = self._economic_result(fill, kind, commission_rate, dead_heat_fraction)
            delta = effective if head is None else effective - Decimal(head.effective_pnl)
            selected = LedgerEvent(
                event_id=event_id,
                event_type=event_type,
                occurred_at=occurred_at,
                fill_id=fill_id,
                settlement_kind=kind,
                dead_heat_fraction=str(dead_heat_fraction),
                commission_rate=str(commission_rate),
                delta_pnl=_decimal_text(delta),
                effective_pnl=_decimal_text(effective),
                correction_of=correction_of,
            )
            return {"record_type": "settlement", **selected.to_dict()}

        self.log.transaction(build)
        assert selected is not None
        return selected

    def settle(
        self,
        *,
        event_id: str,
        fill_id: str,
        kind: SettlementKind,
        occurred_at: str,
        commission_rate: str = "0",
        dead_heat_fraction: str = "1",
        correction_of: str | None = None,
    ) -> LedgerEvent:
        return self._settle(
            event_id=event_id,
            event_type="settlement",
            fill_id=fill_id,
            kind=SettlementKind(kind),
            occurred_at=occurred_at,
            commission_rate=commission_rate,
            dead_heat_fraction=dead_heat_fraction,
            correction_of=correction_of,
        )

    def record_cancellation(
        self,
        *,
        event_id: str,
        fill_id: str,
        occurred_at: str,
        correction_of: str | None = None,
    ) -> LedgerEvent:
        """Record cancellation/void through the same economic lineage."""

        return self._settle(
            event_id=event_id,
            event_type="cancellation",
            fill_id=fill_id,
            kind=SettlementKind.VOID,
            occurred_at=occurred_at,
            commission_rate="0",
            dead_heat_fraction="1",
            correction_of=correction_of,
        )

    def head(self, fill_id: str) -> LedgerEvent | None:
        return self._replay(tuple(self.log.records())).heads.get(fill_id)

    def reconcile(self, *, venue_order_ids: set[str], known_order_ids: set[str]) -> bool:
        """Return false when the local fill ledger cannot explain a venue fill."""

        state = self._replay(tuple(self.log.records()))
        local_order_ids = {fill.order_id for fill in state.fills.values()}
        return venue_order_ids == (local_order_ids & known_order_ids)

    def total_pnl(self) -> str:
        state = self._replay(tuple(self.log.records()))
        delta_total = sum((Decimal(event.delta_pnl) for event in state.events.values()), Decimal("0"))
        effective_total = sum((Decimal(event.effective_pnl) for event in state.heads.values()), Decimal("0"))
        if delta_total != effective_total:
            raise RegistryConflict("settlement ledger does not conserve P/L")
        return _decimal_text(delta_total)

    def verify(self) -> int:
        rows = tuple(self.log.records())
        self._replay(rows)
        return len(rows)
