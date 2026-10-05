"""Actual .invalid Windows DNS timing plus 100 abandoned-worker soak."""
import socket, statistics, sys, threading, time, uuid
from pathlib import Path
from unittest import mock
candidate = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(candidate / "adapters" / "src"), str(candidate / "src")]
from genesis_adapters.oddspapi import transport_http as th
real = []
for _ in range(10):
    host = "r7-" + uuid.uuid4().hex + ".invalid"
    connection = th._Connection(host, 443, object(), None)
    start = time.perf_counter()
    try:
        connection.open(.05)
    except Exception as error:
        real.append((type(error).__name__, (time.perf_counter() - start) * 1000))
    else:
        raise AssertionError("unexpected connection")
print("REAL_DNS", [(kind, round(ms, 3)) for kind, ms in real], flush=True)
gate = threading.Event()
calls = {"dns": 0, "socket": 0}
def stalled(host, port, **kwargs):
    calls["dns"] += 1
    gate.wait(60)
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
def socket_called(*args, **kwargs):
    calls["socket"] += 1
    raise AssertionError("late socket")
before = {id(thread) for thread in threading.enumerate()}
samples = []
with mock.patch.object(th.socket, "getaddrinfo", stalled), mock.patch.object(th.socket, "socket", socket_called):
    for _ in range(100):
        connection = th._Connection("r7-stall.invalid", 443, object(), None)
        start = time.perf_counter()
        try:
            connection.open(.02)
        except TimeoutError:
            pass
        else:
            raise AssertionError("deadline missed")
        samples.append((time.perf_counter() - start) * 1000)
    workers = [thread for thread in threading.enumerate()
               if id(thread) not in before and thread.name == "genesis-adapters-resolve"]
    print("STALL_100", "median_ms", round(statistics.median(samples), 3),
          "max_ms", round(max(samples), 3), "live", len(workers), "socket", calls["socket"], flush=True)
    time.sleep(15)
    print("AFTER_15S", "live", sum(thread.is_alive() for thread in workers), flush=True)
    expired = th._Connection("r7-stall.invalid", 443, object(), None)
    expired._bound(0)
    try:
        expired._resolve("r7-stall.invalid", 443)
    except TimeoutError:
        pass
    else:
        raise AssertionError("expired lookup started")
    print("EXPIRED_DNS_COUNT", calls["dns"], flush=True)
    gate.set()
    for thread in workers:
        thread.join(2)
    print("AFTER_RELEASE", "live", sum(thread.is_alive() for thread in workers),
          "socket", calls["socket"], "dns", calls["dns"], flush=True)
    assert calls == {"dns": 100, "socket": 0}
    assert not any(thread.is_alive() for thread in workers)
