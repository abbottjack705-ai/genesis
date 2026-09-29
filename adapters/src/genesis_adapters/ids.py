"""Deterministic, domain-separated identities (design section 8.1)."""

from __future__ import annotations

import re

from genesis.repro import canonical_json, sha256_bytes

IDENTITY_DOMAIN = "genesis.adapters.identity.v1"
_KIND = re.compile(r"^[a-z]+$")
_NATIVE_STR = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class IdentityError(ValueError):
    """Invalid identity input."""

    code = "IDENTITY_ERROR"


class IdentityTypeError(IdentityError):
    """A native ID has the wrong JSON type or grammar (never coerced)."""

    code = "SCHEMA_REJECTED"


def gid(kind: str, **parts: object) -> str:
    """``kind:`` + full 64-hex SHA-256 over canonical JSON of (domain, kind, parts).

    The digest is never truncated and never delimiter-joined, so distinct part sets cannot
    collide by concatenation.
    """

    if type(kind) is not str or not _KIND.match(kind):
        raise IdentityError("identity kind must be lowercase letters")
    if not parts:
        raise IdentityError("identity needs at least one part")
    try:
        payload = canonical_json({"domain": IDENTITY_DOMAIN, "kind": kind, "parts": parts})
    except (TypeError, ValueError) as exc:
        raise IdentityError("identity parts are not JSON serializable") from None
    return f"{kind}:{sha256_bytes(payload)}"


def native_id(value: object, *, declared_type: str) -> dict:
    """Canonical provider-native ID: ``{"native_type", "value"}``. No coercion, ever."""

    if declared_type == "int":
        if type(value) is not int or value < 0:
            raise IdentityTypeError("declared int ID has another type or is negative")
        text = str(value)
    elif declared_type == "str":
        if type(value) is not str:
            raise IdentityTypeError("declared str ID has another type")
        text = value
    else:
        raise IdentityError("declared_type must be 'int' or 'str'")
    if not _NATIVE_STR.match(text):
        raise IdentityTypeError("native ID is outside the permitted grammar")
    return {"native_type": declared_type, "value": text}
