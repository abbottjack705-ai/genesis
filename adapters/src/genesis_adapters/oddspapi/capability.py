"""Capability rows adapter runtime code may write: fail-safe downgrades only (design 13.3, 16, G-03).

Adapter runtime code may register a market-book source as ``UNKNOWN`` (G2R capture, nothing consumable)
or ``BLOCKED`` (a derivation-source change at ``T_fix``, 401/403, a secret echo). It can never make a
source READY: that is an operator action through the CLI after a G3 record, so no status other than
``BLOCKED`` or ``UNKNOWN`` can be written here.
"""

from __future__ import annotations

from genesis.pit import OperationalStatus, SourceCapability, SourceCapabilityRegistry
from genesis.repro import canonical_json, sha256_bytes

from genesis_adapters.oddspapi.endpoints import PROVIDER_ID

MARKET_BOOK_PREFIX = "oddspapi.v4.soccer.market_book."
_DOWNGRADES = (OperationalStatus.BLOCKED, OperationalStatus.UNKNOWN)
_DEFAULTS = {"provider": PROVIDER_ID, "access_method": "rest_pregame_v4", "cost_tier": "unknown",
             "entitlement_class": "unknown", "historical_availability_class": "none",
             "point_in_time_reliability": "unverified", "revision_behaviour": "append_only_supersede",
             "coverage": "unknown", "rate_quota_limits": "unknown", "schema_version": "v1"}
_DESCRIPTIVE = tuple(_DEFAULTS)


class CapabilityDowngradeError(ValueError):
    """An attempt to write anything but a BLOCKED or UNKNOWN row from adapter runtime code."""


def _version(source_id: str, status: OperationalStatus, at: str, reason: str) -> str:
    digest = sha256_bytes(canonical_json({"source_id": source_id, "status": status.value, "at": at,
                                          "reason": reason}))
    return f"{source_id[len(MARKET_BOOK_PREFIX):] if source_id.startswith(MARKET_BOOK_PREFIX) else source_id}" \
           f"-{status.value}-{digest[:16]}"


def register_downgrade(capabilities: SourceCapabilityRegistry, source_id: str, *, status: OperationalStatus,
                       at: str, reason: str) -> str:
    """Append a BLOCKED or UNKNOWN row for ``source_id`` at the trusted time ``at``.

    The descriptive fields are copied from the source's latest row (or neutral ``unknown`` values for a
    new source) with ``point_in_time_reliability`` forced to ``unverified``, so the row can never read as
    ready whatever its status. The frozen registry refuses a row whose ``recorded_at`` does not advance.
    """

    if status not in _DOWNGRADES:
        raise CapabilityDowngradeError("adapter runtime code may only register BLOCKED or UNKNOWN rows")
    history = capabilities.history(source_id)
    fields = dict(_DEFAULTS)
    if history:
        latest = history[-1].to_dict()
        fields.update({name: latest[name] for name in _DESCRIPTIVE})
    fields["point_in_time_reliability"] = "unverified"
    capability = SourceCapability(source_id=source_id, operational_status=status, recorded_at=at,
                                  version=_version(source_id, status, at, reason), **fields)
    return capabilities.register(capability)


def market_book_sources(capabilities: SourceCapabilityRegistry) -> tuple[str, ...]:
    return tuple(sorted({row["source_id"] for row in capabilities.log.records()
                         if row.get("record_type") == "source_capability_registered"
                         and str(row.get("source_id", "")).startswith(MARKET_BOOK_PREFIX)}))


def block_market_book_sources(capabilities: SourceCapabilityRegistry, *, at: str, reason: str,
                              also: tuple[str, ...] = ()) -> tuple[str, ...]:
    """BLOCK every known market-book source (and ``also``) at ``at`` - the 401/403 and secret-echo response."""

    blocked = []
    for source_id in sorted(set(market_book_sources(capabilities)) | set(also)):
        register_downgrade(capabilities, source_id, status=OperationalStatus.BLOCKED, at=at, reason=reason)
        blocked.append(source_id)
    return tuple(blocked)
