"""MKT-07 (literal parsing part) and F-13 payload decoding rules."""

from __future__ import annotations

import unittest
from decimal import Decimal

from genesis_adapters import jsonstrict

LIMIT = 1 << 20
DEPTH, EXPONENT = 50, 1000          # the pinned policy's bounds (a test must name them: no default exists)


def loads(data: bytes, *, max_bytes: int = LIMIT, max_depth: int = DEPTH, max_exponent: int = EXPONENT):
    return jsonstrict.loads_strict(data, max_bytes=max_bytes, max_depth=max_depth, max_exponent=max_exponent)


class StrictJsonTests(unittest.TestCase):
    def test_mkt07_numbers_are_exact_decimals_never_floats(self):
        data = loads(b'{"a": 1.910, "b": 2, "c": 1E2, "d": 0.10, "e": -0.0}')
        self.assertIsInstance(data["a"], Decimal)
        self.assertEqual(str(data["a"]), "1.910")
        self.assertIs(type(data["b"]), int)
        self.assertEqual(str(data["d"]), "0.10")
        self.assertFalse(any(isinstance(v, float) for v in data.values()))
        nested = loads(b'[[1.5, {"x": 2.25}]]')
        self.assertIsInstance(nested[0][0], Decimal)
        self.assertIsInstance(nested[0][1]["x"], Decimal)

    def test_valid_documents_round_trip_types(self):
        self.assertEqual(loads(b"[]"), [])
        self.assertEqual(loads(b'{"k": [true, false, null, "s"]}'),
                         {"k": [True, False, None, "s"]})
        self.assertEqual(loads(" \n[1]\n ".encode()), [1])

    def _code(self, data: bytes, limit: int = LIMIT) -> str:
        with self.assertRaises(jsonstrict.StrictJsonError) as caught:
            loads(data, max_bytes=limit)
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
        loads(body, max_bytes=len(body))
        self.assertEqual(self._code(body, len(body) - 1), "OVERSIZE")

    def test_pathological_nesting_and_huge_integers_fail_closed(self):
        # nesting far beyond the decoder's own recursion limit is "too deep" like any other excess (R6)
        self.assertEqual(self._code(b"[" * 200000 + b"]" * 200000), "TOO_DEEP")
        self.assertEqual(self._code(b"1" * 6000), "NUMBER_OUT_OF_RANGE")

    def test_error_carries_no_payload_text(self):
        with self.assertRaises(jsonstrict.StrictJsonError) as caught:
            loads(b'{"secret-looking-key": NaN}')
        self.assertNotIn("secret-looking-key", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)


class StrictJsonBoundTests(unittest.TestCase):
    """R6 / RA5-001: the decoder's bounds - nesting depth, numeric magnitude, encodable text - at their exact edges."""

    def code(self, data: bytes, **kw) -> str:
        with self.assertRaises(jsonstrict.StrictJsonError) as caught:
            loads(data, **kw)
        return caught.exception.code

    # -- nesting depth ----------------------------------------------------------------------------------
    def test_a_container_chain_of_exactly_max_depth_is_accepted_and_one_more_is_too_deep(self):
        for depth in (1, 2, 5, 17):
            text = b"[" * depth + b"]" * depth
            with self.subTest(depth=depth, shape="lists"):
                self.assertIsNotNone(loads(text, max_depth=depth))
                self.assertEqual(self.code(b"[" + text + b"]", max_depth=depth), "TOO_DEEP")
            obj = b'{"a":' * depth + b"1" + b"}" * depth
            with self.subTest(depth=depth, shape="objects"):
                self.assertIsNotNone(loads(obj, max_depth=depth))
                self.assertEqual(self.code(b'{"a":' + obj + b"}", max_depth=depth), "TOO_DEEP")

    def test_depth_counts_every_container_whatever_its_kind_and_content(self):
        self.assertEqual(loads(b"[]", max_depth=1), [])
        self.assertEqual(loads(b"{}", max_depth=1), {})
        self.assertEqual(self.code(b"[[]]", max_depth=1), "TOO_DEEP")                # an EMPTY inner list still counts
        self.assertEqual(self.code(b'{"a": {}}', max_depth=1), "TOO_DEEP")
        self.assertEqual(self.code(b'[{"a": 1}]', max_depth=1), "TOO_DEEP")          # mixed nesting
        self.assertEqual(loads(b'[{"a": [1]}]', max_depth=3), [{"a": [1]}])
        self.assertEqual(self.code(b'[{"a": [1]}]', max_depth=2), "TOO_DEEP")
        self.assertEqual(loads(b"1", max_depth=1), 1)                                 # a scalar root opens nothing
        self.assertEqual(loads(b'"s"', max_depth=1), "s")

    def test_the_depth_check_sees_a_deep_branch_that_is_not_the_first_child(self):
        deep = b"[" * 6 + b"]" * 6
        body = b"[[], [1, 2, 3], {}, " + deep + b"]"                                   # depth 7 only in the last child
        self.assertEqual(self.code(body, max_depth=6), "TOO_DEEP")
        self.assertEqual(len(loads(body, max_depth=7)), 4)

    def test_a_chain_beyond_the_decoders_own_recursion_limit_is_too_deep_not_a_crash(self):
        for depth in (990, 2000, 200000):
            with self.subTest(depth=depth):
                self.assertEqual(self.code(b"[" * depth + b"]" * depth), "TOO_DEEP")

    def test_the_depth_walk_agrees_with_an_independent_recursive_depth_on_random_structures(self):
        import random

        rng = random.Random(3)

        def build(budget):
            if budget == 0 or rng.random() < 0.25:
                return rng.choice([1, "x", None, True])
            if rng.random() < 0.5:
                return [build(budget - 1) for _ in range(rng.randint(0, 3))]
            return {f"k{i}": build(budget - 1) for i in range(rng.randint(0, 3))}

        def depth(node):
            if isinstance(node, dict):
                return 1 + max((depth(v) for v in node.values()), default=0)
            if isinstance(node, list):
                return 1 + max((depth(v) for v in node), default=0)
            return 0

        import json

        for _ in range(300):
            node = build(rng.randint(1, 9))
            text = json.dumps(node).encode()
            actual = depth(node)
            if actual == 0:
                continue
            self.assertEqual(loads(text, max_depth=actual), node)
            if actual > 1:
                self.assertEqual(self.code(text, max_depth=actual - 1), "TOO_DEEP", text[:80])

    # -- numeric magnitude -------------------------------------------------------------------------------
    def test_a_decimal_literal_is_bounded_by_its_adjusted_exponent_in_both_directions(self):
        accepted = (b"1E+5", b"1E-5", b"123E+3", b"0.00001", b"100000.0", b"-1E+5", b"-1E-5", b"0E+5", b"0E-5",
                    b"1.5", b"0", b"-0.0")
        rejected = (b"1E+6", b"1E-6", b"123E+4", b"0.000001", b"1000000.0", b"-1E+6", b"-1E-6", b"0E+6", b"0E-6")
        for literal in accepted:
            with self.subTest(accepted=literal):
                loads(b"[" + literal + b"]", max_exponent=5)
        for literal in rejected:
            with self.subTest(rejected=literal):
                self.assertEqual(self.code(b"[" + literal + b"]", max_exponent=5), "NUMBER_OUT_OF_RANGE")

    def test_an_integer_literal_is_bounded_by_the_same_measure(self):
        for literal in (b"100000", b"-100000", b"99999", b"0", b"-0"):
            with self.subTest(accepted=literal):
                loads(b"[" + literal + b"]", max_exponent=5)
        for literal in (b"1000000", b"-1000000", b"9" * 40):
            with self.subTest(rejected=literal):
                self.assertEqual(self.code(b"[" + literal + b"]", max_exponent=5), "NUMBER_OUT_OF_RANGE")
        for digits in (1000, 1001, 4300, 4301, 6000):                                  # the default bound, around the
            with self.subTest(digits=digits):                                          # interpreter's own int limit
                literal = b"1" + b"0" * (digits - 1)
                if digits <= EXPONENT + 1:
                    loads(b"[" + literal + b"]")
                else:
                    self.assertEqual(self.code(b"[" + literal + b"]"), "NUMBER_OUT_OF_RANGE")

    def test_an_exponent_beyond_what_a_decimal_can_represent_is_out_of_range_never_an_arithmetic_error(self):
        """The decoder itself used to leak ``decimal.InvalidOperation`` for these (an uncaught exception before the
        attempt's verdict row existed)."""

        for literal in (b"1E+99999999999999999999", b"1E-99999999999999999999", b"0E+99999999999999999999",
                        b"-1E+99999999999999999999999999", b"1E+999999999", b"1E-999999999"):
            with self.subTest(literal):
                self.assertEqual(self.code(b"[" + literal + b"]"), "NUMBER_OUT_OF_RANGE")

    def test_numbers_are_bounded_wherever_they_sit(self):
        for text in (b'{"a": [1, {"b": 1E+2000}]}', b'[[[[1E-2000]]]]', b'{"k": {"k": {"k": 9' + b"9" * 1200 + b"}}}"):
            with self.subTest(text[:30]):
                self.assertEqual(self.code(text), "NUMBER_OUT_OF_RANGE")
        loads(b'{"a": [1, {"b": 1E+999}]}')                                            # under the bound: fine

    def test_in_range_numbers_stay_exact_decimals(self):
        value = loads(b"[1.9100, 2.50, 1E+3]")
        self.assertEqual([str(x) for x in value], ["1.9100", "2.50", "1E+3"])

    # -- encodable text ---------------------------------------------------------------------------------
    def test_a_lone_surrogate_anywhere_is_invalid_text(self):
        for escaped in ("\\ud800", "\\udbff", "\\udc00", "\\udfff", "\\ud800x", "x\\udfff", "\\ud800\\ud800",
                        "\\udc00\\ud800"):                                         # incl. a pair in the wrong order
            for shape in ('["%s"]', '{"k": "%s"}', '{"%s": 1}', '[[{"a": ["%s"]}]]', '{"a": {"%s": [1]}}'):
                with self.subTest(escaped=escaped, shape=shape):
                    self.assertEqual(self.code((shape % escaped).encode()), "INVALID_UTF8")

    def test_well_formed_text_is_accepted(self):
        for escaped in ("\\ud83d\\ude00", "\\u00e9", "\\u4e2d", "\\ud7ff", "\\ue000", "\u00e9"):
            for shape in ('["%s"]', '{"k": "%s"}', '{"%s": 1}'):
                with self.subTest(escaped=escaped, shape=shape):
                    loads((shape % escaped).encode())
        self.assertEqual(loads('["é中😀"]'.encode()), ["é中😀"])

    def test_the_text_walk_reaches_every_string_not_only_the_first(self):
        items = ",".join('"ok%d"' % i for i in range(500))
        for position in (0, 250, 499):
            parts = ['"ok%d"' % i for i in range(500)]
            parts[position] = '"\\ud800"'
            with self.subTest(position=position):
                self.assertEqual(self.code(("[" + ",".join(parts) + "]").encode()), "INVALID_UTF8")
        keys = ",".join('"k%d": 1' % i for i in range(300))
        self.assertEqual(self.code(('{' + keys + ', "\\udfff": 1}').encode()), "INVALID_UTF8")
        loads(("[" + items + "]").encode())

    # -- the contract ------------------------------------------------------------------------------------
    def test_every_code_has_exactly_one_taxonomy_outcome(self):
        from genesis_adapters.errors import JSON_FAILURE, AdapterFailure, reason_code

        self.assertEqual(set(jsonstrict.CODES), set(JSON_FAILURE))
        self.assertEqual(JSON_FAILURE["TOO_DEEP"], AdapterFailure.NESTING_TOO_DEEP)       # each new code is its own outcome
        self.assertEqual(JSON_FAILURE["NUMBER_OUT_OF_RANGE"], AdapterFailure.NUMBER_OUT_OF_RANGE)
        self.assertEqual(JSON_FAILURE["INVALID_UTF8"], AdapterFailure.INVALID_UTF8)
        for failure in JSON_FAILURE.values():
            self.assertIsInstance(failure, AdapterFailure)
            reason_code(failure)                                                         # and a frozen reason exists

    def test_the_bounds_have_no_defaults_so_no_caller_can_forget_them(self):
        with self.assertRaises(TypeError):
            jsonstrict.loads_strict(b"[]", max_bytes=LIMIT)

    def test_a_bound_error_carries_no_payload_text(self):
        for text in (b'["\\ud800-secret-looking"]', b'{"secret-looking-key": 1E+2000}', b"[" * 200 + b"]" * 200):
            with self.assertRaises(jsonstrict.StrictJsonError) as caught:
                loads(text)
            self.assertEqual(str(caught.exception), caught.exception.code)
            self.assertIsNone(caught.exception.__cause__)

    def test_the_size_cap_is_still_checked_before_anything_else(self):
        body = b"[" * 200 + b"]" * 200
        self.assertEqual(self.code(body, max_bytes=len(body) - 1), "OVERSIZE")


if __name__ == "__main__":
    unittest.main()
