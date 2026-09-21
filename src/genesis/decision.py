"""Deterministic decision identity and reproducibility manifests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .repro import canonical_json, sha256_bytes


DECISION_HASH_FIELDS = (
    "strategy_version",
    "strategy_config_hash",
    "strategy_decision_contract_hash",
    "odds_profile_hash",
    "sport_adapter_version",
    "event_id",
    "market_id",
    "selection_id",
    "side",
    "evidence_cutoff_ts",
    "candidate_decision_ts",
    "evidence_pack_hash",
    "feature_manifest_hash",
    "model_artifact_hash",
    "calibration_artifact_hash",
    "gate_policy_hash",
)
DECISION_HASH_DIGEST_FIELDS = {
    "strategy_config_hash",
    "strategy_decision_contract_hash",
    "odds_profile_hash",
    "evidence_pack_hash",
    "feature_manifest_hash",
    "model_artifact_hash",
    "calibration_artifact_hash",
    "gate_policy_hash",
}


def candidate_decision_hash(inputs: Mapping[str, Any]) -> str:
    missing = [field for field in DECISION_HASH_FIELDS if field not in inputs or inputs[field] in (None, "")]
    if missing:
        raise ValueError(f"decision hash inputs missing: {', '.join(missing)}")
    invalid_hashes = [field for field in DECISION_HASH_DIGEST_FIELDS if len(str(inputs[field])) != 64]
    if invalid_hashes:
        raise ValueError(f"decision hash inputs must be SHA-256 digests: {', '.join(invalid_hashes)}")
    normalized = {field: inputs[field] for field in DECISION_HASH_FIELDS}
    return sha256_bytes(canonical_json(normalized))


def decision_hash_for_candidate(
    candidate: Any,
    *,
    strategy_config_hash: str,
    odds_profile_hash: str,
    sport_adapter_version: str,
) -> str:
    """Build the V0.4 identity from a canonical CandidateBet.

    Required artifact hashes are intentionally not inferred.  A caller must
    supply complete frozen identity fields before a candidate can be used by
    risk or execution.
    """

    return candidate_decision_hash(
        {
            "strategy_version": candidate.strategy_version,
            "strategy_config_hash": strategy_config_hash,
            "strategy_decision_contract_hash": candidate.strategy_decision_contract_hash,
            "odds_profile_hash": odds_profile_hash,
            "sport_adapter_version": sport_adapter_version,
            "event_id": candidate.event_id,
            "market_id": candidate.market_id,
            "selection_id": candidate.selection_id,
            "side": candidate.side.value,
            "evidence_cutoff_ts": candidate.evidence_cutoff_ts,
            "candidate_decision_ts": candidate.decision_at,
            "evidence_pack_hash": candidate.evidence_pack_id,
            "feature_manifest_hash": candidate.feature_manifest_hash,
            "model_artifact_hash": candidate.model_artifact_hash,
            "calibration_artifact_hash": candidate.calibration_artifact_hash,
            "gate_policy_hash": candidate.gate_policy_hash,
        }
    )


@dataclass(frozen=True)
class ReproducibilityManifest:
    git_commit_hash: str
    dependency_lock_hash: str
    runtime_hash: str
    config_hash: str
    dataset_release_hash: str
    model_hashes: tuple[str, ...]
    calibration_hashes: tuple[str, ...]
    prompt_template_hash: str
    extractor_schema_hash: str
    evidence_pack_hash: str
    feature_manifest_hash: str
    random_seeds: tuple[str, ...]
    timezone_policy: str
    command: str
    run_mode: str

    def __post_init__(self) -> None:
        for name in (
            "git_commit_hash",
            "dependency_lock_hash",
            "runtime_hash",
            "config_hash",
            "dataset_release_hash",
            "prompt_template_hash",
            "extractor_schema_hash",
            "evidence_pack_hash",
            "feature_manifest_hash",
        ):
            value = getattr(self, name)
            if len(value) != 64:
                raise ValueError(f"{name} must be a SHA-256 digest")

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json(asdict(self)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"manifest_hash": self.digest}
