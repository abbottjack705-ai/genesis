"""Deterministic PASS-first qualification interface; no execution side effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from .canonical import CandidateBet
from .reasons import ReasonCode
from .time import parse_utc


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    reason: ReasonCode | None = None


@dataclass(frozen=True)
class SelectionDecision:
    candidate_id: str
    action: str
    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return self.action == "QUALIFY"

    @property
    def reason_codes(self) -> tuple[ReasonCode, ...]:
        return tuple(g.reason for g in self.gates if g.reason is not None)

    @property
    def final_reason(self) -> ReasonCode:
        return ReasonCode.QUALIFY_ALL_GATES_PASSED if self.passed else self.reason_codes[0]


@dataclass(frozen=True)
class QualificationFacts:
    """Explicit gate facts; None is UNKNOWN and therefore fails closed."""

    source_ready: bool | None = None
    identity_unambiguous: bool | None = None
    model_supported: bool | None = None
    calibration_supported: bool | None = None
    evidence_pack_frozen: bool | None = None
    evidence_reproducible: bool | None = None
    critical_evidence_fresh: bool | None = None
    no_contradiction: bool | None = None
    uncertainty_supported: bool | None = None
    odds_profile_ok: bool | None = None
    price_sanity_ok: bool | None = None
    liquidity_ok: bool | None = None
    risk_ok: bool | None = None
    correlation_ok: bool | None = None
    execution_available: bool | None = None
    strategy_approved: bool | None = None
    no_duplicate_order: bool | None = None
    no_kill_condition: bool | None = None


def _gate(name: str, value: bool | None, reason: ReasonCode) -> GateResult:
    if value is True:
        return GateResult(name, True, None)
    return GateResult(name, False, ReasonCode.PASS_UNKNOWN_STATE if value is None else reason)


def qualify_v04(candidate: CandidateBet, *, now: str, facts: QualificationFacts) -> SelectionDecision:
    """Run the V0.4 ordered fail-closed gate set without side effects."""

    expired = parse_utc(now) > parse_utc(candidate.expires_at)
    gates = (
        _gate("strategy_approved", facts.strategy_approved, ReasonCode.PASS_STRATEGY_NOT_APPROVED),
        _gate("source_ready", facts.source_ready, ReasonCode.PASS_DATA_CAPABILITY_NOT_READY),
        _gate("identity_unambiguous", facts.identity_unambiguous, ReasonCode.PASS_IDENTITY_AMBIGUOUS),
        _gate("model_supported", facts.model_supported, ReasonCode.PASS_MODEL_OUT_OF_SUPPORT),
        _gate("calibration_supported", facts.calibration_supported, ReasonCode.PASS_CALIBRATION_UNSUPPORTED),
        _gate("evidence_pack_frozen", facts.evidence_pack_frozen, ReasonCode.PASS_MISSING_EVIDENCE),
        _gate("evidence_reproducible", facts.evidence_reproducible, ReasonCode.PASS_GATE_ERROR),
        _gate("critical_evidence_fresh", facts.critical_evidence_fresh, ReasonCode.PASS_STALE_EVIDENCE),
        _gate("no_contradiction", facts.no_contradiction, ReasonCode.PASS_CONTRADICTION),
        _gate("uncertainty_supported", facts.uncertainty_supported, ReasonCode.PASS_CRITICAL_UNCERTAINTY),
        _gate("odds_profile_ok", facts.odds_profile_ok, ReasonCode.PASS_ODDS_OUTSIDE_PROFILE),
        _gate("price_sanity_ok", facts.price_sanity_ok, ReasonCode.PASS_PRICE_SANITY_FAIL),
        _gate("liquidity_ok", facts.liquidity_ok, ReasonCode.PASS_LIQUIDITY_FAIL),
        _gate("risk_ok", facts.risk_ok, ReasonCode.PASS_RISK_LIMIT),
        _gate("correlation_ok", facts.correlation_ok, ReasonCode.PASS_CORRELATION_LIMIT),
        _gate("execution_available", facts.execution_available, ReasonCode.PASS_EXECUTION_UNAVAILABLE),
        _gate("no_duplicate_order", facts.no_duplicate_order, ReasonCode.PASS_UNKNOWN_STATE),
        _gate("no_kill_condition", facts.no_kill_condition, ReasonCode.PASS_RISK_LIMIT),
        GateResult("candidate_not_expired", not expired, None if not expired else ReasonCode.PASS_EXPIRED_CANDIDATE),
    )
    passed = all(gate.passed for gate in gates)
    return SelectionDecision(candidate.candidate_id, "QUALIFY" if passed else "PASS", gates)


def qualify(
    candidate: CandidateBet,
    *,
    now: str,
    market_supported: bool,
    strategy_approved: bool,
    model_supported: bool,
    evidence_fresh: bool,
    price_sane: bool,
    execution_available: bool,
    risk_approved: bool,
) -> SelectionDecision:
    """Evaluate hard gates and return QUALIFY or PASS.

    This function never submits an order and never changes configuration.  It
    accepts explicit gate facts so later services cannot smuggle in hidden
    defaults or an LLM-generated override.
    """

    gates = (
        GateResult("market_supported", market_supported, None if market_supported else ReasonCode.UNSUPPORTED_MARKET),
        GateResult("strategy_approved", strategy_approved, None if strategy_approved else ReasonCode.STRATEGY_NOT_APPROVED),
        GateResult("model_supported", model_supported, None if model_supported else ReasonCode.MODEL_UNSUPPORTED),
        GateResult("evidence_fresh", evidence_fresh, None if evidence_fresh else ReasonCode.STALE_EVIDENCE),
        GateResult("decision_not_expired", parse_utc(now) <= parse_utc(candidate.expires_at), None if parse_utc(now) <= parse_utc(candidate.expires_at) else ReasonCode.EXPIRED),
        GateResult("price_sane", price_sane, None if price_sane else ReasonCode.PRICE_SANITY_FAILED),
        GateResult("execution_available", execution_available, None if execution_available else ReasonCode.EXECUTION_UNAVAILABLE),
        GateResult("risk_approved", risk_approved, None if risk_approved else ReasonCode.RISK_REJECTED),
        GateResult("evidence_complete", candidate.evidence_complete, None if candidate.evidence_complete else ReasonCode.MISSING_EVIDENCE),
        GateResult("no_critical_uncertainty", not candidate.critical_uncertainty_flags, None if not candidate.critical_uncertainty_flags else ReasonCode.CRITICAL_UNCERTAINTY),
    )
    return SelectionDecision(candidate.candidate_id, "QUALIFY" if all(g.passed for g in gates) else "PASS", gates)


def rank_qualified(candidates: Iterable[tuple[CandidateBet, SelectionDecision]]) -> list[CandidateBet]:
    qualified = [candidate for candidate, decision in candidates if decision.passed]

    def tier(candidate: CandidateBet) -> Decimal:
        if candidate.strategy_tier is None:
            return Decimal("0")
        try:
            return Decimal(candidate.strategy_tier.rstrip("u"))
        except (ValueError, ArithmeticError):
            return Decimal("0")

    def region(candidate: CandidateBet) -> tuple[int, str]:
        odds = Decimal(candidate.observed_odds)
        if Decimal("1.40") <= odds <= Decimal("1.49"):
            return (0, "exceptional_short_price")
        if Decimal("1.50") <= odds <= Decimal("3.00"):
            return (1, "normal")
        return (2, "outside")

    return sorted(
        qualified,
        key=lambda candidate: (
            -tier(candidate),
            region(candidate),
            candidate.market_family or candidate.market_id,
            -Decimal(candidate.conservative_probability),
            candidate.selection_dependency_group or "",
            candidate.candidate_id,
        ),
    )
