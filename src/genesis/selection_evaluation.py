"""Selection-policy evaluation records kept separate from research inputs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .repro import canonical_json, sha256_bytes


@dataclass(frozen=True)
class SelectionObservation:
    candidate_id: str
    predicted_probability: str
    outcome: int
    selected: bool
    qualified: bool
    odds_region: str
    support_region: str
    dependency_group: str | None = None
    pass_reason: str | None = None

    def __post_init__(self) -> None:
        probability = Decimal(self.predicted_probability)
        if not 0 <= probability <= 1 or self.outcome not in (0, 1):
            raise ValueError("invalid protected selection observation")


@dataclass(frozen=True)
class CalibrationSummary:
    population: str
    n_observations: int
    brier: str | None
    mean_prediction: str | None
    observed_rate: str | None
    suppressed: bool = False


@dataclass(frozen=True)
class SelectionEvaluationReport:
    policy_hash: str
    all_candidates: CalibrationSummary
    qualified_candidates: CalibrationSummary
    selected_candidates: CalibrationSummary
    pass_count: int
    pass_reasons: tuple[tuple[str, int], ...]
    dependence_groups: int

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json(self.to_dict()))

    def to_dict(self) -> dict:
        return {
            "policy_hash": self.policy_hash,
            "all_candidates": self.all_candidates.__dict__,
            "qualified_candidates": self.qualified_candidates.__dict__,
            "selected_candidates": self.selected_candidates.__dict__,
            "pass_count": self.pass_count,
            "pass_reasons": list(self.pass_reasons),
            "dependence_groups": self.dependence_groups,
        }


def _summary(name: str, observations: list[SelectionObservation], *, minimum_cell_size: int) -> CalibrationSummary:
    if len(observations) < minimum_cell_size:
        return CalibrationSummary(name, 0, None, None, None, suppressed=True)
    predictions = [Decimal(item.predicted_probability) for item in observations]
    outcomes = [Decimal(item.outcome) for item in observations]
    brier = sum(((prediction - outcome) ** 2 for prediction, outcome in zip(predictions, outcomes)), Decimal("0")) / Decimal(len(observations))
    mean_prediction = sum(predictions, Decimal("0")) / Decimal(len(predictions))
    observed_rate = sum(outcomes, Decimal("0")) / Decimal(len(outcomes))
    return CalibrationSummary(name, len(observations), format(brier, "f"), format(mean_prediction, "f"), format(observed_rate, "f"))


def evaluate_selection_policy(
    observations: Iterable[SelectionObservation],
    *,
    policy_hash: str,
    minimum_cell_size: int = 5,
) -> SelectionEvaluationReport:
    """Evaluate all, qualified, and selected populations on one frozen policy.

    The caller is the trusted evaluation boundary.  The returned report has
    aggregates only; individual outcomes are not returned to research code.
    """

    if len(policy_hash) != 64:
        raise ValueError("policy_hash must be a SHA-256 digest")
    rows = list(observations)
    all_rows = rows
    qualified = [row for row in rows if row.qualified]
    selected = [row for row in rows if row.selected]
    reasons: dict[str, int] = {}
    for row in rows:
        if not row.selected and row.pass_reason:
            reasons[row.pass_reason] = reasons.get(row.pass_reason, 0) + 1
    groups = {row.dependency_group for row in rows if row.dependency_group is not None}
    return SelectionEvaluationReport(
        policy_hash=policy_hash,
        all_candidates=_summary("all_candidates", all_rows, minimum_cell_size=minimum_cell_size),
        qualified_candidates=_summary("qualified_candidates", qualified, minimum_cell_size=minimum_cell_size),
        selected_candidates=_summary("selected_candidates", selected, minimum_cell_size=minimum_cell_size),
        pass_count=len(rows) - len(selected),
        pass_reasons=tuple(sorted(reasons.items())),
        dependence_groups=len(groups),
    )


@dataclass(frozen=True)
class PassAblationRequest:
    request_id: str
    policy_hash: str
    gate_name: str
    neighbourhood_definition: str
    protected_campaign_id: str

    def __post_init__(self) -> None:
        if not self.request_id or len(self.policy_hash) != 64 or not self.gate_name or not self.protected_campaign_id:
            raise ValueError("PASS ablation request is incomplete")
