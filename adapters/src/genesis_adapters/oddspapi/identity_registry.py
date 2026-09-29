"""Append-only fixture / participant binding registry (design 8.3).

``identity.jsonl`` is a hash-chained :class:`genesis.registry.AppendOnlyJsonl` whose replay
validates every row. A fixture id is bound exactly once, on first sight in a schema-valid
response, to (competition, home participant, away participant). A later response that binds the
same fixture id differently is an ``IDENTITY_CONFLICT``: it is never written as a row, the event
is quarantined and a human resolves it through a new identity map version.

Every normalized document pins the head (``sequence`` and ``record_hash``) of the prefix its
derivation used, so re-derivation replays exactly that prefix (EV-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from genesis.registry import AppendOnlyJsonl, RegistryConflict
from genesis.time import TimestampError, iso_utc, parse_utc

SCHEMA_VERSION = "identity-registry-v1"
EMPTY_HEAD = {"sequence": 0, "record_hash": "0" * 64}
_CHAIN = frozenset({"previous_hash", "sequence", "record_hash"})
_COMMON = frozenset({"record_type", "schema_version"})
_ROW_KEYS = {
    "fixture_bound": frozenset({"event_id", "provider_fixture_id", "competition_id", "home_participant_id",
                                "away_participant_id", "first_seen_at", "raw_observation_id"}),
    "participant_seen": frozenset({"participant_id", "provider_participant_id", "display_name",
                                   "first_seen_at", "raw_observation_id", "note"}),
}
NOTE_FIRST_SEEN = "FIRST_SEEN"
NOTE_NAME_DRIFT = "NAME_DRIFT"


class IdentityConflict(RegistryConflict):
    """A binding that contradicts an existing registry row (design F-21)."""


class IdentityRegistryInvalid(RegistryConflict):
    """A registry row that would make the registry unreadable or inconsistent."""


@dataclass(frozen=True)
class IdentityState:
    fixtures: Mapping[str, Mapping[str, Any]]           # event_id -> fixture_bound row
    participants: Mapping[str, str]                     # participant_id -> latest display name


def _bad(message: str) -> None:
    raise IdentityRegistryInvalid(message)


def _native(value: Any, where: str) -> None:
    if type(value) is not dict or set(value) != {"native_type", "value"} \
            or value["native_type"] not in ("int", "str") or type(value["value"]) is not str \
            or not value["value"]:
        _bad(f"{where} is not a canonical native id")


def _text(value: Any, where: str) -> None:
    if type(value) is not str or not value:
        _bad(f"{where} must be a non-empty string")


def _stamp(value: Any, where: str) -> None:
    if type(value) is not str:
        _bad(f"{where} must be a timestamp string")
    try:
        parse_utc(value)
        if iso_utc(value) != value:
            _bad(f"{where} is not canonical")
    except TimestampError:
        _bad(f"{where} is not a valid UTC timestamp")


def replay(rows: Iterable[Mapping[str, Any]]) -> IdentityState:
    """Validate the whole history and return its state. Raises :class:`IdentityRegistryInvalid`."""

    fixtures: dict[str, Mapping[str, Any]] = {}
    participants: dict[str, str] = {}
    last = None
    for row in rows:
        kind = row.get("record_type")
        keys = _ROW_KEYS.get(kind)
        if keys is None or row.get("schema_version") != SCHEMA_VERSION:
            _bad("unknown identity registry record")
        if set(row) - _CHAIN != keys | _COMMON:
            _bad(f"{kind} has unexpected or missing keys")
        _stamp(row["first_seen_at"], "first_seen_at")
        if last is not None and row["first_seen_at"] < last:
            _bad("first_seen_at regressed")
        last = row["first_seen_at"]
        _text(row["raw_observation_id"], "raw_observation_id")
        if kind == "fixture_bound":
            _text(row["event_id"], "event_id")
            _native(row["provider_fixture_id"], "provider_fixture_id")
            _text(row["competition_id"], "competition_id")
            _text(row["home_participant_id"], "home_participant_id")
            _text(row["away_participant_id"], "away_participant_id")
            if row["home_participant_id"] == row["away_participant_id"]:
                _bad("a fixture cannot bind one participant as both home and away")
            if row["event_id"] in fixtures:
                _bad("a fixture id is bound exactly once")
            fixtures[row["event_id"]] = {k: v for k, v in row.items() if k not in _CHAIN}
        else:
            _text(row["participant_id"], "participant_id")
            _native(row["provider_participant_id"], "provider_participant_id")
            _text(row["display_name"], "display_name")
            seen = participants.get(row["participant_id"])
            if row["note"] == NOTE_FIRST_SEEN:
                if seen is not None:
                    _bad("FIRST_SEEN for a participant that was already seen")
            elif row["note"] == NOTE_NAME_DRIFT:
                if seen is None or seen == row["display_name"]:
                    _bad("NAME_DRIFT requires an earlier, different name")
            else:
                _bad("unknown participant note")
            participants[row["participant_id"]] = row["display_name"]
    return IdentityState(fixtures, participants)


def head_of(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``{"sequence", "record_hash"}`` of the last row of a verified prefix (empty prefix: sequence 0)."""

    if not rows:
        return dict(EMPTY_HEAD)
    last = rows[-1]
    return {"sequence": last["sequence"], "record_hash": last["record_hash"]}


def fixture_binding_row(*, event_id: str, provider_fixture_id: Mapping[str, str], competition_id: str,
                        home_participant_id: str, away_participant_id: str, first_seen_at: str,
                        raw_observation_id: str) -> dict[str, Any]:
    return {"record_type": "fixture_bound", "schema_version": SCHEMA_VERSION, "event_id": event_id,
            "provider_fixture_id": dict(provider_fixture_id), "competition_id": competition_id,
            "home_participant_id": home_participant_id, "away_participant_id": away_participant_id,
            "first_seen_at": first_seen_at, "raw_observation_id": raw_observation_id}


def participant_seen_row(*, participant_id: str, provider_participant_id: Mapping[str, str],
                         display_name: str, first_seen_at: str, raw_observation_id: str,
                         drift: bool) -> dict[str, Any]:
    return {"record_type": "participant_seen", "schema_version": SCHEMA_VERSION,
            "participant_id": participant_id, "provider_participant_id": dict(provider_participant_id),
            "display_name": display_name, "first_seen_at": first_seen_at,
            "raw_observation_id": raw_observation_id,
            "note": NOTE_NAME_DRIFT if drift else NOTE_FIRST_SEEN}


def _same_binding(existing: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    return all(existing[key] == row[key] for key in
               ("event_id", "provider_fixture_id", "competition_id", "home_participant_id",
                "away_participant_id"))


class IdentityRegistry:
    """The file-backed registry (``identity.jsonl``)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.log = AppendOnlyJsonl(self.path, reader=lambda rows: replay(rows))

    def rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.log.records())

    def head(self) -> dict[str, Any]:
        return head_of(self.rows())

    def state(self) -> IdentityState:
        return replay(self.rows())

    def prefix(self, sequence: int) -> tuple[dict[str, Any], ...]:
        """The first ``sequence`` rows (with chain fields), verified by :meth:`rows`."""

        rows = self.rows()
        if type(sequence) is not int or not 0 <= sequence <= len(rows):
            raise IdentityRegistryInvalid("the pinned registry head is beyond the registry")
        return rows[:sequence]

    def apply(self, proposed: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
        """Append the proposed rows idempotently; return the rows actually appended.

        A fixture binding that already exists identically, or a participant already seen under the
        same name, is treated as already applied (crash resume). A binding that differs from an
        existing one raises :class:`IdentityConflict` and appends nothing further.
        """

        appended: list[dict[str, Any]] = []
        for row in proposed:
            state = self.state()
            if row["record_type"] == "fixture_bound":
                existing = state.fixtures.get(row["event_id"])
                if existing is not None:
                    if not _same_binding(existing, row):
                        raise IdentityConflict("fixture id is already bound to a different identity")
                    continue
            else:
                seen = state.participants.get(row["participant_id"])
                if seen is not None and seen == row["display_name"]:
                    continue
                if (seen is None) != (row["note"] == NOTE_FIRST_SEEN):
                    row = {**row, "note": NOTE_FIRST_SEEN if seen is None else NOTE_NAME_DRIFT}
            self.log.append(dict(row))
            appended.append(dict(row))
        return tuple(appended)
