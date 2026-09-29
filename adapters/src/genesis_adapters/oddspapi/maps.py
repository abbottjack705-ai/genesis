"""Pinned identity, market and status maps with closed-shape validation (design 8, 8.5, 10).

The three JSON files are read into typed, immutable structures. Every object is closed: a key
that is not listed is a load error, so a map can never silently carry meaning the code does not
know about. Nothing here reads a clock or performs I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

SPORT = "soccer"
KIND_SPORTSBOOK = "fixed_odds_sportsbook"
SELECTIONS = ("HOME", "DRAW", "AWAY", "OVER", "UNDER")
STATE_VOCABULARY = {
    "event": ("PREMATCH", "NOT_PREMATCH"),
    "market": ("OPEN", "SUSPENDED"),
    "outcome": ("ACTIVE", "INACTIVE"),
    "bookmaker": ("ACTIVE", "INACTIVE"),
}
JSON_TYPES = ("int", "str", "bool")
MARKET_LEVEL_ABSENT = "DECLARED_ABSENT"
_BOOKMAKER_ID = re.compile(r"^bk\.[a-z0-9][a-z0-9-]{0,39}$")
_NATIVE_STR = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
_LINE_SOURCE = re.compile(r"^(none|market_definition|outcome_field:[A-Za-z][A-Za-z0-9_]{0,40})$")

_IDENTITY_KEYS = {"schema", "competitions", "bookmakers", "provider_sport"}
_COMPETITION_KEYS = {"provider_tournament_id", "native_type", "genesis_competition_id", "sport",
                     "doc_reference", "expected_category_name", "expected_tournament_name",
                     "fixture_only", "verified_live"}
_BOOKMAKER_KEYS = {"provider_bookmaker_key", "genesis_bookmaker_id", "kind", "declared", "doc_reference",
                   "fixture_only", "verified_live"}
_MARKET_FILE_KEYS = {"schema", "families", "markets"}
_FAMILY_KEYS = {"period", "required_line", "selections"}
_MARKET_KEYS = {"provider_market_id", "native_type", "family", "period", "line", "line_source", "outcomes",
                "doc_reference", "fixture_only", "verified_live"}
_STATUS_FILE_KEYS = {"schema", "event_status", "market_level_status", "market_status", "outcome_status",
                     "bookmaker_status"}
_RULE_KEYS = {"field", "json_type", "value", "genesis", "doc_reference", "verified_live"}


class MapError(ValueError):
    """A pinned map that is malformed, inconsistent or outside the operational policy."""


def _closed(value: Any, keys: set, where: str) -> Mapping:
    if type(value) is not dict or set(value) != keys:
        raise MapError(f"{where}: unexpected or missing keys")
    return value


def _flag(value: Any, where: str) -> bool:
    if type(value) is not bool:
        raise MapError(f"{where}: must be a boolean")
    return value


def _native(value: Any, declared: Any, where: str) -> dict:
    if declared == "int":
        if type(value) is not int or value < 0:
            raise MapError(f"{where}: a declared int id must be a non-negative integer")
        return {"native_type": "int", "value": str(value)}
    if declared == "str":
        if type(value) is not str or not _NATIVE_STR.match(value):
            raise MapError(f"{where}: a declared str id must match the native-id grammar")
        return {"native_type": "str", "value": value}
    raise MapError(f"{where}: native_type must be 'int' or 'str'")


def _decimal(text: Any, where: str) -> Decimal:
    if type(text) is not str:
        raise MapError(f"{where}: must be a decimal string")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise MapError(f"{where}: not a decimal") from None
    if not value.is_finite():
        raise MapError(f"{where}: must be finite")
    return value


@dataclass(frozen=True)
class Competition:
    native: Mapping[str, str]
    genesis_id: str
    fixture_only: bool


@dataclass(frozen=True)
class Bookmaker:
    key: str
    genesis_id: str
    kind: str
    declared: bool
    fixture_only: bool


@dataclass(frozen=True)
class Family:
    name: str
    period: str
    required_line: Decimal | None
    selections: tuple[str, ...]


@dataclass(frozen=True)
class MarketEntry:
    native: Mapping[str, str]
    family: str
    period: str
    line: Decimal | None
    line_source: str
    outcomes: Mapping[str, str]                 # provider outcome id (text) -> selection code
    fixture_only: bool

    @property
    def outcome_field(self) -> str | None:
        prefix = "outcome_field:"
        return self.line_source[len(prefix):] if self.line_source.startswith(prefix) else None


@dataclass(frozen=True)
class StatusRule:
    field: str
    json_type: str
    value: Any
    genesis: str


def json_type_of(value: Any) -> str | None:
    """The status-map ``json_type`` of a decoded JSON value, or None for types a rule cannot name."""

    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is str:
        return "str"
    return None


@dataclass(frozen=True)
class AdapterMaps:
    competitions: Mapping[tuple[str, str], Competition]     # (native_type, value) -> competition
    bookmakers: Mapping[str, Bookmaker]
    markets: Mapping[tuple[str, str], MarketEntry]
    families: Mapping[str, Family]
    status_rules: Mapping[str, tuple[StatusRule, ...]]      # level -> rules
    fixture_only: bool
    sport_id: int | str                                     # the provider's native id of the soccer sport

    def competition(self, native_type: str, value: str) -> Competition | None:
        return self.competitions.get((native_type, value))

    def market(self, native_type: str, value: str) -> MarketEntry | None:
        return self.markets.get((native_type, value))

    def declared_bookmakers(self) -> tuple[Bookmaker, ...]:
        return tuple(sorted((b for b in self.bookmakers.values() if b.declared), key=lambda b: b.key))

    def classify(self, level: str, field: str, value: Any) -> str | None:
        """The Genesis state for ``(field, json_type, value)`` or None when it is not on the allowlist.

        Matching is on the exact JSON type: ``1`` and ``"1"`` (and ``true`` and ``1``) never match
        one another.
        """

        kind = json_type_of(value)
        if kind is None:
            return None
        for rule in self.status_rules[level]:
            if rule.field == field and rule.json_type == kind and rule.value == value \
                    and json_type_of(rule.value) == kind:
                return rule.genesis
        return None

    def status_field(self, level: str) -> str | None:
        """The single provider field that carries ``level`` status (None when none is declared)."""

        fields = {rule.field for rule in self.status_rules[level]}
        return next(iter(fields)) if len(fields) == 1 else None


def _load_families(document: Mapping) -> dict[str, Family]:
    families: dict[str, Family] = {}
    raw = document["families"]
    if type(raw) is not dict or not raw:
        raise MapError("families: must be a non-empty mapping")
    for name, body in raw.items():
        _closed(body, _FAMILY_KEYS, f"family {name}")
        selections = body["selections"]
        if type(selections) is not list or not selections or len(set(selections)) != len(selections) \
                or any(item not in SELECTIONS for item in selections):
            raise MapError(f"family {name}: selections must be distinct known selection codes")
        line = body["required_line"]
        required = None if line is None else _decimal(line, f"family {name}.required_line")
        if type(body["period"]) is not str or not body["period"]:
            raise MapError(f"family {name}: period is required")
        families[name] = Family(name, body["period"], required, tuple(selections))
    return families


def _load_competitions(identity: Mapping) -> dict[tuple[str, str], Competition]:
    competitions: dict[tuple[str, str], Competition] = {}
    genesis_ids: set[str] = set()
    for index, body in enumerate(identity["competitions"]):
        where = f"competitions[{index}]"
        _closed(body, _COMPETITION_KEYS, where)
        if body["sport"] != SPORT:
            raise MapError(f"{where}: only sport '{SPORT}' is in scope")
        native = _native(body["provider_tournament_id"], body["native_type"], where)
        if type(body["genesis_competition_id"]) is not str or not _SLUG.match(body["genesis_competition_id"]):
            raise MapError(f"{where}: genesis_competition_id must be a pinned slug")
        key = (native["native_type"], native["value"])
        if key in competitions or body["genesis_competition_id"] in genesis_ids:
            raise MapError(f"{where}: duplicate competition")
        genesis_ids.add(body["genesis_competition_id"])
        competitions[key] = Competition(native, body["genesis_competition_id"],
                                        _flag(body["fixture_only"], where))
        _flag(body["verified_live"], where)
    return competitions


def _load_bookmakers(identity: Mapping, *, declared_max: int) -> dict[str, Bookmaker]:
    bookmakers: dict[str, Bookmaker] = {}
    genesis_ids: set[str] = set()
    for index, body in enumerate(identity["bookmakers"]):
        where = f"bookmakers[{index}]"
        _closed(body, _BOOKMAKER_KEYS, where)
        key, genesis_id = body["provider_bookmaker_key"], body["genesis_bookmaker_id"]
        if type(key) is not str or not _NATIVE_STR.match(key):
            raise MapError(f"{where}: provider_bookmaker_key is outside the native-id grammar")
        if type(genesis_id) is not str or not _BOOKMAKER_ID.match(genesis_id):
            raise MapError(f"{where}: genesis_bookmaker_id must look like bk.<slug>")
        if key in bookmakers or genesis_id in genesis_ids:
            raise MapError(f"{where}: duplicate bookmaker")
        genesis_ids.add(genesis_id)
        kind, declared = body["kind"], _flag(body["declared"], where)
        if type(kind) is not str or not kind:
            raise MapError(f"{where}: kind is required")
        if declared and kind != KIND_SPORTSBOOK:
            raise MapError(f"{where}: only {KIND_SPORTSBOOK} bookmakers can be declared (exchanges are excluded)")
        bookmakers[key] = Bookmaker(key, genesis_id, kind, declared, _flag(body["fixture_only"], where))
        _flag(body["verified_live"], where)
    if sum(1 for b in bookmakers.values() if b.declared) > declared_max:
        raise MapError("more bookmakers are declared than the policy permits")
    return bookmakers


def _load_markets(document: Mapping, families: Mapping[str, Family]) -> dict[tuple[str, str], MarketEntry]:
    markets: dict[tuple[str, str], MarketEntry] = {}
    raw = document["markets"]
    if type(raw) is not list or not raw:
        raise MapError("markets: must be a non-empty list")
    for index, body in enumerate(raw):
        where = f"markets[{index}]"
        _closed(body, _MARKET_KEYS, where)
        family = families.get(body["family"])
        if family is None:
            raise MapError(f"{where}: unknown family")
        if body["period"] != family.period:
            raise MapError(f"{where}: period differs from the family period")
        native = _native(body["provider_market_id"], body["native_type"], where)
        key = (native["native_type"], native["value"])
        if key in markets:
            raise MapError(f"{where}: duplicate provider market id")
        source = body["line_source"]
        if type(source) is not str or not _LINE_SOURCE.match(source):
            raise MapError(f"{where}: unknown line_source")
        line = None if body["line"] is None else _decimal(body["line"], f"{where}.line")
        if family.required_line is None:
            if source != "none" or line is not None:
                raise MapError(f"{where}: a lineless family cannot carry a line or a line source")
        else:
            if source == "none":
                raise MapError(f"{where}: a lined family needs a declared line source")
            if (source == "market_definition") != (line is not None):
                raise MapError(f"{where}: a static line goes with market_definition, and only with it")
        outcomes = body["outcomes"]
        if type(outcomes) is not dict or not outcomes:
            raise MapError(f"{where}: outcomes must be a non-empty mapping")
        mapped: dict[str, str] = {}
        for outcome_id, selection in outcomes.items():
            if type(outcome_id) is not str or not _NATIVE_STR.match(outcome_id) or selection not in family.selections:
                raise MapError(f"{where}: outcome mapping is outside the family's selection set")
            mapped[outcome_id] = selection
        if sorted(mapped.values()) != sorted(family.selections):
            raise MapError(f"{where}: outcomes must map each selection of the family exactly once")
        markets[key] = MarketEntry(native, family.name, family.period, line, source, mapped,
                                   _flag(body["fixture_only"], where))
        _flag(body["verified_live"], where)
    return markets


def _load_status(document: Mapping) -> dict[str, tuple[StatusRule, ...]]:
    _closed(document, _STATUS_FILE_KEYS, "status map")
    if document["market_level_status"] != MARKET_LEVEL_ABSENT:
        raise MapError("market-level status is not supported by the pinned schema; declare it absent")
    rules: dict[str, tuple[StatusRule, ...]] = {}
    for level, section in (("event", "event_status"), ("market", "market_status"),
                           ("outcome", "outcome_status"), ("bookmaker", "bookmaker_status")):
        raw = document[section]
        if type(raw) is not list:
            raise MapError(f"{section}: must be a list")
        seen: dict[tuple, str] = {}
        built: list[StatusRule] = []
        for index, body in enumerate(raw):
            where = f"{section}[{index}]"
            _closed(body, _RULE_KEYS, where)
            if body["json_type"] not in JSON_TYPES or json_type_of(body["value"]) != body["json_type"]:
                raise MapError(f"{where}: value does not have the declared json_type")
            if type(body["field"]) is not str or not body["field"]:
                raise MapError(f"{where}: field is required")
            if body["genesis"] not in STATE_VOCABULARY[level]:
                raise MapError(f"{where}: genesis state is outside the {level} vocabulary")
            key = (body["field"], body["json_type"], body["value"])
            if key in seen:
                raise MapError(f"{where}: duplicate status rule")
            seen[key] = body["genesis"]
            _flag(body["verified_live"], where)
            built.append(StatusRule(body["field"], body["json_type"], body["value"], body["genesis"]))
        if len({rule.field for rule in built}) > 1:
            raise MapError(f"{section}: the pinned schema carries one status field per level")
        rules[level] = tuple(built)
    if rules["market"]:
        raise MapError("market_status must be empty while market-level status is declared absent")
    return rules


def load_maps(identity: Any, market: Any, status: Any, *, declared_bookmakers_max: int) -> AdapterMaps:
    """Validate the three decoded map documents and return the typed :class:`AdapterMaps`."""

    _closed(identity, _IDENTITY_KEYS, "identity map")
    _closed(market, _MARKET_FILE_KEYS, "market map")
    sport = identity["provider_sport"]
    if type(sport) is not dict or set(sport) != {"native_type", "provider_sport_id", "sport"}             or sport["sport"] != SPORT:
        raise MapError("provider_sport must name the soccer sport")
    sport_native = _native(sport["provider_sport_id"], sport["native_type"], "provider_sport")
    families = _load_families(market)
    competitions = _load_competitions(identity)
    bookmakers = _load_bookmakers(identity, declared_max=declared_bookmakers_max)
    markets = _load_markets(market, families)
    rules = _load_status(status)
    fixture_only = any(c.fixture_only for c in competitions.values()) or any(
        b.fixture_only for b in bookmakers.values()) or any(m.fixture_only for m in markets.values())
    return AdapterMaps(competitions, bookmakers, markets, families, rules, fixture_only,
                       sport["provider_sport_id"] if sport_native["native_type"] == "int" else sport_native["value"])


def maps_from_config(config) -> AdapterMaps:
    """The typed maps for a loaded :class:`genesis_adapters.config.AdapterConfig`."""

    return load_maps(config.identity_map, config.market_map, config.status_map,
                     declared_bookmakers_max=config.policy.declared_bookmakers_max)
