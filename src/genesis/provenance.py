"""Source provenance and availability contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, sha256_bytes
from .time import AvailabilityWindow, iso_utc, parse_utc


class AvailabilityClass(StrEnum):
    HISTORICAL_RECONSTRUCTED = "historical_reconstructed"
    PROSPECTIVE_CAPTURED = "prospective_captured"
    LIVE_RECEIVED = "live_received"
    DERIVED = "derived"
    ASSUMED = "assumed"
    FUTURE_LABEL = "future_label"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceContract:
    contract_id: str
    provider: str
    source_type: str
    uri_pattern: str
    availability_class: AvailabilityClass
    timestamp_precision: str
    availability_rule: str
    parser_version: str
    licensing_note: str
    supports_historical_reconstruction: bool = False
    supports_prospective_capture: bool = False

    def __post_init__(self) -> None:
        if not self.contract_id or not self.provider or not self.parser_version:
            raise ValueError("source contract identity fields are required")
        if self.availability_class == AvailabilityClass.FUTURE_LABEL:
            if self.supports_historical_reconstruction or self.supports_prospective_capture:
                raise ValueError("future labels cannot be decision-time source inputs")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"availability_class": self.availability_class.value}

    def check_window(self, window: AvailabilityWindow, decision_at: str) -> None:
        """Validate a concrete source observation against this contract."""

        if self.availability_class in {
            AvailabilityClass.FUTURE_LABEL,
            AvailabilityClass.UNKNOWN,
        }:
            raise ValueError(f"source contract is not decision-usable: {self.contract_id}")
        if not window.is_ready_by(parse_utc(decision_at)):
            raise ValueError(f"source not ready by decision time: {self.contract_id}")


class SourceContractRegistry:
    """Append-only named authority for immutable source contracts."""

    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    @staticmethod
    def _from_row(row: dict[str, Any]) -> SourceContract:
        fields = {key: row[key] for key in SourceContract.__dataclass_fields__}
        fields["availability_class"] = AvailabilityClass(fields["availability_class"])
        return SourceContract(**fields)

    def get(self, contract_id: str) -> SourceContract:
        matches = [
            self._from_row(row)
            for row in self.log.records()
            if row.get("record_type") == "source_contract_registered"
            and row.get("contract_id") == contract_id
        ]
        if not matches:
            raise RegistryConflict(f"unknown source contract: {contract_id}")
        if any(item != matches[0] for item in matches[1:]):
            raise RegistryConflict(f"conflicting source contract history: {contract_id}")
        return matches[0]

    def register(self, contract: SourceContract) -> str:
        record = {"record_type": "source_contract_registered", **contract.to_dict()}

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            matches = [
                self._from_row(row)
                for row in rows
                if row.get("record_type") == "source_contract_registered"
                and row.get("contract_id") == contract.contract_id
            ]
            if not matches:
                return record
            if all(item == contract for item in matches):
                return None
            raise RegistryConflict(f"source contract already exists: {contract.contract_id}")

        result = self.log.transaction(build)
        return result or sha256_bytes(canonical_json(record))


@dataclass(frozen=True)
class ProvenanceRef:
    artifact_hash: str
    contract_id: str
    source_uri: str
    retrieved_at: str
    parse_ready_at: str
    availability_class: AvailabilityClass
    parser_version: str
    evidence_span: str | None = None
    observation_id: str | None = None

    def __post_init__(self) -> None:
        if len(self.artifact_hash) != 64:
            raise ValueError("artifact_hash must be a full SHA-256 digest")
        parse_utc(self.retrieved_at)
        parse_utc(self.parse_ready_at)
        if self.observation_id is not None and len(self.observation_id) != 64:
            raise ValueError("observation_id must be a full SHA-256 digest")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"availability_class": self.availability_class.value}

    @property
    def is_authoritative_v2(self) -> bool:
        return self.observation_id is not None
