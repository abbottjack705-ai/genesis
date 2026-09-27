"""T6 F-B / ADR-0004: the outer OS confinement is correctly specified and stays
disabled.

E11 requires the real research boundary to be an OS-level confinement, not the
in-process CPython audit hook. ADR-0004 specifies that boundary and this tranche
ships it as a *disabled* scaffold (`genesis.protected_isolation`). These tests
pin three things without activating anything:

* the confinement policy encodes ADR-0004's four properties (explicit filesystem
  access, no network, no escaping child processes, fail-closed teardown) and
  refuses to relax the security-fixed ones;
* real activation is fail-closed: `apply_confinement` refuses regardless of any
  token, so this change cannot turn OS confinement on;
* ADR-0003's real-activation guard on the launcher is preserved.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genesis.protected_isolation import (
    ACTIVATION_ENABLED,
    ResearchConfinementNotActivated,
    ResearchProcessConfinement,
    apply_confinement,
    plan_confinement,
)


class ADR0004ConfinementPolicyTests(unittest.TestCase):
    def _confinement(self, **overrides):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            imports = root / "code"
            workdir = root / "research"
            labels = root / "labels"
            for path in (imports, workdir, labels):
                path.mkdir()
            kwargs = {
                "program_import_roots": (imports,),
                "research_workdir": workdir,
                "denied_label_roots": (labels,),
            }
            kwargs.update(overrides)
            return ResearchProcessConfinement(**kwargs)

    def test_policy_defaults_deny_network_and_children_and_kill_on_teardown(self):
        confinement = self._confinement()
        self.assertFalse(confinement.allow_network)
        self.assertFalse(confinement.allow_child_processes)
        self.assertTrue(confinement.kill_on_teardown)

    def test_policy_refuses_to_grant_network(self):
        with self.assertRaises(ValueError):
            self._confinement(allow_network=True)

    def test_policy_refuses_to_grant_child_processes(self):
        with self.assertRaises(ValueError):
            self._confinement(allow_child_processes=True)

    def test_policy_refuses_to_disable_teardown_kill(self):
        with self.assertRaises(ValueError):
            self._confinement(kill_on_teardown=False)

    def test_policy_refuses_filesystem_grant_overlapping_a_label_root(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            labels = root / "labels"
            labels.mkdir()
            workdir = labels / "inside"  # overlaps a label root: must fail closed
            workdir.mkdir()
            with self.assertRaises(ValueError):
                ResearchProcessConfinement(
                    program_import_roots=(root / "code",),
                    research_workdir=workdir,
                    denied_label_roots=(labels,),
                )

    def test_plan_encodes_no_network_explicit_fs_no_children_kill_on_close(self):
        plan = plan_confinement(self._confinement())
        self.assertEqual(plan["network_capabilities_granted"], ())
        self.assertFalse(plan["network_reachable"])
        self.assertTrue(plan["filesystem_grants"]["read_execute"])
        self.assertTrue(plan["filesystem_grants"]["read_write"])
        self.assertTrue(plan["filesystem_denied_roots"])
        self.assertEqual(plan["job_object"]["active_process_limit"], 1)
        self.assertFalse(plan["job_object"]["breakaway_ok"])
        self.assertFalse(plan["job_object"]["silent_breakaway_ok"])
        self.assertTrue(plan["job_object"]["kill_on_job_close"])


class ADR0004ActivationDisabledTests(unittest.TestCase):
    def test_activation_flag_is_off(self):
        self.assertFalse(ACTIVATION_ENABLED)

    def test_apply_confinement_is_fail_closed_regardless_of_token(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            (root / "code").mkdir()
            (root / "research").mkdir()
            confinement = ResearchProcessConfinement(
                program_import_roots=(root / "code",),
                research_workdir=root / "research",
            )
            for token in (None, True, "approved", object()):
                with self.subTest(token=repr(token)):
                    with self.assertRaises(ResearchConfinementNotActivated):
                        apply_confinement(confinement, approval_token=token)


class ADR0003ActivationGuardPreservedTests(unittest.TestCase):
    def test_real_activation_still_refused_by_launcher(self):
        # ADR-0003's guard is unchanged: a non-test launch is refused before any
        # process starts. (Full arguments are unnecessary; the guard fires first.)
        from genesis.protected import launch_trusted_protected_evaluator
        from genesis.registry import RegistryConflict

        with self.assertRaises(RegistryConflict):
            launch_trusted_protected_evaluator(
                campaign=None,
                sealed_frames=None,
                labels=(),
                campaigns=None,
                experiments=None,
                attempts=None,
                family_limit=1,
                local_checkpoint_test_only=False,
            )


if __name__ == "__main__":
    unittest.main()
