"""T6 F-3: enumerate every risk-log write path, statically and dynamically.

Usage: python F3_WRITE_PATH_ENUMERATION.py <clone> <transcript> [unittest names...]

Static part (AST over <clone>/src/genesis):
  * every .transaction(...) / .append(...) call whose receiver names a risk
    audit log, with the builder it passes and whether read_locks are given;
  * every read-only builder those calls use, with its return statements;
  * every AppendOnlyJsonl subclass and construction;
  * every byte-level write primitive in the source tree.

Dynamic part: runs the named test modules (default: full discovery) in this
process with AppendOnlyJsonl._append_exactly, the only byte writer of any
append-only log, instrumented. Every write that reaches a risk log is recorded
with its storage class, whether its engine replayed that exact chained row
first, the public source entry point and the test that caused it. Child
processes started by tests are not instrumented and are reported as such.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import platform
import subprocess
import sys
import threading
import traceback
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CLONE, TRANSCRIPT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
NAMES = sys.argv[3:]
sys.path[:0] = [str(CLONE), str(CLONE / "src")]
LINES: list[str] = []
WRITE_PRIMITIVES = {
    "os.open", "os.write", "os.link", "os.replace", "os.rename", "os.symlink",
    "os.remove", "os.unlink", "os.truncate", "os.ftruncate", "tempfile.mkstemp",
    "tempfile.NamedTemporaryFile", "shutil.copy", "shutil.copy2", "shutil.copyfile",
    "shutil.copytree", "shutil.move", "shutil.rmtree",
}
MUTATING_METHODS = (
    ".write_bytes", ".write_text", ".unlink", ".touch", ".rmdir", ".truncate",
    ".symlink_to", ".hardlink_to",
)


def emit(text: str = "") -> None:
    LINES.append(text)
    print(text, flush=True)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(CLONE), *args], capture_output=True, check=True, text=True,
    ).stdout


def enclosing(parents: dict[ast.AST, ast.AST], node: ast.AST) -> str:
    names = []
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return ".".join(reversed(names)) or "<module>"


def static_inventory() -> None:
    emit("## static inventory of src/genesis")
    risk_calls, builders, subclasses, constructions, primitives = [], {}, [], [], []
    for path in sorted((CLONE / "src" / "genesis").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        functions = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.setdefault((enclosing(parents, node), node.name), node)
            if isinstance(node, ast.ClassDef) and any(
                ast.unparse(base).endswith("AppendOnlyJsonl") for base in node.bases
            ):
                subclasses.append(f"{path.name}:{node.lineno} class {node.name}")
            if not isinstance(node, ast.Call):
                continue
            function = ast.unparse(node.func)
            where = f"{path.name}:{node.lineno} in {enclosing(parents, node)}"
            if function.endswith("AppendOnlyJsonl") or function == "_RiskLogStorage":
                argument = ast.unparse(node.args[0]) if node.args else "<none>"
                constructions.append(f"{where}: {function}({argument})")
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"transaction", "append"}
                    and "audit_log" in ast.unparse(node.func.value)):
                builder = ast.unparse(node.args[0]) if node.args else "<none>"
                has_locks = any(keyword.arg == "read_locks" for keyword in node.keywords)
                risk_calls.append((where, f"{ast.unparse(node.func)}({builder}, "
                                          f"read_locks={'yes' if has_locks else 'no'})"))
                if isinstance(node.args[0], ast.Name):
                    scope = enclosing(parents, node)
                    builders[(path.name, scope, node.args[0].id)] = functions.get(
                        (scope, node.args[0].id)
                    )
            opens_for_write = (
                function in {"open", "io.open", "os.fdopen"} or function.endswith(".open")
            ) and any(
                isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                and set(argument.value) & set("wax+")
                for argument in [*node.args, *(k.value for k in node.keywords if k.arg == "mode")]
            )
            moves = (function.endswith((".rename", ".replace"))
                     and len(node.args) == 1 and not node.keywords)
            if (opens_for_write or moves or function in WRITE_PRIMITIVES
                    or function.endswith(MUTATING_METHODS)):
                primitives.append(f"{where}: {ast.unparse(node)[:110]}")
    emit("### calls that write or inspect a risk audit log")
    for where, call in risk_calls:
        emit(f"  {where}: {call}")
    emit("### named builders passed to those calls, with every return value")
    for (file, scope, name), node in sorted(builders.items()):
        if node is None:
            emit(f"  {file} {scope}.{name}: not a local function")
            continue
        returns = sorted({ast.unparse(item.value) if item.value is not None else "None"
                          for item in ast.walk(node) if isinstance(item, ast.Return)})
        emit(f"  {file} {scope}.{name}: returns {returns}")
    emit("### AppendOnlyJsonl subclasses")
    for item in subclasses:
        emit(f"  {item}")
    emit("### AppendOnlyJsonl / risk storage constructions")
    for item in constructions:
        emit(f"  {item}")
    emit("### byte-level write primitives")
    for item in primitives:
        emit(f"  {item}")
    emit()


def dynamic_trace() -> None:
    from genesis import registry, risk

    replayed = threading.local()
    writes: Counter = Counter()
    unexpected: list[str] = []
    original_call = risk._ReplayChecked.__call__
    original_append = registry.AppendOnlyJsonl._append_exactly

    def traced_call(self, rows):
        record = original_call(self, rows)
        if isinstance(record, dict):
            chained = registry.AppendOnlyJsonl.chained(rows, record)
            replayed.__dict__.setdefault("hashes", set()).add(chained["record_hash"])
        return record

    def traced_append(self, verified, start, line):
        guarded = isinstance(self, risk._RiskLogStorage)
        if not guarded and not self.path.name.endswith("risk.jsonl"):
            return original_append(self, verified, start, line)
        record_hash = json.loads(line)["record_hash"]
        checked = record_hash in replayed.__dict__.get("hashes", set())
        stack = traceback.extract_stack()[:-1]
        source = [frame for frame in stack if "src" in Path(frame.filename).parts
                  and Path(frame.filename).name != "registry.py"]
        entry = (f"{Path(source[0].filename).name}:{source[0].name}" if source
                 else "raw AppendOnlyJsonl writer")
        test = next((f"{Path(frame.filename).name}:{frame.name}" for frame in reversed(stack)
                     if Path(frame.filename).parent.name == "tests"
                     and frame.name.startswith("test_")), "<outside a test method>")
        storage = type(self).__name__
        replay = "replay-checked" if checked else "not replayed"
        try:
            original_append(self, verified, start, line)
        except registry.RegistryConflict:
            key = (storage, replay, entry, "refused at write")
            writes[key] += 1
            tests_by_key.setdefault(key, set()).add(test)
            raise
        key = (storage, replay, entry, "written")
        writes[key] += 1
        tests_by_key.setdefault(key, set()).add(test)
        if guarded and not checked:
            unexpected.append(f"{entry} from {test}")

    tests_by_key: dict = {}
    risk._ReplayChecked.__call__ = traced_call
    registry.AppendOnlyJsonl._append_exactly = traced_append
    loader = unittest.TestLoader()
    suite = (loader.loadTestsFromNames(NAMES) if NAMES
             else loader.discover(str(CLONE / "tests"), top_level_dir=str(CLONE)))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    risk._ReplayChecked.__call__ = original_call
    registry.AppendOnlyJsonl._append_exactly = original_append
    emit("## dynamic trace: every write that reached a risk log during the run")
    emit(f"tests run {result.testsRun}, failures {len(result.failures)}, "
         f"errors {len(result.errors)}, skipped {len(result.skipped)}")
    for (storage, replay, entry, outcome), count in sorted(writes.items()):
        emit(f"  {count:5d}  {storage:16s} {replay:15s} {outcome:17s} entry {entry}")
        for test in sorted(tests_by_key[(storage, replay, entry, outcome)])[:6]:
            emit(f"           e.g. {test}")
    emit(f"writes through the risk log storage that were not replay-checked: {len(unexpected)}")
    for item in unexpected:
        emit(f"  UNEXPECTED {item}")
    if result.failures or result.errors:
        emit("### failures and errors (the instrumented run must be clean)")
        for test, text in [*result.failures, *result.errors]:
            emit(f"  {test}: {text.strip().splitlines()[-1][:200]}")
    emit()


def main() -> None:
    emit(f"# T6 F-3 risk-log write-path enumeration")
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
