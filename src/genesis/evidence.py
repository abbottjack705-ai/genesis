"""Content-addressed evidence with separate immutable observation identity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .canonical import ResearchEvidence
from .provenance import AvailabilityClass, SourceContract, SourceContractRegistry
from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, immutable_write, read_json, sha256_bytes
from .time import iso_utc, parse_utc


def _digest(value: str, name: str) -> str:
    if len(value) != 64:
        raise ValueError(f"{name} must be a full SHA-256 digest")
    int(value, 16)
    return value


@dataclass(frozen=True)
class EvidenceContent:
    artifact_hash: str
    byte_length: int

    def __post_init__(self) -> None:
        _digest(self.artifact_hash, "artifact_hash")
        if self.byte_length < 0:
            raise ValueError("byte_length cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceObservation:
    observation_id: str
    artifact_hash: str
    contract_id: str
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
    schema_version: str = "evidence-observation-v2"

    def __post_init__(self) -> None:
        _digest(self.observation_id, "observation_id")
        _digest(self.artifact_hash, "artifact_hash")
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
        if self.compute_id() != self.observation_id:
            raise ValueError("observation_id does not match observation contents")

    def unsigned_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("observation_id")
        value["availability_class"] = self.availability_class.value
        for key in (
            "retrieved_at",
            "first_seen_at",
            "parse_ready_at",
            "publisher_timestamp",
            "valid_from",
            "valid_to",
        ):
            if value[key] is not None:
                value[key] = iso_utc(value[key])
        return value

    def compute_id(self) -> str:
        return sha256_bytes(canonical_json(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {"observation_id": self.observation_id, **self.unsigned_dict()}


# Compatibility name: metadata is now explicitly observation identity and can
# occur many times for one raw content object.
EvidenceMetadata = EvidenceObservation


class EvidenceStore:
    """Immutable raw objects plus append-only, contract-validated observations."""

    def __init__(self, root: str | Path, *, contracts: SourceContractRegistry):
        if not isinstance(contracts, SourceContractRegistry):
            raise TypeError("EvidenceStore requires a SourceContractRegistry authority")
        self.root = Path(root)
        self.contracts = contracts
        self.objects = self.root / "objects"
        self.content = self.root / "content"
        self.observations = self.root / "observations"
        self.manifest = self.root / "manifests" / "evidence.jsonl"
        self._manifest_log = AppendOnlyJsonl(self.manifest)

    def _object_path(self, digest: str) -> Path:
        return self.objects / digest[:2] / digest

    @staticmethod
    def _validate_contract(
        contract: SourceContract,
        *,
        provider: str,
        source_type: str,
        source_uri: str,
        parser_version: str,
        licensing_note: str,
        availability_class: AvailabilityClass,
    ) -> None:
        mismatches: list[str] = []
        for name, actual, expected in (
            ("provider", provider, contract.provider),
            ("source_type", source_type, contract.source_type),
            ("parser_version", parser_version, contract.parser_version),
            ("licensing_note", licensing_note, contract.licensing_note),
            ("availability_class", availability_class, contract.availability_class),
        ):
            if actual != expected:
                mismatches.append(name)
        if not fnmatchcase(source_uri, contract.uri_pattern):
            mismatches.append("source_uri")
        if (
            availability_class == AvailabilityClass.PROSPECTIVE_CAPTURED
            and not contract.supports_prospective_capture
        ):
            mismatches.append("supports_prospective_capture")
        if (
            availability_class == AvailabilityClass.HISTORICAL_RECONSTRUCTED
            and not contract.supports_historical_reconstruction
        ):
            mismatches.append("supports_historical_reconstruction")
        if availability_class in {AvailabilityClass.FUTURE_LABEL, AvailabilityClass.UNKNOWN}:
            mismatches.append("decision_usable_availability")
        if mismatches:
            raise ValueError(
                f"observation conflicts with source contract {contract.contract_id}: "
                + ", ".join(mismatches)
            )

    def publish(
        self,
        payload: bytes,
        *,
        contract_id: str,
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
    ) -> EvidenceObservation:
        contract = self.contracts.get(contract_id)
        availability_class = AvailabilityClass(availability_class)
        self._validate_contract(
            contract,
            provider=provider,
            source_type=source_type,
            source_uri=source_uri,
            parser_version=parser_version,
            licensing_note=licensing_note,
            availability_class=availability_class,
        )
        digest = sha256_bytes(payload)
        retrieved = iso_utc(retrieved_at)
        fields: dict[str, Any] = {
            "artifact_hash": digest,
            "contract_id": contract_id,
            "source_uri": source_uri,
            "provider": provider,
            "source_type": source_type,
            "retrieved_at": retrieved,
            "first_seen_at": iso_utc(first_seen_at or retrieved),
            "parse_ready_at": iso_utc(parse_ready_at),
            "publisher_timestamp": iso_utc(publisher_timestamp) if publisher_timestamp else None,
            "valid_from": iso_utc(valid_from) if valid_from else None,
            "valid_to": iso_utc(valid_to) if valid_to else None,
            "upstream_version": upstream_version,
            "parser_version": parser_version,
            "content_type": content_type,
            "byte_length": len(payload),
            "licensing_note": licensing_note,
            "availability_class": availability_class,
            "schema_version": "evidence-observation-v2",
        }
        normalized = dict(fields)
        normalized["availability_class"] = availability_class.value
        observation = EvidenceObservation(
            observation_id=sha256_bytes(canonical_json(normalized)), **fields
        )
        content = EvidenceContent(digest, len(payload))
        immutable_write(self._object_path(digest), payload)
        immutable_write(self.content / f"{digest}.json", canonical_json(content.to_dict()))
        immutable_write(
            self.observations / f"{observation.observation_id}.json",
            canonical_json(observation.to_dict()),
        )

        record = {"record_type": "evidence_observation", **observation.to_dict()}

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            matches = [
                row for row in rows if row.get("observation_id") == observation.observation_id
            ]
            if not matches:
                return record
            expected = observation.to_dict()
            if all({key: row.get(key) for key in expected} == expected for row in matches):
                return None
            raise RegistryConflict("observation identity maps to conflicting contents")

        self._manifest_log.transaction(build)
        return observation

    def get_bytes(self, artifact_hash: str) -> bytes:
        payload = self._object_path(artifact_hash).read_bytes()
        if sha256_bytes(payload) != artifact_hash:
            raise ValueError(f"evidence hash mismatch: {artifact_hash}")
        content = EvidenceContent(**read_json(self.content / f"{artifact_hash}.json"))
        if content.byte_length != len(payload):
            raise ValueError("evidence byte length mismatch")
        return payload

    def get_observation(self, observation_id: str) -> EvidenceObservation:
        data = read_json(self.observations / f"{observation_id}.json")
        data["availability_class"] = AvailabilityClass(data["availability_class"])
        observation = EvidenceObservation(**data)
        if observation.observation_id != observation_id:
            raise ValueError("observation identity mismatch")
        self.get_bytes(observation.artifact_hash)
        return observation

    def get_observations(self, artifact_hash: str) -> tuple[EvidenceObservation, ...]:
        ids = {
            row["observation_id"]
            for row in self._manifest_log.records()
            if row.get("record_type") == "evidence_observation"
            and row.get("artifact_hash") == artifact_hash
        }
        return tuple(self.get_observation(value) for value in sorted(ids))

    def get_metadata(self, artifact_hash: str) -> dict[str, Any]:
        observations = self.get_observations(artifact_hash)
        if len(observations) != 1:
            raise ValueError("artifact metadata is ambiguous; use get_observations()")
        return observations[0].to_dict()

    def import_legacy_metadata(
        self, artifact_hash: str, *, contract_id: str
    ) -> EvidenceObservation:
        """Deterministically migrate one old artifact-keyed metadata record.

        The caller must name an already-registered exact contract; migration
        never invents source authority that the old record did not preserve.
        """

        data = read_json(self.root / "metadata" / f"{artifact_hash}.json")
        if data.get("artifact_hash") != artifact_hash:
            raise ValueError("legacy metadata artifact hash mismatch")
        payload = self._object_path(artifact_hash).read_bytes()
        return self.publish(
            payload,
            contract_id=contract_id,
            source_uri=data["source_uri"],
            provider=data["provider"],
            source_type=data["source_type"],
            retrieved_at=data["retrieved_at"],
            first_seen_at=data.get("first_seen_at"),
            parse_ready_at=data["parse_ready_at"],
            publisher_timestamp=data.get("publisher_timestamp"),
            valid_from=data.get("valid_from"),
            valid_to=data.get("valid_to"),
            upstream_version=data.get("upstream_version"),
            parser_version=data["parser_version"],
            content_type=data["content_type"],
            licensing_note=data["licensing_note"],
            availability_class=AvailabilityClass(data["availability_class"]),
        )

    def verify_manifest(self) -> int:
        rows = self._manifest_log.records()
        for row in rows:
            if row.get("record_type") != "evidence_observation":
                raise ValueError("unknown evidence manifest record")
            observation = self.get_observation(row["observation_id"])
            expected = observation.to_dict()
            if {key: row.get(key) for key in expected} != expected:
                raise ValueError("evidence manifest observation mismatch")
        return len(rows)


class StructuredEvidenceStore:
    """Immutable canonical ResearchEvidence objects addressed by their digest."""

    def __init__(self, root: str | Path, *, evidence: EvidenceStore):
        if not isinstance(evidence, EvidenceStore):
            raise TypeError("StructuredEvidenceStore requires an EvidenceStore authority")
        self.root = Path(root)
        self.evidence = evidence

    def _verify_source_ref(self, source_ref: dict[str, Any]) -> None:
        observation_id = source_ref.get("observation_id")
        if not observation_id:
            raise ValueError("structured evidence is legacy/audit-only")
        observation = self.evidence.get_observation(observation_id)
        expected = {
            "artifact_hash": observation.artifact_hash,
            "contract_id": observation.contract_id,
            "source_uri": observation.source_uri,
            "retrieved_at": observation.retrieved_at,
            "parse_ready_at": observation.parse_ready_at,
            "availability_class": observation.availability_class.value,
            "parser_version": observation.parser_version,
            "observation_id": observation.observation_id,
        }
        for key, value in expected.items():
            if source_ref.get(key) != value:
                raise ValueError(f"structured evidence provenance mismatch: {key}")

    def publish(self, evidence: ResearchEvidence) -> str:
        if not evidence.is_authoritative_v2:
            raise ValueError("structured evidence lacks an exact observation identity")
        self._verify_source_ref(evidence.source_ref.to_dict())
        digest = evidence.digest
        immutable_write(self.root / f"{digest}.json", canonical_json(evidence.to_dict()))
        return digest

    def verify(self, digest: str) -> dict[str, Any]:
        _digest(digest, "structured evidence digest")
        path = self.root / f"{digest}.json"
        if not path.exists():
            raise ValueError(f"structured evidence does not exist: {digest}")
        data = read_json(path)
        if sha256_bytes(canonical_json(data)) != digest:
            raise ValueError(f"structured evidence hash mismatch: {digest}")
        self._verify_source_ref(data.get("source_ref", {}))
        return data
