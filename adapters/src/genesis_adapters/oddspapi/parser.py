"""PURE parser: raw ODDS bytes + :class:`ParseContext` -> :class:`ParsedResponse`.

Design sections 8-10, 15 (F-15 .. F-29, F-38). Nothing here reads a clock, the filesystem, the
network or any random source: every time it uses arrives in the context (the acquisition record's
``T0``/``T1``), every identity it uses is derived from provider ids, and every threshold comes from
the pinned policy. Re-running it over the same bytes and context gives the same result (EV-03).

Result semantics (design 10, 10.1, 15):

* envelope-level problems reject the whole response (no observation, no tombstone);
* drift, status, timestamp, price and identity problems block exactly the books they can affect;
* only a well-formed, complete, non-drifting book is OPEN, and only OPEN carries prices;
* a book that is neither present nor blocked is absent; the response gets a tombstone for it only
  when the response as a whole is complete.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN
from typing import Any, Iterable, Mapping, Sequence

from genesis.repro import canonical_json
from genesis.time import iso_utc

from genesis_adapters import jsonstrict, schema
from genesis_adapters.errors import AdapterFailure
from genesis_adapters.ids import IdentityTypeError, gid, native_id
from genesis_adapters.oddspapi import identity_registry as registry
from genesis_adapters.oddspapi.maps import AdapterMaps, Bookmaker, Competition, Family, MarketEntry

UTC = timezone.utc
PROVIDER = "oddspapi"
FIXTURE_NS = "v4.fixture"
PARTICIPANT_NS = "v4.participant"
STATE_OPEN, STATE_SUSPENDED, STATE_BLOCKED, STATE_ABSENT = "OPEN", "SUSPENDED", "BLOCKED", "ABSENT"

# Provider field names the parser knows by name. The maps pin VALUES; the closed response schema
# pins STRUCTURE; these are the few structural roles that schema flags cannot express.
KEY_FIXTURE_ID = "fixtureId"
KEY_TOURNAMENT = "tournamentId"
KEY_SPORT = "sportId"
KEY_HOME, KEY_AWAY = "participant1Id", "participant2Id"
KEY_HOME_NAME, KEY_AWAY_NAME = "participant1Name", "participant2Name"
KEY_START = "startTime"
KEY_BOOKMAKERS = "bookmakerOdds"
KEY_MARKETS, KEY_OUTCOMES, KEY_PLAYERS = "markets", "outcomes", "players"
KEY_HANDICAP, KEY_PRICE, KEY_CHANGED = "handicap", "price", "changedAt"
EVENT_TIMESTAMP_KEYS = ("updatedAt", "trueStartTime", "trueEndTime")
_PARTICIPANT_KEYS = (KEY_HOME, KEY_AWAY)
_MISSING_OR_TYPE = ("WRONG_TYPE", "MISSING_REQUIRED")
_DECIMAL = Context(prec=40, rounding=ROUND_HALF_EVEN)          # deterministic, ambient-independent
_ZERO_OFFSET = timedelta(0)

_JSON_FAILURES = {
    "OVERSIZE": AdapterFailure.OVERSIZE_BODY, "INVALID_UTF8": AdapterFailure.INVALID_UTF8,
    "EMPTY": AdapterFailure.NOT_JSON, "NOT_JSON": AdapterFailure.NOT_JSON,
    "DUPLICATE_KEYS": AdapterFailure.DUPLICATE_KEYS, "NONFINITE_NUMBER": AdapterFailure.NONFINITE_NUMBER,
}


# --------------------------------------------------------------------------------------
# Context and result types
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class FixtureInfo:
    fixture_id: str
    tournament_id: int
    start_time: str


@dataclass(frozen=True)
class FixtureSnapshot:
    """The newest FIXTURES capture, used to join a scheduled start the ODDS payload lacks (design 8.3)."""

    observation_id: str
    retrieved_at: str
    fixtures: Mapping[str, FixtureInfo]


@dataclass(frozen=True)
class ExpectedBook:
    """One book of the expected scope (design 12.4) with everything an ABSENT document needs."""

    entity_id: str
    event_id: str
    competition_id: str
    provider_fixture_id: Mapping[str, str]
    home_participant_id: str | None
    away_participant_id: str | None
    scheduled_start_as_known: str | None
    bookmaker_id: str
    provider_bookmaker_key: str
    market_id: str
    market_family: str
    line: str | None
    period: str


@dataclass(frozen=True)
class ParseContext:
    acquisition_id: str
    provider_request_hash: str
    raw_artifact_hash: str
    raw_observation_id: str
    request_started_at: str
    response_received_at: str
    maps: AdapterMaps
    policy: Any                                     # SlicePolicy
    response_schema: schema.ClosedSchema
    derivation_version: str
    # The competitions the request named (its tournamentIds through the pinned map), read from the stored
    # canonical request. A requested competition the payload does not show is an unproven omission, so the
    # response is partial and nothing is tombstoned (design 12.4, section 15 F-15; hostile audit F-03).
    requested_competitions: tuple[str, ...]
    identity_prefix: tuple[Mapping[str, Any], ...] = ()
    expected_scope: Mapping[str, ExpectedBook] | None = None
    expected_scope_hash: str | None = None          # hash of the scope artifact the mapping came from
    fixture_join: FixtureSnapshot | None = None
    complete_hint: bool = True                      # False when the provider says the payload is partial


@dataclass(frozen=True)
class EventFacts:
    competition_id: str
    event_id: str
    provider_fixture_id: Mapping[str, str]
    home_participant_id: str | None
    away_participant_id: str | None
    scheduled_start_as_known: str | None
    fixture_join_observation_id: str | None
    event_status: Any                               # the raw typed provider status value, or None


@dataclass(frozen=True)
class BookResult:
    entity_id: str
    event: EventFacts
    bookmaker_id: str
    provider_bookmaker_key: str
    market_id: str
    market_family: str
    line: str | None
    period: str
    state: str
    reasons: tuple[str, ...]
    selections: Mapping[str, Mapping[str, Any]] | None       # selection code -> {provider_outcome_id, odds_decimal}
    provider_status: Mapping[str, Any]
    provider_timestamps: Mapping[str, str]
    publisher_timestamp: str | None


@dataclass(frozen=True)
class Exclusion:
    code: str
    count: int


@dataclass(frozen=True)
class ParsedResponse:
    books: tuple[BookResult, ...]
    tombstones: tuple[ExpectedBook, ...]
    exclusions: tuple[Exclusion, ...]
    identity_rows: tuple[Mapping[str, Any], ...]
    quarantined_events: tuple[str, ...]
    failure: AdapterFailure | None
    partial: bool
    findings: tuple[schema.DriftFinding, ...]

    @property
    def complete(self) -> bool:
        return self.failure is None and not self.partial


# --------------------------------------------------------------------------------------
# Small pure helpers
# --------------------------------------------------------------------------------------
def classify_timestamp(text: Any) -> tuple[datetime | None, AdapterFailure | None]:
    """A provider timestamp as an aware UTC datetime, or the exact anomaly (design 6.4).

    Offsets are rejected, never normalized: naive -> TIMESTAMP_NAIVE, explicit non-zero offset ->
    TIMESTAMP_NON_UTC, anything unparseable or not a string -> TIMESTAMP_INVALID.
    """

    if type(text) is not str:
        return None, AdapterFailure.TIMESTAMP_INVALID
    cleaned = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None, AdapterFailure.TIMESTAMP_INVALID
    if parsed.tzinfo is None:
        return None, AdapterFailure.TIMESTAMP_NAIVE
    if parsed.utcoffset() != _ZERO_OFFSET:
        return None, AdapterFailure.TIMESTAMP_NON_UTC
    return parsed.astimezone(UTC), None


def decimal_text(value: Decimal) -> str:
    """The canonical text of a decimal: ``format(Decimal(literal).normalize(), "f")``."""

    return format(value.normalize(_DECIMAL), "f")


def _fraction_digits(value: Decimal) -> int:
    exponent = value.normalize(_DECIMAL).as_tuple().exponent
    return -exponent if exponent < 0 else 0


def _as_decimal(value: Any) -> Decimal | None:
    if type(value) is Decimal:
        return value
    if type(value) is int:
        return Decimal(value)
    return None


def _line_from(value: Any) -> Decimal | None:
    """A line from a JSON number or a numeric string; None when it cannot be read exactly."""

    if type(value) is str:
        try:
            parsed = Decimal(value.strip())
        except ArithmeticError:
            return None
        return parsed if parsed.is_finite() else None
    return _as_decimal(value)


def _price_problem(value: Decimal, policy) -> AdapterFailure | None:
    """INVALID_PRICE for an out-of-band or over-precise price; the caller handles ``<= 1``."""

    if value < Decimal(policy.odds_min) or value > Decimal(policy.odds_max):
        return AdapterFailure.INVALID_PRICE
    if _fraction_digits(value) > policy.odds_max_fraction_digits:
        return AdapterFailure.INVALID_PRICE
    return None


def _sorted(codes: Iterable[AdapterFailure | str]) -> tuple[str, ...]:
    return tuple(sorted({str(code) for code in codes}))


def _typed(value: Any) -> bool:
    return type(value) in (bool, int, str)


def _comparable(value: Any) -> Any:
    """``value`` with every decimal replaced by its canonical text, so payload fragments can be compared
    (the frozen ``canonical_json`` refuses ``Decimal``, and ``1.910`` must equal ``1.91``)."""

    if type(value) is Decimal:
        return decimal_text(value)
    if type(value) is dict:
        return {key: _comparable(item) for key, item in value.items()}
    if type(value) is list:
        return [_comparable(item) for item in value]
    return value


def _same(first: Any, second: Any) -> bool:
    return canonical_json(_comparable(first)) == canonical_json(_comparable(second))


def _outcome_native(outcome_id: str) -> dict[str, str]:
    """Outcome ids are JSON object keys (always text); digits are an int id, anything else a str id."""

    return native_id(int(outcome_id) if outcome_id.isdigit() else outcome_id,
                     declared_type="int" if outcome_id.isdigit() else "str")


# --------------------------------------------------------------------------------------
# FIXTURES snapshot (used only for the scheduled-start join)
# --------------------------------------------------------------------------------------
def build_fixture_snapshot(raw: bytes, *, observation_id: str, retrieved_at: str, maps: AdapterMaps,
                           policy, fixtures_schema: schema.ClosedSchema) -> FixtureSnapshot | None:
    """A snapshot from one FIXTURES response, or None when the response is unusable as a whole.

    Only fixtures of allowlisted competitions with a valid scheduled start are kept, and a fixture
    id that appears twice with different content is dropped (it can never be joined).
    """

    try:
        payload = jsonstrict.loads_strict(raw, max_bytes=policy.max_response_bytes)
    except jsonstrict.StrictJsonError:
        return None
    if any(f.scope == "RESPONSE" for f in schema.validate_closed(payload, fixtures_schema)):
        return None
    kept: dict[str, FixtureInfo] = {}
    dropped: set[str] = set()
    for item in payload:
        try:
            fixture_id = native_id(item[KEY_FIXTURE_ID], declared_type="str")["value"]
        except IdentityTypeError:
            continue
        tournament = item.get(KEY_TOURNAMENT)
        start, problem = classify_timestamp(item.get(KEY_START))
        if type(tournament) is not int or problem is not None \
                or maps.competition("int", str(tournament)) is None:
            continue
        info = FixtureInfo(fixture_id, tournament, iso_utc(start))
        if fixture_id in kept and kept[fixture_id] != info:
            dropped.add(fixture_id)
        kept[fixture_id] = info
    return FixtureSnapshot(observation_id, retrieved_at,
                           {key: value for key, value in sorted(kept.items()) if key not in dropped})


# --------------------------------------------------------------------------------------
# Attribution of drift findings
# --------------------------------------------------------------------------------------
class _Attribution:
    """Drift findings, attributed to exact entities by their path trail (never by parsing text)."""

    def __init__(self, findings: Sequence[schema.DriftFinding], statuses: Mapping[str, str | None],
                 timestamp_keys: frozenset[str]):
        self.event: dict[int, set[AdapterFailure]] = {}
        self.bookmaker: dict[tuple[int, str], set[AdapterFailure]] = {}
        self.book: dict[tuple[int, str, str], set[AdapterFailure]] = {}
        for item in findings:
            if item.scope == "RESPONSE" or not item.trail:
                continue
            code = self._code(item, statuses, timestamp_keys)
            index = item.trail[0]
            if item.scope == "EVENT":
                self.event.setdefault(index, set()).add(code)
            elif item.scope == "EVENT_BOOKMAKER" and len(item.trail) >= 3:
                self.bookmaker.setdefault((index, item.trail[2]), set()).add(code)
            elif item.scope == "BOOK" and len(item.trail) >= 5:
                self.book.setdefault((index, item.trail[2], item.trail[4]), set()).add(code)
            else:                                               # cannot be attributed: widen to the event
                self.event.setdefault(index, set()).add(code)

    @staticmethod
    def _code(item: schema.DriftFinding, statuses, timestamp_keys) -> AdapterFailure:
        key = item.trail[-1] if isinstance(item.trail[-1], str) else None
        typed = item.kind in _MISSING_OR_TYPE
        if typed and key in _PARTICIPANT_KEYS:
            return AdapterFailure.PARTICIPANT_AMBIGUOUS
        if typed and key is not None and key == statuses.get("event"):
            return AdapterFailure.UNKNOWN_EVENT_STATUS
        if typed and key is not None and key == statuses.get("outcome"):
            return AdapterFailure.UNKNOWN_OUTCOME_STATUS
        if typed and key is not None and key == statuses.get("bookmaker"):
            return AdapterFailure.UNKNOWN_MARKET_STATUS
        if typed and key == KEY_START:
            return AdapterFailure.EVENT_START_INVALID
        if typed and key in timestamp_keys:
            return AdapterFailure.TIMESTAMP_INVALID
        return AdapterFailure.SCHEMA_DRIFT


# --------------------------------------------------------------------------------------
# The parser
# --------------------------------------------------------------------------------------
@dataclass
class _Outcome:
    outcome_id: str
    selection: str
    active_value: Any = None
    active_state: str | None = None
    price: Decimal | None = None
    price_present: bool = False
    changed_at_text: str | None = None
    changed_at: datetime | None = None
    readable: bool = True            # False when its price entry could not be read (the problem is on the read)


@dataclass
class _Read:
    """One mapped market of one bookmaker in one event, read without judgement."""

    market_key: str
    entry: MarketEntry
    line: Decimal | None
    outcomes: dict[str, _Outcome] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)
    problems: set[AdapterFailure] = field(default_factory=set)


class _Parser:
    def __init__(self, ctx: ParseContext):
        self.ctx = ctx
        self.maps = ctx.maps
        self.policy = ctx.policy
        self.t1 = classify_timestamp(ctx.response_received_at)[0]
        self.future_limit = self.t1 + timedelta(seconds=self.policy.provider_future_tolerance_seconds)
        self.guard = timedelta(seconds=self.policy.prematch_guard_seconds)
        self.state = registry.replay(ctx.identity_prefix)
        self.families = ctx.maps.families
        self.expected = dict(ctx.expected_scope or {})
        self.expected_by_event: dict[str, list[ExpectedBook]] = {}
        for book in self.expected.values():
            self.expected_by_event.setdefault(book.event_id, []).append(book)
        self.books: dict[str, BookResult] = {}
        self.suppressed: set[str] = set()
        self.exclusions: Counter[str] = Counter()
        self.identity_rows: list[dict[str, Any]] = []
        self.proposed_names: dict[str, str] = {}
        self.quarantined: list[str] = []
        self.timestamp_keys = frozenset(
            name for obj in ctx.response_schema.objects.values()
            for name, spec in obj.keys.items() if spec.timestamp)
        self.statuses = {level: ctx.maps.status_field(level) for level in ("event", "outcome", "bookmaker")}

    # -- entry point ------------------------------------------------------------------------
    def run(self, payload: list, findings: tuple[schema.DriftFinding, ...]) -> ParsedResponse:
        attribution = _Attribution(findings, self.statuses, self.timestamp_keys)
        partial = not self.ctx.complete_hint or any(
            f.kind == "MISSING_REQUIRED" and f.scope != "RESPONSE" for f in findings) \
            or bool(self._omitted_competitions(payload))
        groups: dict[str, list[tuple[int, dict]]] = {}
        for index, item in enumerate(payload):
            groups.setdefault(item[KEY_FIXTURE_ID], []).append((index, item))
        for fixture_id in sorted(groups):
            self._event(fixture_id, groups[fixture_id], attribution)
        tombstones: tuple[ExpectedBook, ...] = ()
        if not partial:
            tombstones = tuple(book for key, book in sorted(self.expected.items())
                               if key not in self.books and key not in self.suppressed)
        else:
            self.exclusions[AdapterFailure.PARTIAL_RESPONSE.value] += 1
        return ParsedResponse(
            books=tuple(self.books[key] for key in sorted(self.books)), tombstones=tombstones,
            exclusions=tuple(Exclusion(code, count) for code, count in sorted(self.exclusions.items())),
            identity_rows=tuple(self.identity_rows), quarantined_events=tuple(sorted(set(self.quarantined))),
            failure=None, partial=partial, findings=findings)

    def _omitted_competitions(self, payload: list) -> tuple[str, ...]:
        """Requested competitions with no in-scope fixture in ``payload`` (design 12.4, section 15 F-15).

        The ODDS payload is a flat fixture list, so a requested tournament is visible only through its fixtures;
        one with no fixture at all may simply be missing from this response. Only an exactly typed tournament id
        (no ``"8"``, ``8.0`` or ``true``) of the pinned sport that maps to the competition counts as present."""

        present = set()
        for item in payload:
            tournament, sport = item.get(KEY_TOURNAMENT), item.get(KEY_SPORT)
            if type(tournament) is not int or type(sport) is not int or sport != self.maps.sport_id:
                continue
            competition = self.maps.competition("int", str(tournament))
            if competition is not None:
                present.add(competition.genesis_id)
        return tuple(item for item in self.ctx.requested_competitions if item not in present)

    # -- one fixture ------------------------------------------------------------------------
    def _resolve_competition(self, fixture: dict, event_id: str) -> tuple[str | None, bool]:
        """(competition id, drift): the map's id, the id of an already-known book, or None when out of scope."""

        tournament, sport = fixture.get(KEY_TOURNAMENT), fixture.get(KEY_SPORT)
        if type(tournament) is int:
            competition: Competition | None = self.maps.competition("int", str(tournament))
            if competition is None or (type(sport) is int and sport != self.maps.sport_id):
                return None, False
            return competition.genesis_id, False
        known = self.expected_by_event.get(event_id)
        return (known[0].competition_id if known else None), True

    def _event(self, fixture_id: str, objs: list[tuple[int, dict]], attribution: _Attribution) -> None:
        index, fixture = objs[0]
        native = native_id(fixture_id, declared_type="str")
        event_id = gid("evt", provider=PROVIDER, ns=FIXTURE_NS, native_type="str", native=native["value"])
        competition_id, unresolved = self._resolve_competition(fixture, event_id)
        if competition_id is None:
            self.exclusions[(AdapterFailure.SCHEMA_DRIFT if unresolved
                             else AdapterFailure.OUT_OF_SCOPE_COMPETITION).value] += 1
            return
        blockers: set[AdapterFailure] = set()
        if unresolved:
            blockers.add(AdapterFailure.SCHEMA_DRIFT)
        for _, twin in objs[1:]:
            if not _same(twin, fixture):
                blockers.add(AdapterFailure.CONTRADICTORY_DUPLICATE)
        for position, _ in objs:
            blockers |= attribution.event.get(position, set())

        home_id = self._participant(fixture.get(KEY_HOME), blockers)
        away_id = self._participant(fixture.get(KEY_AWAY), blockers)
        if home_id is not None and home_id == away_id:
            blockers.add(AdapterFailure.PARTICIPANT_AMBIGUOUS)

        status_field = self.statuses["event"]
        status_value = fixture.get(status_field) if status_field else None
        event_state = self.maps.classify("event", status_field, status_value) if status_field else None
        if event_state is None:
            blockers.add(AdapterFailure.UNKNOWN_EVENT_STATUS)

        start, join_id = self._start(fixture, native["value"], competition_id, blockers)
        for key in EVENT_TIMESTAMP_KEYS:
            if type(fixture.get(key)) is str:
                moment, problem = classify_timestamp(fixture[key])
                if problem is not None:
                    blockers.add(problem)
                elif moment > self.future_limit:
                    blockers.add(AdapterFailure.TIMESTAMP_FUTURE)
        if event_state == "PREMATCH" and start is not None and start <= self.t1:
            blockers.add(AdapterFailure.CONTRADICTORY_STATUS)

        self._identity(fixture, event_id, native, competition_id, home_id, away_id, blockers)
        facts = EventFacts(competition_id, event_id, native, home_id, away_id,
                           None if start is None else iso_utc(start), join_id,
                           status_value if _typed(status_value) else None)
        candidates = self._candidates(event_id)
        if event_state == "PREMATCH" and not blockers and start is not None \
                and self.t1 >= start - self.guard:                       # F-27: nothing is emitted
            self.exclusions[AdapterFailure.PREMATCH_WINDOW_CLOSED.value] += 1
            self.suppressed |= {entry[0] for entry in candidates.values()}
            return

        reads = self._reads(index, fixture, attribution)
        for (bookmaker_key, family), (entity, bookmaker, line, market_id) in sorted(candidates.items()):
            group = reads.get((bookmaker_key, family), [])
            inactive, book_blockers = self._bookmaker_state(fixture, bookmaker_key,
                                                            attribution.bookmaker.get((index, bookmaker_key), set()))
            all_blockers = blockers | book_blockers
            if not group and entity not in self.expected:
                continue                                                # nothing is known about this book
            if not group and not all_blockers and event_state != "NOT_PREMATCH":
                continue                                                # absent: a tombstone if complete
            self.books[entity] = self._book(entity, facts, bookmaker, family, line, market_id, group,
                                            event_state, all_blockers, inactive)

    # -- identity ----------------------------------------------------------------------------
    @staticmethod
    def _participant(value: Any, blockers: set[AdapterFailure]) -> str | None:
        if type(value) is not int or value < 0:
            blockers.add(AdapterFailure.PARTICIPANT_AMBIGUOUS)
            return None
        return gid("part", provider=PROVIDER, ns=PARTICIPANT_NS, native_type="int",
                   native=native_id(value, declared_type="int")["value"])

    def _identity(self, fixture, event_id, native, competition_id, home_id, away_id, blockers) -> None:
        """Registry rows for a clean first sight, or an IDENTITY_CONFLICT (never a row)."""

        existing = self.state.fixtures.get(event_id)
        if existing is not None and home_id is not None and away_id is not None:
            if (existing["competition_id"], existing["home_participant_id"],
                    existing["away_participant_id"]) != (competition_id, home_id, away_id):
                blockers.add(AdapterFailure.IDENTITY_CONFLICT)
                self.quarantined.append(event_id)
                return
        if blockers or home_id is None or away_id is None:
            return
        if existing is None:
            self.identity_rows.append(registry.fixture_binding_row(
                event_id=event_id, provider_fixture_id=native, competition_id=competition_id,
                home_participant_id=home_id, away_participant_id=away_id,
                first_seen_at=iso_utc(self.t1), raw_observation_id=self.ctx.raw_observation_id))
        for participant_id, provider_id, name in (
                (home_id, fixture.get(KEY_HOME), fixture.get(KEY_HOME_NAME)),
                (away_id, fixture.get(KEY_AWAY), fixture.get(KEY_AWAY_NAME))):
            if type(name) is not str or not name:
                continue
            known = self.proposed_names.get(participant_id, self.state.participants.get(participant_id))
            if known == name:
                continue
            self.proposed_names[participant_id] = name
            self.identity_rows.append(registry.participant_seen_row(
                participant_id=participant_id,
                provider_participant_id=native_id(provider_id, declared_type="int"), display_name=name,
                first_seen_at=iso_utc(self.t1), raw_observation_id=self.ctx.raw_observation_id,
                drift=known is not None))

    # -- scheduled start ---------------------------------------------------------------------
    def _start(self, fixture, fixture_id, competition_id, blockers) -> tuple[datetime | None, str | None]:
        """S from the payload, else from the joined FIXTURES snapshot (design 8.3), else a blocker."""

        if KEY_START in fixture:
            if type(fixture[KEY_START]) is not str:                  # a wrong type is drift, reported already
                return None, None
            moment, problem = classify_timestamp(fixture[KEY_START])
            if problem is not None:
                blockers.add(AdapterFailure.EVENT_START_INVALID)
                return None, None
            return moment, None
        join = self.ctx.fixture_join
        info = None if join is None else join.fixtures.get(fixture_id)
        if info is None:
            blockers.add(AdapterFailure.EVENT_METADATA_STALE)
            return None, None
        captured = classify_timestamp(join.retrieved_at)[0]
        joined = self.maps.competition("int", str(info.tournament_id))
        fresh = captured is not None and captured <= self.t1 and self.t1 - captured <= timedelta(
            seconds=self.policy.fixture_join_max_age_seconds)
        if not fresh or joined is None or joined.genesis_id != competition_id:
            blockers.add(AdapterFailure.EVENT_METADATA_STALE)
            return None, None
        return classify_timestamp(info.start_time)[0], join.observation_id

    # -- candidates ----------------------------------------------------------------------------
    def _candidates(self, event_id: str):
        """(bookmaker key, family) -> (entity id, bookmaker, line text, market id), for every declared book."""

        found = {}
        for bookmaker in self.maps.declared_bookmakers():
            for family in self.families.values():
                line = None if family.required_line is None else decimal_text(family.required_line)
                market_id = gid("mkt", event_id=event_id, family=family.name, line=line, period=family.period)
                entity = gid("book", market_id=market_id, bookmaker_id=bookmaker.genesis_id)
                found[(bookmaker.key, family.name)] = (entity, bookmaker, line, market_id)
        return found

    # -- bookmaker level -----------------------------------------------------------------------
    def _bookmaker_state(self, fixture, bookmaker_key: str, drift: set[AdapterFailure]):
        blockers = set(drift)
        inactive = False
        blocks = fixture.get(KEY_BOOKMAKERS)
        block = blocks.get(bookmaker_key) if type(blocks) is dict else None
        field_name = self.statuses["bookmaker"]
        if type(block) is dict and field_name in block:
            state = self.maps.classify("bookmaker", field_name, block[field_name])
            if state is None:
                blockers.add(AdapterFailure.UNKNOWN_MARKET_STATUS)
            elif state == "INACTIVE":
                inactive = True
        return inactive, blockers

    # -- markets -------------------------------------------------------------------------------
    def _reads(self, index: int, fixture: dict, attribution: _Attribution) -> dict:
        reads: dict[tuple[str, str], list[_Read]] = {}
        blocks = fixture.get(KEY_BOOKMAKERS)
        if type(blocks) is not dict:
            return reads
        for key in sorted(blocks):
            bookmaker = self.maps.bookmakers.get(key)
            if bookmaker is None or not bookmaker.declared:
                self.exclusions[AdapterFailure.OUT_OF_SCOPE_BOOKMAKER.value] += 1
                continue
            block = blocks[key]
            markets = block.get(KEY_MARKETS) if type(block) is dict else None
            if type(markets) is not dict:
                continue
            for market_key in sorted(markets):
                entry = self.maps.market("int", market_key) if market_key.isascii() and market_key.isdigit() \
                    else None
                entry = entry or self.maps.market("str", market_key)
                if entry is None:
                    self.exclusions[AdapterFailure.OUT_OF_SCOPE_MARKET.value] += 1
                    continue
                read = self._read_market(market_key, markets[market_key], entry,
                                         attribution.book.get((index, key, market_key), set()))
                if read is not None:
                    reads.setdefault((key, entry.family), []).append(read)
        return reads

    def _read_market(self, market_key: str, market: Any, entry: MarketEntry, drift: set[AdapterFailure]):
        family = self.families[entry.family]
        outcomes = market.get(KEY_OUTCOMES) if type(market) is dict else None
        line = self._line(entry, outcomes)
        if family.required_line is not None:
            if line is None:
                if not drift:            # an unreadable line cannot be judged; a drifting market blocks instead
                    self.exclusions[AdapterFailure.LINE_UNIDENTIFIED.value] += 1
                    return None
            elif line != family.required_line:
                self.exclusions[AdapterFailure.OUT_OF_SCOPE_LINE.value] += 1
                return None
        elif self._any_line_field(outcomes):
            self.exclusions[AdapterFailure.LINE_UNIDENTIFIED.value] += 1   # a line from an undeclared source
            return None
        read = _Read(market_key, entry, line)
        read.problems |= drift
        if type(outcomes) is not dict:
            return read
        for outcome_id in sorted(outcomes):
            selection = entry.outcomes.get(outcome_id)
            if selection is None:
                read.unmapped.append(outcome_id)
            else:
                read.outcomes[selection] = self._read_outcome(outcome_id, selection, outcomes[outcome_id], read)
        return read

    @staticmethod
    def _any_line_field(outcomes: Any) -> bool:
        return type(outcomes) is dict and any(
            type(item) is dict and KEY_HANDICAP in item for item in outcomes.values())

    @staticmethod
    def _line(entry: MarketEntry, outcomes: Any) -> Decimal | None:
        if entry.line_source == "market_definition":
            return entry.line
        field_name = entry.outcome_field
        if field_name is None or type(outcomes) is not dict or not outcomes:
            return None
        seen: set[Decimal] = set()
        for item in outcomes.values():
            if type(item) is not dict or field_name not in item:
                return None
            value = _line_from(item[field_name])
            if value is None:
                return None
            seen.add(value)
        return next(iter(seen)) if len(seen) == 1 else None

    def _read_outcome(self, outcome_id: str, selection: str, obj: Any, read: _Read) -> _Outcome:
        result = _Outcome(outcome_id, selection, readable=False)
        if type(obj) is not dict:
            return result                                            # drift on the outcome, reported already
        players = obj.get(KEY_PLAYERS)
        if type(players) is not dict:
            return result                                            # missing or mistyped: schema drift blocks it
        if not players:
            read.problems.add(AdapterFailure.INCOMPLETE_SELECTIONS)
            return result
        entries = [players[key] for key in sorted(players)]
        if not all(_same(entry, entries[0]) for entry in entries):   # identical duplicates collapse
            read.problems.add(AdapterFailure.CONTRADICTORY_DUPLICATE)
            return result
        price = entries[0]
        if type(price) is not dict:
            return result
        result.readable = True
        status_field = self.statuses["outcome"]
        if status_field in price:
            result.active_value = price[status_field]
            result.active_state = self.maps.classify("outcome", status_field, price[status_field])
        result.price_present = price.get(KEY_PRICE) is not None
        result.price = _as_decimal(price.get(KEY_PRICE))
        if type(price.get(KEY_CHANGED)) is str:
            result.changed_at_text = price[KEY_CHANGED]
            moment, problem = classify_timestamp(result.changed_at_text)
            if problem is not None:
                read.problems.add(problem)
            else:
                result.changed_at = moment
                if moment > self.future_limit:
                    read.problems.add(AdapterFailure.TIMESTAMP_FUTURE)
        return result

    # -- one book ------------------------------------------------------------------------------
    def _book(self, entity, facts: EventFacts, bookmaker: Bookmaker, family_name: str, line: str | None,
              market_id: str, group: list[_Read], event_state, blockers: set[AdapterFailure],
              bookmaker_inactive: bool) -> BookResult:
        family = self.families[family_name]
        blockers = set(blockers)
        suspenders: set[AdapterFailure] = set()
        timestamps: dict[str, str] = {}
        status_outcomes: dict[str, Any] = {}
        publisher: datetime | None = None
        read = group[0] if group else None
        if len(group) > 1 and len({self._signature(item) for item in group}) > 1:
            blockers.add(AdapterFailure.CONTRADICTORY_DUPLICATE)
        any_active = False
        if read is not None:
            blockers |= read.problems
            if read.unmapped:
                blockers.add(AdapterFailure.UNMAPPED_OUTCOME)
            if AdapterFailure.SCHEMA_DRIFT not in read.problems and any(
                    selection not in read.outcomes for selection in family.selections):
                blockers.add(AdapterFailure.INCOMPLETE_SELECTIONS)
            for selection in family.selections:
                outcome = read.outcomes.get(selection)
                if outcome is None or not outcome.readable:
                    continue
                status_outcomes[outcome.outcome_id] = outcome.active_value if _typed(outcome.active_value) else None
                if outcome.changed_at_text is not None:
                    timestamps[f"outcome.{outcome.outcome_id}.changedAt"] = outcome.changed_at_text
                if outcome.changed_at is not None and (publisher is None or outcome.changed_at > publisher):
                    publisher = outcome.changed_at
                if outcome.active_state is None:
                    blockers.add(AdapterFailure.UNKNOWN_OUTCOME_STATUS)
                elif outcome.active_state == "INACTIVE":
                    suspenders.add(AdapterFailure.OUTCOME_INACTIVE)
                else:
                    any_active = True
                    problem = self._active_price_problem(outcome)
                    if problem is not None:
                        blockers.add(problem)
        if event_state == "NOT_PREMATCH":
            blockers.add(AdapterFailure.CONTRADICTORY_STATUS if any_active else AdapterFailure.EVENT_NOT_PREMATCH)
        if bookmaker_inactive:
            suspenders.add(AdapterFailure.MARKET_SUSPENDED)
        if read is not None and not blockers and not suspenders and not self._coherent(read, family):
            blockers.add(AdapterFailure.PRICE_INCOHERENT)
        selections = None
        if blockers:
            state, reasons = STATE_BLOCKED, _sorted(blockers)
        elif suspenders:
            state, reasons = STATE_SUSPENDED, _sorted(suspenders)
        else:
            state, reasons = STATE_OPEN, ()
            selections = {s: {"provider_outcome_id": _outcome_native(read.outcomes[s].outcome_id),
                              "odds_decimal": decimal_text(read.outcomes[s].price)}
                          for s in family.selections}
        clean = read is not None and not read.problems
        return BookResult(
            entity_id=entity, event=facts, bookmaker_id=bookmaker.genesis_id,
            provider_bookmaker_key=bookmaker.key, market_id=market_id, market_family=family_name, line=line,
            period=family.period, state=state, reasons=reasons, selections=selections,
            provider_status={"event": {self.statuses["event"]: facts.event_status}
                             if facts.event_status is not None else {},
                             "market": {}, "outcomes": dict(sorted(status_outcomes.items())) if clean else {}},
            provider_timestamps=dict(sorted(timestamps.items())),
            publisher_timestamp=None if publisher is None or state == STATE_BLOCKED else iso_utc(publisher))

    def _active_price_problem(self, outcome: _Outcome) -> AdapterFailure | None:
        if outcome.price is None:
            # a price of the wrong type is drift (reported already); an absent or null one is a contradiction
            return None if outcome.price_present else AdapterFailure.CONTRADICTORY_STATUS
        if outcome.price <= Decimal(1):
            return AdapterFailure.CONTRADICTORY_STATUS               # active at or below even money
        return _price_problem(outcome.price, self.policy)

    def _coherent(self, read: _Read, family: Family) -> bool:
        band = self.policy.overround_1x2 if family.required_line is None else self.policy.overround_ou
        total = Decimal(0)
        for selection in family.selections:
            total = _DECIMAL.add(total, _DECIMAL.divide(Decimal(1), read.outcomes[selection].price))
        return Decimal(band[0]) <= total <= Decimal(band[1])

    @staticmethod
    def _signature(read: _Read) -> bytes:
        return canonical_json({
            "line": None if read.line is None else decimal_text(read.line),
            "outcomes": {s: [o.outcome_id, o.active_value if _typed(o.active_value) else None,
                             None if o.price is None else decimal_text(o.price), o.changed_at_text]
                         for s, o in sorted(read.outcomes.items())},
            "unmapped": sorted(read.unmapped), "problems": sorted(str(p) for p in read.problems)})


# --------------------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------------------
def _rejected(failure: AdapterFailure, findings=()) -> ParsedResponse:
    return ParsedResponse((), (), (), (), (), failure, False, tuple(findings))


def parse_odds_response(raw: bytes, ctx: ParseContext) -> ParsedResponse:
    """Parse one ODDS response. Pure: the same bytes and context always give the same result."""

    try:
        payload = jsonstrict.loads_strict(raw, max_bytes=ctx.policy.max_response_bytes)
    except jsonstrict.StrictJsonError as exc:
        return _rejected(_JSON_FAILURES[exc.code])
    findings = schema.validate_closed(payload, ctx.response_schema)
    envelope = [item for item in findings if item.scope == "RESPONSE"]
    if envelope:
        typed = any(item.kind in _MISSING_OR_TYPE for item in envelope)
        return _rejected(AdapterFailure.ENVELOPE_SCHEMA_MISMATCH if typed else AdapterFailure.SCHEMA_DRIFT,
                         findings)
    for item in payload:                                     # an identity key outside its grammar is an
        try:                                                 # envelope problem: nothing can be attributed
            native_id(item[KEY_FIXTURE_ID], declared_type="str")
        except IdentityTypeError:
            return _rejected(AdapterFailure.ENVELOPE_SCHEMA_MISMATCH, findings)
    return _Parser(ctx).run(payload, findings)
