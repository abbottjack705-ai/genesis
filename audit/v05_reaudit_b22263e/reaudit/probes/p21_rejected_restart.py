"""Attack area 7 - rejected / quarantined evidence must stay unusable across a crash and restart.

c8dfafd §14.4: "A completed row with raw evidence but no normalized row resumes normalization". §11.1 puts
the status-code, Date-skew and content-type checks AFTER the raw publish and the ``completed`` row. So a
resume path that re-parses retained raw bytes without re-applying those checks can turn a REJECTED response
into OPEN, usable books. Every rejected response below therefore carries a VALID odds body: only the HTTP
status / headers / transport outcome make it a rejection (F-06, F-07, F-08, F-09, F-10, F-12, F-13).

For each rejection R and crash point K in {none, after acq_completed}:
  1. READY source in scratch registries; window w1 = good response (OPEN heads);
  2. window w2 = R, killed at K;
  3. fresh runtime over the same root, later clock, ``resume()``;
  4. R1  no normalized document / PIT record derived from the w2 attempt, before or after restart;
     R2  no book whose usable head comes from w2 at any cutoff after restart;
     R3  ``verify_all`` still totals the w1 books only;
     R4  protective classes (401, 429, Date skew) keep blocking sends after restart (F-08, F-09, F-12).

    python -B p21_rejected_restart.py --repo <candidate> [--out p21.json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _probe as p  # noqa: E402
from _probe import c  # noqa: E402

AREA = "P21"


def rejections(body: bytes) -> list[tuple[str, object, bool]]:
    skewed = p.http_date(c.add(c.START, seconds=-86400))
    return [
        ("F-10 503 carrying a valid odds body", (503, c.JSON_HEADERS, body), False),
        ("F-08 401 carrying a valid odds body", (401, c.JSON_HEADERS, body), True),
        ("F-09 429 carrying a valid odds body", (429, c.JSON_HEADERS + (("retry-after", "3600"),), body), True),
        ("F-07 302 carrying a valid odds body", (302, c.JSON_HEADERS + (("location", "https://redirect.invalid/"),),
                                                 body), False),
        ("F-13 200 with content-type text/html", (200, (("content-type", "text/html"),), body), False),
        ("F-12 200 with a Date header 1 day off T1", (200, c.JSON_HEADERS + (("date", skewed),), body), True),
        ("F-06 TRUNCATED outcome carrying a full body", "TRUNCATED", False),
    ]


class Scripted(c.CountingTransport):
    """First call: good body. Second call: the rejection (a tuple, or the literal "TRUNCATED")."""

    def __init__(self, good, rejection):
        super().__init__(responses=[(200, c.JSON_HEADERS, good)])
        self.rejection = rejection

    def send(self, request, *, clock, deadline_at):
        if self.sends == 0:
            return super().send(request, clock=clock, deadline_at=deadline_at)
        from genesis_adapters.oddspapi.transport import TransportResult

        self.sends += 1
        t0 = clock.now()
        if self.rejection == "TRUNCATED":
            body = self.responses[0][2] if self.responses else self.default[2]
            return TransportResult("TRUNCATED", 200, c.JSON_HEADERS, body, None, t0, clock.now())
        status, headers, body = self.rejection
        return TransportResult("RESPONSE", status, tuple(headers), body, None, t0, clock.now())


def attempt_id(item) -> str:
    from genesis_adapters.oddspapi.acquisition import attempt_id as aid

    return aid(item.request.provider_request_hash, item.window_id, item.attempt)


def from_attempt(rt, acquisition_id: str) -> list[dict]:
    return [r for r in p.pit_rows(rt) if p.doc(rt, r).get("acquisition_id") == acquisition_id]


def case(repo: Path, good: bytes, label: str, rejection, protective: bool, crash: str | None) -> None:
    name = f"{label} / crash {crash or 'none'}"

    @p.guarded(AREA, name)
    def body() -> None:
        root = c.scratch("p21-")
        clock = c.StepClock()
        transport = Scripted(good, rejection if rejection != "TRUNCATED" else "TRUNCATED")
        transport.default = (200, c.JSON_HEADERS, good)
        rt = c.open_runtime(repo, root, clock=clock, transport=transport, secret=None)
        p.approve_ready(rt)
        rt.acquire(c.odds_item(repo, window="w1"))
        baseline_books = len(p.pit_rows(rt))
        clock.jump(600)
        item2 = c.odds_item(repo, window="w2")
        restore = p.crash_on_row("acq_completed", after=True)(rt) if crash == "after_completed" else None
        try:
            rt.acquire(item2)
        except c.Crash:
            pass
        except Exception as exc:              # a refusal surfacing as an exception is acceptable here
            c.check(AREA, f"{name}: (info) w2 raised", True, raised=type(exc).__name__)
        finally:
            if restore:
                restore()
        aid2 = attempt_id(item2)
        c.check(AREA, f"R1 {name}: no PIT record from the rejected attempt before restart",
                not from_attempt(rt, aid2), records=len(from_attempt(rt, aid2)))
        last = c.jsonl(root / "acquisition.jsonl")[-1]["recorded_at"]
        clock2 = c.StepClock(start=c.add(last, seconds=60))
        second = c.CountingTransport(default=(200, c.JSON_HEADERS, good))
        rt2 = c.open_runtime(repo, root, clock=clock2, transport=second, secret=None)
        resume_error = None
        try:
            rt2.resume()
        except Exception as exc:                # a halting resume is recorded, not hidden
            resume_error = f"{type(exc).__name__}:{getattr(exc, 'code', '')}"
        derived = from_attempt(rt2, aid2)
        c.check(AREA, f"R1 {name}: no normalized document / PIT record from the rejected attempt after restart",
                not derived, records=len(derived), resume_error=resume_error,
                states=[p.doc(rt2, r)["market_state"] for r in derived][:6])
        from genesis_adapters.oddspapi import reader

        decision = clock2.now()
        usable_from_w2, unattributable = [], 0
        for entity in sorted({row["entity_id"] for row in p.pit_rows(rt2)}):
            head = reader.admissible_head(entity, decision, stores=rt2.stores)
            if isinstance(head, reader.UsableBook):
                payload = next((getattr(head, a) for a in ("payload_hash", "artifact_hash", "normalized_artifact_hash")
                                if isinstance(getattr(head, a, None), str)), None)
                if payload is None:
                    unattributable += 1
                    continue
                rows = [r for r in p.pit_rows(rt2) if r["payload_hash"] == payload]
                if any(p.doc(rt2, r).get("acquisition_id") == aid2 for r in rows):
                    usable_from_w2.append(entity)
        if unattributable:
            p.cannot_run(AREA, f"R2 {name}", RuntimeError(f"{unattributable} UsableBook(s) expose no artifact hash; "
                                                          "bind the attribute name in this probe"))
        else:
            c.check(AREA, f"R2 {name}: no usable head comes from the rejected attempt after restart",
                    not usable_from_w2, usable=usable_from_w2[:6])
        try:
            verified = rt2.verify_all()
        except Exception as exc:
            verified = f"ERROR:{type(exc).__name__}"
        c.check(AREA, f"R3 {name}: verify_all totals the good window's books only", verified == baseline_books,
                verified=verified, baseline=baseline_books)
        if protective:
            try:
                rt2.acquire(c.odds_item(repo, window="w3"))
            except Exception as exc:
                c.check(AREA, f"{name}: (info) w3 raised", True, raised=type(exc).__name__)
            c.check(AREA, f"R4 {name}: the protective halt/circuit still blocks sends after restart",
                    second.sends == 0, sends=second.sends)
        c.remove(root)

    body()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    try:
        good = c.fixture_bytes(repo, "odds_by_tournaments.json")
    except Exception as exc:  # noqa: BLE001
        p.cannot_run(AREA, "fixture odds_by_tournaments.json", exc)
        return p.finish(args.out)
    for label, rejection, protective in rejections(good):
        for crash in (None, "after_completed"):
            case(repo, good, label, rejection, protective, crash)
    return p.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
