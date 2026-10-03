"""Is there ANY operator remedy for a poison-pill capture? (reset command, restart, later healthy capture)."""
import contextlib, io
from boot import *
from types import SimpleNamespace
from genesis_adapters import cli
def poisoned():
    p = parp.odds_payload(); fx = parp.fixture_of(p)
    mk = next(iter(fx["bookmakerOdds"]["pinnacle"]["markets"].values())); oc = next(iter(mk["outcomes"].values())); pl = next(iter(oc["players"].values()))
    pl["changedAt"] = "@big"
    return parp.dump_with(p, big="1E+999999999")
with scratch_root() as root:
    clock = FixedClock(START, step_micros=1000)
    rt = open_rt(root, clock=clock, script=[odds_response(), ok(poisoned(), headers=JSON)])
    rt.acquire(odds_item("w1")); approve(rt); ents = sorted({r["entity_id"] for r in pit_rows(rt)}); clock.advance(seconds=900)
    try: rt.acquire(odds_item("w2"))
    except BaseException as e: print("poison acquire:", type(e).__name__)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.cmd_reset(SimpleNamespace(config=None, root=str(root), approval_reference="adr:ADR-7-operator", reason="clear poison"), prompt=lambda _: cli.CONFIRMATION_PHRASE)
    print("operator `reset` rc:", rc, out.getvalue().strip() or err.getvalue().strip())
    from datetime import datetime, timedelta, timezone
    from genesis.time import iso_utc
    rt2 = reopen(rt, clock=FixedClock(iso_utc(datetime.now(timezone.utc) + timedelta(minutes=5)), step_micros=1000))
    try: rt2.resume(); print("resume after reset: ok")
    except BaseException as e: print("resume after reset: RAISED", type(e).__name__)
    v = rt2.reader().head(ents[0], parp.iso_add(rt2.clock.peek(), seconds=30))
    print("reader after reset:", type(v).__name__, getattr(getattr(v, "code", None), "value", ""), "|", getattr(v, "detail", "")[:70])
    from genesis_adapters.oddspapi import quiescence
    print("pending_work:", quiescence.pending_work(rt2.stores))
