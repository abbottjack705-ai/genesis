from __future__ import annotations
import os, subprocess, sys, time
from pathlib import Path

repo = Path(__file__).resolve().parents[3]
child = r"""
import socket, sys, threading
sys.path[:0] = [sys.argv[1] + "/adapters/src", sys.argv[1] + "/src"]
from genesis_adapters.oddspapi.transport_http import _Connection
def blocked(*args, **kwargs):
    threading.Event().wait(3600)
socket.getaddrinfo = blocked
c = _Connection("api.oddspapi.io", 443, object(), None)
try:
    c.open(0.02)
except TimeoutError:
    print("deadline returned", flush=True)
else:
    raise AssertionError("unexpected success")
"""
env = os.environ.copy()
env["PYTHONDONTWRITEBYTECODE"] = "1"
start = time.perf_counter()
p = subprocess.run([sys.executable, "-B", "-c", child, str(repo)], cwd=repo, env=env,
                   capture_output=True, text=True, timeout=2)
elapsed = time.perf_counter() - start
print(f"child_exit={p.returncode} elapsed_s={elapsed:.3f} stdout={p.stdout.strip()}")
if p.stderr:
    print("stderr:", p.stderr.strip())
assert p.returncode == 0 and "deadline returned" in p.stdout
