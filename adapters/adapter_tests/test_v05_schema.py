"""Closed-schema validator (design section 10.1): unit behaviour."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal

from genesis_adapters import schema as sch

from .support import CONFIG

TINY = {
    "root": {"type": "array", "ref": "event"},
    "objects": {
        "event": {"scope": "EVENT", "keys": {
            "id": {"type": "str", "required": True, "identity": True},
            "n": {"type": "int", "required": True},
            "note": {"type": "str", "inert": True},
            "maybe": {"type": ["str", "null"]},
            "status": {"type": "int", "values": [0, 1]},
            "amount": {"type": "number"},
            "flag": {"type": "bool"},
            "books": {"type": "object_map", "ref": "book", "required": True},
        }},
        "book": {"scope": "EVENT_BOOKMAKER", "keys": {
            "active": {"type": "bool", "required": True},
            "prices": {"type": "object_map", "ref": "price", "required": True},
        }},
        "price": {"scope": "BOOK", "keys": {
            "value": {"type": "number", "required": True},
            "meta": {"type": "object", "ref": "meta"},
        }},
        "meta": {"scope": "BOOK", "keys": {}},
    },
}


def good_event(**overrides):
    event = {"id": "e1", "n": 3, "books": {"b1": {"active": True, "prices": {
        "0": {"value": Decimal("1.5")}}}}}
    event.update(overrides)
    return event


def make(value=None, schema_obj=TINY):
    return sch.validate_closed([good_event()] if value is None else value,
                               sch.load_closed_schema("tiny", schema_obj))


def kinds(findings):
    return sorted((f.kind, f.scope, f.path) for f in findings)


class ClosedSchemaTests(unittest.TestCase):
    def test_clean_document_has_no_findings(self):
        self.assertEqual(make(), ())

    def test_unknown_key_scope_follows_the_object_that_holds_it(self):
        cases = {
            "EVENT": lambda e: e.update(extra=1),
            "EVENT_BOOKMAKER": lambda e: e["books"]["b1"].update(extra=1),
            "BOOK": lambda e: e["books"]["b1"]["prices"]["0"].update(extra=1),
        }
        for scope, mutate in cases.items():
            event = good_event()
            mutate(event)
            found = make([event])
            self.assertEqual([(f.kind, f.scope) for f in found], [("UNKNOWN_KEY", scope)], scope)

    def test_unknown_key_inside_the_empty_closed_object(self):
        event = good_event()
        event["books"]["b1"]["prices"]["0"]["meta"] = {"anything": 1}
        self.assertEqual([(f.kind, f.scope) for f in make([event])], [("UNKNOWN_KEY", "BOOK")])
        event["books"]["b1"]["prices"]["0"]["meta"] = {}
        self.assertEqual(make([event]), ())

    def test_inert_keys_are_type_checked_but_accepted(self):
        self.assertEqual(make([good_event(note="x")]), ())
        self.assertEqual([f.kind for f in make([good_event(note=5)])], ["WRONG_TYPE"])

    def test_wrong_types_missing_required_and_enums(self):
        self.assertEqual([f.kind for f in make([good_event(n="3")])], ["WRONG_TYPE"])
        self.assertEqual([f.kind for f in make([good_event(n=True)])], ["WRONG_TYPE"])
        self.assertEqual([f.kind for f in make([good_event(n=Decimal("3"))])], ["WRONG_TYPE"])
        self.assertEqual([f.kind for f in make([good_event(flag=1)])], ["WRONG_TYPE"])
        self.assertEqual([f.kind for f in make([good_event(amount=True)])], ["WRONG_TYPE"])
        self.assertEqual(make([good_event(amount=2)]), ())
        self.assertEqual(make([good_event(amount=Decimal("2.50"))]), ())
        self.assertEqual(make([good_event(maybe=None)]), ())
        self.assertEqual([f.kind for f in make([good_event(maybe=3)])], ["WRONG_TYPE"])
        event = good_event()
        del event["n"]
        self.assertEqual([f.kind for f in make([event])], ["MISSING_REQUIRED"])
        self.assertEqual([f.kind for f in make([good_event(status=1)])], [])
        self.assertEqual([f.kind for f in make([good_event(status=7)])], ["UNKNOWN_ENUM"])
        self.assertEqual([f.kind for f in make([good_event(status="1")])], ["WRONG_TYPE"])

    def test_identity_key_problems_escalate_to_response_scope(self):
        event = good_event()
        del event["id"]
        self.assertEqual([(f.kind, f.scope) for f in make([event])], [("MISSING_REQUIRED", "RESPONSE")])
        self.assertEqual([(f.kind, f.scope) for f in make([good_event(id=5)])],
                         [("WRONG_TYPE", "RESPONSE")])

    def test_envelope_problems_are_response_scope(self):
        self.assertEqual([(f.kind, f.scope, f.path) for f in make({"not": "a list"})],
                         [("WRONG_TYPE", "RESPONSE", "$")])
        self.assertEqual([(f.kind, f.scope) for f in make([5])], [("WRONG_TYPE", "RESPONSE")])
        self.assertEqual(make([]), ())

    def test_object_map_values_and_key_grammar(self):
        event = good_event()
        event["books"]["bad key with spaces"] = {"active": True, "prices": {}}
        found = make([event])
        self.assertEqual([f.kind for f in found], ["UNKNOWN_KEY"])
        event = good_event()
        event["books"]["b1"] = "not an object"
        self.assertEqual([(f.kind, f.scope) for f in make([event])],
                         [("WRONG_TYPE", "EVENT")])

    def test_findings_are_deterministic_and_carry_paths_only(self):
        event = good_event(extra=1, n="x")
        event["books"]["b1"]["prices"]["0"]["zzz"] = Decimal("9")
        first = make([event])
        self.assertEqual(first, make([event]))
        self.assertEqual(list(first), sorted(first, key=lambda f: (f.path, f.kind)))
        for finding in first:
            self.assertTrue(finding.path.startswith("$"))
            self.assertNotIn("9", finding.path.replace("$[0]", ""))

    def test_schema_files_are_themselves_validated(self):
        broken = json.loads(json.dumps(TINY))
        broken["objects"]["event"]["keys"]["n"]["type"] = "integer"
        with self.assertRaises(sch.SchemaDefinitionError):
            sch.load_closed_schema("x", broken)
        broken = json.loads(json.dumps(TINY))
        broken["objects"]["event"]["keys"]["books"]["ref"] = "missing"
        with self.assertRaises(sch.SchemaDefinitionError):
            sch.load_closed_schema("x", broken)
        broken = json.loads(json.dumps(TINY))
        broken["objects"]["event"]["keys"]["n"]["surprise"] = True
        with self.assertRaises(sch.SchemaDefinitionError):
            sch.load_closed_schema("x", broken)
        broken = json.loads(json.dumps(TINY))
        broken["objects"]["event"]["scope"] = "GALAXY"
        with self.assertRaises(sch.SchemaDefinitionError):
            sch.load_closed_schema("x", broken)

    def test_shipped_schemas_load_and_have_stable_digests(self):
        document = json.loads((CONFIG / "oddspapi_v4_response_schemas.json").read_text())
        loaded = {name: sch.load_closed_schema(name, body) for name, body in document["schemas"].items()}
        self.assertEqual(len(loaded), 6)
        digests = {name: schema.digest for name, schema in loaded.items()}
        self.assertEqual(len(set(digests.values())), 6)
        again = {name: sch.load_closed_schema(name, body).digest
                 for name, body in document["schemas"].items()}
        self.assertEqual(digests, again)


if __name__ == "__main__":
    unittest.main()
