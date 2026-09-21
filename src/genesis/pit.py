"""Controlled point-in-time source capability and bitemporal access."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, sha256_bytes
from .time import iso_utc, parse_utc


class OperationalStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceCapability:
    source_id: str
    provider: str
    access_method: str
    cost_tier: str
    entitlement_class: str
    historical_availability_class: str
    point_in_time_reliability: str
    revision_behaviour: str
    coverage: str
    rate_quota_limits: str
    schema_version: str
    operational_status: OperationalStatus
    recorded_at: str
    version: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.provider or not self.schema_version or not self.version:
            raise ValueError("source capability identity is required")
        parse_utc(self.recorded_at)

    def is_ready(self) -> bool:
        return self.operational_status == OperationalStatus.READY and self.point_in_time_reliability not in {"unknown", "unverified"}

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["operational_status"] = self.operational_status.value
        value["recorded_at"] = iso_utc(self.recorded_at)
        return value


class SourceUnavailable(RuntimeError):
    pass


class SourceCapabilityRegistry:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    @staticmethod
    def _from_row(row: dict[str, Any]) -> SourceCapability:
        fields = {key: row[key] for key in SourceCapability.__dataclass_fields__}
        fields["operational_status"] = OperationalStatus(fields["operational_status"])
        return SourceCapability(**fields)

    def history(self, source_id: str) -> tuple[SourceCapability, ...]:
        items = [
            self._from_row(row)
            for row in self.log.records()
            if row.get("record_type") == "source_capability_registered"
            and row.get("source_id") == source_id
        ]
        return tuple(sorted(items, key=lambda item: (parse_utc(item.recorded_at), item.version)))

    def register(self, capability: SourceCapability) -> str:
        record = {"record_type": "source_capability_registered", **capability.to_dict()}

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            history = [
                self._from_row(row)
                for row in rows
                if row.get("record_type") == "source_capability_registered"
                and row.get("source_id") == capability.source_id
            ]
            same_version = [item for item in history if item.version == capability.version]
            if same_version:
                if all(item == capability for item in same_version):
                    return None
                raise RegistryConflict(
                    f"source capability version already exists: {capability.source_id}/{capability.version}"
                )
            if history and parse_utc(capability.recorded_at) <= max(
                parse_utc(item.recorded_at) for item in history
            ):
                raise RegistryConflict("source capability recorded_at must advance monotonically")
            return record

        result = self.log.transaction(build)
        return result or sha256_bytes(canonical_json(record))

    def require_ready(self, source_id: str) -> SourceCapability:
        history = self.history(source_id)
        if not history:
            raise SourceUnavailable(f"unknown source capability: {source_id}")
        capability = history[-1]
        if not capability.is_ready():
            raise SourceUnavailable(f"source capability is not ready: {source_id}")
        return capability

    def require_ready_at(self, source_id: str, decision_at: str) -> SourceCapability:
        point = parse_utc(decision_at)
        eligible = [item for item in self.history(source_id) if parse_utc(item.recorded_at) <= point]
        if not eligible:
            raise SourceUnavailable(
                f"source capability has no record at decision time: {source_id}"
            )
        capability = eligible[-1]
        if not capability.is_ready():
            raise SourceUnavailable(
                f"source capability is not ready at decision time: {source_id}"
            )
        return capability


@dataclass(frozen=True)
class BitemporalRecord:
    record_id: str
    entity_id: str
    source_id: str
    payload_hash: str
    available_at: str
    published_at: str | None
    retrieved_at: str
    ready_at: str
    valid_from: str
    valid_to: str | None = None
    superseded_by: str | None = None
    superseded_at: str | None = None

    def __post_init__(self) -> None:
        if not self.record_id or not self.entity_id or not self.source_id:
            raise ValueError("PIT record identity is required")
        if len(self.payload_hash) != 64:
            raise ValueError("payload_hash must be a SHA-256 digest")
        values = (self.available_at, self.retrieved_at, self.ready_at, self.valid_from, self.valid_to, self.published_at, self.superseded_at)
        for value in values:
            if value is not None:
                parse_utc(value)
        if parse_utc(self.ready_at) < parse_utc(self.available_at):
            raise ValueError("ready_at cannot precede available_at")
        if self.valid_to is not None and parse_utc(self.valid_to) <= parse_utc(self.valid_from):
            raise ValueError("valid_to must follow valid_from")
        if self.superseded_by and self.superseded_at is None:
            raise ValueError("superseded records require superseded_at")

    def admissible_at(self, decision_at: str) -> bool:
        point = parse_utc(decision_at)
        if (
            parse_utc(self.available_at) > point
            or parse_utc(self.retrieved_at) > point
            or parse_utc(self.ready_at) > point
        ):
            return False
        if parse_utc(self.valid_from) > point:
            return False
        if self.valid_to is not None and point >= parse_utc(self.valid_to):
            return False
        if self.superseded_at is not None and point >= parse_utc(self.superseded_at):
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PITViolation(RuntimeError):
    pass


class PITStore:
    """Small controlled PIT store used by adapters and deterministic tests."""

    def __init__(
        self,
        path: str | Path | None,
        *,
        capabilities: SourceCapabilityRegistry,
    ):
        if not isinstance(capabilities, SourceCapabilityRegistry):
            raise TypeError("PITStore requires a SourceCapabilityRegistry authority")
        self.capabilities = capabilities
        self.log = AppendOnlyJsonl(path) if path is not None else None
        self._records: dict[str, BitemporalRecord] = {}
        if self.log is not None:
            for row in self.log.records():
                if row.get("record_type") == "pit_record":
                    record = BitemporalRecord(**{key: row[key] for key in BitemporalRecord.__dataclass_fields__})
                    self._records[record.record_id] = record

    def append(self, record: BitemporalRecord) -> str:
        if record.record_id in self._records:
            if self._records[record.record_id] != record:
                raise RegistryConflict(f"PIT record already exists: {record.record_id}")
            return sha256_bytes(canonical_json(record.to_dict()))
        self._records[record.record_id] = record
        if self.log is not None:
            return self.log.append({"record_type": "pit_record", **record.to_dict()})
        return sha256_bytes(canonical_json(record.to_dict()))

    def as_of_query(
        self,
        entity_id: str,
        decision_at: str,
        *,
        source_id: str | None = None,
    ) -> tuple[BitemporalRecord, ...]:
        parse_utc(decision_at)
        if source_id is not None:
            self.capabilities.require_ready_at(source_id, decision_at)
        records = [record for record in self._records.values() if record.entity_id == entity_id and (source_id is None or record.source_id == source_id)]
        admissible = [record for record in records if record.admissible_at(decision_at)]
        for record in admissible:
            self.capabilities.require_ready_at(record.source_id, decision_at)
        admissible.sort(key=lambda record: (record.valid_from, record.ready_at, record.record_id), reverse=True)
        if len(admissible) > 1 and admissible[0].valid_from == admissible[1].valid_from:
            raise PITViolation(f"ambiguous PIT records for {entity_id} at {decision_at}")
        return tuple(sorted(admissible, key=lambda record: record.record_id))

    def feature_view(
        self,
        feature_set_id: str,
        entity_ids: Iterable[str],
        decision_at: str,
    ) -> tuple[BitemporalRecord, ...]:
        if not feature_set_id:
            raise PITViolation("feature_set_id is required")
        result: list[BitemporalRecord] = []
        for entity_id in entity_ids:
            result.extend(self.as_of_query(entity_id, decision_at))
        return tuple(sorted(result, key=lambda record: record.record_id))
