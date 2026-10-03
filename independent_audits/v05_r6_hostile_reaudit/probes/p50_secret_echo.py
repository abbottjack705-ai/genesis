"""AREA A: independent secret-containment attack on the real pipeline (fixture mode with a configured key)."""
from boot import *
import base64, gzip, urllib.parse, math
from indep_scan import scan_tree, hits, forms
from genesis_adapters.secrets import Secret
from genesis_adapters.errors import AcquisitionHalt
KEY = "AUD1T-Zq8vLm2XpR7tYk4WnB9cD3fHsJ"
sec = Secret(KEY)
raw = KEY.encode()
def pct(s, up=True): return "".join(("%%%02X" if up else "%%%02x") % c for c in s.encode())
def b64a(off, urlsafe=False):
    e = base64.b64encode(b"\x00" * off + raw).rstrip(b"=")
    e = e[-(len(e) - (-(-off * 8 // 6))):] if off else e   # drop unknown-prefix chars
    return (e.replace(b"+", b"-").replace(b"/", b"_") if urlsafe else e).decode()
variants = {
  "raw": KEY, "lower": KEY.lower(), "pct_upper": pct(KEY), "pct_lower": pct(KEY, False), "double_pct": urllib.parse.quote(pct(KEY), safe=""),
  "json_u": "".join("\\u%04x" % ord(c) for c in KEY), "json_u_mixed": KEY[:10] + "".join("\\u%04x" % ord(c) for c in KEY[10:]),
  "hex": raw.hex(), "HEX": raw.hex().upper(), "b64_0": b64a(0), "b64_1": b64a(1), "b64_2": b64a(2), "b64url_0": b64a(0, True),
  "fragment_exact": KEY[3:3 + max(8, math.ceil(len(KEY) / 3))], "fragment_one_shorter": KEY[3:3 + max(8, math.ceil(len(KEY) / 3)) - 1],
}
R = {}
def body_with(text: str, enc="utf-8"):
    p = parp.odds_payload(); p[0]["tournamentName"] = "x"
    s = json.dumps(p, sort_keys=True)
    s = s.replace('"x"', '"' + text + '"') if enc == "utf-8" else s
    return s.encode("utf-8")
for name, form in list(variants.items()):
    with scratch_root() as root:
        rt = open_rt(root, secret=sec, script=[odds_response(), odds_response(), odds_response()])
        # inject the form into the (raw) body text of tournamentName
        pl = parp.odds_payload(); pl[0]["tournamentName"] = "echo-" + form + "-echo"
        rt.runner.transport.script = [ok(json.dumps(pl, sort_keys=True).encode("ascii"), headers=JSON)]
        try:
            out = rt.acquire(odds_item())
            res = ("returned", out.outcome.outcome, str(out.outcome.failure))
        except AcquisitionHalt as h:
            res = ("halt", str(h.args))
        # restart and settle again
        rt2 = reopen(rt, secret=sec)
        try: rt2.resume()
        except Exception as e: res += ("resume:" + type(e).__name__,)
        leaks = scan_tree(root, KEY)
        R[name] = {"result": res, "leaking_files": leaks, "raw_stored": (root / "evidence").exists() and any((root/"evidence").rglob("*"))}
# utf-16 / utf-32 body echo, gzip wire & decoded, header value, header name, content-type
def run_custom(name, scripted):
    with scratch_root() as root:
        rt = open_rt(root, secret=sec, script=[scripted])
        try:
            out = rt.acquire(odds_item()); res = ("returned", out.outcome.outcome, str(out.outcome.failure))
        except AcquisitionHalt as h:
            res = ("halt", str(h.args))
        rt2 = reopen(rt, secret=sec)
        try: rt2.resume()
        except Exception as e: res += ("resume:" + type(e).__name__,)
        R[name] = {"result": res, "leaking_files": scan_tree(root, KEY), "quarantine_rows": len(read_jsonl(root / "quarantine.jsonl"))}
base = parp.dump(parp.odds_payload())
for codec in ("utf-16", "utf-16-le", "utf-16-be", "utf-32-le"):
    run_custom("body_" + codec, ok(base + b"\n" + KEY.encode(codec), headers=JSON))
run_custom("gzip_decoded", ok(gzip.compress(base + b" " + raw), headers=JSON + (("content-encoding", "gzip"),)))
run_custom("header_value_etag", ok(base, headers=JSON + (("etag", KEY),)))
run_custom("header_value_nonallow", ok(base, headers=JSON + (("x-echo", KEY),)))
run_custom("header_name", ok(base, headers=JSON + (("x-" + KEY.lower(), "1"),)))
run_custom("content_type_dirty", ok(base, headers=(("content-type", "application/json; x=" + KEY),)))
run_custom("mixed_case_in_body", ok(base + b" " + KEY.swapcase().encode(), headers=JSON))
for k, v in R.items():
    print(f"{k:24s}", v["result"], "LEAK:" + str(v["leaking_files"]) if v["leaking_files"] else "clean")
