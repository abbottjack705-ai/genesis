"""Endpoint specs, canonical requests and the provider request hash (design sections 7.2, 7.3).

The canonical request is structured data built from a pinned endpoint spec. It has no field
that can carry the credential: any parameter named like the credential (or a common alias) is
REJECTED at build time, never dropped. ``provider_request_hash`` is the SHA-256 of the
canonical JSON of the request.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from genesis.repro import canonical_json, sha256_bytes

PROVIDER_ID = "oddspapi"
REQUEST_DOMAIN = "genesis.adapters.oddspapi.request.v1"
RAW_URI_PREFIX = "oddspapi-request:sha256:"
RAW_URI_PATTERN = RAW_URI_PREFIX + "*"
RAW_CONTRACT_ID = "oddspapi-v4-raw-response-v1"
FIXED_HEADERS = (("accept", "application/json"), ("accept-encoding", "identity"))
ROLES = ("META_SPORTS", "META_TOURNAMENTS", "META_BOOKMAKERS", "META_MARKETS", "FIXTURES", "ODDS")
CREDENTIAL_ALIASES = frozenset({"apikey", "api_key", "key", "token", "access_token", "secret"})
PARAM_TYPES = ("int", "str", "date", "csv_set")

_TEXT = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
_ENDPOINT_KEYS = frozenset({
    "cache_ttl_source", "cacheable", "credential_param", "doc_reference", "genesis_debit_units",
    "host", "method", "params", "path", "provider_documented_billable", "provider_metering",
    "provider_request_weight", "response_schema_id", "role", "scheme", "verified_live"})
_PARAM_KEYS = frozenset({"allowed_values", "element_type", "name", "required", "set_valued", "type"})


class SpecError(ValueError):
    """An endpoint spec that is malformed or unsafe."""


class RoleNotUsable(RuntimeError):
    """The role's provider metering cannot be bounded before sending (design 14.2)."""


class RequestError(ValueError):
    """A request that cannot be built. ``code`` is CREDENTIAL_PARAM, UNKNOWN_PARAM, MISSING_PARAM
    or INVALID_VALUE."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class Metering(StrEnum):
    PER_REQUEST = "PER_REQUEST"
    FIXED_WEIGHT = "FIXED_WEIGHT"
    NON_METERED = "NON_METERED"
    VARIABLE = "VARIABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str
    required: bool
    set_valued: bool
    allowed_values: tuple[str, ...] | None
    element_type: str | None


@dataclass(frozen=True)
class EndpointSpec:
    role: str
    method: str
    scheme: str
    host: str
    path: str
    params: tuple[ParamSpec, ...]
    credential_param: str
    cacheable: bool
    cache_ttl_seconds: int | None
    response_schema_id: str
    doc_reference: str
    verified_live: bool
    provider_metering: Metering
    provider_request_weight: int | None
    provider_documented_billable: bool | None
    genesis_debit_units: int
    api_version: str = "v4"

    @property
    def usable(self) -> bool:
        """VARIABLE/UNKNOWN roles have no pre-send bound and are never sent (BILL-03)."""

        return self.provider_metering not in (Metering.VARIABLE, Metering.UNKNOWN)

    def require_usable(self) -> None:
        if not self.usable:
            raise RoleNotUsable(self.role)


@dataclass(frozen=True)
class CanonicalRequest:
    role: str
    method: str
    scheme: str
    host: str
    path: str
    query: tuple[tuple[str, str], ...]
    headers: tuple[tuple[str, str], ...]
    api_version: str = "v4"

    def to_json(self) -> dict:
        return {
            "domain": REQUEST_DOMAIN,
            "provider_id": PROVIDER_ID,
            "api_version": self.api_version,
            "role": self.role,
            "method": self.method,
            "scheme": self.scheme,
            "host": self.host,
            "path": self.path,
            "query": [list(pair) for pair in self.query],
            "headers": [list(pair) for pair in self.headers],
            "body": None,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.to_json())

    @property
    def provider_request_hash(self) -> str:
        return sha256_bytes(self.canonical_bytes())

    @property
    def source_uri(self) -> str:
        return RAW_URI_PREFIX + self.provider_request_hash


def _bool(value: Any, where: str) -> bool:
    if type(value) is not bool:
        raise SpecError(f"{where} must be a boolean")
    return value


def _parse_param(raw: Any, credential: str) -> ParamSpec:
    if type(raw) is not dict or set(raw) != _PARAM_KEYS:
        raise SpecError("param spec has unexpected keys")
    name = raw["name"]
    if type(name) is not str or not _TEXT.match(name):
        raise SpecError("param name is invalid")
    folded = name.casefold()
    if folded == credential.casefold() or folded in CREDENTIAL_ALIASES:
        raise SpecError("a credential-like name cannot be a request parameter")
    if raw["type"] not in PARAM_TYPES:
        raise SpecError("param type is invalid")
    required = _bool(raw["required"], "required")
    set_valued = _bool(raw["set_valued"], "set_valued")
    element = raw["element_type"]
    if raw["type"] == "csv_set":
        if not set_valued or element not in ("int", "str"):
            raise SpecError("csv_set params must be set_valued with an int/str element type")
    elif set_valued or element is not None:
        raise SpecError("only csv_set params may be set_valued")
    allowed = raw["allowed_values"]
    if allowed is not None:
        if type(allowed) is not list or not allowed or any(type(v) is not str for v in allowed):
            raise SpecError("allowed_values must be a non-empty list of strings")
        allowed = tuple(allowed)
    return ParamSpec(name, raw["type"], required, set_valued, allowed, element)


def parse_endpoints(body: Any, policy) -> dict[str, EndpointSpec]:
    """Validate the endpoint spec document and return role -> :class:`EndpointSpec`."""

    if type(body) is not dict or set(body) != {"api_version", "endpoints", "schema"}:
        raise SpecError("endpoint file has unexpected keys")
    if body["schema"] != "genesis.adapters.oddspapi.endpoints.v1" or type(body["api_version"]) is not str:
        raise SpecError("unsupported endpoint schema")
    specs: dict[str, EndpointSpec] = {}
    for raw in body["endpoints"]:
        if type(raw) is not dict or set(raw) != _ENDPOINT_KEYS:
            raise SpecError("endpoint has unexpected keys")
        role = raw["role"]
        if role not in ROLES or role in specs:
            raise SpecError("unknown or duplicate endpoint role")
        if raw["method"] != "GET" or raw["scheme"] != "https":
            raise SpecError("only HTTPS GET is supported")
        host, path = raw["host"], raw["path"]
        if type(host) is not str or host != host.lower() or not _HOST.match(host):
            raise SpecError("host must be a pinned lowercase name")
        if type(path) is not str or not path.startswith("/") or path.endswith("/") or "?" in path:
            raise SpecError("path must be exact, without trailing slash or query")
        credential = raw["credential_param"]
        if type(credential) is not str or not credential:
            raise SpecError("credential_param is required")
        params = tuple(_parse_param(item, credential) for item in raw["params"])
        if len({p.name for p in params}) != len(params):
            raise SpecError("duplicate param names")
        cacheable = _bool(raw["cacheable"], "cacheable")
        source = raw["cache_ttl_source"]
        if cacheable:
            if role == "ODDS" or source != "policy" or role not in policy.cache_ttl_seconds:
                raise SpecError("cacheable roles need a policy TTL and ODDS is never cacheable")
            ttl: int | None = policy.cache_ttl_seconds[role]
        else:
            if source is not None:
                raise SpecError("an uncached role must not name a TTL source")
            ttl = None
        metering = raw["provider_metering"]
        try:
            metering = Metering(metering)
        except ValueError:
            raise SpecError("unknown provider_metering") from None
        weight, billable, debit = (raw["provider_request_weight"], raw["provider_documented_billable"],
                                   raw["genesis_debit_units"])
        if type(debit) is not int or debit < 1:
            raise SpecError("genesis_debit_units must be an integer >= 1")
        if billable is not None and type(billable) is not bool:
            raise SpecError("provider_documented_billable must be true, false or null")
        if metering is Metering.PER_REQUEST:
            ok = type(weight) is int and weight == 1 and billable in (True, None)
        elif metering is Metering.FIXED_WEIGHT:
            ok = type(weight) is int and weight >= 1 and billable in (True, None)
        elif metering is Metering.NON_METERED:
            ok = type(weight) is int and weight == 0 and billable in (False, None)
        else:
            ok = weight is None
        if not ok:
            raise SpecError("provider metering fields are inconsistent")
        if type(weight) is int and debit < max(1, weight):
            raise SpecError("genesis_debit_units must be >= the provider request weight")
        specs[role] = EndpointSpec(
            role=role, method=raw["method"], scheme=raw["scheme"], host=host, path=path,
            params=params, credential_param=credential, cacheable=cacheable, cache_ttl_seconds=ttl,
            response_schema_id=str(raw["response_schema_id"]), doc_reference=str(raw["doc_reference"]),
            verified_live=_bool(raw["verified_live"], "verified_live"), provider_metering=metering,
            provider_request_weight=weight, provider_documented_billable=billable,
            genesis_debit_units=debit, api_version=body["api_version"])
    return specs


def load_endpoints(path: str | Path, policy) -> dict[str, EndpointSpec]:
    import json

    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SpecError("endpoint file is missing or not JSON") from None
    return parse_endpoints(body, policy)


def _render_text(value: Any, name: str) -> str:
    if type(value) is not str:
        raise RequestError("INVALID_VALUE", f"{name} must be text")
    text = unicodedata.normalize("NFC", value)
    if not _TEXT.match(text):
        raise RequestError("INVALID_VALUE", f"{name} is outside the permitted grammar")
    return text


def _render_int(value: Any, name: str) -> str:
    if type(value) is not int or value < 0:
        raise RequestError("INVALID_VALUE", f"{name} must be a non-negative integer")
    text = str(value)
    if not _TEXT.match(text):
        raise RequestError("INVALID_VALUE", f"{name} is too large")
    return text


def _render_date(value: Any, name: str) -> str:
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is str and _DATE.match(value):
        try:
            if dt.date.fromisoformat(value).isoformat() == value:
                return value
        except ValueError:
            pass
    raise RequestError("INVALID_VALUE", f"{name} must be a calendar date (YYYY-MM-DD)")


def _render_scalar(kind: str, value: Any, name: str) -> str:
    if kind == "int":
        return _render_int(value, name)
    if kind == "str":
        return _render_text(value, name)
    if kind == "date":
        return _render_date(value, name)
    raise RequestError("INVALID_VALUE", f"{name} has an unsupported type")


def _render_param(param: ParamSpec, value: Any) -> str:
    if param.type == "csv_set":
        if not isinstance(value, (list, tuple, set, frozenset)) or not value:
            raise RequestError("INVALID_VALUE", f"{param.name} must be a non-empty collection")
        rendered = sorted({_render_scalar(param.element_type, item, param.name) for item in value},
                          key=(int if param.element_type == "int" else str))
        text = ",".join(rendered)
        parts = rendered
    else:
        text = _render_scalar(param.type, value, param.name)
        parts = [text]
    if param.allowed_values is not None and any(item not in param.allowed_values for item in parts):
        raise RequestError("INVALID_VALUE", f"{param.name} has a value outside the allowed set")
    return text


def build_request(spec: EndpointSpec, **params: Any) -> CanonicalRequest:
    """Build the canonical request for ``spec`` from typed arguments (design 7.3 rules 1-5)."""

    credential = spec.credential_param.casefold()
    for name in params:
        folded = name.casefold()
        if folded == credential or folded in CREDENTIAL_ALIASES:
            raise RequestError("CREDENTIAL_PARAM", "a credential parameter is never part of a request")
    known = {p.name: p for p in spec.params}
    for name in params:
        if name not in known:
            raise RequestError("UNKNOWN_PARAM", name)
    for param in spec.params:
        if param.required and param.name not in params:
            raise RequestError("MISSING_PARAM", param.name)
    query = sorted((name, _render_param(known[name], value)) for name, value in params.items())
    return CanonicalRequest(role=spec.role, method=spec.method, scheme=spec.scheme,
                            host=spec.host, path=spec.path, query=tuple(query),
                            headers=tuple(sorted(FIXED_HEADERS)), api_version=spec.api_version)
