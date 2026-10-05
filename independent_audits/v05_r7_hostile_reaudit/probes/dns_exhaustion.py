from __future__ import annotations
import sys, threading, time
from pathlib import Path
from unittest import mock

repo = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(repo / "adapters" / "src"), str(repo / "src")]
from genesis_adapters.oddspapi import transport_http as th

gate = threading.Event()
calls = {"resolve": 0, "socket": 0}
def stalled(host, port, **kwargs):
    calls["resolve"] += 1
    gate.wait(30)
    return [(2, 1, 6, "", ("127.0.0.1", port))]
def socket_called(*args, **kwargs):
    calls["socket"] += 1
    raise AssertionError("late resolution started a socket")

before = {id(t) for t in threading.enumerate()}
elapsed = []
with mock.patch.object(th.socket, "getaddrinfo", stalled), mock.patch.object(th.socket, "socket", socket_called):
    for _ in range(12):
        c = th._Connection("api.oddspapi.io", 443, object(), None)
        start = time.perf_counter()
        try:
            c.open(0.02)
        except TimeoutError:
            pass
        else:
            raise AssertionError("expired resolution returned success")
        elapsed.append(time.perf_counter() - start)
    live = [t for t in threading.enumerate() if id(t) not in before and t.name == "genesis-adapters-resolve"]
    print(f"12 sequential 20ms deadlines: total_s={sum(elapsed):.3f} max_one_s={max(elapsed):.3f}")
    print(f"resolver_calls={calls['resolve']} live_abandoned_workers={len(live)} socket_calls_before_release={calls['socket']}")
    expired = th._Connection("api.oddspapi.io", 443, object(), None)
    expired._bound(0)
    try:
        expired._resolve("blocked.invalid", 443)
    except TimeoutError:
        pass
    else:
        raise AssertionError("expired deadline accepted")
    print(f"expired_deadline_resolver_calls={calls['resolve']}")
    gate.set()
    for t in live:
        t.join(1)
    print(f"live_workers_after_release={sum(t.is_alive() for t in live)} socket_calls_after_release={calls['socket']}")
    assert calls == {"resolve": 12, "socket": 0}
    assert len(live) == 12
    assert all(not t.is_alive() for t in live)
