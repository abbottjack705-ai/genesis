# PROJECT GENESIS v0.4 — PROJECT LAWS

This file is the short-form statement of user intent and non-negotiable architecture rules. If another document is ambiguous, the full v0.4 blueprint controls; if the implementation appears to contradict these laws, stop and flag the conflict.

## Objective

- Ultimate objective: sustainable long-run net profit/ROI.
- Daily selection style: genuinely good, research-backed bets across sports; neither raw-win-probability maximization nor tiny-edge EV hunting.
- Normal odds: 1.50–3.00.
- Exceptional short zone: 1.40–1.49 under stricter rules.
- No standard standalone bets below 1.40.
- Daily search/output aims: Mon–Thu 2–5, Fri 4–10, Sat 7–13, Sun 4–10.
- Those ranges are aims, not quotas or caps.
- Breadth before leniency: expand validated coverage before weakening standards.

## Bet quality

- No opaque “confidence 92/100” decision variable.
- Model probability, uncertainty, evidence state, contradictions, price sanity, support region, execution and risk remain separately auditable.
- Price is a guardrail. A slightly near-fair central estimate may still qualify; obvious overpayment must not.
- No requirement to chase or maximize a +EV percentage.

## Staking/risk

- 1u = 2.5% of staking bankroll.
- Supported stake tiers: 1u, 1.5u, 2u, 2.5u, 3u.
- 3u is the initial hard per-bet maximum.
- No cumulative daily turnover cap.
- Approximate initial hard simultaneous open-liability cap: 60% of bankroll.
- Strongly correlated clusters have materially tighter caps (initial design target ~10–12.5%, to be simulated before live).
- Upward bankroll rebase weekly; downward rebase may occur sooner under a configured drawdown rule.
- No Martingale, loss chasing, or autonomous risk-cap increases.

## Research/data

- Immutable evidence.
- Point-in-time causality based on when data was actually ready, not merely event time.
- Frozen evidence pack before qualification.
- Critical volatile evidence is rechecked before execution.
- LLM extracts/structures evidence; it does not invent the live probability or stake.
- Every screened candidate is retained for selection-aware evaluation.
- Selected-set calibration is mandatory.
- Protected holdouts/attempt budgets cannot be controlled by the research agent.

## Execution

- Official supported interfaces only.
- Research code has no live broker credentials/order authority.
- Order submission is deterministic and idempotent.
- UNKNOWN broker state blocks further affected exposure until reconciliation.
- Outcome bets hold to settlement by default; no generic price-drift stop-loss/cash-out.
- No live strategy self-promotion.
- Human approval is required for strategy/live-mode activation, not each individual bet.

## Operations/cost

- Genesis should ultimately run autonomously in the cloud; user's laptop need not stay on.
- Luna/Codex builds and repairs Genesis; it is not the permanent runtime.
- Pre-profit operating-cost target <= £10/month.
- Do not architect around a large mandatory one-off API payment.
- Default OddsPapi planning budget <=7 billable current-data calls/day and <=220/month on one legitimate allowance.
- Do not design around multi-account quota circumvention.

## Daily behaviour

- Never lower qualification standards to meet the day's target.
- Never stop searching early merely because a couple of strong bets have already been found.
- If more than the nominal target range genuinely qualify and portfolio risk permits, more may be placed.
- PASS remains valid when the slate is poor.
