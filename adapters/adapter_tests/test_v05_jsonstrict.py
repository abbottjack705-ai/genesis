"""MKT-07 (literal parsing part) and F-13 payload decoding rules."""

from __future__ import annotations

import unittest
from decimal import Decimal

from genesis_adapters import jsonstrict

LIMIT = 1 << 20


class StrictJsonTests(unittest.TestCase):
    def test_mkt07_numbers_are_exact_decimals_never_floats(self):
        data = jsonstrict.loads_strict(b'{"a": 1.910, "b": 2, "c": 1E2, "d": 0.10, "e": -0.0}',
                                       max_bytes=LIMIT)
        self.assertIsInstance(data["a"], Decimal)
        self.assertEqual(str(data["a"]), "1.910")
        self.assertIs(type(data["b"]), int)
        self.assertEqual(str(data["d"]), "0.10")
        self.assertFalse(any(isinstance(v, float) for v in data.values()))
        nested = jsonstrict.loads_strict(b'[[1.5, {"x": 2.25}]]', max_bytes=LIMIT)
        self.assertIsInstance(nested[0][0], Decimal)
        self.assertIsInstance(nested[0][1]["x"], Decimal)

    def test_valid_documents_round_trip_types(self):
        self.assertEqual(jsonstrict.loads_strict(b"[]", max_bytes=LIMIT), [])
        self.assertEqual(jsonstrict.loads_strict(b'{"k": [true, false, null, "s"]}', max_bytes=LIMIT),
                         {"k": [True, False, None, "s"]})
        self.assertEqual(jsonstrict.loads_strict(" \n[1]\n ".encode(), max_bytes=LIMIT), [1])

    def _code(self, data: bytes, limit: int = LIMIT) -> str:
        with self.assertRaises(jsonstrict.StrictJsonError) as caught:
            jsonstrict.loads_strict(data, max_bytes=limit)
        return caught.exception.code

    def test_duplicate_keys_are_rejected_at_every_depth(self):
        self.assertEqual(self._code(b'{"a": 1, "a": 2}'), "DUPLICATE_KEYS")
        self.assertEqual(self._code(b'{"x": {"a": 1, "b": 2, "a": 3}}'), "DUPLICATE_KEYS")
        self.assertEqual(self._code(b'[{"a": 1, "a": 1}]'), "DUPLICATE_KEYS")

    def test_non_finite_numbers_are_rejected(self):
        for text in (b"NaN", b"Infinity", b"-Infinity", b'{"a": NaN}', b"[Infinity]"):
            self.assertEqual(self._code(text), "NONFINITE_NUMBER", text)

    def test_encoding_and_shape_failures(self):
        self.assertEqual(self._code(b"\xef\xbb\xbf[1]"), "NOT_JSON")          # UTF-8 BOM
        self.assertEqual(self._code(b"[\xff]"), "INVALID_UTF8")
        self.assertEqual(self._code("[1]".encode("utf-16")), "INVALID_UTF8")
        self.assertEqual(self._code(b""), "EMPTY")
        self.assertEqual(self._code(b"   \n"), "EMPTY")
        for text in (b"{", b"[1,]", b"{'a': 1}", b"[1] [2]", b"garbage", b'{"a": 1} x'):
            self.assertEqual(self._code(text), "NOT_JSON", text)

    def test_size_cap_is_exact(self):
        body = b'["' + b"x" * 30 + b'"]'
        jsonstrict.loads_strict(body, max_bytes=len(body))
        self.assertEqual(self._code(body, len(body) - 1), "OVERSIZE")

    def test_pathological_nesting_and_huge_integers_fail_closed(self):
        self.assertEqual(self._code(b"[" * 200000 + b"]" * 200000), "NOT_JSON")
        self.assertEqual(self._code(b"1" * 6000), "NOT_JSON")

    def test_error_carries_no_payload_text(self):
        with self.assertRaises(jsonstrict.StrictJsonError) as caught:
            jsonstrict.loads_strict(b'{"secret-looking-key": NaN}', max_bytes=LIMIT)
        self.assertNotIn("secret-looking-key", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
