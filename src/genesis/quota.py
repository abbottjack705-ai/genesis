"""Offline quota ledger and cache-aware current-data budget contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .registry import AppendOnlyJsonl
from .time import parse_utc


@dataclass(frozen=True)
class QuotaPolicy:
    version: str = "genesis-oddspapi-budget-v0.4-draft"
    daily_billable_limit: int = 7
    monthly_billable_limit: int = 220
    monthly_reserve: int = 30
    one_legitimate_allowance: bool = True

    def __post_init__(self) -> None:
        if self.daily_billable_limit <= 0 or self.monthly_billable_limit <= 0 or self.monthly_reserve < 0:
            raise ValueError("quota values must be positive")
        if self.monthly_reserve >= self.monthly_billable_limit:
            raise ValueError("quota reserve must be below monthly limit")
        if not self.one_legitimate_allowance:
            raise ValueError("quota policy cannot permit allowance circumvention")


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    reason: str
    daily_used: int
    monthly_used: int


class QuotaLedger:
    def __init__(self, path: str | Path | None = None, policy: QuotaPolicy | None = None):
        self.policy = policy or QuotaPolicy()
        self.log = AppendOnlyJsonl(path) if path is not None else None
        self._lock = Lock()
        self._calls: list[tuple[str, int, str]] = []
        if self.log is not None:
            for row in self.log.records():
                if row.get("record_type") == "billable_call":
                    self._calls.append((row["occurred_at"], int(row["units"]), row["request_id"]))

    def _counts(self, occurred_at: str) -> tuple[int, int]:
        point = parse_utc(occurred_at)
        month = (point.year, point.month)
        daily = 0
        monthly = 0
        for timestamp, units, _ in self._calls:
            called = parse_utc(timestamp)
            if called.date() == point.date():
                daily += units
            if (called.year, called.month) == month:
                monthly += units
        return daily, monthly

    def request(self, *, request_id: str, occurred_at: str, billable_units: int = 1, cached: bool = False) -> QuotaDecision:
        if billable_units <= 0:
            raise ValueError("billable units must be positive")
        parse_utc(occurred_at)
        with self._lock:
            daily, monthly = self._counts(occurred_at)
            if cached:
                return QuotaDecision(True, "verified_cache_hit", daily, monthly)
            if daily + billable_units > self.policy.daily_billable_limit:
                return QuotaDecision(False, "daily_quota_exhausted", daily, monthly)
            if monthly + billable_units > self.policy.monthly_billable_limit - self.policy.monthly_reserve:
                return QuotaDecision(False, "monthly_quota_reserve_protected", daily, monthly)
            self._calls.append((occurred_at, billable_units, request_id))
            if self.log is not None:
                self.log.append({"record_type": "billable_call", "request_id": request_id, "occurred_at": occurred_at, "units": billable_units})
            return QuotaDecision(True, "billable_call_reserved", daily + billable_units, monthly + billable_units)

    def usage(self, occurred_at: str) -> tuple[int, int]:
        with self._lock:
            return self._counts(occurred_at)


@dataclass(frozen=True)
class CachedData:
    cache_key: str
    evidence_hash: str
    captured_at: str
    expires_at: str
    verified: bool

    def usable_at(self, at: str) -> bool:
        point = parse_utc(at)
        return self.verified and parse_utc(self.captured_at) <= point < parse_utc(self.expires_at)


def allow_cached_or_block(cache: CachedData | None, at: str) -> bool:
    return cache is not None and cache.usable_at(at)

