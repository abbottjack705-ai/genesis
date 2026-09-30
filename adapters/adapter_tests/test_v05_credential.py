"""CredentialSource (design 7.5, F-04): tested only with a temp file holding the sentinel key."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from genesis_adapters import errors as err
from genesis_adapters.credential import ENV_VAR, CredentialSource
from genesis_adapters.secrets import Secret

from .support import REPO, SENTINEL_KEY, scratch_root

FINGERPRINT = Secret(SENTINEL_KEY).fingerprint


def restrict(path: Path) -> None:
    if sys.platform == "win32":
        user = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"], capture_output=True,
                       check=True)
    else:
        os.chmod(path, 0o600)


def widen(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.run(["icacls", str(path), "/grant", "*S-1-5-32-545:R"], capture_output=True, check=True)  # Users
    else:
        os.chmod(path, 0o644)


class CredentialTests(unittest.TestCase):
    def source(self, base: Path, path: Path | None, *, fingerprint=FINGERPRINT, extra_env=None):
        env = {} if path is None else {ENV_VAR: str(path)}
        env.update(extra_env or {})
        return CredentialSource(repo=REPO, runtime_root=base / "runtime", expected_fingerprint=fingerprint,
                                environ=env)

    def key_file(self, base: Path, content: bytes = SENTINEL_KEY.encode() + b"\n", name="oddspapi.key") -> Path:
        folder = base / "keys"
        folder.mkdir(exist_ok=True)
        path = folder / name
        path.write_bytes(content)
        restrict(path)
        return path

    def refused(self, source, code: str):
        with self.assertRaises(err.CredentialProblem) as caught:
            source.load()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(SENTINEL_KEY, str(caught.exception))
        self.assertNotIn(SENTINEL_KEY, repr(caught.exception.args))

    def test_a_private_single_line_file_outside_repo_and_root_loads_with_its_pinned_fingerprint(self):
        with scratch_root() as base:
            secret = self.source(base, self.key_file(base)).load()
            self.assertEqual(secret.fingerprint, FINGERPRINT)
            self.assertNotIn(SENTINEL_KEY, repr(secret))
            no_newline = self.key_file(base, SENTINEL_KEY.encode(), name="plain.key")
            self.assertEqual(self.source(base, no_newline).load().fingerprint, FINGERPRINT)

    def test_f04_a_missing_variable_or_file_is_credential_missing(self):
        with scratch_root() as base:
            self.refused(self.source(base, None), "CREDENTIAL_MISSING")
            self.refused(self.source(base, base / "keys" / "absent.key"), "CREDENTIAL_MISSING")

    def test_f04_anything_but_exactly_one_line_holding_the_key_is_refused(self):
        with scratch_root() as base:
            for label, content in (("empty", b""), ("two lines", SENTINEL_KEY.encode() + b"\nsecond\n"),
                                   ("crlf", SENTINEL_KEY.encode() + b"\r\n"), ("blank line", b"\n"),
                                   ("padded", b" " + SENTINEL_KEY.encode() + b"\n")):
                with self.subTest(label):
                    self.refused(self.source(base, self.key_file(base, content, name=label.replace(" ", "_"))),
                                 "CREDENTIAL_MISSING")

    def test_f04_a_file_inside_the_repository_or_the_runtime_root_is_refused(self):
        with scratch_root() as base:
            runtime = base / "runtime"
            runtime.mkdir()
            inside_root = runtime / "oddspapi.key"
            inside_root.write_bytes(SENTINEL_KEY.encode() + b"\n")
            restrict(inside_root)
            self.refused(self.source(base, inside_root), "CREDENTIAL_PERMISSIONS")
        # a path inside the worktree is refused before the file is ever opened
        source = CredentialSource(repo=REPO, runtime_root=REPO / "no-such-runtime", expected_fingerprint=FINGERPRINT,
                                  environ={ENV_VAR: str(REPO / "adapters" / "README.md")})
        self.refused(source, "CREDENTIAL_PERMISSIONS")
        with scratch_root() as base:                    # a private one-line key inside a (stand-in) repository
            path = self.key_file(base)
            source = CredentialSource(repo=base, runtime_root=base / "runtime", expected_fingerprint=FINGERPRINT,
                                      environ={ENV_VAR: str(path)})
            self.refused(source, "CREDENTIAL_PERMISSIONS")

    def test_f04_a_file_swapped_between_the_checks_and_the_read_is_refused(self):
        with scratch_root() as base:
            path = self.key_file(base)
            real = CredentialSource._check_file

            def check_then_swap(source, candidate):
                checked = real(source, candidate)
                os.replace(self.key_file(base, name="impostor.key"), path)   # same bytes, another file
                return checked

            with mock.patch.object(CredentialSource, "_check_file", check_then_swap):
                self.refused(self.source(base, path), "CREDENTIAL_PERMISSIONS")

    def test_f04_a_link_reported_by_lstat_is_refused_on_every_platform(self):
        # the real-link test above needs a privilege this Windows account lacks; this one simulates what
        # os.lstat reports for a link, so the branch is exercised everywhere
        with scratch_root() as base:
            path = self.key_file(base)
            link_mode = stat.S_IFLNK | 0o600
            fake = os.stat_result((link_mode, 1, 1, 1, 0, 0, len(SENTINEL_KEY) + 1, 0, 0, 0))
            with mock.patch("genesis_adapters.credential.os.lstat", return_value=fake):
                self.refused(self.source(base, path), "CREDENTIAL_PERMISSIONS")

    def test_f04_a_file_with_a_second_hard_link_name_is_refused(self):
        with scratch_root() as base:
            path = self.key_file(base)
            os.link(path, base / "second-name.key")      # the same bytes reachable under another path
            self.refused(self.source(base, path), "CREDENTIAL_PERMISSIONS")
            os.remove(base / "second-name.key")
            self.assertEqual(self.source(base, path).load().fingerprint, FINGERPRINT)

    def test_f04_a_file_readable_by_others_is_refused(self):
        with scratch_root() as base:
            path = self.key_file(base)
            widen(path)
            self.refused(self.source(base, path), "CREDENTIAL_PERMISSIONS")

    def test_f04_a_link_is_refused(self):
        with scratch_root() as base:
            target = self.key_file(base)
            link = base / "keys" / "link.key"
            try:
                os.symlink(target, link)
            except OSError:
                self.skipTest("symbolic links need a privilege this account does not hold")
            self.refused(self.source(base, link), "CREDENTIAL_PERMISSIONS")

    def test_f04_a_fingerprint_that_differs_from_g1_is_refused(self):
        with scratch_root() as base:
            path = self.key_file(base)
            self.refused(self.source(base, path, fingerprint="0" * 12), "CREDENTIAL_FINGERPRINT_MISMATCH")
            self.refused(self.source(base, path, fingerprint=None), "CREDENTIAL_FINGERPRINT_MISMATCH")

    def test_the_key_itself_may_never_live_in_the_environment(self):
        with scratch_root() as base:
            path = self.key_file(base)
            self.refused(self.source(base, path, extra_env={"ODDSPAPI_KEY": SENTINEL_KEY}), "CREDENTIAL_PERMISSIONS")
            self.refused(self.source(base, path, extra_env={"OTHER": "x" + SENTINEL_KEY + "y"}),
                         "CREDENTIAL_PERMISSIONS")


def junction(link: Path, target: Path) -> None:
    """A directory link that needs NO privilege: an NTFS junction on Windows (``mklink /J``), a directory symbolic
    link elsewhere. Failing to create one fails the test; it is never a skip."""

    if sys.platform == "win32":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
        if made.returncode != 0:
            raise AssertionError(f"mklink /J failed: {made.stdout.strip()} {made.stderr.strip()}")
    else:
        os.symlink(target, link, target_is_directory=True)


class UnprivilegedLinkAttackTests(unittest.TestCase):
    """R-4 (hostile audit F-04, oracle CR-12): the real-OS link attacks that need no privilege, ported from the
    auditor's ``probe_credential_links.py``. A stand-in repository and runtime root live in the scratch directory,
    so nothing is ever written into the real worktree. Each refusal has a control that LOADS from the same layout,
    so a blanket refusal cannot pass. The genuine symbolic-link case still needs a privilege this account lacks:
    ``test_f04_a_link_is_refused`` stays and skips here (see adapters/evidence/R1/F04_REAL_SYMLINK_RECIPE.md)."""

    def layout(self, base: Path) -> tuple[Path, Path, Path]:
        repo, runtime, outside = base / "repo", base / "runtime", base / "outside"
        for folder in (repo / "inside", runtime, outside):
            folder.mkdir(parents=True)
        return repo, runtime, outside

    def planted(self, path: Path) -> Path:
        path.write_bytes(SENTINEL_KEY.encode("ascii") + b"\n")
        restrict(path)                                    # owner-only, so only the location can refuse it
        return path

    def loader(self, repo: Path, runtime: Path, path: Path) -> CredentialSource:
        return CredentialSource(repo=repo, runtime_root=runtime, expected_fingerprint=FINGERPRINT,
                                environ={ENV_VAR: str(path)})

    def refused(self, source, code: str):
        with self.assertRaises(err.CredentialProblem) as caught:
            source.load()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(SENTINEL_KEY, str(caught.exception))

    def test_r4_controls_a_plain_file_and_a_junction_to_an_allowed_folder_both_load(self):
        with scratch_root() as base:
            repo, runtime, outside = self.layout(base)
            plain = self.planted(outside / "key.txt")
            self.assertEqual(self.loader(repo, runtime, plain).load().fingerprint, FINGERPRINT)
            junction(base / "j-allowed", outside)
            through = base / "j-allowed" / "key.txt"
            self.assertEqual(self.loader(repo, runtime, through).load().fingerprint, FINGERPRINT)

    def test_r4_a_junction_resolving_inside_the_repository_is_refused(self):
        with scratch_root() as base:
            repo, runtime, _ = self.layout(base)
            self.planted(repo / "inside" / "key.txt")
            junction(base / "j-repo", repo / "inside")
            self.refused(self.loader(repo, runtime, base / "j-repo" / "key.txt"), "CREDENTIAL_PERMISSIONS")

    def test_r4_a_junction_resolving_into_the_runtime_root_is_refused(self):
        with scratch_root() as base:
            repo, runtime, _ = self.layout(base)
            self.planted(runtime / "key.txt")
            junction(base / "j-runtime", runtime)
            self.refused(self.loader(repo, runtime, base / "j-runtime" / "key.txt"), "CREDENTIAL_PERMISSIONS")

    def test_r4_a_hard_link_whose_second_name_is_inside_the_repository_is_refused(self):
        with scratch_root() as base:
            repo, runtime, outside = self.layout(base)
            inside = self.planted(repo / "inside" / "key.txt")
            os.link(inside, outside / "key.txt")          # the path given to the loader lies outside
            restrict(outside / "key.txt")
            self.refused(self.loader(repo, runtime, outside / "key.txt"), "CREDENTIAL_PERMISSIONS")
            os.remove(inside)                            # the second name gone: the same file now loads
            self.assertEqual(self.loader(repo, runtime, outside / "key.txt").load().fingerprint, FINGERPRINT)


if __name__ == "__main__":
    unittest.main()
