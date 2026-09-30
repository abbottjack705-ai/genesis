"""PURE normalizer: :class:`ParsedResponse` -> canonical ``MarketBookDocument`` bytes (design 9.1).

A ``RESPONSE`` document depends only on the raw bytes, the acquisition record (``T0``/``T1`` and
the request), the pinned map/schema/policy digests (through ``derivation_version``), the pinned
identity-registry prefix, the expected-scope artifact and the fixture-join observation. It holds
no ``T2``/``T3`` and reads no clock, so re-derivation is byte-identical (EV-03).

``selections`` exists only for an OPEN book, so a manifest field such as
``$.selections.OVER.odds_decimal`` cannot resolve against any other state (EV-06).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping

from genesis.repro import canonical_json, sha256_bytes
from genesis.time import iso_utc, parse_utc

from genesis_adapters.errors import AdapterFailure
from genesis_adapters.ids import gid
from genesis_adapters.oddspapi import identity_registry as registry
from genesis_adapters.oddspapi.parser import (
    STATE_ABSENT, STATE_OPEN, BookResult, ExpectedBook, ParseContext, ParsedResponse,
)

# Part of derivation_version (design 9.2: any change to code semantics creates a new source). 2: a requested
# tournament the response does not show makes the response partial, so it is never tombstoned (hostile audit F-03).
CODE_VERSION = "mb-normalize-2"
DOCUMENT_SCHEMA = "genesis.adapters.oddspapi.market-book.v1"
KIND_RESPONSE = "RESPONSE"
SIDE_BACK = "BACK"
PROVIDER = "oddspapi"
API_VERSION = "v4"
SPORT = "soccer"


@dataclass(frozen=True)
class NormalizedDocument:
    """One document plus the facts the emitter needs to publish it (all derived, none read from a clock)."""

    entity_id: str
    state: str
    data: bytes
    valid_from: str
    valid_to: str | None
    publisher_timestamp: str | None

    @property
    def artifact_hash(self) -> str:
        return sha256_bytes(self.data)


def _valid_to(book: BookResult, ctx: ParseContext) -> str | None:
    """OPEN only: ``min(T1 + price_ttl_seconds, S - prematch_guard_seconds)``; every other state never expires."""

    if book.state != STATE_OPEN:
        return None
    start = parse_utc(book.event.scheduled_start_as_known)
    ttl_end = parse_utc(ctx.response_received_at) + timedelta(seconds=ctx.policy.price_ttl_seconds)
    return iso_utc(min(ttl_end, start - timedelta(seconds=ctx.policy.prematch_guard_seconds)))


def _common(ctx: ParseContext) -> dict[str, Any]:
    return {
        "schema": DOCUMENT_SCHEMA, "derivation_kind": KIND_RESPONSE, "derivation_version": ctx.derivation_version,
        "provider": PROVIDER, "api_version": API_VERSION,
        "raw_artifact_hash": ctx.raw_artifact_hash, "raw_observation_id": ctx.raw_observation_id,
        "provider_request_hash": ctx.provider_request_hash, "acquisition_id": ctx.acquisition_id,
        "identity_registry_head": registry.head_of(ctx.identity_prefix),
        "expected_scope_hash": ctx.expected_scope_hash,
        "sport": SPORT, "side": SIDE_BACK,
        "times": {"request_started_at": ctx.request_started_at,
                  "response_received_at": ctx.response_received_at},
        "valid_from": iso_utc(ctx.response_received_at),
    }


def _book_document(book: BookResult, ctx: ParseContext) -> dict[str, Any]:
    event = book.event
    document = _common(ctx)
    document.update({
        "fixture_join_observation_id": event.fixture_join_observation_id,
        "competition_id": event.competition_id, "event_id": event.event_id,
        "provider_fixture_id": dict(event.provider_fixture_id),
        "home_participant_id": event.home_participant_id, "away_participant_id": event.away_participant_id,
        "scheduled_start_as_known": event.scheduled_start_as_known,
        "bookmaker_id": book.bookmaker_id, "provider_bookmaker_key": book.provider_bookmaker_key,
        "market_id": book.market_id, "market_family": book.market_family, "line": book.line,
        "period": book.period, "entity_id": book.entity_id,
        "market_state": book.state, "state_reasons": list(book.reasons),
        "provider_status": {key: dict(value) for key, value in book.provider_status.items()},
        "provider_timestamps": dict(book.provider_timestamps),
        "valid_to": _valid_to(book, ctx),
    })
    if book.state == STATE_OPEN:
        document["selections"] = {
            selection: {"selection_id": gid("sel", market_id=book.market_id, selection=selection), **dict(body)}
            for selection, body in book.selections.items()}
    return document


def _absent_document(book: ExpectedBook, ctx: ParseContext) -> dict[str, Any]:
    document = _common(ctx)
    document.update({
        "fixture_join_observation_id": None,
        "competition_id": book.competition_id, "event_id": book.event_id,
        "provider_fixture_id": dict(book.provider_fixture_id),
        "home_participant_id": book.home_participant_id, "away_participant_id": book.away_participant_id,
        "scheduled_start_as_known": book.scheduled_start_as_known,
        "bookmaker_id": book.bookmaker_id, "provider_bookmaker_key": book.provider_bookmaker_key,
        "market_id": book.market_id, "market_family": book.market_family, "line": book.line,
        "period": book.period, "entity_id": book.entity_id,
        "market_state": STATE_ABSENT, "state_reasons": [AdapterFailure.BOOK_ABSENT.value],
        "provider_status": {"event": {}, "market": {}, "outcomes": {}}, "provider_timestamps": {},
        "valid_to": None,
    })
    return document


def build_documents(parsed: ParsedResponse, ctx: ParseContext) -> tuple[NormalizedDocument, ...]:
    """Every document of one parsed response, ordered by ``entity_id`` (books and tombstones together)."""

    if parsed.failure is not None:
        return ()
    documents: dict[str, NormalizedDocument] = {}
    for book in parsed.books:
        body = _book_document(book, ctx)
        documents[book.entity_id] = NormalizedDocument(
            book.entity_id, book.state, canonical_json(body), body["valid_from"], body["valid_to"],
            book.publisher_timestamp)
    for tombstone in parsed.tombstones:
        body = _absent_document(tombstone, ctx)
        documents[tombstone.entity_id] = NormalizedDocument(
            tombstone.entity_id, STATE_ABSENT, canonical_json(body), body["valid_from"], None, None)
    return tuple(documents[key] for key in sorted(documents))


def market_book_documents(parsed: ParsedResponse, ctx: ParseContext) -> tuple[bytes, ...]:
    """The canonical bytes of every document (design 17 interface)."""

    return tuple(document.data for document in build_documents(parsed, ctx))
