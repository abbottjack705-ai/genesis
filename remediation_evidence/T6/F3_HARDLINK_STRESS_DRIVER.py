"""T6 F-3b stress: concurrent risk writers through the real name and a toggled hard link.

Usage: python F3_HARDLINK_STRESS_DRIVER.py <clone> <workdir> <transcript> <label> <runs>

Each run builds a synthetic risk deployment from <clone>'s own test fixtures,
records one exposure, hard-links every other authority file into a mirror,
then starts two writer processes on the real deployment, two on the mirror and
one process that repeatedly creates and removes a hard link from the mirror's
risk.jsonl name to the real risk log. Every writer calls
RiskEngine.record_exposure in a loop. Afterwards the alias names are removed
and the real risk log is checked: its chain must verify, it must replay in a
restarted engine, and it must hold exactly the seed plus the rows the real
writers reported as appended.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CLONE = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(CLONE), str(CLONE / "src")]
SIDECARS = (
    ".owners.jsonl", ".risk-authority.jsonl",
    ".sqlite3", ".sqlite3-journal", ".sqlite3-wal", ".sqlite3-shm",
)


def writer(root: str, name: str, attempts: int, ready, go, results) -> None:
    from genesis.registry import RegistryConflict
    from genesis.risk import Exposure, ExposureState
    from tests.test_astra_t5_owner_binding import risk_like

    appended, refused, error = [], 0, None
    try:
        try:
            engine = risk_like(Path(root))
        finally:
            ready.put(name)  # no alias exists while engines are composed
        go.wait(60)
        for index in range(attempts):
            try:
                engine.record_exposure(
                    Exposure(f"{name}-{index}", "e" * 64, "1", ExposureState.MATCHED),
                    recorded_at="2026-01-01T00:30:00Z",
                )
                appended.append(index)
            except (RegistryConflict, OSError):
                refused += 1
    except BaseException as exc:  # reported to the driver
        error = repr(exc)
    results.put((name, appended, refused, error))


def toggler(real: str, alias: str, cycles: int, go, results) -> None:
    linked, error = 0, None
    try:
        go.wait(60)
        for _ in range(cycles):
            try:
                os.link(real, alias)
                linked += 1
            except FileExistsError:
                pass
            time.sleep(0.003)
            for _attempt in range(300):
                try:
                    os.unlink(alias)
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    time.sleep(0.002)
            time.sleep(0.003)
    except BaseException as exc:  # reported to the driver
        error = repr(exc)
    results.put(("toggler", [linked], 0, error))


def one_run(root: Path) -> dict:
    from genesis.registry import AppendOnlyJsonl, RegistryConflict
    from genesis.risk import Exposure, ExposureState
    from tests.test_astra_t5_owner_binding import risk_like
    from tests.test_remediation_r5_risk import build_risk

    real, mirror = root / "real", root / "mirror"
    f = build_risk(real)
    f["engine"].record_exposure(
        Exposure("seed", "e" * 64, "1", ExposureState.MATCHED), recorded_at="2026-01-01T00:01:00Z",
    )
    linked = []
    for path in sorted(real.rglob("*")):
        relative = path.relative_to(real)
        if path.is_dir():
            (mirror / relative).mkdir(parents=True, exist_ok=True)
        elif not path.name.endswith(SIDECARS) and relative.as_posix() != "risk.jsonl":
            (mirror / relative).parent.mkdir(parents=True, exist_ok=True)
            os.link(path, mirror / relative)
            linked.append(mirror / relative)
    context = multiprocessing.get_context("spawn")
    ready, go, results = context.Queue(), context.Event(), context.Queue()
    processes = [
        context.Process(target=writer, args=(str(where), name, 20, ready, go, results))
        for where, name in ((real, "real-0"), (real, "real-1"), (mirror, "alias-0"), (mirror, "alias-1"))
    ]
    processes.append(context.Process(
        target=toggler, args=(str(real / "risk.jsonl"), str(mirror / "risk.jsonl"), 80, go, results),
    ))
    for process in processes:
        process.start()
    outcomes = {}
    try:
        for _ in processes[:-1]:
            ready.get(timeout=180)
        go.set()
        for _ in processes:
            name, appended, refused, error = results.get(timeout=180)
            outcomes[name] = (appended, refused, error)
    finally:
        for process in processes:
            process.join(30)
            if process.is_alive():
                process.terminate()
                process.join(5)
    alias = mirror / "risk.jsonl"
    if os.path.lexists(alias):
        alias.unlink()
    for path in linked:
        path.unlink()
    report = {
        "link_cycles": outcomes["toggler"][0][0],
        "real_appended": sum(len(outcomes[n][0]) for n in ("real-0", "real-1")),
        "real_refused": sum(outcomes[n][1] for n in ("real-0", "real-1")),
        "alias_appended": sum(len(outcomes[n][0]) for n in ("alias-0", "alias-1")),
        "alias_refused": sum(outcomes[n][1] for n in ("alias-0", "alias-1")),
        "worker_errors": {n: o[2] for n, o in outcomes.items() if o[2]},
    }
    try:
        rows = AppendOnlyJsonl(real / "risk.jsonl").records()
    except RegistryConflict as exc:
        report["real_log"] = f"CORRUPTED: {exc}"
        return report
    ids = {row.get("exposure_id") for row in rows}
    expected = {"seed"} | {
        f"{n}-{i}" for n in ("real-0", "real-1") for i in outcomes[n][0]
    }
    report["alias_rows_in_real_log"] = sorted(i for i in ids if str(i).startswith("alias-"))
    try:
        replayed = {item.exposure_id for item in risk_like(real).reserved_exposures()}
        report["real_log"] = ("intact" if ids == expected == replayed
                              else f"INCONSISTENT: rows {len(ids)} expected {len(expected)}")
    except Exception as exc:  # noqa: BLE001
        report["real_log"] = f"CORRUPTED: {type(exc).__name__}: {exc}"
    return report


def main() -> None:
    work, transcript = Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    label, runs = sys.argv[4], int(sys.argv[5])
    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text, flush=True)

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(CLONE), *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    emit(f"# T6 F-3b concurrent hard-link stress ({label})")
    emit(f"# started {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    emit(f"# python {sys.version.split()[0]}; {platform.platform()}; cpus {os.cpu_count()}")
    emit(f"# clone {CLONE} HEAD {git('rev-parse', 'HEAD')}")
    for line in git("status", "--porcelain=v1", "--untracked-files=all").splitlines():
        path = CLONE / line[3:]
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "-"
        emit(f"#   {line}  sha256 {digest}")
    for name in ("src/genesis/registry.py", "src/genesis/risk.py"):
        emit(f"# {name} sha256 {hashlib.sha256((CLONE / name).read_bytes()).hexdigest()}")
    emit(f"# driver sha256 {hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}")
    emit(f"# runs {runs}: writers real-0, real-1 (real name), alias-0, alias-1 (mirror name),"
         " 20 record_exposure attempts each; toggler 80 link/unlink cycles")
    emit()
    corrupted = 0
    for run in range(1, runs + 1):
        root = work / f"run-{run}"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        report = one_run(root)
        corrupted += not report["real_log"].startswith("intact")
        emit(f"run {run:2d}: {report}")
        shutil.rmtree(root, ignore_errors=True)
    emit()
    emit(f"VERDICT ({label}): real risk log not intact in {corrupted} of {runs} runs")
    emit(f"# finished {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
