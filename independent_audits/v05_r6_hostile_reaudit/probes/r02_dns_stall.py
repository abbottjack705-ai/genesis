"""R02 (RA5-004 disclosed residual): can name resolution hold the transport past the absolute deadline?

Run INSIDE `unshare -rmn` (new user, mount and network namespaces: only `lo`, nothing external is reachable). The
script brings `lo` up, bind-mounts a resolv.conf naming a fake DNS server on 127.0.0.1:53 that receives queries and
never answers (a stalled resolver), then calls the production ``HttpsTransport.send`` with a connection factory that
builds the production ``_Connection`` for the harmless name ``genesis-audit-stall.invalid`` (the pinned provider host
name is never resolved), deadline D. Also measured: a resolver that answers slowly (just under the stub timeout).
usage (outer):  unshare -rmn python3 r02_dns_stall.py <candidate_dir> [D] [resolv-options]
"""
import fcntl, json, os, socket, struct, subprocess, sys, tempfile, threading, time
CAND = sys.argv[1]
D = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
OPTIONS = sys.argv[3] if len(sys.argv) > 3 else ""

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
fcntl.ioctl(s, 0x8914, struct.pack("16sh", b"lo", 0x1 | 0x40))           # lo up
t = socket.socket(); t.settimeout(1)
try:
    t.connect(("1.1.1.1", 443)); print("ISOLATION FAILED: external reachable"); sys.exit(2)
except OSError as exc:
    print("isolation: external unreachable (errno %s)" % exc.errno)

resolv = tempfile.NamedTemporaryFile("w", delete=False, suffix=".conf")
NS = ["127.0.0.1", "127.0.0.2", "127.0.0.3"] if os.environ.get("R02_THREE_NAMESERVERS") else ["127.0.0.1"]
resolv.write("".join(f"nameserver {ns}\n" for ns in NS) + (f"options {OPTIONS}\n" if OPTIONS else "")); resolv.close()
subprocess.check_call(["mount", "--bind", resolv.name, "/etc/resolv.conf"])
for name in ("/etc/hosts",):
    hosts = tempfile.NamedTemporaryFile("w", delete=False); hosts.write("127.0.0.1 localhost\n"); hosts.close()
    subprocess.check_call(["mount", "--bind", hosts.name, name])
print("resolv.conf:", open("/etc/resolv.conf").read().replace("\n", " | "))

queries = []
MODE = {"answer_after": None}
def dns_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); srv.bind(("0.0.0.0", 53))     # every loopback address
    while True:
        data, peer = srv.recvfrom(4096)
        queries.append(time.monotonic())
        delay = MODE["answer_after"]
        if delay is not None:
            def answer(data=data, peer=peer, delay=delay):
                time.sleep(delay)
                # NXDOMAIN answer for the query (same id, QR + RCODE 3, question copied)
                reply = data[:2] + b"\x81\x83" + data[4:6] + b"\x00\x00\x00\x00\x00\x00" + data[12:]
                srv.sendto(reply, peer)
            threading.Thread(target=answer, daemon=True).start()
threading.Thread(target=dns_server, daemon=True).start()
time.sleep(0.2)

sys.path.insert(0, CAND + "/adapters"); os.chdir(CAND)
os.environ["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp()
# NOT importing the adapter_tests package: its audit hook refuses the very resolution this probe measures. Safety is
# the namespace itself (only `lo`; external connect verified unreachable above) and the .invalid name.
import importlib.util, pathlib
sys.path[:0] = [CAND + "/src", CAND + "/adapters/src"]
spec = importlib.util.spec_from_file_location("tls_support", CAND + "/adapters/adapter_tests/tls_support.py")
tls_support = importlib.util.module_from_spec(spec); sys.modules["tls_support"] = tls_support; spec.loader.exec_module(tls_support)
CONFIG = pathlib.Path(CAND) / "adapters" / "config"
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

def factory(host, port, context, address):
    return th._Connection("genesis-audit-stall.invalid", port, context, None)    # production class, harmless name

def attempt(label):
    queries.clear()
    tr = HttpsTransport(Secret("AUD1T-0123456789abcdefghijKLMN"), credential_param="apiKey", policy=POL,
                        ssl_context=PKI.client_context(), connection_factory=factory)
    start = time.monotonic()
    r = tr.send(REQ, clock=SystemUtcClock(drift_max_ms=POL.wall_monotonic_drift_max_ms),
                deadline_at=iso_utc(datetime.now(timezone.utc) + timedelta(seconds=D)))
    held = time.monotonic() - start
    rec = {"scenario": label, "deadline_s": D, "held_s": round(held, 2), "overshoot_s": round(held - D, 2),
           "outcome": r.outcome, "error": (r.sanitized_error or {}).get("class"), "dns_queries_seen": len(queries),
           "verdict": "VIOLATION (writer held past the deadline)" if held - D > 0.25 else "bounded"}
    print(json.dumps(rec)); sys.stdout.flush()

MODE["answer_after"] = None
attempt("resolver never answers (stub defaults%s)" % (", " + OPTIONS if OPTIONS else ""))
MODE["answer_after"] = 4.5
attempt("resolver answers NXDOMAIN after 4.5 s")
