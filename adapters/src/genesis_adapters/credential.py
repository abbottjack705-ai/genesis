"""Loading the read-only OddsPapi key after G1 (design 7.5). Tested only with a temp file holding the sentinel.

The path comes from ``GENESIS_ODDSPAPI_CREDENTIAL_FILE``; no environment variable ever holds the key itself.
The file must be a regular file with exactly one name (no symbolic link, no second hard-link name that could
lie elsewhere) outside the repository worktree and outside the adapter runtime root, readable only by the
runner user (POSIX ``0600`` owned by the user; on Windows an ACL that names only the user), and hold exactly
one line: the key. The bytes are read from the very file that was checked (same device and file id). Its
fingerprint must equal the one pinned in the G1 record. Every refusal is a ``CredentialProblem`` whose code is an AdapterFailure name; no message ever
carries any part of the key or the file content.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping

from genesis_adapters.errors import AdapterFailure, CredentialProblem
from genesis_adapters.secrets import Secret, contains_raw

ENV_VAR = "GENESIS_ODDSPAPI_CREDENTIAL_FILE"
_OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _windows_principals(path: Path) -> set[str]:
    """The principals named by the file's ACL (``icacls`` output), lower-cased."""

    listing = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=False)
    if listing.returncode != 0:
        raise CredentialProblem(AdapterFailure.CREDENTIAL_PERMISSIONS.value)
    principals: set[str] = set()
    for number, line in enumerate(listing.stdout.splitlines()):
        text = line[len(str(path)):] if number == 0 else line
        text = text.strip()
        if ":(" in text:
            principals.add(text.split(":(", 1)[0].strip().lower())
    return principals


def _windows_user() -> str:
    who = subprocess.run(["whoami"], capture_output=True, text=True, check=False)
    if who.returncode != 0 or not who.stdout.strip():
        raise CredentialProblem(AdapterFailure.CREDENTIAL_PERMISSIONS.value)
    return who.stdout.strip().lower()


class CredentialSource:
    def __init__(self, *, repo: Path, runtime_root: Path, expected_fingerprint: str | None,
                 environ: Mapping[str, str] | None = None):
        self.repo = Path(repo).resolve()
        self.runtime_root = Path(runtime_root).resolve()
        self.expected_fingerprint = expected_fingerprint
        self.environ = os.environ if environ is None else environ

    def _path(self) -> Path:
        value = self.environ.get(ENV_VAR)
        if not value:
            raise CredentialProblem(AdapterFailure.CREDENTIAL_MISSING.value)
        return Path(value)

    def _check_file(self, path: Path) -> tuple[Path, os.stat_result]:
        try:
            info = os.lstat(path)
        except OSError:
            raise CredentialProblem(AdapterFailure.CREDENTIAL_MISSING.value) from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise CredentialProblem(AdapterFailure.CREDENTIAL_PERMISSIONS.value)
        resolved = path.resolve()
        if _inside(resolved, self.repo) or _inside(resolved, self.runtime_root):
            raise CredentialProblem(AdapterFailure.CREDENTIAL_PERMISSIONS.value)
        if sys.platform == "win32":
            if _windows_principals(resolved) != {_windows_user()}:
                raise CredentialProblem(AdapterFailure.CREDENTIAL_PERMISSIONS.value)
        else:
            if stat.S_IMODE(info.st_mode) != _OWNER_ONLY or info.st_uid != os.getuid():
                raise CredentialProblem(AdapterFailure.CREDENTIAL_PERMISSIONS.value)
        return resolved, info

    def load(self) -> Secret:
        path, checked = self._check_file(self._path())
        try:
            with open(path, "rb") as handle:
                opened = os.fstat(handle.fileno())
                # the very file that was checked (not swapped in between), and its only name: a second hard-link
                # name could lie anywhere, including inside the repository
                same = (opened.st_dev, opened.st_ino) == (checked.st_dev, checked.st_ino) and opened.st_nlink == 1
                data = handle.read() if same else b""
        except OSError:
            raise CredentialProblem(AdapterFailure.CREDENTIAL_MISSING.value) from None
        if not same:
            raise CredentialProblem(AdapterFailure.CREDENTIAL_PERMISSIONS.value)
        text = data[:-1] if data.endswith(b"\n") else data
        if not text or b"\n" in text or b"\r" in text:
            raise CredentialProblem(AdapterFailure.CREDENTIAL_MISSING.value)      # exactly one line, the key
        try:
            secret = Secret(text)
        except (TypeError, ValueError):
            raise CredentialProblem(AdapterFailure.CREDENTIAL_MISSING.value) from None
        finally:
            del data, text
        for name, value in self.environ.items():
            if name != ENV_VAR and contains_raw(secret, value):
                raise CredentialProblem(AdapterFailure.CREDENTIAL_PERMISSIONS.value)   # never in the environment
        if self.expected_fingerprint is None or secret.fingerprint != self.expected_fingerprint:
            raise CredentialProblem(AdapterFailure.CREDENTIAL_FINGERPRINT_MISMATCH.value)
        return secret
