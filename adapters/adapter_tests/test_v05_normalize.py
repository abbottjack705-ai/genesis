"""EV-03 (purity and determinism), EV-04 (document contract), EV-08 (partial payload), EV-06 (document side)."""

from __future__ import annotations

import ast
import hashlib
import json
import unittest
from pathlib import Path

from genesis.repro import canonical_json, sha256_bytes

from genesis_adapters import ids
from genesis_adapters.oddspapi import identity_registry as reg
from genesis_adapters.oddspapi import normalize, parser

from . import parser_support as ps
from .parser_support import (
    ACQUISITION, DERIVATION, FIXTURE_A, FIXTURE_B, FIXTURE_DIR, RAW_HASH, RAW_OBSERVATION, REQUEST_HASH, SCOPE_HASH,
    T0, T1, books_by, documents, fixture_of, iso_add, odds_payload, one_book, parse, price_of, scope_of,
)

OU = "SOCCER_TOTAL_GOALS_OU_FT"
FORBIDDEN_FIELDS = ("T2", "T3", "ready_at", "parse_ready_at", "recorded_at", "first_seen_at")


def keys_everywhere(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from keys_everywhere(value)
    elif isinstance(node, list):
        for value in node:
            yield from keys_everywhere(value)


class FixtureIntegrityTests(unittest.TestCase):
    def test_every_fixture_matches_its_pinned_sha256_and_none_is_unlisted(self):
        listed = {}
        for line in (FIXTURE_DIR / "FIXTURES.sha256").read_text(encoding="ascii").splitlines():
            digest, name = line.split(" *")
            listed[name] = digest
        present = {path.name for path in FIXTURE_DIR.iterdir() if path.name != "FIXTURES.sha256"}
        self.assertEqual(set(listed), present)
        for name, digest in listed.items():
            self.assertEqual(hashlib.sha256((FIXTURE_DIR / name).read_bytes()).hexdigest(), digest, name)

    def test_the_fixtures_are_ascii_json_with_lf_line_endings(self):
        for path in FIXTURE_DIR.iterdir():
            data = path.read_bytes()
            self.assertNotIn(b"\r", data, path.name)
            data.decode("ascii")


class PurityTests(unittest.TestCase):
    def test_ev03_the_same_inputs_give_byte_identical_documents(self):
        raw = ps.dump(odds_payload())
        first = normalize.market_book_documents(parser.parse_odds_response(raw, ps.make_ctx()), ps.make_ctx())
        second = normalize.market_book_documents(parser.parse_odds_response(raw, ps.make_ctx()), ps.make_ctx())
        self.assertEqual(first, second)
        self.assertEqual(len(first), 12)
        self.assertEqual(len({sha256_bytes(item) for item in first}), 12)

    def test_ev03_documents_are_independent_of_ambient_state(self):
        import decimal
        raw = ps.dump(odds_payload())
        baseline = normalize.market_book_documents(parser.parse_odds_response(raw, ps.make_ctx()), ps.make_ctx())
        with decimal.localcontext() as context:
            context.prec = 5
            context.rounding = decimal.ROUND_DOWN
            again = normalize.market_book_documents(parser.parse_odds_response(raw, ps.make_ctx()), ps.make_ctx())
        self.assertEqual(again, baseline)

    def test_ev03_the_parser_and_normalizer_read_no_clock_file_network_or_randomness(self):
        banned_modules = {"time", "random", "secrets", "socket", "ssl", "os", "subprocess", "pathlib", "shutil",
                          "urllib", "http", "requests", "tempfile", "uuid"}
        banned_calls = {"now", "utcnow", "today", "time", "monotonic", "open", "urandom"}
        for module in (parser, normalize):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({a.name.split(".")[0] for a in node.names} & banned_modules, module.__name__)
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module.split(".")[0], banned_modules, module.__name__)
                if isinstance(node, ast.Call):
                    func = node.func
                    label = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                    self.assertNotIn(label, banned_calls, module.__name__)

    def test_documents_carry_no_processing_times_and_no_floats(self):
        for item in documents(parse(odds_payload())):
            body = json.loads(item.data, parse_float=lambda text: self.fail("float literal in a document"))
            self.assertFalse(set(FORBIDDEN_FIELDS) & set(keys_everywhere(body)))

    def test_documents_are_canonical_bytes_and_ordered_by_entity(self):
        docs = documents(parse(odds_payload()))
        self.assertEqual([d.entity_id for d in docs], sorted(d.entity_id for d in docs))
        for item in docs:
            self.assertEqual(item.data, canonical_json(json.loads(item.data)))
            self.assertEqual(item.artifact_hash, hashlib.sha256(item.data).hexdigest())


class DocumentContractTests(unittest.TestCase):
    def open_document(self):
        parsed = parse(odds_payload())
        book = one_book(parsed)
        return book, ps.document_of(parsed, book.entity_id)

    def test_ev04_an_open_document_has_exactly_the_design_9_1_fields(self):
        book, document = self.open_document()
        self.assertEqual(set(document), {
            "schema", "derivation_kind", "derivation_version", "provider", "api_version", "raw_artifact_hash",
            "raw_observation_id", "provider_request_hash", "acquisition_id", "identity_registry_head",
            "expected_scope_hash", "fixture_join_observation_id", "sport", "competition_id", "event_id",
            "provider_fixture_id", "home_participant_id", "away_participant_id", "scheduled_start_as_known",
            "bookmaker_id", "provider_bookmaker_key", "market_id", "market_family", "line", "period", "entity_id",
            "market_state", "state_reasons", "selections", "provider_status", "provider_timestamps", "times",
            "valid_from", "valid_to", "side"})
        self.assertEqual((document["schema"], document["derivation_kind"], document["provider"],
                          document["api_version"], document["sport"], document["side"]),
                         ("genesis.adapters.oddspapi.market-book.v1", "RESPONSE", "oddspapi", "v4", "soccer", "BACK"))
        self.assertEqual((document["derivation_version"], document["raw_artifact_hash"],
                          document["raw_observation_id"], document["provider_request_hash"],
                          document["acquisition_id"]), (DERIVATION, RAW_HASH, RAW_OBSERVATION, REQUEST_HASH,
                                                        ACQUISITION))
        self.assertEqual(document["times"], {"request_started_at": T0, "response_received_at": T1})
        self.assertEqual((document["valid_from"], document["valid_to"]), (T1, iso_add(T1, seconds=3600)))
        self.assertEqual((document["market_state"], document["state_reasons"]), ("OPEN", []))
        self.assertEqual((document["competition_id"], document["market_family"], document["line"],
                          document["period"]), ("soccer.eng.premier-league", OU, "2.5", "FT_REGULAR"))
        self.assertEqual(document["provider_fixture_id"], {"native_type": "str", "value": FIXTURE_A})
        self.assertEqual(document["scheduled_start_as_known"], "2026-10-03T14:00:00.000000Z")
        self.assertEqual(document["bookmaker_id"], "bk.pinnacle")
        self.assertEqual(document["provider_status"], {"event": {"statusId": 0}, "market": {},
                                                       "outcomes": {"2001": True, "2002": True}})

    def test_ev04_identities_are_the_design_8_formulas(self):
        book, document = self.open_document()
        event = ids.gid("evt", provider="oddspapi", ns="v4.fixture", native_type="str", native=FIXTURE_A)
        market = ids.gid("mkt", event_id=event, family=OU, line="2.5", period="FT_REGULAR")
        self.assertEqual((document["event_id"], document["market_id"]), (event, market))
        self.assertEqual(document["entity_id"], ids.gid("book", market_id=market, bookmaker_id="bk.pinnacle"))
        self.assertEqual(document["home_participant_id"], ids.gid(
            "part", provider="oddspapi", ns="v4.participant", native_type="int", native="35"))
        for selection in ("OVER", "UNDER"):
            body = document["selections"][selection]
            self.assertEqual(body["selection_id"], ids.gid("sel", market_id=market, selection=selection))
            self.assertEqual(body["provider_outcome_id"], {"native_type": "int", "value": {"OVER": "2001",
                                                                                            "UNDER": "2002"}[selection]})
        self.assertEqual({k: v["odds_decimal"] for k, v in document["selections"].items()},
                         {"OVER": "1.91", "UNDER": "1.95"})

    def test_ev04_pinned_inputs_are_embedded_verbatim(self):
        parsed = parse(odds_payload())
        prefix_registry_head = {"sequence": 0, "record_hash": "0" * 64}
        document = ps.document_of(parsed, one_book(parsed).entity_id, expected_scope_hash=SCOPE_HASH)
        self.assertEqual(document["expected_scope_hash"], SCOPE_HASH)
        self.assertEqual(document["identity_registry_head"], prefix_registry_head)
        self.assertIsNone(document["fixture_join_observation_id"])
        self.assertEqual(ps.document_of(parsed, one_book(parsed).entity_id)["expected_scope_hash"], None)

    def test_the_derivation_version_is_the_normalized_contract_parser_version(self):
        self.assertTrue(DERIVATION.startswith("mb1-") and len(DERIVATION) == len("mb1-") + 16)
        self.assertEqual(ps.CONFIG_BODY.code_version, normalize.CODE_VERSION)
        changed = ps.policy_with(price_ttl_seconds=ps.POLICY.price_ttl_seconds + 1)
        self.assertNotEqual(ps.cfg.derivation_version(normalize.CODE_VERSION, ps.CONFIG_BODY.digests, changed),
                            DERIVATION)

    def test_ev06_only_an_open_document_can_supply_a_price(self):
        payload = odds_payload()
        price_of(payload, "pinnacle", "1010", "2002")["active"] = False
        fixture_of(payload)["bookmakerOdds"]["fixture-book-a"]["bookmakerIsActive"] = False
        fixture_of(payload)["bookmakerOdds"]["fixture-book-b"]["markets"]["101"]["outcomes"].pop("102")
        parsed = parse(payload, expected_scope=scope_of(parse(odds_payload())))
        seen_states = set()
        for item in documents(parsed):
            body = json.loads(item.data)
            seen_states.add(body["market_state"])
            if body["market_state"] == "OPEN":
                self.assertIsNotNone(body["valid_to"])
            else:
                self.assertNotIn("selections", body)
                self.assertIsNone(body["valid_to"])
        self.assertEqual(seen_states, {"OPEN", "SUSPENDED", "BLOCKED"})

    def test_a_valid_to_never_exceeds_the_prematch_guard(self):
        payload = odds_payload()
        fixture_of(payload)["startTime"] = iso_add(T1, seconds=ps.POLICY.prematch_guard_seconds + 60)
        parsed = parse(payload)
        book = one_book(parsed)
        document = ps.document_of(parsed, book.entity_id)
        self.assertEqual(document["valid_to"], iso_add(T1, seconds=60))
        self.assertLess(document["valid_to"], iso_add(T1, seconds=ps.POLICY.price_ttl_seconds))


class TombstoneTests(unittest.TestCase):
    def test_a_complete_response_tombstones_an_expected_book_it_no_longer_carries(self):
        base = parse(odds_payload())
        scope = scope_of(base)
        payload = odds_payload()
        gone = one_book(base, bookmaker="fixture-book-a", family="SOCCER_1X2_FT")
        del fixture_of(payload)["bookmakerOdds"]["fixture-book-a"]["markets"]["101"]
        parsed = parse(payload, expected_scope=scope)
        self.assertEqual([t.entity_id for t in parsed.tombstones], [gone.entity_id])
        docs = {d.entity_id: json.loads(d.data) for d in documents(parsed, expected_scope_hash=SCOPE_HASH)}
        absent = docs[gone.entity_id]
        self.assertEqual((absent["market_state"], absent["state_reasons"], absent["valid_to"], absent["valid_from"]),
                         ("ABSENT", ["BOOK_ABSENT"], None, T1))
        self.assertNotIn("selections", absent)
        self.assertEqual(absent["expected_scope_hash"], SCOPE_HASH)
        self.assertEqual({key: absent[key] for key in ("event_id", "market_id", "bookmaker_id", "entity_id", "line")},
                         {"event_id": gone.event.event_id, "market_id": gone.market_id,
                          "bookmaker_id": gone.bookmaker_id, "entity_id": gone.entity_id, "line": None})

    def test_ev08_a_partial_payload_emits_present_books_and_no_absent_documents(self):
        base = parse(odds_payload())
        payload = odds_payload()
        del fixture_of(payload, FIXTURE_B)["bookmakerOdds"]["pinnacle"]["markets"]["1010"]
        parsed = parse(payload, expected_scope=scope_of(base), complete_hint=False)
        docs = [json.loads(d.data) for d in documents(parsed)]
        self.assertEqual(len(docs), 11)
        self.assertEqual({d["market_state"] for d in docs}, {"OPEN"})
        self.assertNotIn("ABSENT", {d["market_state"] for d in docs})

    def test_a_response_that_failed_as_a_whole_yields_no_documents(self):
        parsed = parse(b'{"not": "a list"}', expected_scope=scope_of(parse(odds_payload())))
        self.assertEqual(documents(parsed), ())
        self.assertEqual(normalize.market_book_documents(parsed, ps.make_ctx()), ())


if __name__ == "__main__":
    unittest.main()
