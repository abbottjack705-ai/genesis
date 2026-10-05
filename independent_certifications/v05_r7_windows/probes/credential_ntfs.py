"""Certification-only NTFS credential probes. Synthetic key; no provider calls."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

candidate = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(candidate / "adapters" / "src"), str(candidate / "src")]
from genesis_adapters.credential import CredentialSource, ENV_VAR
from genesis_adapters.errors import CredentialProblem
from genesis_adapters.secrets import Secret

KEY = b"SYNTHETIC_CERTIFICATION_KEY_2026\n"
FP = Secret(KEY[:-1]).fingerprint
USER = subprocess.check_output(["whoami"], text=True).strip()


def command(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, capture_output=True, text=True)
    print("COMMAND", " ".join(args), "EXIT", result.returncode)
    print(result.stdout.strip())
    print(result.stderr.strip())
    return result


def acl(path: Path) -> None:
    command("icacls", str(path))


def private(path: Path) -> None:
    result = command("icacls", str(path), "/inheritance:r", "/grant:r", f"{USER}:F")
    if result.returncode:
        raise RuntimeError("could not set private test ACL")


def plant(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(KEY)
    private(path)
    return path


def outcome(repo: Path, runtime: Path, path: Path) -> str:
    source = CredentialSource(repo=repo, runtime_root=runtime, expected_fingerprint=FP,
                              environ={ENV_VAR: str(path)})
    try:
        secret = source.load()
    except CredentialProblem as error:
        return error.code
    return "LOADED" if secret.fingerprint == FP else "WRONG_FINGERPRINT"


def check(label: str, repo: Path, runtime: Path, path: Path, expected: str) -> None:
    actual = outcome(repo, runtime, path)
    print("CASE", label, "PATH_LENGTH", len(str(path)), "EXPECTED", expected, "ACTUAL", actual,
          "MATCH", actual == expected)
    if actual != expected:
        raise AssertionError(label)


def junction(link: Path, target: Path) -> None:
    result = command("cmd", "/c", "mklink", "/J", str(link), str(target))
    if result.returncode:
        raise RuntimeError("NTFS junction creation failed")


with tempfile.TemporaryDirectory(prefix="genesis-r7-cert-ntfs-") as name:
    base = Path(name)
    print("TEMP_ROOT", base, "USER", USER)
    repo, runtime, outside = base / "repo", base / "runtime", base / "outside"
    for folder in (repo / "inside", runtime, outside):
        folder.mkdir(parents=True)
    allowed = plant(outside / "synthetic.key")
    check("plain_allowed", repo, runtime, allowed, "LOADED")

    # W1: this must be a real NTFS symbolic link. Failure to create is OPEN.
    link = outside / "real-symlink.key"
    try:
        os.symlink(allowed, link)
    except OSError as error:
        print("W1_REAL_SYMLINK", "OPEN", "create_failed", type(error).__name__,
              "winerror", getattr(error, "winerror", None), "errno", error.errno)
    else:
        print("W1_REAL_SYMLINK", "CREATED", "is_symlink", link.is_symlink())
        check("real_symlink_refused", repo, runtime, link, "CREDENTIAL_PERMISSIONS")
        link.unlink()

    # W2: actual NTFS directory junctions, including a positive control.
    inside = plant(repo / "inside" / "synthetic.key")
    in_runtime = plant(runtime / "synthetic.key")
    links = [(base / "j-allowed", outside), (base / "j-repo", repo / "inside"),
             (base / "j-runtime", runtime)]
    try:
        for alias, target in links:
            junction(alias, target)
        check("junction_allowed", repo, runtime, links[0][0] / allowed.name, "LOADED")
        check("junction_repository", repo, runtime, links[1][0] / inside.name, "CREDENTIAL_PERMISSIONS")
        check("junction_runtime", repo, runtime, links[2][0] / in_runtime.name, "CREDENTIAL_PERMISSIONS")
    finally:
        for alias, _ in links:
            if alias.exists():
                alias.rmdir()

    # W3: inherited and explicit principal ACLs on NTFS.
    inherited = outside / "inherited.key"
    inherited.write_bytes(KEY)
    acl(inherited)
    print("W3_INHERITED_OUTCOME", outcome(repo, runtime, inherited))
    private(inherited)
    acl(inherited)
    check("private_owner", repo, runtime, inherited, "LOADED")
    command("icacls", str(inherited), "/grant", "*S-1-5-32-545:R")
    acl(inherited)
    check("Users_readable", repo, runtime, inherited, "CREDENTIAL_PERMISSIONS")
    private(inherited)
    command("icacls", str(inherited), "/remove:g", "*S-1-5-32-545")
    command("icacls", str(inherited), "/grant", "*S-1-5-32-544:R")
    acl(inherited)
    check("Administrators_readable", repo, runtime, inherited, "CREDENTIAL_PERMISSIONS")

    # W8: long NTFS paths for each boundary; a stand-in repo avoids touching candidate bytes.
    long_base = base / ("r" * 75) / ("s" * 75) / ("t" * 75)
    long_repo, long_runtime, long_outside = (long_base / part for part in ("repo", "runtime", "outside"))
    for folder in (long_repo, long_runtime, long_outside):
        folder.mkdir(parents=True)
    long_allowed = plant(long_outside / "synthetic.key")
    long_inside = plant(long_repo / "synthetic.key")
    long_runtime_key = plant(long_runtime / "synthetic.key")
    check("long_allowed", long_repo, long_runtime, long_allowed, "LOADED")
    check("long_repo_refused", long_repo, long_runtime, long_inside, "CREDENTIAL_PERMISSIONS")
    check("long_runtime_refused", long_repo, long_runtime, long_runtime_key, "CREDENTIAL_PERMISSIONS")
    print("W1_W2_W3_W8_PROBE_COMPLETE")
