"""AREA A/Q: a credential made ONLY of percent-encodable characters, so the 11-char fragment detector cannot rescue an encoded form.
Shows that the double-encoded-percent and JSON-escaped-slash detectors are load-bearing (mutants M26/M27) yet untested by the suite."""
from boot import *
import urllib.parse
from genesis_adapters.secrets import Secret
from genesis_adapters.errors import AcquisitionHalt
KEY = "/+=&/+=&/+=&/+=&/+=&/+=&/+=&/+=&"
sec = Secret(KEY)
forms = {"raw": KEY, "single_pct": urllib.parse.quote(KEY, safe=""), "double_pct": urllib.parse.quote(urllib.parse.quote(KEY, safe=""), safe=""),
         "json_escaped_slash": KEY.replace("/", "\\/")}
for name, form in forms.items():
    pl = parp.odds_payload(); pl[0]["tournamentName"] = "@E@"
    body = json.dumps(pl, sort_keys=True).replace('"@E@"', '"echo-' + form.replace('"', '') + '-echo"').encode("ascii")
    with scratch_root() as root:
        rt = open_rt(root, secret=sec, script=[ok(body, headers=JSON)])
        try: out = rt.acquire(odds_item()); res = ("returned", out.outcome.outcome, str(out.outcome.failure))
        except AcquisitionHalt: res = ("halt", "SECRET_ECHO")
        stored = any((root / "evidence").rglob("*")) if (root / "evidence").exists() else False
        print(f"{name:20s}", res, "raw-body-persisted" if stored else "nothing-persisted")
