"""FRZ-10: no numeric duration, bound, threshold or timeout literal in genesis_adapters."""

from __future__ import annotations

import json
import textwrap
import unittest

from . import static_scan as scan
from .support import CONFIG


def policy_numbers() -> frozenset:
    values: set = set()

    def walk(node):
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            values.add(node)
        elif isinstance(node, str):
            try:
                values.add(int(node))
            except ValueError:
                pass

    walk(json.loads((CONFIG / "oddspapi_slice1_policy.json").read_text(encoding="utf-8")))
    return frozenset(values)


POLICY_VALUES = policy_numbers()


def flagged(source: str) -> list[str]:
    return scan.scan_frz10("m.py", textwrap.dedent(source), policy_values=POLICY_VALUES)


class Frz10Tests(unittest.TestCase):
    def test_real_package_has_no_forbidden_numeric_literals(self):
        self.assertIn(3600, POLICY_VALUES)
        self.assertIn(60, POLICY_VALUES)
        self.assertEqual(scan.scan_all(scan.scan_frz10, policy_values=POLICY_VALUES), [])

    def test_flags_time_call_arguments_and_timeout_keywords(self):
        for source in (
            "import time\ntime.sleep(5)\n",
            "def f(s):\n    s.settimeout(30)\n",
            "import socket\nsocket.setdefaulttimeout(20)\n",
            "from datetime import timedelta\nx = timedelta(7)\n",
            "def f(c):\n    return c(timeout=60)\n",
            "def f(c):\n    return c(retry_backoff=2)\n",
            "def f(q):\n    q.wait(9)\n",
        ):
            self.assertTrue(flagged(source), source)

    def test_flags_names_that_read_like_bounds_and_defaults(self):
        for source in (
            "PRICE_TTL_SECONDS = 3600\n",
            "class C:\n    max_retries = 3\n",
            "def f(timeout_seconds=30):\n    return timeout_seconds\n",
            "def f(*, skew_tolerance=5):\n    return skew_tolerance\n",
            "x: int = 0\nrequest_timeout = 15\n",
        ):
            self.assertTrue(flagged(source), source)

    def test_flags_literals_equal_to_a_large_policy_value_anywhere(self):
        for value in (3600, 86400, 2592000, 8388608, 300, 120, 900, 65536, 256, 1000, 60):
            self.assertTrue(flagged(f"def f(x):\n    return x + {value}\n"), value)
        self.assertTrue(flagged("def f(x):\n    return x > 120.0\n"))

    def test_accepts_structural_literals(self):
        clean = """
            from datetime import timedelta
            def f(text, items, policy):
                head = text[:16]
                first = items[0]
                for i in range(3):
                    pass
                window = timedelta(seconds=policy.price_ttl_seconds)
                pad = "x" * 8
                flag = len(items) == 1
                return head, first, window, pad, flag, -1
        """
        self.assertEqual(flagged(clean), [])

    def test_slice_policy_names_are_the_only_source_of_provisional_numbers(self):
        from genesis_adapters import config as cfg
        import dataclasses
        names = {f.name for f in dataclasses.fields(cfg.SlicePolicy)}
        for required in ("request_timeout_seconds", "price_ttl_seconds", "prematch_guard_seconds",
                         "clock_skew_max_seconds", "provider_future_tolerance_seconds",
                         "wall_monotonic_drift_max_ms", "max_response_bytes", "odds_min", "odds_max"):
            self.assertIn(required, names)


if __name__ == "__main__":
    unittest.main()
