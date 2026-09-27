"""E10: test runtime leaves no residue, and a cleanup failure is never silent.

Invariant: ``scratch_directory`` removes its whole tree when the test ends,
including read-only files such as a nested Git repository's objects, and
every external directory attached to it (the S5 label roots live outside the
repository by design). If anything cannot be removed, the cleanup raises
instead of reporting success, so ``work/test_runtime`` and the system temp
directory stay empty after a green run.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import _support
from ._support import scratch_directory
from .test_astra_s5_process import build_fixture


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class T6E10RuntimeCleanupTests(unittest.TestCase):
    def test_e10_read_only_git_objects_and_files_are_removed(self):
        if shutil.which("git") is None:
            self.skipTest("git is unavailable")
        with scratch_directory() as root:
            repo = root / "repo"
            repo.mkdir()
            git("init", "-q", cwd=repo)
            (repo / "file.txt").write_text("x", encoding="utf-8")
            git("add", "file.txt", cwd=repo)
            git("-c", "user.name=e10", "-c", "user.email=e10@local", "commit", "-q", "-m", "x",
                cwd=repo)
            objects = [path for path in (repo / ".git" / "objects").rglob("*") if path.is_file()]
            self.assertTrue(objects)
            locked = root / "read-only" / "nested"
            locked.mkdir(parents=True)
            (locked / "file").write_text("x", encoding="utf-8")
            os.chmod(locked / "file", stat.S_IREAD)
            os.chmod(root / "read-only", stat.S_IREAD | stat.S_IEXEC)
        self.assertFalse(root.exists(), "E10: scratch tree left residue")

    def test_e10_attached_external_directories_die_with_their_scratch(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            label_root = fixture["label_root"]
            self.assertTrue(label_root.exists())
            self.assertFalse(label_root.is_relative_to(root))
            external = Path(tempfile.mkdtemp(prefix="genesis-e10-"))
            _support.attach_to_scratch(root / "sub", external)
            os.chmod(label_root / "raw-label.secret", stat.S_IREAD)
        self.assertFalse(root.exists())
        self.assertFalse(label_root.exists(), "E10: S5 label root outlived its test")
        self.assertFalse(external.exists())

    @unittest.skipUnless(os.name == "nt", "only Windows refuses to delete an open file")
    def test_e10_a_tree_that_cannot_be_removed_is_reported_not_ignored(self):
        with scratch_directory() as root:
            held = root / "held"
            held.mkdir()
            handle = open(held / "open.txt", "w", encoding="utf-8")
            try:
                with self.assertRaises(RuntimeError):
                    _support.remove_tree(held, attempts=2)
                self.assertTrue(held.exists())
            finally:
                handle.close()
            _support.remove_tree(held)
            self.assertFalse(held.exists())


if __name__ == "__main__":
    unittest.main()
