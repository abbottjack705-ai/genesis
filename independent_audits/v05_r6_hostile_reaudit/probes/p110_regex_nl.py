from boot import *
from genesis_adapters import ids
from genesis_adapters.oddspapi import endpoints as ep
from genesis_adapters.config import load_policy
pol = load_policy(CONFIG / "oddspapi_slice1_policy.json")
specs = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", pol)
for v in ("abc", "abc\n", "abc\r\n", "abc\n\n"):
    try: r = ids.native_id(v, declared_type="str"); print("native_id", repr(v), "ACCEPTED", r)
    except Exception as e: print("native_id", repr(v), "rejected", type(e).__name__)
for v in ("pinnacle", "pinnacle\n"):
    try:
        q = ep.build_request(specs["ODDS"], bookmaker=[v], tournamentIds=[17], oddsFormat="decimal")
        print("build_request bookmaker", repr(v), "ACCEPTED; query", q.query, "hash", q.provider_request_hash[:12])
    except Exception as e: print("build_request bookmaker", repr(v), "rejected", type(e).__name__, str(e)[:60])
