"""Append-only candidate-run retention and non-quota search telemetry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .policy import PolicySet
from .registry import AppendOnlyJsonl
from .repro import canonical_json, sha256_bytes
from .time import iso_utc, parse_utc


@dataclass(frozen=True)
class CandidateRunRecord:
    run_id: str
    candidate_id: str
    recorded_at: str
    stage: str
    status: str
    decision_hash: str | None = None
    rank: int | None = None
    reason_codes: tuple[str, ...] = ()
    near_miss: bool = False
    dependency_group: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id or not self.candidate_id or not self.stage or not self.status:
            raise ValueError("candidate run identity is required")
        parse_utc(self.recorded_at)
        if self.rank is not None and self.rank < 1:
            raise ValueError("candidate rank must be positive")
        if self.decision_hash is not None and len(self.decision_hash) != 64:
            raise ValueError("decision_hash must be a SHA-256 digest")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["recorded_at"] = iso_utc(self.recorded_at)
        return value


class CandidateRunStore:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    def append(self, record: CandidateRunRecord) -> str:
        return self.log.append({"record_type": "candidate_run", **record.to_dict()})

    def verify(self) -> int:
        return self.log.verify()


@dataclass(frozen=True)
class SearchCoverageSummary:
    run_id: str
    run_date: str
    markets_screened: int
    candidate_universe_size: int
    candidates_modelled: int
    candidates_researched: int
    candidates_qualified: int
    bets_placed: int
    passes_by_reason: tuple[tuple[str, int], ...]
    near_miss_candidates: int
    search_coverage_by_sport: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        date.fromisoformat(self.run_date)
        for value in (
            self.markets_screened,
            self.candidate_universe_size,
            self.candidates_modelled,
            self.candidates_researched,
            self.candidates_qualified,
            self.bets_placed,
            self.near_miss_candidates,
        ):
            if value < 0:
                raise ValueError("coverage counts cannot be negative")

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json(asdict(self)))

    def daily_aim(self, policy: PolicySet | None = None):
        return (policy or PolicySet()).daily_aim(date.fromisoformat(self.run_date))

    def is_below_aim(self, policy: PolicySet | None = None) -> bool:
        return self.bets_placed < self.daily_aim(policy).minimum

    def is_above_nominal_range(self, policy: PolicySet | None = None) -> bool:
        return self.bets_placed > self.daily_aim(policy).maximum

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"summary_hash": self.digest, "targets_are_quota_or_cap": False}

