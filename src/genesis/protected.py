"""Isolated protected evaluation with sealed frames and durable attempts."""

from __future__ import annotations

import importlib
import inspect
import json
import multiprocessing
import os
import queue
import secrets
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, BinaryIO, Iterable

from .evaluation import (
    EvaluationCertificate,
    EvaluationRequest,
    LegacyInProcessEvaluationHarness,
    ProtectedEvaluationError,
    ResearchStrategy,
)
from .labels import DecisionFrame, FutureOutcomeLabel
from .registry import AppendOnlyJsonl, ExperimentRegistry, RegistryConflict
from .repro import canonical_json, sha256_bytes, sha256_file
from .time import iso_utc, parse_utc


CAMPAIGN_SCHEMA = "protected-campaign-v2"
ATTEMPT_SCHEMA = "protected-attempt-v2"
FRAME_MANIFEST_SCHEMA = "sealed-frame-manifest-v1"
PREDICTION_ARTIFACT_SCHEMA = "frozen-predictions-v1"
RESEARCH_PROGRAM_SCHEMA = "research-program-ref-v1"
RESEARCH_PROGRAM_DOMAIN = "genesis.protected-research-program.v1"
RESEARCH_LAUNCH_SCHEMA = "protected-research-launch-v1"
RESEARCH_BOUNDARY_SCHEMA = "protected-research-boundary-v1"
MAX_IPC_BYTES = 1_000_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SealedFrameSet:
    campaign_id: str
    dataset_version: str
    frames: tuple[DecisionFrame, ...]
    frame_ids: tuple[str, ...]
    frame_hashes: tuple[str, ...]
    frame_manifest_hash: str
    schema_version: str = FRAME_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != FRAME_MANIFEST_SCHEMA:
            raise ValueError("unsupported sealed frame manifest schema")
        if not self.campaign_id or not self.dataset_version or not self.frames:
            raise ValueError("sealed frame identity/material is incomplete")
        expected_ids = tuple(frame.decision_id for frame in self.frames)
        if len(set(expected_ids)) != len(expected_ids):
            raise ValueError("sealed frame IDs must be unique")
        if expected_ids != self.frame_ids:
            raise ValueError("sealed frame ID manifest mismatch")
        if any(frame.dataset_version != self.dataset_version for frame in self.frames):
            raise ValueError("sealed frame dataset version mismatch")
        expected_hashes = tuple(
            sha256_bytes(canonical_json(frame.to_dict())) for frame in self.frames
        )
        if expected_hashes != self.frame_hashes:
            raise ValueError("sealed frame content hash mismatch")
        if self.compute_hash() != self.frame_manifest_hash:
            raise ValueError("sealed frame manifest digest mismatch")

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "dataset_version": self.dataset_version,
            "frame_ids": list(self.frame_ids),
            "frame_hashes": list(self.frame_hashes),
        }

    def compute_hash(self) -> str:
        return sha256_bytes(canonical_json(self.manifest_dict()))

    @classmethod
    def create(
        cls,
        *,
        campaign_id: str,
        dataset_version: str,
        frames: Iterable[DecisionFrame],
    ) -> "SealedFrameSet":
        material = tuple(frames)
        frame_ids = tuple(frame.decision_id for frame in material)
        frame_hashes = tuple(
            sha256_bytes(canonical_json(frame.to_dict())) for frame in material
        )
        unsigned = {
            "schema_version": FRAME_MANIFEST_SCHEMA,
            "campaign_id": campaign_id,
            "dataset_version": dataset_version,
            "frame_ids": list(frame_ids),
            "frame_hashes": list(frame_hashes),
        }
        return cls(
            campaign_id,
            dataset_version,
            material,
            frame_ids,
            frame_hashes,
            sha256_bytes(canonical_json(unsigned)),
        )


@dataclass(frozen=True)
class FrozenPredictionArtifact:
    campaign_id: str
    dataset_version: str
    strategy_id: str
    strategy_digest: str
    frame_manifest_hash: str
    predictions: tuple[tuple[str, str], ...]
    artifact_hash: str
    schema_version: str = PREDICTION_ARTIFACT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PREDICTION_ARTIFACT_SCHEMA:
            raise ValueError("unsupported frozen prediction schema")
        if not self.campaign_id or not self.dataset_version or not self.strategy_id:
            raise ValueError("frozen prediction identity is incomplete")
        for name in ("strategy_digest", "frame_manifest_hash", "artifact_hash"):
            value = getattr(self, name)
            if len(value) != 64:
                raise ValueError(f"{name} must be SHA-256")
            int(value, 16)
        if not all(isinstance(item, tuple) and len(item) == 2 for item in self.predictions):
            raise ValueError("prediction rows are malformed")
        ids = [item[0] for item in self.predictions]
        if len(ids) != len(set(ids)) or any(not item for item in ids):
            raise ValueError("prediction frame IDs must be unique and non-empty")
        for _frame_id, probability in self.predictions:
            try:
                value = Decimal(probability)
            except InvalidOperation as exc:
                raise ValueError("prediction is not decimal") from exc
            if not value.is_finite() or not 0 <= value <= 1:
                raise ValueError("prediction must be finite and in [0, 1]")
        if self.compute_hash() != self.artifact_hash:
            raise ValueError("frozen prediction artifact digest mismatch")

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "dataset_version": self.dataset_version,
            "strategy_id": self.strategy_id,
            "strategy_digest": self.strategy_digest,
            "frame_manifest_hash": self.frame_manifest_hash,
            "predictions": [
                {"frame_id": frame_id, "probability": probability}
                for frame_id, probability in self.predictions
            ],
        }

    def compute_hash(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        return self.unsigned_dict() | {"artifact_hash": self.artifact_hash}

    @classmethod
    def create(
        cls,
        request: EvaluationRequest,
        frame_manifest_hash: str,
        predictions: dict[str, Decimal | str | int | float],
    ) -> "FrozenPredictionArtifact":
        normalized = tuple(
            sorted(
                (frame_id, format(Decimal(str(probability)), "f"))
                for frame_id, probability in predictions.items()
            )
        )
        unsigned = {
            "schema_version": PREDICTION_ARTIFACT_SCHEMA,
            "campaign_id": request.campaign_id,
            "dataset_version": request.dataset_version,
            "strategy_id": request.strategy_id,
            "strategy_digest": request.strategy_digest,
            "frame_manifest_hash": frame_manifest_hash,
            "predictions": [
                {"frame_id": frame_id, "probability": probability}
                for frame_id, probability in normalized
            ],
        }
        return cls(
            request.campaign_id,
            request.dataset_version,
            request.strategy_id,
            request.strategy_digest,
            frame_manifest_hash,
            normalized,
            sha256_bytes(canonical_json(unsigned)),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FrozenPredictionArtifact":
        required = {
            "schema_version",
            "campaign_id",
            "dataset_version",
            "strategy_id",
            "strategy_digest",
            "frame_manifest_hash",
            "predictions",
            "artifact_hash",
        }
        if set(value) != required or not isinstance(value["predictions"], list):
            raise ValueError("frozen prediction payload is invalid")
        predictions: list[tuple[str, str]] = []
        for row in value["predictions"]:
            if not isinstance(row, dict) or set(row) != {"frame_id", "probability"}:
                raise ValueError("frozen prediction row is invalid")
            if not isinstance(row["frame_id"], str) or not isinstance(row["probability"], str):
                raise ValueError("frozen prediction row types are invalid")
            predictions.append((row["frame_id"], row["probability"]))
        fields = dict(value)
        fields["predictions"] = tuple(predictions)
        return cls(**fields)


def _import_identifier(value: str) -> bool:
    return bool(value) and all(part.isidentifier() for part in value.split("."))


@dataclass(frozen=True)
class ResearchProgramRef:
    """Closed, data-only identity for code executed by the research worker."""

    module: str
    qualname: str
    module_artifact_hash: str
    program_digest: str
    schema_version: str = RESEARCH_PROGRAM_SCHEMA
    domain: str = RESEARCH_PROGRAM_DOMAIN

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_PROGRAM_SCHEMA or self.domain != RESEARCH_PROGRAM_DOMAIN:
            raise ValueError("unsupported research program reference")
        if not _import_identifier(self.module) or not _import_identifier(self.qualname):
            raise ValueError("research program import identity is invalid")
        if "<locals>" in self.qualname or any(
            part.startswith("__") and part.endswith("__")
            for part in self.qualname.split(".")
        ):
            raise ValueError("research program traversal is forbidden")
        for name in ("module_artifact_hash", "program_digest"):
            value = getattr(self, name)
            if len(value) != 64 or value.lower() != value:
                raise ValueError(f"{name} must be lowercase SHA-256")
            int(value, 16)
        if self.compute_digest() != self.program_digest:
            raise ValueError("research program digest mismatch")

    def unsigned_dict(self) -> dict[str, str]:
        return {
            "domain": self.domain,
            "schema_version": self.schema_version,
            "module": self.module,
            "qualname": self.qualname,
            "module_artifact_hash": self.module_artifact_hash,
        }

    def compute_digest(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, str]:
        return self.unsigned_dict() | {"program_digest": self.program_digest}

    @classmethod
    def from_callable(cls, callback: Any) -> "ResearchProgramRef":
        if not inspect.isfunction(callback):
            raise ValueError("research program must be a top-level Python function")
        if (
            callback.__closure__ is not None
            or callback.__defaults__
            or callback.__kwdefaults__
            or "<locals>" in callback.__qualname__
        ):
            raise ValueError("research program cannot carry parent state")
        module = importlib.import_module(callback.__module__)
        module_path = getattr(module, "__file__", None)
        if not isinstance(module_path, str):
            raise ValueError("research program module is not file-backed")
        unsigned = {
            "domain": RESEARCH_PROGRAM_DOMAIN,
            "schema_version": RESEARCH_PROGRAM_SCHEMA,
            "module": callback.__module__,
            "qualname": callback.__qualname__,
            "module_artifact_hash": sha256_file(Path(module_path).resolve()),
        }
        return cls(
            callback.__module__,
            callback.__qualname__,
            unsigned["module_artifact_hash"],
            sha256_bytes(canonical_json(unsigned)),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ResearchProgramRef":
        required = {
            "domain",
            "schema_version",
            "module",
            "qualname",
            "module_artifact_hash",
            "program_digest",
        }
        if set(value) != required or not all(isinstance(value[key], str) for key in required):
            raise ValueError("research program payload is invalid")
        return cls(
            module=value["module"],
            qualname=value["qualname"],
            module_artifact_hash=value["module_artifact_hash"],
            program_digest=value["program_digest"],
            schema_version=value["schema_version"],
            domain=value["domain"],
        )


@dataclass(frozen=True)
class ProtectedCampaign:
    campaign_id: str
    family_id: str
    max_attempts: int
    evaluator_digest: str
    minimum_cell_size: int = 5
    experiment_id: str | None = None
    dataset_version: str | None = None
    frame_manifest_hash: str | None = None
    registered_at: str | None = None
    schema_version: str = "protected-campaign-v1-legacy"

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.family_id or len(self.evaluator_digest) != 64:
            raise ValueError("protected campaign identity is invalid")
        int(self.evaluator_digest, 16)
        if self.max_attempts <= 0 or self.minimum_cell_size <= 0:
            raise ValueError("protected campaign limits must be positive")
        if self.schema_version == CAMPAIGN_SCHEMA:
            if not all((self.experiment_id, self.dataset_version, self.frame_manifest_hash, self.registered_at)):
                raise ValueError("registered protected campaign is incomplete")
            if len(self.frame_manifest_hash or "") != 64:
                raise ValueError("campaign frame manifest hash must be SHA-256")
            int(self.frame_manifest_hash or "", 16)
            parse_utc(self.registered_at or "")
            object.__setattr__(self, "registered_at", iso_utc(self.registered_at or ""))
        elif self.schema_version != "protected-campaign-v1-legacy":
            raise ValueError("unsupported protected campaign schema")

    @property
    def is_registered_v2(self) -> bool:
        return self.schema_version == CAMPAIGN_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create_registered(
        cls,
        *,
        campaign_id: str,
        family_id: str,
        max_attempts: int,
        evaluator_digest: str,
        minimum_cell_size: int,
        experiment_id: str,
        sealed_frames: SealedFrameSet,
        registered_at: str,
    ) -> "ProtectedCampaign":
        return cls(
            campaign_id,
            family_id,
            max_attempts,
            evaluator_digest,
            minimum_cell_size,
            experiment_id,
            sealed_frames.dataset_version,
            sealed_frames.frame_manifest_hash,
            registered_at,
            CAMPAIGN_SCHEMA,
        )


class ProtectedCampaignRegistry:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    @staticmethod
    def _from_row(row: dict[str, Any]) -> ProtectedCampaign:
        try:
            return ProtectedCampaign(
                **{key: row[key] for key in ProtectedCampaign.__dataclass_fields__}
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryConflict("invalid protected campaign record") from exc

    def register(self, campaign: ProtectedCampaign, experiments: ExperimentRegistry) -> str:
        if not campaign.is_registered_v2:
            raise RegistryConflict("legacy campaign cannot enter protected mode")
        experiment = experiments.get(campaign.experiment_id or "")
        if experiment.dataset_version != campaign.dataset_version:
            raise RegistryConflict("campaign dataset is not bound to its experiment")
        record = {"record_type": "protected_campaign_registered", **campaign.to_dict()}

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            matches = [
                self._from_row(row)
                for row in rows
                if row.get("record_type") == "protected_campaign_registered"
                and row.get("campaign_id") == campaign.campaign_id
            ]
            if not matches:
                return record
            if all(item == campaign for item in matches):
                return None
            raise RegistryConflict("protected campaign ID conflict")

        result = self.log.transaction(build)
        return result or sha256_bytes(canonical_json(campaign.to_dict()))

    def get(self, campaign_id: str) -> ProtectedCampaign:
        matches = [
            self._from_row(row)
            for row in self.log.records()
            if row.get("record_type") == "protected_campaign_registered"
            and row.get("campaign_id") == campaign_id
        ]
        if len(matches) != 1:
            raise RegistryConflict("unknown or ambiguous protected campaign")
        return matches[0]


@dataclass(frozen=True)
class _AttemptState:
    reservations: dict[str, dict[str, Any]]
    completions: dict[str, dict[str, Any]]
    campaign_counts: dict[str, int]
    family_counts: dict[str, int]


class ProtectedAttemptLedger:
    """Monotonic attempt authority; protected mode requires a durable path."""

    def __init__(self, path: str | Path | None = None):
        self.log = AppendOnlyJsonl(path) if path is not None else None
        self._legacy_campaign_attempts: dict[str, int] = {}
        self._legacy_family_attempts: dict[str, int] = {}
        if self.log is not None:
            self._replay(tuple(self.log.records()))

    @staticmethod
    def _replay(rows: tuple[dict[str, Any], ...]) -> _AttemptState:
        reservations: dict[str, dict[str, Any]] = {}
        completions: dict[str, dict[str, Any]] = {}
        campaign_counts: dict[str, int] = {}
        family_counts: dict[str, int] = {}
        for row in rows:
            record_type = row.get("record_type")
            if record_type == "protected_attempt_reserved" and row.get("schema_version") is None:
                campaign = row.get("campaign_id")
                family = row.get("family_id")
                campaign_attempt = int(row.get("campaign_attempt", 0))
                family_attempt = int(row.get("family_attempt", 0))
                if (
                    not campaign
                    or not family
                    or campaign_attempt != campaign_counts.get(campaign, 0) + 1
                    or family_attempt != family_counts.get(family, 0) + 1
                ):
                    raise RegistryConflict("invalid legacy protected attempt history")
                campaign_counts[campaign] = campaign_attempt
                family_counts[family] = family_attempt
                continue
            if record_type == "protected_attempt_reserved":
                required = {
                    "schema_version",
                    "attempt_id",
                    "campaign_id",
                    "family_id",
                    "experiment_id",
                    "campaign_attempt",
                    "family_attempt",
                    "request_digest",
                    "frame_manifest_hash",
                    "reserved_at",
                }
                if row.get("schema_version") != ATTEMPT_SCHEMA or not required.issubset(row):
                    raise RegistryConflict("protected attempt reservation is incomplete")
                attempt_id = row["attempt_id"]
                campaign = row["campaign_id"]
                family = row["family_id"]
                if attempt_id in reservations:
                    raise RegistryConflict("duplicate protected attempt ID")
                if int(row["campaign_attempt"]) != campaign_counts.get(campaign, 0) + 1:
                    raise RegistryConflict("protected campaign attempt sequence is broken")
                if int(row["family_attempt"]) != family_counts.get(family, 0) + 1:
                    raise RegistryConflict("protected family attempt sequence is broken")
                parse_utc(row["reserved_at"])
                expected = dict(row)
                expected.pop("record_hash", None)
                expected.pop("previous_hash", None)
                expected.pop("sequence", None)
                claimed = expected.pop("attempt_id")
                if sha256_bytes(canonical_json(expected)) != claimed:
                    raise RegistryConflict("protected attempt ID mismatch")
                reservations[attempt_id] = row
                campaign_counts[campaign] = int(row["campaign_attempt"])
                family_counts[family] = int(row["family_attempt"])
                continue
            if record_type == "protected_attempt_completed":
                if row.get("schema_version") != ATTEMPT_SCHEMA:
                    raise RegistryConflict("unsupported protected completion schema")
                attempt_id = row.get("attempt_id")
                if attempt_id not in reservations or attempt_id in completions:
                    raise RegistryConflict("invalid protected attempt completion")
                if row.get("disposition") not in {
                    "certificate",
                    "suppressed",
                    "research_failure",
                    "evaluation_failure",
                    "artifact_rejected",
                }:
                    raise RegistryConflict("unknown protected attempt disposition")
                parse_utc(row["completed_at"])
                if parse_utc(row["completed_at"]) < parse_utc(
                    reservations[attempt_id]["reserved_at"]
                ):
                    raise RegistryConflict("protected attempt completion predates reservation")
                completions[attempt_id] = row
                continue
            raise RegistryConflict(f"unknown protected attempt event: {record_type!r}")
        return _AttemptState(reservations, completions, campaign_counts, family_counts)

    def reserve(
        self,
        campaign: ProtectedCampaign,
        *,
        family_limit: int | None = None,
        note: str = "",
    ) -> int:
        """Legacy synthetic-only reservation used by the unsafe harness."""

        if self.log is not None:
            raise RegistryConflict("durable attempt ledger requires trusted reserve")
        campaign_attempt = self._legacy_campaign_attempts.get(campaign.campaign_id, 0)
        family_attempt = self._legacy_family_attempts.get(campaign.family_id, 0)
        if campaign_attempt >= campaign.max_attempts:
            raise RegistryConflict("protected campaign attempt budget exhausted")
        if family_limit is not None and family_attempt >= family_limit:
            raise RegistryConflict("protected family attempt budget exhausted")
        campaign_attempt += 1
        self._legacy_campaign_attempts[campaign.campaign_id] = campaign_attempt
        self._legacy_family_attempts[campaign.family_id] = family_attempt + 1
        return campaign_attempt

    def reserve_trusted(
        self,
        campaign: ProtectedCampaign,
        request: EvaluationRequest,
        *,
        family_limit: int,
        reserved_at: str,
    ) -> str:
        if self.log is None:
            raise RegistryConflict("protected attempts require durable authority")
        reserved_at = iso_utc(reserved_at)
        request_digest = sha256_bytes(canonical_json(request.to_dict()))
        selected: str | None = None

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
            nonlocal selected
            state = self._replay(rows)
            campaign_attempt = state.campaign_counts.get(campaign.campaign_id, 0) + 1
            family_attempt = state.family_counts.get(campaign.family_id, 0) + 1
            if campaign_attempt > campaign.max_attempts:
                raise RegistryConflict("protected campaign attempt budget exhausted")
            if family_attempt > family_limit:
                raise RegistryConflict("protected family attempt budget exhausted")
            body = {
                "record_type": "protected_attempt_reserved",
                "schema_version": ATTEMPT_SCHEMA,
                "campaign_id": campaign.campaign_id,
                "family_id": campaign.family_id,
                "experiment_id": campaign.experiment_id,
                "campaign_attempt": campaign_attempt,
                "family_attempt": family_attempt,
                "request_digest": request_digest,
                "frame_manifest_hash": campaign.frame_manifest_hash,
                "reserved_at": reserved_at,
            }
            selected = sha256_bytes(canonical_json(body))
            return {**body, "attempt_id": selected}

        self.log.transaction(build)
        assert selected is not None
        return selected

    def require_open(self, attempt_id: str, request: EvaluationRequest) -> dict[str, Any]:
        if self.log is None:
            raise RegistryConflict("protected attempts require durable authority")
        state = self._replay(tuple(self.log.records()))
        row = state.reservations.get(attempt_id)
        if row is None or attempt_id in state.completions:
            raise RegistryConflict("protected attempt is unknown or already complete")
        if row["request_digest"] != sha256_bytes(canonical_json(request.to_dict())):
            raise RegistryConflict("protected attempt request binding mismatch")
        return row

    def complete(
        self,
        attempt_id: str,
        *,
        disposition: str,
        certificate_digest: str | None,
        completed_at: str,
    ) -> None:
        if self.log is None:
            raise RegistryConflict("protected attempts require durable authority")
        completed_at = iso_utc(completed_at)
        record = {
            "record_type": "protected_attempt_completed",
            "schema_version": ATTEMPT_SCHEMA,
            "attempt_id": attempt_id,
            "disposition": disposition,
            "certificate_digest": certificate_digest,
            "completed_at": completed_at,
        }

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            state = self._replay(rows)
            if attempt_id not in state.reservations:
                raise RegistryConflict("cannot complete unknown protected attempt")
            if parse_utc(completed_at) < parse_utc(
                state.reservations[attempt_id]["reserved_at"]
            ):
                raise RegistryConflict("protected attempt completion predates reservation")
            existing = state.completions.get(attempt_id)
            if existing is not None:
                comparable = {key: existing.get(key) for key in record}
                if comparable != record:
                    raise RegistryConflict("protected attempt disposition conflict")
                return None
            return record

        self.log.transaction(build)

    def counts(self, campaign: ProtectedCampaign) -> tuple[int, int]:
        if self.log is None:
            return (
                self._legacy_campaign_attempts.get(campaign.campaign_id, 0),
                self._legacy_family_attempts.get(campaign.family_id, 0),
            )
        state = self._replay(tuple(self.log.records()))
        return (
            state.campaign_counts.get(campaign.campaign_id, 0),
            state.family_counts.get(campaign.family_id, 0),
        )


class LegacyUnsafeProtectedEvaluationBoundary:
    """Retained synthetic-only callback harness; never a protected-mode port."""

    def __init__(
        self,
        campaign: ProtectedCampaign,
        frames: Iterable[DecisionFrame],
        labels: Iterable[FutureOutcomeLabel],
        attempts: ProtectedAttemptLedger,
        *,
        family_limit: int | None = None,
        legacy_test_only: bool = False,
    ):
        if not legacy_test_only:
            raise RegistryConflict("unsafe in-process harness requires explicit test-only mode")
        if campaign.is_registered_v2:
            raise RegistryConflict("registered V2 campaign cannot use legacy unsafe harness")
        self.campaign = campaign
        self._legacy_harness = LegacyInProcessEvaluationHarness(frames, labels)
        self._attempts = attempts
        self._family_limit = family_limit

    def run(self, request: EvaluationRequest, strategy: ResearchStrategy) -> EvaluationCertificate:
        if request.campaign_id != self.campaign.campaign_id:
            raise ProtectedEvaluationError("legacy synthetic request rejected")
        if request.rules_digest != self.campaign.evaluator_digest:
            raise ProtectedEvaluationError("legacy synthetic evaluator version mismatch")
        self._attempts.reserve(
            self.campaign,
            family_limit=self._family_limit,
            note=request.strategy_id,
        )
        if (
            self._legacy_harness._frames
            and len(self._legacy_harness._frames) < self.campaign.minimum_cell_size
        ):
            return EvaluationCertificate(
                campaign_id=request.campaign_id,
                strategy_id=request.strategy_id,
                strategy_digest=request.strategy_digest,
                dataset_version=request.dataset_version,
                rules_digest=request.rules_digest,
                metrics={"suppressed": "true"},
                n_observations=0,
                issued_at=_now(),
            )
        try:
            return self._legacy_harness.run(request, strategy)
        except Exception:
            raise ProtectedEvaluationError("legacy synthetic evaluation failed") from None


def _send_json(connection: Any, payload: dict[str, Any]) -> None:
    connection.send_bytes(canonical_json(payload))


def _recv_json(connection: Any) -> dict[str, Any]:
    raw = connection.recv_bytes(MAX_IPC_BYTES)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("IPC payload must be an object")
    return value


def _trusted_evaluator_worker(
    connection: Any,
    campaign: ProtectedCampaign,
    frames: tuple[DecisionFrame, ...],
    labels: tuple[FutureOutcomeLabel, ...],
    campaign_registry_path: str,
    experiment_registry_path: str,
    attempt_path: str,
    family_limit: int,
    allow_fault_injection: bool,
) -> None:
    attempts = ProtectedAttemptLedger(attempt_path)
    try:
        registered = ProtectedCampaignRegistry(campaign_registry_path).get(campaign.campaign_id)
        experiment = ExperimentRegistry(experiment_registry_path).get(campaign.experiment_id or "")
        sealed = SealedFrameSet.create(
            campaign_id=campaign.campaign_id,
            dataset_version=campaign.dataset_version or "",
            frames=frames,
        )
        if registered != campaign or experiment.dataset_version != campaign.dataset_version:
            raise RegistryConflict("trusted campaign registration mismatch")
        if sealed.frame_manifest_hash != campaign.frame_manifest_hash:
            raise RegistryConflict("trusted frame manifest mismatch")
        if len(frames) != len(labels):
            raise RegistryConflict("trusted protected frame/label cardinality mismatch")
        label_by_entity: dict[str, FutureOutcomeLabel] = {}
        for frame, label in zip(frames, labels):
            if frame.entity_id != label.entity_id:
                raise RegistryConflict("trusted protected label alignment mismatch")
            if parse_utc(label.observed_at) <= parse_utc(frame.decision_at):
                raise RegistryConflict("trusted protected label is not future")
            if label.entity_id in label_by_entity:
                raise RegistryConflict("trusted protected label identity is ambiguous")
            label_by_entity[label.entity_id] = label
        _send_json(connection, {"status": "ready"})
    except Exception:
        _send_json(connection, {"status": "error", "message": "protected evaluator unavailable"})
        connection.close()
        return

    while True:
        attempt_id: str | None = None
        try:
            message = _recv_json(connection)
            operation = message.get("op")
            if operation == "shutdown":
                _send_json(connection, {"status": "closed"})
                break
            if operation == "reserve":
                if set(message) != {"op", "request"} or not isinstance(message["request"], dict):
                    raise ValueError
                request = EvaluationRequest.from_dict(message["request"])
                if (
                    request.campaign_id != campaign.campaign_id
                    or request.dataset_version != campaign.dataset_version
                    or request.rules_digest != campaign.evaluator_digest
                ):
                    _send_json(connection, {"status": "error", "message": "protected request rejected"})
                    continue
                attempt_id = attempts.reserve_trusted(
                    campaign,
                    request,
                    family_limit=family_limit,
                    reserved_at=_now(),
                )
                _send_json(connection, {"status": "reserved", "attempt_id": attempt_id})
                continue
            if operation == "crash":
                if not allow_fault_injection:
                    raise ValueError
                os._exit(23)
            if operation == "abandon":
                if set(message) != {"op", "request", "attempt_id"}:
                    raise ValueError
                request = EvaluationRequest.from_dict(message["request"])
                attempt_id = str(message["attempt_id"])
                attempts.require_open(attempt_id, request)
                attempts.complete(
                    attempt_id,
                    disposition="research_failure",
                    certificate_digest=None,
                    completed_at=_now(),
                )
                _send_json(connection, {"status": "failed", "message": "protected evaluation failed"})
                continue
            if operation != "evaluate" or set(message) != {
                "op",
                "request",
                "attempt_id",
                "artifact",
            }:
                raise ValueError
            request = EvaluationRequest.from_dict(message["request"])
            attempt_id = str(message["attempt_id"])
            attempts.require_open(attempt_id, request)
            artifact = FrozenPredictionArtifact.from_dict(message["artifact"])
            if (
                artifact.campaign_id != campaign.campaign_id
                or artifact.dataset_version != campaign.dataset_version
                or artifact.strategy_id != request.strategy_id
                or artifact.strategy_digest != request.strategy_digest
                or artifact.frame_manifest_hash != sealed.frame_manifest_hash
                or set(frame_id for frame_id, _ in artifact.predictions) != set(sealed.frame_ids)
                or len(artifact.predictions) != len(sealed.frame_ids)
            ):
                attempts.complete(
                    attempt_id,
                    disposition="artifact_rejected",
                    certificate_digest=None,
                    completed_at=_now(),
                )
                _send_json(connection, {"status": "error", "message": "protected evaluation failed"})
                continue

            if len(frames) < campaign.minimum_cell_size:
                certificate = EvaluationCertificate(
                    campaign_id=request.campaign_id,
                    strategy_id=request.strategy_id,
                    strategy_digest=request.strategy_digest,
                    dataset_version=request.dataset_version,
                    rules_digest=request.rules_digest,
                    metrics={"suppressed": "true"},
                    n_observations=0,
                    issued_at=_now(),
                    frame_manifest_hash=sealed.frame_manifest_hash,
                    attempt_id=attempt_id,
                )
                disposition = "suppressed"
            else:
                prediction_by_id = {
                    frame_id: Decimal(probability)
                    for frame_id, probability in artifact.predictions
                }
                total = Decimal("0")
                for frame in frames:
                    label = label_by_entity[frame.entity_id]
                    total += (
                        prediction_by_id[frame.decision_id]
                        - Decimal(str(label.outcome_value))
                    ) ** 2
                brier = total / Decimal(len(frames))
                certificate = EvaluationCertificate(
                    campaign_id=request.campaign_id,
                    strategy_id=request.strategy_id,
                    strategy_digest=request.strategy_digest,
                    dataset_version=request.dataset_version,
                    rules_digest=request.rules_digest,
                    metrics={"brier": format(brier, "f")},
                    n_observations=len(frames),
                    issued_at=_now(),
                    frame_manifest_hash=sealed.frame_manifest_hash,
                    attempt_id=attempt_id,
                )
                disposition = "certificate"
            attempts.complete(
                attempt_id,
                disposition=disposition,
                certificate_digest=certificate.certificate_digest,
                completed_at=_now(),
            )
            _send_json(connection, {"status": "certificate", "certificate": certificate.to_dict()})
        except RegistryConflict:
            _send_json(connection, {"status": "error", "message": "protected request rejected"})
        except Exception:
            if attempt_id is not None:
                try:
                    attempts.complete(
                        attempt_id,
                        disposition="evaluation_failure",
                        certificate_digest=None,
                        completed_at=_now(),
                    )
                except Exception:
                    pass
            _send_json(connection, {"status": "error", "message": "protected evaluation failed"})
    connection.close()


def _sealed_launch_dict(sealed: SealedFrameSet) -> dict[str, Any]:
    return {
        "schema_version": sealed.schema_version,
        "campaign_id": sealed.campaign_id,
        "dataset_version": sealed.dataset_version,
        "frames": [frame.to_dict() for frame in sealed.frames],
        "frame_ids": list(sealed.frame_ids),
        "frame_hashes": list(sealed.frame_hashes),
        "frame_manifest_hash": sealed.frame_manifest_hash,
    }


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _research_environment(workdir: Path) -> dict[str, str]:
    environment = {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "TEMP": str(workdir),
        "TMP": str(workdir),
    }
    for name in ("SYSTEMROOT", "WINDIR", "COMSPEC"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _research_reader(
    stream: BinaryIO,
    messages: "queue.Queue[bytes | None]",
) -> None:
    try:
        while True:
            raw = stream.readline(MAX_IPC_BYTES + 1)
            if not raw:
                break
            messages.put(raw)
    finally:
        messages.put(None)


def _take_research_message(
    messages: "queue.Queue[bytes | None]",
    *,
    timeout: float,
) -> dict[str, Any]:
    try:
        raw = messages.get(timeout=timeout)
    except queue.Empty as exc:
        raise ProtectedEvaluationError("protected research unavailable") from exc
    if raw is None or len(raw) > MAX_IPC_BYTES or not raw.endswith(b"\n"):
        raise ProtectedEvaluationError("protected research unavailable")
    try:
        value = json.loads(raw)
    except Exception as exc:
        raise ProtectedEvaluationError("protected research unavailable") from exc
    if not isinstance(value, dict):
        raise ProtectedEvaluationError("protected research unavailable")
    return value


def _start_research_process(
    sealed_frames: SealedFrameSet,
    *,
    research_workdir: Path,
    allowed_program_import_roots: tuple[Path, ...],
) -> tuple[
    subprocess.Popen[bytes],
    "queue.Queue[bytes | None]",
    threading.Thread,
    dict[str, Any],
]:
    environment = _research_environment(research_workdir)
    worker_path = Path(__file__).with_name("protected_research_worker.py").resolve()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", str(worker_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=str(research_workdir),
        env=environment,
        close_fds=True,
        creationflags=creationflags,
    )
    if process.stdin is None or process.stdout is None:
        process.kill()
        process.wait(10)
        raise ProtectedEvaluationError("protected research unavailable")
    messages: "queue.Queue[bytes | None]" = queue.Queue()
    reader = threading.Thread(
        target=_research_reader,
        args=(process.stdout, messages),
        daemon=True,
        name=f"genesis-research-reader-{process.pid}",
    )
    reader.start()
    launch = {
        "schema_version": RESEARCH_LAUNCH_SCHEMA,
        "sealed_frame_manifest": _sealed_launch_dict(sealed_frames),
        "allowed_program_import_roots": [str(path) for path in allowed_program_import_roots],
        "max_ipc_bytes": MAX_IPC_BYTES,
    }
    try:
        raw = canonical_json(launch)
        if len(raw) > MAX_IPC_BYTES:
            raise ValueError("research launch exceeds IPC limit")
        process.stdin.write(raw)
        process.stdin.flush()
        response = _take_research_message(messages, timeout=15)
        required = {
            "status",
            "schema_version",
            "research_pid",
            "frame_manifest_hash",
            "received_capabilities",
        }
        if (
            set(response) != required
            or response["status"] != "ready"
            or response["schema_version"] != RESEARCH_BOUNDARY_SCHEMA
            or response["research_pid"] != process.pid
            or response["frame_manifest_hash"] != sealed_frames.frame_manifest_hash
            or response["received_capabilities"]
            != [
                "program_import_roots",
                "research_ipc",
                "research_workdir",
                "sealed_frames",
            ]
        ):
            raise ValueError("research ready response mismatch")
    except Exception:
        if process.poll() is None:
            process.kill()
        process.wait(10)
        process.stdin.close()
        process.stdout.close()
        raise ProtectedEvaluationError("protected research unavailable") from None
    boundary = {
        "schema_version": RESEARCH_BOUNDARY_SCHEMA,
        "research_pid": process.pid,
        "frame_manifest_hash": sealed_frames.frame_manifest_hash,
        "received_capabilities": tuple(response["received_capabilities"]),
        "environment_keys": tuple(sorted(environment)),
        "working_directory": str(research_workdir),
        "research_ready_before_evaluator": True,
    }
    return process, messages, reader, boundary


class ProtectedEvaluationClient:
    """Trusted orchestrator for separate label-free research and evaluator processes."""

    def __init__(
        self,
        connection: Any,
        process: multiprocessing.Process,
        sealed_frames: SealedFrameSet,
        research_process: subprocess.Popen[bytes],
        research_messages: "queue.Queue[bytes | None]",
        research_reader: threading.Thread,
        research_boundary: dict[str, Any],
        *,
        allow_fault_injection: bool,
    ):
        self._connection = connection
        self._process = process
        self._sealed_frames = sealed_frames
        self._research_process = research_process
        self._research_messages = research_messages
        self._research_reader = research_reader
        self._research_boundary = dict(research_boundary)
        self._research_lock = threading.Lock()
        self._last_research_pid: int | None = None
        self._allow_fault_injection = allow_fault_injection
        self._closed = False

    @property
    def frames(self) -> tuple[DecisionFrame, ...]:
        return self._sealed_frames.frames

    @property
    def frame_manifest_hash(self) -> str:
        return self._sealed_frames.frame_manifest_hash

    @property
    def evaluator_pid(self) -> int | None:
        return self._process.pid

    @property
    def research_pid(self) -> int:
        return int(self._research_process.pid)

    @property
    def last_research_pid(self) -> int | None:
        return self._last_research_pid

    @property
    def research_boundary(self) -> dict[str, Any]:
        return dict(self._research_boundary)

    def _roundtrip(self, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        if self._closed or not self._process.is_alive():
            raise ProtectedEvaluationError("protected evaluator unavailable") from None
        try:
            raw = canonical_json(payload)
            if len(raw) > MAX_IPC_BYTES:
                raise ValueError
            self._connection.send_bytes(raw)
            if not self._connection.poll(timeout):
                raise TimeoutError
            response = json.loads(self._connection.recv_bytes(MAX_IPC_BYTES))
            if not isinstance(response, dict):
                raise ValueError
            return response
        except Exception:
            raise ProtectedEvaluationError("protected evaluator unavailable") from None

    def _research_roundtrip(
        self,
        payload: dict[str, Any],
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        if self._closed or self._research_process.poll() is not None:
            raise ProtectedEvaluationError("protected research unavailable") from None
        with self._research_lock:
            try:
                raw = canonical_json(payload)
                if len(raw) > MAX_IPC_BYTES or self._research_process.stdin is None:
                    raise ValueError
                self._research_process.stdin.write(raw)
                self._research_process.stdin.flush()
                return _take_research_message(self._research_messages, timeout=timeout)
            except Exception:
                if self._research_process.poll() is None:
                    self._research_process.kill()
                    self._research_process.wait(10)
                raise ProtectedEvaluationError("protected research unavailable") from None

    def _reserve(self, request: EvaluationRequest) -> str:
        response = self._roundtrip({"op": "reserve", "request": request.to_dict()})
        if response.get("status") != "reserved" or not isinstance(response.get("attempt_id"), str):
            raise ProtectedEvaluationError(str(response.get("message", "protected request rejected"))) from None
        return response["attempt_id"]

    def _abandon(self, request: EvaluationRequest, attempt_id: str) -> None:
        try:
            self._roundtrip(
                {
                    "op": "abandon",
                    "request": request.to_dict(),
                    "attempt_id": attempt_id,
                }
            )
        except Exception:
            pass

    def _evaluate_reserved(
        self,
        request: EvaluationRequest,
        attempt_id: str,
        artifact: FrozenPredictionArtifact,
    ) -> EvaluationCertificate:
        response = self._roundtrip(
            {
                "op": "evaluate",
                "request": request.to_dict(),
                "attempt_id": attempt_id,
                "artifact": artifact.to_dict(),
            }
        )
        if response.get("status") != "certificate" or not isinstance(response.get("certificate"), dict):
            raise ProtectedEvaluationError("protected evaluation failed") from None
        try:
            certificate = EvaluationCertificate.from_dict(response["certificate"])
            if (
                certificate.campaign_id != request.campaign_id
                or certificate.strategy_id != request.strategy_id
                or certificate.strategy_digest != request.strategy_digest
                or certificate.dataset_version != request.dataset_version
                or certificate.rules_digest != request.rules_digest
                or certificate.frame_manifest_hash != self.frame_manifest_hash
                or certificate.attempt_id != attempt_id
                or certificate.raw_labels_exposed
            ):
                raise ValueError
            return certificate
        except Exception:
            raise ProtectedEvaluationError("protected evaluation failed") from None

    def submit(
        self,
        request: EvaluationRequest,
        artifact: FrozenPredictionArtifact,
    ) -> EvaluationCertificate:
        attempt_id = self._reserve(request)
        return self._evaluate_reserved(request, attempt_id, artifact)

    def run(
        self,
        request: EvaluationRequest,
        program: ResearchProgramRef,
    ) -> EvaluationCertificate:
        if not isinstance(program, ResearchProgramRef) or request.strategy_digest != program.program_digest:
            raise ProtectedEvaluationError("protected request rejected") from None
        attempt_id = self._reserve(request)
        # A fresh per-request nonce authenticates the worker's own reply. The
        # research callback never sees it, so bytes a callback writes into the
        # IPC channel cannot pass as the response (ADR-0003: callback output
        # must not corrupt the protocol).
        nonce = secrets.token_hex(32)
        try:
            response = self._research_roundtrip(
                {
                    "op": "predict",
                    "request": request.to_dict(),
                    "program": program.to_dict(),
                    "nonce": nonce,
                }
            )
            if response.get("status") != "error" and response.get("nonce") != nonce:
                self._terminate_research_after_protocol_violation()
                raise ValueError
            if set(response) != {"status", "artifact", "research_pid", "nonce"}:
                raise ValueError
            if (
                response["status"] != "artifact"
                or response["nonce"] != nonce
                or response["research_pid"] != self.research_pid
                or not isinstance(response["artifact"], dict)
            ):
                raise ValueError
            artifact = FrozenPredictionArtifact.from_dict(response["artifact"])
            if (
                artifact.campaign_id != request.campaign_id
                or artifact.dataset_version != request.dataset_version
                or artifact.strategy_id != request.strategy_id
                or artifact.strategy_digest != request.strategy_digest
                or artifact.frame_manifest_hash != self.frame_manifest_hash
                or set(frame_id for frame_id, _ in artifact.predictions)
                != set(self._sealed_frames.frame_ids)
                or len(artifact.predictions) != len(self._sealed_frames.frame_ids)
            ):
                raise ValueError
            self._last_research_pid = int(response["research_pid"])
        except Exception:
            self._abandon(request, attempt_id)
            raise ProtectedEvaluationError("protected evaluation failed") from None
        return self._evaluate_reserved(request, attempt_id, artifact)

    def _terminate_research_after_protocol_violation(self) -> None:
        """An unauthenticated reply means the stream is no longer trustworthy."""

        if self._research_process.poll() is None:
            self._research_process.kill()
            self._research_process.wait(10)

    def _close_research(self) -> None:
        try:
            if self._research_process.poll() is None:
                try:
                    self._research_roundtrip({"op": "shutdown"})
                except Exception:
                    pass
                try:
                    self._research_process.wait(10)
                except subprocess.TimeoutExpired:
                    self._research_process.kill()
                    self._research_process.wait(10)
        finally:
            if self._research_process.stdin is not None:
                self._research_process.stdin.close()
            if self._research_process.stdout is not None:
                self._research_process.stdout.close()
            self._research_reader.join(10)

    def crash_after_reservation_for_test(self, request: EvaluationRequest) -> None:
        if not self._allow_fault_injection:
            raise ProtectedEvaluationError("fault injection is disabled")
        self._reserve(request)
        try:
            self._connection.send_bytes(canonical_json({"op": "crash"}))
            self._process.join(10)
        finally:
            self._close_research()
            self._closed = True
            self._connection.close()
        raise ProtectedEvaluationError("protected evaluator unavailable") from None

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._process.is_alive():
                self._roundtrip({"op": "shutdown"})
                self._process.join(10)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(10)
            self._close_research()
        finally:
            self._closed = True
            self._connection.close()

    def __enter__(self) -> "ProtectedEvaluationClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def launch_trusted_protected_evaluator(
    *,
    campaign: ProtectedCampaign,
    sealed_frames: SealedFrameSet,
    labels: Iterable[FutureOutcomeLabel],
    campaigns: ProtectedCampaignRegistry,
    experiments: ExperimentRegistry,
    attempts: ProtectedAttemptLedger,
    family_limit: int,
    research_workdir: str | Path | None = None,
    allowed_program_import_roots: Iterable[str | Path] = (),
    trusted_label_roots: Iterable[str | Path] = (),
    allow_fault_injection: bool = False,
    local_checkpoint_test_only: bool = False,
) -> ProtectedEvaluationClient:
    """Launch research first, then the separate trusted label evaluator."""

    if not local_checkpoint_test_only:
        raise RegistryConflict(
            "real protected campaigns remain disabled pending independent boundary review"
        )
    if attempts.log is None:
        raise RegistryConflict("protected evaluator requires durable attempt authority")
    registered = campaigns.get(campaign.campaign_id)
    experiment = experiments.get(campaign.experiment_id or "")
    if registered != campaign or not campaign.is_registered_v2:
        raise RegistryConflict("protected campaign is not registered exactly")
    if experiment.dataset_version != campaign.dataset_version:
        raise RegistryConflict("protected experiment dataset mismatch")
    if (
        sealed_frames.campaign_id != campaign.campaign_id
        or sealed_frames.dataset_version != campaign.dataset_version
        or sealed_frames.frame_manifest_hash != campaign.frame_manifest_hash
    ):
        raise RegistryConflict("protected sealed frame registration mismatch")
    if research_workdir is None:
        raise RegistryConflict("protected research workdir is required")
    resolved_workdir = Path(research_workdir).resolve()
    resolved_workdir.mkdir(parents=True, exist_ok=True)
    import_roots = tuple(Path(path).resolve() for path in allowed_program_import_roots)
    label_roots = tuple(Path(path).resolve() for path in trusted_label_roots)
    if not import_roots or any(not path.is_dir() for path in import_roots):
        raise RegistryConflict("protected program import roots are invalid")
    if any(not path.is_dir() for path in label_roots):
        raise RegistryConflict("trusted label roots are invalid")
    for label_root in label_roots:
        if _paths_overlap(resolved_workdir, label_root) or any(
            _paths_overlap(import_root, label_root) for import_root in import_roots
        ):
            raise RegistryConflict("research and trusted label paths must be disjoint")

    research_process, research_messages, research_reader, research_boundary = (
        _start_research_process(
            sealed_frames,
            research_workdir=resolved_workdir,
            allowed_program_import_roots=import_roots,
        )
    )

    def dispose_research() -> None:
        if research_process.poll() is None:
            research_process.kill()
        research_process.wait(10)
        if research_process.stdin is not None:
            research_process.stdin.close()
        if research_process.stdout is not None:
            research_process.stdout.close()
        research_reader.join(10)

    # Materialize raw labels and create the evaluator endpoint only after the
    # fresh-interpreter research worker has completed its label-free startup.
    try:
        trusted_labels = tuple(labels)
        if len(trusted_labels) != len(sealed_frames.frames):
            raise RegistryConflict("protected labels do not align to registered frames")
    except Exception:
        dispose_research()
        raise

    parent_connection: Any | None = None
    child_connection: Any | None = None
    process: multiprocessing.Process | None = None
    try:
        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=True)
        process = context.Process(
            target=_trusted_evaluator_worker,
            args=(
                child_connection,
                campaign,
                sealed_frames.frames,
                trusted_labels,
                str(campaigns.log.path),
                str(experiments.log.path),
                str(attempts.log.path),
                family_limit,
                allow_fault_injection,
            ),
        )
        process.start()
        child_connection.close()
        child_connection = None
        if not parent_connection.poll(15):
            raise ProtectedEvaluationError("protected evaluator unavailable")
        response = json.loads(parent_connection.recv_bytes(MAX_IPC_BYTES))
        if response != {"status": "ready"}:
            raise ProtectedEvaluationError("protected evaluator unavailable")
    except Exception:
        if process is not None and process.pid is not None and process.is_alive():
            process.terminate()
        if process is not None and process.pid is not None:
            process.join(10)
        if child_connection is not None:
            child_connection.close()
        if parent_connection is not None:
            parent_connection.close()
        dispose_research()
        raise ProtectedEvaluationError("protected evaluator unavailable") from None
    assert process is not None and parent_connection is not None
    research_boundary["evaluator_pid"] = process.pid
    return ProtectedEvaluationClient(
        parent_connection,
        process,
        sealed_frames,
        research_process,
        research_messages,
        research_reader,
        research_boundary,
        allow_fault_injection=allow_fault_injection,
    )
