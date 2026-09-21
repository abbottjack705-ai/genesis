"""Versioned deterministic configuration and dependency-lock checks."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import StrEnum
from pathlib import Path
from typing import Any

from .repro import canonical_json, sha256_bytes


class OperationalMode(StrEnum):
    OFFLINE_RESEARCH = "offline_research"
    SHADOW = "shadow"
    PAPER = "paper"
    MICRO_LIVE = "micro_live"
    LIVE = "live"
    DISABLED = "disabled"
    KILL_SWITCH_ACTIVE = "kill_switch_active"


@dataclass(frozen=True)
class GenesisConfig:
    config_version: str
    mode: OperationalMode
    live_enabled: bool
    allowed_sports: tuple[str, ...]
    odds_profile: str
    commission_rate: str
    max_daily_stake: str
    max_bets_per_day: int
    dependencies_lock_digest: str
    policy_version: str = "genesis-policy-v0.4-starting"
    daily_targets_are_quota: bool = False
    daily_targets_are_cap: bool = False

    def __post_init__(self) -> None:
        if self.live_enabled and self.mode not in {OperationalMode.MICRO_LIVE, OperationalMode.LIVE}:
            raise ValueError("live_enabled requires an explicit live mode")
        if self.mode in {OperationalMode.OFFLINE_RESEARCH, OperationalMode.SHADOW, OperationalMode.PAPER} and self.live_enabled:
            raise ValueError("non-live modes cannot enable live betting")
        if self.max_bets_per_day < 0:
            raise ValueError("max_bets_per_day cannot be negative")
        if self.daily_targets_are_quota or self.daily_targets_are_cap:
            raise ValueError("V0.4 daily search ranges are not quotas or caps")

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json(asdict(self) | {"mode": self.mode.value}))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"mode": self.mode.value, "config_digest": self.digest}


def load_config(path: str | Path, dependencies_lock_digest: str) -> GenesisConfig:
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("dependencies_lock_digest") != dependencies_lock_digest:
        raise ValueError("configuration is not pinned to the dependency lock")
    return GenesisConfig(
        config_version=data["config_version"],
        mode=OperationalMode(data["mode"]),
        live_enabled=bool(data["live_enabled"]),
        allowed_sports=tuple(data["allowed_sports"]),
        odds_profile=data["odds_profile"],
        commission_rate=str(data["commission_rate"]),
        max_daily_stake=str(data["max_daily_stake"]),
        max_bets_per_day=int(data["max_bets_per_day"]),
        dependencies_lock_digest=data["dependencies_lock_digest"],
        policy_version=str(data.get("policy_version", "genesis-policy-v0.4-starting")),
        daily_targets_are_quota=bool(data.get("daily_targets_are_quota", False)),
        daily_targets_are_cap=bool(data.get("daily_targets_are_cap", False)),
    )
