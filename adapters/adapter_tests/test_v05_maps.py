"""ST-01, ID-06, ID-07, ID-09, MKT-02 and the closed-shape validation of the pinned identity/market/status maps."""

from __future__ import annotations

import copy
import json
import unittest
from decimal import Decimal

from genesis_adapters import config as cfg
from genesis_adapters.oddspapi import maps as maps_mod
from genesis_adapters.oddspapi.maps import MapError

from . import parser_support as ps
from .parser_support import CONFIG_BODY, MAPS, POLICY, books_by, maps_with, odds_payload, parse
from .support import CONFIG


class LoadTests(unittest.TestCase):
    def test_the_pinned_files_load_into_typed_maps(self):
        self.assertEqual({key: c.genesis_id for key, c in MAPS.competitions.items()},
                         {("int", "17"): "soccer.eng.premier-league", ("int", "8"): "soccer.esp.laliga"})
        self.assertEqual([b.key for b in MAPS.declared_bookmakers()], ["fixture-book-a", "fixture-book-b", "pinnacle"])
        self.assertEqual(MAPS.sport_id, 10)
        self.assertEqual(sorted(MAPS.families), ["SOCCER_1X2_FT", "SOCCER_TOTAL_GOALS_OU_FT"])
        self.assertEqual(MAPS.families["SOCCER_TOTAL_GOALS_OU_FT"].required_line, Decimal("2.5"))
        self.assertIsNone(MAPS.families["SOCCER_1X2_FT"].required_line)
        self.assertTrue(MAPS.fixture_only)
        self.assertEqual(MAPS.market("int", "101").family, "SOCCER_1X2_FT")
        self.assertEqual(MAPS.market("int", "1010").outcome_field, "handicap")
        self.assertEqual(MAPS.market("int", "101").outcome_field, None)

    def test_id09_the_operational_loader_refuses_maps_that_still_hold_fixture_only_entries(self):
        with self.assertRaises(cfg.FixtureOnlyConfig):
            cfg.load_adapter_config(CONFIG)
        cfg.load_adapter_config(CONFIG, allow_fixture_only=True)          # only tests may opt in
        self.assertTrue(MAPS.fixture_only)

    def test_id06_only_the_two_pinned_competitions_are_known(self):
        self.assertIsNotNone(MAPS.competition("int", "17"))
        self.assertIsNotNone(MAPS.competition("int", "8"))
        for native in (("int", "18"), ("str", "17"), ("int", "0"), ("int", "817")):
            self.assertIsNone(MAPS.competition(*native))

    def test_mkt02_more_than_the_permitted_bookmakers_normalize_only_under_a_larger_policy_limit(self):
        def add_two_more(identity):
            template = identity["bookmakers"][0]                       # a declared sportsbook
            for number in (1, 2):
                identity["bookmakers"].append({**template, "provider_bookmaker_key": f"extra-{number}",
                                               "genesis_bookmaker_id": f"bk.extra-{number}"})
            return identity

        with self.assertRaises(MapError):                             # the operational limit is a policy field
            maps_with(identity=add_two_more)
        five = maps_with(identity=add_two_more, declared_max=5)
        self.assertEqual(len(five.declared_bookmakers()), 5)
        payload = odds_payload()
        for fixture in payload:
            for key in ("extra-1", "extra-2"):
                fixture["bookmakerOdds"][key] = copy.deepcopy(fixture["bookmakerOdds"]["pinnacle"])
        parsed = parse(payload, maps=five, policy=ps.policy_with(declared_bookmakers_max=5))
        self.assertEqual({b.provider_bookmaker_key for b in parsed.books},
                         {"pinnacle", "fixture-book-a", "fixture-book-b", "extra-1", "extra-2"})
        self.assertEqual(len(books_by(parsed)), 10)                    # 5 bookmakers x 2 families

    def test_mkt02_an_exchange_can_never_be_declared(self):
        def declare_exchange(identity):
            for entry in identity["bookmakers"]:
                if entry["kind"] == "exchange":
                    entry["declared"] = True
            return identity

        for limit in (POLICY.declared_bookmakers_max, 50):
            with self.assertRaises(MapError):
                maps_with(identity=declare_exchange, declared_max=limit)


class StatusAllowlistTests(unittest.TestCase):
    def test_st01_every_allowlisted_value_maps_exactly(self):
        status = json.loads((CONFIG / "oddspapi_v4_status_map.json").read_text(encoding="utf-8"))
        expected_levels = {"event": "event_status", "market": "market_status", "outcome": "outcome_status",
                           "bookmaker": "bookmaker_status"}
        total = 0
        for level, section in expected_levels.items():
            for rule in status[section]:
                self.assertEqual(MAPS.classify(level, rule["field"], rule["value"]), rule["genesis"], rule)
                total += 1
        self.assertGreaterEqual(total, 8)

    def test_st01_the_event_states_are_the_documented_ones(self):
        self.assertEqual(MAPS.classify("event", "statusId", 0), "PREMATCH")
        self.assertEqual({MAPS.classify("event", "statusId", value) for value in (1, 2, 3)}, {"NOT_PREMATCH"})
        self.assertEqual(MAPS.classify("outcome", "active", True), "ACTIVE")
        self.assertEqual(MAPS.classify("outcome", "active", False), "INACTIVE")
        self.assertEqual(MAPS.classify("bookmaker", "bookmakerIsActive", True), "ACTIVE")
        self.assertEqual(MAPS.classify("bookmaker", "bookmakerIsActive", False), "INACTIVE")

    def test_st06_matching_is_on_field_json_type_and_value(self):
        for value in ("0", "PREMATCH", None, 0.5, [0], {"a": 0}, True, False, 4, -1):
            self.assertIsNone(MAPS.classify("event", "statusId", value), value)
        self.assertIsNone(MAPS.classify("event", "otherField", 0))
        for value in (1, 0, "true", "false", None):
            self.assertIsNone(MAPS.classify("outcome", "active", value), value)
        self.assertIsNone(MAPS.classify("outcome", "statusId", True))

    def test_the_status_field_of_a_level_is_unique(self):
        self.assertEqual([MAPS.status_field(level) for level in ("event", "outcome", "bookmaker", "market")],
                         ["statusId", "active", "bookmakerIsActive", None])


class ClosedShapeTests(unittest.TestCase):
    def assert_refused(self, **edits):
        with self.assertRaises(MapError):
            maps_with(**edits)

    def test_an_unknown_key_anywhere_in_a_map_is_refused(self):
        def add(target_path):
            def edit(document):
                node = document
                for step in target_path:
                    node = node[step]
                node["surprise"] = 1
                return document
            return edit

        for label, kwargs in (
                ("identity root", dict(identity=add(()))),
                ("competition", dict(identity=add(("competitions", 0)))),
                ("bookmaker", dict(identity=add(("bookmakers", 0)))),
                ("market root", dict(market=add(()))),
                ("family", dict(market=add(("families", "SOCCER_1X2_FT")))),
                ("market entry", dict(market=add(("markets", 0)))),
                ("status root", dict(status=add(()))),
                ("status rule", dict(status=add(("event_status", 0))))):
            with self.subTest(label):
                self.assert_refused(**kwargs)

    def test_a_missing_key_is_refused(self):
        def drop(section, index, key):
            def edit(document):
                del document[section][index][key]
                return document
            return edit

        self.assert_refused(identity=drop("competitions", 0, "sport"))
        self.assert_refused(identity=drop("bookmakers", 0, "kind"))
        self.assert_refused(market=drop("markets", 0, "line_source"))
        self.assert_refused(status=drop("outcome_status", 0, "json_type"))

    def test_market_map_consistency_is_enforced(self):
        def edit_market(index, **changes):
            def edit(document):
                document["markets"][index].update(changes)
                return document
            return edit

        self.assert_refused(market=edit_market(0, outcomes={"101": "HOME", "102": "DRAW"}))           # incomplete
        self.assert_refused(market=edit_market(0, outcomes={"101": "HOME", "102": "DRAW", "103": "OVER"}))
        self.assert_refused(market=edit_market(0, outcomes={"101": "HOME", "102": "HOME", "103": "AWAY"}))
        self.assert_refused(market=edit_market(0, family="NO_SUCH_FAMILY"))
        self.assert_refused(market=edit_market(0, line="2.5", line_source="market_definition"))       # lineless family
        self.assert_refused(market=edit_market(1, line_source="none"))                                  # lined family
        self.assert_refused(market=edit_market(1, line="2.5"))                    # a static line needs its source
        self.assert_refused(market=edit_market(1, line_source="guess"))
        self.assert_refused(market=edit_market(1, period="FT_OVERTIME"))
        self.assert_refused(market=edit_market(1, native_type="float"))
        self.assert_refused(market=edit_market(1, provider_market_id="1010"))                        # int declared
        duplicate = lambda document: document["markets"].append(copy.deepcopy(document["markets"][0])) or document
        self.assert_refused(market=duplicate)

    def test_a_static_line_is_accepted_when_it_matches_its_declared_source(self):
        def static(document):
            document["markets"][1].update(line="2.5", line_source="market_definition")
            return document

        loaded = maps_with(market=static)
        self.assertEqual(loaded.market("int", "1010").line, Decimal("2.5"))
        self.assertIsNone(loaded.market("int", "1010").outcome_field)

    def test_status_map_consistency_is_enforced(self):
        def edit_rule(section, index, **changes):
            def edit(document):
                document[section][index].update(changes)
                return document
            return edit

        self.assert_refused(status=edit_rule("event_status", 0, json_type="str"))                # value/type mismatch
        self.assert_refused(status=edit_rule("event_status", 0, genesis="OPEN"))                 # wrong vocabulary
        self.assert_refused(status=edit_rule("outcome_status", 0, value=1))
        self.assert_refused(status=lambda d: d["event_status"].append(copy.deepcopy(d["event_status"][0])) or d)
        self.assert_refused(status=lambda d: d.update(market_level_status="PRESENT") or d)
        self.assert_refused(status=lambda d: d["market_status"].append(
            {"field": "state", "json_type": "int", "value": 1, "genesis": "OPEN", "doc_reference": "x",
             "verified_live": False}) or d)
        self.assert_refused(status=lambda d: d["event_status"].append(
            {"field": "otherStatus", "json_type": "int", "value": 7, "genesis": "PREMATCH", "doc_reference": "x",
             "verified_live": False}) or d)

    def test_identity_map_consistency_is_enforced(self):
        def edit_competition(index, **changes):
            def edit(document):
                document["competitions"][index].update(changes)
                return document
            return edit

        def edit_bookmaker(index, **changes):
            def edit(document):
                document["bookmakers"][index].update(changes)
                return document
            return edit

        self.assert_refused(identity=edit_competition(0, provider_tournament_id="17"))              # int declared
        self.assert_refused(identity=edit_competition(0, provider_tournament_id=-1))
        self.assert_refused(identity=edit_competition(0, sport="basketball"))
        self.assert_refused(identity=edit_competition(0, genesis_competition_id="Not A Slug"))
        self.assert_refused(identity=edit_competition(1, provider_tournament_id=17))                # duplicate id
        self.assert_refused(identity=edit_competition(1, genesis_competition_id="soccer.eng.premier-league"))
        self.assert_refused(identity=edit_bookmaker(0, genesis_bookmaker_id="pinnacle"))
        self.assert_refused(identity=edit_bookmaker(0, genesis_bookmaker_id="bk.fixture-book-a"))    # duplicate
        self.assert_refused(identity=edit_bookmaker(0, provider_bookmaker_key="bad key"))
        self.assert_refused(identity=edit_bookmaker(0, declared="yes"))
        self.assert_refused(identity=lambda d: d.update(provider_sport={"sport": "soccer"}) or d)


if __name__ == "__main__":
    unittest.main()
