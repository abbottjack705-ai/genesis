"""Area 8 (D8, D17, deviations 6/7): schema and status fail-closed, probed on the PURE parser.

Every probe mutates one thing in a copy of the committed ODDS fixture, parses it with an auditor-built
``ParseContext`` and asserts the design outcome for the affected book(s) - and that no other book changed.
A book "priced" means its normalized state is OPEN (only OPEN documents carry ``selections``).

    python -B attacks/a08_schema_status.py --repo <candidate>
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

FIX_A = "id1000001761301153"
T1 = "2026-10-01T12:00:00.100000Z"


def context(repo: Path, raw: bytes, *, fixture_join=None):
    from genesis_adapters import config as cfg
    from genesis_adapters.oddspapi import normalize, parser
    from genesis_adapters.oddspapi.maps import maps_from_config

    config = cfg.load_adapter_config(repo / "adapters" / "config", allow_fixture_only=True,
                                     code_version=normalize.CODE_VERSION)
    spec = config.endpoints["ODDS"]
    return parser.ParseContext(
        acquisition_id="d" * 64, provider_request_hash="c" * 64, raw_artifact_hash=hashlib.sha256(raw).hexdigest(),
        raw_observation_id="b" * 64, request_started_at="2026-10-01T12:00:00.000000Z", response_received_at=T1,
        maps=maps_from_config(config), policy=config.policy, response_schema=config.schemas[spec.response_schema_id],
        derivation_version=config.derivation_version, fixture_join=fixture_join)


def parse(repo: Path, payload, **kw):
    from genesis_adapters.oddspapi import parser

    raw = json.dumps(payload, sort_keys=True).encode() if not isinstance(payload, bytes) else payload
    return parser.parse_odds_response(raw, context(repo, raw, **kw))


def books(parsed, fixture=FIX_A, bookmaker=None):
    out = {}
    for b in parsed.books:
        doc_fixture = b.event.provider_fixture_id["value"]
        if fixture and doc_fixture != fixture:
            continue
        if bookmaker and b.provider_bookmaker_key != bookmaker:
            continue
        out[(doc_fixture, b.provider_bookmaker_key, b.market_family)] = (b.state, tuple(b.reasons))
    return out


def fixture_of(payload, fixture=FIX_A):
    return next(item for item in payload if item["fixtureId"] == fixture)


def outcomes(item, bookmaker, market):
    return item["bookmakerOdds"][bookmaker]["markets"][market]["outcomes"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    base_payload = json.loads(c.fixture_bytes(repo, "odds_by_tournaments.json"))
    base = parse(repo, base_payload)
    base_books = books(base, fixture=None)
    c.check("A8", "baseline: every declared book of the fixture is OPEN", base_books
            and all(state == "OPEN" for state, _ in base_books.values()), books=len(base_books))
    first_bk = sorted({k[1] for k in books(base)})[0]

    def probe(label, mutate, expect_state, expect_reason=None, scope="book", **kw):
        payload = copy.deepcopy(base_payload)
        target = mutate(payload)
        parsed = parse(repo, payload, **kw)
        if parsed.failure is not None:
            got = {"RESPONSE": (str(parsed.failure), ())}
            ok = expect_state == "REJECTED" and (expect_reason is None or expect_reason in str(parsed.failure))
            c.check("A8", label, ok, got=str(parsed.failure))
            return
        now = books(parsed, fixture=None)
        affected = {k: v for k, v in now.items() if v != base_books.get(k)}
        states = {v[0] for v in affected.values()}
        reasons = {r for v in affected.values() for r in v[1]}
        ok = bool(affected) and states == {expect_state} and (expect_reason is None or expect_reason in reasons)
        if scope == "book":
            ok = ok and len(affected) == 1
        c.check("A8", label, ok and "OPEN" not in states, affected=len(affected), states=sorted(states),
                reasons=sorted(reasons), target=target)

    # status allowlists (10 rule 1-5, ST-*)
    probe("unknown event statusId (7) -> every book of the event BLOCKED, no price",
          lambda p: fixture_of(p).__setitem__("statusId", 7), "BLOCKED", scope="event")
    probe("statusId typed as string \"0\" -> unknown (1 != \"1\"), BLOCKED",
          lambda p: fixture_of(p).__setitem__("statusId", "0"), "BLOCKED", scope="event")
    probe("event finished (statusId 2) with active prices -> BLOCKED (EVENT_NOT_PREMATCH or CONTRADICTORY)",
          lambda p: fixture_of(p).__setitem__("statusId", 2), "BLOCKED", scope="event")

    def outcome_active(value):
        def m(p):
            outs = outcomes(fixture_of(p), first_bk, "101")
            first = sorted(outs)[0]
            outs[first]["players"]["0"]["active"] = value
            return (first_bk, "101", first, value)
        return m
    probe("outcome active=false -> SUSPENDED (no price)", outcome_active(False), "SUSPENDED")
    probe("outcome active=\"true\" (wrong JSON type) -> not ACTIVE, never priced", outcome_active("true"), "BLOCKED")
    probe("outcome active=null -> never priced", outcome_active(None), "BLOCKED")

    def price(value):
        def m(p):
            outs = outcomes(fixture_of(p), first_bk, "101")
            first = sorted(outs)[0]
            outs[first]["players"]["0"]["price"] = value
            return (first_bk, "101", first, value)
        return m
    probe("deviation 7: ACTIVE outcome with null price -> BLOCKED CONTRADICTORY_STATUS", price(None), "BLOCKED",
          "CONTRADICTORY_STATUS")
    probe("ACTIVE outcome with price 1.0 -> BLOCKED CONTRADICTORY_STATUS", price(1.0), "BLOCKED", "CONTRADICTORY_STATUS")
    probe("ACTIVE outcome with price \"2.05\" (string) -> never priced", price("2.05"), "BLOCKED")

    def bookmaker_active(value, drop=False):
        def m(p):
            block = fixture_of(p)["bookmakerOdds"][first_bk]
            if drop:
                block.pop("bookmakerIsActive")
            else:
                block["bookmakerIsActive"] = value
            return (first_bk, value, drop)
        return m
    probe("deviation 6: bookmakerIsActive=false -> that bookmaker's books SUSPENDED (no price)",
          bookmaker_active(False), "SUSPENDED", scope="bookmaker")
    probe("deviation 6: bookmakerIsActive=1 (wrong type) -> BLOCKED, no price", bookmaker_active(1), "BLOCKED",
          scope="bookmaker")
    probe("deviation 6: bookmakerIsActive missing -> never priced", bookmaker_active(None, drop=True), "BLOCKED",
          scope="bookmaker")

    # closed-schema drift (10.1, SCH-01..03)
    def add_key(where):
        def m(p):
            item = fixture_of(p)
            if where == "outcome":
                outs = outcomes(item, first_bk, "101")
                outs[sorted(outs)[0]]["players"]["0"]["newField"] = 1
            elif where == "market":
                item["bookmakerOdds"][first_bk]["markets"]["101"]["newField"] = 1
            elif where == "bookmaker":
                item["bookmakerOdds"][first_bk]["newField"] = 1
            elif where == "event":
                item["newField"] = 1
            return where
        return m
    probe("unknown key in an outcome/price object -> that book BLOCKED SCHEMA_DRIFT", add_key("outcome"), "BLOCKED",
          "SCHEMA_DRIFT")
    probe("unknown key in a market object -> that book BLOCKED SCHEMA_DRIFT", add_key("market"), "BLOCKED",
          "SCHEMA_DRIFT")
    probe("unknown key in a bookmaker block -> event x bookmaker BLOCKED SCHEMA_DRIFT", add_key("bookmaker"),
          "BLOCKED", "SCHEMA_DRIFT", scope="bookmaker")
    probe("unknown key in the event object -> every book of the event BLOCKED SCHEMA_DRIFT", add_key("event"),
          "BLOCKED", "SCHEMA_DRIFT", scope="event")
    parsed = parse(repo, {"unexpected": base_payload})
    c.check("A8", "envelope drift -> response REJECTED, zero books, zero tombstones",
            parsed.failure is not None and not parsed.books and not parsed.tombstones, failure=str(parsed.failure))

    # deviation 7: optional startTime (8.3) - absent -> fixture join or BLOCKED, never OPEN without S
    def drop_start(p):
        fixture_of(p).pop("startTime")
        return "startTime"
    probe("deviation 7: startTime absent and no fixture join -> BLOCKED EVENT_METADATA_STALE, never OPEN",
          drop_start, "BLOCKED", "EVENT_METADATA_STALE", scope="event")

    def offset_start(p):
        fixture_of(p)["startTime"] = "2026-10-03T15:00:00.000+01:00"
        return "offset"
    probe("startTime with a +01:00 offset -> rejected, not normalized (6.4)", offset_start, "BLOCKED", scope="event")

    def naive_changed(p):
        outs = outcomes(fixture_of(p), first_bk, "101")
        outs[sorted(outs)[0]]["players"]["0"]["changedAt"] = "2026-10-01T11:58:30"
        return "naive changedAt"
    probe("naive provider timestamp -> BLOCKED TIMESTAMP_NAIVE", naive_changed, "BLOCKED", "TIMESTAMP_NAIVE")
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
