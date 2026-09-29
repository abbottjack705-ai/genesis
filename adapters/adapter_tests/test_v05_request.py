"""REQ-01, REQ-02, REQ-03, REQ-08 (hash part) and endpoint-spec validation."""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import hashlib
import json
import unittest
from fnmatch import fnmatchcase

from genesis_adapters.config import load_policy
from genesis_adapters.oddspapi import endpoints as ep

from .support import CONFIG

POLICY = load_policy(CONFIG / "oddspapi_slice1_policy.json")
SPECS = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", POLICY)
ODDS = SPECS["ODDS"]
ALIASES = ("apiKey", "APIKEY", "apikey", "ApiKey", "api_key", "API_KEY", "key", "KEY", "token",
           "Token", "access_token", "ACCESS_TOKEN", "secret", "Secret")


def odds_request(**over):
    params = {"bookmaker": ["pinnacle", "fixture-book-b", "fixture-book-a"],
              "tournamentIds": [17, 8], "oddsFormat": "decimal"}
    params.update(over)
    return ep.build_request(ODDS, **params)


def sha(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()


EXPECTED_JSON = {
    "api_version": "v4", "body": None, "domain": "genesis.adapters.oddspapi.request.v1",
    "headers": [["accept", "application/json"], ["accept-encoding", "identity"]],
    "host": "api.oddspapi.io", "method": "GET", "path": "/v4/odds-by-tournaments",
    "provider_id": "oddspapi",
    "query": [["bookmaker", "fixture-book-a,fixture-book-b,pinnacle"], ["oddsFormat", "decimal"],
              ["tournamentIds", "8,17"]],
    "role": "ODDS", "scheme": "https",
}


class RequestIdentityTests(unittest.TestCase):
    def test_req01_credential_params_and_aliases_are_rejected_not_dropped(self):
        for role, spec in SPECS.items():
            required = {p.name: _sample(p) for p in spec.params if p.required}
            for alias in ALIASES:
                with self.assertRaises(ep.RequestError, msg=f"{role}/{alias}") as caught:
                    ep.build_request(spec, **required, **{alias: "anything"})
                self.assertEqual(caught.exception.code, "CREDENTIAL_PARAM")
        # the spec's own credential parameter name, whatever its case
        self.assertEqual(ODDS.credential_param, "apiKey")
        for role, spec in SPECS.items():
            with self.assertRaises(ep.RequestError) as caught:
                ep.build_request(spec, **{"aPiKeY": "x"})
            self.assertEqual(caught.exception.code, "CREDENTIAL_PARAM")

    def test_req01_unknown_and_missing_params(self):
        with self.assertRaises(ep.RequestError) as caught:
            odds_request(unexpected="1")
        self.assertEqual(caught.exception.code, "UNKNOWN_PARAM")
        for name in ("bookmaker", "tournamentIds", "oddsFormat"):
            params = {"bookmaker": ["pinnacle"], "tournamentIds": [17], "oddsFormat": "decimal"}
            del params[name]
            with self.assertRaises(ep.RequestError) as caught:
                ep.build_request(ODDS, **params)
            self.assertEqual(caught.exception.code, "MISSING_PARAM")

    def test_req02_canonical_request_matches_the_section_7_3_shape(self):
        request = odds_request()
        self.assertEqual(request.to_json(), EXPECTED_JSON)
        expected_bytes = (json.dumps(EXPECTED_JSON, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False) + "\n").encode()
        self.assertEqual(request.canonical_bytes(), expected_bytes)
        self.assertEqual(request.provider_request_hash, sha(expected_bytes))
        self.assertEqual(request.role, "ODDS")

    def test_req02_pinned_golden_hash(self):
        from . import golden
        self.assertEqual(odds_request().provider_request_hash, golden.ODDS_REQUEST_HASH)
        meta = ep.build_request(SPECS["META_TOURNAMENTS"], sportId=10)
        self.assertEqual(meta.provider_request_hash, golden.TOURNAMENTS_REQUEST_HASH)

    def test_req02_parameter_and_set_order_never_change_the_hash(self):
        base = odds_request()
        variants = [
            odds_request(bookmaker=["fixture-book-a", "pinnacle", "fixture-book-b"]),
            odds_request(bookmaker=("fixture-book-b", "fixture-book-a", "pinnacle", "pinnacle")),
            odds_request(tournamentIds=[8, 17, 8]),
            odds_request(tournamentIds={17, 8}),
        ]
        for variant in variants:
            self.assertEqual(variant.provider_request_hash, base.provider_request_hash)
        reordered = ep.build_request(ODDS, oddsFormat="decimal", tournamentIds=[8, 17],
                                     bookmaker=["pinnacle", "fixture-book-a", "fixture-book-b"])
        self.assertEqual(reordered.provider_request_hash, base.provider_request_hash)

    def test_req03_any_identity_change_changes_the_hash(self):
        base = odds_request().provider_request_hash
        hashes = {
            "bookmaker subset": odds_request(bookmaker=["pinnacle"]).provider_request_hash,
            "extra bookmaker": odds_request(bookmaker=["pinnacle", "fixture-book-a", "fixture-book-b",
                                                        "fixture-book-c"]).provider_request_hash,
            "tournament": odds_request(tournamentIds=[17]).provider_request_hash,
            "other tournament": odds_request(tournamentIds=[8, 18]).provider_request_hash,
            "path": ep.build_request(dataclasses.replace(ODDS, path="/v4/odds-by-tournament"),
                                     bookmaker=["pinnacle"], tournamentIds=[17, 8],
                                     oddsFormat="decimal").provider_request_hash,
            "host": ep.build_request(dataclasses.replace(ODDS, host="api2.oddspapi.io"),
                                     bookmaker=["pinnacle"], tournamentIds=[17, 8],
                                     oddsFormat="decimal").provider_request_hash,
        }
        hashes["api version"] = ep.build_request(
            dataclasses.replace(ODDS, api_version="v5"), bookmaker=["pinnacle"],
            tournamentIds=[17, 8], oddsFormat="decimal").provider_request_hash
        for label, value in hashes.items():
            self.assertNotEqual(value, base, label)
        distinct = {v for k, v in hashes.items() if k not in {"bookmaker subset"}}
        self.assertEqual(len(distinct), len(hashes) - 1)

    def test_req08_hash_part_source_uri_and_content_addressing(self):
        request = odds_request()
        uri = request.source_uri
        self.assertEqual(uri, f"oddspapi-request:sha256:{request.provider_request_hash}")
        self.assertTrue(fnmatchcase(uri, ep.RAW_URI_PATTERN))
        self.assertEqual(ep.RAW_URI_PATTERN, "oddspapi-request:sha256:*")
        self.assertEqual(sha(request.canonical_bytes()), request.provider_request_hash)
        self.assertNotIn(b"apikey", request.canonical_bytes().lower())
        self.assertNotIn(b"?", request.canonical_bytes())

    def test_canonical_request_holds_no_field_that_could_carry_a_credential(self):
        names = {f.name for f in dataclasses.fields(ep.CanonicalRequest)}
        self.assertFalse({n for n in names if "key" in n.lower() or "secret" in n.lower()
                          or "token" in n.lower()})
        body = odds_request().to_json()
        self.assertEqual(set(body), {"domain", "provider_id", "api_version", "role", "method", "scheme",
                                     "host", "path", "query", "headers", "body"})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            odds_request().host = "evil"          # type: ignore[misc]


def _sample(param):
    if param.type == "int":
        return 10
    if param.type == "date":
        return "2026-10-03"
    if param.type == "csv_set":
        return [17] if param.element_type == "int" else ["pinnacle"]
    return (param.allowed_values or ["x"])[0]


class RenderingTests(unittest.TestCase):
    def build(self, spec, **params):
        return ep.build_request(spec, **params)

    def test_int_rendering(self):
        tournaments = SPECS["META_TOURNAMENTS"]
        self.assertEqual(dict(self.build(tournaments, sportId=10).query), {"sportId": "10"})
        self.assertEqual(dict(self.build(tournaments, sportId=0).query), {"sportId": "0"})
        for bad in (-1, True, 1.0, "10", None, 10 ** 70):
            with self.assertRaises(ep.RequestError, msg=repr(bad)):
                self.build(tournaments, sportId=bad)

    def test_date_rendering(self):
        fixtures = SPECS["FIXTURES"]
        base = dict(sportId=10, tournamentIds=[17])
        good = self.build(fixtures, **base, **{"from": dt.date(2026, 10, 3), "to": "2026-10-04"})
        self.assertEqual(dict(good.query)["from"], "2026-10-03")
        self.assertEqual(dict(good.query)["to"], "2026-10-04")
        for bad in ("2026-13-01", "2026-1-1", "20261003", "2026-10-03T00:00:00Z", 20261003,
                    dt.datetime(2026, 10, 3, 12, 0)):
            with self.assertRaises(ep.RequestError, msg=repr(bad)):
                self.build(fixtures, **base, **{"from": bad, "to": "2026-10-04"})

    def test_csv_set_rules(self):
        fixtures = SPECS["FIXTURES"]
        request = self.build(fixtures, sportId=10, tournamentIds=[17, 8, 17, 100, 9],
                             **{"from": "2026-10-03", "to": "2026-10-04"})
        self.assertEqual(dict(request.query)["tournamentIds"], "8,9,17,100")      # numeric order
        for bad in ([], "17", 17, [17, "8"], [-1], [True], [1.5]):
            with self.assertRaises(ep.RequestError, msg=repr(bad)):
                self.build(fixtures, sportId=10, tournamentIds=bad,
                           **{"from": "2026-10-03", "to": "2026-10-04"})
        odds = self.build(ODDS, bookmaker=["b", "a", "B"], tournamentIds=[1], oddsFormat="decimal")
        self.assertEqual(dict(odds.query)["bookmaker"], "B,a,b")                   # lexicographic

    def test_str_grammar_allowed_values_and_scalar_misuse(self):
        with self.assertRaises(ep.RequestError):
            self.build(ODDS, bookmaker=["ok"], tournamentIds=[1], oddsFormat="american")
        for bad in ("has space", "x" * 65, "", "é", "a/b", "a=b", "a,b"):
            with self.assertRaises(ep.RequestError, msg=repr(bad)):
                self.build(ODDS, bookmaker=[bad], tournamentIds=[1], oddsFormat="decimal")
        with self.assertRaises(ep.RequestError):                                   # list for a scalar param
            self.build(SPECS["META_TOURNAMENTS"], sportId=[10])

    def test_headers_are_the_fixed_lowercase_allowlist(self):
        self.assertEqual(odds_request().headers,
                         (("accept", "application/json"), ("accept-encoding", "identity")))


class EndpointSpecValidationTests(unittest.TestCase):
    def body(self):
        return copy.deepcopy(json.loads((CONFIG / "oddspapi_v4_endpoints.json").read_text()))

    def load(self, body):
        return ep.parse_endpoints(body, POLICY)

    def test_shipped_specs_are_valid_usable_and_unverified(self):
        self.assertEqual(set(SPECS), {"META_SPORTS", "META_TOURNAMENTS", "META_BOOKMAKERS", "META_MARKETS",
                                      "FIXTURES", "ODDS"})
        for role, spec in SPECS.items():
            self.assertFalse(spec.verified_live, role)
            self.assertTrue(spec.usable, role)
            self.assertEqual(spec.cacheable, role != "ODDS")
            self.assertEqual(spec.provider_metering, ep.Metering.PER_REQUEST)
            self.assertGreaterEqual(spec.genesis_debit_units, 1)
        self.assertIsNone(ODDS.cache_ttl_seconds)
        self.assertEqual(SPECS["FIXTURES"].cache_ttl_seconds, POLICY.cache_ttl_seconds["FIXTURES"])

    def test_odds_can_never_be_cacheable(self):
        body = self.body()
        for entry in body["endpoints"]:
            if entry["role"] == "ODDS":
                entry["cacheable"] = True
                entry["cache_ttl_source"] = "policy"
        with self.assertRaises(ep.SpecError):
            self.load(body)

    def test_metering_rules(self):
        cases = [
            ("PER_REQUEST", 1, True, 1, True),
            ("PER_REQUEST", 2, True, 2, False),      # PER_REQUEST weight is exactly 1
            ("PER_REQUEST", 1, True, 0, False),      # debit must be >= 1
            ("FIXED_WEIGHT", 2, True, 2, True),
            ("FIXED_WEIGHT", 2, True, 1, False),     # debit < weight refused (BILL-02)
            ("FIXED_WEIGHT", 0, True, 1, False),
            ("NON_METERED", 0, False, 1, True),
            ("NON_METERED", 0, False, 0, False),     # a debited row cannot be zero
            ("NON_METERED", 1, False, 1, False),
            ("VARIABLE", None, None, 1, True),       # loads, but is not usable
            ("UNKNOWN", None, None, 1, True),
            ("VARIABLE", 1, None, 1, False),
        ]
        for metering, weight, billable, debit, ok in cases:
            body = self.body()
            entry = body["endpoints"][1]
            entry.update(provider_metering=metering, provider_request_weight=weight,
                         provider_documented_billable=billable, genesis_debit_units=debit)
            if ok:
                specs = self.load(body)
                spec = specs["META_TOURNAMENTS"]
                self.assertEqual(spec.usable, metering not in {"VARIABLE", "UNKNOWN"},
                                 (metering, weight))
                if not spec.usable:
                    with self.assertRaises(ep.RoleNotUsable):
                        spec.require_usable()
                else:
                    spec.require_usable()
            else:
                with self.assertRaises(ep.SpecError, msg=(metering, weight, debit)):
                    self.load(body)

    def test_structural_validation(self):
        for mutate, label in (
            (lambda b: b["endpoints"].append(copy.deepcopy(b["endpoints"][0])), "duplicate role"),
            (lambda b: b["endpoints"][0].update(method="POST"), "method"),
            (lambda b: b["endpoints"][0].update(scheme="http"), "scheme"),
            (lambda b: b["endpoints"][0].update(host="API.ODDSPAPI.IO"), "host case"),
            (lambda b: b["endpoints"][0].update(path="/v4/sports/"), "trailing slash"),
            (lambda b: b["endpoints"][0].update(role="NOPE"), "role"),
            (lambda b: b["endpoints"][0].update(surprise=1), "extra key"),
            (lambda b: b["endpoints"][1]["params"].append(
                {"name": "apiKey", "type": "str", "required": False, "set_valued": False,
                 "allowed_values": None, "element_type": None}), "credential in params"),
            (lambda b: b["endpoints"][1]["params"].append(
                {"name": "x", "type": "float", "required": False, "set_valued": False,
                 "allowed_values": None, "element_type": None}), "param type"),
            (lambda b: b["endpoints"][0].update(cacheable=False, cache_ttl_source="policy"), "ttl when uncached"),
            (lambda b: b["endpoints"][0].update(cache_ttl_source=None), "cacheable without ttl"),
        ):
            body = self.body()
            mutate(body)
            with self.assertRaises(ep.SpecError, msg=label):
                self.load(body)

    def test_cacheable_roles_need_a_policy_ttl(self):
        policy_body = json.loads((CONFIG / "oddspapi_slice1_policy.json").read_text())
        del policy_body["cache_ttl_seconds"]["META_MARKETS"]
        from genesis_adapters import config as cfg
        with self.assertRaises((cfg.PolicyError, ep.SpecError)):
            ep.parse_endpoints(self.body(), cfg.parse_policy(policy_body))


if __name__ == "__main__":
    unittest.main()
