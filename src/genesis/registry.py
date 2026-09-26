"""Append-only dataset, experiment, and strategy registries."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
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


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


_ALIASED = (
    "registry file has another name (hard link, symlink or short name); "
    "an authority log is written only through its single name"
)


def _own_name(path: Path) -> bool:
    """The path's final name is the file's own name, not a symlink or 8.3 alias."""

    return os.path.normcase(os.path.realpath(path)) == os.path.normcase(
        os.path.join(os.path.realpath(path.parent), path.name)
    )


def _require_single_name(path: Path) -> None:
    """One authority file, one name, one lock (T6 F-3b).

    The coordinator lock is derived from the name a log is opened by, so a
    file with a second name (a hard link), reached through a file symlink or
    opened by its Windows short name could be written under two locks. No
    write happens while any participant is such an alias or has one.
    """

    status = _lstat(path)
    if status is not None and (
        stat.S_ISLNK(status.st_mode) or status.st_nlink != 1 or not _own_name(path)
    ):
        raise RegistryConflict(_ALIASED)


class AppendOnlyJsonl:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.coordinator_path = self.path.with_name(f"{self.path.name}.coordinator.sqlite3")

    def _verified_records(self) -> list[dict[str, Any]]:
        return self._read_verified()[1]

    def _read_verified(self) -> tuple[bytes | None, list[dict[str, Any]]]:
        """The log's bytes (None when absent) and their verified records."""

        if not self.path.exists():
            return None, []
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
        return raw, records

    def _append_exactly(
        self, verified: bytes | None, start: os.stat_result | None, line: bytes,
    ) -> None:
        """Append right after the verified bytes of the same single-named file (F-3b).

        A log absent when the transaction read it is created exclusively; an
        existing one is opened without creation and must still be the file
        that was read, have one name and hold exactly the verified bytes.
        """

        flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0)
        if start is None:
            flags |= os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self.path, flags, 0o666)
        except (FileExistsError, FileNotFoundError) as exc:
            raise RegistryConflict(
                "registry file appeared or vanished during its transaction"
            ) from exc
        with open(descriptor, "ab") as handle:
            status = os.fstat(handle.fileno())
            if (
                status.st_nlink != 1
                or (start is not None and stat.S_ISLNK(start.st_mode))
                or not _own_name(self.path)
            ):
                raise RegistryConflict(_ALIASED)
            if status.st_size != len(verified or b"") or (
                start is not None
                and (status.st_dev, status.st_ino) != (start.st_dev, start.st_ino)
            ):
                raise RegistryConflict("registry file changed during its transaction")
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def transaction(
        self,
        build_record: Callable[[tuple[dict[str, Any], ...]], dict[str, Any] | None],
        *,
        read_locks: tuple["AppendOnlyJsonl", ...] = (),
    ) -> str | None:
        """Serialize verified read/check/append/fsync across processes.

        SQLite coordinates the critical section only.  The verified JSONL
        remains the sole authoritative business and audit history.  A row is
        appended only if the append target and every read-lock participant is
        its file's single name (F-3b), so the name-derived locks are the files'
        only locks, and only right after the exact bytes that were verified.
        """

        # Every participant, including the append target, is acquired in the
        # same global order.  A risk release can read an order while an order
        # send reads risk; taking each primary first would deadlock that pair.
        coordinator_paths = sorted(
            {self.coordinator_path.resolve()}
            | {log.coordinator_path.resolve() for log in read_locks},
            key=lambda path: os.path.normcase(str(path)),
        )
        connections: dict[Path, sqlite3.Connection] = {}
        try:
            for coordinator_path in coordinator_paths:
                coordinator_path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(
                    coordinator_path, timeout=30, isolation_level=None,
                )
                connections[coordinator_path] = connection
                connection.execute("PRAGMA busy_timeout = 30000")
                connection.execute("BEGIN IMMEDIATE")
            connection = connections[self.coordinator_path.resolve()]
            connection.execute(
                "CREATE TABLE IF NOT EXISTS coordination "
                "(singleton INTEGER PRIMARY KEY CHECK (singleton = 1), generation INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO coordination(singleton, generation) VALUES (1, 0)"
            )
            start = _lstat(self.path)
            raw, records = self._read_verified()
            record = build_record(tuple(dict(row) for row in records))
            if record is None:
                connection.commit()
                return None
            if not isinstance(record, dict) or "record_hash" in record or "previous_hash" in record:
                raise RegistryConflict("record payload contains reserved hash-chain fields")
            chained = self.chained(records, record)
            record_hash = chained["record_hash"]
            line = canonical_json(chained)
            for log in read_locks:
                _require_single_name(log.path)
            self._append_exactly(raw, start, line)
            connection.execute("UPDATE coordination SET generation = generation + 1 WHERE singleton = 1")
            connection.commit()
            return record_hash
        except BaseException:
            for connection in connections.values():
                if connection.in_transaction:
                    connection.rollback()
            raise
        finally:
            for coordinator_path in reversed(coordinator_paths):
                if coordinator_path in connections:
                    connections[coordinator_path].close()

    @staticmethod
    def chained(
        records: tuple[dict[str, Any], ...] | list[dict[str, Any]], record: dict[str, Any],
    ) -> dict[str, Any]:
        """The exact row ``transaction`` appends after ``records``, chain fields included."""

        previous = records[-1]["record_hash"] if records else "0" * 64
        body = {"previous_hash": previous, "sequence": len(records) + 1, **record}
        return {**body, "record_hash": sha256_bytes(canonical_json(body))}

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

    def get(self, experiment_id: str) -> ExperimentSpec:
        try:
            return self._latest[experiment_id]
        except KeyError as exc:
            raise RegistryConflict(f"unknown experiment: {experiment_id}") from exc

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


@dataclass(frozen=True)
class StrategyDecisionContract:
    schema_version: str
    strategy_id: str
    strategy_version: str
    strategy_config_hash: str
    odds_profile_hash: str
    sport_adapter_version: str
    market_capability_id: str
    required_lifecycle: StrategyLifecycle
    support_region: str
    comparability_group_id: str
    model_artifact_hash: str
    calibration_artifact_hash: str
    feature_manifest_hash: str
    gate_policy_hash: str
    approved_tier_policy_id: str
    approved_tiers: tuple[str, ...]
    created_at: str
    contract_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != "strategy-decision-contract-v2":
            raise ValueError("unsupported strategy decision contract schema")
        if not all(
            (
                self.strategy_id,
                self.strategy_version,
                self.sport_adapter_version,
                self.market_capability_id,
                self.support_region,
                self.comparability_group_id,
                self.approved_tier_policy_id,
                self.approved_tiers,
            )
        ):
            raise ValueError("strategy decision contract identity is incomplete")
        if self.required_lifecycle != StrategyLifecycle.PAPER:
            raise ValueError("V0.4 remediation requires exact PAPER lifecycle")
        parse_utc(self.created_at)
        for name in (
            "strategy_config_hash",
            "odds_profile_hash",
            "model_artifact_hash",
            "calibration_artifact_hash",
            "feature_manifest_hash",
            "gate_policy_hash",
            "contract_hash",
        ):
            value = getattr(self, name)
            if len(value) != 64:
                raise ValueError(f"{name} must be a full SHA-256 digest")
            int(value, 16)
        if self.compute_hash() != self.contract_hash:
            raise ValueError("strategy decision contract hash mismatch")

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("contract_hash")
        value["required_lifecycle"] = self.required_lifecycle.value
        value["created_at"] = iso_utc(self.created_at)
        return value

    def compute_hash(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        return self.unsigned_dict() | {"contract_hash": self.contract_hash}

    @classmethod
    def create(cls, **fields: Any) -> "StrategyDecisionContract":
        normalized = dict(fields)
        normalized.setdefault("schema_version", "strategy-decision-contract-v2")
        normalized["required_lifecycle"] = StrategyLifecycle(
            normalized["required_lifecycle"]
        )
        normalized["approved_tiers"] = tuple(normalized["approved_tiers"])
        unsigned = dict(normalized)
        unsigned["required_lifecycle"] = normalized["required_lifecycle"].value
        unsigned["approved_tiers"] = list(normalized["approved_tiers"])
        unsigned["created_at"] = iso_utc(normalized["created_at"])
        return cls(contract_hash=sha256_bytes(canonical_json(unsigned)), **normalized)


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
        self._replay_current(self.log.records())

    def _replay_current(
        self, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ) -> dict[tuple[str, str], StrategyArtifact]:
        """Derive current heads from verified JSONL, never an instance cache."""
        latest: dict[tuple[str, str], StrategyArtifact] = {}
        last_time: dict[tuple[str, str], Any] = {}
        contract_hashes: set[str] = set()
        for row in rows:
            kind = row.get("record_type")
            if kind == "strategy_registered":
                try:
                    fields = {k: row[k] for k in StrategyArtifact.__dataclass_fields__}
                    fields["lifecycle"] = StrategyLifecycle(fields["lifecycle"])
                    artifact = StrategyArtifact(**fields)
                except (KeyError, TypeError, ValueError) as exc:
                    raise RegistryConflict("invalid strategy registration") from exc
                key = (artifact.strategy_id, artifact.version)
                if key in latest or artifact.lifecycle != StrategyLifecycle.IDEA:
                    raise RegistryConflict("duplicate or invalid strategy registration")
                latest[key] = artifact
                last_time[key] = parse_utc(artifact.created_at)
            elif kind == "strategy_transition":
                try:
                    key = (row["strategy_id"], row["version"])
                    current = latest[key]
                    target = StrategyLifecycle(row["to"])
                    occurred = parse_utc(row["occurred_at"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise RegistryConflict("invalid or orphaned strategy transition") from exc
                if (
                    row.get("from") != current.lifecycle.value
                    or target not in self._allowed[current.lifecycle]
                    or occurred <= last_time[key]
                    or (target == StrategyLifecycle.APPROVED_LIVE and not row.get("approval_ref"))
                ):
                    raise RegistryConflict("strategy transition conflicts with durable head")
                latest[key] = replace(
                    current,
                    lifecycle=target,
                    approval_ref=row.get("approval_ref") or current.approval_ref,
                )
                last_time[key] = occurred
            elif kind == "strategy_decision_contract_registered":
                contract = self._contract_from_row(row)
                key = (contract.strategy_id, contract.strategy_version)
                if key not in latest or contract.contract_hash in contract_hashes:
                    raise RegistryConflict("orphaned or duplicate strategy contract")
                contract_hashes.add(contract.contract_hash)
            else:
                raise RegistryConflict(f"unknown strategy registry event: {kind}")
        return latest

    @staticmethod
    def _contract_from_row(row: dict[str, Any]) -> StrategyDecisionContract:
        try:
            fields = {key: row[key] for key in StrategyDecisionContract.__dataclass_fields__}
            fields["required_lifecycle"] = StrategyLifecycle(fields["required_lifecycle"])
            fields["approved_tiers"] = tuple(fields["approved_tiers"])
            return StrategyDecisionContract(**fields)
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryConflict("invalid strategy decision contract") from exc

    def register(self, artifact: StrategyArtifact) -> None:
        key = (artifact.strategy_id, artifact.version)
        if artifact.lifecycle != StrategyLifecycle.IDEA:
            raise RegistryConflict("new strategy artifacts must start at IDEA")

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
            if key in self._replay_current(rows):
                raise RegistryConflict(f"strategy version already exists: {key}")
            return {
                "record_type": "strategy_registered",
                **asdict(artifact),
                "lifecycle": artifact.lifecycle.value,
            }

        self.log.transaction(build)

    def get(self, strategy_id: str, version: str) -> StrategyArtifact:
        return self.current_head(strategy_id, version)

    def current_head(self, strategy_id: str, version: str) -> StrategyArtifact:
        """Fresh verified durable head; action callers must also hold ``log``."""
        try:
            return self._replay_current(self.log.records())[(strategy_id, version)]
        except KeyError as exc:
            raise RegistryConflict(f"unknown strategy version: {(strategy_id, version)}") from exc

    def register_decision_contract(self, contract: StrategyDecisionContract) -> str:
        record = {"record_type": "strategy_decision_contract_registered", **contract.to_dict()}

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            current = self._replay_current(rows)
            if (contract.strategy_id, contract.strategy_version) not in current:
                raise RegistryConflict("strategy decision contract has no registered strategy")
            matches = [
                row
                for row in rows
                if row.get("record_type") == "strategy_decision_contract_registered"
                and row.get("contract_hash") == contract.contract_hash
            ]
            if not matches:
                return record
            expected = contract.to_dict()
            if all({key: row.get(key) for key in expected} == expected for row in matches):
                return None
            raise RegistryConflict("strategy decision contract hash conflict")

        result = self.log.transaction(build)
        return result or contract.contract_hash

    def get_decision_contract(self, contract_hash: str) -> StrategyDecisionContract:
        rows = self.log.records()
        self._replay_current(rows)
        matches = [
            row
            for row in rows
            if row.get("record_type") == "strategy_decision_contract_registered"
            and row.get("contract_hash") == contract_hash
        ]
        if len(matches) != 1:
            raise RegistryConflict(f"unknown or ambiguous strategy contract: {contract_hash}")
        return self._contract_from_row(matches[0])

    def require_current_paper_contract(
        self, strategy_id: str, version: str, contract_hash: str,
    ) -> StrategyArtifact:
        """Check the bound exact contract and current PAPER head.

        Risk approval and order send callers must hold ``self.log``'s
        coordinator through their own checked append. This standalone method
        is a fresh read, not by itself a cross-owner transaction.
        """
        contract = self.get_decision_contract(contract_hash)
        head = self.current_head(strategy_id, version)
        if any((
            contract.strategy_id != strategy_id,
            contract.strategy_version != version,
            contract.required_lifecycle != StrategyLifecycle.PAPER,
            head.lifecycle != StrategyLifecycle.PAPER,
            head.config_digest != contract.strategy_config_hash,
            head.model_digest != contract.model_artifact_hash,
            head.support_region != contract.support_region,
        )):
            raise RegistryConflict("current strategy does not match PAPER decision contract")
        return head

    def lifecycle_at(
        self, strategy_id: str, version: str, at: str
    ) -> StrategyLifecycle:
        point = parse_utc(at)
        rows = self.log.records()
        self._replay_current(rows)
        registrations = [
            row
            for row in rows
            if row.get("record_type") == "strategy_registered"
            and row.get("strategy_id") == strategy_id
            and row.get("version") == version
        ]
        if len(registrations) != 1:
            raise RegistryConflict(f"unknown or ambiguous strategy version: {(strategy_id, version)}")
        registration = registrations[0]
        if parse_utc(registration["created_at"]) > point:
            raise RegistryConflict("strategy did not exist at decision time")
        lifecycle = StrategyLifecycle(registration["lifecycle"])
        for row in rows:
            if (
                row.get("record_type") == "strategy_transition"
                and row.get("strategy_id") == strategy_id
                and row.get("version") == version
                and row.get("occurred_at") is not None
                and parse_utc(row["occurred_at"]) <= point
            ):
                lifecycle = StrategyLifecycle(row["to"])
        return lifecycle

    def transition(
        self,
        strategy_id: str,
        version: str,
        lifecycle: StrategyLifecycle,
        *,
        approval_ref: str | None = None,
        occurred_at: str,
    ) -> StrategyArtifact:
        key = (strategy_id, version)
        if lifecycle == StrategyLifecycle.APPROVED_LIVE and not approval_ref:
            raise RegistryConflict("live activation requires an external approval reference")
        occurred = iso_utc(occurred_at)
        result: dict[str, StrategyArtifact] = {}

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
            try:
                current = self._replay_current(rows)[key]
            except KeyError as exc:
                raise RegistryConflict(f"unknown strategy version: {key}") from exc
            if lifecycle not in self._allowed[current.lifecycle]:
                raise RegistryConflict(
                    f"invalid strategy transition {current.lifecycle} -> {lifecycle}"
                )
            event_times = [parse_utc(current.created_at)]
            event_times.extend(
                parse_utc(row["occurred_at"])
                for row in rows
                if row.get("record_type") == "strategy_transition"
                and (row.get("strategy_id"), row.get("version")) == key
            )
            if parse_utc(occurred) <= max(event_times):
                raise RegistryConflict("strategy transition time must advance monotonically")
            result["value"] = replace(
                current,
                lifecycle=lifecycle,
                approval_ref=approval_ref or current.approval_ref,
            )
            return {
                "record_type": "strategy_transition",
                "strategy_id": strategy_id,
                "version": version,
                "from": current.lifecycle.value,
                "to": lifecycle.value,
                "approval_ref": approval_ref,
                "occurred_at": occurred,
            }

        self.log.transaction(build)
        return result["value"]
