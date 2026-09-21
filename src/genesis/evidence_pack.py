"""Immutable frozen evidence packs and append-only pack manifests."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .evidence import StructuredEvidenceStore
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
    schema_version: str = "evidence-pack-v1-legacy"
    structured_evidence_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.pack_id or not self.extractor_versions:
            raise ValueError("frozen evidence pack identity is required")
        cutoff = parse_utc(self.evidence_cutoff_ts)
        frozen = parse_utc(self.frozen_at)
        if frozen < cutoff:
            raise ValueError("pack cannot freeze before evidence cutoff")
        for digest in self.source_artifact_hashes:
            _hash(digest, "source artifact hash")
        for digest in self.structured_evidence_hashes:
            _hash(digest, "structured evidence hash")
        if self.schema_version == "evidence-pack-v2" and not self.structured_evidence_hashes:
            raise ValueError("V2 evidence packs require structured evidence identity")
        if self.schema_version not in {"evidence-pack-v1-legacy", "evidence-pack-v2"}:
            raise ValueError("unknown evidence pack schema")
        _hash(self.prompt_schema_hash, "prompt schema hash")
        _hash(self.feature_manifest_hash, "feature manifest hash")
        _hash(self.pack_hash, "pack hash")
        expected = self.compute_hash()
        if expected != self.pack_hash:
            raise ValueError("evidence pack hash does not match frozen contents")

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("pack_hash")
        if self.schema_version == "evidence-pack-v1-legacy":
            value.pop("schema_version")
            value.pop("structured_evidence_hashes")
        value["evidence_cutoff_ts"] = iso_utc(self.evidence_cutoff_ts)
        value["frozen_at"] = iso_utc(self.frozen_at)
        return value

    def compute_hash(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        value = self.unsigned_dict() | {"pack_hash": self.pack_hash}
        if self.schema_version == "evidence-pack-v1-legacy":
            value["schema_version"] = self.schema_version
            value["structured_evidence_hashes"] = []
        return value

    @property
    def authoritative_complete(self) -> bool:
        return (
            self.schema_version == "evidence-pack-v2"
            and bool(self.structured_evidence_hashes)
        )

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
        structured_evidence_hashes: tuple[str, ...] | None = None,
    ) -> "EvidencePack":
        schema_version = (
            "evidence-pack-v1-legacy"
            if structured_evidence_hashes is None
            else "evidence-pack-v2"
        )
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
            "schema_version": schema_version,
            "structured_evidence_hashes": list(structured_evidence_hashes or ()),
        }
        hash_input = dict(unsigned)
        if schema_version == "evidence-pack-v1-legacy":
            hash_input.pop("schema_version")
            hash_input.pop("structured_evidence_hashes")
        pack_hash = sha256_bytes(canonical_json(hash_input))
        return cls(pack_hash=pack_hash, **{key: tuple(value) if isinstance(value, list) else value for key, value in unsigned.items()})


class EvidencePackStore:
    def __init__(
        self,
        root: str | Path,
        *,
        structured_evidence: StructuredEvidenceStore | None = None,
    ):
        self.root = Path(root)
        self.structured_evidence = structured_evidence
        self.packs = self.root / "packs"
        self.manifest = self.root / "manifests" / "packs.jsonl"
        self._manifest_log = AppendOnlyJsonl(self.manifest)

    def freeze(self, pack: EvidencePack) -> EvidencePack:
        if pack.authoritative_complete:
            if self.structured_evidence is None:
                raise ValueError("authoritative pack requires a structured evidence store")
            for digest in pack.structured_evidence_hashes:
                self.structured_evidence.verify(digest)
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
        data.setdefault("schema_version", "evidence-pack-v1-legacy")
        data.setdefault("structured_evidence_hashes", [])
        for key in ("source_artifact_hashes", "extractor_versions", "contradiction_links", "freshness_state", "structured_evidence_hashes"):
            data[key] = tuple(data[key])
        return EvidencePack(**data)

    def use_authoritatively(self, pack_hash: str) -> EvidencePack:
        pack = self.get(pack_hash)
        if not pack.authoritative_complete:
            raise ValueError("legacy evidence pack is audit-only")
        if self.structured_evidence is None:
            raise ValueError("structured evidence authority is unavailable")
        for digest in pack.structured_evidence_hashes:
            self.structured_evidence.verify(digest)
        return pack

    def verify_manifest(self) -> int:
        return self._manifest_log.verify()
