from boot import *
from genesis_adapters.errors import AcquisitionHalt
base = parp.dump(parp.odds_payload())
for label, val in (("99999", "99999"), ("1e5", "1e5"), ("99,999", "99,999"), ("-5", "-5"), ("fullwidth 99999", "９９９９９"), ("'99999 units'", "99999 units"), ("0x1869F", "0x1869F")):
    with scratch_root() as root:
        rt = open_rt(root, script=[ok(base, headers=JSON + (("x-requests-used", val),))])
        try: out = rt.acquire(odds_item()); r = ("returned", out.outcome.outcome, str(out.outcome.failure))
        except AcquisitionHalt as h: r = ("HALT", str(h.args[0]))
        comp = [x for x in acquisition_rows(rt) if x["record_type"] == "acq_completed"][-1]
        print(f"{label:20s}", r, "usage record:", comp["provider_reported_usage"])
