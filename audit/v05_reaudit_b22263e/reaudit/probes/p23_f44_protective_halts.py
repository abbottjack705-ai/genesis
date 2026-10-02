"""F-44 / attack area 4 - does a raw-publication I/O failure pre-empt a PROTECTIVE halt?

c8dfafd §11.1 orders: raw EvidenceStore.publish -> completed row -> skew / status-code / JSON checks. The
protective reactions to a received response - 401/403 circuit open for all roles + capability BLOCKED (F-08,
§14.3), 429 circuit (F-09), CLOCK_SKEW send suspension until the next UTC day (F-12, §14.6 rule 5) and the
QUOTA_DIVERGENCE halt (F-37) - therefore run AFTER the raw publish. If that publish raises an ordinary
OSError (disk full, permission, AV lock: the F-44 gap), the reaction may never become durable, and a
restarted runner sends again with a rejected key, into a rate limit, or while the skew bound W1-W4 rely on
is broken.

For each protective response P:
  F0  control (no I/O failure): after P, a restarted runtime's next acquisition sends nothing. If the control
      itself sends, the protective behaviour is not active in fixture mode and the class is CANNOT_RUN;
  F1  with OSError(ENOSPC) injected into the RAW publish only: after restart + resume, the next acquisition
      in the same UTC day sends nothing;
  F2  (info) what the durable record says about the failed attempt (reconciled label, send_state).

    python -B p23_f44_protective_halts.py --repo <candidate> [--out p23.json]
"""

from __future__ import annotations

import argparse
import errno
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _probe as p  # noqa: E402
from _probe import c  # noqa: E402

AREA = "P23"


def protective(body: bytes) -> list[tuple[str, tuple]]:
    skewed = p.http_date(c.add(c.START, seconds=-86400))
    return [
        ("F-08 401", (401, c.JSON_HEADERS, b'{"error":"unauthorized"}')),
        ("F-08 403", (403, c.JSON_HEADERS, b'{"error":"forbidden"}')),
        ("F-09 429", (429, c.JSON_HEADERS + (("retry-after", "3600"),), b'{"error":"rate"}')),
        ("F-12 Date skew", (200, c.JSON_HEADERS + (("date", skewed),), body)),
        ("F-37 usage header above the Genesis debit", (200, c.JSON_HEADERS + (("x-requests-used", "999"),), body)),
    ]


def fail_raw_publish_once(rt):
    store = rt.capture.evidence
    original = store.publish
    state = {"fired": False}

    def publish(*args, **kwargs):
        if not state["fired"]:
            state["fired"] = True
            raise OSError(errno.ENOSPC, "No space left on device (re-audit injection)")
        return original(*args, **kwargs)

    store.publish = publish
    return lambda: setattr(store, "publish", original)


def run(repo: Path, response: tuple, inject: bool) -> dict:
    root = c.scratch("p23-")
    clock = c.StepClock()
    rt = c.open_runtime(repo, root, clock=clock, transport=c.CountingTransport(default=response))
    restore = fail_raw_publish_once(rt) if inject else None
    raised = None
    try:
        rt.acquire(c.odds_item(repo, window="w1"))
    except Exception as exc:
        raised = type(exc).__name__
    finally:
        if restore:
            restore()
    last = max(r.get("recorded_at", "") for r in c.jsonl(root / "acquisition.jsonl"))
    second = c.CountingTransport(default=(200, c.JSON_HEADERS, c.fixture_bytes(repo, "odds_by_tournaments.json")))
    rt2 = c.open_runtime(repo, root, clock=c.StepClock(start=c.add(last, seconds=60)), transport=second)
    try:
        rt2.resume()
    except Exception:
        pass
    try:
        rt2.acquire(c.odds_item(repo, window="w2"))
    except Exception:
        pass
    rows = c.jsonl(root / "acquisition.jsonl")
    info = {"sends_after_restart": second.sends, "first_raised": raised,
            "row_types": [r["record_type"] for r in rows][-8:],
            "reconciled": [{k: r.get(k) for k in ("outcome", "send_state", "reason")} for r in rows
                           if r["record_type"] in ("acq_reconciled", "acq_halted", "acq_circuit_opened")]}
    c.remove(root)
    return info


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
    for label, response in protective(body):
        @p.guarded(AREA, label)
        def one(label=label, response=response) -> None:
            control = run(repo, response, inject=False)
            if control["sends_after_restart"] != 0:
                p.cannot_run(AREA, f"F0 {label}", RuntimeError(
                    f"control sent {control['sends_after_restart']} after the protective response: the reaction is "
                    "not active in fixture mode, so F1 cannot be decided here"))
                return
            c.check(AREA, f"F0 {label}: control - no send after restart", True, **control)
            attacked = run(repo, response, inject=True)
            c.check(AREA, f"F1 {label}: raw-publish OSError does not lose the protective halt (no send after restart)",
                    attacked["sends_after_restart"] == 0, **attacked)
        one()
    return p.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
