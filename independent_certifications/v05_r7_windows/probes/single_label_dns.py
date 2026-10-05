"""Safe random single-label Windows resolver fallback timing."""
import socket, sys, threading, time, uuid
from pathlib import Path
candidate = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(candidate / "adapters" / "src"), str(candidate / "src")]
from genesis_adapters.oddspapi import transport_http as th
before = {id(thread) for thread in threading.enumerate()}
for index in range(5):
    host = "r7cert" + uuid.uuid4().hex[:20]
    connection = th._Connection(host, 443, object(), None)
    start = time.perf_counter()
    try:
        connection._bound(.05)
        connection._resolve(host, 443)
    except (TimeoutError, socket.gaierror, OSError) as error:
        print("single_label", index, "outcome", type(error).__name__,
              "elapsed_ms", round((time.perf_counter() - start) * 1000, 3), flush=True)
    else:
        raise AssertionError("random single-label name unexpectedly resolved")
workers = [thread for thread in threading.enumerate()
           if id(thread) not in before and thread.name == "genesis-adapters-resolve"]
print("resolver_workers_after_calls", len(workers), flush=True)
start = time.perf_counter()
for thread in workers:
    thread.join(30)
print("resolver_workers_after_wait", sum(thread.is_alive() for thread in workers),
      "recovery_wait_ms", round((time.perf_counter() - start) * 1000, 3), flush=True)
