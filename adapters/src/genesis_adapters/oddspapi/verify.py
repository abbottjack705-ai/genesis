"""Freeze verification (S0). Later stages add derivation re-verification and the runtime secret scan.

Nothing here imports ``genesis`` at module level: this module is imported by the test
package bootstrap before the frozen package is loaded.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import MappingProxyType

# Design section 2.1: the six frozen tree SHAs that must hold at EVERY V0.5 commit.
FROZEN_TREE_SHAS = MappingProxyType({
    "src": "51cb635bc42b993815b6c02a23c4c3ceb7d98476",
    "tests": "e90b298180068fec03ba7e2fa81957082e7fb3ce",
    "config": "abd22db01ff482a8da84634ee740ba382b68c804",
    "tools": "a0e3411edb4e068fd4708050516cb6870834e7ac",
    "DECISIONS": "cc97ec6f841f1e3fbe6dbb57c9cb6e1ac24fdb64",
    "v04_pack": "3c3c1c27d80ed6f10c32ac6605a5f438b2e7de12",
})

# SHA-256 of adapters/config/frozen_genesis_modules.json (design section 2.4).
FROZEN_MANIFEST_SHA256 = "9a50e370cb27919ee6b13e85a2b325cdaf6691c3b1168a2bc1294f1604e22fdf"


class FreezeViolation(RuntimeError):
    """A frozen tree, worktree or transcript differs from the V0.4 freeze record."""


def _git(repo: Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(["git", "--no-replace-objects", "-C", str(repo), *args],
                            capture_output=True, check=False)
    return result.returncode, result.stdout.decode("utf-8", errors="replace").strip()


def verify_frozen_trees(repo: Path, commit: str = "HEAD") -> None:
    """Every frozen top-level tree of ``commit`` has exactly its recorded object ID."""

    mismatched = []
    for tree, expected in FROZEN_TREE_SHAS.items():
        code, actual = _git(Path(repo), "rev-parse", f"{commit}:{tree}")
        if code != 0 or actual != expected:
            mismatched.append(tree)
    if mismatched:
        raise FreezeViolation("frozen tree changed: " + ", ".join(mismatched))


def verify_frozen_worktree_clean(repo: Path) -> None:
    """No modified, deleted or untracked path inside a frozen tree (FRZ-03)."""

    code, output = _git(Path(repo), "status", "--porcelain", "--", *FROZEN_TREE_SHAS)
    if code != 0:
        raise FreezeViolation("git status failed")
    if output:
        raise FreezeViolation("frozen worktree is not clean: " + str(len(output.splitlines())) + " path(s)")


_RAN = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
_OK = re.compile(r"^OK(?: \((?P<extras>[^)]*)\))?\s*$", re.MULTILINE)
_FAILED = re.compile(r"^FAILED \((?P<extras>[^)]*)\)\s*$", re.MULTILINE)


def parse_unittest_summary(text: str) -> dict:
    """``{"ran", "failures", "errors", "skipped", "ok"}`` from a unittest transcript."""

    ran = list(_RAN.finditer(text))
    if not ran:
        raise FreezeViolation("transcript has no unittest summary")
    tail = text[ran[-1].start():]
    counts = {"failures": 0, "errors": 0, "skipped": 0}
    ok = False
    match = _OK.search(tail)
    failed = _FAILED.search(tail)
    if match:
        ok = True
        extras = match.group("extras")
    elif failed:
        extras = failed.group("extras")
    else:
        raise FreezeViolation("transcript has no OK/FAILED status line")
    for part in (extras or "").split(","):
        part = part.strip()
        if "=" in part:
            key, value = part.split("=", 1)
            if key in counts and value.strip().isdigit():
                counts[key] = int(value)
    return {"ran": int(ran[-1].group(1)), **counts, "ok": ok}


def compare_frozen_transcripts(baseline_text: str, current_text: str) -> dict:
    """The frozen suite must be green with pass/skip counts identical to the baseline (FRZ-04)."""

    baseline = parse_unittest_summary(baseline_text)
    current = parse_unittest_summary(current_text)
    if not baseline["ok"]:
        raise FreezeViolation("baseline transcript is not green")
    if current != baseline:
        raise FreezeViolation(f"frozen-suite counts differ: baseline={baseline} current={current}")
    return current


def scan_runtime_for_secret(root: Path, secret, *, policy=None) -> tuple[Path, ...]:
    """Every file under ``root`` whose NAME (relative path) or CONTENT contains ``secret`` in any
    section-7.6 form. Run at stage end and at G3 (design section 7.6, test SEC-05).

    ``policy`` defaults to the pinned slice-1 policy file (fragment thresholds come from it).
    """

    import os

    from genesis_adapters import config as config_module
    from genesis_adapters import secrets as secrets_module

    base = Path(root)
    if not base.is_dir():
        raise FileNotFoundError("runtime root does not exist")
    if policy is None:
        policy = config_module.load_policy(
            Path(__file__).resolve().parents[3] / "config" / config_module.POLICY_FILE)
    scanner = secrets_module.SecretScanner(secret, policy=policy)
    hits: list[Path] = []
    for directory, _dirs, files in os.walk(base):
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(base).as_posix().encode("utf-8", "replace")
            if scanner.scan(relative).hit or scanner.scan(path.read_bytes()).hit:
                hits.append(path)
    return tuple(sorted(hits))
