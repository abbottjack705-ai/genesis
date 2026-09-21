"""Protected-evaluation interfaces and an intentionally small local skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Iterable, Protocol

from .labels import DecisionFrame, FutureOutcomeLabel
from .reasons import ReasonCode
from .repro import canonical_json, sha256_bytes
from .time import parse_utc


class ProtectedEvaluationError(PermissionError):
    pass


@dataclass(frozen=True)
class EvaluationRequest:
    campaign_id: str
    strategy_id: str
    strategy_digest: str
    dataset_version: str
    rules_digest: str


@dataclass(frozen=True)
class EvaluationCertificate:
    campaign_id: str
    strategy_id: str
    strategy_digest: str
    dataset_version: str
    rules_digest: str
    metrics: dict[str, str]
    n_observations: int
    issued_at: str
    raw_labels_exposed: bool = False

    @property
    def certificate_digest(self) -> str:
        return sha256_bytes(canonical_json(self.__dict__))


class ResearchStrategy(Protocol):
    def __call__(self, frame: DecisionFrame) -> Decimal:
        """Return a probability using only the supplied decision frame."""


class ProtectedEvaluationService:
    """In-process contract skeleton for a future isolated evaluator.

    The production implementation must run in a separate process/service with
    a one-way result channel.  Even this skeleton keeps labels in a private
    closure and passes only DecisionFrame objects to research code.
    """

    def __init__(
        self,
        frames: Iterable[DecisionFrame],
        labels: Iterable[FutureOutcomeLabel],
    ):
        self._frames = tuple(frames)
        self.__labels = tuple(labels)
        if len(self._frames) != len(self.__labels):
            raise ValueError("protected frames and labels must align")
        for frame, label in zip(self._frames, self.__labels):
            if frame.entity_id != label.entity_id:
                raise ValueError("protected labels do not align to decision entities")
            if parse_utc(label.observed_at) <= parse_utc(frame.decision_at):
                raise ValueError("protected outcome label is not future to its decision")

    def run(self, request: EvaluationRequest, strategy: ResearchStrategy) -> EvaluationCertificate:
        predictions: list[Decimal] = []
        for frame in self._frames:
            prediction = Decimal(strategy(frame))
            if not 0 <= prediction <= 1:
                raise ProtectedEvaluationError("strategy returned probability outside [0, 1]")
            predictions.append(prediction)

        # The label vault is only read here, after the strategy has returned.
        # No label object is passed through the strategy callback.
        brier = sum(
            (prediction - Decimal(str(label.outcome_value))) ** 2
            for prediction, label in zip(predictions, self.__labels)
        ) / Decimal(len(predictions) or 1)
        issued_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return EvaluationCertificate(
            campaign_id=request.campaign_id,
            strategy_id=request.strategy_id,
            strategy_digest=request.strategy_digest,
            dataset_version=request.dataset_version,
            rules_digest=request.rules_digest,
            metrics={"brier": format(brier, "f")},
            n_observations=len(predictions),
            issued_at=issued_at,
        )
