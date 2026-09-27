"""Durable, cache-aware quota authority with explicit reserve semantics."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, immutable_write, sha256_bytes
from .time import iso_utc, parse_utc


QUOTA_POLICY_SCHEMA = "quota-policy-v2"
QUOTA_EVENT_SCHEMA = "quota-event-v2"
CACHE_HIT_EVENT_SCHEMA = "quota-cache-hit-event-v3"
RESERVE_AUTHORIZATION_SCHEMA = "quota-reserve-authorization-v1"
CACHE_ENTRY_SCHEMA = "verified-cache-entry-v1"


class CacheUnavailable(ValueError):
    """The named cache proof cannot authorize a cache hit."""


class QuotaInterpretation(StrEnum):
    A = "A"
    B = "B"


class BudgetClass(StrEnum):
    NORMAL = "normal"
    RESERVE = "reserve"


@dataclass(frozen=True)
class QuotaPolicy:
    schema_version: str
    version: str
    provider_id: str
    policy_interpretation: QuotaInterpretation
    provider_monthly_allowance: int
    normal_monthly_budget: int
    reserve_units: int
    daily_billable_budget: int
    one_legitimate_allowance: bool
    approved_active: bool
    test_only: bool
    approval_reference: str
    approved_at: str
    approval_revoked: bool
    provider_terms_reverification_required: bool
    policy_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != QUOTA_POLICY_SCHEMA:
            raise ValueError("unsupported quota policy schema")
        if not self.version or not self.provider_id:
            raise ValueError("quota policy identity is required")
        object.__setattr__(self, "policy_interpretation", QuotaInterpretation(self.policy_interpretation))
        if self.provider_monthly_allowance <= 0 or self.normal_monthly_budget <= 0:
            raise ValueError("quota allowance and normal budget must be positive")
        if self.reserve_units < 0 or self.daily_billable_budget <= 0:
            raise ValueError("quota reserve/daily budget is invalid")
        if self.normal_monthly_budget + self.reserve_units > self.provider_monthly_allowance:
            raise ValueError("Genesis operational quota exceeds provider allowance")
        if not self.one_legitimate_allowance:
            raise ValueError("quota policy cannot permit allowance circumvention")
        if self.approved_active and self.test_only:
            raise ValueError("test-only quota policy cannot be active")
        if not self.approval_reference:
            raise ValueError("quota policy approval reference is required")
        parse_utc(self.approved_at)
        object.__setattr__(self, "approved_at", iso_utc(self.approved_at))
        if len(self.policy_digest) != 64:
            raise ValueError("quota policy digest must be SHA-256")
        int(self.policy_digest, 16)
        if self.compute_digest() != self.policy_digest:
            raise ValueError("quota policy digest mismatch")

    @property
    def genesis_monthly_limit(self) -> int:
        return self.normal_monthly_budget + self.reserve_units

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("policy_digest")
        value["policy_interpretation"] = self.policy_interpretation.value
        value["approved_at"] = iso_utc(self.approved_at)
        return value

    def compute_digest(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        return self.unsigned_dict() | {"policy_digest": self.policy_digest}

    @classmethod
    def create(cls, **fields: Any) -> "QuotaPolicy":
        normalized = dict(fields)
        normalized.setdefault("schema_version", QUOTA_POLICY_SCHEMA)
        normalized["policy_interpretation"] = QuotaInterpretation(
            normalized["policy_interpretation"]
        )
        normalized["approved_at"] = iso_utc(normalized["approved_at"])
        unsigned = dict(normalized)
        unsigned["policy_interpretation"] = normalized["policy_interpretation"].value
        return cls(policy_digest=sha256_bytes(canonical_json(unsigned)), **normalized)

    @classmethod
    def test_fixture(
        cls,
        interpretation: QuotaInterpretation,
        *,
        provider_monthly_allowance: int,
        normal_monthly_budget: int,
        reserve_units: int,
        daily_billable_budget: int,
        provider_id: str = "oddspapi",
        version: str | None = None,
    ) -> "QuotaPolicy":
        interpretation = QuotaInterpretation(interpretation)
        return cls.create(
            version=version or f"quota-test-{interpretation.value.lower()}",
            provider_id=provider_id,
            policy_interpretation=interpretation,
            provider_monthly_allowance=provider_monthly_allowance,
            normal_monthly_budget=normal_monthly_budget,
            reserve_units=reserve_units,
            daily_billable_budget=daily_billable_budget,
            one_legitimate_allowance=True,
            approved_active=False,
            test_only=True,
            approval_reference="TEST-ONLY-NOT-ACTIVE",
            approved_at="2026-09-19T00:00:00Z",
            approval_revoked=False,
            provider_terms_reverification_required=True,
        )

    @classmethod
    def from_legacy(
        cls,
        *,
        interpretation: QuotaInterpretation,
        provider_monthly_allowance: int,
        daily_billable_limit: int,
        monthly_billable_limit: int,
        monthly_reserve: int,
    ) -> "QuotaPolicy":
        """Explicit migration only; interpretation and provider ceiling are mandatory."""

        interpretation = QuotaInterpretation(interpretation)
        normal = (
            monthly_billable_limit
            if interpretation == QuotaInterpretation.A
            else monthly_billable_limit - monthly_reserve
        )
        return cls.test_fixture(
            interpretation,
            provider_monthly_allowance=provider_monthly_allowance,
            normal_monthly_budget=normal,
            reserve_units=monthly_reserve,
            daily_billable_budget=daily_billable_limit,
            version=f"legacy-explicit-{interpretation.value.lower()}",
        )

    def require_operational(self, *, allow_test_policy: bool = False) -> None:
        if self.test_only:
            if not allow_test_policy:
                raise RegistryConflict("test-only quota policy cannot be selected operationally")
            return
        if self.policy_interpretation != QuotaInterpretation.A:
            raise RegistryConflict("active quota policy must be approved Interpretation A")
        if not self.approved_active or self.approval_revoked:
            raise RegistryConflict("active quota policy approval is missing or revoked")
        if self.provider_id != "oddspapi":
            raise RegistryConflict("active quota policy is not bound to OddsPapi")
        if (
            self.provider_monthly_allowance,
            self.normal_monthly_budget,
            self.reserve_units,
            self.daily_billable_budget,
        ) != (250, 220, 30, 7):
            raise RegistryConflict("active Interpretation A boundaries do not match D-REM-001")


def load_quota_policy(path: str | Path, *, require_active: bool = True) -> QuotaPolicy:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        fields = {key: data[key] for key in QuotaPolicy.__dataclass_fields__}
        fields["policy_interpretation"] = QuotaInterpretation(fields["policy_interpretation"])
        policy = QuotaPolicy(**fields)
        if require_active:
            policy.require_operational()
        return policy
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RegistryConflict("quota policy record is missing, corrupt, or incomplete") from exc


@dataclass(frozen=True)
class QuotaReserveAuthorization:
    schema_version: str
    provider_id: str
    quota_policy_version: str
    quota_policy_digest: str
    quota_period: str
    max_reserve_units: int
    reason: str
    approval_reference: str
    granted_at: str
    valid_from: str
    valid_through: str
    authorization_id: str

    def __post_init__(self) -> None:
        if self.schema_version != RESERVE_AUTHORIZATION_SCHEMA:
            raise ValueError("unsupported quota reserve authorization schema")
        if not self.provider_id or not self.quota_policy_version:
            raise ValueError("reserve authorization provider/policy identity is required")
        if len(self.quota_policy_digest) != 64:
            raise ValueError("reserve authorization policy digest must be SHA-256")
        int(self.quota_policy_digest, 16)
        if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", self.quota_period) is None:
            raise ValueError("quota period must be YYYY-MM")
        if not 0 < self.max_reserve_units <= 30:
            raise ValueError("reserve authorization grant must be in 1..30")
        if not self.reason or not self.approval_reference:
            raise ValueError("reserve authorization reason/approval are required")
        granted = parse_utc(self.granted_at)
        valid_from = parse_utc(self.valid_from)
        valid_through = parse_utc(self.valid_through)
        if valid_from < granted or valid_through <= valid_from:
            raise ValueError("reserve authorization validity window is invalid")
        object.__setattr__(self, "granted_at", iso_utc(self.granted_at))
        object.__setattr__(self, "valid_from", iso_utc(self.valid_from))
        object.__setattr__(self, "valid_through", iso_utc(self.valid_through))
        if len(self.authorization_id) != 64:
            raise ValueError("reserve authorization ID must be SHA-256")
        int(self.authorization_id, 16)
        if self.compute_id() != self.authorization_id:
            raise ValueError("reserve authorization ID mismatch")

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("authorization_id")
        for field in ("granted_at", "valid_from", "valid_through"):
            value[field] = iso_utc(value[field])
        return value

    def compute_id(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        return self.unsigned_dict() | {"authorization_id": self.authorization_id}

    @classmethod
    def create(cls, **fields: Any) -> "QuotaReserveAuthorization":
        normalized = dict(fields)
        normalized.setdefault("schema_version", RESERVE_AUTHORIZATION_SCHEMA)
        for field in ("granted_at", "valid_from", "valid_through"):
            normalized[field] = iso_utc(normalized[field])
        return cls(
            authorization_id=sha256_bytes(canonical_json(normalized)),
            **normalized,
        )


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    reason: str
    daily_used: int
    monthly_used: int
    normal_monthly_used: int
    reserve_monthly_used: int
    request_id: str
    budget_class: BudgetClass | None = None
    authorization_id: str | None = None
    billable_units: int = 0


@dataclass(frozen=True)
class CachedData:
    """Legacy caller claim retained for input compatibility; never authority."""

    cache_key: str
    evidence_hash: str
    provider_id: str
    quota_policy_digest: str
    captured_at: str
    expires_at: str
    verified: bool

    def __post_init__(self) -> None:
        if not self.cache_key or not self.provider_id or len(self.evidence_hash) != 64:
            raise ValueError("cache identity/evidence hash is invalid")
        int(self.evidence_hash, 16)
        if len(self.quota_policy_digest) != 64:
            raise ValueError("cache quota-policy digest must be SHA-256")
        int(self.quota_policy_digest, 16)
        captured = parse_utc(self.captured_at)
        expires = parse_utc(self.expires_at)
        if expires <= captured:
            raise ValueError("cache expiry must follow capture")
        object.__setattr__(self, "captured_at", iso_utc(self.captured_at))
        object.__setattr__(self, "expires_at", iso_utc(self.expires_at))

    def usable_at(self, at: str, *, provider_id: str, policy_digest: str) -> bool:
        parse_utc(at)
        return False


@dataclass(frozen=True)
class CacheReference:
    cache_entry_id: str

    def __post_init__(self) -> None:
        _cache_digest(self.cache_entry_id, "cache entry ID")


def _cache_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise ValueError(f"{name} must be lowercase SHA-256")
    int(value, 16)
    return value


@dataclass(frozen=True)
class VerifiedCacheEntry:
    cache_entry_id: str
    schema_version: str
    cache_key: str
    provider_request_hash: str
    artifact_hash: str
    byte_length: int
    provider_id: str
    quota_policy_digest: str
    captured_at: str
    expires_at: str

    def __post_init__(self) -> None:
        if self.schema_version != CACHE_ENTRY_SCHEMA or not self.cache_key or not self.provider_id:
            raise ValueError("cache entry identity is incomplete")
        for value, name in (
            (self.cache_entry_id, "cache entry ID"),
            (self.provider_request_hash, "provider request hash"),
            (self.artifact_hash, "cache artifact hash"),
            (self.quota_policy_digest, "cache quota-policy digest"),
        ):
            _cache_digest(value, name)
        if not isinstance(self.byte_length, int) or self.byte_length < 0:
            raise ValueError("cache artifact byte length is invalid")
        captured = parse_utc(self.captured_at)
        expires = parse_utc(self.expires_at)
        if expires <= captured:
            raise ValueError("cache expiry must follow capture")
        object.__setattr__(self, "captured_at", iso_utc(self.captured_at))
        object.__setattr__(self, "expires_at", iso_utc(self.expires_at))
        if self.compute_id() != self.cache_entry_id:
            raise ValueError("cache entry identity mismatch")

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("cache_entry_id")
        return value

    def compute_id(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        return self.unsigned_dict() | {"cache_entry_id": self.cache_entry_id}

    @classmethod
    def create(cls, **fields: Any) -> "VerifiedCacheEntry":
        normalized = dict(fields)
        normalized.setdefault("schema_version", CACHE_ENTRY_SCHEMA)
        normalized["captured_at"] = iso_utc(normalized["captured_at"])
        normalized["expires_at"] = iso_utc(normalized["expires_at"])
        return cls(
            cache_entry_id=sha256_bytes(canonical_json(normalized)), **normalized,
        )


class VerifiedCacheStore:
    """Immutable cache bytes plus append-only observation/invalidation authority."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.log = AppendOnlyJsonl(self.root / "cache-authority.jsonl", reader=self._replay)

    def object_path(self, artifact_hash: str) -> Path:
        _cache_digest(artifact_hash, "cache artifact hash")
        return self.objects / artifact_hash[:2] / artifact_hash[2:]

    @staticmethod
    def _replay(rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> tuple[
        dict[str, VerifiedCacheEntry], dict[str, dict[str, Any]]
    ]:
        entries: dict[str, VerifiedCacheEntry] = {}
        invalidations: dict[str, dict[str, Any]] = {}
        entry_fields = set(VerifiedCacheEntry.__dataclass_fields__)
        chain_fields = {"previous_hash", "sequence", "record_hash"}
        for row in rows:
            kind = row.get("record_type")
            if kind == "verified_cache_entry_published":
                if set(row) != entry_fields | chain_fields | {"record_type"}:
                    raise RegistryConflict("cache publication has an unsupported schema")
                try:
                    entry = VerifiedCacheEntry(**{key: row[key] for key in entry_fields})
                except (KeyError, TypeError, ValueError) as exc:
                    raise RegistryConflict("invalid cache publication") from exc
                if entry.cache_entry_id in entries:
                    raise RegistryConflict("duplicate cache entry publication")
                entries[entry.cache_entry_id] = entry
                continue
            if kind == "verified_cache_entry_invalidated":
                required = {
                    "record_type", "cache_entry_id", "invalidated_at", "reason",
                } | chain_fields
                if set(row) != required:
                    raise RegistryConflict("cache invalidation has an unsupported schema")
                try:
                    entry_id = _cache_digest(row["cache_entry_id"], "cache entry ID")
                    invalidated_at = iso_utc(row["invalidated_at"])
                    if invalidated_at != row["invalidated_at"] or not row["reason"]:
                        raise ValueError
                except (KeyError, TypeError, ValueError) as exc:
                    raise RegistryConflict("invalid cache invalidation") from exc
                if entry_id not in entries or entry_id in invalidations:
                    raise RegistryConflict("orphan or duplicate cache invalidation")
                invalidations[entry_id] = row
                continue
            raise RegistryConflict(f"unsupported cache authority event: {kind!r}")
        return entries, invalidations

    def _verify_bytes(self, entry: VerifiedCacheEntry) -> bytes:
        try:
            payload = self.object_path(entry.artifact_hash).read_bytes()
        except OSError as exc:
            raise CacheUnavailable("cache artifact is missing") from exc
        if len(payload) != entry.byte_length or sha256_bytes(payload) != entry.artifact_hash:
            raise CacheUnavailable("cache artifact content does not match authority")
        return payload

    def publish(
        self,
        payload: bytes,
        *,
        cache_key: str,
        provider_request_hash: str,
        provider_id: str,
        quota_policy_digest: str,
        captured_at: str,
        expires_at: str,
    ) -> CacheReference:
        if not isinstance(payload, bytes):
            raise TypeError("cache payload must be immutable bytes")
        artifact_hash = sha256_bytes(payload)
        entry = VerifiedCacheEntry.create(
            cache_key=cache_key,
            provider_request_hash=provider_request_hash,
            artifact_hash=artifact_hash,
            byte_length=len(payload),
            provider_id=provider_id,
            quota_policy_digest=quota_policy_digest,
            captured_at=captured_at,
            expires_at=expires_at,
        )
        immutable_write(self.object_path(artifact_hash), payload)
        record = {"record_type": "verified_cache_entry_published", **entry.to_dict()}

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            entries, _invalidations = self._replay(rows)
            existing = entries.get(entry.cache_entry_id)
            if existing is None:
                return record
            if existing != entry:
                raise RegistryConflict("cache entry ID conflict")
            return None

        self.log.transaction(build)
        return CacheReference(entry.cache_entry_id)

    def get(self, cache_entry_id: str) -> VerifiedCacheEntry:
        try:
            entry_id = _cache_digest(cache_entry_id, "cache entry ID")
        except ValueError as exc:
            raise CacheUnavailable("cache entry reference is invalid") from exc
        entries, _invalidations = self._replay(self.log.records())
        entry = entries.get(entry_id)
        if entry is None:
            raise CacheUnavailable("cache entry is missing")
        self._verify_bytes(entry)
        return entry

    def resolve(
        self,
        cache_entry_id: str,
        *,
        at: str,
        provider_id: str,
        policy_digest: str,
        provider_request_hash: str,
    ) -> VerifiedCacheEntry:
        point = parse_utc(at)
        entries, invalidations = self._replay(self.log.records())
        entry = entries.get(cache_entry_id)
        if entry is None:
            raise CacheUnavailable("cache entry is missing")
        self._verify_bytes(entry)
        invalidation = invalidations.get(cache_entry_id)
        if (
            entry.provider_id != provider_id
            or entry.quota_policy_digest != policy_digest
            or entry.provider_request_hash != provider_request_hash
            or not (parse_utc(entry.captured_at) <= point < parse_utc(entry.expires_at))
            or (
                invalidation is not None
                and parse_utc(invalidation["invalidated_at"]) <= point
            )
        ):
            raise CacheUnavailable("cache entry is not usable for this exact request")
        return entry

    def invalidate(self, cache_entry_id: str, *, invalidated_at: str, reason: str) -> None:
        entry_id = _cache_digest(cache_entry_id, "cache entry ID")
        timestamp = iso_utc(invalidated_at)
        if not reason:
            raise ValueError("cache invalidation reason is required")

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
            entries, invalidations = self._replay(rows)
            entry = entries.get(entry_id)
            if entry is None or entry_id in invalidations:
                raise RegistryConflict("cache entry cannot be invalidated")
            if parse_utc(timestamp) < parse_utc(entry.captured_at):
                raise RegistryConflict("cache invalidation predates capture")
            return {
                "record_type": "verified_cache_entry_invalidated",
                "cache_entry_id": entry_id,
                "invalidated_at": timestamp,
                "reason": reason,
            }

        self.log.transaction(build)

    def verify(self) -> int:
        rows = self.log.records()
        entries, _invalidations = self._replay(rows)
        for entry in entries.values():
            self._verify_bytes(entry)
        return len(rows)


@dataclass(frozen=True)
class _QuotaState:
    calls: tuple[dict[str, Any], ...]
    decisions: dict[str, dict[str, Any]]
    authorizations: dict[str, QuotaReserveAuthorization]
    revocations: dict[str, dict[str, Any]]


class QuotaLedger:
    def __init__(
        self,
        path: str | Path,
        *,
        policy: QuotaPolicy,
        allow_test_policy: bool = False,
        cache_store: VerifiedCacheStore | None = None,
    ):
        policy.require_operational(allow_test_policy=allow_test_policy)
        self.policy = policy
        self.cache_store = cache_store
        self.log = AppendOnlyJsonl(path, reader=self._replay)
        self._validated_state(tuple(self.log.records()))

    @classmethod
    def from_active_config(
        cls,
        path: str | Path,
        policy_path: str | Path,
    ) -> "QuotaLedger":
        return cls(path, policy=load_quota_policy(policy_path))

    @staticmethod
    def _authorization_from_row(row: dict[str, Any]) -> QuotaReserveAuthorization:
        try:
            return QuotaReserveAuthorization(
                **{key: row[key] for key in QuotaReserveAuthorization.__dataclass_fields__}
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryConflict("invalid quota reserve authorization event") from exc

    @classmethod
    def _replay(cls, rows: tuple[dict[str, Any], ...]) -> _QuotaState:
        calls: list[dict[str, Any]] = []
        decisions: dict[str, dict[str, Any]] = {}
        authorizations: dict[str, QuotaReserveAuthorization] = {}
        revocations: dict[str, dict[str, Any]] = {}

        for row in rows:
            record_type = row.get("record_type")
            if record_type == "billable_call" and row.get("schema_version") is None:
                try:
                    request_id = row["request_id"]
                    units = int(row["units"])
                    parse_utc(row["occurred_at"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise RegistryConflict("invalid legacy quota usage event") from exc
                if not request_id or units <= 0 or request_id in decisions:
                    raise RegistryConflict("ambiguous legacy quota usage event")
                migrated = {
                    **row,
                    "provider_id": None,
                    "budget_class": BudgetClass.NORMAL.value,
                    "authorization_id": None,
                    "allowed": True,
                    "reason": "legacy_billable_usage",
                    "request_fingerprint": None,
                }
                calls.append(migrated)
                decisions[request_id] = migrated
                continue
            if record_type == "quota_reserve_authorization_granted":
                if row.get("event_schema_version") != QUOTA_EVENT_SCHEMA:
                    raise RegistryConflict("unsupported reserve grant event schema")
                authorization = cls._authorization_from_row(row)
                if authorization.authorization_id in authorizations:
                    raise RegistryConflict("duplicate reserve authorization grant event")
                authorizations[authorization.authorization_id] = authorization
                continue
            if record_type == "quota_reserve_authorization_revoked":
                if row.get("schema_version") != QUOTA_EVENT_SCHEMA:
                    raise RegistryConflict("unsupported reserve revocation event schema")
                authorization_id = row.get("authorization_id")
                if authorization_id not in authorizations or authorization_id in revocations:
                    raise RegistryConflict("invalid or duplicate reserve revocation")
                try:
                    parse_utc(row["revoked_at"])
                    if not row["reason"] or not row["approval_reference"]:
                        raise ValueError
                except (KeyError, TypeError, ValueError) as exc:
                    raise RegistryConflict("invalid reserve revocation event") from exc
                revocations[authorization_id] = row
                continue
            if record_type not in {
                "quota_billable_call",
                "quota_request_blocked",
                "quota_verified_cache_hit",
            }:
                raise RegistryConflict(f"unknown quota ledger event: {record_type!r}")
            expected_schema = (
                CACHE_HIT_EVENT_SCHEMA
                if record_type == "quota_verified_cache_hit"
                else QUOTA_EVENT_SCHEMA
            )
            if row.get("schema_version") != expected_schema:
                raise RegistryConflict("unsupported quota request event schema")
            required = {
                "request_id",
                "request_fingerprint",
                "occurred_at",
                "provider_id",
                "quota_policy_version",
                "quota_policy_digest",
                "billable_units",
                "budget_class",
                "authorization_id",
                "allowed",
                "reason",
                "daily_used",
                "monthly_used",
                "normal_monthly_used",
                "reserve_monthly_used",
            }
            if not required.issubset(row):
                raise RegistryConflict("quota request event is incomplete")
            request_id = row["request_id"]
            if not request_id or request_id in decisions:
                raise RegistryConflict("duplicate quota request ID")
            try:
                parse_utc(row["occurred_at"])
                units = int(row["billable_units"])
                if units < 0:
                    raise ValueError
                budget_class = row["budget_class"]
                if budget_class is not None:
                    BudgetClass(budget_class)
            except (TypeError, ValueError) as exc:
                raise RegistryConflict("invalid quota request event") from exc
            expected_allowed = record_type != "quota_request_blocked"
            if bool(row["allowed"]) != expected_allowed:
                raise RegistryConflict("quota decision disposition disagrees with event type")
            if record_type == "quota_billable_call":
                if units <= 0 or budget_class is None:
                    raise RegistryConflict("billable quota event is incomplete")
                calls.append(row)
            elif units != 0:
                raise RegistryConflict("non-billable quota event charged units")
            if record_type == "quota_verified_cache_hit":
                cache_fields = {
                    "cache_entry_id", "provider_request_hash", "cache_key",
                    "cache_artifact_hash", "cache_byte_length", "cache_captured_at",
                    "cache_expires_at",
                }
                exact_fields = required | cache_fields | {
                    "record_type", "schema_version", "previous_hash", "sequence",
                    "record_hash",
                }
                if set(row) != exact_fields:
                    raise RegistryConflict("verified cache event lacks exact proof identity")
                try:
                    for field in (
                        "cache_entry_id", "provider_request_hash", "cache_artifact_hash",
                    ):
                        _cache_digest(row[field], field)
                    if int(row["cache_byte_length"]) < 0 or not row["cache_key"]:
                        raise ValueError
                    if row["cache_captured_at"] != iso_utc(row["cache_captured_at"]):
                        raise ValueError
                    if row["cache_expires_at"] != iso_utc(row["cache_expires_at"]):
                        raise ValueError
                except (KeyError, TypeError, ValueError) as exc:
                    raise RegistryConflict("verified cache event proof is invalid") from exc
            decisions[request_id] = row
        return _QuotaState(tuple(calls), decisions, authorizations, revocations)

    def _validated_state(self, rows: tuple[dict[str, Any], ...]) -> _QuotaState:
        """Re-derive active-policy quota legality from the ordered authority."""

        state = self._replay(rows)
        authorizations: dict[str, QuotaReserveAuthorization] = {}
        revoked: set[str] = set()
        daily: dict[tuple[int, int, int], int] = {}
        monthly: dict[tuple[int, int], int] = {}
        normal: dict[tuple[int, int], int] = {}
        reserve: dict[tuple[int, int], int] = {}
        authorization_used: dict[str, int] = {}

        for row in rows:
            record_type = row.get("record_type")
            if record_type == "quota_reserve_authorization_granted":
                authorization = self._authorization_from_row(row)
                authorizations[authorization.authorization_id] = authorization
                continue
            if record_type == "quota_reserve_authorization_revoked":
                revoked.add(row["authorization_id"])
                continue
            if record_type not in {"billable_call", "quota_billable_call"}:
                if record_type == "quota_verified_cache_hit":
                    if self.cache_store is None:
                        raise RegistryConflict("verified cache history has no cache authority")
                    try:
                        entry = self.cache_store.resolve(
                            row["cache_entry_id"],
                            at=row["occurred_at"],
                            provider_id=row["provider_id"],
                            policy_digest=row["quota_policy_digest"],
                            provider_request_hash=row["provider_request_hash"],
                        )
                    except CacheUnavailable as exc:
                        raise RegistryConflict("persisted cache hit lacks valid proof") from exc
                    if any((
                        row["cache_key"] != entry.cache_key,
                        row["cache_artifact_hash"] != entry.artifact_hash,
                        int(row["cache_byte_length"]) != entry.byte_length,
                        row["cache_captured_at"] != entry.captured_at,
                        row["cache_expires_at"] != entry.expires_at,
                    )):
                        raise RegistryConflict("persisted cache proof differs from authority")
                continue
            if record_type == "billable_call":
                provider_id = self.policy.provider_id
                units = int(row["units"])
                budget = BudgetClass.NORMAL
                policy_matches = False
                authorization_id = None
            else:
                provider_id = row["provider_id"]
                units = int(row["billable_units"])
                budget = BudgetClass(row["budget_class"])
                policy_matches = (
                    row["quota_policy_version"] == self.policy.version
                    and row["quota_policy_digest"] == self.policy.policy_digest
                )
                authorization_id = row.get("authorization_id")
            if provider_id != self.policy.provider_id:
                continue
            point = parse_utc(row["occurred_at"])
            day_key = (point.year, point.month, point.day)
            month_key = (point.year, point.month)
            before_daily = daily.get(day_key, 0)
            before_monthly = monthly.get(month_key, 0)
            before_normal = normal.get(month_key, 0)
            before_reserve = reserve.get(month_key, 0)

            if policy_matches:
                if before_daily + units > self.policy.daily_billable_budget:
                    raise RegistryConflict("persisted billable call exceeds active daily budget")
                if budget == BudgetClass.NORMAL:
                    if authorization_id is not None:
                        raise RegistryConflict("persisted normal call carries reserve authority")
                    if before_normal + units > self.policy.normal_monthly_budget:
                        raise RegistryConflict("persisted normal call exceeds active monthly budget")
                else:
                    authorization = authorizations.get(authorization_id or "")
                    if authorization is None:
                        raise RegistryConflict("persisted reserve call has no prior authorization")
                    if before_normal < self.policy.normal_monthly_budget:
                        raise RegistryConflict("persisted reserve call predates normal-budget exhaustion")
                    if authorization_id in revoked:
                        raise RegistryConflict("persisted reserve call follows authorization revocation")
                    if (
                        authorization.provider_id != self.policy.provider_id
                        or authorization.quota_policy_version != self.policy.version
                        or authorization.quota_policy_digest != self.policy.policy_digest
                        or authorization.quota_period != f"{point.year:04d}-{point.month:02d}"
                        or not (
                            parse_utc(authorization.valid_from)
                            <= point
                            < parse_utc(authorization.valid_through)
                        )
                    ):
                        raise RegistryConflict("persisted reserve call violates authorization binding")
                    consumed = authorization_used.get(authorization.authorization_id, 0)
                    if consumed + units > authorization.max_reserve_units:
                        raise RegistryConflict("persisted reserve call exceeds authorization grant")
                if before_reserve + (units if budget == BudgetClass.RESERVE else 0) > self.policy.reserve_units:
                    raise RegistryConflict("persisted call exceeds protected reserve")
                if before_monthly + units > self.policy.genesis_monthly_limit:
                    raise RegistryConflict("persisted call exceeds Genesis monthly limit")
                if before_monthly + units > self.policy.provider_monthly_allowance:
                    raise RegistryConflict("persisted call exceeds provider monthly allowance")

            daily[day_key] = before_daily + units
            monthly[month_key] = before_monthly + units
            if budget == BudgetClass.RESERVE:
                reserve[month_key] = before_reserve + units
                if authorization_id is not None:
                    authorization_used[authorization_id] = authorization_used.get(authorization_id, 0) + units
            else:
                normal[month_key] = before_normal + units

            if policy_matches:
                if (
                    int(row["daily_used"]) != daily[day_key]
                    or int(row["monthly_used"]) != monthly[month_key]
                    or int(row["normal_monthly_used"]) != normal.get(month_key, 0)
                    or int(row["reserve_monthly_used"]) != reserve.get(month_key, 0)
                ):
                    raise RegistryConflict("persisted quota counters disagree with replay")
        return state

    def _counts(
        self,
        state: _QuotaState,
        occurred_at: str,
    ) -> tuple[int, int, int, int]:
        point = parse_utc(occurred_at)
        month = (point.year, point.month)
        daily = monthly = normal = reserve = 0
        for call in state.calls:
            provider_id = call.get("provider_id")
            if provider_id not in {None, self.policy.provider_id}:
                continue
            called = parse_utc(call["occurred_at"])
            units = int(call.get("billable_units", call.get("units", 0)))
            if called.date() == point.date():
                daily += units
            if (called.year, called.month) == month:
                monthly += units
                if call.get("budget_class") == BudgetClass.RESERVE.value:
                    reserve += units
                else:
                    normal += units
        return daily, monthly, normal, reserve

    @staticmethod
    def _decision_from_row(row: dict[str, Any]) -> QuotaDecision:
        budget = row.get("budget_class")
        return QuotaDecision(
            allowed=bool(row["allowed"]),
            reason=row["reason"],
            daily_used=int(row["daily_used"]),
            monthly_used=int(row["monthly_used"]),
            normal_monthly_used=int(row["normal_monthly_used"]),
            reserve_monthly_used=int(row["reserve_monthly_used"]),
            request_id=row["request_id"],
            budget_class=BudgetClass(budget) if budget is not None else None,
            authorization_id=row.get("authorization_id"),
            billable_units=int(row["billable_units"]),
        )

    def grant_authorization(self, authorization: QuotaReserveAuthorization) -> str:
        if (
            authorization.provider_id != self.policy.provider_id
            or authorization.quota_policy_version != self.policy.version
            or authorization.quota_policy_digest != self.policy.policy_digest
            or authorization.max_reserve_units > self.policy.reserve_units
        ):
            raise RegistryConflict("reserve authorization is not bound to the active quota policy")

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            state = self._validated_state(rows)
            existing = state.authorizations.get(authorization.authorization_id)
            if existing is not None:
                if existing != authorization:
                    raise RegistryConflict("reserve authorization ID conflict")
                return None
            return {
                "record_type": "quota_reserve_authorization_granted",
                "event_schema_version": QUOTA_EVENT_SCHEMA,
                **authorization.to_dict(),
            }

        self.log.transaction(build)
        return authorization.authorization_id

    def revoke_authorization(
        self,
        authorization_id: str,
        *,
        revoked_at: str,
        reason: str,
        approval_reference: str,
    ) -> None:
        revoked_at = iso_utc(revoked_at)
        if not reason or not approval_reference:
            raise ValueError("revocation reason/approval reference are required")

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            state = self._validated_state(rows)
            authorization = state.authorizations.get(authorization_id)
            if authorization is None:
                raise RegistryConflict("cannot revoke unknown reserve authorization")
            if parse_utc(revoked_at) < parse_utc(authorization.granted_at):
                raise RegistryConflict("reserve revocation predates grant")
            record = {
                "record_type": "quota_reserve_authorization_revoked",
                "schema_version": QUOTA_EVENT_SCHEMA,
                "authorization_id": authorization_id,
                "revoked_at": revoked_at,
                "reason": reason,
                "approval_reference": approval_reference,
            }
            existing = state.revocations.get(authorization_id)
            if existing is not None:
                comparable = {key: existing.get(key) for key in record}
                if comparable != record:
                    raise RegistryConflict("reserve authorization revocation is irreversible")
                return None
            return record

        self.log.transaction(build)

    def _authorization_failure(
        self,
        state: _QuotaState,
        authorization_id: str | None,
        occurred_at: str,
        units: int,
    ) -> str | None:
        if authorization_id is None:
            return "reserve_authorization_required"
        authorization = state.authorizations.get(authorization_id)
        if authorization is None:
            return "reserve_authorization_unknown"
        point = parse_utc(occurred_at)
        if authorization.provider_id != self.policy.provider_id:
            return "reserve_authorization_wrong_provider"
        if (
            authorization.quota_policy_version != self.policy.version
            or authorization.quota_policy_digest != self.policy.policy_digest
        ):
            return "reserve_authorization_wrong_policy"
        if authorization.quota_period != f"{point.year:04d}-{point.month:02d}":
            return "reserve_authorization_wrong_period"
        if not (
            parse_utc(authorization.valid_from)
            <= point
            < parse_utc(authorization.valid_through)
        ):
            return "reserve_authorization_expired"
        if authorization_id in state.revocations:
            return "reserve_authorization_revoked"
        consumed = sum(
            int(call.get("billable_units", 0))
            for call in state.calls
            if call.get("authorization_id") == authorization_id
        )
        if consumed + units > authorization.max_reserve_units:
            return "reserve_authorization_exhausted"
        return None

    def request(
        self,
        *,
        request_id: str,
        occurred_at: str,
        billable_units: int = 1,
        budget_class: BudgetClass = BudgetClass.NORMAL,
        authorization_id: str | None = None,
        cache: CacheReference | CachedData | None = None,
        provider_id: str | None = None,
        provider_request_hash: str | None = None,
    ) -> QuotaDecision:
        if not request_id:
            raise ValueError("quota request ID is required")
        if billable_units <= 0:
            raise ValueError("billable units must be positive")
        occurred_at = iso_utc(occurred_at)
        budget_class = BudgetClass(budget_class)
        requested_provider = provider_id or self.policy.provider_id
        if provider_request_hash is not None:
            _cache_digest(provider_request_hash, "provider request hash")
        cache_entry_id = (
            cache.cache_entry_id if isinstance(cache, CacheReference) else None
        )
        fingerprint = sha256_bytes(
            canonical_json(
                {
                    "provider_id": requested_provider,
                    "occurred_at": occurred_at,
                    "billable_units": billable_units,
                    "budget_class": budget_class.value,
                    "authorization_id": authorization_id,
                    "cache_entry_id": cache_entry_id,
                    "provider_request_hash": provider_request_hash,
                    "quota_policy_version": self.policy.version,
                    "quota_policy_digest": self.policy.policy_digest,
                }
            )
        )
        selected: QuotaDecision | None = None

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            nonlocal selected
            state = self._validated_state(rows)
            existing = state.decisions.get(request_id)
            if existing is not None:
                if existing.get("request_fingerprint") is None:
                    raise RegistryConflict("legacy quota request ID cannot be replayed")
                if existing.get("request_fingerprint") != fingerprint:
                    raise RegistryConflict("quota request ID cannot be reused with another payload")
                selected = self._decision_from_row(existing)
                return None

            daily, monthly, normal, reserve = self._counts(state, occurred_at)
            base = {
                "schema_version": QUOTA_EVENT_SCHEMA,
                "request_id": request_id,
                "request_fingerprint": fingerprint,
                "occurred_at": occurred_at,
                "provider_id": requested_provider,
                "quota_policy_version": self.policy.version,
                "quota_policy_digest": self.policy.policy_digest,
                "authorization_id": authorization_id,
            }
            latest_request_time = max(
                (
                    parse_utc(row["occurred_at"])
                    for row in state.decisions.values()
                    if row.get("occurred_at") is not None
                ),
                default=None,
            )
            time_regressed = latest_request_time is not None and parse_utc(occurred_at) < latest_request_time
            cache_entry: VerifiedCacheEntry | None = None
            if (
                not time_regressed
                and requested_provider == self.policy.provider_id
                and self.cache_store is not None
                and cache_entry_id is not None
                and provider_request_hash is not None
            ):
                try:
                    cache_entry = self.cache_store.resolve(
                        cache_entry_id,
                        at=occurred_at,
                        provider_id=self.policy.provider_id,
                        policy_digest=self.policy.policy_digest,
                        provider_request_hash=provider_request_hash,
                    )
                except CacheUnavailable:
                    cache_entry = None
            if (
                not time_regressed
                and requested_provider == self.policy.provider_id
                and cache_entry is not None
            ):
                selected = QuotaDecision(
                    True,
                    "verified_cache_hit",
                    daily,
                    monthly,
                    normal,
                    reserve,
                    request_id,
                    None,
                    None,
                    0,
                )
                return {
                    "record_type": "quota_verified_cache_hit",
                    **base,
                    "schema_version": CACHE_HIT_EVENT_SCHEMA,
                    "billable_units": 0,
                    "budget_class": None,
                    "allowed": True,
                    "reason": selected.reason,
                    "daily_used": daily,
                    "monthly_used": monthly,
                    "normal_monthly_used": normal,
                    "reserve_monthly_used": reserve,
                    "cache_entry_id": cache_entry.cache_entry_id,
                    "provider_request_hash": cache_entry.provider_request_hash,
                    "cache_key": cache_entry.cache_key,
                    "cache_artifact_hash": cache_entry.artifact_hash,
                    "cache_byte_length": cache_entry.byte_length,
                    "cache_captured_at": cache_entry.captured_at,
                    "cache_expires_at": cache_entry.expires_at,
                }

            reason: str | None = None
            if time_regressed:
                reason = "quota_event_time_regressed"
            elif requested_provider != self.policy.provider_id:
                reason = "provider_identity_mismatch"
            elif daily + billable_units > self.policy.daily_billable_budget:
                reason = "daily_quota_exhausted"
            elif budget_class == BudgetClass.NORMAL:
                if authorization_id is not None:
                    reason = "normal_request_cannot_use_reserve_authorization"
                elif normal + billable_units > self.policy.normal_monthly_budget:
                    reason = "normal_monthly_budget_exhausted"
                elif monthly + billable_units > self.policy.genesis_monthly_limit:
                    reason = "genesis_monthly_limit_exhausted"
                elif monthly + billable_units > self.policy.provider_monthly_allowance:
                    reason = "provider_monthly_allowance_exhausted"
            else:
                if normal < self.policy.normal_monthly_budget:
                    reason = "normal_monthly_budget_not_exhausted"
                else:
                    reason = self._authorization_failure(
                        state, authorization_id, occurred_at, billable_units
                    )
                if reason is None and reserve + billable_units > self.policy.reserve_units:
                    reason = "protected_reserve_exhausted"
                if reason is None and monthly + billable_units > self.policy.genesis_monthly_limit:
                    reason = "genesis_monthly_limit_exhausted"
                if reason is None and monthly + billable_units > self.policy.provider_monthly_allowance:
                    reason = "provider_monthly_allowance_exhausted"

            allowed = reason is None
            next_daily = daily + billable_units if allowed else daily
            next_monthly = monthly + billable_units if allowed else monthly
            next_normal = normal + billable_units if allowed and budget_class == BudgetClass.NORMAL else normal
            next_reserve = reserve + billable_units if allowed and budget_class == BudgetClass.RESERVE else reserve
            selected = QuotaDecision(
                allowed,
                reason or "billable_call_reserved",
                next_daily,
                next_monthly,
                next_normal,
                next_reserve,
                request_id,
                budget_class,
                authorization_id,
                billable_units if allowed else 0,
            )
            return {
                "record_type": "quota_billable_call" if allowed else "quota_request_blocked",
                **base,
                "billable_units": billable_units if allowed else 0,
                "requested_billable_units": billable_units,
                "budget_class": budget_class.value,
                "allowed": allowed,
                "reason": selected.reason,
                "daily_used": next_daily,
                "monthly_used": next_monthly,
                "normal_monthly_used": next_normal,
                "reserve_monthly_used": next_reserve,
            }

        self.log.transaction(
            build,
            read_locks=(self.cache_store.log,) if self.cache_store is not None else (),
        )
        assert selected is not None
        return selected

    def usage(self, occurred_at: str) -> tuple[int, int]:
        state = self._validated_state(tuple(self.log.records()))
        daily, monthly, _normal, _reserve = self._counts(state, occurred_at)
        return daily, monthly

    def verify(self) -> int:
        rows = tuple(self.log.records())
        self._validated_state(rows)
        return len(rows)


def allow_cached_or_block(
    cache: CacheReference | None,
    at: str,
    *,
    provider_id: str,
    policy_digest: str,
    provider_request_hash: str,
    cache_store: VerifiedCacheStore | None,
) -> bool:
    if cache is None or cache_store is None:
        return False
    try:
        cache_store.resolve(
            cache.cache_entry_id,
            at=at,
            provider_id=provider_id,
            policy_digest=policy_digest,
            provider_request_hash=provider_request_hash,
        )
        return True
    except (CacheUnavailable, RegistryConflict, TypeError, ValueError):
        return False
