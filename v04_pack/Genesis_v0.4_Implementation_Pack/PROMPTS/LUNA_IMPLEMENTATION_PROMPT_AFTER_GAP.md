# LUNA PROMPT — IMPLEMENT ACCEPTED V0.4 FOUNDATION MIGRATION

Use this only after `V03_TO_V04_GAP_ANALYSIS.md` and `V04_MIGRATION_PLAN.md` have been reviewed.

You are the primary implementation engineer for PROJECT GENESIS.

Read in full:

- `PROJECT_GENESIS_v0.4.md`
- `PROJECT_LAWS_v0.4.md`
- `V03_TO_V04_GAP_ANALYSIS.md`
- `V04_MIGRATION_PLAN.md`
- `V0.4_ACCEPTANCE_CHECKLIST.md`
- current `PROJECT_STATE.md`
- current `TEST_EVIDENCE.md`

Implement the accepted v0.4 migration in dependency order.

PRIORITY ORDER:

1. PIT/bitemporal access and `ready_at` enforcement.
2. Evidence pack freeze/hash/version contracts.
3. Deterministic candidate decision hash.
4. Pure fail-closed gate engine + reason-code taxonomy.
5. Protected evaluation boundary and non-refundable attempt accounting.
6. Full candidate retention / selection-policy provenance interfaces.
7. Reproducibility manifest.
8. Risk policy interfaces: units, open liability, correlation groups, single-use approvals.
9. Order state-machine interfaces + idempotency + UNKNOWN/reconciliation in paper/mock mode only.
10. Settlement ledger/property tests.
11. Source capability registry and OddsPapi quota/batching interfaces.
12. Runtime/cloud interfaces only where they are non-regret foundations.

CONSTRAINTS:

- No live credentials.
- No real-money orders.
- No strategy search or profitability optimization.
- No new sport model merely to demonstrate architecture.
- Do not modify legacy repositories.
- Do not weaken protected invariants or their tests.
- Do not turn Genesis into an EV maximizer, favourites bot, price trader, arbitrage engine, or daily-quota picker.
- Preserve working code where possible; prefer migrations over rewrites.

For every protected-contract change:

- add or update adversarial tests first where practical;
- fail closed;
- preserve old decision reconstruction;
- version configs/artifacts instead of silent mutation.

At completion:

1. run the entire test suite;
2. run adversarial/property tests;
3. update `TEST_EVIDENCE.md` with exact commands/results;
4. update `PROJECT_STATE.md` with implemented/partial/missing items;
5. update `V0.4_ACCEPTANCE_CHECKLIST.md` with evidence links, not optimistic checkmarks;
6. create `HANDOFF_V04_FOUNDATION.md` describing current state and next safe phase;
7. stop before substantive betting research.
