"""E6: audit package identity is bound to the named Git objects themselves.

Invariant: every Git read of the audit package tool names the object with
that ID, never a repository-local replacement (``refs/replace``): a replaced
commit is never packaged or verified as ``git_bound``, a repository whose
ordinary Git view substitutes objects (a replace ref or a grafts file) is
refused, and each packaged Git blob's bytes must hash to its object ID. This
binds evidence to the object database's content; it does not claim more than
the same-user trust boundary of the local repository.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import unittest
import zlib
from pathlib import Path

from . import test_astra_t4_evidence_package as t4_package
from ._support import scratch_directory
from .test_astra_t4_evidence_package import TOOL, command


def git(repo: Path, *args: str) -> str:
    result = command("git", *args, cwd=repo)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def tool_module():
    spec = importlib.util.spec_from_file_location("genesis_audit_package_e6", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class T6E6ReplaceObjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.t4 = t4_package.AstraT4EvidencePackageTests()

    def replace_commit(self, fixture: dict) -> str:
        """Map the fixture commit to one with other content; return the replacement."""

        repo, commit = fixture["repo"], fixture["commit"]
        git(repo, "-c", "advice.detachedHead=false", "checkout", "-q", commit)
        (repo / "source" / "program.py").write_bytes(b"VALUE = 2\r\n")
        git(repo, "commit", "-q", "-am", "replacement")
        replacement = git(repo, "rev-parse", "HEAD")
        git(repo, "replace", commit, replacement)
        return replacement

    def run_tool(self, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return command(sys.executable, str(TOOL), *args, cwd=cwd)

    def test_e6_a_replaced_commit_is_never_packaged(self):
        with scratch_directory() as root:
            fixture = self.t4.fixture(root)
            self.replace_commit(fixture)
            repo, commit = fixture["repo"], fixture["commit"]
            for label, checkout in (
                ("replacement content checked out", ("checkout", "-q", "-f", commit)),
                ("true content checked out", ("--no-replace-objects", "checkout", "-q", "-f", commit)),
            ):
                with self.subTest(label):
                    git(repo, "-c", "advice.detachedHead=false", *checkout)
                    output = root / f"{len(label)}.zip"
                    result = self.run_tool(
                        "build", "--repo", str(repo), "--commit", commit,
                        "--output", str(output), cwd=root,
                    )
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertFalse(output.exists())
            self.assertIn("refs/replace", result.stderr)

    def test_e6_a_repository_with_replacements_never_verifies_git_bound(self):
        with scratch_directory() as root:
            fixture = self.t4.fixture(root)
            archive = root / "package.zip"
            self.t4.build(fixture, archive)
            repo, commit = fixture["repo"], fixture["commit"]
            verify = ("verify", "--archive", str(archive), "--repo", str(repo),
                      "--expect-commit", commit)
            clean = self.run_tool(*verify, cwd=root)
            self.assertEqual(clean.returncode, 0, clean.stderr)
            self.assertEqual(json.loads(clean.stdout)["trust_mode"], "git_bound")
            self.replace_commit(fixture)
            replaced = self.run_tool(*verify, cwd=root)
            self.assertNotEqual(replaced.returncode, 0, replaced.stdout)
            self.assertIn("refs/replace", replaced.stderr)
            git(repo, "replace", "-d", commit)
            restored = self.run_tool(*verify, cwd=root)
            self.assertEqual(restored.returncode, 0, restored.stderr)

    def test_e6_git_reads_name_the_object_not_its_replacement(self):
        with scratch_directory() as root:
            fixture = self.t4.fixture(root)
            replacement = self.replace_commit(fixture)
            repo, commit = fixture["repo"], fixture["commit"]
            self.assertEqual(git(repo, "rev-parse", f"{commit}^{{tree}}"),
                             git(repo, "rev-parse", f"{replacement}^{{tree}}"))
            module = tool_module()
            self.assertEqual(
                module._git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip(),
                fixture["tree"],
            )

    def test_e6_git_bound_blob_bytes_must_hash_to_their_object_id(self):
        with scratch_directory() as root:
            fixture = self.t4.fixture(root)
            archive = root / "package.zip"
            self.t4.build(fixture, archive)
            repo, commit = fixture["repo"], fixture["commit"]
            oid = git(repo, "rev-parse", f"{commit}:source/program.py")
            loose = repo / ".git" / "objects" / oid[:2] / oid[2:]
            self.assertTrue(loose.is_file())
            # The object database now returns other bytes under the same ID.
            other = b"VALUE = 3\r\n"
            header = b"blob %d\x00" % len(other)
            os.chmod(loose, stat.S_IREAD | stat.S_IWRITE)
            loose.write_bytes(zlib.compress(header + other))
            self.assertEqual(
                subprocess.check_output(["git", "-C", str(repo), "cat-file", "blob", oid]), other,
            )
            self.assertNotEqual(hashlib.sha1(header + other).hexdigest(), oid)
            result = self.run_tool(
                "verify", "--archive", str(archive), "--repo", str(repo),
                "--expect-commit", commit, cwd=root,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("do not hash to their object ID", result.stderr)


if __name__ == "__main__":
    unittest.main()
