"""Deterministic decimal odds, exposure, and settlement arithmetic."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum


MONEY_QUANTUM = Decimal("0.01")


def money(value: Decimal | str | int | float) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def decimal_odds(value: Decimal | str | int | float) -> Decimal:
    odds = Decimal(str(value))
    if odds <= 1:
        raise ValueError("decimal odds must be greater than 1")
    return odds


def implied_probability(odds: Decimal | str | int | float) -> Decimal:
    return Decimal(1) / decimal_odds(odds)


class BetSide(StrEnum):
    BACK = "back"
    LAY = "lay"


class SettlementKind(StrEnum):
    WIN = "win"
    LOSS = "loss"
    VOID = "void"
    NON_RUNNER = "non_runner"
    DEAD_HEAT = "dead_heat"


@dataclass(frozen=True)
class MatchedFragment:
    fragment_id: str
    side: BetSide
    odds: Decimal
    stake: Decimal

    def __post_init__(self) -> None:
        decimal_odds(self.odds)
        if self.stake <= 0:
            raise ValueError("matched stake must be positive")

    @property
    def liability(self) -> Decimal:
        return self.stake * (self.odds - 1) if self.side == BetSide.LAY else self.stake


@dataclass(frozen=True)
class Settlement:
    kind: SettlementKind
    pnl: Decimal
    returned_stake: Decimal
    commission: Decimal


def _commission(gross_positive: Decimal, rate: Decimal) -> Decimal:
    if rate < 0 or rate >= 1:
        raise ValueError("commission rate must be in [0, 1)")
    return gross_positive * rate


def settle_back(
    stake: Decimal | str | int | float,
    odds: Decimal | str | int | float,
    kind: SettlementKind,
    *,
    commission_rate: Decimal | str | int | float = 0,
    dead_heat_fraction: Decimal | str | int | float = 1,
) -> Settlement:
    stake = money(stake)
    odds = decimal_odds(odds)
    rate = Decimal(str(commission_rate))
    fraction = Decimal(str(dead_heat_fraction))
    if stake <= 0 or not 0 < fraction <= 1:
        raise ValueError("stake and dead-heat fraction must be positive")
    if kind in {SettlementKind.VOID, SettlementKind.NON_RUNNER}:
        return Settlement(kind, Decimal("0.00"), stake, Decimal("0.00"))
    if kind == SettlementKind.LOSS:
        return Settlement(kind, -stake, Decimal("0.00"), Decimal("0.00"))
    gross = stake * (odds - 1) * (fraction if kind == SettlementKind.DEAD_HEAT else 1)
    commission = _commission(gross, rate)
    return Settlement(kind, money(gross - commission), money(stake + gross - commission), money(commission))


def settle_lay(
    stake: Decimal | str | int | float,
    odds: Decimal | str | int | float,
    kind: SettlementKind,
    *,
    commission_rate: Decimal | str | int | float = 0,
) -> Settlement:
    stake = money(stake)
    odds = decimal_odds(odds)
    rate = Decimal(str(commission_rate))
    if stake <= 0:
        raise ValueError("stake must be positive")
    if kind in {SettlementKind.VOID, SettlementKind.NON_RUNNER}:
        return Settlement(kind, Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))
    if kind == SettlementKind.WIN:
        liability = stake * (odds - 1)
        return Settlement(kind, money(-liability), Decimal("0.00"), Decimal("0.00"))
    if kind == SettlementKind.DEAD_HEAT:
        raise ValueError("lay dead-heat settlement requires an explicit market rule")
    gross = stake
    commission = _commission(gross, rate)
    return Settlement(kind, money(gross - commission), money(stake + gross - commission), money(commission))


def expected_value(probability: Decimal | str | int | float, odds: Decimal | str | int | float) -> Decimal:
    probability = Decimal(str(probability))
    if not 0 <= probability <= 1:
        raise ValueError("probability must be in [0, 1]")
    return probability * (decimal_odds(odds) - 1) - (1 - probability)

