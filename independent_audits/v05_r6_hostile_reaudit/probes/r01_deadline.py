"""R01 (RA5-004): wall-clock occupancy of the REAL transport against hostile pacing, loopback only.

Each scenario calls ``HttpsTransport.send`` (production code; only the loopback address and a context trusting a
per-run minted CA are injected) with ``deadline_at = now + D`` and measures how long ``send`` held the caller, the
outcome, and the overshoot past the deadline. A peer that paces bytes just inside any per-call timeout must not
extend the exchange: the claimed invariant is ONE absolute deadline for connect, TLS, send and every receive.
usage: r01_deadline.py <candidate_dir> [D_seconds]
"""
import json, os, signal, socket, ssl, sys, threading, time
CAND = sys.argv[1]
D = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
sys.path.insert(0, CAND + "/adapters"); os.chdir(CAND)
import adapter_tests  # noqa: provenance guard + network hook (refuses non-loopback)
from adapter_tests import tls_support
from adapter_tests.support import CONFIG
from genesis_adapters.oddspapi import transport_http as th
from genesis_adapters.oddspapi.transport_http import HttpsTransport
from genesis_adapters.secrets import Secret
from genesis_adapters.config import load_policy
from genesis_adapters.clock import SystemUtcClock
from genesis_adapters.oddspapi import endpoints as ep
from datetime import datetime, timedelta, timezone
from genesis.time import iso_utc

POL = load_policy(CONFIG / "oddspapi_slice1_policy.json")
REQ = ep.build_request(ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", POL)["META_SPORTS"])
PKI = tls_support.new_pki("api.oddspapi.io")
SERVER_CTX = PKI.server_context()
BODY = b'[{"sportId":10,"sportName":"Soccer"}]'

def head(length=None, chunked=False, close=True):
    h = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
    h += "Transfer-Encoding: chunked\r\n" if chunked else "Content-Length: %d\r\n" % (len(BODY) if length is None else length)
    h += "Connection: close\r\n" if close else ""
    return (h + "\r\n").encode()

def chunked_body():
    out = b""
    for byte in BODY:
        out += b"1\r\n" + bytes([byte]) + b"\r\n"
    return out + b"0\r\n\r\n"

class Server:
    """mode: callable(conn) run after the TLS handshake (or on the raw socket when tls=False)."""
    def __init__(self, behaviour, tls=True, backlog=16, accept=True):
        self.listener = socket.create_server(("127.0.0.1", 0), backlog=backlog)
        self.port = self.listener.getsockname()[1]
        self.behaviour, self.tls, self.accept = behaviour, tls, accept
        self.stop = False; self.conns = []
        if accept:
            threading.Thread(target=self.serve, daemon=True).start()
    def serve(self):
        self.listener.settimeout(0.1)
        while not self.stop:
            try:
                raw, _ = self.listener.accept()
            except (TimeoutError, OSError):
                continue
            threading.Thread(target=self.handle, args=(raw,), daemon=True).start()
    def handle(self, raw):
        self.conns.append(raw)
        try:
            conn = SERVER_CTX.wrap_socket(raw, server_side=True) if self.tls else raw
            if self.tls:
                conn.settimeout(30)
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    data += chunk
            self.behaviour(conn)
        except Exception:
            pass
        finally:
            try:
                raw.close()
            except Exception:
                pass
    def close(self):
        self.stop = True
        self.listener.close()

def drip(conn, data, pause):
    for i in range(len(data)):
        conn.sendall(data[i:i + 1]); time.sleep(pause)

def run(name, server, *, deadline=None, clock=None, address=None, factory=None, note=""):
    clock = clock or SystemUtcClock(drift_max_ms=POL.wall_monotonic_drift_max_ms)
    t = HttpsTransport(Secret("AUD1T-0123456789abcdefghijKLMN"), credential_param="apiKey", policy=POL,
                       ssl_context=PKI.client_context(), connect_address=address or ("127.0.0.1", server.port),
                       connection_factory=factory)
    d = D if deadline is None else deadline
    deadline_at = datetime.now(timezone.utc) + timedelta(seconds=d)
    start = time.monotonic()
    result = t.send(REQ, clock=clock, deadline_at=iso_utc(deadline_at))
    held = time.monotonic() - start
    over = held - d
    rec = {"scenario": name, "deadline_s": d, "held_s": round(held, 3), "overshoot_s": round(over, 3),
           "outcome": result.outcome, "status": result.http_status,
           "error": (result.sanitized_error or {}).get("class"), "body_bytes": len(result.body or b"")}
    if note:
        rec["note"] = note
    rec["verdict"] = ("VIOLATION" if over > 0.25 else "bounded") + (
        "; RESPONSE after deadline" if result.outcome == "RESPONSE" and over > 0 else "")
    print(json.dumps(rec)); sys.stdout.flush()
    server.close()
    return rec

results = []
# 1-4: pacing after the handshake
results.append(run("slow-drip headers (1 byte / 0.15 s)", Server(lambda c: drip(c, head() + BODY, 0.15))))
results.append(run("slow-drip body Content-Length (1 byte / 0.15 s)",
                   Server(lambda c: (c.sendall(head()), drip(c, BODY, 0.15)))))
results.append(run("chunked drip (each byte its own chunk, 0.05 s per byte)",
                   Server(lambda c: (c.sendall(head(chunked=True)), drip(c, chunked_body(), 0.05)))))
results.append(run("stall before first response byte", Server(lambda c: time.sleep(D + 5))))
results.append(run("drip just inside a 1 s per-call timeout (0.9 s per byte)",
                   Server(lambda c: (c.sendall(head()), drip(c, BODY, 0.9)))))
# the request reaches the server a few ms after send() starts; sleeping D +/- delta from then lands the response
# just after / just before the deadline
results.append(run("complete response arriving ~0.05 s AFTER the deadline",
                   Server(lambda c: (time.sleep(D + 0.05), c.sendall(head() + BODY)))))
results.append(run("complete response arriving ~0.10 s BEFORE the deadline (control: RESPONSE expected)",
                   Server(lambda c: (time.sleep(D - 0.10), c.sendall(head() + BODY)))))
class LateHandshake(Server):
    """TCP accepted at once; the TLS handshake is only answered ~0.15 s before the deadline."""
    def handle(self, raw):
        time.sleep(D - 0.15)
        super().handle(raw)
results.append(run("TLS handshake answered ~0.15 s before the deadline, response sent at once",
                   LateHandshake(lambda c: c.sendall(head() + BODY))))
# 5: TLS handshake stall: TCP accepted, no TLS byte ever
results.append(run("TLS handshake stall (raw TCP, server never speaks)", Server(lambda c: time.sleep(D + 5), tls=False)))

# 6: TLS handshake drip through a byte-drip relay in front of a normal TLS server
class Relay:
    def __init__(self, upstream_port, pause):
        self.listener = socket.create_server(("127.0.0.1", 0)); self.port = self.listener.getsockname()[1]
        self.up, self.pause, self.stop = upstream_port, pause, False
        threading.Thread(target=self.serve, daemon=True).start()
    def pipe(self, a, b, dripping):
        try:
            while not self.stop:
                data = a.recv(65536)
                if not data:
                    break
                if dripping:
                    for i in range(len(data)):
                        b.sendall(data[i:i + 1]); time.sleep(self.pause)
                else:
                    b.sendall(data)
        except OSError:
            pass
    def serve(self):
        self.listener.settimeout(0.1)
        while not self.stop:
            try:
                c, _ = self.listener.accept()
            except (TimeoutError, OSError):
                continue
            u = socket.create_connection(("127.0.0.1", self.up))
            threading.Thread(target=self.pipe, args=(c, u, False), daemon=True).start()
            threading.Thread(target=self.pipe, args=(u, c, True), daemon=True).start()
    def close(self):
        self.stop = True; self.listener.close()

upstream = Server(lambda c: c.sendall(head() + BODY))
relay = Relay(upstream.port, 0.01)
class _Both:
    port = relay.port
    def close(self):
        relay.close(); upstream.close()
results.append(run("TLS handshake + everything dripped 1 byte / 10 ms by a relay", _Both()))

# 7: connect stalls on several addresses: a loopback listener whose accept queue is full drops SYNs
blocker = socket.socket(); blocker.bind(("127.0.0.1", 0)); blocker.listen(0)
bport = blocker.getsockname()[1]
fillers = []
for _ in range(8):
    s = socket.socket(); s.setblocking(False)
    try:
        s.connect(("127.0.0.1", bport))
    except BlockingIOError:
        pass
    fillers.append(s)
time.sleep(0.2)
real_getaddrinfo = socket.getaddrinfo
def many(host, port, *a, **k):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", bport))] * 5
socket.getaddrinfo = many
class _Blk:
    port = bport
    def close(self):
        pass
results.append(run("connect stalls on 5 resolved addresses (full accept queue)", _Blk(),
                   note="getaddrinfo patched to return the stalled loopback address 5 times"))
socket.getaddrinfo = real_getaddrinfo
for s in fillers:
    s.close()
blocker.close()

# 8: deadline boundary values
results.append(run("deadline already reached (D = 0)", Server(lambda c: c.sendall(head() + BODY)), deadline=0.0))
results.append(run("deadline 1 ms", Server(lambda c: c.sendall(head() + BODY)), deadline=0.001))
results.append(run("deadline 50 ms", Server(lambda c: c.sendall(head() + BODY)), deadline=0.05))

# 9: a trusted clock that steps BACKWARDS after the first readings (remaining time grows): bound must not extend
class BackwardsClock:
    def __init__(self):
        self.calls = 0; self.real = SystemUtcClock(drift_max_ms=POL.wall_monotonic_drift_max_ms)
    def now(self):
        self.calls += 1
        moment = datetime.now(timezone.utc) - (timedelta(seconds=60) if self.calls > 2 else timedelta(0))
        return iso_utc(moment)
results.append(run("trusted clock steps back 60 s after open (slow-drip body)",
                   Server(lambda c: (c.sendall(head()), drip(c, BODY, 0.15))), clock=BackwardsClock()))

# 10: EINTR storm during a slow-drip body (SIGALRM every 20 ms, handler does nothing)
signal.signal(signal.SIGALRM, lambda *a: None)
signal.setitimer(signal.ITIMER_REAL, 0.02, 0.02)
results.append(run("EINTR storm (SIGALRM every 20 ms) during a slow-drip body",
                   Server(lambda c: (c.sendall(head()), drip(c, BODY, 0.15)))))
signal.setitimer(signal.ITIMER_REAL, 0, 0)

worst = max(r["overshoot_s"] for r in results)
print(json.dumps({"python": sys.version.split()[0], "D": D, "scenarios": len(results),
                  "violations": [r["scenario"] for r in results if r["verdict"].startswith("VIOLATION")],
                  "responses_after_deadline": [r["scenario"] for r in results if "RESPONSE after" in r["verdict"]],
                  "worst_overshoot_s": worst}))
