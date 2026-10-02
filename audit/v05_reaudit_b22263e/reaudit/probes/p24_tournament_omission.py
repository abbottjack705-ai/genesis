"""Attack area 15 - a requested-but-omitted tournament versus genuine ABSENT evidence (both directions).

c8dfafd §12.4: ABSENT tombstones only after a COMPLETE response; F-15: a partial payload ("a required list
missing for part of the scope") emits the books present and NO ABSENT tombstones; F-30: an expected book
absent from a complete response gets an ABSENT head. Tombstones never expire (§12.2 rule 6), so a false
ABSENT is a permanent false claim in PIT history; a missing genuine ABSENT leaves a pulled market's older
OPEN price usable until its TTL (§12.2 rule 5). Both are defects; the probe checks both.

  T1  omission: request tournaments {A, B}; the response holds no entry for B -> zero ABSENT tombstones for
      any B book, and B's existing heads unchanged;
  T2  over-correction guard: B present but one DECLARED bookmaker's block missing from one B fixture ->
      ABSENT heads for exactly that event x bookmaker (every in-scope market family), reader Unusable(ABSENT);
  T3  (info) one declared bookmaker missing from every fixture -> number of ABSENT tombstones.

    python -B p24_tournament_omission.py --repo <candidate> [--out p24.json]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _probe as p  # noqa: E402
from _probe import c  # noqa: E402

AREA = "P24"


def tournament_key(payload: list[dict]) -> str | None:
    for item in payload:
        for key, value in item.items():
            if "tournament" in key.lower() and isinstance(value, (int, str)):
                return key
    return None


def two_windows(repo: Path, first: bytes, second: bytes):
    root = c.scratch("p24-")
    clock = c.StepClock()
    rt = c.open_runtime(repo, root, clock=clock, transport=c.CountingTransport(
        responses=[(200, c.JSON_HEADERS, first), (200, c.JSON_HEADERS, second)]))
    p.approve_ready(rt)
    rt.acquire(c.odds_item(repo, window="w1"))
    clock.jump(600)
    rt.acquire(c.odds_item(repo, window="w2"))
    return root, rt, clock


def absent_docs(rt) -> list[dict]:
    return [p.doc(rt, r) for r in p.pit_rows(rt) if p.doc(rt, r)["market_state"] == "ABSENT"]


@p.guarded(AREA, "tournament omission")
def omission(repo: Path, payload: list[dict], key: str) -> None:
    tournaments = sorted({str(item[key]) for item in payload if key in item})
    if len(tournaments) < 2:
        raise RuntimeError(f"fixture holds {tournaments}; need two requested tournaments")
    omitted = tournaments[-1]
    b_fixtures = {str(item["fixtureId"]) for item in payload if str(item.get(key)) == omitted}
    kept = [item for item in payload if str(item.get(key)) != omitted]
    root, rt, _ = two_windows(repo, json.dumps(payload).encode(), json.dumps(kept).encode())
    false_absent = [d for d in absent_docs(rt) if d["provider_fixture_id"]["value"] in b_fixtures]
    c.check(AREA, f"T1 a response omitting requested tournament {omitted} fabricates no ABSENT tombstone for it",
            not false_absent, false_absent=len(false_absent), omitted_fixtures=len(b_fixtures))
    c.remove(root)


@p.guarded(AREA, "genuine ABSENT")
def genuine(repo: Path, payload: list[dict], key: str) -> None:
    from genesis_adapters.oddspapi import reader

    tournaments = sorted({str(item[key]) for item in payload if key in item})
    target = next(item for item in payload if str(item.get(key)) == tournaments[-1])
    bookmaker = next(b for b in c.DECLARED if b in target.get("bookmakerOdds", {}))
    changed = copy.deepcopy(payload)
    for item in changed:
        if item["fixtureId"] == target["fixtureId"]:
            item["bookmakerOdds"].pop(bookmaker)
    root, rt, clock = two_windows(repo, json.dumps(payload).encode(), json.dumps(changed).encode())
    absent = absent_docs(rt)
    exact = all(d["provider_fixture_id"]["value"] == str(target["fixtureId"])
                and d["provider_bookmaker_key"] == bookmaker for d in absent)
    c.check(AREA, "T2 a complete response missing one declared bookmaker of one event yields ABSENT heads for "
                  "exactly that event x bookmaker (no over-correction)", bool(absent) and exact,
            absent=len(absent), exact=exact, bookmaker=bookmaker, fixture=str(target["fixtureId"]))
    if absent:
        decision = clock.now()
        head = reader.admissible_head(absent[0]["entity_id"], decision, stores=rt.stores)
        c.check(AREA, "T2 reader: the tombstoned book is Unusable (its older OPEN price is blocked)",
                not isinstance(head, reader.UsableBook), got=type(head).__name__)
    c.remove(root)


@p.guarded(AREA, "bookmaker missing everywhere")
def bookmaker_everywhere(repo: Path, payload: list[dict]) -> None:
    present = [b for b in c.DECLARED if any(b in item.get("bookmakerOdds", {}) for item in payload)]
    dropped = present[-1]
    changed = copy.deepcopy(payload)
    for item in changed:
        item.get("bookmakerOdds", {}).pop(dropped, None)
    root, rt, _ = two_windows(repo, json.dumps(payload).encode(), json.dumps(changed).encode())
    c.check(AREA, "T3 (info) a declared bookmaker missing from every fixture", True, dropped=dropped,
            absent=len(absent_docs(rt)), note="compare with the candidate's documented completeness rule")
    c.remove(root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    try:
        payload = json.loads(c.fixture_bytes(repo, "odds_by_tournaments.json"))
        key = tournament_key(payload)
        if key is None:
            raise RuntimeError("no tournament field in the ODDS fixture items")
    except Exception as exc:  # noqa: BLE001
        p.cannot_run(AREA, "fixture binding", exc)
        return p.finish(args.out)
    omission(repo, payload, key)
    genuine(repo, payload, key)
    bookmaker_everywhere(repo, payload)
    return p.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
