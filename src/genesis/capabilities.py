"""Fail-closed market capability registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, sha256_bytes
from .time import iso_utc, parse_utc


@dataclass(frozen=True)
class MarketCapability:
    capability_id: str
    sport: str
    market_family: str
    market_supported_by_data_adapter: bool | None
    market_supported_by_model: bool | None
    market_supported_by_execution_venue: bool | None
    market_settlement_rules_known: bool | None
    market_liquidity_policy_known: bool | None
    market_approved_by_strategy: bool | None
    market_live_allowed: bool | None
    version: str
    recorded_at: str
    evidence_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_id or not self.sport or not self.market_family or not self.version:
            raise ValueError("capability identity is required")
        parse_utc(self.recorded_at)
        for digest in self.evidence_hashes:
            if len(digest) != 64:
                raise ValueError("capability evidence hashes must be SHA-256 digests")

    def is_ready(self, *, live: bool = False) -> bool:
        required = (
            self.market_supported_by_data_adapter,
            self.market_supported_by_model,
            self.market_supported_by_execution_venue,
            self.market_settlement_rules_known,
            self.market_liquidity_policy_known,
            self.market_approved_by_strategy,
        )
        if any(value is not True for value in required):
            return False
        if live and self.market_live_allowed is not True:
            return False
        return True

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["recorded_at"] = iso_utc(self.recorded_at)
        return value


class CapabilityUnavailable(RuntimeError):
    pass


class MarketCapabilityRegistry:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    @staticmethod
    def _from_row(row: dict[str, Any]) -> MarketCapability:
        fields = {key: row[key] for key in MarketCapability.__dataclass_fields__}
        fields["evidence_hashes"] = tuple(fields["evidence_hashes"])
        return MarketCapability(**fields)

    def register(self, capability: MarketCapability) -> str:
        record = {"record_type": "market_capability_registered", **capability.to_dict()}

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            matches = [
                self._from_row(row)
                for row in rows
                if row.get("record_type") == "market_capability_registered"
                and row.get("capability_id") == capability.capability_id
            ]
            if not matches:
                return record
            if all(item == capability for item in matches):
                return None
            raise RegistryConflict(
                f"market capability already exists: {capability.capability_id}"
            )

        result = self.log.transaction(build)
        return result or capability.digest

    def get(self, capability_id: str) -> MarketCapability:
        matches = [
            self._from_row(row)
            for row in self.log.records()
            if row.get("record_type") == "market_capability_registered"
            and row.get("capability_id") == capability_id
        ]
        if not matches:
            raise CapabilityUnavailable(f"unknown market capability: {capability_id}")
        if any(item != matches[0] for item in matches[1:]):
            raise CapabilityUnavailable(f"conflicting market capability: {capability_id}")
        return matches[0]

    def require_ready(self, capability_id: str, *, live: bool = False) -> MarketCapability:
        capability = self.get(capability_id)
        if not capability.is_ready(live=live):
            raise CapabilityUnavailable(f"market capability is not ready: {capability_id}")
        return capability

    def require_ready_at(
        self, capability_id: str, decision_at: str, *, live: bool = False
    ) -> MarketCapability:
        capability = self.get(capability_id)
        if parse_utc(capability.recorded_at) > parse_utc(decision_at):
            raise CapabilityUnavailable(
                f"market capability was not recorded at decision time: {capability_id}"
            )
        if not capability.is_ready(live=live):
            raise CapabilityUnavailable(f"market capability is not ready: {capability_id}")
        return capability
