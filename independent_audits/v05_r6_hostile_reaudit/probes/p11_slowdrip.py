"""AREA B: real-socket slow-drip response vs the 'hard' transport deadline (design 14.6 rule 3, BND-04)."""
from boot import *
import time, dataclasses
from adapter_tests.loopback_support import LoopbackHttps, Reply, test_ca_context
from genesis_adapters.oddspapi.transport_http import HttpsTransport
from genesis_adapters.secrets import Secret
from genesis_adapters.config import load_policy
from genesis_adapters.clock import SystemUtcClock
from genesis_adapters.oddspapi import endpoints as ep
from datetime import datetime, timedelta, timezone
from genesis.time import iso_utc

pol = load_policy(CONFIG / "oddspapi_slice1_policy.json")
specs = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", pol)
req = ep.build_request(specs["META_SPORTS"])
body = b"[" + b"0," * 28 + b"0]"
srv = LoopbackHttps([Reply(body=body, chunks=len(body), pause=0.7)])
t = HttpsTransport(Secret("KEY-0123456789abcdefghij"), credential_param="apiKey", policy=pol,
                   ssl_context=test_ca_context(), connect_address=srv.address)
clock = SystemUtcClock(drift_max_ms=pol.wall_monotonic_drift_max_ms)
now = datetime.now(timezone.utc)
deadline = iso_utc(now + timedelta(seconds=3))
t0 = time.monotonic()
r = t.send(req, clock=clock, deadline_at=deadline)
elapsed = time.monotonic() - t0
srv.close()
print(json.dumps({"deadline_after_s": 3, "send_returned_after_s": round(elapsed, 2), "outcome": r.outcome,
                  "bytes": len(r.body or b""), "T1": r.response_received_at, "deadline": deadline,
                  "T1_after_deadline": (r.response_received_at or "") > deadline}))
