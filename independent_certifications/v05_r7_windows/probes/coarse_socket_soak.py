"""Coarse 1/4/16 ms clock soak on real loopback Windows sockets."""
import socket, statistics, sys, threading, time
from pathlib import Path
candidate = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(candidate / "adapters"), str(candidate / "adapters" / "src"), str(candidate / "src")]
from adapter_tests.test_v05_r6_deadline import T0, bounded_transport, drip, odds_request, ps
from adapter_tests.test_v05_transport_http import CoarseClock
from adapter_tests.loopback_support import LoopbackHttps, Reply
samples = {}
for phase in ("body", "headers", "handshake"):
    for tick in (1, 4, 16):
        for rep in range(2):
            server = listener = release = thread = None
            held = []
            try:
                if phase == "body":
                    server = LoopbackHttps([Reply(body=drip(20), chunks=20, pause=.4)])
                elif phase == "headers":
                    server = LoopbackHttps([Reply(body=b"[]", head_pause=.1)])
                else:
                    listener = socket.create_server(("127.0.0.1", 0))
                    release = threading.Event()
                    def accept():
                        listener.settimeout(.2)
                        while not release.is_set():
                            try:
                                held.append(listener.accept()[0])
                            except OSError:
                                continue
                    thread = threading.Thread(target=accept, daemon=True)
                    thread.start()
                address = None if server else ("127.0.0.1", listener.getsockname()[1])
                transport = bounded_transport(server, address=address)
                start = time.perf_counter()
                result = transport.send(odds_request(), clock=CoarseClock(T0, tick_ms=tick),
                                        deadline_at=ps.iso_add(T0, seconds=1))
                elapsed = time.perf_counter() - start
                overshoot_ms = (elapsed - 1) * 1000
                samples.setdefault((phase, tick), []).append(overshoot_ms)
                print("CASE", phase, "tick_ms", tick, "rep", rep, "elapsed_ms", round(elapsed * 1000, 3),
                      "overshoot_ms", round(overshoot_ms, 3), "outcome", result.outcome, flush=True)
                assert result.outcome != "RESPONSE" and elapsed < 3
            finally:
                if server:
                    server.close()
                if release:
                    release.set()
                if thread:
                    thread.join(5)
                for connection in held:
                    connection.close()
                if listener:
                    listener.close()
for key, values in samples.items():
    print("DISTRIBUTION", key, "min_ms", round(min(values), 3),
          "median_ms", round(statistics.median(values), 3), "max_ms", round(max(values), 3), flush=True)
