"""Attack area 6 - invalidation crash/restart convergence WITHOUT an operator re-issue.

The prior audit's C14-C16 (37b86fb a02_a03) crashed ``emit_invalidation`` and then "recovered" by calling
``emit_invalidation`` again with the same arguments, i.e. by an operator re-issue. That never tested whether a
restarted runtime, on its own, makes a DURABLY RECORDED invalidation effective. If it does not, the
invalidated price stays the usable head after restart although ``invalidations.jsonl`` says it is invalid
(c8dfafd §13.2: emission steps 3-4; D5; F-40).

For each crash point K in {after_recorded, after_invalidation_observation, after_invalidation_pit}:
  I0  control: the still-current OPEN target is usable before the invalidation;
  I1  after a fresh runtime + ``resume()`` (no re-issue), the target entity is NOT usable at a cutoff after
      the restart, and is ``Unusable(INVALIDATED)``;
  I2  exactly one recorded row, one applied row, one INVALIDATED PIT record (convergence, no duplicates);
  I3  ``verify_all`` re-derives every document incl. the INVALIDATION document (§11.5);
  I4  cutoffs before T3_inv are unchanged (the original is still the head there);
  I5  a second ``resume()`` is a no-op; an operator re-issue afterwards adds no second INVALIDATED head
      (``NONE_ALREADY_SUPERSEDED``, §13.2 step 4);
  I6  (REVIEW) the head is not usable on a restarted runtime even BEFORE resume() is called.

    python -B p22_invalidation_selfheal.py --repo <candidate> [--out p22.json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _probe as p  # noqa: E402
from _probe import c  # noqa: E402

AREA = "P22"


class Injector:
    def __init__(self, target):
        self.target, self.fired = target, False

    def __call__(self, step):
        if not self.fired and step == self.target:
            self.fired = True
            raise c.Crash(step)


def inval_pit(rt) -> list[dict]:
    return [r for r in p.pit_rows(rt) if p.doc(rt, r).get("market_state") == "INVALIDATED"]


def case(repo: Path, body: bytes, step: str) -> None:
    @p.guarded(AREA, f"crash {step}")
    def run() -> None:
        from genesis_adapters.oddspapi import emit, reader

        root = c.scratch("p22-")
        clock = c.StepClock()
        rt = c.open_runtime(repo, root, clock=clock, transport=c.CountingTransport(default=(200, c.JSON_HEADERS, body)))
        p.approve_ready(rt)
        rt.acquire(c.odds_item(repo))
        target_row = next(r for r in p.pit_rows(rt) if p.doc(rt, r)["market_state"] == "OPEN")
        entity = target_row["entity_id"]
        target = [o for o in rt.stores.evidence.get_observations(target_row["payload_hash"])
                  if o.contract_id == rt.stores.contract_id][0]
        before = clock.now()
        control = reader.admissible_head(entity, before, stores=rt.stores)
        c.check(AREA, f"I0 crash {step}: control - the OPEN target is usable before the invalidation",
                isinstance(control, reader.UsableBook), got=type(control).__name__)
        kwargs = dict(invalidated_observation_id=target.observation_id, invalidation_class="OPERATOR",
                      reason="INVALIDATED", actor="OPERATOR", evidence_refs=("reaudit:p22",))
        crashed = False
        try:
            emit.emit_invalidation(clock=clock, checkpoint=Injector(step), stores=rt.stores, **kwargs)
        except c.Crash:
            crashed = True
        c.check(AREA, f"crash {step}: the injected crash fired", crashed)
        last = max(r.get("recorded_at", "") for r in c.jsonl(root / "acquisition.jsonl"))
        restart = c.add(max(last, clock.now()), seconds=60)

        pre = c.open_runtime(repo, root, clock=c.StepClock(start=restart), transport=c.CountingTransport())
        head_pre = reader.admissible_head(entity, c.add(restart, seconds=1), stores=pre.stores)
        c.check(AREA, f"I6 crash {step}: (REVIEW) not usable on a restarted runtime before resume()",
                not isinstance(head_pre, reader.UsableBook), got=type(head_pre).__name__,
                note="if usable, the decision runner must be proven to run resume() before taking D")

        clock2 = c.StepClock(start=c.add(restart, seconds=2))
        rt2 = c.open_runtime(repo, root, clock=clock2, transport=c.CountingTransport())
        error = None
        try:
            rt2.resume()
        except Exception as exc:
            error = f"{type(exc).__name__}:{getattr(exc, 'code', '')}"
        decision = clock2.now()
        head = reader.admissible_head(entity, decision, stores=rt2.stores)
        reason = str(getattr(head, "reason", getattr(head, "code", "")))
        c.check(AREA, f"I1 crash {step}: after restart+resume (no re-issue) the target is Unusable(INVALIDATED)",
                not isinstance(head, reader.UsableBook) and "INVALID" in reason.upper(), got=type(head).__name__,
                reason=reason, resume_error=error)
        rows = c.jsonl(root / "invalidations.jsonl")
        kinds = [r.get("record_type") for r in rows]
        c.check(AREA, f"I2 crash {step}: one recorded row, one applied row, one INVALIDATED PIT record",
                len(inval_pit(rt2)) == 1 and len(rows) == 2, rows=kinds, invalidated_pit=len(inval_pit(rt2)))
        try:
            verified = rt2.verify_all()
        except Exception as exc:
            verified = f"ERROR:{type(exc).__name__}"
        c.check(AREA, f"I3 crash {step}: verify_all re-derives every document incl. INVALIDATION",
                isinstance(verified, int) and verified == len(p.pit_rows(rt2)), verified=verified,
                documents=len(p.pit_rows(rt2)))
        if inval_pit(rt2):
            t3_inv = inval_pit(rt2)[0]["ready_at"]
            early = reader.admissible_head(entity, c.add(t3_inv, micros=-1), stores=rt2.stores)
            c.check(AREA, f"I4 crash {step}: cutoff T3_inv - 1us still resolves to the original price",
                    isinstance(early, reader.UsableBook), got=type(early).__name__)
        try:
            rt2.resume()
        except Exception:
            pass
        reissue = "ok"
        try:
            reissue = getattr(emit.emit_invalidation(clock=clock2, stores=rt2.stores, **kwargs), "head_effect", "ok")
        except Exception as exc:                       # a refusal of the duplicate is also acceptable
            reissue = f"refused:{type(exc).__name__}"
        c.check(AREA, f"I5 crash {step}: second resume + operator re-issue add no second INVALIDATED head",
                len(inval_pit(rt2)) == 1, invalidated_pit=len(inval_pit(rt2)), reissue=reissue,
                rows=[r.get("record_type") for r in c.jsonl(root / "invalidations.jsonl")])
        c.remove(root)

    run()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    try:
        body = c.fixture_bytes(repo, "odds_by_tournaments.json")
    except Exception as exc:  # noqa: BLE001
        p.cannot_run(AREA, "fixture", exc)
        return p.finish(args.out)
    for step in ("after_recorded", "after_invalidation_observation", "after_invalidation_pit"):
        case(repo, body, step)
    return p.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
