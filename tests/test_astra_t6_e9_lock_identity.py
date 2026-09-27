"""E9: the dependency-lock pin is independent of checkout line endings.

Invariant: ``config/defaults.json`` pins ``requirements.lock`` by the SHA-256
of its canonical LF text. ``.gitattributes`` makes every checkout hold LF
bytes, and ``dependency_lock_digest`` gives a CRLF checkout of the same content
(Git for Windows ``core.autocrlf=true``) the same identity, so configuration
integrity passes wherever the repository content is identical. Any other
change to the lock, including a lone carriage return, fails it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from genesis.config import dependency_lock_digest, load_config

from ._support import scratch_directory


ROOT = Path(__file__).resolve().parents[1]


def pinned() -> str:
    return json.loads((ROOT / "config" / "defaults.json").read_text(encoding="utf-8"))[
        "dependencies_lock_digest"
    ]


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout


class T6E9LockIdentityTests(unittest.TestCase):
    def test_e9_lf_and_crlf_copies_of_the_lock_have_the_pinned_identity(self):
        lf = (ROOT / "requirements.lock").read_bytes().replace(b"\r\n", b"\n")
        with scratch_directory() as root:
            for name, data in (("lf", lf), ("crlf", lf.replace(b"\n", b"\r\n"))):
                with self.subTest(name):
                    (root / name).write_bytes(data)
                    self.assertEqual(dependency_lock_digest(root / name), pinned())
                    load_config(ROOT / "config" / "defaults.json",
                                dependency_lock_digest(root / name))

    def test_e9_a_changed_lock_still_fails_configuration_integrity(self):
        lf = (ROOT / "requirements.lock").read_bytes().replace(b"\r\n", b"\n")
        tampered = {
            "added requirement": lf + b"requests==2.32.3\n",
            "changed text": lf.replace(b"stdlib-only", b"stdlib-only!"),
            "lone carriage return": lf.replace(b"\n", b"\r", 1),
            "trailing byte": lf + b" ",
        }
        with scratch_directory() as root:
            for label, data in tampered.items():
                with self.subTest(label):
                    (root / "lock").write_bytes(data)
                    self.assertNotEqual(dependency_lock_digest(root / "lock"), pinned())
                    with self.assertRaises(ValueError):
                        load_config(ROOT / "config" / "defaults.json",
                                    dependency_lock_digest(root / "lock"))

    def test_e9_the_repository_checks_the_lock_out_with_lf_endings(self):
        if shutil.which("git") is None or not (ROOT / ".git").exists():
            self.skipTest("not a Git working tree")
        attributes = git("check-attr", "text", "eol", "--", "requirements.lock", cwd=ROOT)
        self.assertIn("requirements.lock: eol: lf", attributes)

    def test_e9_an_autocrlf_checkout_of_the_lock_passes_integrity(self):
        """A disposable repository with this repository's lock and attribute rule."""

        if shutil.which("git") is None:
            self.skipTest("git is unavailable")
        with scratch_directory() as root:
            source = root / "source"
            source.mkdir()
            git("init", "-q", cwd=source)
            git("config", "core.autocrlf", "false", cwd=source)
            (source / "requirements.lock").write_bytes(
                (ROOT / "requirements.lock").read_bytes().replace(b"\r\n", b"\n")
            )
            (source / ".gitattributes").write_bytes(b"requirements.lock text eol=lf\n")
            (source / "notes.txt").write_bytes(b"one\ntwo\n")
            git("add", ".", cwd=source)
            git("-c", "user.name=e9", "-c", "user.email=e9@local", "commit", "-q", "-m", "e9",
                cwd=source)
            checkout = root / "checkout"
            git("-c", "core.autocrlf=true", "clone", "-q", str(source), str(checkout), cwd=root)
            # autocrlf=true converts ordinary text, but not the attributed lock.
            self.assertIn(b"\r\n", (checkout / "notes.txt").read_bytes())
            self.assertNotIn(b"\r\n", (checkout / "requirements.lock").read_bytes())
            self.assertEqual(dependency_lock_digest(checkout / "requirements.lock"), pinned())


if __name__ == "__main__":
    unittest.main()
