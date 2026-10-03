"""AREAS J, K, L: backdated approval/READY, halt reset authority, fixed gate limits (REAL system clock, no patching)."""
import contextlib, io, shutil
from boot import *
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from genesis_adapters import cli
from genesis_adapters.oddspapi import authority as auth, capability
from genesis_adapters.oddspapi.reader import UsableBook
from genesis_adapters.secrets import Secret
from adapter_tests.test_v05_authority import g1, g2, g2r, g3
from genesis.time import iso_utc, parse_utc
CONF = lambda: cli.CONFIRMATION_PHRASE
R = {}
def quiet(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(*a, **k)
    return rc, out.getvalue().strip(), err.getvalue().strip()
def approve(root, record, config=None):
    p = root / "rec.json"; p.write_text(json.dumps(record), encoding="utf-8")
    try:
        return quiet(cli.cmd_approve, SimpleNamespace(config=config, root=str(root), record=str(p)), prompt=lambda _: CONF())
    except Exception as e:
        return ("EXC", "", type(e).__name__ + ": " + str(e)[:50])
    return quiet(cli.cmd_approve, SimpleNamespace(config=config, root=str(root), record=str(p)), prompt=lambda _: CONF())
now = datetime.now(timezone.utc)
# ---- J: approve backdating
with scratch_root() as root:
    day_ago = now - timedelta(days=1)
    rc = approve(root, g1(day_ago))
    R["J1_approve_granted_at_one_day_back"] = rc[0], rc[2][:70]
    rec = g1(now - timedelta(seconds=100)); r2 = approve(root, rec)
    stored = [r for r in auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=auth.load_gate_limits(CONFIG)).records("G1")]
    R["J2_approve_within_skew_overwritten_with_trusted_now"] = r2[0], (parse_utc(stored[-1]["granted_at"]) - parse_utc(rec["granted_at"])).total_seconds() if stored else None
    R["J2b_future_dated"] = approve(root, g1(now + timedelta(seconds=600)))[0]
    R["J2c_approve_with_no_granted_at_key_then_ledger_has_stamp"] = None
    rec = g1(now); rec.pop("granted_at")
    try:
        r = approve(root, rec); R["J2c_approve_with_no_granted_at_key_then_ledger_has_stamp"] = r[0], r[2][:80]
    except Exception as e:
        R["J2c_approve_with_no_granted_at_key_then_ledger_has_stamp"] = "EXC " + type(e).__name__
# ---- J: READY / backdating via approve-ready, capture before approval, cutoff before approval
with scratch_root() as root:
    cap_t = now - timedelta(minutes=20)
    clock = FixedClock(iso_utc(cap_t), step_micros=1000)
    rt = open_rt(root, clock=clock, script=[odds_response()])
    capability.anchor_unknown(rt.stores.capabilities, rt.stores.source_id, at=iso_utc(cap_t - timedelta(seconds=1)), reason="G2R_START")
    rt.acquire(odds_item())
    entity = pit_rows(rt)[0]["entity_id"]; t3 = pit_rows(rt)[0]["ready_at"]
    sid, cid, dv = rt.stores.source_id, rt.stores.contract_id, rt.stores.derivation_version
    # G3 record granted "now" and ALSO an attempt to pass an operator time through args
    approve(root, g3(now, derivation=dv, source=sid, contract=cid))
    args = SimpleNamespace(config=None, root=str(root), derivation_version=dv, source_id=sid, contract_id=cid, cost_tier="x", at=iso_utc(cap_t - timedelta(minutes=5)))
    rc = quiet(cli.cmd_approve_ready, args, prompt=lambda _: CONF())
    caps = rt.stores.capabilities.history(sid)
    ready = [c for c in caps if c.operational_status.name == "READY"]
    R["J3_approve_ready_rc"] = rc[0], rc[2][:60]
    R["J3_ready_row_recorded_at_vs_now"] = (ready[-1].recorded_at if ready else None, iso_utc(now)[:16])
    rt2 = reopen(rt, clock=FixedClock(iso_utc(now + timedelta(minutes=1)), step_micros=1000))
    for label, D in (("D_between_capture_and_approval", iso_utc(cap_t + timedelta(minutes=5))),
                     ("D_just_before_approval", iso_utc(parse_utc(ready[-1].recorded_at) - timedelta(microseconds=1))),
                     ("D_at_approval", ready[-1].recorded_at),
                     ("D_after_approval", iso_utc(parse_utc(ready[-1].recorded_at) + timedelta(seconds=30)))):
        v = rt2.reader().head(entity, D)
        R["J4_" + label] = type(v).__name__ + ":" + str(getattr(v, "code", ""))
# ---- K: halts and reset
def echo_root():
    root_cm = scratch_root(); root = root_cm.__enter__()
    clock = FixedClock(iso_utc(now - timedelta(hours=3)), step_micros=1000)
    sec = Secret("AUD1T-Zq8vLm2XpR7tYk4WnB9cD3fHsJ")
    rt = open_rt(root, clock=clock, secret=sec, script=[ok(parp.dump(parp.odds_payload()) + b" AUD1T-Zq8vLm2XpR7tYk4WnB9cD3fHsJ", headers=JSON)])
    try: rt.acquire(odds_item())
    except Exception: pass
    return root_cm, root, sec
def reset(root, ref="adr:ADR-9-reviewed"):
    return quiet(cli.cmd_reset, SimpleNamespace(config=None, root=str(root), approval_reference=ref, reason="r"), prompt=lambda _: CONF())
cm, root, sec = echo_root()
halts = [r for r in read_jsonl(root / "acquisition.jsonl") if r["record_type"] == "acq_halted"]
R["K0_secret_echo_halt_recorded"] = [h["reason"] for h in halts]
R["K1_reset_without_any_G1"] = reset(root)[0]
R["K2_reset_after_G1_for_SAME_key"] = None
approve(root, g1(now, fingerprint=sec.fingerprint)); R["K2_reset_after_G1_for_SAME_key"] = reset(root)[0]
approve(root, g1(now + timedelta(seconds=1), fingerprint=sec.fingerprint.upper()))        # same key, different spelling
R["K2b_reset_after_G1_same_key_UPPERCASE_fingerprint"] = reset(root)[0]
approve(root, g1(now + timedelta(seconds=2), fingerprint="0" * 12))
R["K3_reset_after_G1_for_different_fingerprint"] = reset(root)[0]
cm.__exit__(None, None, None)
# ---- L: gate limits
with scratch_root() as root:
    cdir = root / "cfg"; shutil.copytree(CONFIG, cdir)
    lim = json.loads((cdir / "oddspapi_gate_limits.json").read_text())
    lim["g2_requests_cap"] = 9; (cdir / "oddspapi_gate_limits.json").write_text(json.dumps(lim, indent=1))
    h = ["%064x" % i for i in range(1, 7)]
    r = approve(root, g2(now, h, hours=12), config=str(cdir)); R["L1_edited_limits_file_6_requests"] = r[0], r[2][:60]
    r = approve(root, g2(now, h, hours=12)); R["L2_pristine_limits_6_requests"] = r[0], r[2][:60]
    r = approve(root, g2(now, h[:5], hours=73)); R["L3_pristine_5_requests_73h"] = r[0], r[2][:60]
    r = approve(root, g2r(now, derivation="mb1-" + "0"*16, policy="0"*64, days=36)); R["L4_pristine_g2r_36d"] = r[0], r[2][:60]
    # policy edit: declared_bookmakers_max raised; does the OPERATIONAL loader accept >3 declared bookmakers?
    cdir2 = root / "cfg2"; shutil.copytree(CONFIG, cdir2)
    pol = json.loads((cdir2 / "oddspapi_slice1_policy.json").read_text()); pol["declared_bookmakers_max"] = 50
    (cdir2 / "oddspapi_slice1_policy.json").write_text(json.dumps(pol, indent=1))
    from genesis_adapters.config import load_adapter_config
    from genesis_adapters.oddspapi.maps import maps_from_config
    try:
        cfg = load_adapter_config(cdir2, allow_fixture_only=True, code_version="x"); m = maps_from_config(cfg)
        R["L5_policy_declared_bookmakers_max_50_loads"] = ("loads", cfg.policy.declared_bookmakers_max, len([b for b in m.bookmakers.values() if b.declared]))
    except Exception as e:
        R["L5_policy_declared_bookmakers_max_50_loads"] = "refused " + type(e).__name__
for k, v in R.items(): print(f"{k:58s}", v)
