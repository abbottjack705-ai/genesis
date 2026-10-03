"""Append-only invalidation ledger and the INVALIDATION document (design 9.1a, 13.2).

An invalidation is never an edit: it is a new ledger row plus, when the invalidated record is still
the head of its scope, a new ``INVALIDATED`` head with its own admissible time. Invalidation only
ever REDUCES usability, so adapter code may append ``ADAPTER_AUTOMATIC`` rows; an operator appends
``OPERATOR`` rows. A mistaken invalidation is not undone: the next genuine capture supersedes the
INVALIDATED head in the ordinary way.

The INVALIDATION document is a pure function of (ledger row, invalidated normalized document,
ledger head), so ``verify_derivation`` can rebuild it byte for byte.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from genesis.registry import AppendOnlyJsonl, RegistryConflict
from genesis.repro import canonical_json, sha256_bytes
from genesis.time import TimestampError, iso_utc, parse_utc

from genesis_adapters.errors import AdapterFailure

SCHEMA_VERSION = "invalidation-ledger-v1"
DOCUMENT_SCHEMA = "genesis.adapters.oddspapi.market-book.v1"
KIND_INVALIDATION = "INVALIDATION"
STATE_INVALIDATED = "INVALIDATED"
CLASSES = ("OBSERVATION_DEFECT", "DERIVATION_DEFECT", "PROVIDER_ERROR_NOTICE", "OPERATOR")
ACTORS = ("ADAPTER_AUTOMATIC", "OPERATOR")
EFFECT_EMITTED = "INVALIDATED_HEAD_EMITTED"
EFFECT_SUPERSEDED = "NONE_ALREADY_SUPERSEDED"
HEAD_EFFECTS = (EFFECT_EMITTED, EFFECT_SUPERSEDED)
EMPTY_HEAD = {"sequence": 0, "record_hash": "0" * 64}
_HEX64 = re.compile(r"^[0-9a-f]{64}\Z")
_CHAIN = frozenset({"previous_hash", "sequence", "record_hash"})
_COMMON = frozenset({"record_type", "schema_version"})
_RECORDED = frozenset({"invalidation_id", "invalidated_observation_id", "invalidated_artifact_hash",
                       "invalidated_pit_record_id", "entity_id", "source_id", "invalidation_class", "reason",
                       "recorded_at", "actor", "evidence_refs"})
_APPLIED = frozenset({"invalidation_id", "head_effect", "invalidation_observation_id",
                      "invalidation_pit_record_id", "applied_at"})


class InvalidationLedgerInvalid(RegistryConflict):
    """A row that would make the invalidation ledger unreadable or inconsistent."""


def _bad(message: str) -> None:
    raise InvalidationLedgerInvalid(message)


def _stamp(value: Any, name: str) -> str:
    if type(value) is not str:
        _bad(f"{name} must be a timestamp string")
    try:
        parse_utc(value)
        if iso_utc(value) != value:
            _bad(f"{name} is not canonical")
    except TimestampError:
        _bad(f"{name} is not a valid UTC timestamp")
    return value


def _digest(value: Any, name: str) -> None:
    if type(value) is not str or not _HEX64.match(value):
        _bad(f"{name} must be a lowercase SHA-256 digest")


def invalidation_id_of(row: Mapping[str, Any]) -> str:
    """``sha256(canonical_json(row without invalidation_id))`` over the recorded row (no chain fields)."""

    body = {key: value for key, value in row.items() if key not in _CHAIN and key != "invalidation_id"}
    return sha256_bytes(canonical_json(body))


def recorded_row(*, invalidated_observation_id: str, invalidated_artifact_hash: str,
                 invalidated_pit_record_id: str, entity_id: str, source_id: str, invalidation_class: str,
                 reason: str, recorded_at: str, actor: str, evidence_refs: Sequence[str]) -> dict[str, Any]:
    body = {"record_type": "invalidation_recorded", "schema_version": SCHEMA_VERSION,
            "invalidated_observation_id": invalidated_observation_id,
            "invalidated_artifact_hash": invalidated_artifact_hash,
            "invalidated_pit_record_id": invalidated_pit_record_id, "entity_id": entity_id,
            "source_id": source_id, "invalidation_class": invalidation_class, "reason": reason,
            "recorded_at": recorded_at, "actor": actor, "evidence_refs": list(evidence_refs)}
    return {**body, "invalidation_id": invalidation_id_of(body)}


def applied_row(*, invalidation_id: str, head_effect: str, invalidation_observation_id: str | None,
                invalidation_pit_record_id: str | None, applied_at: str) -> dict[str, Any]:
    return {"record_type": "invalidation_applied", "schema_version": SCHEMA_VERSION,
            "invalidation_id": invalidation_id, "head_effect": head_effect,
            "invalidation_observation_id": invalidation_observation_id,
            "invalidation_pit_record_id": invalidation_pit_record_id, "applied_at": applied_at}


def replay(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate the whole history; ``{invalidation_id: {"recorded": row, "applied": row | None}}``."""

    state: dict[str, dict[str, Any]] = {}
    last = None
    for row in rows:
        kind = row.get("record_type")
        if row.get("schema_version") != SCHEMA_VERSION or kind not in ("invalidation_recorded",
                                                                       "invalidation_applied"):
            _bad("unknown invalidation ledger record")
        keys = _RECORDED if kind == "invalidation_recorded" else _APPLIED
        if set(row) - _CHAIN != keys | _COMMON:
            _bad(f"{kind} has unexpected or missing keys")
        stamp = _stamp(row["recorded_at" if kind == "invalidation_recorded" else "applied_at"], "time")
        if last is not None and stamp < last:
            _bad("ledger time regressed")
        last = stamp
        _digest(row["invalidation_id"], "invalidation_id")
        if kind == "invalidation_recorded":
            if row["invalidation_id"] != invalidation_id_of(row):
                _bad("invalidation_id does not match the row")
            if row["invalidation_id"] in state:
                _bad("an invalidation is recorded once")
            _digest(row["invalidated_observation_id"], "invalidated_observation_id")
            _digest(row["invalidated_artifact_hash"], "invalidated_artifact_hash")
            if row["invalidation_class"] not in CLASSES or row["actor"] not in ACTORS:
                _bad("unknown invalidation class or actor")
            if type(row["evidence_refs"]) is not list or any(type(item) is not str for item in row["evidence_refs"]):
                _bad("evidence_refs must be a list of strings")
            for name in ("invalidated_pit_record_id", "entity_id", "source_id", "reason"):
                if type(row[name]) is not str or not row[name]:
                    _bad(f"{name} is required")
            try:
                AdapterFailure(row["reason"])
            except ValueError:
                _bad("reason is not a known detail code")
            state[row["invalidation_id"]] = {"recorded": dict(row), "applied": None}
        else:
            entry = state.get(row["invalidation_id"])
            if entry is None or entry["applied"] is not None:
                _bad("an application needs exactly one earlier recording")
            if row["head_effect"] not in HEAD_EFFECTS:
                _bad("unknown head effect")
            emitted = row["head_effect"] == EFFECT_EMITTED
            if emitted != (row["invalidation_observation_id"] is not None) or emitted != (
                    row["invalidation_pit_record_id"] is not None):
                _bad("head effect and emitted references disagree")
            if stamp < entry["recorded"]["recorded_at"]:
                _bad("applied before recorded")
            entry["applied"] = dict(row)
    return state


def head_of(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return dict(EMPTY_HEAD)
    return {"sequence": rows[-1]["sequence"], "record_hash": rows[-1]["record_hash"]}


class InvalidationLedger:
    """``invalidations.jsonl``: hash-chained, replay-validated, never edited."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.log = AppendOnlyJsonl(self.path, reader=lambda rows: replay(rows))

    def rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.log.records())

    def state(self) -> dict[str, dict[str, Any]]:
        return replay(self.rows())

    def head(self) -> dict[str, Any]:
        return head_of(self.rows())

    def last_time(self) -> str | None:
        rows = self.rows()
        if not rows:
            return None
        last = rows[-1]
        return last["recorded_at"] if last["record_type"] == "invalidation_recorded" else last["applied_at"]

    def record(self, row: Mapping[str, Any]) -> dict[str, Any]:
        self.log.append(dict(row))
        return self.head()

    def apply(self, row: Mapping[str, Any]) -> None:
        self.log.append(dict(row))

    def head_containing(self, invalidation_id: str) -> dict[str, Any]:
        """The head right after the recording of ``invalidation_id`` (what its document pins)."""

        for row in self.rows():
            if row["record_type"] == "invalidation_recorded" and row["invalidation_id"] == invalidation_id:
                return {"sequence": row["sequence"], "record_hash": row["record_hash"]}
        raise InvalidationLedgerInvalid("unknown invalidation")


def build_invalidation_document(row: Mapping[str, Any], target: Mapping[str, Any], *,
                                ledger_head: Mapping[str, Any]) -> bytes:
    """The design 9.1a document, a pure function of (ledger row, invalidated document, ledger head)."""

    if target.get("derivation_kind") != "RESPONSE" or target.get("entity_id") != row["entity_id"]:
        raise InvalidationLedgerInvalid("the invalidated document is not a RESPONSE document of this entity")
    body = {
        "schema": DOCUMENT_SCHEMA, "derivation_kind": KIND_INVALIDATION,
        "derivation_version": target["derivation_version"],
        "invalidation_id": row["invalidation_id"],
        "invalidation_ledger_head": {"sequence": ledger_head["sequence"], "record_hash": ledger_head["record_hash"]},
        "invalidated_observation_id": row["invalidated_observation_id"],
        "invalidated_artifact_hash": row["invalidated_artifact_hash"],
        "invalidated_pit_record_id": row["invalidated_pit_record_id"],
        "invalidation_class": row["invalidation_class"], "invalidation_reason": row["reason"],
        "provider": target["provider"], "api_version": target["api_version"], "sport": target["sport"],
        "competition_id": target["competition_id"], "event_id": target["event_id"],
        "bookmaker_id": target["bookmaker_id"], "market_id": target["market_id"],
        "market_family": target["market_family"], "line": target["line"], "period": target["period"],
        "entity_id": row["entity_id"], "scheduled_start_as_known": target["scheduled_start_as_known"],
        "market_state": STATE_INVALIDATED, "state_reasons": [row["reason"]],
        "times": {"invalidation_recorded_at": row["recorded_at"]},
        "valid_from": row["recorded_at"], "valid_to": None, "side": target["side"],
    }
    return canonical_json(body)


class InvalidationDerivationError(ValueError):
    """An INVALIDATION document that cannot be rebuilt byte for byte from its pinned inputs."""


def _strip(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in _CHAIN}


def verify_invalidation_derivation(observation_id: str, *, stores) -> None:
    """Rebuild one INVALIDATION document from (its ledger row, the invalidated document) and require byte equality.

    Checks, in order (design 11.5): the observation is under this derivation's contract and its bytes verify;
    the document is an INVALIDATION document; its pinned ledger head is a prefix of the verified ledger that
    contains exactly one recording of its invalidation; the invalidated observation's artifact is the recorded
    one; the recorded PIT record carries that artifact for the recorded entity and source; the rebuilt bytes
    equal the stored bytes. Any failure raises; nothing passes by omission.
    """

    observation = stores.evidence.get_observation(observation_id)
    if observation.contract_id != stores.contract_id:
        raise InvalidationDerivationError("the observation is not under this derivation's contract")
    data = stores.evidence.get_bytes(observation.artifact_hash)
    try:
        document = json.loads(data)
    except ValueError:
        raise InvalidationDerivationError("the document is not JSON") from None
    if type(document) is not dict or document.get("derivation_kind") != KIND_INVALIDATION:
        raise InvalidationDerivationError("not an INVALIDATION document")
    head = document.get("invalidation_ledger_head")
    rows = stores.invalidations.rows()
    if type(head) is not dict or set(head) != {"sequence", "record_hash"} or type(head["sequence"]) is not int \
            or not 1 <= head["sequence"] <= len(rows) or rows[head["sequence"] - 1]["record_hash"] != head["record_hash"]:
        raise InvalidationDerivationError("the pinned ledger head is not a prefix of the verified ledger")
    recorded = [row for row in rows[:head["sequence"]] if row["record_type"] == "invalidation_recorded"
                and row["invalidation_id"] == document.get("invalidation_id")]
    if len(recorded) != 1:
        raise InvalidationDerivationError("the pinned prefix does not contain exactly one recording")
    row = _strip(recorded[0])
    target_observation = stores.evidence.get_observation(row["invalidated_observation_id"])
    if target_observation.artifact_hash != row["invalidated_artifact_hash"]:
        raise InvalidationDerivationError("the invalidated artifact is not the recorded one")
    target = json.loads(stores.evidence.get_bytes(target_observation.artifact_hash))
    named = [pit for pit in stores.pit.log.records() if pit.get("record_type") == "pit_record"
             and pit.get("record_id") == row["invalidated_pit_record_id"]]
    if len(named) != 1 or (named[0]["payload_hash"], named[0]["entity_id"], named[0]["source_id"]) != (
            row["invalidated_artifact_hash"], row["entity_id"], row["source_id"]):
        raise InvalidationDerivationError("the recorded PIT record does not carry the invalidated artifact")
    if row["source_id"] != stores.source_id:
        raise InvalidationDerivationError("the invalidation belongs to another source")
    if build_invalidation_document(row, target, ledger_head=head) != data:
        raise InvalidationDerivationError("the rebuilt document differs from the stored bytes")
    if (observation.retrieved_at, observation.valid_from, observation.valid_to) != (
            row["recorded_at"], row["recorded_at"], None):
        raise InvalidationDerivationError("the observation times are not the invalidation's")
