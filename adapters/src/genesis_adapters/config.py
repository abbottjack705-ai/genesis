"""Adapter configuration: SlicePolicy (design section 12.1), file digests, derivation_version.

``SlicePolicy`` has NO code defaults: every provisional slice-1 parameter is read from
``oddspapi_slice1_policy.json``, whose canonical-JSON SHA-256 (``policy_digest``) feeds
``derivation_version``. Changing any value therefore creates a new derivation source.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from genesis.repro import canonical_json, sha256_bytes

POLICY_CLASSIFICATION = "PROVISIONAL_SLICE1_POLICY"
CACHE_ROLES = ("FIXTURES", "META_BOOKMAKERS", "META_MARKETS", "META_SPORTS", "META_TOURNAMENTS")
BUDGET_POOLS = ("conditional", "fixtures", "metadata", "scheduled_odds")
_DAY_TIME = re.compile(r"^(MON|TUE|WED|THU|FRI|SAT|SUN) ([01]\d|2[0-3]):[0-5]\d$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

CONFIG_FILES = {
    "endpoint_spec_digest": "oddspapi_v4_endpoints.json",
    "identity_map_digest": "oddspapi_v4_identity_map.json",
    "market_map_digest": "oddspapi_v4_market_map.json",
    "response_schema_digest": "oddspapi_v4_response_schemas.json",
    "status_map_digest": "oddspapi_v4_status_map.json",
}
POLICY_FILE = "oddspapi_slice1_policy.json"


class ConfigError(ValueError):
    """Configuration that cannot be used."""


class PolicyError(ConfigError):
    """A slice-1 policy file that is missing, malformed or self-contradictory."""


class FixtureOnlyConfig(ConfigError):
    """The operational loader refuses maps that still contain fixture-only entries."""


@dataclass(frozen=True)
class SlicePolicy:
    policy_version: str
    classification: str
    price_ttl_seconds: int
    prematch_guard_seconds: int
    provider_future_tolerance_seconds: int
    clock_skew_max_seconds: int
    request_timeout_seconds: int
    wall_monotonic_drift_max_ms: int
    fixture_join_max_age_seconds: int
    max_response_bytes: int
    max_decompression_ratio: int
    secret_fragment_min_chars_floor: int
    secret_fragment_min_chars_divisor: int
    odds_min: str
    odds_max: str
    odds_max_fraction_digits: int
    overround_1x2: tuple[str, str]
    overround_ou: tuple[str, str]
    cache_ttl_seconds: Mapping[str, int]
    retry_min_backoff_seconds: int
    max_retries_per_window: int
    conditional_refresh_min_lead_seconds: int
    schedule_cluster_hours: int
    schedule_prekick_offset_minutes: int
    schedule_matchday_offset_hours: int
    schedule_inventory_utc: str
    schedule_inventory_horizon_hours: int
    schedule_fixtures_days_utc: tuple[str, ...]
    budget_pools: Mapping[str, int]
    scheduled_daily_max: int
    conditional_daily_max: int
    g3_min_observation_days: int
    declared_bookmakers_max: int
    header_value_max_chars: int
    read_chunk_bytes: int

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, tuple):
                value = list(value)
            elif isinstance(value, Mapping):
                value = dict(value)
            result[item.name] = value
        return result

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json(self.to_dict()))


_POSITIVE_INTS = (
    "price_ttl_seconds", "prematch_guard_seconds", "provider_future_tolerance_seconds",
    "clock_skew_max_seconds", "request_timeout_seconds", "wall_monotonic_drift_max_ms",
    "fixture_join_max_age_seconds", "max_response_bytes", "max_decompression_ratio",
    "secret_fragment_min_chars_floor", "secret_fragment_min_chars_divisor",
    "retry_min_backoff_seconds", "conditional_refresh_min_lead_seconds", "schedule_cluster_hours",
    "schedule_prekick_offset_minutes", "schedule_matchday_offset_hours",
    "schedule_inventory_horizon_hours", "scheduled_daily_max", "g3_min_observation_days",
    "declared_bookmakers_max", "header_value_max_chars", "read_chunk_bytes",
)
_NON_NEGATIVE_INTS = ("odds_max_fraction_digits", "max_retries_per_window", "conditional_daily_max")


def _int(body: Mapping, name: str, *, minimum: int) -> int:
    value = body[name]
    if type(value) is not int or value < minimum:
        raise PolicyError(f"{name} must be an integer >= {minimum}")
    return value


def _decimal(value: Any, name: str) -> Decimal:
    if type(value) is not str:
        raise PolicyError(f"{name} must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise PolicyError(f"{name} is not a decimal") from None
    if not number.is_finite():
        raise PolicyError(f"{name} must be finite")
    return number


def parse_policy(body: Any) -> SlicePolicy:
    """Validate a decoded policy document and return the frozen :class:`SlicePolicy`."""

    names = {item.name for item in fields(SlicePolicy)}
    if type(body) is not dict or set(body) != names:
        raise PolicyError("policy fields differ from the SlicePolicy field list")
    if body["classification"] != POLICY_CLASSIFICATION:
        raise PolicyError("policy classification must be PROVISIONAL_SLICE1_POLICY")
    if type(body["policy_version"]) is not str or not body["policy_version"]:
        raise PolicyError("policy_version is required")
    values: dict[str, Any] = {"policy_version": body["policy_version"],
                              "classification": body["classification"]}
    for name in _POSITIVE_INTS:
        values[name] = _int(body, name, minimum=1)
    for name in _NON_NEGATIVE_INTS:
        values[name] = _int(body, name, minimum=0)
    odds_min = _decimal(body["odds_min"], "odds_min")
    odds_max = _decimal(body["odds_max"], "odds_max")
    if not Decimal(1) < odds_min < odds_max:
        raise PolicyError("odds bounds must satisfy 1 < odds_min < odds_max")
    values["odds_min"], values["odds_max"] = body["odds_min"], body["odds_max"]
    for name in ("overround_1x2", "overround_ou"):
        pair = body[name]
        if type(pair) is not list or len(pair) != 2:
            raise PolicyError(f"{name} must be a [low, high] pair")
        low, high = _decimal(pair[0], name), _decimal(pair[1], name)
        if not Decimal(0) < low < high:
            raise PolicyError(f"{name} must satisfy 0 < low < high")
        values[name] = (pair[0], pair[1])
    ttl = body["cache_ttl_seconds"]
    if type(ttl) is not dict or set(ttl) != set(CACHE_ROLES) or any(
            type(v) is not int or v < 1 for v in ttl.values()):
        raise PolicyError("cache_ttl_seconds needs a positive integer for exactly the cacheable roles")
    values["cache_ttl_seconds"] = dict(ttl)
    pools = body["budget_pools"]
    if type(pools) is not dict or set(pools) != set(BUDGET_POOLS) or any(
            type(v) is not int or v < 0 for v in pools.values()):
        raise PolicyError("budget_pools needs a non-negative integer for exactly the four pools")
    values["budget_pools"] = dict(pools)
    if type(body["schedule_inventory_utc"]) is not str or not _TIME.match(body["schedule_inventory_utc"]):
        raise PolicyError("schedule_inventory_utc must be HH:MM")
    values["schedule_inventory_utc"] = body["schedule_inventory_utc"]
    days = body["schedule_fixtures_days_utc"]
    if type(days) is not list or not days or any(
            type(d) is not str or not _DAY_TIME.match(d) for d in days):
        raise PolicyError("schedule_fixtures_days_utc must be a non-empty list of 'DAY HH:MM'")
    values["schedule_fixtures_days_utc"] = tuple(days)
    zone = timedelta(seconds=values["request_timeout_seconds"]
                     + 2 * values["clock_skew_max_seconds"])
    if zone >= timedelta(hours=1):
        raise PolicyError("guard zone request_timeout + 2 * clock_skew must stay below one hour")
    return SlicePolicy(**values)


def _reject_float(_text):
    raise PolicyError("policy files may not contain floating-point numbers")


def load_policy(path: str | Path) -> SlicePolicy:
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"), parse_float=_reject_float)
    except (OSError, ValueError) as exc:
        if isinstance(exc, PolicyError):
            raise
        raise PolicyError("policy file is missing or not JSON") from None
    return parse_policy(body)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConfigError(f"config file is missing or not JSON: {path.name}") from None


def _digest(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def load_config_digests(config_dir: str | Path) -> dict[str, str]:
    """Canonical-JSON SHA-256 of each pinned config file (the policy digest is separate)."""

    root = Path(config_dir)
    return {key: _digest(_load_json(root / name)) for key, name in CONFIG_FILES.items()}


def derivation_version(code_version: str, digests: Mapping[str, str], policy: SlicePolicy) -> str:
    """``mb1-<16hex>`` over code, maps, schemas, endpoint specs and the FULL policy digest."""

    if set(digests) != set(CONFIG_FILES):
        raise ConfigError("digest set is incomplete")
    payload = {"code_version": code_version, "policy_digest": policy.digest, **dict(digests)}
    return "mb1-" + _digest(payload)[:16]


def normalized_contract_id(version: str) -> str:
    return f"oddspapi-v4-market-book-{version}"


def market_book_source_id(version: str) -> str:
    return f"oddspapi.v4.soccer.market_book.{version}"


@dataclass(frozen=True)
class AdapterConfig:
    policy: SlicePolicy
    endpoints: Mapping[str, Any]
    identity_map: Mapping[str, Any]
    market_map: Mapping[str, Any]
    status_map: Mapping[str, Any]
    schemas: Mapping[str, Any]
    digests: Mapping[str, str]
    code_version: str
    derivation_version: str


def _fixture_only(entries) -> bool:
    return any(isinstance(item, dict) and item.get("fixture_only") for item in entries)


def load_adapter_config(config_dir: str | Path, *, allow_fixture_only: bool = False,
                        code_version: str = "unspecified") -> AdapterConfig:
    """Load and cross-check every pinned config file.

    The operational loader (``allow_fixture_only=False``) refuses any map that still holds a
    fixture-only entry (design section 8.5 rule 6, test ID-09).
    """

    from genesis_adapters import schema as schema_mod
    from genesis_adapters.oddspapi import endpoints as endpoints_mod

    root = Path(config_dir)
    policy = load_policy(root / POLICY_FILE)
    identity = _load_json(root / CONFIG_FILES["identity_map_digest"])
    market = _load_json(root / CONFIG_FILES["market_map_digest"])
    status = _load_json(root / CONFIG_FILES["status_map_digest"])
    if not allow_fixture_only and (
            _fixture_only(identity.get("competitions", ()))
            or _fixture_only(identity.get("bookmakers", ()))
            or _fixture_only(market.get("markets", ()))):
        raise FixtureOnlyConfig("maps still contain fixture-only entries")
    schemas_doc = _load_json(root / CONFIG_FILES["response_schema_digest"])
    if type(schemas_doc) is not dict or set(schemas_doc) != {"schema", "schemas"}:
        raise ConfigError("response schema file has an unexpected shape")
    schemas = {name: schema_mod.load_closed_schema(name, body)
               for name, body in schemas_doc["schemas"].items()}
    endpoints = endpoints_mod.load_endpoints(root / CONFIG_FILES["endpoint_spec_digest"], policy)
    for spec in endpoints.values():
        if spec.response_schema_id not in schemas:
            raise ConfigError("an endpoint references an unknown response schema")
    digests = load_config_digests(root)
    return AdapterConfig(policy, endpoints, identity, market, status, schemas, digests, code_version,
                         derivation_version(code_version, digests, policy))
