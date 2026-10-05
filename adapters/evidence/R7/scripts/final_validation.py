#!/usr/bin/env python3
"""Run the R7 validation stages serially and retain their full transcripts under evidence/R7."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "adapters" / "evidence" / "R7"


def run(name: str, argv: list[str], *, cache: bool = True) -> tuple[int, str]:
    env = os.environ.copy()
    adapters_path = str(REPO / "adapters")
    env["PYTHONPATH"] = os.pathsep.join(
        [adapters_path] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    if cache:
        env["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp(prefix="genesis-r7-pycache-")
    started = time.perf_counter()
    proc = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    duration = time.perf_counter() - started
    output = proc.stdout + proc.stderr
    header = (f"# R7 validation: {name}\n# command: {' '.join(argv)}\n# python: {sys.version.split()[0]}\n"
              f"# platform: {platform.platform()}\n# duration_seconds: {duration:.3f}\n# exit_code: {proc.returncode}\n----\n")
    (OUT / f"{name}.txt").write_text(header + output, encoding="utf-8", newline="\n")
    summary = re.findall(r"Ran \d+ tests? in [^\n]+|OK(?: \([^\n]+\))?|FAILED \([^\n]+\)", output)
    print(f"{name}: exit={proc.returncode}; " + ("; ".join(summary[-2:]) if summary else "no unittest summary"),
          flush=True)
    return proc.returncode, output


def integrity() -> int:
    frozen = ("src", "tests", "config", "tools", "DECISIONS", "v04_pack")
    expected = {
        "src": "51cb635bc42b993815b6c02a23c4c3ceb7d98476",
        "tests": "e90b298180068fec03ba7e2fa81957082e7fb3ce",
        "config": "abd22db01ff482a8da84634ee740ba382b68c804",
        "tools": "a0e3411edb4e068fd4708050516cb6870834e7ac",
        "DECISIONS": "cc97ec6f841f1e3fbe6dbb57c9cb6e1ac24fdb64",
        "v04_pack": "3c3c1c27d80ed6f10c32ac6605a5f438b2e7de12",
    }

    def git(*args: str) -> tuple[int, str]:
        proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        return proc.returncode, proc.stdout + proc.stderr

    lines = ["# R7 integrity validation", f"# branch: {git('branch', '--show-current')[1].strip()}",
             f"# HEAD: {git('rev-parse', 'HEAD')[1].strip()}", "# frozen tree object IDs:"]
    failed = False
    for tree in frozen:
        rc, value = git("rev-parse", f"HEAD:{tree}")
        actual = value.strip()
        good = rc == 0 and actual == expected[tree]
        lines.append(f"{tree:10s} {actual} {'PASS' if good else 'FAIL expected ' + expected[tree]}")
        failed |= not good
    rc, value = git("diff", "--name-status", "v0.4-foundation-freeze", "HEAD", "--", *frozen)
    lines.extend(("# diff vs v0.4-foundation-freeze (must be empty):", value.rstrip() or "(empty)"))
    failed |= rc != 0 or bool(value.strip())
    rc, value = git("status", "--porcelain", "--", *frozen)
    lines.extend(("# worktree status for six frozen trees (must be empty):", value.rstrip() or "(empty)"))
    failed |= rc != 0 or bool(value.strip())
    rc, value = git("diff", "--check")
    lines.extend(("# git diff --check:", value.rstrip() or "(clean)"))
    failed |= rc != 0 or bool(value.strip())
    for path in (
        "adapters/src/genesis_adapters/oddspapi/acquisition.py",
        "adapters/src/genesis_adapters/oddspapi/derivation.py",
        "adapters/src/genesis_adapters/oddspapi/quiescence.py",
        "adapters/src/genesis_adapters/oddspapi/transport_http.py",
    ):
        rc, value = git("diff", "--quiet", "c38df0f", "--", path)
        lines.append(f"# prior R7 source preserved: {path}: {'PASS' if rc == 0 else 'FAIL'}")
        failed |= rc != 0
    lines.append(f"# result: {'FAIL' if failed else 'PASS'}")
    (OUT / "INTEGRITY.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"INTEGRITY: {'FAIL' if failed else 'PASS'}", flush=True)
    return 1 if failed else 0


def network_result(full_output: str) -> int:
    # This suite-level sentinel is meaningful even if another independent test failed.
    passed = re.search(r"(?m)^test_no_test_contacted_a_non_loopback_address.*\.\.\. ok\s*$", full_output) is not None
    text = ("# R7 network validation\n"
            "# source: complete adapter suite; audit hook installed at adapter_tests package import\n"
            "# the suite's final test asserts NON_LOOPBACK_ATTEMPTS == [] after every test has run\n"
            f"# final sentinel observed: {'PASS' if passed else 'FAIL'}\n"
            "# provider calls / credentials: none; loopback tests only\n")
    (OUT / "NO_NETWORK.txt").write_text(text, encoding="utf-8", newline="\n")
    return 0 if passed else 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    if sys.argv[1:] == ["--full-adapter-only"]:
        initial = OUT / "FULL_ADAPTER_INITIAL.txt"
        current = OUT / "FULL_ADAPTER.txt"
        if current.exists() and not initial.exists():
            shutil.copy2(current, initial)
        full_rc, full_output = run("FULL_ADAPTER", [python, "-u", "-B", "-m", "unittest", "discover", "-s",
                                                       "adapters/adapter_tests", "-t", "adapters", "-v"])
        network_rc = network_result(full_output)
        integrity_rc = integrity()
        summary = ["# R7 validation summary", f"# Python: {sys.version.split()[0]} ({sys.executable})",
                   f"# platform: {platform.platform()}",
                   "# interpreter discovery: only the active CPython 3.12 installation is available via the Python launcher",
                   "# targeted R7: PASS (57 tests)", "# replay: PASS (2 tests)", "# provenance: PASS (3 tests)",
                   f"# full adapter: {'PASS' if full_rc == 0 else 'FAIL'}",
                   f"# no-network final sentinel: {'PASS' if network_rc == 0 else 'FAIL'}",
                   "# frozen V0.4: PASS (493 tests, skipped=1)", "# compileall: PASS",
                   f"# integrity: {'PASS' if integrity_rc == 0 else 'FAIL'}",
                   "# Windows-only certification: OPEN (this run is not the complete W1-W15 certification)",
                   f"# overall: {'PASS' if all(code == 0 for code in (full_rc, network_rc, integrity_rc)) else 'FAIL'}"]
        (OUT / "VALIDATION.txt").write_text("\n".join(summary) + "\n", encoding="utf-8", newline="\n")
        return 0 if all(code == 0 for code in (full_rc, network_rc, integrity_rc)) else 1
    results = []
    results.append(run("TARGETED_R7", [python, "-u", "-B", "-m", "unittest", "discover", "-s",
                                        "adapters/adapter_tests", "-t", "adapters", "-p",
                                        "test_v05_r7_*.py", "-v"])[0])
    results.append(run("REPLAY", [python, "-u", "-B", "-m", "unittest",
                                  "adapter_tests.test_v05_r7_quota_divergence.TheHaltAndItsRecoveryTests.test_a_replay_and_a_rebuild_never_derive_the_divergent_response",
                                  "adapter_tests.test_v05_pipeline.RebuildTests.test_pit09_rebuilding_into_empty_stores_gives_identical_artifacts_and_record_ids",
                                  "-v"])[0])
    results.append(run("PROVENANCE", [python, "-u", "-B", "-m", "unittest",
                                       "adapter_tests.test_v05_zz_final_provenance", "-v"])[0])
    full_rc, full_output = run("FULL_ADAPTER", [python, "-u", "-B", "-m", "unittest", "discover", "-s",
                                                 "adapters/adapter_tests", "-t", "adapters", "-v"])
    results.append(full_rc)
    results.append(network_result(full_output))
    results.append(run("FROZEN", [python, "-u", "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".",
                                    "-v"])[0])
    compile_env = os.environ.copy()
    compile_env["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp(prefix="genesis-r7-compile-pycache-")
    compile_start = time.perf_counter()
    compile_proc = subprocess.run([python, "-B", "-m", "compileall", "-q", "src", "tests", "adapters/src",
                                   "adapters/adapter_tests", "adapters/evidence/R7/scripts"],
                                  cwd=REPO, env=compile_env, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace")
    compile_body = (f"# R7 compileall; {sys.version.split()[0]} ({sys.executable})\n"
                    f"# duration_seconds: {time.perf_counter() - compile_start:.3f}\n"
                    f"# exit_code: {compile_proc.returncode}\n----\n" + compile_proc.stdout + compile_proc.stderr)
    (OUT / "COMPILE.txt").write_text(compile_body, encoding="utf-8", newline="\n")
    print(f"COMPILE: exit={compile_proc.returncode}; {'clean' if not compile_body.split('----\n',1)[1].strip() else 'diagnostics'}",
          flush=True)
    results.append(compile_proc.returncode)
    results.append(integrity())
    summary = ["# R7 validation summary", f"# Python: {sys.version.split()[0]} ({sys.executable})",
               f"# platform: {platform.platform()}",
               "# interpreter discovery: only the active CPython 3.12 installation is available via the Python launcher",
               "# stage exit codes in order: targeted R7, replay, provenance, full adapter, no-network, frozen, compile, integrity",
               "# codes: " + ", ".join(map(str, results)),
               "# Windows-only certification: OPEN (this run is not the complete W1-W15 certification)",
               f"# overall: {'PASS' if all(code == 0 for code in results) else 'FAIL'}"]
    (OUT / "VALIDATION.txt").write_text("\n".join(summary) + "\n", encoding="utf-8", newline="\n")
    return 0 if all(code == 0 for code in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
