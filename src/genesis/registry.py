"""Append-only dataset, experiment, and strategy registries."""

from __future__ import annotations

import json
import os
from dataclasses import MISSING, asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from .repro import canonical_json, sha256_bytes
from .time import iso_utc, parse_utc


class RegistryConflict(ValueError):
    pass


class StrategyLifecycle(StrEnum):
    IDEA = "idea"
    EXPLORATION = "exploration"
    WALK_FORWARD = "walk_forward_validation"
    PROTECTED = "protected_confirmation"
    PROSPECTIVE_SHADOW = "prospective_shadow"
    PAPER = "paper"
    MICRO_LIVE_ELIGIBLE = "micro_live_eligible"
    APPROVED_LIVE = "approved_live"
    MONITORED = "monitored"
    QUARANTINED = "quarantined"
    RETIRED = "retired"


class AppendOnlyJsonl:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, record: dict[str, Any]) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        previous = "0" * 64
        if self.path.exists():
            rows = self.path.read_text(encoding="utf-8").splitlines()
            if rows:
                previous = json.loads(rows[-1])["record_hash"]
        body = {"previous_hash": previous, **record}
        record_hash = sha256_bytes(canonical_json(body))
        line = canonical_json({**body, "record_hash": record_hash})
        with self.path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return record_hash

    def verify(self) -> int:
        if not self.path.exists():
            return 0
        previous = "0" * 64
        count = 0
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            row = json.loads(raw)
            if row["previous_hash"] != previous:
                raise RegistryConflict("registry hash chain is broken")
            actual = row.pop("record_hash")
            if actual != sha256_bytes(canonical_json(row)):
                raise RegistryConflict("registry record was tampered")
            previous = actual
            count += 1
        return count

    def records(self) -> list[dict[str, Any]]:
        """Replay verified records; callers never replay an unverified log."""

        self.verify()
        if not self.path.exists():
            return []
        return [json.loads(raw) for raw in self.path.read_text(encoding="utf-8").splitlines()]


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    version: str
    schema_version: str
    created_at: str
    artifact_hashes: tuple[str, ...]
    source_contract_ids: tuple[str, ...]
    availability_policy: str
    decision_time_fields: tuple[str, ...]
    future_label_fields: tuple[str, ...]
    parent_version: str | None = None
    split_definition: str | None = None

    def __post_init__(self) -> None:
        parse_utc(self.created_at)
        if not self.dataset_id or not self.version or not self.schema_version:
            raise ValueError("dataset identity fields are required")
        if set(self.decision_time_fields) & set(self.future_label_fields):
            raise ValueError("decision-time and future-label fields must be disjoint")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DatasetRegistry:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)
        self._latest: dict[tuple[str, str], DatasetManifest] = {}
        for row in self.log.records():
            if row.get("record_type") == "dataset_registered":
                manifest = DatasetManifest(**{k: row[k] for k in DatasetManifest.__dataclass_fields__})
                self._latest[(manifest.dataset_id, manifest.version)] = manifest

    def register(self, manifest: DatasetManifest) -> None:
        key = (manifest.dataset_id, manifest.version)
        if key in self._latest:
            raise RegistryConflict(f"dataset version already exists: {key}")
        self._latest[key] = manifest
        self.log.append({"record_type": "dataset_registered", **manifest.to_dict()})


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    family: str
    parent_id: str | None
    hypothesis: str
    mechanism: str
    dataset_version: str
    eligibility_definition: str
    features: tuple[str, ...]
    target: str
    search_budget: int
    training_period: str
    validation_period: str
    protected_period: str | None
    primary_metrics: tuple[str, ...]
    status: str = "registered"
    attempts_used: int = 0
    candidate_universe: str | None = None
    evidence_policy: str | None = None
    model_class: str | None = None
    hyperparameter_search_budget: str | None = None
    selection_policy: str | None = None
    odds_profile: str | None = None
    stake_execution_assumptions: str | None = None
    secondary_metrics: tuple[str, ...] = ()
    adaptive_search_notes: str | None = None

    def __post_init__(self) -> None:
        if self.search_budget <= 0:
            raise ValueError("search budget must be positive")
        if self.attempts_used < 0 or self.attempts_used > self.search_budget:
            raise ValueError("attempt accounting exceeds declared budget")


class ExperimentRegistry:
    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)
        self._latest: dict[str, ExperimentSpec] = {}
        for row in self.log.records():
            kind = row.get("record_type")
            if kind == "experiment_registered":
                fields = {}
                for key, field in ExperimentSpec.__dataclass_fields__.items():
                    if key in row:
                        fields[key] = row[key]
                    elif field.default is not MISSING:
                        fields[key] = field.default
                    elif field.default_factory is not MISSING:
                        fields[key] = field.default_factory()
                    else:
                        raise RegistryConflict(f"experiment record missing field: {key}")
                self._latest[fields["experiment_id"]] = ExperimentSpec(**fields)
            elif kind == "experiment_attempt":
                current = self._latest[row["experiment_id"]]
                self._latest[row["experiment_id"]] = replace(
                    current, attempts_used=int(row["attempt_number"]), status="running"
                )
            elif kind == "experiment_finished":
                current = self._latest[row["experiment_id"]]
                self._latest[row["experiment_id"]] = replace(current, status=row["disposition"])

    def register(self, spec: ExperimentSpec) -> None:
        if spec.experiment_id in self._latest:
            raise RegistryConflict(f"experiment already registered: {spec.experiment_id}")
        self._latest[spec.experiment_id] = spec
        self.log.append({"record_type": "experiment_registered", **asdict(spec)})

    def record_attempt(self, experiment_id: str, *, note: str) -> ExperimentSpec:
        current = self._latest[experiment_id]
        if current.attempts_used >= current.search_budget:
            raise RegistryConflict("attempt budget exhausted; attempt is not refunded")
        updated = replace(current, attempts_used=current.attempts_used + 1, status="running")
        self._latest[experiment_id] = updated
        self.log.append(
            {
                "record_type": "experiment_attempt",
                "experiment_id": experiment_id,
                "attempt_number": updated.attempts_used,
                "note": note,
            }
        )
        return updated

    def finish(self, experiment_id: str, *, disposition: str) -> ExperimentSpec:
        current = self._latest[experiment_id]
        updated = replace(current, status=disposition)
        self._latest[experiment_id] = updated
        self.log.append(
            {
                "record_type": "experiment_finished",
                "experiment_id": experiment_id,
                "disposition": disposition,
                "attempts_used": current.attempts_used,
            }
        )
        return updated


@dataclass(frozen=True)
class StrategyArtifact:
    strategy_id: str
    version: str
    lifecycle: StrategyLifecycle
    code_digest: str
    config_digest: str
    model_digest: str
    support_region: str
    created_at: str
    parent_version: str | None = None
    approval_ref: str | None = None

    def __post_init__(self) -> None:
        parse_utc(self.created_at)
        for name in ("code_digest", "config_digest", "model_digest"):
            value = getattr(self, name)
            if len(value) != 64:
                raise ValueError(f"{name} must be a full SHA-256 digest")


class StrategyRegistry:
    _allowed = {
        StrategyLifecycle.IDEA: {StrategyLifecycle.EXPLORATION, StrategyLifecycle.RETIRED},
        StrategyLifecycle.EXPLORATION: {StrategyLifecycle.WALK_FORWARD, StrategyLifecycle.RETIRED},
        StrategyLifecycle.WALK_FORWARD: {StrategyLifecycle.PROTECTED, StrategyLifecycle.RETIRED},
        StrategyLifecycle.PROTECTED: {StrategyLifecycle.PROSPECTIVE_SHADOW, StrategyLifecycle.RETIRED},
        StrategyLifecycle.PROSPECTIVE_SHADOW: {StrategyLifecycle.PAPER, StrategyLifecycle.RETIRED},
        StrategyLifecycle.PAPER: {StrategyLifecycle.MICRO_LIVE_ELIGIBLE, StrategyLifecycle.RETIRED},
        StrategyLifecycle.MICRO_LIVE_ELIGIBLE: {StrategyLifecycle.APPROVED_LIVE, StrategyLifecycle.RETIRED},
        StrategyLifecycle.APPROVED_LIVE: {StrategyLifecycle.MONITORED, StrategyLifecycle.QUARANTINED},
        StrategyLifecycle.MONITORED: {StrategyLifecycle.QUARANTINED, StrategyLifecycle.RETIRED},
        StrategyLifecycle.QUARANTINED: {StrategyLifecycle.RETIRED, StrategyLifecycle.EXPLORATION},
        StrategyLifecycle.RETIRED: set(),
    }

    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)
        self._latest: dict[tuple[str, str], StrategyArtifact] = {}
        for row in self.log.records():
            kind = row.get("record_type")
            if kind == "strategy_registered":
                fields = {k: row[k] for k in StrategyArtifact.__dataclass_fields__}
                fields["lifecycle"] = StrategyLifecycle(fields["lifecycle"])
                artifact = StrategyArtifact(**fields)
                self._latest[(artifact.strategy_id, artifact.version)] = artifact
            elif kind == "strategy_transition":
                key = (row["strategy_id"], row["version"])
                current = self._latest[key]
                self._latest[key] = replace(
                    current,
                    lifecycle=StrategyLifecycle(row["to"]),
                    approval_ref=row.get("approval_ref") or current.approval_ref,
                )

    def register(self, artifact: StrategyArtifact) -> None:
        key = (artifact.strategy_id, artifact.version)
        if key in self._latest:
            raise RegistryConflict(f"strategy version already exists: {key}")
        if artifact.lifecycle != StrategyLifecycle.IDEA:
            raise RegistryConflict("new strategy artifacts must start at IDEA")
        self._latest[key] = artifact
        self.log.append({"record_type": "strategy_registered", **asdict(artifact), "lifecycle": artifact.lifecycle.value})

    def transition(
        self,
        strategy_id: str,
        version: str,
        lifecycle: StrategyLifecycle,
        *,
        approval_ref: str | None = None,
    ) -> StrategyArtifact:
        key = (strategy_id, version)
        current = self._latest[key]
        if lifecycle not in self._allowed[current.lifecycle]:
            raise RegistryConflict(f"invalid strategy transition {current.lifecycle} -> {lifecycle}")
        if lifecycle == StrategyLifecycle.APPROVED_LIVE and not approval_ref:
            raise RegistryConflict("live activation requires an external approval reference")
        updated = replace(current, lifecycle=lifecycle, approval_ref=approval_ref or current.approval_ref)
        self._latest[key] = updated
        self.log.append(
            {
                "record_type": "strategy_transition",
                "strategy_id": strategy_id,
                "version": version,
                "from": current.lifecycle.value,
                "to": lifecycle.value,
                "approval_ref": approval_ref,
            }
        )
        return updated
