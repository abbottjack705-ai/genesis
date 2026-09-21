"""Provider-neutral scheduler, cost, and run-manifest interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from .repro import canonical_json, sha256_bytes


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    job_type: str
    scheduled_at: str
    input_manifest_hash: str
    mode: str

    def __post_init__(self) -> None:
        if not self.job_id or not self.job_type or len(self.input_manifest_hash) != 64:
            raise ValueError("job identity is invalid")


class SchedulerPort(Protocol):
    def submit(self, job: JobSpec) -> str:
        """Submit a deterministic job without selecting a cloud provider."""


@dataclass(frozen=True)
class CostBudget:
    version: str = "genesis-cost-target-v0.4"
    monthly_limit_gbp: Decimal = Decimal("10.00")
    mandatory_one_off_limit_gbp: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        if self.monthly_limit_gbp < 0 or self.mandatory_one_off_limit_gbp < 0:
            raise ValueError("cost limits cannot be negative")


@dataclass(frozen=True)
class CostLedgerEntry:
    entry_id: str
    occurred_at: str
    category: str
    amount_gbp: Decimal
    recurring: bool


class CostLedger:
    def __init__(self, budget: CostBudget | None = None):
        self.budget = budget or CostBudget()
        self._entries: list[CostLedgerEntry] = []

    def record(self, entry: CostLedgerEntry) -> None:
        if entry.amount_gbp < 0:
            raise ValueError("cost cannot be negative")
        self._entries.append(entry)

    def total_recurring(self) -> Decimal:
        return sum((entry.amount_gbp for entry in self._entries if entry.recurring), Decimal("0"))

    def can_deploy(self) -> bool:
        return self.total_recurring() <= self.budget.monthly_limit_gbp and all(
            (entry.recurring or entry.amount_gbp <= self.budget.mandatory_one_off_limit_gbp)
            for entry in self._entries
        )


@dataclass(frozen=True)
class RuntimeManifest:
    job_id: str
    config_hash: str
    dependency_lock_hash: str
    input_manifest_hash: str
    mode: str
    command: str

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json(self.__dict__))

