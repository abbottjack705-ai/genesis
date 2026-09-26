"""T6 F-2: enumerate qualification recording and admission paths, statically and dynamically.

Usage: python F2_CAUSALITY_ENUMERATION.py <clone> <transcript> [unittest names...]

Static part (AST over <clone>/src/genesis):
  * every call that appends a qualification record or a witness;
  * every caller of QualificationRecordStore.get_for_new_risk;
  * every transaction read-lock set naming the approval ledger, and whether it
    also names the witness log;
  * every QualificationRecordStore construction in the source tree.

Dynamic part: runs the named test modules (default: full discovery) in this
process with AppendOnlyJsonl._append_exactly and
QualificationRecordStore.get_for_new_risk instrumented, and checks that:
  * every V3 qualification row written through QualificationRecordStore.append
    already had its approval witness in that log's witness sidecar;
  * no witness row was ever written after its qualification record;
  * every qualification admitted by get_for_new_risk had a witness.
Rows written by raw storage writers are counted separately. Child processes
started by tests are not instrumented and are reported as such.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import platform
import subprocess
import sys
import traceback
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CLONE, TRANSCRIPT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
NAMES = sys.argv[3:]
sys.path[:0] = [str(CLONE), str(CLONE / "src")]
WITNESS_SUFFIX = ".approval-witness.jsonl"
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


def enclosing(parents: dict, node: ast.AST) -> str:
    names = []
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return ".".join(reversed(names)) or "<module>"


def static_inventory() -> None:
    emit("## static inventory of src/genesis")
    appends, readers, lock_sets, stores = [], [], [], []
    for path in sorted((CLONE / "src" / "genesis").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "read_locks"
                            for target in node.targets)
                    and "approvals.log" in ast.unparse(node.value)):
                lock_sets.append(
                    f"{path.name}:{node.lineno} in {enclosing(parents, node)}: witness log locked: "
                    f"{'witnesses' in ast.unparse(node.value)}"
                )
            if not isinstance(node, ast.Call):
                continue
            function = ast.unparse(node.func)
            where = f"{path.name}:{node.lineno} in {enclosing(parents, node)}"
            if function.endswith("QualificationRecordStore"):
                stores.append(f"{where}: {ast.unparse(node)[:100]}")
            if isinstance(node.func, ast.Attribute):
                receiver = ast.unparse(node.func.value)
                if node.func.attr == "get_for_new_risk":
                    readers.append(f"{where}: {function}(...)")
                if node.func.attr in {"append", "transaction"} and (
                    receiver.endswith(("qualification_records", "qualifications"))
                    or (path.name == "selection.py"
                        and receiver in {"self.log", "self.witnesses", "super()"})
                ):
                    appends.append(f"{where}: {function}(...)")
            for keyword in node.keywords:
                if keyword.arg != "read_locks":
                    continue
                text = ast.unparse(keyword.value)
                if "approvals.log" in text:
                    locked = ("witnesses" in text
                              or enclosing(parents, node) == "_ApprovalWitnessLog.transaction")
                    lock_sets.append(f"{where}: witness log locked: {locked}"
                                     + (" (it is the append target)"
                                        if "witnesses" not in text and locked else ""))
    emit("### qualification / witness append and transaction calls in selection.py and callers")
    for item in appends:
        emit(f"  {item}")
    emit("### callers of get_for_new_risk (the risk-time admission check)")
    for item in readers:
        emit(f"  {item}")
    emit("### read-lock sets naming the approval ledger")
    for item in lock_sets:
        emit(f"  {item}")
    emit("### QualificationRecordStore constructions in src")
    for item in stores or ["(none: stores are composed by callers)"]:
        emit(f"  {item}")
    emit()


def dynamic_trace() -> None:
    from genesis import registry, selection

    counts: Counter = Counter()
    violations: list[str] = []
    original_append = registry.AppendOnlyJsonl._append_exactly
    original_admit = selection.QualificationRecordStore.get_for_new_risk

    def test_name() -> str:
        for frame in reversed(traceback.extract_stack()):
            if Path(frame.filename).parent.name == "tests" and frame.name.startswith("test_"):
                return f"{Path(frame.filename).name}:{frame.name}"
        return "<outside a test method>"

    def recorded_ids(log_path: Path) -> set:
        if not log_path.exists():
            return set()
        return {row.get("qualification_record_id")
                for row in registry.AppendOnlyJsonl(log_path).records()
                if row.get("record_type") == "qualification_record"}

    def witnessed_ids(log_path: Path) -> set:
        sidecar = log_path.with_name(f"{log_path.name}{WITNESS_SUFFIX}")
        if not sidecar.exists():
            return set()
        return {row.get("qualification_record_id")
                for row in registry.AppendOnlyJsonl(sidecar).records()}

    def traced_append(self, verified, start, line):
        row = json.loads(line)
        kind = row.get("record_type")
        if kind == "qualification_record" and row.get("schema_version") == "qualification-record-v3":
            via_append = any(
                Path(frame.filename).name == "selection.py" and frame.name == "append"
                for frame in traceback.extract_stack()
            )
            witnessed = row["qualification_record_id"] in witnessed_ids(self.path)
            writer = "recording path" if via_append else "raw storage writer"
            counts[f"V3 qualification row, {writer}, witness already present: {witnessed}"] += 1
            if via_append and not witnessed:
                violations.append(f"unwitnessed recording from {test_name()}")
        elif kind == "qualification_approval_witnessed":
            log_path = self.path.with_name(self.path.name[: -len(WITNESS_SUFFIX)])
            before = row["qualification_record_id"] not in recorded_ids(log_path)
            guarded = isinstance(self, selection._ApprovalWitnessLog)
            counts[f"witness row, guarded storage: {guarded}, before its record: {before}"] += 1
            if not before:
                violations.append(f"witness after its record from {test_name()}")
        return original_append(self, verified, start, line)

    def traced_admit(self, record_id, *, at=None):
        record = original_admit(self, record_id, at=at)
        present = record_id in witnessed_ids(self.log.path)
        counts[f"get_for_new_risk admitted a V3 record, witness present: {present}"] += 1
        if not present:
            violations.append(f"admitted without witness from {test_name()}")
        return record

    registry.AppendOnlyJsonl._append_exactly = traced_append
    selection.QualificationRecordStore.get_for_new_risk = traced_admit
    loader = unittest.TestLoader()
    suite = (loader.loadTestsFromNames(NAMES) if NAMES
             else loader.discover(str(CLONE / "tests"), top_level_dir=str(CLONE)))
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=1).run(suite)
    registry.AppendOnlyJsonl._append_exactly = original_append
    selection.QualificationRecordStore.get_for_new_risk = original_admit
    emit("## dynamic trace")
    emit(f"tests run {result.testsRun}, failures {len(result.failures)}, "
         f"errors {len(result.errors)}, skipped {len(result.skipped)}")
    for key, count in sorted(counts.items()):
        emit(f"  {count:5d}  {key}")
    emit(f"causality violations: {len(violations)}")
    for item in violations:
        emit(f"  VIOLATION {item}")
    if result.failures or result.errors:
        emit("### failures and errors (the instrumented run must be clean)")
        for test, text in [*result.failures, *result.errors]:
            emit(f"  {test}: {text.strip().splitlines()[-1][:200]}")
    emit()


def main() -> None:
    emit("# T6 F-2 qualification causality enumeration")
    emit(f"# started {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    emit(f"# python {sys.version.split()[0]}; {platform.platform()}")
    emit(f"# clone {CLONE} HEAD {git('rev-parse', 'HEAD').strip()}")
    status = git("status", "--porcelain=v1", "--untracked-files=all").splitlines()
    emit(f"# uncommitted paths: {len(status)}")
    for line in status:
        path = CLONE / line[3:]
        emit(f"#   {line}  sha256 {sha256(path.read_bytes()) if path.is_file() else '-'}")
    emit(f"# script sha256 {sha256(Path(__file__).read_bytes())}")
    emit(f"# dynamic scope: {' '.join(NAMES) if NAMES else 'full discovery of tests/'}")
    emit()
    static_inventory()
    dynamic_trace()
    emit(f"# finished {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    TRANSCRIPT.parent.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT.write_bytes(("\n".join(LINES) + "\n").encode("utf-8"))


# Spawned test workers import this file as __mp_main__; only the parent runs.
if __name__ == "__main__":
    main()
