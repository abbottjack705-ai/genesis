"""T6 F-1/E3: the research boundary holds through trusted teardown.

The earlier F-1 work fixed a real scan-cost/timeout problem (37c7ba5) but did
not close the trust-boundary flaw itself.  The broken assumption was:

    "The research function returned, therefore no research-controlled code can
     execute anymore."

That is false in CPython.  Research code can arrange to regain execution *after*
the callback returns and *after* the worker believes it has entered a trusted
housekeeping phase -- through a ``__del__``/finalizer, a generator ``close``/
``finally`` driven by garbage collection, or a dunder method (``__hash__``,
``__str__``) touched while the interpreter state is scanned, the result is
converted, or the artifact is serialized -- or by rebinding a trusted callable
that trusted teardown then invokes.  If enforcement is dormant during those
phases, that re-entrant research code can reach a forbidden sink (spawning a
process, loading native code) unprotected, and the later identity/module scan
cannot save us: a transient finalizer can perform the side effect and leave no
suspicious binding behind.

The invariant these tests pin is therefore the strong one:

    There must never be a period in which research-controlled Python execution
    remains possible while enforcement of forbidden operations is withdrawn.

Each program below deliberately attempts a forbidden operation (spawning a
process that would create a marker file) specifically during that post-research
transition.  Python cannot stop the finalizer/dunder/callback from *running*;
the boundary instead guarantees the forbidden operation is refused whenever it
runs.  The proof is structural and observable: the marker file must never exist.
Against the pre-fix worker these go RED (the marker appears); against the fixed
worker the marker never appears.
"""

from __future__ import annotations

import os
import sys
import unittest

from genesis.evaluation import ProtectedEvaluationError

from ._support import scratch_directory
from .test_astra_s5_process import build_fixture, request_for
from .test_astra_t3_protected_integrity import launch as launch_with_roots
from .test_astra_t3_protected_integrity import pin


_RUN = "import os\n"
_PREDICT = "def predict(frame):\n    return '0.5'\n"


def _spawn_marker_command(marker) -> str:
    """A shell command that creates ``marker`` only if os.system is allowed to run.

    Its presence afterwards is proof a process was spawned unprotected; its
    absence is proof the boundary held.
    """

    if os.name == "nt":
        return f'cmd /c echo ran> "{marker}"'
    return f"printf ran > '{marker}'"


def _program_source(kind: str, marker) -> str:
    call = f"os.system({_spawn_marker_command(marker)!r})"
    if kind == "finalizer_on_teardown":
        # __del__ runs when the object is collected during trusted cleanup.
        return _RUN + f"class _D:\n    def __del__(self):\n        {call}\n_keep = _D()\n" + _PREDICT
    if kind == "generator_close_on_teardown":
        # The generator's `finally` runs when GC closes it during cleanup.
        return _RUN + (
            "def _g():\n    try:\n        yield 1\n    finally:\n"
            f"        {call}\n_gen = _g()\nnext(_gen)\n"
        ) + _PREDICT
    if kind == "str_subclass_scan":
        # __hash__ runs when the post-execution scan hashes the module __file__.
        return _RUN + (
            "class _P(str):\n    def __hash__(self):\n"
            f"        {call}\n        return str.__hash__(self)\n"
            "__file__ = _P(__file__)\n"
        ) + _PREDICT
    if kind == "prediction_value_dispatch":
        # __str__ runs when the artifact is built from the returned value.
        return _RUN + (
            "class _V(str):\n    def __str__(self):\n"
            f"        {call}\n        return '0.5'\n"
            "def predict(frame):\n    return _V('0.5')\n"
        )
    if kind == "rebind_trusted_serializer":
        # A rebound trusted method runs when trusted serialization calls it.
        return _RUN + (
            "from genesis.protected import FrozenPredictionArtifact\n"
            "_orig = FrozenPredictionArtifact.to_dict\n"
            "def _to_dict(self):\n"
            f"    {call}\n    return _orig(self)\n"
            "FrozenPredictionArtifact.to_dict = _to_dict\n"
        ) + _PREDICT
    if kind == "armed_startfile":
        # os.startfile is a Windows process-creation primitive; it must be a
        # forbidden sink even while the research callback itself is executing.
        arguments = f'/c echo ran> "{marker}"'
        return _RUN + (
            "import time\n"
            "def predict(frame):\n"
            f"    os.startfile('cmd.exe', 'open', {arguments!r}, None, 0)\n"
            "    time.sleep(1)\n"
            "    return '0.5'\n"
        )
    if kind == "import_winapi_rejected":
        # _winapi.CreateProcess raises no audit event, so importing _winapi must
        # be refused outright rather than relied on being caught at the call.
        return _RUN + "import _winapi\n" + _PREDICT
    raise ValueError(kind)


def _run_vector(kind: str) -> tuple[bool, bool]:
    """Run one adversarial program; return (raised, marker_created)."""

    with scratch_directory() as root:
        fixture = build_fixture(root / "campaign", max_attempts=3)
        code = root / "code"
        code.mkdir()
        marker = root / "marker.txt"
        name = f"t6_f1_{kind}"
        source = code / f"{name}.py"
        source.write_text(_program_source(kind, marker), encoding="utf-8")
        program = pin(name, source)
        raised = False
        with launch_with_roots(fixture, code) as client:
            try:
                client.run(request_for(fixture, program, strategy_id=name), program)
            except ProtectedEvaluationError:
                raised = True
        return raised, marker.exists()


class T6ForbiddenSinkDuringTeardownTests(unittest.TestCase):
    """The forbidden operation must never occur, in any phase (the F-1 invariant)."""

    def _assert_boundary_held(self, kind: str) -> bool:
        raised, marker_created = _run_vector(kind)
        self.assertFalse(
            marker_created,
            f"{kind}: a forbidden process was spawned unprotected during teardown",
        )
        return raised

    def test_finalizer_cannot_spawn_during_cleanup(self):
        self._assert_boundary_held("finalizer_on_teardown")

    def test_generator_finally_cannot_spawn_during_cleanup(self):
        self._assert_boundary_held("generator_close_on_teardown")

    def test_str_subclass_cannot_spawn_during_scan(self):
        # Reached only during the post-execution scan, so this deterministically
        # fails the request in addition to being blocked.
        self.assertTrue(self._assert_boundary_held("str_subclass_scan"))

    def test_return_value_dispatch_cannot_spawn_during_artifact_build(self):
        self.assertTrue(self._assert_boundary_held("prediction_value_dispatch"))

    def test_rebound_trusted_method_cannot_spawn_during_serialization(self):
        self.assertTrue(self._assert_boundary_held("rebind_trusted_serializer"))

    @unittest.skipUnless(os.name == "nt", "os.startfile exists only on Windows")
    def test_startfile_is_a_forbidden_sink(self):
        self.assertTrue(self._assert_boundary_held("armed_startfile"))

    def test_winapi_import_is_refused(self):
        # _winapi has process-creation primitives with no audit event, so the
        # import itself must fail closed.
        self.assertTrue(self._assert_boundary_held("import_winapi_rejected"))


if __name__ == "__main__":
    unittest.main()
