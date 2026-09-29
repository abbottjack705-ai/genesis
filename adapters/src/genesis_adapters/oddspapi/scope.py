"""Expected scope for ABSENT tombstones (design 12.4).

Before an ODDS request is sent, the runner computes the books it expects to see: those of the
request's competitions and declared bookmakers that have an admissible OPEN or SUSPENDED head at
``Tq``. The set is written immutably to ``scopes/<hash>.json`` and its hash is recorded, so a later
re-derivation reads exactly the same set. After a COMPLETE response every expected book that is not
present gets an ABSENT tombstone; a partial or failed response produces none.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from genesis.repro import canonical_json, immutable_write, sha256_bytes
from genesis.time import parse_utc

from genesis_adapters.oddspapi.parser import ExpectedBook

SCOPE_SCHEMA = "genesis.adapters.oddspapi.expected-scope.v1"
_BOOK_FIELDS = ("entity_id", "event_id", "competition_id", "provider_fixture_id", "home_participant_id",
                "away_participant_id", "scheduled_start_as_known", "bookmaker_id", "provider_bookmaker_key",
                "market_id", "market_family", "line", "period")


class ScopeError(ValueError):
    """An expected-scope artifact that is malformed or does not match its hash."""


def book_to_dict(book: ExpectedBook) -> dict[str, Any]:
    return {name: (dict(getattr(book, name)) if name == "provider_fixture_id" else getattr(book, name))
            for name in _BOOK_FIELDS}


def book_from_dict(item: Mapping[str, Any]) -> ExpectedBook:
    if type(item) is not dict or set(item) != set(_BOOK_FIELDS):
        raise ScopeError("expected-scope book has unexpected or missing keys")
    return ExpectedBook(**{name: item[name] for name in _BOOK_FIELDS})


def scope_bytes(books: Iterable[ExpectedBook], *, as_of: str) -> bytes:
    """Canonical bytes of a scope artifact (books sorted by entity id, no duplicates)."""

    ordered = sorted(books, key=lambda book: book.entity_id)
    if len({book.entity_id for book in ordered}) != len(ordered):
        raise ScopeError("an entity appears twice in the expected scope")
    return canonical_json({"schema": SCOPE_SCHEMA, "as_of": as_of, "books": [book_to_dict(b) for b in ordered]})


def publish_scope(root: Path, books: Iterable[ExpectedBook], *, as_of: str) -> str:
    """Write the scope artifact (idempotently) and return its hash."""

    data = scope_bytes(books, as_of=as_of)
    digest = sha256_bytes(data)
    immutable_write(Path(root) / "scopes" / f"{digest}.json", data)
    return digest


def load_scope(root: Path, digest: str) -> dict[str, ExpectedBook]:
    """The scope with this hash, verified byte for byte."""

    path = Path(root) / "scopes" / f"{digest}.json"
    data = path.read_bytes()
    if sha256_bytes(data) != digest:
        raise ScopeError("expected-scope bytes do not match their hash")
    body = json.loads(data)
    if type(body) is not dict or set(body) != {"schema", "as_of", "books"} or body["schema"] != SCOPE_SCHEMA:
        raise ScopeError("expected-scope artifact has an unexpected shape")
    books = [book_from_dict(item) for item in body["books"]]
    if canonical_json(body) != data:
        raise ScopeError("expected-scope artifact is not canonical")
    return {book.entity_id: book for book in books}


def build_expected_scope(*, pit, evidence, source_id: str, decision_at: str, competition_ids: Iterable[str],
                         bookmaker_ids: Iterable[str]) -> dict[str, ExpectedBook]:
    """Books with an admissible OPEN or SUSPENDED head at ``decision_at`` for the given competitions and bookmakers.

    The head of each entity is the unique admissible record with the latest ``valid_from`` (a tie or
    an unreadable head leaves the entity out: an expected book must be certain). The documents are
    read through the frozen evidence store, which re-hashes their bytes.
    """

    from genesis.pit import BitemporalRecord

    point = parse_utc(decision_at)
    competitions, bookmakers = set(competition_ids), set(bookmaker_ids)
    scope: dict[str, list[BitemporalRecord]] = {}
    for row in pit.log.records():
        if row.get("record_type") != "pit_record" or row.get("source_id") != source_id:
            continue
        record = BitemporalRecord(**{key: row[key] for key in BitemporalRecord.__dataclass_fields__})
        if record.admissible_at(decision_at):
            scope.setdefault(record.entity_id, []).append(record)
    found: dict[str, ExpectedBook] = {}
    for entity_id, records in sorted(scope.items()):
        latest = max(parse_utc(record.valid_from) for record in records)
        heads = [record for record in records if parse_utc(record.valid_from) == latest]
        if len(heads) != 1:
            continue
        document = json.loads(evidence.get_bytes(heads[0].payload_hash))
        if document.get("derivation_kind") != "RESPONSE" or document.get("market_state") not in ("OPEN", "SUSPENDED"):
            continue
        if document["competition_id"] not in competitions or document["bookmaker_id"] not in bookmakers:
            continue
        found[entity_id] = ExpectedBook(
            entity_id=entity_id, event_id=document["event_id"], competition_id=document["competition_id"],
            provider_fixture_id=document["provider_fixture_id"],
            home_participant_id=document["home_participant_id"], away_participant_id=document["away_participant_id"],
            scheduled_start_as_known=document["scheduled_start_as_known"], bookmaker_id=document["bookmaker_id"],
            provider_bookmaker_key=document["provider_bookmaker_key"], market_id=document["market_id"],
            market_family=document["market_family"], line=document["line"], period=document["period"])
    return found
