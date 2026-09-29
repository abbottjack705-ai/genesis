"""Test-only oracle: build a manifest by hand and ask the REAL frozen verifier (public interfaces only)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from genesis.evidence_pack import EvidencePack
from genesis.feature_manifest import FeatureInputManifestStore, identity_transform_hash
from genesis.pit import BitemporalRecord
from genesis.time import iso_utc, parse_utc

from genesis_adapters.oddspapi import emit
from genesis_adapters.oddspapi.normalize import NormalizedDocument

from .emit_support import doc_json

ZERO = "0" * 64


class NoManifest(Exception):
    """The oracle cannot even build a manifest body (nothing to pin)."""


def _capability_head_row(stores: emit.AdapterStores, decision_at: str) -> dict:
    rows = [row for row in stores.capabilities.log.records()
            if row.get("record_type") == "source_capability_registered"
            and row.get("source_id") == stores.source_id
            and parse_utc(row["recorded_at"]) <= parse_utc(decision_at)]
    if not rows:
        raise NoManifest("no capability row at the cutoff")
    latest = max(parse_utc(row["recorded_at"]) for row in rows)
    return sorted((row for row in rows if parse_utc(row["recorded_at"]) == latest),
                  key=lambda row: row["version"])[-1]


def _observation(stores: emit.AdapterStores, record: BitemporalRecord):
    found = [item for item in stores.evidence.get_observations(record.payload_hash)
             if item.contract_id == stores.contract_id]
    if len(found) != 1:
        raise NoManifest("the record has no unique observation")
    return found[0]


def manifest_body(stores: emit.AdapterStores, pins, *, decision_at: str) -> tuple[dict, tuple[str, ...]]:
    """A manifest body pinning ``pins`` (``(record, selection)`` pairs), and the structured-evidence hashes."""

    capability = _capability_head_row(stores, decision_at)
    inputs, structured, event_id, market_id = [], set(), None, None
    for record, selection in pins:
        observation = _observation(stores, record)
        document = doc_json(stores, record.payload_hash)
        event_id, market_id = document["event_id"], document["market_id"]
        row = next(item for item in stores.pit.log.records()
                   if item.get("record_type") == "pit_record" and item.get("record_id") == record.record_id)
        field_id = f"$.selections.{selection}.odds_decimal"
        inputs.append({
            "role": "feature", "input_key": f"odds.{document['bookmaker_id']}.{selection}",
            "entity_id": record.entity_id, "event_id": event_id, "market_id": market_id,
            "source_id": stores.source_id, "source_contract_id": stores.contract_id,
            "source_capability_version": capability["version"],
            "source_capability_record_hash": capability["record_hash"],
            "raw_artifact_hash": observation.artifact_hash, "observation_id": observation.observation_id,
            "pit_record_id": record.record_id, "pit_record_hash": row["record_hash"], "field_id": field_id,
            "transform_artifact_hash": identity_transform_hash(field_id)})
        if document.get("market_state") == "OPEN":
            structured.add(emit.research_evidence(NormalizedDocument(
                record.entity_id, "OPEN", stores.evidence.get_bytes(record.payload_hash), record.valid_from,
                document["valid_to"], observation.publisher_timestamp), observation, document, stores).digest)
    if not inputs:
        raise NoManifest("nothing to pin")
    inputs.sort(key=lambda ref: (ref["role"], ref["input_key"], ref["entity_id"], ref["source_id"],
                                 ref["observation_id"], ref["pit_record_id"]))
    hashes = tuple(sorted(structured)) or (ZERO,)
    body = {"domain": "genesis.feature-input-manifest.v1", "schema_version": "feature-input-manifest-v1",
            "event_id": event_id, "market_id": market_id, "evidence_cutoff_ts": iso_utc(decision_at),
            "required_inputs": inputs, "structured_evidence_hashes": list(hashes)}
    return body, hashes


def verifier_verdict(stores: emit.AdapterStores, pins, *, decision_at: str, scratch: Path,
                     label: str = "m") -> tuple[bool, str]:
    """Does the frozen ``verify_for_pack`` accept a manifest that pins ``pins`` at ``decision_at``?"""

    try:
        body, hashes = manifest_body(stores, pins, decision_at=decision_at)
    except NoManifest as exc:
        return False, f"NoManifest:{exc}"
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", label)
    manifests = FeatureInputManifestStore(scratch / f"manifests-{safe}", bindings=stores.bindings)
    try:
        digest = manifests.publish(body)
        artifacts = tuple(sorted({item["raw_artifact_hash"] for item in body["required_inputs"]}))
        pack = EvidencePack.freeze(
            pack_id="pack-" + digest[:16], evidence_cutoff_ts=decision_at, frozen_at=decision_at,
            source_artifact_hashes=artifacts, extractor_versions=(stores.derivation_version,),
            prompt_schema_hash=ZERO, contradiction_links=(), freshness_state=(), feature_manifest_hash=digest,
            structured_evidence_hashes=hashes)
        manifests.verify_for_pack(pack, event_id=body["event_id"], market_id=body["market_id"], pit=stores.pit,
                                  evidence=stores.evidence, structured_evidence=stores.structured)
    except Exception as exc:                              # the oracle's whole job is to report any refusal
        return False, f"{type(exc).__name__}:{exc}"
    return True, ""
