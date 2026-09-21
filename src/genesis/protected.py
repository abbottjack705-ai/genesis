"""Protected-evaluation controls layered around the local evaluator skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .evaluation import EvaluationCertificate, EvaluationRequest, ProtectedEvaluationError, ProtectedEvaluationService, ResearchStrategy
from .labels import DecisionFrame, FutureOutcomeLabel
from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, sha256_bytes


@dataclass(frozen=True)
class ProtectedCampaign:
    campaign_id: str
    family_id: str
    max_attempts: int
    evaluator_digest: str
    minimum_cell_size: int = 5

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.family_id or len(self.evaluator_digest) != 64:
            raise ValueError("protected campaign identity is invalid")
        if self.max_attempts <= 0 or self.minimum_cell_size <= 0:
            raise ValueError("protected campaign limits must be positive")


class ProtectedAttemptLedger:
    """Monotonic attempt accounting; reservation happens before execution."""

    def __init__(self, path: str | Path | None = None):
        self.log = AppendOnlyJsonl(path) if path is not None else None
        self._campaign_attempts: dict[str, int] = {}
        self._family_attempts: dict[str, int] = {}
        if self.log is not None:
            for row in self.log.records():
                if row.get("record_type") == "protected_attempt_reserved":
                    self._campaign_attempts[row["campaign_id"]] = row["campaign_attempt"]
                    self._family_attempts[row["family_id"]] = row["family_attempt"]

    def reserve(self, campaign: ProtectedCampaign, *, family_limit: int | None = None, note: str = "") -> int:
        campaign_attempt = self._campaign_attempts.get(campaign.campaign_id, 0)
        family_attempt = self._family_attempts.get(campaign.family_id, 0)
        if campaign_attempt >= campaign.max_attempts:
            raise RegistryConflict("protected campaign attempt budget exhausted")
        if family_limit is not None and family_attempt >= family_limit:
            raise RegistryConflict("protected family attempt budget exhausted")
        campaign_attempt += 1
        family_attempt += 1
        self._campaign_attempts[campaign.campaign_id] = campaign_attempt
        self._family_attempts[campaign.family_id] = family_attempt
        if self.log is not None:
            self.log.append(
                {
                    "record_type": "protected_attempt_reserved",
                    "campaign_id": campaign.campaign_id,
                    "family_id": campaign.family_id,
                    "campaign_attempt": campaign_attempt,
                    "family_attempt": family_attempt,
                    "note": note,
                }
            )
        return campaign_attempt


class ProtectedEvaluationBoundary:
    """A fail-closed interface with no label-bearing callback or debug channel."""

    def __init__(
        self,
        campaign: ProtectedCampaign,
        frames: Iterable[DecisionFrame],
        labels: Iterable[FutureOutcomeLabel],
        attempts: ProtectedAttemptLedger,
        *,
        family_limit: int | None = None,
    ):
        self.campaign = campaign
        self._service = ProtectedEvaluationService(frames, labels)
        self._attempts = attempts
        self._family_limit = family_limit

    def run(self, request: EvaluationRequest, strategy: ResearchStrategy) -> EvaluationCertificate:
        if request.campaign_id != self.campaign.campaign_id:
            raise ProtectedEvaluationError("protected request rejected")
        if request.rules_digest != self.campaign.evaluator_digest:
            raise ProtectedEvaluationError("protected evaluator version mismatch")
        self._attempts.reserve(self.campaign, family_limit=self._family_limit, note=request.strategy_id)
        if self._service._frames and len(self._service._frames) < self.campaign.minimum_cell_size:
            return EvaluationCertificate(
                campaign_id=request.campaign_id,
                strategy_id=request.strategy_id,
                strategy_digest=request.strategy_digest,
                dataset_version=request.dataset_version,
                rules_digest=request.rules_digest,
                metrics={"suppressed": "true"},
                n_observations=0,
                issued_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )
        try:
            return self._service.run(request, strategy)
        except Exception as exc:
            # The caller receives no evaluator internals, labels, or stack
            # details.  The reservation remains consumed.
            raise ProtectedEvaluationError("protected evaluation failed") from exc
