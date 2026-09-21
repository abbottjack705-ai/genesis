"""Append-only fill and settlement ledger built on existing arithmetic."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .accounting import BetSide, MatchedFragment, SettlementKind, settle_back, settle_lay
from .registry import AppendOnlyJsonl
from .repro import canonical_json, sha256_bytes
from .time import iso_utc, parse_utc


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
        from decimal import Decimal

        if not self.fill_id or not self.order_id or len(self.candidate_decision_hash) != 64:
            raise ValueError("fill identity is invalid")
        if Decimal(self.odds) <= 1 or Decimal(self.stake) <= 0:
            raise ValueError("fill odds/stake are invalid")
        parse_utc(self.filled_at)

    def fragment(self) -> MatchedFragment:
        return MatchedFragment(self.side, self.odds, self.stake)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"side": self.side.value, "filled_at": iso_utc(self.filled_at)}


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    event_type: str
    occurred_at: str
    fill_id: str | None = None
    settlement_kind: SettlementKind | None = None
    dead_heat_fraction: str = "1"
    commission_rate: str = "0"
    pnl: str = "0"
    correction_of: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type:
            raise ValueError("ledger event identity is required")
        parse_utc(self.occurred_at)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["occurred_at"] = iso_utc(self.occurred_at)
        if self.settlement_kind is not None:
            value["settlement_kind"] = self.settlement_kind.value
        return value


class SettlementLedger:
    """P/L is available only from recorded fill and settlement events."""

    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)
        self._fills: dict[str, FillRecord] = {}
        self._settled_events: dict[str, LedgerEvent] = {}
        for row in self.log.records():
            if row.get("record_type") == "fill":
                fields = {key: row[key] for key in FillRecord.__dataclass_fields__}
                fields["side"] = BetSide(fields["side"])
                self._fills[fields["fill_id"]] = FillRecord(**fields)
            elif row.get("record_type") == "settlement":
                fields = {key: row[key] for key in LedgerEvent.__dataclass_fields__}
                if fields["settlement_kind"] is not None:
                    fields["settlement_kind"] = SettlementKind(fields["settlement_kind"])
                self._settled_events[fields["event_id"]] = LedgerEvent(**fields)

    def record_fill(self, fill: FillRecord) -> str:
        if fill.fill_id in self._fills:
            if self._fills[fill.fill_id] != fill:
                raise ValueError("fill ID cannot be rewritten")
            return sha256_bytes(canonical_json(fill.to_dict()))
        self._fills[fill.fill_id] = fill
        return self.log.append({"record_type": "fill", **fill.to_dict()})

    def record_cancellation(self, *, event_id: str, fill_id: str, occurred_at: str) -> str:
        if fill_id not in self._fills:
            raise ValueError("cannot cancel unknown fill")
        event = LedgerEvent(event_id, "cancellation", occurred_at, fill_id=fill_id)
        return self.log.append({"record_type": "cancellation", **event.to_dict()})

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
        if fill_id not in self._fills:
            raise ValueError("cannot settle unknown fill")
        if event_id in self._settled_events:
            return self._settled_events[event_id]
        fill = self._fills[fill_id]
        if fill.side == BetSide.BACK:
            result = settle_back(fill.stake, fill.odds, kind=kind, commission_rate=commission_rate, dead_heat_fraction=dead_heat_fraction)
        else:
            result = settle_lay(fill.stake, fill.odds, kind=kind, commission_rate=commission_rate)
        pnl = result.pnl
        if correction_of is not None:
            prior = self._settled_events.get(correction_of)
            if prior is None:
                raise ValueError("correction must reference an existing settlement")
            from decimal import Decimal

            pnl = Decimal(result.pnl) - Decimal(prior.pnl)
        event = LedgerEvent(
            event_id,
            "settlement",
            occurred_at,
            fill_id=fill_id,
            settlement_kind=kind,
            dead_heat_fraction=dead_heat_fraction,
            commission_rate=commission_rate,
            pnl=format(pnl, "f"),
            correction_of=correction_of,
        )
        self.log.append({"record_type": "settlement", **event.to_dict()})
        self._settled_events[event_id] = event
        return event

    def reconcile(self, *, venue_order_ids: set[str], known_order_ids: set[str]) -> bool:
        """Return false when the local fill ledger cannot explain a venue fill."""

        local_order_ids = {fill.order_id for fill in self._fills.values()}
        return venue_order_ids == (local_order_ids & known_order_ids)

    def total_pnl(self) -> str:
        from decimal import Decimal

        total = sum((Decimal(event.pnl) for event in self._settled_events.values()), Decimal("0"))
        return format(total, "f")

    def verify(self) -> int:
        return self.log.verify()
