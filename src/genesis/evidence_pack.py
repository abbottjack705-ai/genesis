"""Immutable frozen evidence packs and append-only pack manifests."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, immutable_write, sha256_bytes
from .time import iso_utc, parse_utc


def _hash(value: str, name: str) -> str:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 digest")
    int(value, 16)
    return value


@dataclass(frozen=True)
class EvidencePack:
    pack_id: str
    evidence_cutoff_ts: str
    frozen_at: str
    source_artifact_hashes: tuple[str, ...]
    extractor_versions: tuple[str, ...]
    prompt_schema_hash: str
    contradiction_links: tuple[str, ...]
    freshness_state: tuple[str, ...]
    feature_manifest_hash: str
    pack_hash: str
    parent_pack_id: str | None = None

    def __post_init__(self) -> None:
        if not self.pack_id or not self.extractor_versions:
            raise ValueError("frozen evidence pack identity is required")
        cutoff = parse_utc(self.evidence_cutoff_ts)
        frozen = parse_utc(self.frozen_at)
        if frozen < cutoff:
            raise ValueError("pack cannot freeze before evidence cutoff")
        for digest in self.source_artifact_hashes:
            _hash(digest, "source artifact hash")
        _hash(self.prompt_schema_hash, "prompt schema hash")
        _hash(self.feature_manifest_hash, "feature manifest hash")
        _hash(self.pack_hash, "pack hash")
        expected = self.compute_hash()
        if expected != self.pack_hash:
            raise ValueError("evidence pack hash does not match frozen contents")

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("pack_hash")
        value["evidence_cutoff_ts"] = iso_utc(self.evidence_cutoff_ts)
        value["frozen_at"] = iso_utc(self.frozen_at)
        return value

    def compute_hash(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        return self.unsigned_dict() | {"pack_hash": self.pack_hash}

    @classmethod
    def freeze(
        cls,
        *,
        pack_id: str,
        evidence_cutoff_ts: str,
        frozen_at: str,
        source_artifact_hashes: tuple[str, ...],
        extractor_versions: tuple[str, ...],
        prompt_schema_hash: str,
        contradiction_links: tuple[str, ...],
        freshness_state: tuple[str, ...],
        feature_manifest_hash: str,
        parent_pack_id: str | None = None,
    ) -> "EvidencePack":
        unsigned = {
            "pack_id": pack_id,
            "evidence_cutoff_ts": iso_utc(evidence_cutoff_ts),
            "frozen_at": iso_utc(frozen_at),
            "source_artifact_hashes": list(source_artifact_hashes),
            "extractor_versions": list(extractor_versions),
            "prompt_schema_hash": prompt_schema_hash,
            "contradiction_links": list(contradiction_links),
            "freshness_state": list(freshness_state),
            "feature_manifest_hash": feature_manifest_hash,
            "parent_pack_id": parent_pack_id,
        }
        pack_hash = sha256_bytes(canonical_json(unsigned))
        return cls(pack_hash=pack_hash, **{key: tuple(value) if isinstance(value, list) else value for key, value in unsigned.items()})


class EvidencePackStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.packs = self.root / "packs"
        self.manifest = self.root / "manifests" / "packs.jsonl"
        self._manifest_log = AppendOnlyJsonl(self.manifest)

    def freeze(self, pack: EvidencePack) -> EvidencePack:
        path = self.packs / f"{pack.pack_hash}.json"
        if path.exists():
            existing = self.get(pack.pack_hash)
            if existing != pack:
                raise RegistryConflict("evidence pack hash maps to different contents")
            return existing
        immutable_write(path, canonical_json(pack.to_dict()))
        self._manifest_log.append({"record_type": "evidence_pack_frozen", **pack.to_dict()})
        return pack

    def get(self, pack_hash: str) -> EvidencePack:
        path = self.packs / f"{pack_hash}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("pack_hash") != pack_hash:
            raise ValueError("evidence pack hash mismatch")
        for key in ("source_artifact_hashes", "extractor_versions", "contradiction_links", "freshness_state"):
            data[key] = tuple(data[key])
        return EvidencePack(**data)

    def verify_manifest(self) -> int:
        return self._manifest_log.verify()
