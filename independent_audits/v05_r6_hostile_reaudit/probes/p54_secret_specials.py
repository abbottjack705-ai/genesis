"""AREA A: credential containing '/', '+', '=' and '%': escaped-slash JSON, percent, base64 std/url-safe, hex, plus-as-space forms."""
from boot import *
import base64, urllib.parse
from indep_scan import scan_tree
from genesis_adapters.secrets import Secret
from genesis_adapters.errors import AcquisitionHalt
KEY = "ab/cd+ef=GH-ij_klMNOP/qrstUV%wx"
sec = Secret(KEY); raw = KEY.encode()
def b64(off, url=False):
    e = base64.b64encode(b"\x00" * off + raw).rstrip(b"=")
    lead = -(-off * 8 // 6); e = e[lead:]
    return (e.replace(b"+", b"-").replace(b"/", b"_") if url else e).decode()
forms = {
 "raw": KEY, "json_escaped_slash(\\/)": KEY.replace("/", "\\/"), "pct_all": urllib.parse.quote(KEY, safe=""), "pct_slash_only": KEY.replace("/", "%2F"),
 "plus_as_space_in_form": KEY.replace("+", " ").replace(" ", "+"), "double_pct": urllib.parse.quote(urllib.parse.quote(KEY, safe=""), safe=""),
 "b64_off0": b64(0), "b64_off1": b64(1), "b64_off2": b64(2), "b64url_off0": b64(0, True), "hex": raw.hex(),
 "json_u_all": "".join("\\u%04x" % ord(c) for c in KEY), "json_u_slash_only": KEY.replace("/", "\\u002f"),
}
base = parp.dump(parp.odds_payload())
for name, form in forms.items():
    pl = parp.odds_payload(); pl[0]["tournamentName"] = "@E@"
    body = json.dumps(pl, sort_keys=True).replace('"@E@"', '"echo-' + form + '-echo"').encode("ascii")
    with scratch_root() as root:
        rt = open_rt(root, secret=sec, script=[ok(body, headers=JSON)])
        try: out = rt.acquire(odds_item()); res = ("returned", out.outcome.outcome, str(out.outcome.failure))
        except AcquisitionHalt as h: res = ("halt", "SECRET_ECHO")
        leaks = scan_tree(root, KEY)
        print(f"{name:26s}", res, "LEAK " + str(leaks) if leaks else "clean")
