"""AREA M: can the PRODUCTION tls_context() be made to trust the committed test CA without any code change?"""
import os
import pathlib
CAND0 = os.environ.get("CAND_DIR") or str(pathlib.Path(__file__).resolve().parents[3])
CAFILE = CAND0 + "/adapters/adapter_tests/fixtures/tls/test-ca.pem"
if not os.environ.get("AUDIT_P70_CONTROL"):      # control run: variable NOT set
    os.environ["SSL_CERT_FILE"] = CAFILE          # an environment variable only: no code, no CLI option
from boot import *
from adapter_tests.loopback_support import LoopbackHttps, Reply
from genesis_adapters.oddspapi.transport_http import HttpsTransport, tls_context
from genesis_adapters.secrets import Secret
from genesis_adapters.config import load_policy
from genesis_adapters.clock import SystemUtcClock
from genesis_adapters.oddspapi import endpoints as ep
from datetime import datetime, timedelta, timezone
from genesis.time import iso_utc
pol = load_policy(CONFIG / "oddspapi_slice1_policy.json")
specs = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", pol)
req = ep.build_request(specs["META_SPORTS"])
srv = LoopbackHttps([Reply(body=b"[]")])
ctx = tls_context()                       # the production factory, unmodified, no argument
t = HttpsTransport(Secret("KEY-0123456789abcdefghij"), credential_param="apiKey", policy=pol, ssl_context=ctx, connect_address=srv.address)
r = t.send(req, clock=SystemUtcClock(drift_max_ms=pol.wall_monotonic_drift_max_ms), deadline_at=iso_utc(datetime.now(timezone.utc) + timedelta(seconds=10)))
print(("CONTROL (no SSL_CERT_FILE)" if os.environ.get("AUDIT_P70_CONTROL") else "with SSL_CERT_FILE=test-ca.pem") + " -> production tls_context() outcome:", r.outcome, r.http_status, "| server saw keyed request line:", "apiKey=" in srv.seen[0].request_line if srv.seen else None)
srv.close()
