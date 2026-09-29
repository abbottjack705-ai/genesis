"""Quota gate over the frozen QuotaLedger + VerifiedCacheStore (design sections 12.2 and 14.1).

Every attempt reserves Genesis budget (``BudgetClass.NORMAL``, never reserve) BEFORE anything
is sent, through the frozen ledger's public ``request`` API. ODDS responses are never cached;
only metadata roles use the verified cache. The gate never constructs reserve authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from genesis.quota import (
    BudgetClass, CacheReference, CacheUnavailable, QuotaLedger, VerifiedCacheStore, load_quota_policy,
)
from genesis.registry import AppendOnlyJsonl
from genesis.time import iso_utc, parse_utc

from genesis_adapters.oddspapi.endpoints import PROVIDER_ID, CanonicalRequest

ACTIVE_POLICY_PATH = Path(__file__).resolve().parents[4] / "config" / "oddspapi_quota_policy_v2.json"
UNCACHED_ROLE = "ODDS"
_LEDGER_ROW_TYPES = ("quota_billable_call", "quota_request_blocked", "quota_verified_cache_hit")
_MISS_REASONS = {
    "cache entry is missing": "CACHE_ENTRY_MISSING",
    "cache entry reference is invalid": "CACHE_ENTRY_MISSING",
    "cache artifact is missing": "CACHE_OBJECT_INVALID",
    "cache artifact content does not match authority": "CACHE_OBJECT_INVALID",
    "cache entry is not usable for this exact request": "CACHE_EXPIRED_OR_INVALIDATED",
}


class CachePolicyError(ValueError):
    """An attempt to cache (or look up) an ODDS response."""


@dataclass(frozen=True)
class QuotaCharge:
    """What the frozen ledger decided. ``billable_units`` is the GENESIS internal debit, not
    evidence of provider billing (design 14.2)."""

    quota_request_id: str
    reason: str
    allowed: bool
    billable_units: int
    daily_used: int
    monthly_used: int
    normal_monthly_used: int
    reserve_monthly_used: int
    cache_entry_id: str | None
    cache_miss_reason: str | None = None


def open_operational_ledger(root: Path, *, policy_path: Path | None = None) -> tuple[QuotaLedger, VerifiedCacheStore]:
    """The frozen active policy, loaded unchanged, with the cache store attached.

    The ledger's convenience constructor for the active config is deliberately NOT used: it attaches no
    cache store, and a ledger holding cache-hit history then fails replay.
    """

    base = Path(root)
    cache = VerifiedCacheStore(base / "quota" / "cache")
    policy = load_quota_policy(policy_path or ACTIVE_POLICY_PATH)
    return QuotaLedger(base / "quota" / "ledger.jsonl", policy=policy, cache_store=cache), cache


class QuotaGate:
    def __init__(self, ledger: QuotaLedger, cache: VerifiedCacheStore, *, cache_index_path: Path):
        self.ledger = ledger
        self.cache = cache
        self._index = AppendOnlyJsonl(cache_index_path)

    # -- lookup ------------------------------------------------------------------------
    def _latest_entry(self, request_hash: str) -> str | None:
        entry = None
        for row in self._index.records():
            if row.get("record_type") == "cache_index_entry" and row.get("request_hash") == request_hash:
                entry = row["cache_entry_id"]
        return entry

    def _miss_reason(self, entry_id: str, occurred_at: str, request_hash: str) -> str:
        try:
            self.cache.resolve(entry_id, at=occurred_at, provider_id=PROVIDER_ID,
                               policy_digest=self.ledger.policy.policy_digest,
                               provider_request_hash=request_hash)
        except CacheUnavailable as exc:
            return _MISS_REASONS.get(str(exc), "CACHE_UNUSABLE")
        return "CACHE_NOT_APPLIED"

    # -- reservation -------------------------------------------------------------------
    def reserve(self, *, request: CanonicalRequest, request_id: str, occurred_at: str,
                billable_units: int) -> QuotaCharge:
        """Debit ``billable_units`` of Genesis budget (NORMAL only) or record a verified cache hit."""

        request_hash = request.provider_request_hash
        reference = None
        entry_id = None
        if request.role != UNCACHED_ROLE:
            entry_id = self._latest_entry(request_hash)
            if entry_id is not None:
                reference = CacheReference(entry_id)
        decision = self.ledger.request(
            request_id=request_id, occurred_at=occurred_at, billable_units=billable_units,
            budget_class=BudgetClass.NORMAL, authorization_id=None, cache=reference,
            provider_id=PROVIDER_ID, provider_request_hash=request_hash)
        hit = decision.reason == "verified_cache_hit"
        miss = None
        if reference is not None and not hit:
            miss = self._miss_reason(entry_id, occurred_at, request_hash)
        return QuotaCharge(
            quota_request_id=decision.request_id, reason=decision.reason, allowed=decision.allowed,
            billable_units=decision.billable_units, daily_used=decision.daily_used,
            monthly_used=decision.monthly_used, normal_monthly_used=decision.normal_monthly_used,
            reserve_monthly_used=decision.reserve_monthly_used,
            cache_entry_id=entry_id if hit else None, cache_miss_reason=miss)

    def cached_bytes(self, charge: QuotaCharge, request: CanonicalRequest) -> bytes | None:
        """The ORIGINAL capture's bytes for a verified cache hit, else None."""

        if charge.reason != "verified_cache_hit" or charge.cache_entry_id is None:
            return None
        entry = self.cache.get(charge.cache_entry_id)              # re-verifies hash and length
        return self.cache.object_path(entry.artifact_hash).read_bytes()

    def publish_cache(self, request: CanonicalRequest, payload: bytes, *, captured_at: str,
                      ttl_seconds: int) -> CacheReference:
        """Publish metadata bytes to the verified cache (never ODDS)."""

        if request.role == UNCACHED_ROLE:
            raise CachePolicyError("ODDS responses are never cached")
        request_hash = request.provider_request_hash
        captured = iso_utc(captured_at)
        expires = iso_utc(parse_utc(captured) + timedelta(seconds=ttl_seconds))
        reference = self.cache.publish(
            payload, cache_key=f"oddspapi:{request.api_version}:{request.role}:{request_hash}",
            provider_request_hash=request_hash, provider_id=PROVIDER_ID,
            quota_policy_digest=self.ledger.policy.policy_digest, captured_at=captured,
            expires_at=expires)
        self._index.append({"record_type": "cache_index_entry", "request_hash": request_hash,
                            "cache_entry_id": reference.cache_entry_id, "captured_at": captured,
                            "expires_at": expires})
        return reference

    # -- read-only views -----------------------------------------------------------------
    def find_request(self, request_id: str) -> dict | None:
        """The frozen ledger row for ``request_id`` (public ``log.records()`` only), else None."""

        for row in self.ledger.log.records():
            if row.get("record_type") in _LEDGER_ROW_TYPES and row.get("request_id") == request_id:
                return row
        return None

    def head_time(self) -> str | None:
        """Latest ``occurred_at`` the frozen ledger holds (the durable head this writer extends)."""

        latest = None
        for row in self.ledger.log.records():
            value = row.get("occurred_at")
            if value is not None and (latest is None or parse_utc(value) > parse_utc(latest)):
                latest = value
        return latest

    def headroom(self, at: str, units: int) -> bool:
        """Would ``units`` of NORMAL budget still fit today and this month?"""

        daily, monthly = self.ledger.usage(at)
        policy = self.ledger.policy
        return daily + units <= policy.daily_billable_budget and monthly + units <= policy.normal_monthly_budget
