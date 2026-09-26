"""T6 F-2 reproducer driver around the T5 auditor's unmodified O-5 probe.

Usage: python F2_AUDITOR_PROBE_DRIVER.py <clone> <workdir> <transcript> <label>

Copies C:/Users/abbot/gv/out/probe_o5_composed_store.py into <workdir> after
checking its SHA-256 against the review's own hash list, runs it twice against
<clone> exactly as the review did (AUDIT_REPO=<clone>, PYTHONPATH=<clone>/src),
compares the two runs, and compares every variant with the review's recorded
T5 result. The probe and the recorded results are only read.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CLONE, WORK, TRANSCRIPT = (Path(p).resolve() for p in sys.argv[1:4])
LABEL = sys.argv[4]
AUDIT = Path("C:/Users/abbot/gv/out")
PROBE = "probe_o5_composed_store.py"
RECORDED = AUDIT / "probe_o5_composed_store_t5.txt"
LINES: list[str] = []


def emit(text: str = "") -> None:
    LINES.append(text)
    print(text, flush=True)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(CLONE), *args], capture_output=True, check=True, text=True,
    ).stdout


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    listed = {}
    for line in (AUDIT / "GENESIS_V04_T5_REVIEW_HASHES.sha256").read_text(encoding="ascii").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, name = line.split(" *", 1)
            listed[name] = digest
    emit(f"# T6 F-2 auditor probe transcript ({LABEL})")
    emit(f"# started {now()}")
    emit(f"# python {sys.version.split()[0]}; {platform.platform()}")
    emit(f"# {git('--version').strip()}")
    emit(f"# clone {CLONE} HEAD {git('rev-parse', 'HEAD').strip()}"
         f" branch {git('branch', '--show-current').strip()}"
         f" core.autocrlf={git('config', '--get', 'core.autocrlf').strip()}")
    status = git("status", "--porcelain=v1", "--untracked-files=all").splitlines()
    emit(f"# uncommitted paths: {len(status)}")
    for line in status:
        path = CLONE / line[3:]
        emit(f"#   {line}  sha256 {sha256(path.read_bytes()) if path.is_file() else '-'}")
    for name in ("src/genesis/selection.py", "src/genesis/decision_output.py", "src/genesis/risk.py"):
        emit(f"# {name} sha256 {sha256((CLONE / name).read_bytes())}")
    emit(f"# driver sha256 {sha256(Path(__file__).read_bytes())}")
    raw = (AUDIT / PROBE).read_bytes()
    if sha256(raw) != listed[PROBE]:
        raise SystemExit("auditor probe differs from the review hash list")
    emit(f"# auditor {PROBE} sha256 {sha256(raw)} (equals review hash list: True)")
    emit(f"# auditor recorded T5 result {RECORDED.name} sha256 {sha256(RECORDED.read_bytes())}"
         f" (equals review hash list: {sha256(RECORDED.read_bytes()) == listed[RECORDED.name]})")
    probes = WORK / "probes"
    shutil.rmtree(probes, ignore_errors=True)
    probes.mkdir(parents=True)
    script = probes / PROBE
    script.write_bytes(raw)
    emit()

    environment = dict(os.environ)
    environment.update({
        "AUDIT_REPO": str(CLONE), "PYTHONPATH": str(CLONE / "src"), "PYTHONDONTWRITEBYTECODE": "1",
    })
    runs = []
    for attempt in (1, 2):
        emit(f"$ AUDIT_REPO={CLONE} PYTHONPATH={CLONE / 'src'} python {script}   (run {attempt})")
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                                cwd=probes, env=environment)
        runs.append(result)
        emit(f"exit={result.returncode}")
        emit(result.stdout.rstrip())
        if result.stderr.strip():
            emit("stderr:")
            emit(result.stderr.rstrip())
        emit()
    same = all((runs[0].returncode, runs[0].stdout, runs[0].stderr)
               == (run.returncode, run.stdout, run.stderr) for run in runs)
    emit(f"## determinism: identical exit, stdout and stderr across runs: {same}")
    emit()

    recorded = {item["variant"]: item for item in json.loads(RECORDED.read_text(encoding="utf-8"))}
    current = {item["variant"]: item for item in json.loads(runs[0].stdout)}
    emit("## comparison with the review's recorded T5 result")
    for variant in sorted(set(recorded) | set(current)):
        before, after = recorded.get(variant, {}), current.get(variant, {})
        for key in sorted(set(before) | set(after)):
            verdict = "same" if before.get(key) == after.get(key) else "CHANGED"
            emit(f"  {variant}.{key}: {verdict}")
            if verdict == "CHANGED":
                emit(f"    T5 review: {json.dumps(before.get(key, '<absent>'))}")
                emit(f"    now      : {json.dumps(after.get(key, '<absent>'))}")
    emit()
    control = current.get("control_default_store", {})
    violations = {name: current.get(name, {}).get("VIOLATION_o5_ordering_circumvented")
                  for name in ("copied_ledger_store", "raw_log_append")}
    green = control.get("qualification_recorded") is False and not any(violations.values())
    emit(f"VERDICT F-2 ({LABEL}): control recorded={control.get('qualification_recorded')!r};"
         f" circumvented copied_ledger_store={violations['copied_ledger_store']!r},"
         f" raw_log_append={violations['raw_log_append']!r} -> "
         + ("GREEN" if green else "VIOLATION PRESENT (RED)"))
    emit(f"# finished {now()}")
    TRANSCRIPT.parent.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT.write_bytes(("\n".join(LINES) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
