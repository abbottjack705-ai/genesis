from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path

from ._support import scratch_directory


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPOSITORY_ROOT / "tools" / "genesis_audit_package.py"
MANIFEST_NAME = "GENESIS_AUDIT_PACKAGE_MANIFEST.json"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def command(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*args], cwd=cwd, text=True, capture_output=True, check=False,
    )


class AstraT4EvidencePackageTests(unittest.TestCase):
    def require_tool(self) -> None:
        self.assertTrue(
            TOOL.is_file(),
            "B8 RED: no byte-preserving, representation-labeled audit packager exists",
        )

    def fixture(self, root: Path) -> dict:
        repo = root / "repo"
        repo.mkdir()
        for args in (
            ("git", "init", "-q"),
            ("git", "config", "user.name", "Genesis Test"),
            ("git", "config", "user.email", "genesis@example.invalid"),
            ("git", "config", "core.autocrlf", "true"),
        ):
            result = command(*args, cwd=repo)
            self.assertEqual(result.returncode, 0, result.stderr)
        (repo / "DECISIONS").mkdir()
        (repo / "source").mkdir()
        (repo / "evidence").mkdir()
        # T6 F-4: raw evidence must equal its Git blob, so the CRLF transcript
        # is stored without end-of-line conversion, as the repository does.
        (repo / ".gitattributes").write_bytes(b"evidence/** -text\n")
        adr = repo / "DECISIONS" / "ADR.md"
        source = repo / "source" / "program.py"
        transcript = repo / "evidence" / "raw.txt"
        adr.write_bytes(b"approved authority\r\nexact bytes\r\n")
        source.write_bytes(b"VALUE = 1\r\n")
        transcript.write_bytes(b"RED transcript\r\nline two\r\n")
        for args in (("git", "add", "."), ("git", "commit", "-q", "-m", "fixture")):
            result = command(*args, cwd=repo)
            self.assertEqual(result.returncode, 0, result.stderr)
        commit = command("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        tree = command("git", "rev-parse", "HEAD^{tree}", cwd=repo).stdout.strip()
        adr_blob = subprocess.check_output(
            ["git", "-C", str(repo), "show", f"{commit}:DECISIONS/ADR.md"]
        )
        historical = root / "original-s5.zip"
        historical.write_bytes(b"historical archive\r\nunchanged\x00bytes")
        return {
            "repo": repo,
            "commit": commit,
            "tree": tree,
            "adr_hash": sha256(adr_blob),
            "transcript": transcript,
            "historical": historical,
        }

    def build(self, fixture: dict, output: Path) -> dict:
        self.require_tool()
        result = command(
            sys.executable,
            str(TOOL),
            "build",
            "--repo", str(fixture["repo"]),
            "--commit", fixture["commit"],
            "--output", str(output),
            "--raw-worktree-root", "evidence",
            "--historical", f"original-s5.zip={fixture['historical']}",
            "--authority", f"DECISIONS/ADR.md={fixture['adr_hash']}",
            cwd=REPOSITORY_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def load(self, archive: Path) -> tuple[zipfile.ZipFile, dict]:
        opened = zipfile.ZipFile(archive)
        return opened, json.loads(opened.read(MANIFEST_NAME))

    def test_git_blob_snapshot_preserves_exact_bytes_and_approved_adr(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)
            with self.load(archive)[0] as packaged:
                manifest = json.loads(packaged.read(MANIFEST_NAME))
                for row in manifest["source_snapshot"]:
                    expected = subprocess.check_output([
                        "git", "-C", str(fixture["repo"]), "show",
                        f"{fixture['commit']}:{row['repository_path']}",
                    ])
                    self.assertEqual(packaged.read(row["archive_path"]), expected)
                    self.assertEqual(row["representation"], "git_blob_bytes")
                authority = manifest["authorities"][0]
                self.assertEqual(authority["approved_sha256"], fixture["adr_hash"])
                self.assertEqual(authority["git_blob_sha256"], fixture["adr_hash"])

    def test_raw_worktree_and_historical_bytes_are_distinct_labeled_representations(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)
            with self.load(archive)[0] as packaged:
                manifest = json.loads(packaged.read(MANIFEST_NAME))
                rows = {row["archive_path"]: row for row in manifest["members"]}
                raw_path = "raw-worktree/evidence/raw.txt"
                historical_path = "historical/original-s5.zip"
                self.assertEqual(rows[raw_path]["representation"], "raw_worktree_bytes")
                self.assertEqual(packaged.read(raw_path), fixture["transcript"].read_bytes())
                self.assertEqual(
                    rows[historical_path]["representation"],
                    "historical_raw_artifact_bytes",
                )
                self.assertEqual(packaged.read(historical_path), fixture["historical"].read_bytes())
                # T6 F-4: Git-backed raw bytes equal their blob, unnormalized.
                git_raw = packaged.read("git-blobs/evidence/raw.txt")
                self.assertEqual(git_raw, packaged.read(raw_path))
                self.assertIn(b"\r\n", packaged.read(raw_path))

    def test_fresh_extraction_verifies_without_repository(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)
            extracted = root / "fresh-extraction"
            result = command(
                sys.executable, str(TOOL), "verify",
                "--archive", str(archive), "--extract-to", str(extracted),
                cwd=REPOSITORY_ROOT,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["target_commit"], fixture["commit"])
            self.assertEqual(report["target_tree"], fixture["tree"])
            self.assertTrue(report["sidecar_verified"])
            self.assertTrue(report["fresh_extraction_verified"])
            self.assertTrue((extracted / MANIFEST_NAME).is_file())

    def test_repository_cross_check_passes_and_archive_tamper_fails_closed(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)
            result = command(
                sys.executable, str(TOOL), "verify", "--archive", str(archive),
                "--repo", str(fixture["repo"]), cwd=REPOSITORY_ROOT,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            tampered = root / "tampered.zip"
            tampered.write_bytes(archive.read_bytes())
            with zipfile.ZipFile(tampered, "a") as changed:
                changed.writestr("git-blobs/source/program.py", b"VALUE = 9\n")
            Path(str(tampered) + ".sha256").write_text(
                f"{sha256(tampered.read_bytes())}  {tampered.name}\n",
                encoding="ascii",
            )
            denied = command(
                sys.executable, str(TOOL), "verify", "--archive", str(tampered),
                cwd=REPOSITORY_ROOT,
            )
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("duplicate", denied.stderr)

    def test_repeated_build_is_byte_deterministic_and_sidecar_exact(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            first = root / "first.zip"
            second = root / "second.zip"
            first_report = self.build(fixture, first)
            second_report = self.build(fixture, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_report["sha256"], second_report["sha256"])
            self.assertEqual(first_report["sha256"], sha256(first.read_bytes()))
            sidecar = Path(first_report["sidecar"])
            digest, filename = sidecar.read_text(encoding="ascii").strip().split("  ", 1)
            self.assertEqual(digest, sha256(first.read_bytes()))
            self.assertEqual(filename, first.name)

    def rewrite(
        self,
        archive: Path,
        output: Path,
        *,
        manifest_change=None,
        member_change: tuple[str, bytes] | None = None,
        extra_member: tuple[str, bytes] | None = None,
    ) -> None:
        with zipfile.ZipFile(archive) as source:
            members = [(info.filename, source.read(info.filename)) for info in source.infolist()]
        with zipfile.ZipFile(output, "x") as changed:
            for name, raw in members:
                if name == MANIFEST_NAME and manifest_change is not None:
                    manifest = json.loads(raw)
                    manifest_change(manifest)
                    raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
                if member_change is not None and name == member_change[0]:
                    raw = member_change[1]
                changed.writestr(name, raw)
            if extra_member is not None:
                changed.writestr(*extra_member)
        Path(str(output) + ".sha256").write_text(
            f"{sha256(output.read_bytes())}  {output.name}\n", encoding="ascii",
        )

    def verify(self, archive: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return command(
            sys.executable, str(TOOL), "verify", "--archive", str(archive), *extra,
            cwd=REPOSITORY_ROOT,
        )

    def test_content_tamper_unsafe_path_and_stale_or_missing_sidecar_fail_closed(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)

            content = root / "content.zip"
            self.rewrite(archive, content, member_change=("git-blobs/source/program.py", b"VALUE = 9\n"))
            denied = self.verify(content)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("fail manifest", denied.stderr)

            unsafe = root / "unsafe.zip"
            self.rewrite(archive, unsafe, extra_member=("../escape.txt", b"escape"))
            denied = self.verify(unsafe)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("unsafe", denied.stderr)

            stale = root / "stale.zip"
            self.rewrite(archive, stale, member_change=("historical/original-s5.zip", b"altered"))
            original_hash = sha256(archive.read_bytes())
            Path(str(stale) + ".sha256").write_text(
                f"{original_hash}  {stale.name}\n", encoding="ascii",
            )
            denied = self.verify(stale)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("sidecar", denied.stderr)

            missing = root / "missing.zip"
            missing.write_bytes(archive.read_bytes())
            denied = self.verify(missing)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("sidecar is missing", denied.stderr)

    def test_verifier_enforces_caller_pinned_authorities_without_repository(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)
            pin = f"DECISIONS/ADR.md={fixture['adr_hash']}"
            accepted = self.verify(archive, "--authority", pin)
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)

            wrong = self.verify(archive, "--authority", f"DECISIONS/ADR.md={'0' * 64}")
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn("authority", wrong.stderr)

            stripped = root / "stripped.zip"
            self.rewrite(archive, stripped, manifest_change=lambda m: m.update(authorities=[]))
            denied = self.verify(stripped, "--authority", pin)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("authority", denied.stderr)

    def test_raw_worktree_members_exclude_git_ignored_files(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            repo = fixture["repo"]
            (repo / ".gitignore").write_bytes(b"__pycache__/\n")
            for args in (("git", "add", ".gitignore"), ("git", "commit", "-q", "-m", "ignore")):
                result = command(*args, cwd=repo)
                self.assertEqual(result.returncode, 0, result.stderr)
            fixture["commit"] = command("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
            cache = repo / "evidence" / "__pycache__"
            cache.mkdir()
            (cache / "probe.cpython-312.pyc").write_bytes(b"\x00volatile cache\x00")
            archive = root / "package.zip"
            self.build(fixture, archive)
            with self.load(archive)[0] as packaged:
                names = set(packaged.namelist())
            self.assertIn("raw-worktree/evidence/raw.txt", names)
            self.assertFalse(
                [name for name in names if "__pycache__" in name],
                "Git-ignored worktree files must not enter the raw evidence namespace",
            )

    def test_manifest_rows_and_fixed_fields_are_closed(self) -> None:
        with scratch_directory() as root:
            fixture = self.fixture(root)
            archive = root / "package.zip"
            self.build(fixture, archive)

            def extra_raw_field(manifest: dict) -> None:
                for row in manifest["members"]:
                    if row["representation"] == "raw_worktree_bytes":
                        row["git_blob_oid"] = "0" * 40

            mutations = {
                "extra-row-field": extra_raw_field,
                "dirty-status": lambda m: m.update(repository_status="dirty"),
                "dropped-non-authorization": lambda m: m.update(
                    non_authorizations=["adapter"],
                ),
                "changed-self-reference-note": lambda m: m.update(
                    self_reference_note="self-authenticating",
                ),
            }
            for label, mutation in mutations.items():
                with self.subTest(label):
                    changed = root / f"{label}.zip"
                    self.rewrite(archive, changed, manifest_change=mutation)
                    denied = self.verify(changed)
                    self.assertNotEqual(denied.returncode, 0, denied.stdout)
                    self.assertIn("audit package rejected", denied.stderr)


if __name__ == "__main__":
    unittest.main()
