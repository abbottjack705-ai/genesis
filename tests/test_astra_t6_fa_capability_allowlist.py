"""T6 F-A (reopens F-1/E3): the research worker admits only an allowlisted set of
trusted-runtime imports, and every capability-bearing route fails closed.

E11 confirmed that the worker's forbidden-sink enforcement was a *denylist*
(``_CONTROL_MODULES`` plus a fixed set of audit events), so any native/extension
module omitted from the enumeration stayed reachable. Two confirmed escapes:

* ``sqlite3`` -> ``Connection.enable_load_extension`` / ``load_extension`` loads
  arbitrary native code; its audit events were not denied.
* ``_tkinter`` -> a Tcl interpreter whose ``exec`` command spawns processes and
  raises *no* Python audit event at all.

The invariant these tests pin is the strong, class-level one:

    Research-controlled code must not be able, in any lifecycle phase, to obtain
    or invoke a capability that can create/control an OS process, load native
    code, access the network, escape the permitted data surface, or mutate the
    enforcement mechanism -- whether or not CPython emits an audit event.

The tests therefore assert a *positive* (allowlist) policy: an unenumerated
module -- even a perfectly benign one -- must fail closed, precisely so that a
future capability-bearing module cannot become reachable merely by having been
omitted from a denylist. They must not merely re-check the two known vectors.

Every probe is non-destructive: no vector loads native code or spawns a process
(the SQLite probe would only *enable* extension loading; against the fixed
worker the import is refused before that).

RED against the pre-fix (denylist) worker: the unenumerated modules certify.
GREEN against the fixed (allowlist) worker: all fail closed, while allowlisted
compute modules still certify.
"""
from __future__ import annotations

import unittest

from genesis.evaluation import ProtectedEvaluationError

from ._support import scratch_directory
from .test_astra_s5_process import build_fixture, request_for
from .test_astra_t3_protected_integrity import launch as launch_with_roots
from .test_astra_t3_protected_integrity import pin


_PREDICT = "def predict(frame):\n    return '0.5'\n"


def _run_source(source: str, *, name: str) -> tuple[str, str]:
    """Return ("certified"|"blocked", detail) for a research program source."""

    with scratch_directory() as root:
        fixture = build_fixture(root / "campaign", max_attempts=3)
        code = root / "code"
        code.mkdir()
        module = code / f"{name}.py"
        module.write_text(source, encoding="utf-8")
        program = pin(name, module)
        with launch_with_roots(fixture, code) as client:
            try:
                cert = client.run(
                    request_for(fixture, program, strategy_id=name), program
                )
            except ProtectedEvaluationError as exc:
                return "blocked", str(exc)
        return "certified", str(cert.metrics.get("brier"))


# Modules that grant, or transitively wrap, a boundary-crossing capability
# (process, native-code load, network) and have no legitimate research use.
# Includes the two confirmed E11 escapes plus a spread of others so the test
# is a class-level check, not a two-vector check.
_CAPABILITY_MODULES = (
    "sqlite3", "_sqlite3", "tkinter", "_tkinter", "socket", "ssl",
    "subprocess", "ctypes", "_ctypes", "multiprocessing", "asyncio",
    "mmap", "pickle", "marshal", "importlib", "sys", "gc", "inspect",
    "http.client", "urllib.request", "ftplib", "webbrowser", "threading",
    "_winapi",
)

# Benign modules with no known sink that are nonetheless NOT on the allowlist.
# They must still fail closed -- this is the proof the policy is a positive
# allowlist (default-deny), not a denylist of today's known-dangerous names.
_BENIGN_UNLISTED_MODULES = ("base64", "hashlib", "secrets", "uuid", "csv", "hmac")

# Allowlisted trusted-runtime compute modules a real predictor may legitimately
# use; these must keep certifying so the fix does not over-block research.
_ALLOWED_COMPUTE_PROGRAM = (
    "import math\n"
    "import decimal\n"
    "import statistics\n"
    "import json\n"
    "import random\n"
    "def predict(frame):\n"
    "    return '0.5'\n"
)


class T6CapabilityAllowlistTests(unittest.TestCase):
    def test_sqlite_native_extension_capability_fails_closed(self):
        # Pre-fix: enable_load_extension succeeds -> certifies (capability was
        # reachable). Post-fix: `import sqlite3` is refused before that.
        source = (
            "import sqlite3\n"
            "def predict(frame):\n"
            "    con = sqlite3.connect(':memory:')\n"
            "    con.enable_load_extension(True)\n"
            "    return '0.5'\n"
        )
        status, detail = _run_source(source, name="fa_sqlite_extension")
        self.assertEqual(
            status, "blocked",
            f"F-A: SQLite native-extension capability was reachable ({detail})",
        )

    def test_tcl_interpreter_capability_fails_closed(self):
        # Pre-fix: _tkinter builds a Tcl interpreter (whose `exec` spawns
        # processes with no audit event) -> certifies. Post-fix: import refused.
        source = (
            "import _tkinter\n"
            "def predict(frame):\n"
            "    interp = _tkinter.create(None, 'x', 'Tcl', 0, 0, 0, 0, None)\n"
            "    return '0.5'\n"
        )
        status, detail = _run_source(source, name="fa_tcl_interpreter")
        self.assertEqual(
            status, "blocked",
            f"F-A: Tcl-interpreter (process-creation) capability was reachable ({detail})",
        )

    def test_every_capability_module_fails_closed(self):
        for module in _CAPABILITY_MODULES:
            with self.subTest(module=module):
                status, detail = _run_source(
                    f"import {module}\n" + _PREDICT,
                    name=f"fa_cap_{module.replace('.', '_')}",
                )
                self.assertEqual(
                    status, "blocked",
                    f"F-A: capability module {module!r} was importable by research ({detail})",
                )

    def test_unenumerated_benign_module_also_fails_closed(self):
        # The invariant: default-deny. A module nobody thought to block must be
        # refused because it is not on the allowlist, not because it is on a
        # denylist. This is what makes a future dangerous module fail closed.
        for module in _BENIGN_UNLISTED_MODULES:
            with self.subTest(module=module):
                status, detail = _run_source(
                    f"import {module}\n" + _PREDICT,
                    name=f"fa_benign_{module}",
                )
                self.assertEqual(
                    status, "blocked",
                    f"F-A: unlisted module {module!r} was admitted (policy is not default-deny) ({detail})",
                )

    def test_allowlisted_compute_modules_still_certify(self):
        status, detail = _run_source(
            _ALLOWED_COMPUTE_PROGRAM, name="fa_allowed_compute",
        )
        self.assertEqual(
            status, "certified",
            f"F-A regression over-blocked legitimate compute imports ({detail})",
        )


if __name__ == "__main__":
    unittest.main()
