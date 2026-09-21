"""Versioned, deterministic V0.4 policy primitives.

These values are policy guardrails, not discovered betting results.  In
particular, the near-fair tolerance is deliberately labelled provisional and
must be validated prospectively before it can be treated as evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .accounting import BetSide
from .repro import canonical_json, sha256_bytes


V04_POLICY_VERSION = "genesis-policy-v0.4-starting"


def _decimal(value: Decimal | str | int | float) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class OddsProfile:
    name: str
    minimum: Decimal
    maximum: Decimal
    exceptional: bool = False

    def __post_init__(self) -> None:
        if self.minimum <= 1 or self.minimum > self.maximum:
            raise ValueError("invalid decimal odds profile")

    def contains(self, odds: Decimal | str | int | float) -> bool:
        value = _decimal(odds)
        return self.minimum <= value <= self.maximum


@dataclass(frozen=True)
class DailySearchAim:
    day: str
    minimum: int
    maximum: int
    is_quota: bool = False
    is_cap: bool = False

    def __post_init__(self) -> None:
        if self.minimum < 0 or self.maximum < self.minimum:
            raise ValueError("invalid daily search aim")
        if self.is_quota or self.is_cap:
            raise ValueError("V0.4 daily ranges are neither quotas nor caps")


@dataclass(frozen=True)
class RiskPolicy:
    version: str = "genesis-risk-v0.4-starting"
    unit_fraction: Decimal = Decimal("0.025")
    stake_tiers: tuple[Decimal, ...] = (
        Decimal("1.0"),
        Decimal("1.5"),
        Decimal("2.0"),
        Decimal("2.5"),
        Decimal("3.0"),
    )
    max_single_units: Decimal = Decimal("3.0")
    max_open_liability_fraction: Decimal = Decimal("0.60")
    correlated_cluster_fraction: Decimal = Decimal("0.125")
    daily_turnover_cap: Decimal | None = None
    downward_rebase_trigger: Decimal | None = None
    status: str = "STARTING_POLICY_NOT_EMPIRICALLY_VALIDATED"

    def __post_init__(self) -> None:
        if not 0 < self.unit_fraction < 1:
            raise ValueError("unit fraction must be in (0, 1)")
        if not self.stake_tiers or tuple(sorted(self.stake_tiers)) != self.stake_tiers:
            raise ValueError("stake tiers must be sorted and non-empty")
        if self.max_single_units not in self.stake_tiers:
            raise ValueError("maximum single stake must be a declared tier")
        for fraction in (self.max_open_liability_fraction, self.correlated_cluster_fraction):
            if not 0 < fraction <= 1:
                raise ValueError("risk fractions must be in (0, 1]")
        if self.daily_turnover_cap is not None:
            raise ValueError("V0.4 has no cumulative daily turnover cap")

    def stake_amount(self, bankroll: Decimal | str | int | float, units: Decimal | str | int | float) -> Decimal:
        unit = _decimal(units)
        if unit not in self.stake_tiers:
            raise ValueError("stake must use a declared unit tier")
        amount = _decimal(bankroll) * self.unit_fraction * unit
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def default_daily_aims() -> tuple[DailySearchAim, ...]:
    return (
        DailySearchAim("monday_thursday", 2, 5),
        DailySearchAim("friday", 4, 10),
        DailySearchAim("saturday", 7, 13),
        DailySearchAim("sunday", 4, 10),
    )


@dataclass(frozen=True)
class PolicySet:
    version: str = V04_POLICY_VERSION
    normal_odds: OddsProfile = OddsProfile("normal", Decimal("1.50"), Decimal("3.00"))
    exceptional_odds: OddsProfile = OddsProfile("exceptional_short_price", Decimal("1.40"), Decimal("1.49"), True)
    near_fair_tolerance: Decimal = Decimal("0.02")
    risk: RiskPolicy = RiskPolicy()
    daily_aims: tuple[DailySearchAim, ...] = default_daily_aims()
    live_enabled_by_default: bool = False
    status: str = "STARTING_POLICY_NOT_EMPIRICALLY_VALIDATED"

    def __post_init__(self) -> None:
        if self.near_fair_tolerance < 0 or self.near_fair_tolerance > 1:
            raise ValueError("near-fair tolerance must be in [0, 1]")
        if self.live_enabled_by_default:
            raise ValueError("foundation policy cannot enable live mode")

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json(self.to_dict(include_digest=False)))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        value = asdict(self)
        value["normal_odds"]["minimum"] = str(self.normal_odds.minimum)
        value["normal_odds"]["maximum"] = str(self.normal_odds.maximum)
        value["exceptional_odds"]["minimum"] = str(self.exceptional_odds.minimum)
        value["exceptional_odds"]["maximum"] = str(self.exceptional_odds.maximum)
        value["near_fair_tolerance"] = str(self.near_fair_tolerance)
        value["risk"]["unit_fraction"] = str(self.risk.unit_fraction)
        value["risk"]["stake_tiers"] = [str(item) for item in self.risk.stake_tiers]
        value["risk"]["max_single_units"] = str(self.risk.max_single_units)
        value["risk"]["max_open_liability_fraction"] = str(self.risk.max_open_liability_fraction)
        value["risk"]["correlated_cluster_fraction"] = str(self.risk.correlated_cluster_fraction)
        if self.risk.downward_rebase_trigger is not None:
            value["risk"]["downward_rebase_trigger"] = str(self.risk.downward_rebase_trigger)
        if include_digest:
            value["policy_digest"] = self.digest
        return value

    def daily_aim(self, day: date) -> DailySearchAim:
        if day.weekday() <= 3:
            return self.daily_aims[0]
        if day.weekday() == 4:
            return self.daily_aims[1]
        if day.weekday() == 5:
            return self.daily_aims[2]
        return self.daily_aims[3]


def break_even_probability(
    odds: Decimal | str | int | float,
    *,
    commission_rate: Decimal | str | int | float = 0,
    side: BetSide = BetSide.BACK,
) -> Decimal:
    """Return the venue-neutral break-even probability for a simple bet.

    Commission is charged on positive winnings.  Venue-specific rules must
    provide a specialised implementation before a market is activated.
    """

    odds_value = _decimal(odds)
    commission = _decimal(commission_rate)
    if odds_value <= 1 or not 0 <= commission < 1:
        raise ValueError("invalid odds or commission")
    if side == BetSide.BACK:
        return Decimal(1) / (Decimal(1) + (odds_value - Decimal(1)) * (Decimal(1) - commission))
    return (Decimal(1) - commission) / ((Decimal(1) - commission) + odds_value - Decimal(1))


@dataclass(frozen=True)
class PriceSanityResult:
    eligible_profile: bool
    profile: str
    break_even: Decimal
    margin: Decimal
    passed: bool
    near_fair_tolerance_used: bool
    reason: str
    provisional: bool = True


def assess_price_sanity(
    *,
    odds: Decimal | str | int | float,
    model_probability: Decimal | str | int | float,
    commission_rate: Decimal | str | int | float = 0,
    side: BetSide = BetSide.BACK,
    policy: PolicySet | None = None,
    strong_conditions: bool = False,
    other_soft_concern: bool = False,
) -> PriceSanityResult:
    active = policy or PolicySet()
    odds_value = _decimal(odds)
    probability = _decimal(model_probability)
    if not 0 <= probability <= 1:
        raise ValueError("model probability must be in [0, 1]")
    profile = "normal" if active.normal_odds.contains(odds_value) else (
        "exceptional_short_price" if active.exceptional_odds.contains(odds_value) else "outside"
    )
    break_even = break_even_probability(odds_value, commission_rate=commission_rate, side=side)
    margin = probability - break_even
    if profile == "outside":
        return PriceSanityResult(False, profile, break_even, margin, False, False, "odds_outside_profile")
    if profile == "exceptional_short_price" and margin < 0:
        return PriceSanityResult(True, profile, break_even, margin, False, False, "exceptional_negative_margin")
    if margin >= 0:
        return PriceSanityResult(True, profile, break_even, margin, True, False, "non_negative_margin")
    tolerance_used = margin >= -active.near_fair_tolerance
    passed = profile == "normal" and tolerance_used and strong_conditions and not other_soft_concern
    return PriceSanityResult(
        True,
        profile,
        break_even,
        margin,
        passed,
        passed,
        "near_fair_tolerance" if passed else "negative_margin_without_strong_conditions",
    )

