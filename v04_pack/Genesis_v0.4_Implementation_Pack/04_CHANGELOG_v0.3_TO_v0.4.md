# Genesis v0.3 -> v0.4 Material Changelog

## Objective changed

v0.3 framed the project as “win-probability first” with ROI largely secondary. v0.4 clarifies the actual user objective:

- **ultimate goal = long-run profit/ROI**;
- daily selection should favour broadly “good bets” rather than mechanically maximizing win probability or estimated EV;
- small modelled EV differences must not dominate candidate choice.

## Volume changed

v0.3 suggested 0–3 daily selections. v0.4 replaces that with day-of-week search/output aims:

- Mon–Thu 2–5;
- Fri 4–10;
- Sat 7–13;
- Sun 4–10.

These are targets for search breadth, not quotas/caps.

## Odds policy changed

- normal standalone range 1.50–3.00;
- 1.40–1.49 exceptional stricter zone;
- below 1.40 excluded from standard profile;
- >3.00 deferred to separately validated higher-variance strategy.

## Ranking changed

v0.3 recommended ranking qualified bets primarily by conservative win probability. This could collapse into short-price selection.

v0.4:

- uses hard qualification first;
- rejects opaque composite confidence scores;
- uses strategy-defined strength tiers and deterministic portfolio construction;
- avoids raw probability comparison across materially different odds/support regions;
- price sanity is a guardrail, not the objective.

## Price sanity made explicit

Initial v0.4 normal-profile rule:

- price-sanity margin >= 0: normal pass;
- -2 percentage points <= margin < 0: near-fair tolerance zone under strong conditions;
- < -2 percentage points: fail;
- exceptional 1.40–1.49 selections may not use negative tolerance.

This is versioned and must be prospectively tested.

## Staking/risk changed

- 1u = 2.5% bankroll;
- tiers 1, 1.5, 2, 2.5, 3u;
- 3u hard per-bet max;
- no daily turnover cap;
- approximate hard simultaneous open-liability cap 60%;
- materially tighter correlated-cluster caps;
- bankroll scales by units, with weekly upward rebase and faster downward protection.

## Statistical safeguards expanded

Added explicitly:

- winner's-curse/selection-policy evaluation;
- selected-set calibration;
- dependence-aware evaluation;
- full candidate retention;
- PASS gate ablation/counterfactual evaluation;
- protected campaign spending/attempt accounting;
- no direct LLM probability injection.

## Point-in-time controls strengthened

Added explicit distinction between:

- event_time;
- published_at;
- retrieved_at;
- ready_at;
- evidence_cutoff_ts;
- candidate_decision_ts;
- execution_check_ts.

Added mandatory PIT/as-of query layer and frozen evidence packs.

## Operational safety strengthened

Added:

- critical evidence refresh immediately before execution;
- explicit UNKNOWN order state;
- idempotent order intent;
- single-use risk approval;
- fail-closed reason taxonomy;
- market capability registry;
- execution recertification;
- dashboard backed only by reconciled state.

## Cloud/cost target added

- autonomous cloud runtime is the end state;
- laptop does not need to remain on;
- Luna is engineer/researcher, not permanent runtime;
- pre-profit operating budget target <= £10/month;
- no dependency on a large mandatory one-off live API payment;
- venue-agnostic execution interface;
- OddsPapi daily/monthly call budget and batching policy added.
