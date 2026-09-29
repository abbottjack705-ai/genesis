"""ID-01, ID-02: deterministic identity function and native-ID canonicalization."""

from __future__ import annotations

import hashlib
import json
import unittest

from genesis_adapters import ids


def independent_gid(kind: str, **parts) -> str:
    """Recompute the section 8.1 formula with no genesis code."""

    body = json.dumps({"domain": "genesis.adapters.identity.v1", "kind": kind, "parts": parts},
                      ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")) + "\n"
    return kind + ":" + hashlib.sha256(body.encode("utf-8")).hexdigest()


EVENT = ids.gid("evt", provider="oddspapi", ns="v4.fixture", native_type="str",
                native="id1000001761301153")
MARKET = ids.gid("mkt", event_id=EVENT, family="SOCCER_1X2_FT", line=None, period="FT_REGULAR")

VECTORS = [
    ("part", dict(provider="oddspapi", ns="v4.participant", native_type="int", native="35")),
    ("evt", dict(provider="oddspapi", ns="v4.fixture", native_type="str", native="id1000001761301153")),
    ("mkt", dict(event_id=EVENT, family="SOCCER_1X2_FT", line=None, period="FT_REGULAR")),
    ("mkt", dict(event_id=EVENT, family="SOCCER_TOTAL_GOALS_OU_FT", line="2.5", period="FT_REGULAR")),
    ("sel", dict(market_id=MARKET, selection="HOME")),
    ("book", dict(market_id=MARKET, bookmaker_id="bk.pinnacle")),
    ("rev", dict(observation_id="ab" * 32)),
]

PINNED = {
    0: "part:PINNED0",
}


class GidTests(unittest.TestCase):
    def test_id01_matches_the_independent_formula_for_every_kind(self):
        for kind, parts in VECTORS:
            with self.subTest(kind=kind):
                value = ids.gid(kind, **parts)
                self.assertEqual(value, independent_gid(kind, **parts))
                prefix, digest = value.split(":")
                self.assertEqual(prefix, kind)
                self.assertEqual(len(digest), 64)
                int(digest, 16)
                self.assertEqual(digest, digest.lower())

    def test_id01_pinned_golden_vectors(self):
        from . import golden
        for index, (kind, parts) in enumerate(VECTORS):
            self.assertEqual(ids.gid(kind, **parts), golden.GID_VECTORS[index], f"vector {index}")

    def test_id01_parts_are_order_independent_and_kinds_are_domain_separated(self):
        a = ids.gid("part", provider="oddspapi", ns="v4.participant", native_type="int", native="35")
        b = ids.gid("part", native="35", native_type="int", ns="v4.participant", provider="oddspapi")
        self.assertEqual(a, b)
        other_kind = ids.gid("evt", provider="oddspapi", ns="v4.participant", native_type="int",
                             native="35")
        self.assertNotEqual(a.split(":")[1], other_kind.split(":")[1])
        for changed in ({"native": "36"}, {"provider": "other"}, {"ns": "v4.fixture"},
                        {"native_type": "str"}):
            base = dict(provider="oddspapi", ns="v4.participant", native_type="int", native="35")
            base.update(changed)
            self.assertNotEqual(ids.gid("part", **base), a)

    def test_id01_no_delimiter_ambiguity(self):
        one = ids.gid("part", provider="a|b", ns="c", native_type="int", native="1")
        two = ids.gid("part", provider="a", ns="b|c", native_type="int", native="1")
        self.assertNotEqual(one, two)

    def test_id01_rejects_bad_kinds_and_unserializable_parts(self):
        for bad in ("", "Part", "p-art", "part:x", "part x", "1"):
            with self.assertRaises(ids.IdentityError):
                ids.gid(bad, x="1")
        with self.assertRaises(ids.IdentityError):
            ids.gid("part", x=object())
        with self.assertRaises(ids.IdentityError):
            ids.gid("part")


class NativeIdTests(unittest.TestCase):
    def test_id02_int_and_str_are_never_coerced(self):
        self.assertEqual(ids.native_id(17, declared_type="int"), {"native_type": "int", "value": "17"})
        self.assertEqual(ids.native_id("17", declared_type="str"), {"native_type": "str", "value": "17"})
        for value, declared in ((17, "str"), ("17", "int"), (True, "int"), (1.0, "int"),
                                (None, "str"), (b"17", "str")):
            with self.assertRaises(ids.IdentityTypeError) as caught:
                ids.native_id(value, declared_type=declared)
            self.assertEqual(caught.exception.code, "SCHEMA_REJECTED")

    def test_id02_the_two_typed_forms_yield_different_identities(self):
        as_int = ids.gid("part", provider="oddspapi", ns="v4.participant",
                         **{"native_type": "int", "native": "17"})
        as_str = ids.gid("part", provider="oddspapi", ns="v4.participant",
                         **{"native_type": "str", "native": "17"})
        self.assertNotEqual(as_int, as_str)

    def test_id02_string_grammar_and_int_range(self):
        for good in ("a", "A-z_0.9:x", "x" * 64, "id1000001761301153"):
            ids.native_id(good, declared_type="str")
        for bad in ("", "x" * 65, "has space", "pipe|x", "é", "a/b", "a\nb", "a=b"):
            with self.assertRaises(ids.IdentityTypeError):
                ids.native_id(bad, declared_type="str")
        for bad in (-1, 10 ** 70):
            with self.assertRaises(ids.IdentityTypeError):
                ids.native_id(bad, declared_type="int")
        self.assertEqual(ids.native_id(0, declared_type="int")["value"], "0")

    def test_declared_type_must_be_int_or_str(self):
        with self.assertRaises(ids.IdentityError):
            ids.native_id(1, declared_type="float")


if __name__ == "__main__":
    unittest.main()
