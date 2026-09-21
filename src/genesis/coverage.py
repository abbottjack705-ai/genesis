"""Coverage, exclusion, and fail-closed reason ledgers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .registry import AppendOnlyJsonl
from .reasons import ReasonCode
from .time import parse_utc


class CoverageStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"
    NOT_ATTEMPTED = "not_attempted"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class CoverageEntry:
    entry_id: str
    entity_id: str
    source_contract_id: str
    status: CoverageStatus
    recorded_at: str
    reason_codes: tuple[ReasonCode, ...]
    artifact_hash: str | None = None
    supersedes_entry_id: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        parse_utc(self.recorded_at)
        if self.status == CoverageStatus.AVAILABLE and not self.artifact_hash:
            raise ValueError("available coverage requires an artifact hash")
        if self.status != CoverageStatus.AVAILABLE and not self.reason_codes:
            raise ValueError("non-available coverage requires a reason code")


class CoverageLedger:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    def append(self, entry: CoverageEntry) -> str:
        return self.log.append(
            {
                "record_type": "coverage",
                **asdict(entry),
                "status": entry.status.value,
                "reason_codes": [code.value for code in entry.reason_codes],
            }
        )

    def verify(self) -> int:
        return self.log.verify()


class ExclusionLedger(CoverageLedger):
    """Named view for explicit exclusions; exclusions are never dropped."""

    def append_exclusion(
        self,
        *,
        entry_id: str,
        entity_id: str,
        source_contract_id: str,
        recorded_at: str,
        reason_codes: tuple[ReasonCode, ...],
        note: str | None = None,
    ) -> str:
        return self.append(
            CoverageEntry(
                entry_id=entry_id,
                entity_id=entity_id,
                source_contract_id=source_contract_id,
                status=CoverageStatus.REJECTED,
                recorded_at=recorded_at,
                reason_codes=reason_codes,
                note=note,
            )
        )
