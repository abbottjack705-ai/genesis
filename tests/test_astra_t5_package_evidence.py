"""T5 evidence path: verification proves the intended package, not only itself.

Invariant: a verifier can pin every fact an auditor needs from outside the
package - target commit, approved authorities, required raw-evidence roots and
exact historical artifacts - and the package cannot hide a conflicting value
behind duplicate JSON keys or omit members while staying self-consistent.
(Hostile re-audit observations O-1, O-2 and O-3; R-3 remains a limit: a
package is authentic only against an out-of-band package hash.)
"""

from __future__ import annotations

import json
import subprocess
import unittest
import zipfile
from pathlib import Path

from . import test_astra_t4_evidence_package as t4_package
from ._support import scratch_directory
from .test_astra_t4_evidence_package import MANIFEST_NAME, command, sha256


class T5PackageEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        # Reuse the T4 fixture/builder helpers without re-collecting T4 tests.
        self.t4 = t4_package.AstraT4EvidencePackageTests()

    def fixture(self, root: Path) -> dict:
        return self.t4.fixture(root)

    def build(self, fixture: dict, output: Path) -> dict:
        return self.t4.build(fixture, output)

    def verify(self, archive: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.t4.verify(archive, *extra)

    def resign(self, archive: Path, members: dict[str, bytes], output: Path) -> None:
        with zipfile.ZipFile(output, "x") as changed:
            for name, raw in members.items():
                changed.writestr(name, raw)
        Path(str(output) + ".sha256").write_text(
            f"{sha256(output.read_bytes())}  {output.name}\n", encoding="ascii",
        )

    def members(self, archive: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(archive) as source:
            return {info.filename: source.read(info.filename) for info in source.infolist()}

    def test_t5_expected_commit_pin_rejects_a_valid_package_for_another_commit(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)
            repo = fixture["repo"]
            (repo / "source" / "program.py").write_bytes(b"VALUE = 2\r\n")
            for args in (("git", "add", "."), ("git", "commit", "-q", "-m", "next")):
                self.assertEqual(command(*args, cwd=repo).returncode, 0)
            later = command("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
            accepted = self.verify(archive, "--expect-commit", fixture["commit"])
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            denied = self.verify(archive, "--repo", str(repo), "--expect-commit", later)
            self.assertNotEqual(denied.returncode, 0, "O-1: package for another commit verified")
            self.assertIn("commit", denied.stderr)

    def test_t5_duplicate_manifest_keys_are_rejected(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)
            members = self.members(archive)
            raw = members[MANIFEST_NAME].decode("utf-8")
            assert raw.startswith("{\n")
            decoy = '{\n  "target": {"commit": "' + "0" * 40 + '", "tree": "' + "0" * 40 + '"},\n'
            members[MANIFEST_NAME] = (decoy + raw[2:]).encode("utf-8")
            forged = root / "duplicate-keys.zip"
            self.resign(archive, members, forged)
            denied = self.verify(forged)
            self.assertNotEqual(denied.returncode, 0, "O-2: duplicate manifest keys verified")
            self.assertIn("duplicate", denied.stderr)

    def test_t5_omitted_raw_member_and_row_is_rejected(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)
            members = self.members(archive)
            manifest = json.loads(members[MANIFEST_NAME])
            dropped = "raw-worktree/evidence/raw.txt"
            manifest["members"] = [row for row in manifest["members"] if row["archive_path"] != dropped]
            members.pop(dropped)
            members[MANIFEST_NAME] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
            forged = root / "omitted-raw.zip"
            self.resign(archive, members, forged)
            for extra in ((), ("--repo", str(fixture["repo"]))):
                denied = self.verify(forged, *extra)
                self.assertNotEqual(
                    denied.returncode, 0, f"O-3: omitted raw evidence verified {extra}",
                )

    def test_t5_required_raw_root_and_historical_pins_reject_substitution(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)
            original = sha256(fixture["historical"].read_bytes())
            pins = ("--require-raw-root", "evidence",
                    "--require-historical", f"original-s5.zip={original}")
            accepted = self.verify(archive, *pins)
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)

            members = self.members(archive)
            manifest = json.loads(members[MANIFEST_NAME])
            replacement = b"substituted historical bytes"
            for row in manifest["members"]:
                if row["archive_path"] == "historical/original-s5.zip":
                    row["bytes"] = len(replacement)
                    row["sha256"] = sha256(replacement)
            members["historical/original-s5.zip"] = replacement
            members[MANIFEST_NAME] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
            substituted = root / "substituted.zip"
            self.resign(archive, members, substituted)
            denied = self.verify(substituted, "--repo", str(fixture["repo"]), *pins)
            self.assertNotEqual(denied.returncode, 0, "O-3: substituted historical artifact verified")


if __name__ == "__main__":
    unittest.main()
