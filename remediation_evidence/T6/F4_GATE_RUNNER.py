"""Run T6 F-4 gate commands in an execution clone and write a byte transcript.

Usage: python F4_GATE_RUNNER.py <clone> <transcript> <title> -- CMD [ARGS] [:: CMD [ARGS]]...

The header identifies the clone (HEAD, autocrlf, every uncommitted path with
its SHA-256) and the tool under test; each command runs with the clone as its
working directory and is recorded with its merged output and exit code. The
transcript is written as UTF-8 with LF line endings.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CLONE, TRANSCRIPT = (Path(p).resolve() for p in sys.argv[1:3])
TITLE = sys.argv[3]
if sys.argv[4] != "--":
    raise SystemExit("expected -- before the commands")
COMMANDS: list[list[str]] = [[]]
for token in sys.argv[5:]:
    if token == "::":
        COMMANDS.append([])
    else:
        COMMANDS[-1].append(token)
LINES: list[str] = []


def emit(text: str = "") -> None:
    LINES.append(text)
    print(text, flush=True)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(CLONE), *args], capture_output=True, check=True, text=True,
    ).stdout.strip()


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


emit(f"# {TITLE}")
emit(f"# started {now()}")
emit(f"# python {sys.version.split()[0]}; {platform.platform()}; cpus {os.cpu_count()}")
emit(f"# {git('--version')}")
emit(f"# clone {CLONE} HEAD {git('rev-parse', 'HEAD')} branch {git('branch', '--show-current')}"
     f" core.autocrlf={git('config', '--get', 'core.autocrlf')}")
status = subprocess.run(
    ["git", "-C", str(CLONE), "status", "--porcelain=v1", "--untracked-files=all"],
    capture_output=True, check=True, text=True,
).stdout.splitlines()
emit(f"# uncommitted paths: {len(status)}")
for line in status:
    path = CLONE / line[3:]
    digest = sha256(path.read_bytes()) if path.is_file() else "-"
    emit(f"#   {line}  sha256 {digest}")
tool = CLONE / "tools" / "genesis_audit_package.py"
emit(f"# tools/genesis_audit_package.py sha256 {sha256(tool.read_bytes())}")
emit(f"# runner sha256 {sha256(Path(__file__).read_bytes())}")
failures = 0
for command in COMMANDS:
    emit()
    emit("$ " + " ".join(command))
    started = time.monotonic()
    result = subprocess.run(
        command, cwd=CLONE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    emit(result.stdout.rstrip())
    emit(f"exit={result.returncode} elapsed={time.monotonic() - started:.1f}s")
    failures += result.returncode != 0
emit()
emit(f"# commands {len(COMMANDS)}, nonzero exits {failures}")
emit(f"# finished {now()}")
TRANSCRIPT.parent.mkdir(parents=True, exist_ok=True)
TRANSCRIPT.write_bytes(("\n".join(LINES) + "\n").encode("utf-8"))
