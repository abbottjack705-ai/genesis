from boot import *
R = {}
with scratch_root() as root:
    clock = FixedClock(START, step_micros=1000)
    rt = open_rt(root, clock=clock, script=[ok(parp.dump(parp.odds_payload()), headers=JSON + (("date", "Mon, 01 Jan 99999999999 00:00:00 GMT"),)), odds_response()])
    try: rt.acquire(odds_item("w1")); R["acquire"] = "returned"
    except BaseException as e: R["acquire"] = "RAISED " + type(e).__name__
    R["rows"] = [r["record_type"] for r in acquisition_rows(rt)]
    R["raw_evidence_published_but_unrecorded"] = any((root / "evidence").rglob("*")) if (root / "evidence").exists() else False
    rt2 = reopen(rt, clock=FixedClock(parp.iso_add(clock.peek(), seconds=100), step_micros=1000))
    rec, _ = rt2.resume(); R["after_restart"] = [r["record_type"] for r in acquisition_rows(rt2)][-2:]
    R["debits"] = len([r for r in read_jsonl(root / "quota" / "ledger.jsonl") if r["record_type"] == "quota_billable_call"])
    R["pit_rows"] = len(pit_rows(rt2))
for k, v in R.items(): print(f"{k:42s}", v)
