"""Content-addressed evidence objects and append-only provenance manifests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .provenance import AvailabilityClass
from .registry import AppendOnlyJsonl
from .repro import canonical_json, immutable_write, read_json, sha256_bytes
from .time import iso_utc, parse_utc


@dataclass(frozen=True)
class EvidenceMetadata:
    artifact_hash: str
    source_uri: str
    provider: str
    source_type: str
    retrieved_at: str
    first_seen_at: str
    parse_ready_at: str
    publisher_timestamp: str | None
    valid_from: str | None
    valid_to: str | None
    upstream_version: str | None
    parser_version: str
    content_type: str
    byte_length: int
    licensing_note: str
    availability_class: AvailabilityClass

    def __post_init__(self) -> None:
        if len(self.artifact_hash) != 64:
            raise ValueError("artifact_hash must be a full SHA-256 digest")
        for value in (
            self.retrieved_at,
            self.first_seen_at,
            self.parse_ready_at,
            self.publisher_timestamp,
            self.valid_from,
            self.valid_to,
        ):
            if value is not None:
                parse_utc(value)
        if parse_utc(self.first_seen_at) > parse_utc(self.retrieved_at):
            raise ValueError("first_seen_at cannot follow retrieved_at")
        if parse_utc(self.parse_ready_at) < parse_utc(self.retrieved_at):
            raise ValueError("parse_ready_at cannot precede retrieved_at")
        if self.byte_length < 0:
            raise ValueError("byte_length cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"availability_class": self.availability_class.value}


class EvidenceStore:
    """A small file-backed immutable object store suitable for offline use.

    Objects are addressed by their full SHA-256.  Metadata and a hash-chained
    manifest are separately persisted so an audit can distinguish missing,
    unreferenced, and tampered evidence.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.metadata = self.root / "metadata"
        self.manifest = self.root / "manifests" / "evidence.jsonl"
        self._manifest_log = AppendOnlyJsonl(self.manifest)

    def _object_path(self, digest: str) -> Path:
        return self.objects / digest[:2] / digest

    def publish(
        self,
        payload: bytes,
        *,
        source_uri: str,
        provider: str,
        source_type: str,
        retrieved_at: str,
        parse_ready_at: str,
        parser_version: str,
        content_type: str,
        licensing_note: str,
        availability_class: AvailabilityClass,
        publisher_timestamp: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        upstream_version: str | None = None,
        first_seen_at: str | None = None,
    ) -> EvidenceMetadata:
        digest = sha256_bytes(payload)
        retrieved = iso_utc(retrieved_at)
        first_seen = iso_utc(first_seen_at or retrieved)
        ready = iso_utc(parse_ready_at)
        metadata = EvidenceMetadata(
            artifact_hash=digest,
            source_uri=source_uri,
            provider=provider,
            source_type=source_type,
            retrieved_at=retrieved,
            first_seen_at=first_seen,
            parse_ready_at=ready,
            publisher_timestamp=iso_utc(publisher_timestamp) if publisher_timestamp else None,
            valid_from=iso_utc(valid_from) if valid_from else None,
            valid_to=iso_utc(valid_to) if valid_to else None,
            upstream_version=upstream_version,
            parser_version=parser_version,
            content_type=content_type,
            byte_length=len(payload),
            licensing_note=licensing_note,
            availability_class=availability_class,
        )
        immutable_write(self._object_path(digest), payload)
        immutable_write(self.metadata / f"{digest}.json", canonical_json(metadata.to_dict()))
        self.append_manifest(
            {
                "record_type": "evidence_artifact",
                "artifact_hash": digest,
                "metadata_hash": sha256_bytes(canonical_json(metadata.to_dict())),
                "source_uri": source_uri,
            }
        )
        return metadata

    def get_bytes(self, artifact_hash: str) -> bytes:
        payload = self._object_path(artifact_hash).read_bytes()
        if sha256_bytes(payload) != artifact_hash:
            raise ValueError(f"evidence hash mismatch: {artifact_hash}")
        return payload

    def get_metadata(self, artifact_hash: str) -> dict[str, Any]:
        data = read_json(self.metadata / f"{artifact_hash}.json")
        if data.get("artifact_hash") != artifact_hash:
            raise ValueError("evidence metadata hash mismatch")
        return data

    def append_manifest(self, record: dict[str, Any]) -> str:
        """Append one hash-chained record; never rewrite an earlier line."""

        return self._manifest_log.append(record)

    def verify_manifest(self) -> int:
        return self._manifest_log.verify()
