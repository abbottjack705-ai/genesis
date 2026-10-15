#!/usr/bin/env python3
"""Deterministic, resource-constrained sharding of a unittest package with exact coverage reconciliation.

The adapter monolithic full-suite run is known to exceed this host's memory, so it is never used as
evidence. Instead: discover a canonical inventory of test ids without running them, split it into
contiguous shards, run each shard serially in a fresh interpreter, and reconcile that every inventoried
test ran exactly once. The verdict is always labelled SHARDED, never MONOLITHIC.

  python -B autonomy/shard_tests.py run --top adapters --start adapter_tests --shards 8 --out DIR
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True


def _isolated_env() -> dict:
    """The adapter suite's provenance guard needs -B and a fresh PYTHONPYCACHEPREFIX in every interpreter."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp(prefix="genesis-pyc-")
    return env


def _run_isolated(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), *args], env=_isolated_env(),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def _flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _flatten(test)
        else:
            yield test


def _discover(top: str, start: str, pattern: str) -> dict:
    sys.path.insert(0, str(Path(top).resolve()))
    suite = unittest.TestLoader().discover(start_dir=start, pattern=pattern, top_level_dir=top)
    tests = list(_flatten(suite))
    failed = [t.id() for t in tests if type(t).__name__ == "_FailedTest"]
    ids = [t.id() for t in tests if type(t).__name__ != "_FailedTest"]
    return {"ids": sorted(ids), "count_discovered": len(tests), "import_failures": failed,
            "duplicates": sorted({i for i in ids if ids.count(i) > 1})}


def inventory(top: str, start: str, pattern: str = "test*.py") -> dict:
    """Canonical list of test ids, discovered in an isolated child without running anything.

    Import failures (including the adapter provenance guard refusing) are reported, never hidden.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        out = Path(tmp) / "inventory.json"
        proc = _run_isolated(["_inventory", "--top", top, "--start", start, "--pattern", pattern,
                              "--out", str(out)])
        if proc.returncode != 0 or not out.exists():
            return {"ids": [], "count_discovered": 0, "duplicates": [],
                    "import_failures": [f"inventory exited {proc.returncode}: {proc.stderr.strip()[-600:]}"]}
        return json.loads(out.read_text(encoding="utf-8"))


def plan(ids: list[str], shards: int) -> list[list[str]]:
    """Contiguous, deterministic split of the sorted inventory. Every id lands in exactly one shard."""
    if shards < 1:
        raise ValueError("shards must be at least 1")
    if not ids:
        return []
    size = math.ceil(len(ids) / shards)
    return [ids[i:i + size] for i in range(0, len(ids), size)]


def reconcile(inventory_ids: list[str], shard_results: list[dict], expected_skips: set[str]) -> dict:
    """Exact coverage: every inventoried id executed once; only expected skips may be skipped."""
    executed = [r["id"] for shard in shard_results for r in shard.get("results", [])]
    counts = {"ok": 0, "failure": 0, "error": 0, "skipped": 0}
    unexpected_skips, failures = [], []
    for shard in shard_results:
        for r in shard.get("results", []):
            counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
            if r["outcome"] == "skipped" and r["id"] not in expected_skips:
                unexpected_skips.append(r["id"])
            if r["outcome"] in ("failure", "error"):
                failures.append({"id": r["id"], "outcome": r["outcome"], "detail": r.get("detail", "")})
    missing = sorted(set(inventory_ids) - set(executed))
    extra = sorted(set(executed) - set(inventory_ids))
    duplicated = sorted({i for i in executed if executed.count(i) > 1})
    verdict = "PASS" if not (missing or extra or duplicated or unexpected_skips or failures) else "FAIL"
    return {"mode": "SHARDED", "monolithic": False, "inventory": len(inventory_ids), "executed": len(executed),
            "counts": counts, "missing": missing, "extra": extra, "duplicated": duplicated,
            "unexpected_skips": sorted(unexpected_skips), "failures": failures, "verdict": verdict}


def _child(top: str, ids_file: str, result_file: str) -> int:
    sys.path.insert(0, str(Path(top).resolve()))
    ids = [line for line in Path(ids_file).read_text(encoding="utf-8").splitlines() if line]
    suite = unittest.defaultTestLoader.loadTestsFromNames(ids)

    class Collector(unittest.TestResult):
        def __init__(self):
            super().__init__()
            self.rows = {}

        def _record(self, test, outcome, detail=""):
            self.rows[test.id()] = {"id": test.id(), "outcome": outcome, "detail": detail[-2000:]}

        def addSuccess(self, test):
            super().addSuccess(test)
            self._record(test, "ok")

        def addFailure(self, test, err):
            super().addFailure(test, err)
            self._record(test, "failure", self._exc_info_to_string(err, test))

        def addError(self, test, err):
            super().addError(test, err)
            self._record(test, "error", self._exc_info_to_string(err, test))

        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            self._record(test, "skipped", reason)

    result = Collector()
    suite.run(result)
    rows = [result.rows.get(i, {"id": i, "outcome": "error", "detail": "test did not report"}) for i in ids]
    Path(result_file).write_text(json.dumps({"results": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def run_sharded(top: str, start: str, pattern: str, shards: int, out: Path, expected_skips: set[str]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    inv = inventory(top, start, pattern)
    (out / "INVENTORY.json").write_text(json.dumps(inv, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if inv["import_failures"] or inv["duplicates"]:
        report = {"mode": "SHARDED", "monolithic": False, "verdict": "FAIL",
                  "reason": "inventory is not clean", "import_failures": inv["import_failures"],
                  "duplicates": inv["duplicates"]}
        (out / "RECONCILIATION.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report
    results = []
    for index, chunk in enumerate(plan(inv["ids"], shards)):
        ids_file = out / f"shard-{index:03d}.ids.txt"
        result_file = out / f"shard-{index:03d}.json"
        ids_file.write_text("\n".join(chunk) + "\n", encoding="utf-8")
        proc = _run_isolated(["_child", "--top", top, "--ids", str(ids_file), "--result", str(result_file)])
        (out / f"shard-{index:03d}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
        if result_file.exists():
            results.append(json.loads(result_file.read_text(encoding="utf-8")))
        else:
            results.append({"results": [{"id": i, "outcome": "error", "detail": f"shard exited {proc.returncode}"}
                                        for i in chunk]})
    report = reconcile(inv["ids"], results, expected_skips)
    (out / "RECONCILIATION.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--top", required=True)
    run.add_argument("--start", required=True)
    run.add_argument("--pattern", default="test*.py")
    run.add_argument("--shards", type=int, required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--expected-skips", default=None, help="JSON list of test ids that may be skipped")
    child = sub.add_parser("_child")
    child.add_argument("--top", required=True)
    child.add_argument("--ids", required=True)
    child.add_argument("--result", required=True)
    inv = sub.add_parser("_inventory")
    inv.add_argument("--top", required=True)
    inv.add_argument("--start", required=True)
    inv.add_argument("--pattern", default="test*.py")
    inv.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "_child":
        return _child(args.top, args.ids, args.result)
    if args.cmd == "_inventory":
        Path(args.out).write_text(json.dumps(_discover(args.top, args.start, args.pattern), indent=2) + "\n",
                                  encoding="utf-8")
        return 0
    skips = set(json.loads(Path(args.expected_skips).read_text(encoding="utf-8"))) if args.expected_skips else set()
    report = run_sharded(args.top, args.start, args.pattern, args.shards, Path(args.out), skips)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
