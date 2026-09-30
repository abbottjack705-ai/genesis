"""Area 15: independent mutation smoke of security-critical lines (auditor-chosen mutants).

Each mutant is applied to a COPY of the candidate working tree (never the candidate clone), the candidate's
own relevant test modules are run, and the mutant must be KILLED (non-zero exit). The unmutated copy must
pass the same modules first, or the mutant is reported INVALID. A surviving mutant is a test-quality finding.

    python -B attacks/a15_mutation.py --repo <candidate> [--only M01,M05] [--out a15.json]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

PKG = "adapters/src/genesis_adapters/"
MUTANTS = [
    ("M01", "acquisition: a known attempt is no longer answered as a duplicate (A-2/HA-001)",
     PKG + "oddspapi/acquisition.py", "        if existing is not None:\n            return self._duplicate(",
     "        if False:\n            return self._duplicate(", ["test_v05_acquisition", "test_v05_emit_crash"]),
    ("M02", "reader: expired newer capture no longer blocks an older price (HA-002)",
     PKG + "oddspapi/reader.py", "    if _newer_capture_exists(stores, entity_id, source, head, point):",
     "    if False and _newer_capture_exists(stores, entity_id, source, head, point):", ["test_v05_reader"]),
    ("M03", "boundary guard W1 off by one (< becomes <=)",
     PKG + "oddspapi/acquisition.py", "    if not reach < next_day:", "    if not reach <= next_day:",
     ["test_v05_boundary"]),
    ("M04", "transport swallows KeyboardInterrupt/SystemExit",
     PKG + "oddspapi/transport_http.py", "        if control is not None:\n            raise control from None",
     "        if control is not None:\n            pass", ["test_v05_tx01", "test_v05_transport_http"]),
    ("M05", "credential loader accepts a second hard-link name",
     PKG + "credential.py", " and opened.st_nlink == 1", "", ["test_v05_credential"]),
    ("M06", "PIT resume compares ready_at too (HA-011: a mid-append crash would halt forever)",
     PKG + "oddspapi/emit.py", "            if dataclasses.replace(existing, ready_at=record.ready_at) != record:",
     "            if existing != record:", ["test_v05_emit_crash"]),
    ("M07", "secret detector loses the UTF-16 BE form",
     PKG + "secrets.py", '("UTF16", "utf-16-le"), ("UTF16", "utf-16-be"),', '("UTF16", "utf-16-le"),',
     ["test_v05_secrets", "test_v05_secret_capture"]),
    ("M08", "raw capture stops scanning response headers",
     PKG + "oddspapi/raw_capture.py", "        if self.scanner is not None:\n            for name, value in result.headers:",
     "        if False:\n            for name, value in result.headers:", ["test_v05_secret_capture", "test_v05_raw_capture"]),
    ("M09", "reader drops the published_at <= D parity check",
     PKG + "oddspapi/reader.py",
     "    if observation.publisher_timestamp is not None and parse_utc(observation.publisher_timestamp) > point:",
     "    if False:", ["test_v05_reader"]),
    ("M10", "expected scope is always empty (HA-012 failure mode)",
     PKG + "oddspapi/scope.py", "        if record.admissible_at(decision_at):", "        if False:",
     ["test_v05_emit", "test_v05_pit"]),
    ("M11", "gzip decoder accepts trailing data after the member",
     PKG + "oddspapi/raw_capture.py", " or not stream.eof or stream.unused_data:", " or not stream.eof:",
     ["test_v05_secret_capture", "test_v05_raw_capture"]),
    ("M12", "CLI accepts a test CA without a loopback address",
     PKG + "cli.py", "    if args.ca_file and address is None:", "    if False:", ["test_v05_cli"]),
    ("M13", "G2 call budget no longer enforced",
     PKG + "oddspapi/authority.py",
     '            if self.sent_count(record["request_hashes"], record["valid_from"]) >= record["max_calls"]:',
     "            if False:", ["test_v05_authority"]),
    ("M14", "quota time regression no longer halts (HA-009)",
     PKG + "oddspapi/acquisition.py", '        if charge.reason == "quota_event_time_regressed":', "        if False:",
     ["test_v05_acquisition", "test_v05_quota_gate"]),
    ("M15", "provenance guard stops hashing loaded module bytes",
     PKG + "provenance_guard.py",
     '        if blob_sha1(data) != entry["blob_sha1"] or sha256_hex(data) != entry["sha256"]:', "        if False:",
     ["test_v05_freeze"]),
    ("M16", "T1 is no longer re-read past T0 on a coarse clock",
     PKG + "oddspapi/transport_http.py",
     "    while parse_utc(reading) <= parse_utc(earlier) and time.monotonic_ns() < give_up:", "    while False:",
     ["test_v05_transport_http"]),
    ("M17", "invalidation T_inv tie is no longer re-read",
     PKG + "oddspapi/emit.py", "        while parse_utc(t_inv) <= floor:", "        while False:",
     ["test_v05_invalidation"]),
    ("M18", "reconciliation always claims NOT_SENT",
     PKG + "oddspapi/acquisition.py",
     'send_state="MAY_HAVE_BEEN_SENT" if item.state == "SENT" else "NOT_SENT")', 'send_state="NOT_SENT")',
     ["test_v05_acquisition"]),
]


def run_modules(tree: Path, modules: list[str], timeout: int) -> tuple[int, float, str]:
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="pyc-mut-"), PYTHONDONTWRITEBYTECODE="1")
    started = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, "-B", "-m", "unittest", *[f"adapter_tests.{m}" for m in modules]],
                              cwd=tree / "adapters", env=env, capture_output=True, text=True, timeout=timeout)
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or [""]
        return proc.returncode, time.monotonic() - started, tail[0]
    except subprocess.TimeoutExpired:
        return -9, time.monotonic() - started, "TIMEOUT"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    tree = c.scratch("mut-") / "tree"
    shutil.copytree(repo, tree, ignore=shutil.ignore_patterns(".git", "__pycache__", "runtime", "*.pyc"))
    wanted = {m.strip() for m in args.only.split(",") if m.strip()}
    baseline_cache: dict[tuple, tuple] = {}
    for mid, label, rel, old, new, modules in MUTANTS:
        if wanted and mid not in wanted:
            continue
        key = tuple(modules)
        if key not in baseline_cache:
            baseline_cache[key] = run_modules(tree, modules, args.timeout)
        base_rc, base_s, base_tail = baseline_cache[key]
        target = tree / rel
        original = target.read_bytes()
        text = original.decode("utf-8")
        if text.count(old) != 1:
            c.check("A15", f"{mid} {label}", False, note=f"MUTANT NOT APPLICABLE (pattern count {text.count(old)})")
            continue
        if base_rc != 0:
            c.check("A15", f"{mid} {label}", False, note="INVALID: unmutated modules fail", baseline=base_tail)
            continue
        try:
            target.write_bytes(text.replace(old, new).encode("utf-8"))
            rc, secs, tail = run_modules(tree, modules, args.timeout)
        finally:
            target.write_bytes(original)
        c.check("A15", f"{mid} {label} -> KILLED", rc != 0, exit=rc, seconds=round(secs, 1), last_line=tail,
                modules=modules)
    shutil.rmtree(tree.parent, ignore_errors=True)
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
