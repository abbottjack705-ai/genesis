"""AREA K (realistic flow): a G1 for key F exists BEFORE the SECRET_ECHO halt; can reset clear it without a rotated key?"""
import contextlib, io
from boot import *
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from genesis_adapters import cli
from genesis_adapters.oddspapi import authority as auth
from genesis_adapters.secrets import Secret
from adapter_tests.test_v05_authority import g1
from genesis.time import iso_utc, parse_utc
now = datetime.now(timezone.utc)
KEYTXT = "AUD1T-Zq8vLm2XpR7tYk4WnB9cD3fHsJ"; sec = Secret(KEYTXT)
def quiet(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): rc = fn(*a, **k)
    except Exception as e: return ("EXC", type(e).__name__)
    return rc, err.getvalue().strip()[:90]
def approve(root, rec):
    p = root / "r.json"; p.write_text(json.dumps(rec)); return quiet(cli.cmd_approve, SimpleNamespace(config=None, root=str(root), record=str(p)), prompt=lambda _: cli.CONFIRMATION_PHRASE)
def reset(root): return quiet(cli.cmd_reset, SimpleNamespace(config=None, root=str(root), approval_reference="adr:ADR-1", reason="r"), prompt=lambda _: cli.CONFIRMATION_PHRASE)
R = {}
for kind in ("SECRET_ECHO", "AUTH_REJECTED"):
    with scratch_root() as root:
        old = now - timedelta(days=1)
        led = auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=auth.load_gate_limits(CONFIG))
        led.append(g1(old, fingerprint=sec.fingerprint, days=30))              # the G1 under which live sends were authorized
        clock = FixedClock(iso_utc(now - timedelta(hours=3)), step_micros=1000)
        body = parp.dump(parp.odds_payload()) + b" " + KEYTXT.encode()
        rt = open_rt(root, clock=clock, secret=sec, script=[ok(body, headers=JSON) if kind == "SECRET_ECHO" else status(401, b"{}")])
        try: rt.acquire(odds_item())
        except Exception: pass
        halted = [(r["record_type"], r.get("reason")) for r in read_jsonl(root / "acquisition.jsonl") if r["record_type"] in ("acq_halted", "acq_circuit_opened")]
        R[kind + "_ledger"] = halted
        R[kind + "_reset_before_any_new_G1"] = reset(root)
        approve(root, g1(now - timedelta(minutes=1), fingerprint=sec.fingerprint, days=30))   # SAME key re-approved (no rotation)
        R[kind + "_reset_after_G1_same_key"] = reset(root)
        approve(root, g1(now, fingerprint="a1b2c3d4e5f6", days=30))                          # a rotated key
        R[kind + "_reset_after_G1_rotated_key"] = reset(root)
for k, v in R.items(): print(f"{k:42s}", v)
