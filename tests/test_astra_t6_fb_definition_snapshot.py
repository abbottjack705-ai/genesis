"""White-box E11 regressions for the trusted-definition snapshot, the permanent
audit-hook tier, and the pre-serialization verify.

These are reconciled from the parallel session's inert regression suite (the
authoritative repo's ``test_astra_t6_e11_defense_in_depth.py``), retained here
because they exercise the mechanisms this reconciliation adopted from that work:
``_TrustedDefinitionSnapshot`` (nested-definition integrity, safe against user
protocols), the permanent forbidden-import/native-sink denial, and
``_send(verify=...)``. They are adapted where this implementation is stronger:
the module-reachability policy is a positive ``_import_allowed`` check with a
*narrowed* Genesis surface (so a non-allowlisted ``genesis.*`` module is refused,
not admitted), and the parallel session's separate import-time export-inspection
mechanism was intentionally not adopted (subsumed by the post-exec capability
audit and the research-mode default-deny), so its test is dropped.

Every probe is inert: no payload, native load, process, or network operation.
"""
from __future__ import annotations

import io
import types
import unittest
from unittest.mock import patch

from genesis import protected_research_worker as worker


def fixture_snapshot():
    # A synthetic `genesis.*` module is inside the snapshot's defence-in-depth
    # scope, so its definitions are captured.
    module = types.ModuleType("genesis.audit_fixture")
    module.State = type("State", (), {
        "__module__": module.__name__, "flag": False,
        "settings": {"nested": ["original"]},
    })
    return module, worker._TrustedDefinitionSnapshot({module.__name__: module})


class ReachableModulePolicyTests(unittest.TestCase):
    def audit(self, module, names=frozenset()):
        worker._audit_capability(
            module, seen=set(), roots=(), program_module="audit_fixture",
            referenced_names=names,
        )

    def test_unlisted_module_object_is_rejected_without_importing_it(self):
        sentinel = types.ModuleType("audit_unlisted_sentinel")
        self.assertFalse(worker._import_allowed(sentinel.__name__))
        with self.assertRaisesRegex(ValueError, "reachable module capability"):
            self.audit(sentinel)

    def test_non_allowlisted_genesis_module_object_is_rejected(self):
        # Stronger than the parallel implementation: the Genesis surface is a
        # narrow positive allowlist, so a genesis.* module that is not one of the
        # permitted data modules is refused even though its root is `genesis`.
        sentinel = types.ModuleType("genesis.protected")
        self.assertFalse(worker._import_allowed(sentinel.__name__))
        with self.assertRaisesRegex(ValueError, "reachable module capability"):
            self.audit(sentinel)

    def test_nested_module_references_keep_the_policy(self):
        # An unlisted module reached several attribute hops out (through an
        # allowlisted module) is still refused: the referenced names propagate.
        outer = types.ModuleType("math")
        outer.child = types.ModuleType("json")
        outer.child.grandchild = types.ModuleType("audit_unlisted_sentinel")
        with self.assertRaisesRegex(ValueError, "reachable module capability"):
            self.audit(outer, frozenset({"child", "grandchild"}))

    def test_allowlisted_module_and_cycles_remain_supported(self):
        outer = types.ModuleType("math")
        outer.child = outer  # a cycle must not loop or falsely reject
        self.audit(outer, frozenset({"child"}))


class TrustedDefinitionSnapshotTests(unittest.TestCase):
    def test_snapshot_does_not_dispatch_metaclass_comparisons(self):
        comparisons = []
        class Meta(type):
            def __eq__(self, other):
                comparisons.append(other)
                return False
        value = Meta("Opaque", (), {})()
        worker._TrustedDefinitionSnapshot._capture(value, set())
        self.assertEqual(comparisons, [])

    def test_snapshot_does_not_dispatch_a_wrapped_mapping(self):
        calls = []
        class Mapping:
            def __getitem__(self, key):
                return None
            def items(self):
                calls.append("items")
                return ()
        worker._TrustedDefinitionSnapshot._capture(types.MappingProxyType(Mapping()), set())
        self.assertEqual(calls, [])

    def test_snapshot_reads_the_real_class_namespace_without_metaclass_properties(self):
        calls = []
        class Meta(type):
            @property
            def __dict__(self):
                calls.append("namespace")
                return {}
        value = Meta("Opaque", (), {})
        worker._TrustedDefinitionSnapshot._capture(value, set())
        self.assertEqual(calls, [])

    def test_snapshot_keeps_original_objects_alive_for_identity_checks(self):
        module, snapshot = fixture_snapshot()
        original = module.State.settings
        self.assertTrue(any(item is original for item in snapshot._retained))
        module.State.settings = {"nested": ["original"]}  # equal value, new object
        with self.assertRaises(worker.ResearchProcessContaminated):
            snapshot.require_clean()

    def test_exported_class_attribute_changes_are_detected(self):
        module, snapshot = fixture_snapshot()
        snapshot.require_clean()
        module.State.flag = True
        with self.assertRaises(worker.ResearchProcessContaminated):
            snapshot.require_clean()

    def test_nested_definition_container_changes_are_detected(self):
        module, snapshot = fixture_snapshot()
        module.State.settings["nested"].append("changed")
        with self.assertRaises(worker.ResearchProcessContaminated):
            snapshot.require_clean()

    def test_function_state_changes_are_detected(self):
        module = types.ModuleType("genesis.audit_fixture")
        def benign():
            return None
        benign.__module__ = module.__name__
        benign.marker = {"items": []}
        module.benign = benign
        snapshot = worker._TrustedDefinitionSnapshot({module.__name__: module})
        benign.marker["items"].append("changed")
        with self.assertRaises(worker.ResearchProcessContaminated):
            snapshot.require_clean()


class PermanentEnforcementTierTests(unittest.TestCase):
    def _hook(self):
        with patch.object(worker.sys, "addaudithook") as register:
            enter_module, enter_callback, leave = worker._install_runtime_audit_hook(())
        return register.call_args.args[0], enter_module, enter_callback, leave

    def test_control_and_nonallowlisted_imports_are_denied_in_every_phase(self):
        hook, enter_module, enter_callback, leave = self._hook()
        code = compile("pass", "<inert-test>", "exec")
        names = (*worker._CONTROL_MODULES, *worker._CONTROL_MODULE_NAMES, "base64", "hashlib")
        for phase in (lambda: enter_module(code), enter_callback, leave):
            phase()
            for name in names:
                with self.subTest(phase=phase, name=name):
                    with self.assertRaises(RuntimeError):
                        hook("import", (name,))

    def test_allowlisted_import_is_admitted_in_every_phase(self):
        hook, enter_module, enter_callback, leave = self._hook()
        code = compile("pass", "<inert-test>", "exec")
        for phase in (lambda: enter_module(code), enter_callback, leave):
            phase()
            for name in ("math", "json", "genesis.labels"):
                with self.subTest(phase=phase, name=name):
                    hook("import", (name,))  # must not raise

    def test_named_and_native_sink_events_remain_denied_in_every_phase(self):
        hook, _enter_module, enter_callback, leave = self._hook()
        for phase in (enter_callback, leave):
            phase()
            for event in ("os.system", "subprocess.Popen", "socket.__new__",
                          "sqlite3.enable_load_extension", "sqlite3.load_extension",
                          "ctypes.dlopen", "sys.addaudithook", "sys.settrace",
                          "_winapi.CreateProcess", "_posixsubprocess.fork_exec"):
                with self.subTest(event=event, phase=phase):
                    with self.assertRaises(RuntimeError):
                        hook(event, ())


class PreSerializationVerifyTests(unittest.TestCase):
    def test_serialization_effects_are_checked_before_any_bytes_are_written(self):
        module, snapshot = fixture_snapshot()
        stream = io.BytesIO()
        def encode(_value):
            module.State.flag = True  # a side effect during serialization
            return b'{}\n'
        with patch.object(worker, "canonical_json", encode):
            with self.assertRaises(worker.ResearchProcessContaminated):
                worker._send(stream, {}, verify=snapshot.require_clean)
        self.assertEqual(stream.getvalue(), b"")

    def test_clean_response_still_serializes(self):
        _, snapshot = fixture_snapshot()
        stream = io.BytesIO()
        worker._send(stream, {"status": "ok"}, verify=snapshot.require_clean)
        self.assertEqual(stream.getvalue(), b'{"status":"ok"}\n')


if __name__ == "__main__":
    unittest.main()
