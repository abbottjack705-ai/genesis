"""Exact frozen input-manifest authority for offline/PAPER qualification."""

from __future__ import annotations

import json
from pathlib import Path

from .evidence import EvidenceStore, StructuredEvidenceStore
from .evidence_pack import EvidencePack
from .pit import BitemporalRecord, PITStore, SourceCapabilityRegistry
from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, immutable_write, sha256_bytes
from .time import AvailabilityWindow, iso_utc, parse_utc


_MANIFEST_KEYS = {
    "domain", "schema_version", "event_id", "market_id",
    "evidence_cutoff_ts", "required_inputs", "structured_evidence_hashes",
}
_INPUT_KEYS = {
    "role", "input_key", "entity_id", "event_id", "market_id", "source_id",
    "source_contract_id", "source_capability_version",
    "source_capability_record_hash", "raw_artifact_hash", "observation_id",
    "pit_record_id", "pit_record_hash", "field_id", "transform_artifact_hash",
}
_DIGEST_INPUT_KEYS = {
    "source_capability_record_hash", "raw_artifact_hash", "observation_id",
    "pit_record_hash",
}


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be a full SHA-256 digest")
    int(value, 16)
    if value != value.lower():
        raise ValueError(f"{name} must use lowercase SHA-256 hex")
    return value


def _pairs_without_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def identity_transform_hash(field_id: str) -> str:
    if not isinstance(field_id, str) or not field_id.startswith("$."):
        raise ValueError("identity transform requires an explicit JSON field path")
    return sha256_bytes(canonical_json({
        "domain": "genesis.identity-transform.v1", "field_id": field_id,
    }))


class SourceInputBindingStore:
    """Durable operator-owned mapping of a source contract to a PIT source."""

    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    def register(self, *, source_id: str, source_contract_id: str,
                 provider: str, approval_reference: str) -> None:
        if not all(isinstance(item, str) and item for item in (
            source_id, source_contract_id, provider, approval_reference,
        )):
            raise ValueError("source input binding authority is incomplete")
        payload = {
            "record_type": "source_input_binding_approved",
            "schema_version": "source-input-binding-v1",
            "source_id": source_id,
            "source_contract_id": source_contract_id,
            "provider": provider,
            "approval_reference": approval_reference,
        }

        def build(rows: tuple[dict, ...]) -> dict | None:
            matching = [row for row in rows if row.get("source_id") == source_id
                        or row.get("source_contract_id") == source_contract_id]
            for row in rows:
                if (row.get("record_type"), row.get("schema_version")) != (
                    "source_input_binding_approved", "source-input-binding-v1"
                ):
                    raise RegistryConflict("unsupported source input binding")
            if matching:
                if len(matching) == 1 and all(
                    matching[0].get(key) == value for key, value in payload.items()
                ):
                    return None
                raise RegistryConflict("source input binding conflicts with approved mapping")
            return payload

        self.log.transaction(build)

    def require(self, *, source_id: str, source_contract_id: str, provider: str) -> None:
        rows = self.log.records()
        for row in rows:
            if (row.get("record_type"), row.get("schema_version")) != (
                "source_input_binding_approved", "source-input-binding-v1"
            ) or not all(isinstance(row.get(key), str) and row[key] for key in (
                "source_id", "source_contract_id", "provider", "approval_reference",
            )):
                raise RegistryConflict("invalid source input binding history")
        matching = [row for row in rows if row["source_id"] == source_id
                    or row["source_contract_id"] == source_contract_id]
        if len(matching) != 1 or any(matching[0][key] != value for key, value in (
            ("source_id", source_id), ("source_contract_id", source_contract_id),
            ("provider", provider),
        )):
            raise RegistryConflict("source contract and PIT source have no exact approved mapping")


class FeatureInputManifestStore:
    """Content-addressed manifests; a digest-shaped reference never suffices."""

    def __init__(self, root: str | Path, *, bindings: SourceInputBindingStore):
        if not isinstance(bindings, SourceInputBindingStore):
            raise TypeError("feature manifest requires source input binding authority")
        self.root = Path(root)
        self.bindings = bindings

    @staticmethod
    def validate(body: dict) -> dict:
        if not isinstance(body, dict) or set(body) != _MANIFEST_KEYS:
            raise ValueError("feature input manifest schema is incomplete or unsupported")
        if (body["domain"], body["schema_version"]) != (
            "genesis.feature-input-manifest.v1", "feature-input-manifest-v1"
        ):
            raise ValueError("unsupported feature input manifest version")
        if not all(isinstance(body[key], str) and body[key] for key in (
            "event_id", "market_id",
        )):
            raise ValueError("feature manifest event/market identity is incomplete")
        if body["evidence_cutoff_ts"] != iso_utc(body["evidence_cutoff_ts"]):
            raise ValueError("feature manifest cutoff is not canonical UTC")
        refs = body["required_inputs"]
        hashes = body["structured_evidence_hashes"]
        if not isinstance(refs, list) or not refs or not isinstance(hashes, list) or not hashes:
            raise ValueError("feature manifest has no required inputs/evidence")
        if hashes != sorted(set(hashes)):
            raise ValueError("structured evidence identities are not sorted and unique")
        for item in hashes:
            _digest(item, "structured evidence hash")
        sort_keys: list[tuple] = []
        logical_keys: set[tuple] = set()
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != _INPUT_KEYS:
                raise ValueError("required input schema is incomplete or unsupported")
            if ref["role"] not in {"feature", "evidence"}:
                raise ValueError("invalid input role")
            for key in _INPUT_KEYS - _DIGEST_INPUT_KEYS - {
                "field_id", "transform_artifact_hash",
            }:
                if not isinstance(ref[key], str) or not ref[key]:
                    raise ValueError(f"required input {key} is incomplete")
            for key in _DIGEST_INPUT_KEYS:
                _digest(ref[key], key)
            if ref["event_id"] != body["event_id"] or ref["market_id"] != body["market_id"]:
                raise ValueError("required input has a different event/market")
            if ref["role"] == "feature":
                if not isinstance(ref["field_id"], str) or not ref["field_id"]:
                    raise ValueError("feature has no exact field")
                _digest(ref["transform_artifact_hash"], "transform artifact")
            elif ref["field_id"] is not None or ref["transform_artifact_hash"] is not None:
                raise ValueError("evidence-only input cannot claim a feature transform")
            logical = (ref["role"], ref["input_key"])
            if logical in logical_keys:
                raise ValueError("duplicate required input key")
            logical_keys.add(logical)
            sort_keys.append((ref["role"], ref["input_key"], ref["entity_id"],
                              ref["source_id"], ref["observation_id"], ref["pit_record_id"]))
        if sort_keys != sorted(set(sort_keys)):
            raise ValueError("required input references are not sorted and unique")
        return body

    def publish(self, body: dict) -> str:
        self.validate(body)
        digest = sha256_bytes(canonical_json(body))
        immutable_write(self.root / f"{digest}.json", canonical_json(body))
        return digest

    def get(self, manifest_hash: str) -> dict:
        _digest(manifest_hash, "feature manifest hash")
        body = json.loads(
            (self.root / f"{manifest_hash}.json").read_text(encoding="utf-8"),
            object_pairs_hook=_pairs_without_duplicates,
        )
        self.validate(body)
        if sha256_bytes(canonical_json(body)) != manifest_hash:
            raise ValueError("feature manifest bytes do not match its identity")
        return body

    def verify_for_pack(self, pack: EvidencePack, *, event_id: str, market_id: str,
                        pit: PITStore,
                        evidence: EvidenceStore,
                        structured_evidence: StructuredEvidenceStore) -> tuple[BitemporalRecord, ...]:
        body = self.get(pack.feature_manifest_hash)
        cutoff = body["evidence_cutoff_ts"]
        if body["event_id"] != event_id or body["market_id"] != market_id:
            raise ValueError("manifest is for a different decision event/market")
        if cutoff != iso_utc(pack.evidence_cutoff_ts):
            raise ValueError("manifest and pack cutoffs differ")
        if tuple(body["structured_evidence_hashes"]) != tuple(sorted(pack.structured_evidence_hashes)):
            raise ValueError("manifest and pack structured evidence differ")
        if pit.log is None:
            raise ValueError("decision PIT has no durable exact record authority")
        pit_rows = pit.log.records()
        capability_rows = pit.capabilities.log.records()
        verified: list[BitemporalRecord] = []
        observations: set[str] = set()
        raw_hashes: set[str] = set()
        for ref in body["required_inputs"]:
            source_id = ref["source_id"]
            contract_id = ref["source_contract_id"]
            contract = evidence.contracts.get(contract_id)
            self.bindings.require(source_id=source_id, source_contract_id=contract_id,
                                  provider=contract.provider)
            applicable = [row for row in capability_rows
                          if row.get("record_type") == "source_capability_registered"
                          and row.get("source_id") == source_id
                          and parse_utc(row["recorded_at"]) <= parse_utc(cutoff)]
            if not applicable:
                raise ValueError("source capability is unavailable at evidence cutoff")
            latest_time = max(parse_utc(row["recorded_at"]) for row in applicable)
            latest = [row for row in applicable if parse_utc(row["recorded_at"]) == latest_time]
            if len(latest) != 1 or latest[0]["record_hash"] != ref["source_capability_record_hash"]:
                raise ValueError("required source capability head differs")
            capability = pit.capabilities.require_ready_at(source_id, cutoff)
            if (capability.version != ref["source_capability_version"]
                    or capability.provider != contract.provider):
                raise ValueError("source capability/provider identity differs")
            observation = evidence.get_observation(ref["observation_id"])
            evidence._validate_contract(
                contract,
                provider=observation.provider,
                source_type=observation.source_type,
                source_uri=observation.source_uri,
                parser_version=observation.parser_version,
                licensing_note=observation.licensing_note,
                availability_class=observation.availability_class,
            )
            if (observation.contract_id != contract_id
                    or observation.provider != contract.provider
                    or observation.artifact_hash != ref["raw_artifact_hash"]
                    or parse_utc(observation.retrieved_at) > parse_utc(cutoff)
                    or parse_utc(observation.parse_ready_at) > parse_utc(cutoff)
                    or (observation.publisher_timestamp is not None
                        and parse_utc(observation.publisher_timestamp) > parse_utc(cutoff))
                    or (observation.valid_from is not None
                        and parse_utc(observation.valid_from) > parse_utc(cutoff))
                    or (observation.valid_to is not None
                        and parse_utc(cutoff) >= parse_utc(observation.valid_to))):
                raise ValueError("required observation is not exact and ready at cutoff")
            contract.check_window(
                AvailabilityWindow(
                    parse_utc(observation.retrieved_at), parse_utc(observation.parse_ready_at)
                ), cutoff,
            )
            matches = [row for row in pit_rows if row.get("record_type") == "pit_record"
                       and row.get("record_hash") == ref["pit_record_hash"]]
            if len(matches) != 1:
                raise ValueError("required exact PIT row is missing")
            row = matches[0]
            record = BitemporalRecord(**{key: row[key] for key in BitemporalRecord.__dataclass_fields__})
            if (record.record_id != ref["pit_record_id"]
                    or record.entity_id != ref["entity_id"]
                    or record.source_id != source_id
                    or record.payload_hash != observation.artifact_hash
                    or not record.admissible_at(cutoff)):
                raise ValueError("required PIT identity is not causally admissible")
            same_scope = [BitemporalRecord(**{key: item[key] for key in BitemporalRecord.__dataclass_fields__})
                          for item in pit_rows if item.get("record_type") == "pit_record"
                          and item.get("entity_id") == record.entity_id
                          and item.get("source_id") == source_id]
            eligible = [item for item in same_scope if item.admissible_at(cutoff)]
            if not eligible:
                raise ValueError("required PIT scope has no admissible head")
            latest_valid = max(parse_utc(item.valid_from) for item in eligible)
            heads = [item for item in eligible if parse_utc(item.valid_from) == latest_valid]
            if len(heads) != 1 or heads[0] != record:
                raise ValueError("required PIT row is not the unique as-of head")
            if ref["role"] == "feature":
                if ref["transform_artifact_hash"] != identity_transform_hash(ref["field_id"]):
                    raise ValueError("unapproved or unresolved feature transform")
                raw = json.loads(evidence.get_bytes(observation.artifact_hash))
                path = ref["field_id"][2:].split(".")
                for part in path:
                    if not isinstance(raw, dict) or part not in raw:
                        raise ValueError("required feature field is absent from exact bytes")
                    raw = raw[part]
            verified.append(record)
            observations.add(observation.observation_id)
            raw_hashes.add(observation.artifact_hash)
        if raw_hashes != set(pack.source_artifact_hashes):
            raise ValueError("manifest and pack raw inputs differ")
        for digest in body["structured_evidence_hashes"]:
            row = structured_evidence.verify(digest)
            if (row.get("event_id") != event_id
                    or row["source_ref"]["observation_id"] not in observations):
                raise ValueError("structured evidence source was not a required input")
        return tuple(verified)
