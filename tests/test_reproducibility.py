from __future__ import annotations

import unittest
from pathlib import Path

from genesis.repro import canonical_json, sha256_file, tree_digest
from ._support import scratch_directory


class ReproducibilityTests(unittest.TestCase):
    def test_canonical_json_and_tree_digest_are_order_independent(self):
        self.assertEqual(canonical_json({"b": 2, "a": 1}), canonical_json({"a": 1, "b": 2}))
        with scratch_directory() as root:
            (root / "b.txt").write_text("b")
            (root / "a.txt").write_text("a")
            first = tree_digest(root)
            self.assertEqual(first, tree_digest(root))
            self.assertEqual(sha256_file(root / "a.txt"), tree_digest(root / "a.txt"))
            (root / "a.txt").write_text("changed")
            self.assertNotEqual(first, tree_digest(root))
