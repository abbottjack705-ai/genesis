"""Areas 2 and 3 (HA-001, HA-011): request identity, quota replay and the crash-point matrix.

For every checkpoint the attack runs one fixture ODDS acquisition through the candidate's real runtime
(``pipeline.open_runtime``), kills it there with a ``BaseException`` (a simulated process death), restarts a
fresh runtime over the same root with a LATER clock, runs ``resume()`` and then re-acquires the very same
plan item. Expected behaviour is c8dfafd 11.1/11.4/14.4/13.2 plus the frozen facts in
``oracle/QUOTA_SEMANTICS_OUTPUT.json`` (see REPRO_COMMANDS.md A3 for the table).

    python -B attacks/a02_a03_crash_matrix.py --repo <candidate checkout> [--out a03.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402


def summary(rt) -> dict:
    rows = [r for r in rt.stores.pit.log.records() if r.get("record_type") == "pit_record"]
    return {"artifacts": sorted((r["entity_id"], r["payload_hash"]) for r in rows),
            "record_ids": sorted(r["record_id"] for r in rows),
            "identity_head": rt.stores.identity.head()}


def pit_rows(rt) -> list[dict]:
    return [r for r in rt.stores.pit.log.records() if r.get("record_type") == "pit_record"]


class Injector:
    """Crash exactly once at a named checkpoint (runner or emission hook)."""

    def __init__(self, target: str | None):
        self.target = target
        self.fired = False

    def __call__(self, step: str) -> None:
        if not self.fired and step == self.target:
            self.fired = True
            raise c.Crash(step)


def baseline(repo: Path, body: bytes, secret) -> dict:
    root = c.scratch("base-")
    rt = c.open_runtime(repo, root, clock=c.StepClock(), transport=c.CountingTransport(default=(200, c.JSON_HEADERS, body)),
                        secret=secret)
    result = rt.acquire(c.odds_item(repo))
    assert result.emitted is not None, "baseline produced no emission"
    out = summary(rt)
    out["books"] = len(pit_rows(rt))
    c.remove(root)
    return out


def run_case(repo: Path, body: bytes, secret, base: dict, name: str, *, runner: str | None = None,
             emit: str | None = None, patch=None, transport_kw=None, plant_pending: bool = False) -> None:
    import genesis.evidence as frozen_evidence
    import genesis.repro as frozen_repro

    area = "A3"
    root = c.scratch("".join(ch if ch.isalnum() else "-" for ch in name[:20]) + "-")   # Windows-safe
    clock = c.StepClock()
    first = c.CountingTransport(default=(200, c.JSON_HEADERS, body), **(transport_kw or {}))
    runner_hook, emit_hook = Injector(runner), Injector(emit)
    rt = c.open_runtime(repo, root, clock=clock, transport=first, secret=secret, checkpoint=emit_hook,
                        runner_checkpoint=runner_hook)
    item = c.odds_item(repo)
    restore = patch(rt, frozen_evidence, frozen_repro) if patch else None
    crashed = False
    try:
        rt.acquire(item)
    except c.Crash:
        crashed = True
    finally:
        if restore:
            restore()
    c.check(area, f"{name}: the injected crash fired", crashed)
    request_id = "oddspapi-attempt:" + __import__("genesis_adapters.oddspapi.acquisition",
                                                  fromlist=["attempt_id"]).attempt_id(
        item.request.provider_request_hash, item.window_id, item.attempt)
    quota_before = len(c.quota_rows(root, request_id))
    durable = {r["record_type"] for r in c.jsonl(root / "acquisition.jsonl") if r.get("acquisition_id")}
    pending = sorted(str(p.relative_to(root)) for p in root.rglob("*.pending"))
    if plant_pending:                                     # what a hard kill between temp write and link leaves
        stray = root / "evidence" / "objects" / ".stray-object.pending"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(b"partial")

    last = c.jsonl(root / "acquisition.jsonl")[-1]["recorded_at"]
    second = c.CountingTransport(default=(200, c.JSON_HEADERS, body))
    rt2 = c.open_runtime(repo, root, clock=c.StepClock(start=c.add(last, seconds=60)), transport=second,
                         secret=secret)
    reserve_calls = {"n": 0}
    original_reserve = rt2.gate.reserve

    def counting_reserve(**kw):
        reserve_calls["n"] += 1
        return original_reserve(**kw)

    rt2.runner.quota.reserve = counting_reserve
    resume_error = None
    try:
        reconciled, results = rt2.resume()
    except Exception as exc:                               # a resume that halts is recorded, not hidden
        resume_error = type(exc).__name__ + ":" + str(getattr(exc, "code", ""))
        reconciled, results = (), ()
    state = rt2.stores.acquisition.attempts()
    aid = request_id.split(":", 1)[1]
    attempt = state.get(aid)
    again = rt2.acquire(item).outcome
    quota_after = len(c.quota_rows(root, request_id))

    c.check(area, f"{name}: restart made no send and no reserve() for the known attempt",
            second.sends == 0 and reserve_calls["n"] == 0, sends=second.sends, reserve_calls=reserve_calls["n"])
    c.check(area, f"{name}: at most one Genesis debit for the attempt, unchanged by restart",
            quota_before <= 1 and quota_after == quota_before, before=quota_before, after=quota_after)
    c.check(area, f"{name}: re-acquiring the same plan item is DUPLICATE/REFUSED",
            again.outcome in ("DUPLICATE", "REFUSED"), outcome=again.outcome,
            failure=str(again.failure) if again.failure else None)
    c.check(area, f"{name}: no stray .pending file after an in-process crash", not pending, pending=pending)

    if "acq_completed" in durable:
        rows = pit_rows(rt2)
        c.check(area, f"{name}: completed capture resumes to NORMALIZED without a halt",
                resume_error is None and attempt is not None and attempt.state == "NORMALIZED",
                error=resume_error, state=getattr(attempt, "state", None))
        c.check(area, f"{name}: resumed history equals the no-crash baseline (artifacts, record ids, identity)",
                summary(rt2) == {k: base[k] for k in ("artifacts", "record_ids", "identity_head")})
        verified = None
        try:
            verified = rt2.verify_all()
        except Exception as exc:
            verified = "ERROR:" + type(exc).__name__
        c.check(area, f"{name}: every normalized document re-derives (verify_all)", verified == base["books"],
                verified=verified, books=base["books"])
        ready_ok, ready_values = True, set()
        for row in rows:
            obs = [o for o in rt2.stores.evidence.get_observations(row["payload_hash"])
                   if o.contract_id == rt2.stores.contract_id]
            ready_values.add(row["ready_at"])
            if len(obs) != 1 or c.parse(row["ready_at"]) < c.parse(obs[0].parse_ready_at) \
                    or c.parse(row["ready_at"]) < c.parse(row["available_at"]):
                ready_ok = False
        c.check(area, f"{name}: every PIT record has one observation and ready_at >= parse_ready_at >= T1",
                ready_ok and len(rows) == base["books"], records=len(rows))
        normalized = [r for r in c.jsonl(root / "acquisition.jsonl") if r["record_type"] == "acq_normalized"]
        c.check(area, f"{name}: T3 values across the response's PIT records (informational)", True,
                distinct_ready_at=len(ready_values),
                normalized_row_T3=normalized[-1]["T3"] if normalized else None)
    else:
        rows = pit_rows(rt2)
        expect_orphan = quota_before == 1
        c.check(area, f"{name}: uncompleted attempt reconciled {'ORPHANED_RESERVATION' if expect_orphan else 'NOT_RESERVED'}",
                attempt is not None and attempt.state == "RECONCILED"
                and attempt.reconciled == ("ORPHANED_RESERVATION" if expect_orphan else "NOT_RESERVED"),
                state=getattr(attempt, "state", None), reconciled=getattr(attempt, "reconciled", None))
        c.check(area, f"{name}: send_state is MAY_HAVE_BEEN_SENT exactly when acq_sent was durable",
                attempt is not None and (attempt.send_state == "MAY_HAVE_BEEN_SENT") == ("acq_sent" in durable),
                send_state=getattr(attempt, "send_state", None), sent_durable="acq_sent" in durable)
        c.check(area, f"{name}: no PIT record from an uncompleted attempt", not rows, records=len(rows))
        retry = rt2.acquire(c.odds_item(repo, attempt=2)).outcome
        retry_id = "oddspapi-attempt:" + retry.acquisition_id
        c.check(area, f"{name}: retry is a new attempt with a new request_id and its own debit",
                retry.request_id == retry_id and retry_id != request_id and len(c.quota_rows(root, retry_id)) == 1
                and second.sends == 1, outcome=retry.outcome, sends=second.sends)
    c.remove(root)


# -- patches for checkpoints the candidate has no hook for ---------------------------------------
def crash_in_secret_screen(rt, _ev, _repro):
    scanner = rt.capture.scanner
    original = scanner.scan
    state = {"n": 0}

    def scan(data):
        state["n"] += 1
        raise c.Crash("secret screen")

    scanner.scan = scan
    return lambda: setattr(scanner, "scan", original)


def crash_before_link(rt, _ev, repro):
    """Only inside the RAW evidence publish: the object's temp file is written, the link never happens."""

    store = rt.capture.evidence
    original_publish, original_link = store.publish, repro.os.link

    def link(src, dst, *a, **k):
        raise c.Crash("raw publish: temp written, link not done")

    def publish(*args, **kwargs):
        repro.os.link = link
        try:
            return original_publish(*args, **kwargs)
        finally:
            repro.os.link = original_link

    store.publish = publish
    return lambda: (setattr(store, "publish", original_publish), setattr(repro.os, "link", original_link))


def crash_after_object_link(rt, ev, _repro):
    original = ev.immutable_write

    def write(path, data):
        original(path, data)
        ev.immutable_write = original
        raise c.Crash("raw publish: object linked, observation not written")

    ev.immutable_write = write
    return lambda: setattr(ev, "immutable_write", original)


def crash_on_row(record_type: str, after: bool):
    def patch(rt, _ev, _repro):
        ledger = rt.runner.ledger
        original = ledger.append

        def append(kind, **kw):
            if kind == record_type and not after:
                ledger.append = original
                raise c.Crash(f"before {kind}")
            original(kind, **kw)
            if kind == record_type and after:
                ledger.append = original
                raise c.Crash(f"after {kind}")

        ledger.append = append
        return lambda: setattr(ledger, "append", original)
    return patch


def invalidation_cases(repo: Path, body: bytes, secret) -> None:
    from genesis_adapters.oddspapi import emit

    for number, step in (("C14", "after_recorded"), ("C15", "after_invalidation_observation"),
                         ("C16", "after_invalidation_pit")):
        root = c.scratch("inv-")
        clock = c.StepClock()
        rt = c.open_runtime(repo, root, clock=clock, transport=c.CountingTransport(default=(200, c.JSON_HEADERS, body)),
                            secret=secret)
        rt.acquire(c.odds_item(repo))
        target = None
        for row in pit_rows(rt):
            doc = json.loads(rt.stores.evidence.get_bytes(row["payload_hash"]))
            if doc.get("market_state") == "OPEN":
                target = [o for o in rt.stores.evidence.get_observations(row["payload_hash"])
                          if o.contract_id == rt.stores.contract_id][0]
                break
        kwargs = dict(invalidated_observation_id=target.observation_id, invalidation_class="OPERATOR",
                      reason="INVALIDATED", actor="OPERATOR", evidence_refs=("audit:ha",), stores=rt.stores)
        crashed = False
        try:
            emit.emit_invalidation(clock=clock, checkpoint=Injector(step), **kwargs)
        except c.Crash:
            crashed = True
        clock.jump(60)
        error = None
        try:
            result = emit.emit_invalidation(clock=clock, **kwargs)
        except Exception as exc:
            error, result = type(exc).__name__, None
        ledger = c.jsonl(root / "invalidations.jsonl")
        kinds = [r.get("record_type") for r in ledger]
        inv_pit = [r for r in pit_rows(rt) if json.loads(rt.stores.evidence.get_bytes(r["payload_hash"])).get(
            "market_state") == "INVALIDATED"]
        c.check("A3", f"{number} invalidation crash {step}: resumes to exactly one recorded row, one applied row, one "
                      f"INVALIDATED PIT record", crashed and error is None and result is not None
                and result.head_effect == "INVALIDATED_HEAD_EMITTED" and len(inv_pit) == 1 and len(ledger) == 2,
                crashed=crashed, error=error, rows=kinds, invalidated_pit=len(inv_pit))
        c.remove(root)


def quota_gate_replay(repo: Path) -> None:
    """HA-001 defence in depth: does the candidate's QuotaGate itself refuse an identical-fingerprint replay?"""

    from genesis.quota import QuotaLedger, VerifiedCacheStore

    from genesis_adapters.oddspapi.quota_gate import QuotaGate

    root = c.scratch("gate-")
    cache = VerifiedCacheStore(root / "quota" / "cache")
    ledger = QuotaLedger(root / "quota" / "ledger.jsonl", policy=c.test_quota_policy(), allow_test_policy=True,
                         cache_store=cache)
    gate = QuotaGate(ledger, cache, cache_index_path=root / "quota" / "cache-index.jsonl")
    request = c.odds_item(repo).request
    first = gate.reserve(request=request, request_id="oddspapi-attempt:" + "a" * 64, occurred_at=c.START,
                         billable_units=1)
    replay = gate.reserve(request=request, request_id="oddspapi-attempt:" + "a" * 64, occurred_at=c.START,
                          billable_units=1)
    rows = len(c.quota_rows(root))
    c.check("A2", "QuotaGate.reserve identical-fingerprint replay (informational: the frozen ledger re-answers "
                  "allowed; protection must come from the acquisition ledger)", True,
            first_allowed=first.allowed, replay_allowed=replay.allowed, ledger_rows=rows)
    c.remove(root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="", help="comma list of case-number prefixes, e.g. C07a,C07b")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    from genesis_adapters.secrets import Secret

    body = c.fixture_bytes(repo, "odds_by_tournaments.json")
    secret = Secret(c.SENTINEL)
    base = baseline(repo, body, secret)
    n = base["books"]
    c.check("A3", "baseline: fixture ODDS response emits books", n > 0, books=n)
    cases = [
        # numbering = REPRO_COMMANDS.md section A3 (16 checkpoints; letters are variants of one checkpoint)
        ("C01 before the quota ledger row", dict(runner="before_quota")),
        ("C02 after the quota ledger row, before quota_decided", dict(runner="after_quota")),
        ("C03 after acquisition quota_decided", dict(runner="after_quota_decided")),
        ("C04 after acquisition sent (before the transport)", dict(runner="after_sent")),
        ("C05a transport dies before the response", dict(transport_kw={"crash_before_receive": True})),
        ("C05b transport complete, result lost", dict(transport_kw={"crash_after_receive": True})),
        ("C06 inside the secret screen", dict(patch=crash_in_secret_screen)),
        ("C07a raw publish: temp written, no link (+stray .pending)", dict(patch=crash_before_link,
                                                                          plant_pending=True)),
        ("C07b raw publish: object linked, no observation", dict(patch=crash_after_object_link)),
        ("C08a before the completed row", dict(patch=crash_on_row("acq_completed", after=False))),
        ("C08b after the completed row", dict(patch=crash_on_row("acq_completed", after=True))),
        ("C09a after T2, before the first normalized publish", dict(emit="after_t2")),
        ("C09b after the first normalized publish", dict(emit="after_observation:0")),
        ("C09c after the last normalized publish", dict(emit=f"after_observation:{n - 1}")),
        ("C10 after the first structured evidence", dict(emit="after_structured:0")),
        ("C11a after T3, before the first PIT append", dict(emit="after_t3")),
        ("C11b after the first PIT append (HA-011)", dict(emit="after_pit:0")),
        ("C11c after a middle PIT append", dict(emit=f"after_pit:{n // 2}")),
        ("C11d after the last PIT append", dict(emit=f"after_pit:{n - 1}")),
        ("C12 after coverage", dict(emit="after_coverage")),
        ("C13a after the normalized row", dict(emit="after_normalized_row")),
        ("C13b after the identity rows", dict(emit="after_identity")),
    ]
    only = [x for x in args.only.split(",") if x]
    for name, kw in cases:
        if only and not any(name.startswith(x + " ") for x in only):
            continue
        try:
            run_case(repo, body, secret, base, name, **kw)
        except Exception as exc:                            # a harness or candidate error is a failed check
            c.check("A3", f"{name}: case ran to completion", False, error=f"{type(exc).__name__}: {exc}")
    if not only:
        invalidation_cases(repo, body, secret)               # C14..C16
        quota_gate_replay(repo)
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
