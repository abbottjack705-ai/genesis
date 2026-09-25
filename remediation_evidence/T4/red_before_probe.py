"""Reproduce B8 without modifying the historical archive or producer manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import unittest
import zipfile
from pathlib import Path


TARGET = "27dd525c1fd7d531c4833c4bf7e44204a9345f19"
ADR_HASHES = {
    "DECISIONS/ADR-0002-s3-manifest-and-candidate-v3.md":
        "7e851df9898f3a257a87b602bc1a7f6011ebae1397d42c17b8727c84e554ae00",
    "DECISIONS/ADR-0003-s5-protected-process-boundary.md":
        "0fd4c63deb7a8431c41d7869163ccf79ce0295b63b585c8e4c3a0695f1dafaad",
}
S5_TRANSCRIPTS = (
    "remediation_evidence/S5/GREEN_COMPILEALL.txt",
    "remediation_evidence/S5/GREEN_FULL.txt",
    "remediation_evidence/S5/GREEN_RETAINED.txt",
    "remediation_evidence/S5/GREEN_TARGETED.txt",
    "remediation_evidence/S5/RED_166F923.txt",
    "remediation_evidence/S5/RED_S4_HEAD.txt",
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class B8HistoricalArchiveProbe(unittest.TestCase):
    repo: Path
    archive: zipfile.ZipFile
    producer_manifest: dict
    tracked: tuple[str, ...]

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Path(ARGS.repo).resolve()
        cls.archive = zipfile.ZipFile(Path(ARGS.archive).resolve())
        cls.producer_manifest = json.loads(Path(ARGS.manifest).read_text(encoding="utf-8"))
        names = subprocess.check_output(
            ["git", "-C", str(cls.repo), "ls-tree", "-r", "--name-only", TARGET]
        )
        cls.tracked = tuple(names.decode("utf-8").splitlines())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.archive.close()

    def git_blob(self, path: str) -> bytes:
        return subprocess.check_output(
            ["git", "-C", str(self.repo), "show", f"{TARGET}:{path}"]
        )

    def test_repository_archive_preserves_every_git_blob_byte(self) -> None:
        mismatches = [
            path for path in self.tracked
            if self.archive.read(path) != self.git_blob(path)
        ]
        normalized_mismatches = [
            path for path in mismatches
            if self.archive.read(path).replace(b"\r\n", b"\n") != self.git_blob(path)
        ]
        print(
            f"B8_TRACKED={len(self.tracked)} BYTE_MISMATCHES={len(mismatches)} "
            f"AFTER_CRLF_TO_LF={len(normalized_mismatches)}",
            flush=True,
        )
        self.assertEqual(
            mismatches,
            [],
            "B8: historical repository archive changed exact Git-blob bytes",
        )

    def test_archive_adrs_equal_the_approved_git_blob_hashes(self) -> None:
        observations = {
            path: {
                "approved_git_blob_sha256": expected,
                "archive_member_sha256": sha256(self.archive.read(path)),
            }
            for path, expected in ADR_HASHES.items()
        }
        print("B8_ADRS=" + json.dumps(observations, sort_keys=True), flush=True)
        for path, expected in ADR_HASHES.items():
            with self.subTest(path=path):
                self.assertEqual(
                    sha256(self.archive.read(path)),
                    expected,
                    "B8: archive authority bytes differ from approved Git blob",
                )

    def test_repository_hashes_have_explicit_representation_labels(self) -> None:
        rows = [
            row for row in self.producer_manifest.get("files", [])
            if "repository_path" in row
        ]
        self.assertTrue(rows, "B8: producer manifest has no repository rows")
        self.assertTrue(
            all(row.get("representation") == "git_blob_bytes" for row in rows),
            "B8: repository hashes do not say whether they identify Git blobs or archive bytes",
        )

    def test_transcript_hashes_are_separately_labeled_raw_representations(self) -> None:
        by_path = {
            row.get("repository_path"): row
            for row in self.producer_manifest.get("files", [])
        }
        missing_or_unlabeled = [
            path for path in S5_TRANSCRIPTS
            if by_path.get(path, {}).get("representation") != "raw_worktree_bytes"
        ]
        self.assertEqual(
            missing_or_unlabeled,
            [],
            "B8: raw transcript hashes are absent or conflated with Git-blob representation",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--manifest", required=True)
    ARGS, remaining = parser.parse_known_args()
    unittest.main(argv=[__file__, *remaining], verbosity=2)
