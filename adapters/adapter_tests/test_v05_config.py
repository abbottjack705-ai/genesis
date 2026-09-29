"""SlicePolicy loading, digests, derivation_version (FR-08 digest part, SCH-04, ID-09 loader)."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import unittest

from genesis_adapters import config as cfg

from .support import CONFIG, scratch_root

POLICY_FILE = CONFIG / "oddspapi_slice1_policy.json"


def canon(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def sha(value) -> str:
    return hashlib.sha256(canon(value)).hexdigest()


def policy_dict():
    return json.loads(POLICY_FILE.read_text(encoding="utf-8"))


def scalar_paths(value, prefix=()):
    """Every leaf of the policy as a path tuple."""

    if isinstance(value, dict):
        for key in sorted(value):
            yield from scalar_paths(value[key], prefix + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from scalar_paths(item, prefix + (index,))
    else:
        yield prefix


def get(value, path):
    for step in path:
        value = value[step]
    return value


def mutate(value, path):
    value = copy.deepcopy(value)
    holder = get(value, path[:-1]) if len(path) > 1 else value
    old = holder[path[-1]]
    if isinstance(old, bool):
        raise AssertionError("no bool leaves expected")
    if isinstance(old, int):
        holder[path[-1]] = old + 1
    elif isinstance(old, str):
        if path[0] in {"odds_min", "odds_max"} or path[0].startswith("overround"):
            holder[path[-1]] = str(float(old) + 0.5)
        elif path[0] == "schedule_inventory_utc":
            holder[path[-1]] = "09:00"
        elif path[0] == "schedule_fixtures_days_utc":
            holder[path[-1]] = old.replace("06:00", "07:00")
        elif path[0] == "classification":
            raise AssertionError("classification is fixed")
        else:
            holder[path[-1]] = old + "-x"
    return value


class PolicyTests(unittest.TestCase):
    def test_policy_loads_and_digest_is_sha256_of_canonical_json_of_the_file(self):
        policy = cfg.load_policy(POLICY_FILE)
        self.assertEqual(policy.digest, sha(policy_dict()))
        self.assertEqual(policy.classification, "PROVISIONAL_SLICE1_POLICY")
        self.assertEqual(policy.request_timeout_seconds, 60)
        self.assertEqual(policy.cache_ttl_seconds["FIXTURES"], 86400)
        self.assertEqual(policy.budget_pools["scheduled_odds"], 135)

    def test_policy_has_no_code_defaults_for_any_field(self):
        import dataclasses
        for field in dataclasses.fields(cfg.SlicePolicy):
            self.assertIs(field.default, dataclasses.MISSING, field.name)
            self.assertIs(field.default_factory, dataclasses.MISSING, field.name)

    def test_every_policy_file_key_is_a_policy_field_and_vice_versa(self):
        import dataclasses
        fields = {f.name for f in dataclasses.fields(cfg.SlicePolicy)}
        self.assertEqual(fields, set(policy_dict()))

    def test_missing_or_unknown_fields_and_bad_classification_are_refused(self):
        for key in list(policy_dict()):
            body = policy_dict()
            del body[key]
            with self.assertRaises(cfg.PolicyError, msg=key):
                cfg.parse_policy(body)
        body = policy_dict()
        body["surprise"] = 1
        with self.assertRaises(cfg.PolicyError):
            cfg.parse_policy(body)
        for value in ("", "FINAL", None):
            body = policy_dict()
            body["classification"] = value
            with self.assertRaises(cfg.PolicyError):
                cfg.parse_policy(body)

    def test_type_and_range_checks(self):
        bad = {
            "price_ttl_seconds": [0, -1, True, "3600", 1.5],
            "request_timeout_seconds": [0, -5, None, "60"],
            "clock_skew_max_seconds": [0, -1],
            "odds_min": ["abc", 1.01, "0", "1"],
            "odds_max_fraction_digits": [-1, "4", True],
            "overround_1x2": [["1.30", "1.00"], ["1.00"], "1.00,1.30", ["1.00", 1.3]],
            "cache_ttl_seconds": [{}, {"FIXTURES": 0}, {"ODDS": 5}],
            "budget_pools": [{}, {"metadata": -1, "fixtures": 1, "scheduled_odds": 1, "conditional": 1}],
            "schedule_inventory_utc": ["8:00", "25:00", "08:60"],
            "schedule_fixtures_days_utc": [[], ["FUNDAY 06:00"], ["MON 6:00"]],
            "secret_fragment_min_chars_divisor": [0, -1],
            "declared_bookmakers_max": [0, -1],
        }
        for key, values in bad.items():
            for value in values:
                body = policy_dict()
                body[key] = value
                with self.assertRaises(cfg.PolicyError, msg=f"{key}={value!r}"):
                    cfg.parse_policy(body)

    def test_bnd05_loader_rejects_nonpositive_timeout_missing_field_and_wide_guard_zone(self):
        body = policy_dict()
        body["request_timeout_seconds"] = 0
        with self.assertRaises(cfg.PolicyError):
            cfg.parse_policy(body)
        body = policy_dict()
        del body["request_timeout_seconds"]
        with self.assertRaises(cfg.PolicyError):
            cfg.parse_policy(body)
        # guard zone = request_timeout + 2 * clock_skew must stay below one hour
        body = policy_dict()
        body["request_timeout_seconds"] = 3600 - 2 * body["clock_skew_max_seconds"] - 1
        cfg.parse_policy(body)
        body["request_timeout_seconds"] += 1
        with self.assertRaises(cfg.PolicyError):
            cfg.parse_policy(body)

    def test_floats_are_never_accepted_from_the_file(self):
        with scratch_root() as root:
            path = root / "policy.json"
            text = POLICY_FILE.read_text().replace('"price_ttl_seconds": 3600', '"price_ttl_seconds": 3600.0')
            path.write_text(text)
            with self.assertRaises(cfg.PolicyError):
                cfg.load_policy(path)

    def test_fr08_changing_any_single_parameter_changes_every_downstream_identity(self):
        base_body = policy_dict()
        base = cfg.parse_policy(base_body)
        digests = cfg.load_config_digests(CONFIG)
        base_version = cfg.derivation_version("code-1", digests, base)
        seen_versions = {base_version}
        paths = [p for p in scalar_paths(base_body) if p != ("classification",)]
        self.assertGreater(len(paths), 40)
        for path in paths:
            body = mutate(base_body, path)
            try:
                changed = cfg.parse_policy(body)
            except cfg.PolicyError:
                continue   # a mutation that violates a validity rule is refused, which is also fine
            self.assertNotEqual(changed.digest, base.digest, path)
            version = cfg.derivation_version("code-1", digests, changed)
            self.assertNotEqual(version, base_version, path)
            self.assertNotEqual(cfg.normalized_contract_id(version),
                                cfg.normalized_contract_id(base_version))
            self.assertNotEqual(cfg.market_book_source_id(version),
                                cfg.market_book_source_id(base_version))
            seen_versions.add(version)
        self.assertGreater(len(seen_versions), 30)

    def test_derivation_version_formula(self):
        policy = cfg.load_policy(POLICY_FILE)
        digests = cfg.load_config_digests(CONFIG)
        expected = "mb1-" + sha({
            "code_version": "code-1",
            "endpoint_spec_digest": sha(json.loads((CONFIG / "oddspapi_v4_endpoints.json").read_text())),
            "identity_map_digest": sha(json.loads((CONFIG / "oddspapi_v4_identity_map.json").read_text())),
            "market_map_digest": sha(json.loads((CONFIG / "oddspapi_v4_market_map.json").read_text())),
            "policy_digest": policy.digest,
            "response_schema_digest": sha(json.loads((CONFIG / "oddspapi_v4_response_schemas.json").read_text())),
            "status_map_digest": sha(json.loads((CONFIG / "oddspapi_v4_status_map.json").read_text())),
        })[:16]
        self.assertEqual(cfg.derivation_version("code-1", digests, policy), expected)
        self.assertRegex(expected, r"^mb1-[0-9a-f]{16}$")
        self.assertEqual(cfg.normalized_contract_id(expected), f"oddspapi-v4-market-book-{expected}")
        self.assertEqual(cfg.market_book_source_id(expected), f"oddspapi.v4.soccer.market_book.{expected}")
        self.assertNotEqual(cfg.derivation_version("code-2", digests, policy), expected)


class ConfigDigestTests(unittest.TestCase):
    def _variant(self, filename, mutator):
        root_cm = scratch_root()
        root = root_cm.__enter__()
        try:
            target = root / "config"
            shutil.copytree(CONFIG, target)
            path = target / filename
            data = json.loads(path.read_text(encoding="utf-8"))
            mutator(data)
            path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return cfg.load_config_digests(target)
        finally:
            root_cm.__exit__(None, None, None)

    def test_sch04_schema_file_change_yields_new_schema_digest_and_derivation_version(self):
        base_digests = cfg.load_config_digests(CONFIG)
        policy = cfg.load_policy(POLICY_FILE)

        def add_inert(data):
            data["schemas"]["oddspapi.v4.odds_by_tournaments.v1"]["objects"]["price"]["keys"]["newKey"] = {
                "inert": True, "type": "str"}

        changed = self._variant("oddspapi_v4_response_schemas.json", add_inert)
        self.assertNotEqual(changed["response_schema_digest"], base_digests["response_schema_digest"])
        self.assertNotEqual(cfg.derivation_version("c", changed, policy),
                            cfg.derivation_version("c", base_digests, policy))
        for key in base_digests:
            if key != "response_schema_digest":
                self.assertEqual(changed[key], base_digests[key], key)

    def test_each_config_file_feeds_its_own_digest(self):
        base = cfg.load_config_digests(CONFIG)
        mutations = {
            "oddspapi_v4_identity_map.json": ("identity_map_digest", lambda d: d["competitions"][0].update(
                genesis_competition_id="soccer.eng.other")),
            "oddspapi_v4_market_map.json": ("market_map_digest", lambda d: d["markets"][0].update(
                doc_reference="changed")),
            "oddspapi_v4_status_map.json": ("status_map_digest", lambda d: d["event_status"][0].update(
                doc_reference="changed")),
            "oddspapi_v4_endpoints.json": ("endpoint_spec_digest", lambda d: d["endpoints"][0].update(
                doc_reference="changed")),
        }
        for filename, (digest_key, mutator) in mutations.items():
            changed = self._variant(filename, mutator)
            self.assertNotEqual(changed[digest_key], base[digest_key], filename)
            for other in base:
                if other != digest_key:
                    self.assertEqual(changed[other], base[other], f"{filename}:{other}")


class AdapterConfigTests(unittest.TestCase):
    def test_id09_operational_loader_refuses_fixture_only_maps(self):
        with self.assertRaises(cfg.FixtureOnlyConfig):
            cfg.load_adapter_config(CONFIG)
        loaded = cfg.load_adapter_config(CONFIG, allow_fixture_only=True)
        self.assertEqual(loaded.policy.digest, cfg.load_policy(POLICY_FILE).digest)
        self.assertEqual(set(loaded.endpoints), {"META_SPORTS", "META_TOURNAMENTS", "META_BOOKMAKERS",
                                                  "META_MARKETS", "FIXTURES", "ODDS"})

    def test_loaded_config_exposes_digests_and_a_derivation_version(self):
        loaded = cfg.load_adapter_config(CONFIG, allow_fixture_only=True, code_version="code-1")
        self.assertRegex(loaded.derivation_version, r"^mb1-[0-9a-f]{16}$")
        self.assertEqual(loaded.digests, cfg.load_config_digests(CONFIG))


if __name__ == "__main__":
    unittest.main()
