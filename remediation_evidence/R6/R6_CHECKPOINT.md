# R6 — Order uniqueness, exact risk binding, and execution replay

Status: **GREEN**

## Red-before basis

R0 recorded F02/F03/F15 before this batch: two keys created two intents for one candidate,
`RISK_APPROVED` was reachable without a genuine approval, and restart erased order state.

## Closed invariants

- Every V2 order event is schema-versioned and persists the complete immutable intent or exact
  prior/new state transition.
- Candidate decision hash owns one order-intent lineage for all time in V0.4. Exact same-intent
  replay is idempotent; a changed key, payload, UNKNOWN/reconciliation state, or terminal prior
  lineage never permits replacement.
- Candidate uniqueness check and creation are one R1 transaction and survive process restart
  and real cross-process races.
- `OrderIntent` binds candidate hash, side, stake, approved odds, risk approval ID, time, mode,
  and deterministic order ID. Execution independently derives its BACK/LAY liability.
- Direct transition to `RISK_APPROVED` is forbidden. `bind_risk()` verifies every approval field,
  consumes it first, then persists the execution binding; submission requires the exact consumed
  approval bound to that order.
- A fault between risk consumption and execution binding becomes an orphan-consumption
  reconciliation block on replay. The approval remains consumed and the order cannot submit.
- Complete order state/history/binding indexes rehydrate from verified events. Restart in
  `SUBMISSION_PENDING`, `SUBMISSION_SENT`, `UNKNOWN`, or reconciliation state never blind-resends.
- Terminal risk reservations can be released/settled durably and do not resurrect on restart.
- Recertification reads the strategy view, immutable evidence-refresh store, market-open/current
  price/liquidity store, risk approval, current bankroll, durable safety state, and order state;
  no caller boolean can spoof those gates.
- PAPER mode and kill state use append-only current-head stores; kill survives restart. Live modes
  remain unimplemented and forbidden.

## Matrix evidence

- T-F02-001..008: all uniqueness, exact replay, UNKNOWN/terminal/restart, and cross-process race
  cases are green.
- T-F03-001..013: direct/fake/mismatched/expired approval, single-use, exact binding, crash split,
  unbound submission, LAY recomputation, authoritative recertification, and expiry boundary are
  green.
- T-F15-001..013: risk/order replay, consumption/reservation persistence, UNKNOWN/ambiguous
  restart, terminal release, uniqueness after restart, kill/mode replay, corrupt events, and
  unsupported/incomplete schema fail-closed behavior are green; settlement integration continues
  in R7.

## Verification

- Targeted R6 suite: **9/9 green** (`tests.test_remediation_r6_execution`).
- Full suite: **75/75 green**.
- `python -m compileall -q src tests`: **green**.
- `git diff --check`: no whitespace errors (only platform line-ending notices).

## Scope check

No external venue/provider adapter, acquisition, strategy/model discovery, UI, cloud,
credential, live-trading, chaos, or canary scope was added.
