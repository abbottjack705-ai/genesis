"""T6 F-4: raw evidence bytes are bound to Git whenever Git is consulted.

Invariant: with ``--repo``, every raw-worktree member is byte-identical to the
Git blob of its source path at the target commit. No self-consistent rewrite of
raw evidence - its content or only its line endings - verifies against Git,
with or without caller pins, and the builder never emits a package whose raw
evidence differs from Git. Git-free verification is a separate, weaker trust
mode: it checks self-consistency and caller pins only, and its report says
that nothing was bound to Git (independent T5 review finding F-4).
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path

from . import test_astra_t4_evidence_package as t4_package
from ._support import scratch_directory
from .test_astra_t4_evidence_package import (
    MANIFEST_NAME, REPOSITORY_ROOT, TOOL, command, sha256,
)


RAW = "raw-worktree/evidence/raw.txt"
BLOB = "git-blobs/evidence/raw.txt"


class T6RawEvidenceGitBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        # Reuse the T4 fixture/builder helpers without re-collecting T4 tests.
        self.t4 = t4_package.AstraT4EvidencePackageTests()

    def pins(self, fixture: dict) -> tuple[str, ...]:
        historical = sha256(fixture["historical"].read_bytes())
        return (
            "--expect-commit", fixture["commit"],
            "--require-raw-root", "evidence",
            "--require-historical", f"original-s5.zip={historical}",
            "--authority", f"DECISIONS/ADR.md={fixture['adr_hash']}",
        )

    def forged(self, archive: Path, output: Path, change) -> Path:
        """Rewrite members and re-sign: manifest, ZIP and sidecar all agree."""

        with zipfile.ZipFile(archive) as source:
            members = {info.filename: source.read(info.filename) for info in source.infolist()}
        change(members)
        manifest = json.loads(members[MANIFEST_NAME])
        for row in manifest["members"]:
            raw = members[row["archive_path"]]
            row["bytes"], row["sha256"] = len(raw), sha256(raw)
        manifest["source_snapshot"] = [
            row for row in manifest["members"] if row["representation"] == "git_blob_bytes"
        ]
        members[MANIFEST_NAME] = (
            json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        with zipfile.ZipFile(output, "x") as changed:
            for name, raw in members.items():
                changed.writestr(name, raw)
        Path(str(output) + ".sha256").write_text(
            f"{sha256(output.read_bytes())}  {output.name}\n", encoding="ascii",
        )
        return output

    def test_t6_genuine_raw_evidence_equals_git_and_verifies_git_bound(self) -> None:
        with scratch_directory() as root:
            fixture = self.t4.fixture(root)
            archive = root / "package.zip"
            self.t4.build(fixture, archive)
            with zipfile.ZipFile(archive) as packaged:
                manifest = json.loads(packaged.read(MANIFEST_NAME))
                raw_rows = [row for row in manifest["members"]
                            if row["representation"] == "raw_worktree_bytes"]
                self.assertTrue(raw_rows)
                for row in raw_rows:
                    blob = subprocess.check_output([
                        "git", "-C", str(fixture["repo"]), "cat-file", "blob",
                        f"{fixture['commit']}:{row['source_path']}",
                    ])
                    self.assertEqual(packaged.read(row["archive_path"]), blob)

            bound = self.t4.verify(archive, "--repo", str(fixture["repo"]), *self.pins(fixture))
            self.assertEqual(bound.returncode, 0, bound.stdout + bound.stderr)
            report = json.loads(bound.stdout)
            self.assertEqual(report["trust_mode"], "git_bound")
            self.assertIs(report["raw_evidence_git_bound"], True)
            self.assertIs(report["git_cross_check"], True)

            weaker = self.t4.verify(archive, *self.pins(fixture))
            self.assertEqual(weaker.returncode, 0, weaker.stdout + weaker.stderr)
            report = json.loads(weaker.stdout)
            self.assertEqual(report["trust_mode"], "git_free_self_consistent")
            self.assertIs(report["raw_evidence_git_bound"], False)
            self.assertIs(report["git_cross_check"], False)

    def test_t6_self_consistent_raw_rewrites_fail_against_git_with_every_pin(self) -> None:
        with scratch_directory() as root:
            fixture = self.t4.fixture(root)
            archive = root / "package.zip"
            self.t4.build(fixture, archive)
            repo = ("--repo", str(fixture["repo"]))

            def content(members: dict) -> None:
                members[RAW] = members[RAW].replace(b"RED transcript", b"GREEN transcript")

            def line_endings(members: dict) -> None:
                members[RAW] = members[RAW].replace(b"\r\n", b"\n")

            def appended(members: dict) -> None:
                members[RAW] = members[RAW] + b"forged addendum\r\n"

            for label, change in (
                ("content", content), ("line-endings", line_endings), ("appended", appended),
            ):
                with self.subTest(label):
                    forged = self.forged(archive, root / f"{label}.zip", change)
                    with zipfile.ZipFile(forged) as packaged:
                        self.assertNotEqual(packaged.read(RAW), packaged.read(BLOB))
                    for extra in (self.pins(fixture), ()):
                        denied = self.t4.verify(forged, *repo, *extra)
                        self.assertNotEqual(
                            denied.returncode, 0,
                            f"F-4 {label}: forged raw evidence verified: {denied.stdout}",
                        )
                        self.assertIn(
                            f"raw evidence member differs from its Git blob: {RAW}",
                            denied.stderr,
                        )
                    # The weaker Git-free mode accepts self-consistent bytes and says so.
                    weaker = self.t4.verify(forged, *self.pins(fixture))
                    self.assertEqual(weaker.returncode, 0, weaker.stdout + weaker.stderr)
                    report = json.loads(weaker.stdout)
                    self.assertEqual(report["trust_mode"], "git_free_self_consistent")
                    self.assertIs(report["raw_evidence_git_bound"], False)

            def raw_and_blob(members: dict) -> None:
                members[RAW] = members[BLOB] = members[RAW] + b"forged addendum\r\n"

            forged = self.forged(archive, root / "raw-and-blob.zip", raw_and_blob)
            denied = self.t4.verify(forged, *repo, *self.pins(fixture))
            self.assertNotEqual(denied.returncode, 0, "F-4: raw and Git-blob forgery verified")
            self.assertIn("audit package rejected", denied.stderr)

    def test_t6_builder_refuses_raw_evidence_that_differs_from_git(self) -> None:
        with scratch_directory() as root:
            fixture = self.t4.fixture(root)
            repo = fixture["repo"]
            # core.autocrlf=true stores this CRLF transcript as an LF blob, so
            # its clean checkout bytes differ from the Git blob.
            (repo / "transcripts").mkdir()
            transcript = repo / "transcripts" / "run.txt"
            transcript.write_bytes(b"captured\r\noutput\r\n")
            for args in (("git", "add", "."), ("git", "commit", "-q", "-m", "transcripts")):
                result = command(*args, cwd=repo)
                self.assertEqual(result.returncode, 0, result.stderr)
            commit = command("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
            status = command("git", "status", "--porcelain=v1", "--untracked-files=all", cwd=repo)
            self.assertEqual(status.stdout, "")
            blob = subprocess.check_output(
                ["git", "-C", str(repo), "cat-file", "blob", f"{commit}:transcripts/run.txt"],
            )
            self.assertNotEqual(blob, transcript.read_bytes())

            def build(output: Path, *roots: str) -> subprocess.CompletedProcess[str]:
                arguments = []
                for relative in roots:
                    arguments += ["--raw-worktree-root", relative]
                return command(
                    sys.executable, str(TOOL), "build", "--repo", str(repo),
                    "--commit", commit, "--output", str(output), *arguments,
                    cwd=REPOSITORY_ROOT,
                )

            refused_output = root / "refused.zip"
            refused = build(refused_output, "evidence", "transcripts")
            self.assertNotEqual(refused.returncode, 0, "F-4: package built from non-Git raw bytes")
            self.assertIn("differs from its Git blob", refused.stderr)
            self.assertIn("transcripts/run.txt", refused.stderr)
            self.assertFalse(refused_output.exists())
            self.assertFalse(Path(str(refused_output) + ".sha256").exists())

            accepted = build(root / "accepted.zip", "evidence")
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)


if __name__ == "__main__":
    unittest.main()
