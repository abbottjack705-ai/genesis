# LUNA PROMPT — V0.3 TO V0.4 RECONCILIATION ONLY

You are the primary implementation engineer for PROJECT GENESIS.

The authoritative specification has changed. Read these files in full before editing code:

1. `PROJECT_GENESIS_v0.4.md`
2. `PROJECT_LAWS_v0.4.md`
3. `CHANGELOG_v0.3_TO_v0.4.md`
4. `DECISION_AND_RISK_POLICY_v0.4.md`
5. `V0.4_ACCEPTANCE_CHECKLIST.md`

Also read the current repository's `PROJECT_STATE.md`, `ARCHITECTURE.md`, current v0.3 blueprint if present, and all existing critical tests.

IMPORTANT:

- The fresh Project Genesis repo is authoritative. Any earlier sports-engine repos are READ-ONLY LEGACY MATERIAL.
- Do not modify legacy repos.
- Do not begin strategy search, backtest optimization, new sport modelling, live execution, credential work, or cloud deployment in this task.
- Preserve working v0.3 foundations unless v0.4 materially requires a change.
- Do not redesign the objective.

The fixed v0.4 user intent is:

- ultimate objective = sustainable long-run profit/ROI;
- identify genuinely good research-backed bets across sports;
- normal odds 1.50–3.00, with separate exceptional 1.40–1.49 policy;
- do not mechanically maximize raw win probability;
- do not mechanically maximize estimated EV or chase tiny edge differences;
- daily search/output aims: Mon–Thu 2–5, Fri 4–10, Sat 7–13, Sun 4–10;
- those ranges are aims, never quotas/caps;
- breadth before leniency;
- 1u = 2.5% bankroll, tiers 1–3u;
- no daily turnover cap;
- approximate hard simultaneous open-liability cap 60%, with tighter correlated-cluster limits;
- hold outcome bets to settlement by default;
- no LLM in live order/stake/risk override path;
- autonomous cloud runtime later, <=£10/month pre-profit target;
- no architecture dependency on a large paid Betfair live key;
- live betting remains disabled.

YOUR ONLY PRIMARY DELIVERABLE IN THIS TASK:

Create `V03_TO_V04_GAP_ANALYSIS.md`.

For every material v0.4 requirement, classify:

- EXISTING
- PARTIAL
- MISSING
- CONFLICTING
- NOT_YET_APPLICABLE

For every PARTIAL / MISSING / CONFLICTING item include:

- exact current modules/files involved;
- what the current implementation does;
- what v0.4 requires;
- smallest safe migration;
- dependency/order constraints;
- tests required;
- whether it touches a protected invariant;
- whether human approval is required before implementation.

Pay special attention to:

- bitemporal/PIT `ready_at` semantics;
- frozen evidence-pack hashing;
- candidate decision hashes;
- fail-closed gate engine and reason codes;
- selected-set calibration / complete-candidate retention;
- protected evaluator side channels and non-refundable attempt accounting;
- no direct LLM probability input;
- explicit price-sanity policy;
- day-of-week search targets as non-quota policy;
- unit staking / 60% open-liability / correlation policy interfaces;
- single-use risk approvals;
- order state machine / idempotency / UNKNOWN reconciliation;
- settlement ledger source of truth;
- mode/live authority boundaries;
- OddsPapi call-budget architecture;
- provider-neutral execution abstraction;
- cloud-ready runtime boundaries.

Then:

1. update `PROJECT_STATE.md` with the exact reconciliation state;
2. update `ARCHITECTURE.md` only if necessary to accurately describe current vs target architecture;
3. create `V04_MIGRATION_PLAN.md` ordered by dependency and risk;
4. run the existing test suite without weakening tests;
5. report test results in `TEST_EVIDENCE.md`;
6. stop.

DO NOT IMPLEMENT THE MIGRATION IN THIS TASK unless a tiny documentation-only change is required to make the gap analysis accurate.

The goal is a trustworthy map of the existing repository before spending more model usage on code.
