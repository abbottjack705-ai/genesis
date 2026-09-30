"""Area 11 (HA-004, HA-005): the credential loader on a REAL Windows filesystem and real ACLs.

Everything happens in a scratch directory outside the repository; the key is the test sentinel. Real ACLs
are set with ``icacls``; hard links and directory junctions need no privilege; a file symbolic link is
attempted and, if the account lacks SeCreateSymbolicLinkPrivilege, recorded as NOT RUN (never as a pass).
A table of synthetic ``icacls`` outputs (German/French principal names, inherited and DENY ACEs, unknown
lines) is fed to the loader's parser through a patched ``subprocess.run`` to test fail-closed parsing.

    python -B attacks/a11_windows_credential.py --repo <candidate>
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402


def icacls(path: Path, *args: str) -> None:
    subprocess.run(["icacls", str(path), *args], check=True, capture_output=True)


def load(repo: Path, runtime: Path, path: Path, fingerprint: str, extra_env=None):
    from genesis_adapters.credential import CredentialSource
    from genesis_adapters.errors import CredentialProblem

    env = {"GENESIS_ODDSPAPI_CREDENTIAL_FILE": str(path), **(extra_env or {})}
    try:
        CredentialSource(repo=repo, runtime_root=runtime, expected_fingerprint=fingerprint, environ=env).load()
        return "LOADED"
    except CredentialProblem as problem:
        return problem.code
    except Exception as exc:                               # anything else must still not load the key
        return "ERROR:" + type(exc).__name__


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    if sys.platform != "win32":
        c.check("A11", "Windows-only checks", False, note="NOT RUN: requires a Windows host")
        return c.finish(args.out)
    from genesis_adapters import credential
    from genesis_adapters.secrets import Secret

    fingerprint = Secret(c.SENTINEL).fingerprint
    user = subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()
    base = c.scratch("cred-")
    runtime = base / "runtime"
    runtime.mkdir()

    def fresh(name: str, data: bytes = (c.SENTINEL + "\n").encode()) -> Path:
        path = base / name
        path.write_bytes(data)
        icacls(path, "/inheritance:r", "/grant:r", f"{user}:(R,W)")
        return path

    good = fresh("good.key")
    c.check("A11", "owner-only ACL, one LF line, outside repo and runtime root -> LOADED",
            load(repo, runtime, good, fingerprint) == "LOADED", result=load(repo, runtime, good, fingerprint))
    cases = []
    p = fresh("everyone.key"); icacls(p, "/grant", "*S-1-1-0:(R)"); cases.append(("Everyone:(R) added", p))
    p = fresh("users.key"); icacls(p, "/grant", "*S-1-5-32-545:(R)"); cases.append(("BUILTIN\\Users (by SID) added", p))
    p = fresh("deny.key"); icacls(p, "/deny", "*S-1-1-0:(W)"); cases.append(("a DENY ACE for Everyone", p))
    p = fresh("inherit.key"); icacls(p, "/inheritance:e"); cases.append(("inheritance re-enabled", p))
    p = fresh("crlf.key", (c.SENTINEL + "\r\n").encode()); cases.append(("CRLF line ending (deviation 19)", p))
    p = fresh("two.key", (c.SENTINEL + "\n" + c.SENTINEL + "\n").encode()); cases.append(("two lines", p))
    p = fresh("linked.key")
    os.link(p, base / "second-name.key"); cases.append(("a second hard-link name", p))
    for label, path in cases:
        result = load(repo, runtime, path, fingerprint)
        c.check("A11", f"HA-005/7.5: {label} -> refused", result != "LOADED", result=result)
    result = load(repo, runtime, good, "0" * 12)
    c.check("A11", "fingerprint mismatch -> refused", result == "CREDENTIAL_FINGERPRINT_MISMATCH", result=result)
    result = load(repo, runtime, good, fingerprint, {"SOME_VAR": "x" + c.SENTINEL})
    c.check("A11", "key present in another environment variable -> refused", result != "LOADED", result=result)
    inside = fresh("inside-runtime.key")
    target = runtime / "inside.key"
    os.replace(inside, target)
    icacls(target, "/inheritance:r", "/grant:r", f"{user}:(R,W)")
    result = load(repo, runtime, target, fingerprint)
    c.check("A11", "credential inside the runtime root -> refused", result != "LOADED", result=result)

    # junction in an ancestor (no privilege needed): one that resolves INTO the runtime root must be refused
    junction = base / "junction-into-runtime"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(runtime)], capture_output=True)
    planted = runtime / "via-junction.key"
    planted.write_bytes((c.SENTINEL + "\n").encode())
    icacls(planted, "/inheritance:r", "/grant:r", f"{user}:(R,W)")
    result = load(repo, runtime, junction / planted.name, fingerprint)
    c.check("A11", "HA-004: credential reached through a junction that resolves into the runtime root -> refused",
            junction.exists() and result != "LOADED", result=result, junction_made=junction.exists())
    subprocess.run(["cmd", "/c", "rmdir", str(junction)], capture_output=True)

    # real file symbolic link (needs SeCreateSymbolicLinkPrivilege or Developer Mode)
    link = base / "symlink.key"
    try:
        os.symlink(good, link)
        made = True
    except OSError as exc:
        made = False
        reason = f"{type(exc).__name__} winerror={getattr(exc, 'winerror', None)}"
    if made:
        result = load(repo, runtime, link, fingerprint)
        c.check("A11", "HA-004: a real file symbolic link -> refused", result != "LOADED", result=result)
    else:
        c.check("A11", "HA-004: a real file symbolic link -> refused", False,
                note="NOT RUN on this account (no SeCreateSymbolicLinkPrivilege / Developer Mode): " + reason)

    # HA-005: parser fail-closed over synthetic icacls outputs (patched subprocess in the loader only)
    who = user.lower()
    table = [
        ("de-DE extra principal", f"{{p}} {user}:(F)\n     VORDEFINIERT\\Administratoren:(I)(F)\n\nErfolgreich verarbeitet: 1 Dateien", False),
        ("fr-FR extra principal", f"{{p}} {user}:(F)\n     AUTORITE NT\\Système:(I)(F)\n\n1 fichiers correctement traités", False),
        ("only the user, localized summary line", f"{{p}} {user}:(F)\n\nErfolgreich verarbeitet: 1 Dateien", True),
        ("user plus an unresolvable SID", f"{{p}} {user}:(F)\n     S-1-5-21-1-2-3-1001:(R)\n", False),
        ("user plus a DENY line", f"{{p}} {user}:(F)\n     Jeder:(DENY)(W)\n", False),
        ("unknown line shape only", "{p} something unexpected\n", False),
        ("empty output", "", False),
    ]
    original = credential.subprocess.run
    for label, text, expect_ok in table:
        def fake(argv, **kw):
            if argv and argv[0] == "icacls":
                return SimpleNamespace(returncode=0, stdout=text.replace("{p}", argv[1]), stderr="")
            return original(argv, **kw)
        credential.subprocess.run = fake
        try:
            result = load(repo, runtime, good, fingerprint)
        finally:
            credential.subprocess.run = original
        ok = (result == "LOADED") == expect_ok
        c.check("A11", f"HA-005 parser: {label} -> {'LOADED' if expect_ok else 'refused'}", ok, result=result)
    c.remove(base)
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
