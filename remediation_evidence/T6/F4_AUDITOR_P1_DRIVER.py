"""T6 F-4 reproducer driver around the T5 auditor's unmodified package probe.

Usage: python F4_AUDITOR_P1_DRIVER.py <clone> <workdir> <transcript> <label>

Runs C:/Users/abbot/gv/out/probe_pkg_t5_pins.py twice against the clone's
tools/genesis_audit_package.py and the frozen T5 package, records the forged
P1 package hashes (determinism), compares every case with the auditor's
recorded exits, and compares the forged raw member with its Git blob. Two
driver cases extend P1 on the same member: D1 a line-ending-only rewrite, D2 a
raw member and its git-blobs member forged together. The auditor's probe, pins
and both packages are only read; every forgery is written under <workdir>.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

CLONE, WORK, TRANSCRIPT = (Path(p).resolve() for p in sys.argv[1:4])
LABEL = sys.argv[4]
AUDIT = Path("C:/Users/abbot/gv/out")
PROBE = AUDIT / "probe_pkg_t5_pins.py"
PINS_FILE = AUDIT / "pins.txt"
AUDITOR_RESULT = AUDIT / "probe_pkg_t5_pins.txt"
OUTPUTS = Path(
    "C:/Users/abbot/Documents/Codex/2026-09-21/goal-complete-the-project-genesis-v0/outputs"
)
NAME = "GENESIS_V04_T5_INTEGRATED_REAUDIT_6c2464e.zip"
PACKAGE = OUTPUTS / NAME
PACKAGE_SHA256 = "04becfb939863d967306e3ea472ca557f86f28127b7c040ab5e8a6dbb1683217"
W3 = Path("C:/Users/abbot/gv/w3pkg/w3.zip")
T5 = "6c2464e470fd5f82f53839492593a0c0ac1cd51f"
VICTIM = "remediation_evidence/T5/GREEN_FINAL.md"
TOOL = CLONE / "tools" / "genesis_audit_package.py"
PINS = PINS_FILE.read_text(encoding="ascii").split()
LINES: list[str] = []


def emit(text: str = "") -> None:
    LINES.append(text)
    print(text, flush=True)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(CLONE), *args], capture_output=True, check=True,
    ).stdout


def verify(path: Path, *extra: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(TOOL), "verify", "--archive", str(path), *extra],
        capture_output=True, text=True, cwd=CLONE,
    )
    return result.returncode, (result.stderr.strip() or result.stdout.strip())


def members_of(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {info.filename: archive.read(info.filename) for info in archive.infolist()}


spec = importlib.util.spec_from_file_location("genesis_audit_package_under_test", TOOL)
gap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gap)


def forge(name: str, change) -> Path:
    """Self-consistent forgery: canonical manifest re-encoding plus a fresh sidecar."""

    members = members_of(PACKAGE)
    change(members)
    manifest = json.loads(members[gap.MANIFEST_NAME])
    for row in manifest["members"]:
        raw = members[row["archive_path"]]
        row["bytes"], row["sha256"] = len(raw), sha256(raw)
    manifest["source_snapshot"] = [
        row for row in manifest["members"] if row["representation"] == "git_blob_bytes"
    ]
    members[gap.MANIFEST_NAME] = gap._manifest_bytes(manifest)
    directory = WORK / name
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    path = directory / NAME
    with zipfile.ZipFile(path, "x") as archive:
        gap._zip_write(archive, gap.MANIFEST_NAME, members[gap.MANIFEST_NAME])
        for member in sorted(key for key in members if key != gap.MANIFEST_NAME):
            gap._zip_write(archive, member, members[member])
    Path(str(path) + ".sha256").write_bytes(
        f"{sha256(path.read_bytes())}  {NAME}\n".encode("ascii")
    )
    return path


emit(f"# T6 F-4 reproducer transcript ({LABEL})")
emit(f"# started {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
emit(f"# python {sys.version.split()[0]}; {platform.platform()}")
emit(f"# {git('--version').decode().strip()}")
emit(f"# clone {CLONE}")
emit(f"#   HEAD {git('rev-parse', 'HEAD').decode().strip()}"
     f" branch {git('branch', '--show-current').decode().strip()}")
emit(f"#   core.autocrlf={git('config', '--get', 'core.autocrlf').decode().strip()}")
status = git("status", "--porcelain=v1", "--untracked-files=all").decode().splitlines()
emit(f"#   status entries: {len(status)}")
for line in status:
    path = CLONE / line[3:]
    digest = sha256(path.read_bytes()) if path.is_file() else "-"
    emit(f"#     {line}  sha256 {digest}")
emit(f"# tool under test sha256 {sha256(TOOL.read_bytes())} {TOOL}")
emit(f"# driver sha256 {sha256(Path(__file__).read_bytes())}")
emit(f"# auditor probe sha256 {sha256(PROBE.read_bytes())} {PROBE}")
emit(f"# auditor pins sha256 {sha256(PINS_FILE.read_bytes())} {PINS_FILE}")
emit(f"# auditor recorded result sha256 {sha256(AUDITOR_RESULT.read_bytes())} {AUDITOR_RESULT}")
package_hash = sha256(PACKAGE.read_bytes())
emit(f"# T5 package sha256 {package_hash} (expected {PACKAGE_SHA256}:"
     f" {package_hash == PACKAGE_SHA256})")
emit(f"# W3 package sha256 {sha256(W3.read_bytes())} {W3}")
emit()

reports = []
p1_hashes = []
for run in (1, 2):
    work = WORK / f"probe_run{run}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    emit(f"$ python {PROBE} {CLONE} {OUTPUTS} {work} {W3}")
    result = subprocess.run(
        [sys.executable, str(PROBE), str(CLONE), str(OUTPUTS), str(work), str(W3)],
        capture_output=True, text=True,
    )
    emit(f"exit={result.returncode}")
    emit(result.stdout.rstrip())
    if result.stderr.strip():
        emit("stderr: " + result.stderr.strip())
    reports.append(json.loads(result.stdout))
    forged = work / "P1_raw_content_forged" / NAME
    p1_hashes.append((sha256(forged.read_bytes()),
                      sha256(Path(str(forged) + ".sha256").read_bytes())))
    emit(f"P1 forged package sha256 {p1_hashes[-1][0]} sidecar sha256 {p1_hashes[-1][1]}")
    emit()

emit("## determinism")
emit(f"P1 forged package identical across runs: {p1_hashes[0] == p1_hashes[1]}")
emit(f"probe reports identical across runs: {reports[0] == reports[1]}")
emit()

emit("## P1 forged raw member against Git")
forged = WORK / "probe_run1" / "P1_raw_content_forged" / NAME
genuine = members_of(PACKAGE)
forged_members = members_of(forged)
blob = git("cat-file", "blob", f"{T5}:{VICTIM}")
emit(f"Git blob {T5}:{VICTIM} sha256 {sha256(blob)}")
emit(f"genuine raw-worktree member sha256 {sha256(genuine['raw-worktree/' + VICTIM])}"
     f" equals Git blob: {genuine['raw-worktree/' + VICTIM] == blob}")
emit(f"forged raw-worktree member sha256 {sha256(forged_members['raw-worktree/' + VICTIM])}"
     f" equals Git blob: {forged_members['raw-worktree/' + VICTIM] == blob}")
emit(f"forged git-blobs member unchanged: "
     f"{forged_members['git-blobs/' + VICTIM] == genuine['git-blobs/' + VICTIM]}")
code, message = verify(forged, "--repo", str(CLONE), *PINS)
emit(f"$ verify P1 --repo {CLONE} <all auditor pins>")
emit(f"exit={code}")
emit(message)
code, message = verify(forged, *PINS)
emit(f"$ verify P1 <all auditor pins> (Git-free)")
emit(f"exit={code}")
emit(message)
emit()

emit("## genuine T5 package under the tool under test")
code, message = verify(PACKAGE, "--repo", str(CLONE), *PINS)
emit(f"$ verify {PACKAGE} --repo {CLONE} <all auditor pins>")
emit(f"exit={code}")
emit(message)
code, message = verify(PACKAGE, *PINS)
emit(f"$ verify {PACKAGE} <all auditor pins> (Git-free)")
emit(f"exit={code}")
emit(message)
emit()

emit("## driver cases on the same raw member")
raw_name = "raw-worktree/" + VICTIM
blob_name = "git-blobs/" + VICTIM


def line_endings(members: dict[str, bytes]) -> None:
    members[raw_name] = members[raw_name].replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def raw_and_blob(members: dict[str, bytes]) -> None:
    changed = members[raw_name] + b"\nforged addendum\n"
    members[raw_name] = changed
    members[blob_name] = changed


driver_results = {}
for case, change in (("D1_raw_line_endings_only", line_endings),
                     ("D2_raw_and_git_blob_member_together", raw_and_blob)):
    path = forge(case, change)
    emit(f"{case}: forged package sha256 {sha256(path.read_bytes())}")
    for mode, extra in (("repo_all_pins", ("--repo", str(CLONE), *PINS)),
                        ("gitfree_all_pins", tuple(PINS))):
        code, message = verify(path, *extra)
        driver_results[f"{case}_{mode}"] = code
        emit(f"  {mode}: exit={code} {message[-200:]}")
emit()

emit("## comparison with the auditor's recorded T5 result")
auditor = json.loads(AUDITOR_RESULT.read_text(encoding="utf-8"))
for key in sorted(set(auditor) | set(reports[0])):
    before = auditor.get(key)
    after = reports[0].get(key)
    before_exit = before["exit"] if isinstance(before, dict) else before
    after_exit = after["exit"] if isinstance(after, dict) else after
    verdict = "same" if before_exit == after_exit else "CHANGED"
    emit(f"{key}: auditor={before_exit} now={after_exit} {verdict}")
emit()

p1 = reports[0]["P1_raw_content_forged_repo_all_pins"]["exit"]
emit(f"VERDICT F-4 ({LABEL}): P1_raw_content_forged_repo_all_pins exit={p1} -> "
     + ("VIOLATION PRESENT (RED): forged raw evidence content verifies with --repo and every pin"
        if p1 == 0 else "rejected (GREEN)"))
emit(f"# finished {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
TRANSCRIPT.parent.mkdir(parents=True, exist_ok=True)
TRANSCRIPT.write_bytes(("\n".join(LINES) + "\n").encode("utf-8"))
