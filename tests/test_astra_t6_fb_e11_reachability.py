"""T6 F-B (E11 re-audit of the F-A allowlist): three confirmed correctness findings.

The F-A remediation converted research *imports* to a fail-closed allowlist. An
independent E11 re-audit confirmed three residual correctness defects, each with
an inert reproduction. These tests pin the class-level invariant for each; every
probe is inert (no process is spawned, no native code is loaded, no network is
touched, and no raw label is used).

Finding 1 -- indirect capability reachability.
    The allowlist gated import *statements*, not object reachability. A native
    process-creation capability (``_winapi.CreateProcess``) stays reachable by
    pure attribute traversal from an allowlisted package
    (``genesis.protected.multiprocessing.reduction._winapi``); allowlisted stdlib
    modules likewise leak references to non-allowlisted modules (``collections._sys``,
    ``enum.bltns``). Capability validation must apply the positive policy to
    indirectly reachable module/native capabilities, not only to direct imports.
    RED (pre-fix): the reachability program certifies. GREEN: it fails closed.

Finding 2 -- enforcement must not depend on lifecycle mode.
    Forbidden-event enforcement was already permanent, but *import* enforcement
    (and native-capability denial) was gated on a research ``mode`` being active,
    so it lapsed during conversion/cleanup/shutdown (``mode`` is None) -- exactly
    the re-entrant window a finalizer or dunder exploits. Permanent
    forbidden-event/import enforcement must remain active in every phase.
    RED (pre-fix): the installed hook admits a forbidden import / native event
    while ``mode`` is None. GREEN: it refuses them in every phase. (White-box and
    inert: it drives the audit hook with ``sys.audit`` and never imports or spawns.)

Finding 3 -- contamination must cover mutable nested trusted state.
    ``require_clean`` snapshotted trusted module namespaces only at the top level
    by object identity, so an in-place mutation of a trusted authority *type*
    reachable by research (adding/rebinding a member of ``FutureOutcomeLabel`` or
    ``DecisionFrame``) left the top-level identity unchanged and went undetected,
    persisting into the next request in the reused worker. Contamination checking
    must cover mutable security-relevant nested state via explicit
    integrity-checked authority objects.
    RED (pre-fix): the mutation certifies. GREEN: it is detected and fails closed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from genesis.evaluation import ProtectedEvaluationError

from ._support import scratch_directory
from .test_astra_s5_process import build_fixture, request_for
from .test_astra_t3_protected_integrity import launch as launch_with_roots
from .test_astra_t3_protected_integrity import pin


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
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


class Finding1IndirectReachabilityTests(unittest.TestCase):
    """A native/process capability reachable only by attribute traversal must
    fail closed, even though no ``import`` statement names it."""

    def test_winapi_createprocess_via_attribute_chain_fails_closed(self):
        # `import genesis.labels` is allowlisted and binds the `genesis` package;
        # the worker itself has loaded `genesis.protected`, so the native process
        # loader is reachable purely by attribute read. The probe only *reads* the
        # attribute (it never calls it) so the test is inert; the boundary must
        # still refuse to certify a program that has obtained the capability.
        source = (
            "import genesis.labels\n"
            "def predict(frame):\n"
            "    sink = genesis.protected.multiprocessing.reduction._winapi.CreateProcess\n"
            "    return '0.5' if sink is None else '0.9'\n"
        )
        status, detail = _run_source(source, name="fb_winapi_attr_chain")
        self.assertEqual(
            status, "blocked",
            f"Finding 1: native process capability reachable by attribute ({detail})",
        )

    def test_stdlib_module_leak_to_nonallowlisted_module_fails_closed(self):
        # `collections._sys` is the (non-allowlisted) `sys` module, reachable from
        # an allowlisted compute module purely by attribute. Binding it must fail
        # closed regardless of the sink not being named in an import.
        source = (
            "import collections\n"
            "def predict(frame):\n"
            "    leaked = collections._sys\n"
            "    return '0.5' if leaked is None else '0.9'\n"
        )
        status, detail = _run_source(source, name="fb_collections_sys_leak")
        self.assertEqual(
            status, "blocked",
            f"Finding 1: non-allowlisted module reachable by attribute leak ({detail})",
        )

    def test_unlisted_pure_submodule_reached_by_attribute_fails_closed(self):
        # Positive policy on reachable modules (reconciled from the parallel
        # remediation): a module reached by attribute must itself be import-
        # allowed. `os.path` is the (non-allowlisted) `ntpath`/`posixpath` module;
        # even though it is benign, reaching it must fail closed, so a future
        # capability-bearing submodule cannot slip through by omission.
        source = (
            "import os\n"
            "def predict(frame):\n"
            "    leaked = os.path\n"
            "    return '0.5' if leaked is None else '0.9'\n"
        )
        status, detail = _run_source(source, name="fb_os_path_submodule")
        self.assertEqual(
            status, "blocked",
            f"Finding 1: non-import-allowed reachable submodule admitted ({detail})",
        )

    def test_allowlisted_compute_still_certifies(self):
        # The reachability closure must not over-block ordinary compute that uses
        # allowlisted modules and their benign members.
        source = (
            "import math\n"
            "import statistics\n"
            "def predict(frame):\n"
            "    return '0.5' if math.sqrt(4.0) == 2.0 and statistics.mean([1.0, 3.0]) == 2.0 else '0.1'\n"
        )
        status, detail = _run_source(source, name="fb_allowed_compute")
        self.assertEqual(
            status, "certified",
            f"Finding 1 regression: allowlisted compute over-blocked ({detail})",
        )


_PERMANENCE_PROBE = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import genesis.protected_research_worker as worker

roots = (Path(sys.argv[2]).resolve(),)
enter_module, enter_callback, leave = worker._install_runtime_audit_hook(roots)

# Enter and then LEAVE research mode: `mode` is now None, exactly the trusted
# conversion/cleanup/shutdown window in which a finalizer or dunder can regain
# control. Enforcement of forbidden imports and native capabilities must remain
# active here, not depend on a research mode being set.
enter_callback()
leave()

results = {}

def _probe(label, event, args):
    try:
        sys.audit(event, *args)
        results[label] = "ADMITTED"
    except Exception:
        results[label] = "REFUSED"

# Inert: `sys.audit` fires the installed hook with these arguments; it performs
# no import and spawns nothing.
_probe("import_control_module", "import", ("ctypes", None, [], [], []))
_probe("import_nonallowlisted", "import", ("base64", None, [], [], []))
_probe("native_process_event", "_winapi.CreateProcess", ("cmd.exe", "", None, None, 0, 0, None, None, None))
_probe("import_allowlisted_ok", "import", ("math", None, [], [], []))

print(__import__("json").dumps(results))
"""


class Finding2EnforcementPermanenceTests(unittest.TestCase):
    """Forbidden-import and native-capability enforcement must hold while
    ``mode`` is None (conversion/cleanup/shutdown), not only during research."""

    def _run_probe(self) -> dict:
        with tempfile.TemporaryDirectory() as roots:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-c", _PERMANENCE_PROBE, str(SOURCE_ROOT), roots],
                capture_output=True, text=True, timeout=120, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_forbidden_import_refused_after_mode_cleared(self):
        observed = self._run_probe()
        self.assertEqual(
            observed["import_control_module"], "REFUSED",
            "Finding 2: control-module import admitted while mode is None",
        )
        self.assertEqual(
            observed["import_nonallowlisted"], "REFUSED",
            "Finding 2: non-allowlisted import admitted while mode is None",
        )

    def test_native_capability_event_refused_after_mode_cleared(self):
        observed = self._run_probe()
        self.assertEqual(
            observed["native_process_event"], "REFUSED",
            "Finding 2: native process-creation event admitted while mode is None",
        )

    def test_allowlisted_import_still_admitted(self):
        # The permanent import policy is a positive allowlist, not a blanket block:
        # an allowlisted module import is still admitted in every phase.
        observed = self._run_probe()
        self.assertEqual(
            observed["import_allowlisted_ok"], "ADMITTED",
            "Finding 2 regression: allowlisted import refused",
        )


class Finding3NestedContaminationTests(unittest.TestCase):
    """In-place mutation of a mutable trusted authority type reachable by
    research must be detected as contamination and fail closed."""

    def test_inplace_mutation_of_trusted_label_type_fails_closed(self):
        # Adds a benign member to the trusted `FutureOutcomeLabel` type (no raw
        # label instance, no sink). The top-level identity `genesis.labels.
        # FutureOutcomeLabel` is unchanged, so the shallow snapshot missed it; the
        # mutation would persist into the next request in the reused worker.
        source = (
            "from genesis.labels import FutureOutcomeLabel\n"
            "def predict(frame):\n"
            "    FutureOutcomeLabel.e11_nested_probe = 1\n"
            "    return '0.5'\n"
        )
        status, detail = _run_source(source, name="fb_nested_label_type_mutation")
        self.assertEqual(
            status, "blocked",
            f"Finding 3: in-place mutation of trusted label type undetected ({detail})",
        )

    def test_inplace_mutation_of_trusted_frame_type_fails_closed(self):
        source = (
            "from genesis.labels import DecisionFrame\n"
            "def predict(frame):\n"
            "    DecisionFrame.e11_nested_probe = 1\n"
            "    return '0.5'\n"
        )
        status, detail = _run_source(source, name="fb_nested_frame_type_mutation")
        self.assertEqual(
            status, "blocked",
            f"Finding 3: in-place mutation of trusted frame type undetected ({detail})",
        )

    def test_nested_container_mutation_in_trusted_type_fails_closed(self):
        # Broader nested-definition integrity (reconciled from the parallel
        # remediation): mutating a mutable container *nested* in a trusted type's
        # namespace (an enum's `_member_map_`) keeps the type's top-level identity,
        # so only a nested snapshot can see it. Inert (no sink, no label).
        source = (
            "import genesis.provenance\n"
            "def predict(frame):\n"
            "    genesis.provenance.AvailabilityClass._member_map_['e11'] = None\n"
            "    return '0.5'\n"
        )
        status, detail = _run_source(source, name="fb_nested_container_mutation")
        self.assertEqual(
            status, "blocked",
            f"Finding 3: nested container mutation of a trusted type undetected ({detail})",
        )

    def test_mutation_during_artifact_serialization_is_caught_before_send(self):
        # Pre-serialization verify (reconciled from the parallel remediation): the
        # returned value's __str__ runs while the artifact is built, AFTER the
        # post-callback scan. Without a check between serialization and emitting,
        # the contaminating artifact would be shipped and only the next request
        # poisoned. The pre-send verify must fail this request instead. Inert:
        # the side effect is a benign in-place mutation of a trusted type.
        source = (
            "from genesis.labels import DecisionFrame\n"
            "class _V(str):\n"
            "    def __str__(self):\n"
            "        DecisionFrame.e11_serialize_probe = 1\n"
            "        return '0.5'\n"
            "def predict(frame):\n"
            "    return _V('0.5')\n"
        )
        status, detail = _run_source(source, name="fb_serialize_time_mutation")
        self.assertEqual(
            status, "blocked",
            f"Finding 3: state mutated during serialization was shipped ({detail})",
        )

    def test_rebinding_enforcement_method_of_trusted_type_fails_closed(self):
        # Self-review variant: `pathlib.PurePath.is_relative_to` is dispatched by
        # the worker's OWN post-callback scan (`require_clean` -> `_inside`).
        # Rebinding it to always return False would subvert the checker while the
        # top-level `pathlib.PurePath` identity is unchanged. Inert (no sink, no
        # label): the rebind must be detected as contamination.
        source = (
            "import pathlib\n"
            "def predict(frame):\n"
            "    pathlib.PurePath.is_relative_to = lambda self, other: False\n"
            "    return '0.5'\n"
        )
        status, detail = _run_source(source, name="fb_rebind_enforcement_method")
        self.assertEqual(
            status, "blocked",
            f"Finding 3 variant: rebind of a trusted enforcement method undetected ({detail})",
        )

    def test_unmutated_reference_to_trusted_type_still_certifies(self):
        # Merely *referencing* a trusted type (without mutating it) must remain
        # fine. (Attribute reads of dunder names are separately forbidden, so the
        # reference is by identity only.)
        source = (
            "from genesis.labels import DecisionFrame\n"
            "def predict(frame):\n"
            "    return '0.5' if DecisionFrame is not None else '0.1'\n"
        )
        status, detail = _run_source(source, name="fb_trusted_type_readonly")
        self.assertEqual(
            status, "certified",
            f"Finding 3 regression: read-only trusted type reference over-blocked ({detail})",
        )


if __name__ == "__main__":
    unittest.main()
