"""Append-only dataset, experiment, and strategy registries."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import MISSING, asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

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
        self.coordinator_path = self.path.with_name(f"{self.path.name}.coordinator.sqlite3")

    def _verified_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise RegistryConflict("registry has a truncated final record")
        previous = "0" * 64
        records: list[dict[str, Any]] = []
        for expected_sequence, raw_line in enumerate(raw.splitlines(), start=1):
            try:
                row = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RegistryConflict("registry contains an invalid record") from exc
            if not isinstance(row, dict) or row.get("previous_hash") != previous:
                raise RegistryConflict("registry hash chain is broken")
            actual = row.get("record_hash")
            body = {key: value for key, value in row.items() if key != "record_hash"}
            if actual != sha256_bytes(canonical_json(body)):
                raise RegistryConflict("registry record was tampered")
            sequence = row.get("sequence")
            if sequence is not None and sequence != expected_sequence:
                raise RegistryConflict("registry sequence is not monotonic")
            previous = actual
            records.append(row)
        return records

    def transaction(
        self,
        build_record: Callable[[tuple[dict[str, Any], ...]], dict[str, Any] | None],
    ) -> str | None:
        """Serialize verified read/check/append/fsync across processes.

        SQLite coordinates the critical section only.  The verified JSONL
        remains the sole authoritative business and audit history.
        """

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.coordinator_path, timeout=30, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS coordination "
                "(singleton INTEGER PRIMARY KEY CHECK (singleton = 1), generation INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO coordination(singleton, generation) VALUES (1, 0)"
            )
            records = self._verified_records()
            record = build_record(tuple(dict(row) for row in records))
            if record is None:
                connection.commit()
                return None
            if not isinstance(record, dict) or "record_hash" in record or "previous_hash" in record:
                raise RegistryConflict("record payload contains reserved hash-chain fields")
            previous = records[-1]["record_hash"] if records else "0" * 64
            body = {"previous_hash": previous, "sequence": len(records) + 1, **record}
            record_hash = sha256_bytes(canonical_json(body))
            line = canonical_json({**body, "record_hash": record_hash})
            with self.path.open("ab") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            connection.execute("UPDATE coordination SET generation = generation + 1 WHERE singleton = 1")
            connection.commit()
            return record_hash
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def append(self, record: dict[str, Any]) -> str:
        result = self.transaction(lambda _records: record)
        assert result is not None
        return result

    def verify(self) -> int:
        return len(self._verified_records())

    def records(self) -> list[dict[str, Any]]:
        """Replay verified records; callers never replay an unverified log."""

        return self._verified_records()


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
