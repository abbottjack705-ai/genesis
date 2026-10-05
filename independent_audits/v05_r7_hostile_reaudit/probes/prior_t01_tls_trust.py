"""T01 (RA5-003): can the PRODUCTION trust boundary be redirected to the RETIRED test CA (restored from Git history)?

The retired material (CA certificate, leaf certificate for api.oddspapi.io, and the leaf's PRIVATE KEY) is extracted
from commit b22263e at run time into the audit scratch directory only (never committed by this audit). A loopback
TLS server presents the retired leaf. Each client scenario runs in a FRESH interpreter, so a variable set "before
import" really is in the process environment from the start. The client is the unmodified production
``tls_context()`` (via ``HttpsTransport`` with only the loopback connect address injected). Loopback only.

usage: t01_tls_trust.py <candidate_dir> <python> [label]
"""
import json, os, socket, ssl, subprocess, sys, tempfile, threading, textwrap, pathlib

CAND = sys.argv[1]
PY = sys.argv[2]
LABEL = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(CAND)
SCR = pathlib.Path(os.environ.get("AUDIT_SCRATCH", tempfile.mkdtemp())) / "oldtls"
SCR.mkdir(parents=True, exist_ok=True)
GIT = os.environ.get("GIT_DIR_FOR_HISTORY", "/home/user/genesis")
OLD = "b22263e582386f04e5b7939e511757940ffdfbe0"
for name in ("test-ca.pem", "server.pem", "server.key"):
    data = subprocess.check_output(["git", "-C", GIT, "show", f"{OLD}:adapters/adapter_tests/fixtures/tls/{name}"])
    target = SCR / name
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
import hashlib
print("retired material sha256:", {n: hashlib.sha256((SCR / n).read_bytes()).hexdigest()[:16]
                                   for n in ("test-ca.pem", "server.pem", "server.key")})
# a hashed CA directory for SSL_CERT_DIR
hashed = SCR / "hashed"; hashed.mkdir(exist_ok=True)
h = subprocess.check_output(["openssl", "x509", "-noout", "-subject_hash", "-in", str(SCR / "test-ca.pem")]).decode().strip()
(hashed / f"{h}.0").write_bytes((SCR / "test-ca.pem").read_bytes())
# an OpenSSL config that tries to add the CA through the system-default SSL configuration
cnf = SCR / "evil-openssl.cnf"
cnf.write_text(textwrap.dedent(f"""
    openssl_conf = openssl_init
    [openssl_init]
    ssl_conf = ssl_sect
    [ssl_sect]
    system_default = system_default_sect
    [system_default_sect]
    VerifyCAFile = {SCR / 'test-ca.pem'}
    ChainCAFile = {SCR / 'test-ca.pem'}
    MinProtocol = TLSv1
    CipherString = DEFAULT@SECLEVEL=0
    """))

# --- the loopback server presenting the RETIRED leaf --------------------------------------------------------------
server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
server_ctx.load_cert_chain(SCR / "server.pem", SCR / "server.key")
listener = socket.create_server(("127.0.0.1", 0))
port = listener.getsockname()[1]
seen = []
def serve():
    listener.settimeout(0.2)
    while True:
        try:
            raw, _ = listener.accept()
        except (TimeoutError, OSError):
            if getattr(serve, "stop", False):
                return
            continue
        try:
            conn = server_ctx.wrap_socket(raw, server_side=True)
        except (ssl.SSLError, OSError) as exc:
            seen.append(("handshake_failed", type(exc).__name__))
            raw.close(); continue
        try:
            conn.settimeout(3)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            line = data.split(b"\r\n", 1)[0].decode("latin-1")
            seen.append(("HANDSHAKE_COMPLETED", "apiKey=" in line))
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n[]")
        except OSError:
            seen.append(("handshake_completed_then_error", None))
        finally:
            conn.close()
threading.Thread(target=serve, daemon=True).start()

CLIENT = textwrap.dedent(r'''
    import os, sys, json
    pre = {k: os.environ.get(k) for k in ("SSL_CERT_FILE", "SSL_CERT_DIR", "SSLKEYLOGFILE")}
    after = json.loads(sys.argv[3])
    for k, v in after.items():
        os.environ[k] = v                                   # set AFTER interpreter start, before tls_context()
    sys.path.insert(0, sys.argv[1] + "/adapters"); os.chdir(sys.argv[1])
    import adapter_tests                                    # provenance guard + the suite's network hook
    from adapter_tests.support import CONFIG
    from genesis_adapters.oddspapi.transport_http import HttpsTransport, tls_context
    from genesis_adapters.secrets import Secret
    from genesis_adapters.config import load_policy
    from genesis_adapters.clock import SystemUtcClock
    from genesis_adapters.oddspapi import endpoints as ep
    from datetime import datetime, timedelta, timezone
    from genesis.time import iso_utc
    pol = load_policy(CONFIG / "oddspapi_slice1_policy.json")
    req = ep.build_request(ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", pol)["META_SPORTS"])
    ctx = tls_context()
    t = HttpsTransport(Secret("AUD1T-0123456789abcdefghijKLMN"), credential_param="apiKey", policy=pol,
                       ssl_context=None, connect_address=("127.0.0.1", int(sys.argv[2])))
    r = t.send(req, clock=SystemUtcClock(drift_max_ms=pol.wall_monotonic_drift_max_ms),
               deadline_at=iso_utc(datetime.now(timezone.utc) + timedelta(seconds=8)))
    cas = [dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()]
    post = {k: os.environ.get(k) for k in ("SSL_CERT_FILE", "SSL_CERT_DIR", "SSLKEYLOGFILE")}
    print(json.dumps({"outcome": r.outcome, "status": r.http_status, "error": r.sanitized_error,
                      "check_hostname": ctx.check_hostname, "verify_mode": int(ctx.verify_mode),
                      "keylog_filename": ctx.keylog_filename, "retired_ca_in_store": any("TEST" in (n or "").upper() or "GENESIS" in (n or "").upper() for n in cas),
                      "ca_count": len(cas), "env_restored": pre == post if not after else post == {**pre, **after}}))
''')
client = SCR / "client.py"; client.write_text(CLIENT)

def scenario(name, env_before=None, env_after=None, drop=("SSL_CERT_FILE", "SSL_CERT_DIR", "SSLKEYLOGFILE")):
    env = {k: v for k, v in os.environ.items() if k not in drop and k not in ("PYTHONPATH",)}
    env["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp()
    env.update(env_before or {})
    before = len(seen)
    p = subprocess.run([PY, "-B", str(client), CAND, str(port), json.dumps(env_after or {})], env=env,
                       capture_output=True, timeout=120)
    import time; time.sleep(0.3)
    try:
        res = json.loads(p.stdout.decode().strip().splitlines()[-1])
    except Exception:
        res = {"client_error": p.stderr.decode()[-600:]}
    res["server_events"] = seen[before:]
    keylog = (env_before or {}).get("SSLKEYLOGFILE") or (env_after or {}).get("SSLKEYLOGFILE")
    if keylog:
        res["keylog_file_written"] = os.path.exists(keylog) and os.path.getsize(keylog) > 0
    breached = any(e[0] == "HANDSHAKE_COMPLETED" for e in res["server_events"])
    print(f"[{LABEL} {PY}] {name}: {'BREACH: production trusted the retired CA' if breached else 'held'}")
    print("      ", json.dumps(res))
    return breached

keylog = str(SCR / "keylog.txt")
if os.path.exists(keylog):
    os.remove(keylog)
CA = str(SCR / "test-ca.pem")
results = {}
results["S1 SSL_CERT_FILE before start"] = scenario("S1 SSL_CERT_FILE before start", {"SSL_CERT_FILE": CA})
results["S2 SSL_CERT_DIR before start"] = scenario("S2 SSL_CERT_DIR before start", {"SSL_CERT_DIR": str(hashed)})
results["S3 all three before start"] = scenario("S3 all three before start", {"SSL_CERT_FILE": CA, "SSL_CERT_DIR": str(hashed), "SSLKEYLOGFILE": keylog})
results["S4 all three set after import"] = scenario("S4 all three set after import", None, {"SSL_CERT_FILE": CA, "SSL_CERT_DIR": str(hashed), "SSLKEYLOGFILE": keylog})
results["S5 lower/mixed case names"] = scenario("S5 lower/mixed case names", {"ssl_cert_file": CA, "Ssl_Cert_File": CA, "ssl_cert_dir": str(hashed)})
results["S6 OPENSSL_CONF system_default VerifyCAFile"] = scenario("S6 OPENSSL_CONF system_default VerifyCAFile", {"OPENSSL_CONF": str(cnf)})
results["S7 no variable (control)"] = scenario("S7 no variable (control)")
print(f"[{LABEL} {PY}] SUMMARY", json.dumps(results))
serve.stop = True
