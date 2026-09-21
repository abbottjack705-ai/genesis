# ASTRA-6 HIGH — FINAL HOSTILE REVIEW PROMPT

You are the final hostile architecture/statistics/implementation auditor for Project Genesis.

You are reviewing a project that has already received independent reviews focused on decision science, external factual/API feasibility, operational failure modes, statistical false-confidence, and software architecture.

Your job is NOT to produce another stylistic rewrite and NOT to redesign the objective.

Read:

1. `PROJECT_GENESIS_v0.4.md`
2. `PROJECT_LAWS_v0.4.md`
3. `AUDIT_RECONCILIATION_v0.4.md`
4. `V03_TO_V04_GAP_ANALYSIS.md`
5. `V04_MIGRATION_PLAN.md`
6. `PROJECT_STATE.md`
7. `ARCHITECTURE.md`
8. `TEST_EVIDENCE.md`
9. relevant source/data capability documents
10. the actual repository implementation and critical tests

FIXED USER OBJECTIVE — DO NOT CHANGE IT:

Genesis aims for sustainable long-run net profit/ROI by autonomously finding a useful daily portfolio of genuinely good research-backed sports bets. It does not mechanically maximize raw win probability, does not mechanically maximize modelled EV, and does not chase tiny edge differences. Normal standalone odds are 1.50–3.00 with a stricter 1.40–1.49 exception. Daily ranges are search/output aims, never quotas. Outcome bets normally hold to settlement.

FIXED USER/RISK CONSTRAINTS:

- Mon–Thu aim 2–5; Fri 4–10; Sat 7–13; Sun 4–10.
- Breadth before leniency.
- 1u = 2.5% bankroll; supported 1–3u tiers; initial hard single bet max 3u.
- No daily turnover cap.
- Approximate initial hard simultaneous open liability 60% with tighter correlated-cluster caps.
- Pre-profit fixed operating-cost target <= £10/month.
- No required large one-off paid API credential.
- No unsupported browser automation.
- No LLM direct live order/risk override.
- No generic stop-loss/cash-out merely because an outcome bet drifts.

AUDIT GOAL:

Find only material defects that could cause:

- false confidence;
- fake profitability;
- leakage;
- winner's-curse/selection bias;
- bad calibration on selected bets;
- quota-driven or favourite-driven behaviour;
- arbitrary “good bet” logic;
- over-betting/correlation blow-up;
- duplicate/uncontrolled orders;
- stale research at execution;
- unreproducible decisions;
- protected-evaluation leakage;
- impossible/over-budget deployment;
- divergence between blueprint and actual code.

For every finding return:

- SEVERITY: CRITICAL / HIGH / MEDIUM;
- BLUEPRINT OR CODE LOCATION;
- FAILURE MECHANISM;
- CONCRETE EXPLOIT/FAILURE EXAMPLE;
- MINIMAL FIX;
- TEST THAT WOULD PROVE THE FIX;
- whether the issue requires changing v0.4 text, code, or both.

Also provide:

1. **Top 10 residual risks** after all fixes already present.
2. **Blueprint-vs-code divergence table**.
3. **Any auditor recommendation previously accepted that you believe was a mistake**, with precise reasoning.
4. **Do-not-change list** for parts now sufficiently strong.
5. **GO / HOLD for beginning substantive shadow research** only. Do not evaluate readiness for live money unless the repository has actually reached that phase.

Do not spend output praising the project. Attack it.
