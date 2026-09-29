"""Test-only helpers for the pure parser/normalizer stages (S4): fixtures, maps, contexts."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

from genesis_adapters import config as cfg
from genesis_adapters import schema as schema_mod
from genesis_adapters.oddspapi import maps as maps_mod
from genesis_adapters.oddspapi import normalize, parser

from .support import CONFIG, load_schemas

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "oddspapi" / "v4"
T0 = "2026-10-01T11:59:59.900000Z"
T1 = "2026-10-01T12:00:00.000000Z"
RAW_HASH = "a" * 64
RAW_OBSERVATION = "b" * 64
REQUEST_HASH = "c" * 64
ACQUISITION = "d" * 64
SCOPE_HASH = "e" * 64
FIXTURE_A = "id1000001761301153"          # Premier League, kickoff 2026-10-03T14:00Z
FIXTURE_B = "id1000001761301999"          # LaLiga, kickoff 2026-10-04T19:00Z

CONFIG_BODY = cfg.load_adapter_config(CONFIG, allow_fixture_only=True, code_version=normalize.CODE_VERSION)
POLICY = CONFIG_BODY.policy
MAPS = maps_mod.maps_from_config(CONFIG_BODY)
SCHEMAS = load_schemas()
ODDS_SCHEMA = SCHEMAS["oddspapi.v4.odds_by_tournaments.v1"]
FIXTURES_SCHEMA = SCHEMAS["oddspapi.v4.fixtures.v1"]
DERIVATION = CONFIG_BODY.derivation_version


def load_fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_bytes().decode("ascii"))


def odds_payload():
    """A fresh, mutable copy of the base ODDS fixture (two fixtures, five bookmakers each)."""

    return copy.deepcopy(load_fixture("odds_by_tournaments.json"))


def dump(payload) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("ascii")


def dump_with(payload, **literals: str) -> bytes:
    """Serialize ``payload``; every string value equal to ``"@name"`` becomes the raw literal text
    (used to test exact number literals such as ``2.50`` or ``1.910``)."""

    text = json.dumps(payload, sort_keys=True)
    for name, raw in literals.items():
        marker = json.dumps("@" + name)
        assert marker in text, name
        text = text.replace(marker, raw)
    return text.encode("ascii")


def fixture_of(payload, fixture_id: str = FIXTURE_A):
    return next(item for item in payload if item["fixtureId"] == fixture_id)


def market_of(payload, bookmaker: str, market: str, fixture_id: str = FIXTURE_A):
    return fixture_of(payload, fixture_id)["bookmakerOdds"][bookmaker]["markets"][market]


def price_of(payload, bookmaker: str, market: str, outcome: str, fixture_id: str = FIXTURE_A):
    return market_of(payload, bookmaker, market, fixture_id)["outcomes"][outcome]["players"]["0"]


def make_ctx(**overrides) -> parser.ParseContext:
    args = dict(acquisition_id=ACQUISITION, provider_request_hash=REQUEST_HASH, raw_artifact_hash=RAW_HASH,
                raw_observation_id=RAW_OBSERVATION, request_started_at=T0, response_received_at=T1,
                maps=MAPS, policy=POLICY, response_schema=ODDS_SCHEMA, derivation_version=DERIVATION,
                identity_prefix=(), expected_scope=None, expected_scope_hash=None, fixture_join=None,
                complete_hint=True)
    args.update(overrides)
    return parser.ParseContext(**args)


def parse(payload_or_bytes, **overrides) -> parser.ParsedResponse:
    raw = payload_or_bytes if isinstance(payload_or_bytes, bytes) else dump(payload_or_bytes)
    return parser.parse_odds_response(raw, make_ctx(**overrides))


def books_by(parsed, *, fixture: str = FIXTURE_A, bookmaker: str | None = None, family: str | None = None):
    found = [b for b in parsed.books if b.event.provider_fixture_id["value"] == fixture
             and (bookmaker is None or b.provider_bookmaker_key == bookmaker)
             and (family is None or b.market_family == family)]
    return found


def one_book(parsed, *, fixture: str = FIXTURE_A, bookmaker: str = "pinnacle",
             family: str = "SOCCER_TOTAL_GOALS_OU_FT"):
    found = books_by(parsed, fixture=fixture, bookmaker=bookmaker, family=family)
    assert len(found) == 1, f"{len(found)} books for {fixture}/{bookmaker}/{family}"
    return found[0]


def exclusion_counts(parsed) -> dict[str, int]:
    return {item.code: item.count for item in parsed.exclusions}


def documents(parsed, **overrides):
    return normalize.build_documents(parsed, make_ctx(**overrides))


def document_of(parsed, entity_id: str, **overrides) -> dict:
    for item in documents(parsed, **overrides):
        if item.entity_id == entity_id:
            return json.loads(item.data)
    raise AssertionError("no document for the entity")


def expected_book(book: parser.BookResult) -> parser.ExpectedBook:
    """An expected-scope entry that mirrors a parsed book (what a previous head would provide)."""

    event = book.event
    return parser.ExpectedBook(
        entity_id=book.entity_id, event_id=event.event_id, competition_id=event.competition_id,
        provider_fixture_id=event.provider_fixture_id, home_participant_id=event.home_participant_id,
        away_participant_id=event.away_participant_id,
        scheduled_start_as_known=event.scheduled_start_as_known, bookmaker_id=book.bookmaker_id,
        provider_bookmaker_key=book.provider_bookmaker_key, market_id=book.market_id,
        market_family=book.market_family, line=book.line, period=book.period)


def scope_of(parsed) -> dict[str, parser.ExpectedBook]:
    return {book.entity_id: expected_book(book) for book in parsed.books}


def maps_with(identity=None, market=None, status=None, *, declared_max: int | None = None):
    """Typed maps built from (possibly edited) copies of the pinned config documents."""

    def load(name):
        return json.loads((CONFIG / name).read_text(encoding="utf-8"))

    identity_doc = identity(load("oddspapi_v4_identity_map.json")) if identity else load("oddspapi_v4_identity_map.json")
    market_doc = market(load("oddspapi_v4_market_map.json")) if market else load("oddspapi_v4_market_map.json")
    status_doc = status(load("oddspapi_v4_status_map.json")) if status else load("oddspapi_v4_status_map.json")
    return maps_mod.load_maps(identity_doc, market_doc, status_doc,
                              declared_bookmakers_max=POLICY.declared_bookmakers_max if declared_max is None
                              else declared_max)


def policy_with(**changes) -> cfg.SlicePolicy:
    body = json.loads((CONFIG / "oddspapi_slice1_policy.json").read_text(encoding="utf-8"))
    body.update(changes)
    return cfg.parse_policy(body)


def decimal(value: str) -> Decimal:
    return Decimal(value)


def schema_with_inert(object_name: str, key: str, *, type_name: str = "str") -> schema_mod.ClosedSchema:
    """The ODDS schema with one extra declared-inert key on ``object_name`` (SCH-01)."""

    document = json.loads((CONFIG / "oddspapi_v4_response_schemas.json").read_text(encoding="utf-8"))
    body = copy.deepcopy(document["schemas"]["oddspapi.v4.odds_by_tournaments.v1"])
    body["objects"][object_name]["keys"][key] = {"inert": True, "type": type_name}
    return schema_mod.load_closed_schema("oddspapi.v4.odds_by_tournaments.v1", body)


def iso_add(text: str, *, seconds: float = 0, micros: int = 0) -> str:
    """``text`` shifted by a duration, as a canonical UTC timestamp."""

    from datetime import timedelta

    from genesis.time import iso_utc, parse_utc

    return iso_utc(parse_utc(text) + timedelta(seconds=seconds, microseconds=micros))


def set_all_outcomes(payload, *, fixture_id: str = FIXTURE_A, **changes) -> None:
    """Apply ``changes`` to every price entry of every declared book of one fixture."""

    for name in ("pinnacle", "fixture-book-a", "fixture-book-b"):
        for market in fixture_of(payload, fixture_id)["bookmakerOdds"][name]["markets"].values():
            for outcome in market["outcomes"].values():
                for entry in outcome["players"].values():
                    entry.update(changes)


def reasons_of(parsed, *, fixture: str = FIXTURE_A) -> set[tuple[str, tuple[str, ...]]]:
    return {(book.state, book.reasons) for book in books_by(parsed, fixture=fixture)}
