# R7 — Settlement uniqueness and correction lineage

Status: **GREEN**

## Red-before basis

The exact R7 module was run in a detached worktree at clean checkpoint `8bb86f3`.
All seven tests were non-green: two assertion failures and five errors. The baseline
permitted both concurrent unlinked settlement writers, accepted cross-fill correction,
conflated event and effective P/L, lacked head semantics, and had a broken fill-fragment
constructor. See `RED_BEFORE.md`.

## Closed invariants

- A fill has zero or one current economic settlement head.
- An initial settlement is unlinked; every subsequent economic change must reference
  the exact current head for the same fill. Cross-fill, stale-ancestor, forked, and
  duplicate-unlinked events fail closed.
- Settlement check and append execute inside the R1 inter-process transaction. In a
  two-process initial-settlement race, exactly one event becomes head.
- V2 events explicitly and separately persist `delta_pnl` and `effective_pnl`.
  Initial delta equals effective P/L; correction delta equals new effective minus the
  prior head effective P/L.
- The sum of all event deltas must equal the sum of all current effective heads on every
  replay and report. Arithmetic is re-derived from the authoritative fill, not trusted
  from stored P/L fields.
- Event-ID exact replay is idempotent; different-payload reuse is rejected.
- Void/cancellation is a `VOID` economic event in the same correction lineage. It cannot
  bypass head ownership or fork an earlier result.
- Restart reconstructs fill lineages and heads solely from the verified JSONL authority.
- The audited legacy schema is migrated only when deterministic: one initial settlement
  and one valid direct correction. Duplicate unlinked results and deeper ambiguous legacy
  corrections fail closed.
- `FillRecord.fragment()` now returns the exact fill ID, enum side, Decimal odds/stake,
  and correct BACK/LAY liability.

## Matrix evidence

- T-F04-001: duplicate unlinked settlement rejected.
- T-F04-002: WIN to LOSS correction has exact final effective and delta P/L.
- T-F04-003..004: cross-fill and stale-ancestor corrections rejected.
- T-F04-005: WIN to LOSS to WIN conserves exactly one final WIN outcome.
- T-F04-006: conflicting event-ID reuse rejected; exact retry idempotent.
- T-F04-007: restart reconstructs identical current head and P/L.
- T-F04-008: duplicate-unlinked legacy history fails closed.
- T-F04-009: cross-process initial-settlement race yields one winner.
- T-F04-010: V2 rows expose distinct delta/effective fields and no ambiguous `pnl` field.
- T-F04-011: void/cancellation uses current-head correction semantics.
- T-ADJ-LEDGER-001: valid fill produces the correct Decimal `MatchedFragment`.

## Verification

- Targeted R7 suite: **7/7 green**.
- Full suite: **82/82 green**.
- `python -m compileall -q src tests`: **green**.
- `git diff --check`: no whitespace errors (only platform line-ending notices).

## Scope check

No venue-specific settlement rules, provider adapter, network path, credential, live
activation, strategy, sport model, or real-money path was added.
