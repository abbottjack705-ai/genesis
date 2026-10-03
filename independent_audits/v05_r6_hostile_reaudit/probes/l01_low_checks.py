"""L01: spot checks of RA5-006/007/008 edges against the candidate (pure, no network)."""
from boot import *
import shutil, tempfile, pathlib, json as _json
from genesis_adapters.config import load_adapter_config, PolicyError
from genesis_adapters.oddspapi import normalize, endpoints as ep
from genesis_adapters.ids import native_id, IdentityTypeError
def load_with(**changes):
    d = pathlib.Path(tempfile.mkdtemp()) / "config"; shutil.copytree(CONFIG, d)
    p = d / "oddspapi_slice1_policy.json"; body = _json.loads(p.read_text()); body.update(changes)
    p.write_text(_json.dumps(body, indent=2, sort_keys=True))
    try:
        c = load_adapter_config(d, allow_fixture_only=True, code_version=normalize.CODE_VERSION)
        return "LOADED (declared_bookmakers_max=%r)" % c.policy.declared_bookmakers_max
    except Exception as exc:
        return "refused: %s: %s" % (type(exc).__name__, str(exc)[:90])
for v in (0, 1, 3, 4, 50, True, 3.0, "3"):
    print("RA5-008 declared_bookmakers_max=%r -> %s" % (v, load_with(declared_bookmakers_max=v)))
for v in ("abc\n", "abc\r\n", "abc\x00", "a" * 64, "a" * 65, "a١", "ab c"):
    try:
        native_id(v, declared_type="str"); r = "accepted"
    except IdentityTypeError:
        r = "rejected"
    print("RA5-006 native_id(%r) -> %s" % (v[:12], r))
specs = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", load_policy(CONFIG / "oddspapi_slice1_policy.json"))
for kw in ({"bookmaker": ["pinnacle\n"]}, {"bookmaker": ["pinnacle"], "tournamentIds": [17]}, {"bookmaker": ["pinnacle١"]}):
    try:
        ep.build_request(specs["ODDS"], oddsFormat="decimal", **({"tournamentIds": [17]} | kw)); r = "accepted"
    except Exception as exc:
        r = "rejected (%s)" % type(exc).__name__
    print("RA5-006 build_request(%r) -> %s" % (kw, r))
for v in ("٢٠٢٦-١٠-٠١", "2026-10-01\n"):
    try:
        ep.build_request(specs["FIXTURES"], **{"from": v, "to": "2026-10-08", "sportId": 10, "tournamentIds": [17]}); r = "accepted"
    except Exception as exc:
        r = "rejected (%s)" % type(exc).__name__
    print("RA5-006 FIXTURES from=%r -> %s" % (v, r))
