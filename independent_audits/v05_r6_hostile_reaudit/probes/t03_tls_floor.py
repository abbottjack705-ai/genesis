"""T03 (RA6-003 note): the production context's protocol floor per interpreter, with and without an environment
OPENSSL_CONF that lowers MinProtocol, and whether a TLS 1.0-only loopback server gets past protocol negotiation
(the handshake still fails on the certificate: production never trusts the minted CA). usage: t03_tls_floor.py <cand>"""
import os, sys, ssl, socket, threading, json, tempfile
CAND = sys.argv[1]
sys.path.insert(0, CAND + "/adapters"); os.chdir(CAND)
import adapter_tests  # noqa
from adapter_tests import tls_support
from genesis_adapters.oddspapi.transport_http import tls_context
ctx = tls_context()
pki = tls_support.new_pki("api.oddspapi.io")
srv_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
srv_ctx.load_cert_chain(pki.cert_file, pki.key_file)
try:
    srv_ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    srv_ctx.minimum_version = ssl.TLSVersion.TLSv1
    srv_ctx.maximum_version = ssl.TLSVersion.TLSv1
except Exception as exc:
    print("server TLS1.0 setup:", exc)
lst = socket.create_server(("127.0.0.1", 0)); port = lst.getsockname()[1]
def serve():
    raw, _ = lst.accept()
    try:
        srv_ctx.wrap_socket(raw, server_side=True)
    except Exception:
        pass
    raw.close()
threading.Thread(target=serve, daemon=True).start()
s = socket.create_connection(("127.0.0.1", port), timeout=5)
try:
    ctx.wrap_socket(s, server_hostname="api.oddspapi.io"); result = "HANDSHAKE COMPLETED"
except ssl.SSLCertVerificationError as exc:
    result = "negotiated, then certificate refused (%s)" % exc.verify_message
except ssl.SSLError as exc:
    result = "protocol refused (%s)" % exc.reason
print(json.dumps({"python": sys.version.split()[0], "OPENSSL_CONF": os.environ.get("OPENSSL_CONF"),
                  "minimum_version": str(ctx.minimum_version), "tls1_0_only_server": result}))
