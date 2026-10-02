from boot import *
with scratch_root() as root:
    rt = open_rt(root, script=[odds_response()])
    # NOTE: raw-only source until READY
    out = rt.acquire(odds_item())
    print("outcome", out.outcome.outcome, out.outcome.failure, "emitted", bool(out.emitted))
    approve(rt)
    rows = pit_rows(rt)
    print("pit rows", len(rows))
    entity = rows[0]["entity_id"]
    t3 = rows[0]["ready_at"]
    D = parp.iso_add(t3, seconds=5)
    v = rt.reader().head(entity, D)
    print(type(v).__name__, getattr(v, "code", None))
    print([r["record_type"] for r in acquisition_rows(rt)])
