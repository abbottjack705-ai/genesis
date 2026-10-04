"""Deterministic reconstruction of a RESPONSE derivation and its byte-exact re-verification (design 9.1, 11.5).

A RESPONSE document depends ONLY on: the raw bytes (by ``raw_artifact_hash``), the acquisition record
(``T0``, ``T1``, the request), the pinned configuration (through ``derivation_version``), the pinned
identity-registry prefix, the expected-scope artifact and the fixture-join observation. This module
rebuilds a parse context from exactly those durable inputs, so that the pipeline, a crash resume, a
rebuild into empty stores and the verifier all derive with the same inputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from genesis.time import iso_utc, parse_utc

from genesis_adapters.errors import AdapterFailure
from genesis_adapters.oddspapi import identity_registry as identity_mod
from genesis_adapters.oddspapi import normalize, parser, scope as scope_mod
from genesis_adapters.oddspapi.acquisition import usage_diverges
from genesis_adapters.oddspapi.maps import AdapterMaps

ROLE_ODDS = "ODDS"
ROLE_FIXTURES = "FIXTURES"
HTTP_OK = 200


class DerivationError(ValueError):
    """A document whose derivation inputs are missing, inconsistent or do not reproduce its bytes."""


def _fail(message: str) -> None:
    raise DerivationError(message)


# --------------------------------------------------------------------------------------
# Acquisition ledger lookups
# --------------------------------------------------------------------------------------
def acquisition_rows(ledger, acquisition_id: str) -> dict[str, dict[str, Any]]:
    """The last row of each kind for one acquisition (the ledger's replay guarantees one of each)."""

    found: dict[str, dict[str, Any]] = {}
    for row in ledger.rows():
        if row.get("acquisition_id") == acquisition_id:
            found[row["record_type"]] = row
    return found


def usable_response(completed: Mapping[str, Any]) -> bool:
    """Whether a ``completed`` row is a response that may yield observations: a 200 whose content checks passed (its
    verdict is no failure), whose raw evidence was kept, and that does not call the provider's usage count into question.

    The last condition is the durable disposition of an acquisition-level QUOTA_DIVERGENCE (design 15 F-37: no
    observation; halt; hostile audit RA6-002). The runner records it as the response's own verdict, so ``failure`` is
    already set on every row it writes; reading the usage figure of the very same row as well keeps a row written
    before that (halt present, verdict clean) just as unusable. The one predicate serves every consumer of a response:
    the pipeline, a resume, a rebuild, the verifier and the fixture join."""

    return (completed["outcome"] == "RESPONSE" and completed["http_status"] == HTTP_OK
            and completed["failure"] is None and completed["raw_observation_id"] is not None
            and not usage_diverges(completed["provider_reported_usage"]))


def successful_capture(rows: Mapping[str, Mapping[str, Any]]) -> bool:
    """A usable 200 response whose derivation was not refused: the only kind of capture that can still be derived (or
    that still has documents). A capture whose pure derivation was rejected carries a durable terminal
    ``acq_derivation_rejected`` verdict (hostile audit RA5-001) and is never derived again."""

    completed = rows.get("acq_completed")
    return (completed is not None and usable_response(completed) and "acq_derivation_rejected" not in rows)


def load_request(root: Path, request_hash: str) -> dict[str, Any]:
    """The canonical request bytes stored at ``requests/<h>.json`` (their SHA-256 must be ``h``)."""

    from genesis.repro import sha256_bytes

    data = (Path(root) / "requests" / f"{request_hash}.json").read_bytes()
    if sha256_bytes(data) != request_hash:
        _fail("stored request bytes do not match their hash")
    return json.loads(data)


def request_scope_filters(request: Mapping[str, Any], maps: AdapterMaps) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(competition ids, bookmaker ids) an ODDS request covers: its tournaments and its declared bookmakers."""

    query = {name: value for name, value in request["query"]}
    tournaments = [item for item in query.get("tournamentIds", "").split(",") if item]
    competitions = sorted({maps.competition("int", item).genesis_id for item in tournaments
                           if maps.competition("int", item) is not None})
    keys = [item for item in query.get("bookmaker", "").split(",") if item]
    bookmakers = sorted({maps.bookmakers[key].genesis_id for key in keys
                         if key in maps.bookmakers and maps.bookmakers[key].declared})
    return tuple(competitions), tuple(bookmakers)


# --------------------------------------------------------------------------------------
# The deterministic inputs
# --------------------------------------------------------------------------------------
def fixture_snapshot_for(stores, config, maps: AdapterMaps, *, at: str) -> parser.FixtureSnapshot | None:
    """The newest successful FIXTURES capture received at or before ``at`` (or None).

    Selection reads only durable facts: the acquisition ledger (role, outcome, ``T1``) and the raw
    observation. A verified cache hit creates no new capture, so it selects its original capture. A response that
    is not usable (:func:`usable_response`: a failed check, or a quota divergence) is never the join.
    """

    roles: dict[str, str] = {}
    best = None
    moment = parse_utc(at)
    for row in stores.acquisition.rows():
        kind = row["record_type"]
        if kind == "acq_planned":
            roles[row["acquisition_id"]] = row["role"]
        elif kind == "acq_completed" and roles.get(row["acquisition_id"]) == ROLE_FIXTURES:
            if usable_response(row) and row["T1"] is not None and parse_utc(row["T1"]) <= moment:
                if best is None or parse_utc(row["T1"]) >= parse_utc(best["T1"]):
                    best = row
    if best is None:
        return None
    observation = stores.evidence.get_observation(best["raw_observation_id"])
    return snapshot_from_observation(stores, config, maps, observation.observation_id)


def snapshot_from_observation(stores, config, maps: AdapterMaps, observation_id: str) -> parser.FixtureSnapshot | None:
    observation = stores.evidence.get_observation(observation_id)
    return parser.build_fixture_snapshot(
        stores.evidence.get_bytes(observation.artifact_hash), observation_id=observation.observation_id,
        retrieved_at=observation.retrieved_at, maps=maps, policy=config.policy,
        fixtures_schema=config.schemas[config.endpoints[ROLE_FIXTURES].response_schema_id])


def expected_scope_at(stores, maps: AdapterMaps, request: Mapping[str, Any], *, tq: str):
    """The expected scope as of ``Tq`` (design 12.4).

    Deterministic at any later time: the PIT log is append-only and every record appended after ``Tq``
    has ``ready_at > Tq``, so it is not admissible at ``Tq``.
    """

    competitions, bookmakers = request_scope_filters(request, maps)
    return scope_mod.build_expected_scope(pit=stores.pit, evidence=stores.evidence, source_id=stores.source_id,
                                          decision_at=tq, competition_ids=competitions, bookmaker_ids=bookmakers)


@dataclass(frozen=True)
class DerivationInputs:
    raw: bytes
    ctx: parser.ParseContext


@dataclass(frozen=True)
class Derived:
    """The outcome of the pure derivation stage of one ODDS response: its documents, or the one reason there are
    none (``failure``). ``detail`` is the exception class name of a ``DERIVATION_FAULT`` (a code-defined name, never
    provider text); the runner screens it again before it is persisted."""

    parsed: parser.ParsedResponse | None
    documents: tuple
    failure: AdapterFailure | None
    detail: str | None = None


def derive(raw: bytes, ctx: parser.ParseContext) -> Derived:
    """The whole PURE stage of one ODDS response - parse, then build every document - as a TOTAL function.

    Hostile audit RA5-001: the parser and normalizer were documented as pure and total, but four classes of
    schema-valid provider content raised out of them after the capture was already recorded as a success, and every
    restart re-derived and re-raised. The known classes now have precise outcomes (the strict decoder's bounds, an
    ambiguous participant id); this boundary is what makes totality an invariant rather than a list of classes: any
    exception that provider content could still provoke ends here as one defined rejection, ``DERIVATION_FAULT``
    (design 15: no usable observation, coverage REJECTED), which the caller records as a durable terminal verdict.
    ``except Exception`` cannot swallow ``KeyboardInterrupt`` or ``SystemExit`` (FRZ-11)."""

    try:
        parsed = parser.parse_odds_response(raw, ctx)
        if parsed.failure is not None:
            return Derived(parsed, (), parsed.failure)
        return Derived(parsed, normalize.build_documents(parsed, ctx), None)
    except Exception as exc:                 # RecursionError, MemoryError, UnicodeEncodeError, anything else
        return Derived(None, (), AdapterFailure.DERIVATION_FAULT, type(exc).__name__)


def odds_inputs(stores, config, maps: AdapterMaps, acquisition_id: str, *, identity_prefix,
                expected_scope, expected_scope_hash: str | None,
                fixture_join: parser.FixtureSnapshot | None, request_root: Path) -> DerivationInputs:
    """The raw bytes and parse context of one successful ODDS acquisition.

    ``request_root`` holds ``requests/<hash>.json``: the requested competitions come from the stored canonical
    request whose SHA-256 is the acquisition's request hash, so normalization, ``verify_derivation`` and a
    rebuild all read the same requested set (design 12.4, F-15; hostile audit F-03)."""

    rows = acquisition_rows(stores.acquisition, acquisition_id)
    planned, sent, completed = rows.get("acq_planned"), rows.get("acq_sent"), rows.get("acq_completed")
    if planned is None or planned["role"] != ROLE_ODDS or sent is None or not successful_capture(rows):
        _fail("not a successful ODDS acquisition")
    requested, _ = request_scope_filters(load_request(request_root, planned["provider_request_hash"]), maps)
    raw_observation = stores.evidence.get_observation(completed["raw_observation_id"])
    if raw_observation.source_uri != "oddspapi-request:sha256:" + planned["provider_request_hash"]:
        _fail("the raw observation is not of this acquisition's request")
    if iso_utc(raw_observation.retrieved_at) != iso_utc(completed["T1"]):
        _fail("the raw observation was not received at this acquisition's T1")
    raw = stores.evidence.get_bytes(raw_observation.artifact_hash)
    ctx = parser.ParseContext(
        acquisition_id=acquisition_id, provider_request_hash=planned["provider_request_hash"],
        raw_artifact_hash=raw_observation.artifact_hash, raw_observation_id=raw_observation.observation_id,
        request_started_at=sent["T0"], response_received_at=completed["T1"], maps=maps, policy=config.policy,
        response_schema=config.schemas[config.endpoints[ROLE_ODDS].response_schema_id],
        derivation_version=config.derivation_version, requested_competitions=requested,
        identity_prefix=tuple(identity_prefix), expected_scope=expected_scope,
        expected_scope_hash=expected_scope_hash, fixture_join=fixture_join, complete_hint=True)
    return DerivationInputs(raw, ctx)


# --------------------------------------------------------------------------------------
# verify_derivation, RESPONSE kind
# --------------------------------------------------------------------------------------
def _pinned_prefix(stores, head: Any) -> tuple[dict[str, Any], ...]:
    if type(head) is not dict or set(head) != {"sequence", "record_hash"} or type(head["sequence"]) is not int:
        _fail("the pinned identity-registry head is malformed")
    try:
        prefix = stores.identity.prefix(head["sequence"])
    except identity_mod.IdentityRegistryInvalid:
        _fail("the pinned identity-registry head is beyond the registry")
    if identity_mod.head_of(prefix) != head:
        _fail("the pinned identity-registry head is not a prefix of the verified registry")
    return prefix


def verify_response_derivation(observation_id: str, *, stores, config, maps: AdapterMaps) -> None:
    """Re-derive one RESPONSE document from its pinned inputs and require byte equality (design 11.5)."""

    from genesis_adapters.oddspapi import emit

    observation = stores.evidence.get_observation(observation_id)
    if observation.contract_id != stores.contract_id:
        _fail("the observation is not under this derivation's contract")
    data = stores.evidence.get_bytes(observation.artifact_hash)
    document = json.loads(data)
    if type(document) is not dict or document.get("derivation_kind") != normalize.KIND_RESPONSE:
        _fail("not a RESPONSE document")
    if document.get("derivation_version") != stores.derivation_version \
            or config.derivation_version != stores.derivation_version:
        _fail("the running configuration does not reproduce this derivation version")
    rows = acquisition_rows(stores.acquisition, document["acquisition_id"])
    if rows.get("acq_planned", {}).get("provider_request_hash") != document["provider_request_hash"] \
            or rows.get("acq_completed", {}).get("raw_observation_id") != document["raw_observation_id"]:
        _fail("the document does not belong to its acquisition record")
    prefix = _pinned_prefix(stores, document.get("identity_registry_head"))
    scope_hash = document.get("expected_scope_hash")
    if scope_hash is None or rows.get("acq_sent", {}).get("expected_scope_hash") != scope_hash:
        _fail("the document's expected scope is not the one pinned before the send (design 12.4)")
    expected = scope_mod.load_scope(stores.root, scope_hash)
    join_id = document.get("fixture_join_observation_id")
    join = snapshot_from_observation(stores, config, maps, join_id) if join_id is not None else None
    if join_id is not None and (join is None or parse_utc(join.retrieved_at) > parse_utc(
            document["times"]["response_received_at"])):
        _fail("the pinned fixture join is unusable or later than the response")
    inputs = odds_inputs(stores, config, maps, document["acquisition_id"], identity_prefix=prefix,
                         expected_scope=expected, expected_scope_hash=scope_hash, fixture_join=join,
                         request_root=stores.root)
    if inputs.ctx.raw_artifact_hash != document["raw_artifact_hash"]:
        _fail("the raw artifact is not the pinned one")
    parsed = parser.parse_odds_response(inputs.raw, inputs.ctx)
    rebuilt = {item.entity_id: item for item in normalize.build_documents(parsed, inputs.ctx)}
    item = rebuilt.get(document.get("entity_id"))
    if item is None or item.data != data:
        _fail("the re-derived document differs from the stored bytes")
    wanted_uri = emit.response_source_uri(stores.derivation_version, item.entity_id, inputs.ctx.raw_observation_id)
    # every field the emitter sets that the source contract does not itself pin (hostile audit RA5-009: the upstream
    # version and the content type used to pass by omission)
    if (observation.source_uri, observation.retrieved_at, observation.first_seen_at, observation.valid_from,
            observation.valid_to, observation.publisher_timestamp, observation.parser_version,
            observation.upstream_version, observation.content_type) != (
            wanted_uri, iso_utc(inputs.ctx.response_received_at), iso_utc(inputs.ctx.response_received_at),
            iso_utc(inputs.ctx.response_received_at), item.valid_to, item.publisher_timestamp,
            stores.derivation_version, emit.UPSTREAM_VERSION, emit.NORMALIZED_CONTENT_TYPE):
        _fail("the observation metadata is not the derivation's")


def verify_derivation(observation_id: str, *, stores, config, maps: AdapterMaps) -> None:
    """Dispatch on ``derivation_kind``; an unknown kind or missing input is a failure, never a pass."""

    from genesis_adapters.oddspapi import invalidation

    observation = stores.evidence.get_observation(observation_id)
    document = json.loads(stores.evidence.get_bytes(observation.artifact_hash))
    kind = document.get("derivation_kind") if type(document) is dict else None
    if kind == normalize.KIND_RESPONSE:
        verify_response_derivation(observation_id, stores=stores, config=config, maps=maps)
    elif kind == invalidation.KIND_INVALIDATION:
        invalidation.verify_invalidation_derivation(observation_id, stores=stores)
    else:
        _fail(f"unknown derivation kind: {kind!r}")


def verify_all(stores, config, maps: AdapterMaps) -> int:
    """``verify_derivation`` for EVERY observation under the derivation's contract (G3 AC-1: 100%, both kinds).

    The evidence manifest (a public, hash-chained log) lists every observation ever published, so an
    observation without a PIT record (e.g. one orphaned by a crash) is verified too.
    """

    from genesis.registry import AppendOnlyJsonl

    count = 0
    for row in AppendOnlyJsonl(stores.evidence.manifest).records():
        if row.get("record_type") == "evidence_observation" and row.get("contract_id") == stores.contract_id:
            verify_derivation(row["observation_id"], stores=stores, config=config, maps=maps)
            count += 1
    return count
