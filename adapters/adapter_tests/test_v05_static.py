"""FRZ-05..08 and FRZ-11: AST scanners over the adapter package (and over planted code)."""

from __future__ import annotations

import textwrap
import unittest

from . import static_scan as scan


def clean(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


class Frz05Tests(unittest.TestCase):
    def test_real_package_is_clean(self):
        self.assertEqual(scan.scan_all(scan.scan_frz05), [])

    def test_flags_planted_violations(self):
        cases = {
            "private import": "from genesis.quota import _validated_state\n",
            "assignment": "import genesis.quota as q\nq.QuotaLedger.request = None\n",
            "setattr": "from genesis import quota\nsetattr(quota, 'x', 1)\n",
            "subclass override": clean("""
                from genesis.quota import QuotaLedger
                class Mine(QuotaLedger):
                    def request(self, **kw):
                        return None
            """),
            "private attribute": "def f(x):\n    return x._secret\n",
            "getattr private": "def f(x):\n    return getattr(x, '_hidden')\n",
        }
        for label, source in cases.items():
            self.assertTrue(scan.scan_frz05("m.py", source), label)

    def test_accepts_public_use(self):
        source = clean("""
            from genesis.quota import QuotaLedger
            from genesis.repro import canonical_json
            class Holder:
                def __init__(self):
                    self._x = 1
                def get(self):
                    return self._x
        """)
        self.assertEqual(scan.scan_frz05("m.py", source), [])


class Frz06Tests(unittest.TestCase):
    def test_real_package_is_clean(self):
        self.assertEqual(scan.scan_all(scan.scan_frz06), [])

    def test_network_imports_only_in_transport(self):
        for statement in ("import socket", "import ssl", "import http.client",
                          "from http import client", "import urllib.request",
                          "from urllib import request", "import requests", "import httpx",
                          "import aiohttp", "from ssl import create_default_context"):
            self.assertTrue(scan.scan_frz06("oddspapi/parser.py", statement + "\n"), statement)
            self.assertEqual(scan.scan_frz06("oddspapi/transport_http.py", statement + "\n"), [], statement)

    def test_non_network_urllib_parse_is_allowed(self):
        self.assertEqual(scan.scan_frz06("oddspapi/parser.py", "import urllib.parse\n"), [])

    def test_reveal_only_in_transport(self):
        source = "def f(s, t):\n    return s.reveal_for_transport(t)\n"
        self.assertTrue(scan.scan_frz06("oddspapi/acquisition.py", source))
        self.assertEqual(scan.scan_frz06("oddspapi/transport_http.py", source), [])


class Frz07Tests(unittest.TestCase):
    def test_real_package_is_clean(self):
        self.assertEqual(scan.scan_all(scan.scan_frz07), [])

    def test_flags_reserve_authority(self):
        for source in ("from genesis.quota import QuotaReserveAuthorization\n",
                       "def f(l):\n    l.grant_authorization(1)\n",
                       "def f(l):\n    l.revoke_authorization(1)\n",
                       "from genesis.quota import BudgetClass\nX = BudgetClass.RESERVE\n"):
            self.assertTrue(scan.scan_frz07("m.py", source), source)
        self.assertEqual(scan.scan_frz07("m.py", "from genesis.quota import BudgetClass\n"
                                                 "X = BudgetClass.NORMAL\n"), [])


class Frz08Tests(unittest.TestCase):
    def test_real_package_is_clean(self):
        self.assertEqual(scan.scan_all(scan.scan_frz08), [])

    def test_flags_test_only_names_and_ready(self):
        for source in ("class FixedClock:\n    pass\n", "class FakeTransport:\n    pass\n",
                       "from adapter_tests.support import FixedClock\n",
                       "from pit import OperationalStatus\nX = OperationalStatus.READY\n",
                       "from pit import OperationalStatus\nX = OperationalStatus('ready')\n"):
            self.assertTrue(scan.scan_frz08("oddspapi/acquisition.py", source), source)

    def test_ready_is_allowed_only_in_the_operator_cli(self):
        source = "from genesis.pit import OperationalStatus\nX = OperationalStatus.READY\n"
        self.assertEqual(scan.scan_frz08("cli.py", source), [])
        self.assertTrue(scan.scan_frz08("oddspapi/emit.py", source))


class Frz11Tests(unittest.TestCase):
    def test_real_package_is_clean(self):
        self.assertEqual(scan.scan_all(scan.scan_frz11), [])

    def test_flags_process_control_handlers(self):
        cases = {
            "bare": "try:\n    f()\nexcept:\n    pass\n",
            "base": "try:\n    f()\nexcept BaseException:\n    pass\n",
            "kbd": "try:\n    f()\nexcept KeyboardInterrupt:\n    pass\n",
            "exit": "try:\n    f()\nexcept SystemExit:\n    pass\n",
            "tuple": "try:\n    f()\nexcept (ValueError, SystemExit):\n    pass\n",
            "suppress": "import contextlib\nwith contextlib.suppress(KeyboardInterrupt):\n    f()\n",
            "suppress2": "from contextlib import suppress\nwith suppress(BaseException):\n    f()\n",
            "return in finally": "def g():\n    try:\n        f()\n    finally:\n        return 1\n",
            "break in finally": "def g():\n    for _ in x:\n        try:\n            f()\n        finally:\n            break\n",
        }
        for label, source in cases.items():
            self.assertTrue(scan.scan_frz11("oddspapi/acquisition.py", source), label)

    def test_except_exception_and_plain_finally_are_fine(self):
        source = clean("""
            def g():
                try:
                    f()
                except Exception:
                    return None
                finally:
                    cleanup()
        """)
        self.assertEqual(scan.scan_frz11("oddspapi/acquisition.py", source), [])

    def test_the_one_transport_clause_must_reraise_after_the_block(self):
        good = clean("""
            def send():
                try:
                    work()
                except Exception:
                    outcome = 1
                except BaseException as exc:
                    code = 2
                    del exc
                if code:
                    raise SystemExit(code) from None
                return outcome
        """)
        self.assertEqual(scan.scan_frz11("oddspapi/transport_http.py", good), [])
        no_reraise = good.replace("    if code:\n        raise SystemExit(code) from None\n", "")
        self.assertTrue(scan.scan_frz11("oddspapi/transport_http.py", no_reraise))
        returning = good.replace("        code = 2\n", "        code = 2\n        return None\n")
        self.assertTrue(scan.scan_frz11("oddspapi/transport_http.py", returning))
        # ...and the same clause anywhere else is forbidden
        self.assertTrue(scan.scan_frz11("oddspapi/acquisition.py", good))


if __name__ == "__main__":
    unittest.main()
