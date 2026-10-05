"""Certification-only Windows taskkill recovery of the candidate run lock."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

candidate = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(candidate / "adapters" / "src"), str(candidate / "src")]
from genesis_adapters.oddspapi.quiescence import QuiescenceBusy, run_lock

with tempfile.TemporaryDirectory(prefix="genesis-r7-cert-lock-") as name:
    root = Path(name) / "runtime"
    ready = Path(name) / "ready"
    code = (
        "from pathlib import Path\n"
        "from genesis_adapters.oddspapi.quiescence import run_lock\n"
        "import sys,time\n"
        "with run_lock(Path(sys.argv[1])):\n"
        "    Path(sys.argv[2]).write_text('held')\n"
        "    while True: time.sleep(1)\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(candidate / "adapters" / "src"), str(candidate / "src")])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    holder = subprocess.Popen([sys.executable, "-B", "-c", code, str(root), str(ready)], env=env)
    print("HOLDER_PID", holder.pid, "RUNTIME", root, flush=True)
    try:
        for _ in range(100):
            if ready.exists():
                break
            if holder.poll() is not None:
                raise AssertionError(f"holder exited early: {holder.returncode}")
            time.sleep(0.05)
        if not ready.exists():
            raise AssertionError("holder never acquired run lock")
        print("HOLDER_READY", ready.read_text(), flush=True)
        try:
            with run_lock(root):
                raise AssertionError("second process acquired live lock")
        except QuiescenceBusy:
            print("CONTENTION", "REFUSED", flush=True)
        killed = subprocess.run(["taskkill", "/F", "/PID", str(holder.pid)], capture_output=True, text=True)
        print("TASKKILL", killed.returncode, killed.stdout.strip(), killed.stderr.strip(), flush=True)
        if killed.returncode:
            raise AssertionError("taskkill failed")
        holder.wait(timeout=10)
        print("HOLDER_EXIT", holder.returncode, flush=True)
        with run_lock(root):
            print("NEXT_PROCESS_ACQUIRED", True, flush=True)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=10)
