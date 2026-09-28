"""Suite-level FRZ-09 and FRZ-03, run last (module name sorts after every other test module)."""

from __future__ import annotations

import importlib
import sys
import unittest

from genesis_adapters import provenance_guard as guard
from genesis_adapters.oddspapi import verify

from . import NON_LOOPBACK_ATTEMPTS
from .support import CONFIG, REPO


PUBLIC_MODULES = ("time", "repro", "registry", "provenance", "evidence", "pit", "feature_manifest",
                  "quota", "coverage", "reasons", "logging", "canonical", "capabilities",
                  "evidence_pack")


class FinalProvenanceTests(unittest.TestCase):
    def test_frz09_every_loaded_genesis_module_matches_the_frozen_manifest(self):
        for name in PUBLIC_MODULES:            # the public modules the adapters consume
            importlib.import_module(f"genesis.{name}")
        verdict = guard.verify_loaded_genesis_modules(
            REPO, manifest_path=CONFIG / "frozen_genesis_modules.json",
            expected_manifest_sha256=verify.FROZEN_MANIFEST_SHA256)
        self.assertEqual(verdict["verdict"], "PASS")
        loaded = [name for name in sys.modules
                  if name == "genesis" or name.startswith("genesis.")]
        self.assertEqual(sorted(m["name"] for m in verdict["modules"]), sorted(loaded))
        self.assertIn("genesis", loaded)

    def test_frz03_frozen_worktree_is_clean_after_the_suite(self):
        verify.verify_frozen_worktree_clean(REPO)
        verify.verify_frozen_trees(REPO, "HEAD")

    def test_no_test_contacted_a_non_loopback_address(self):
        self.assertEqual(NON_LOOPBACK_ATTEMPTS, [])


if __name__ == "__main__":
    unittest.main()
