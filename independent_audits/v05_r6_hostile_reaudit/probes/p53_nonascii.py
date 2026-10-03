"""AREA A: non-ASCII credential: UTF-8 / Latin-1 / mojibake echoes in BODY and in a header (HA-07 covered headers only)."""
from boot import *
from indep_scan import scan_tree
from genesis_adapters.secrets import Secret
from genesis_adapters.errors import AcquisitionHalt
KEY = "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞß"          # 32 Latin-1 letters, no ASCII run
sec = Secret(KEY)
base = parp.dump(parp.odds_payload())
def run(name, script):
    with scratch_root() as root:
        rt = open_rt(root, secret=sec, script=[script])
        try:
            out = rt.acquire(odds_item()); res = ("returned", out.outcome.outcome, str(out.outcome.failure))
        except AcquisitionHalt as h: res = ("halt", h.args[0].value if hasattr(h.args[0], "value") else str(h.args))
        leak_utf8 = scan_tree(root, KEY)
        stored_raw = [p for p in (root / "evidence").rglob("*") if p.is_file()]
        blob = b"".join(p.read_bytes() for p in stored_raw)
        found = {"utf8": KEY.encode("utf-8") in blob, "latin1": KEY.encode("latin-1") in blob,
                 "mojibake_utf8_of_utf8_as_latin1": KEY.encode("utf-8").decode("latin-1").encode("utf-8") in blob,
                 "json_escaped": json.dumps(KEY).encode().strip(b'"') in blob}
        print(f"{name:34s}", res, "| stored forms:", {k: v for k, v in found.items() if v} or "none")
run("body UTF-8 echo", ok(base + b" " + KEY.encode("utf-8"), headers=JSON))
run("body Latin-1 echo", ok(base + b" " + KEY.encode("latin-1"), headers=JSON))
run("body mojibake (UTF-8 read as Latin-1)", ok(base + b" " + KEY.encode("utf-8").decode("latin-1").encode("utf-8"), headers=JSON))
run("body JSON \\u escapes", ok(base.replace(b'"x"', b'"x"') + b'\n{"k":"' + "".join("\\u%04x" % ord(c) for c in KEY).encode() + b'"}', headers=JSON))
run("header etag UTF-8 octets", ok(base, headers=JSON + (("etag", KEY.encode("utf-8").decode("latin-1")),)))
