"""T5 N1 platform rerun: the clean-process scan must not scale with live functions.

Found when rerunning the protected suites on the target Windows / CPython
3.12.10: ``require_clean`` resolved the source path of every live function
(about 3,500 in a worker) with ``os.path.realpath`` and then tested it against
every root with ``Path.is_relative_to``: most of a second per scan on Windows,
two or three scans per request. Under load a trivial program then
exceeded the fixed 10 s research timeout. That fails closed, but it consumes a
nonrefundable protected attempt and made retained R9 tests intermittent. The
timeout itself is deliberately bounded (a retained S5 test requires an 11 s
program to time out), so the scan must be cheap instead: each distinct source
path is resolved and classified once per scan. The scan runs only while no
research code is executing, so this does not change what it accepts or rejects.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
PROBE = r"""
import gc, json, os, sys
from pathlib import Path
from types import FunctionType, ModuleType
sys.path.insert(0, sys.argv[1])
import genesis.protected_research_worker as worker
calls = []
real = os.path.realpath
def counting(path, *args, **kwargs):
    calls.append(path)
    return real(path, *args, **kwargs)
os.path.realpath = counting
inside_calls = []
real_inside = worker._inside
def counting_inside(path, roots):
    inside_calls.append(path)
    return real_inside(path, roots)
worker._inside = counting_inside
def main():
    # Everything after the baseline stays local: new module globals would be
    # (correctly) reported as changed trusted state.
    baseline = worker._InterpreterBaseline((Path(sys.argv[2]).resolve(),))
    calls.clear()
    inside_calls.clear()
    baseline.require_clean(None)
    live = [item for item in gc.get_objects() if isinstance(item, (FunctionType, ModuleType))]
    files = {item.__code__.co_filename for item in live if isinstance(item, FunctionType)}
    files |= {vars(item).get("__file__") for item in live if isinstance(item, ModuleType)}
    files = {value for value in files if isinstance(value, str)}
    first = {"realpath_calls": len(calls), "distinct_paths": len(set(calls)),
             "root_checks": len(inside_calls), "distinct_checked": len(set(inside_calls)),
             "live_functions": sum(isinstance(item, FunctionType) for item in live),
             "distinct_source_files": len(files)}
    calls.clear()
    inside_calls.clear()
    baseline.require_clean(None)
    first["repeat_realpath_calls"] = len(calls)
    first["repeat_root_checks"] = len(inside_calls)
    print(json.dumps(first))
main()
"""


class T5WorkerScanCostTests(unittest.TestCase):
    def test_clean_process_scan_resolves_each_source_path_once(self):
        with tempfile.TemporaryDirectory() as roots:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-c", PROBE, str(SOURCE_ROOT), roots],
                capture_output=True, text=True, timeout=120, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertGreater(observed["live_functions"], observed["distinct_source_files"])
        self.assertEqual(
            observed["realpath_calls"], observed["distinct_paths"],
            f"clean-process scan resolved a source path more than once: {observed}",
        )
        self.assertEqual(
            observed["root_checks"], observed["distinct_checked"],
            f"clean-process scan re-checked a source path against the roots: {observed}",
        )
        self.assertGreater(observed["repeat_realpath_calls"], 0)
        self.assertEqual(
            observed["repeat_root_checks"], 0,
            f"unchanged canonical source paths were re-checked across scans: {observed}",
        )


if __name__ == "__main__":
    unittest.main()
