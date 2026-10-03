"""AREA A (corrected): single-backslash JSON \\u escapes inside the JSON text; gzip whose ratio is under the bound."""
from boot import *
import gzip, os, random
from indep_scan import scan_tree
from genesis_adapters.secrets import Secret
from genesis_adapters.errors import AcquisitionHalt
KEY = "AUD1T-Zq8vLm2XpR7tYk4WnB9cD3fHsJ"
sec = Secret(KEY)
raw = KEY.encode()
def run(name, make_script):
    with scratch_root() as root:
        rt = open_rt(root, secret=sec, script=[make_script()])
        try:
            out = rt.acquire(odds_item()); res = ("returned", out.outcome.outcome, str(out.outcome.failure))
        except AcquisitionHalt as h:
            res = ("halt", str(h.args))
        rt2 = reopen(rt, secret=sec)
        try: rt2.resume()
        except Exception as e: res += ("resume:" + type(e).__name__,)
        print(f"{name:26s}", res, "LEAK:" + str(scan_tree(root, KEY)) if scan_tree(root, KEY) else "clean")
def json_text_with(inner: str) -> bytes:
    p = parp.odds_payload(); p[0]["tournamentName"] = "@E@"
    return json.dumps(p, sort_keys=True).replace('"@E@"', '"' + inner + '"').encode("ascii")
esc_all = "".join("\\u%04x" % ord(c) for c in KEY)
esc_mixed = KEY[:9] + "".join("\\u%04X" % ord(c) for c in KEY[9:20]) + KEY[20:]
esc_slash_only = KEY.replace("-", "\\/")           # '\/' is a legal JSON escape for '/'
run("json_u_all", lambda: ok(json_text_with(esc_all), headers=JSON))
run("json_u_mixed", lambda: ok(json_text_with(esc_mixed), headers=JSON))
run("json_u_upperhex", lambda: ok(json_text_with("".join("\\u%04X" % ord(c) for c in KEY)), headers=JSON))
# key split across two JSON string values (concatenation by consumer) -> fragments exactly at width-1 each, so below threshold
w = max(8, -(-len(KEY) // 3))
run("split_two_halves_len_w-1", lambda: ok(json_text_with(KEY[:w - 1]) .replace(b"@", b"") , headers=JSON))
# gzip: random padding so ratio < 20, key only inside the DECODED body
pad = random.Random(1).randbytes(30000).hex().encode()
body = parp.dump(parp.odds_payload()) + b"\n" + pad + b"\n" + raw
gz = gzip.compress(body)
print("gzip sizes", len(gz), len(body), "ratio", round(len(body) / len(gz), 1))
run("gzip_key_in_decoded_only", lambda: ok(gz, headers=JSON + (("content-encoding", "gzip"),)))
# gzip with key only in the WIRE bytes (e.g. in gzip header FNAME) while decoded body is clean
import io, zlib
def gz_with_name(name: bytes, data: bytes) -> bytes:
    co = zlib.compressobj(wbits=31); out = co.compress(data) + co.flush()
    flags = out[3] | 0x08
    hdr = out[:3] + bytes([flags]) + out[4:10] + name + b"\x00"
    return hdr + out[10:]
run("gzip_key_in_wire_only", lambda: ok(gz_with_name(raw, parp.dump(parp.odds_payload()) + pad), headers=JSON + (("content-encoding", "gzip"),)))
