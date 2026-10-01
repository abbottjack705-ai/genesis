"""FeatureInputManifest-v1 bodies for one (event, market) at a cutoff ``D`` (design 11.5).

The builder never decides admissibility itself: every pinned book must be what the shared predicate
``reader.admissible_head`` returns for its entity at ``D``, so builder, reader and the frozen verifier
cannot diverge. Only OPEN heads can be pinned, and only their exact price fields.
"""

from __future__ import annotations

from typing import Any, Sequence

from genesis.feature_manifest import FeatureInputManifestStore, identity_transform_hash
from genesis.time import iso_utc, parse_utc

from genesis_adapters.oddspapi import emit
from genesis_adapters.oddspapi.normalize import NormalizedDocument
from genesis_adapters.oddspapi.reader import UsableBook, admissible_head

DOMAIN = "genesis.feature-input-manifest.v1"
SCHEMA_VERSION = "feature-input-manifest-v1"
ROLE_FEATURE = "feature"


class ManifestError(ValueError):
    """A manifest that would pin anything but the current usable heads of one event and market."""


def _capability_head(stores, source_id: str, decision_at: str) -> dict[str, Any]:
    rows = [row for row in stores.capabilities.log.records()
            if row.get("record_type") == "source_capability_registered" and row.get("source_id") == source_id
            and parse_utc(row["recorded_at"]) <= parse_utc(decision_at)]
    if not rows:
        raise ManifestError("no capability row at the cutoff")
    latest = max(parse_utc(row["recorded_at"]) for row in rows)
    heads = [row for row in rows if parse_utc(row["recorded_at"]) == latest]
    if len(heads) != 1:
        raise ManifestError("the capability head at the cutoff is not unique")
    return heads[0]


def _pit_row(stores, record_id: str) -> dict[str, Any]:
    rows = [row for row in stores.pit.log.records()
            if row.get("record_type") == "pit_record" and row.get("record_id") == record_id]
    if len(rows) != 1:
        raise ManifestError("the pinned PIT record is not unique")
    return rows[0]


def build_manifest_body(*, event_id: str, market_id: str, decision_at: str, books: Sequence[UsableBook],
                        selections: Sequence[str], stores, derivation_check) -> dict[str, Any]:
    """The manifest body pinning ``selections`` of every book in ``books`` (all heads of one event and market).

    Every pinned head is re-checked with the mandatory derivation verifier (design 12.3 step 7, HA-12)."""

    cutoff = iso_utc(decision_at)
    if not books or not selections or len(set(selections)) != len(selections):
        raise ManifestError("a manifest needs at least one book and distinct selections")
    inputs: list[dict[str, Any]] = []
    structured: set[str] = set()
    for book in books:
        current = admissible_head(book.entity_id, cutoff, stores=stores, derivation_check=derivation_check)
        if not isinstance(current, UsableBook) or current.record != book.record \
                or current.observation != book.observation:
            raise ManifestError("a pinned book is not the usable head at the cutoff")
        document = current.document
        if document["event_id"] != event_id or document["market_id"] != market_id:
            raise ManifestError("a pinned book belongs to another event or market")
        capability = _capability_head(stores, current.source_id, cutoff)
        pit_row = _pit_row(stores, current.record.record_id)
        for selection in selections:
            if selection not in document.get("selections", {}):
                raise ManifestError("the book has no such selection")
            field_id = f"$.selections.{selection}.odds_decimal"
            inputs.append({
                "role": ROLE_FEATURE, "input_key": f"odds.{document['bookmaker_id']}.{selection}",
                "entity_id": current.entity_id, "event_id": event_id, "market_id": market_id,
                "source_id": current.source_id, "source_contract_id": current.contract_id,
                "source_capability_version": capability["version"],
                "source_capability_record_hash": capability["record_hash"],
                "raw_artifact_hash": current.observation.artifact_hash,        # the NORMALIZED artifact (11.5)
                "observation_id": current.observation.observation_id,
                "pit_record_id": current.record.record_id, "pit_record_hash": pit_row["record_hash"],
                "field_id": field_id, "transform_artifact_hash": identity_transform_hash(field_id)})
        research = emit.research_evidence(
            NormalizedDocument(current.entity_id, "OPEN", stores.evidence.get_bytes(current.record.payload_hash),
                               current.record.valid_from, document["valid_to"],
                               current.observation.publisher_timestamp),
            current.observation, document, stores)
        stores.structured.verify(research.digest)                  # it must have been published by emission
        structured.add(research.digest)
    inputs.sort(key=lambda ref: (ref["role"], ref["input_key"], ref["entity_id"], ref["source_id"],
                                 ref["observation_id"], ref["pit_record_id"]))
    body = {"domain": DOMAIN, "schema_version": SCHEMA_VERSION, "event_id": event_id, "market_id": market_id,
            "evidence_cutoff_ts": cutoff, "required_inputs": inputs,
            "structured_evidence_hashes": sorted(structured)}
    FeatureInputManifestStore.validate(body)
    return body


def publish_manifest(body: dict[str, Any], *, stores, root) -> str:
    """Publish a built body to the frozen content-addressed manifest store; returns its hash."""

    return FeatureInputManifestStore(root, bindings=stores.bindings).publish(body)
