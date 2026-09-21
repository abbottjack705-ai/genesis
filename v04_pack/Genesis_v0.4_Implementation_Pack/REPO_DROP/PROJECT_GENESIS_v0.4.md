# PROJECT GENESIS v0.4
## Autonomous Multi-Sport Research-Backed Betting System

**Status:** Authoritative post-audit implementation blueprint  
**Date:** 18 September 2026  
**Supersedes:** Project Genesis v0.3 for all new implementation decisions  
**Primary project objective:** Generate sustainable long-run net profit/ROI through a diversified daily portfolio of genuinely good, research-backed sports bets.  
**Bet-level preference:** Prefer bets with strong calibrated model support, current evidence, sensible pricing, controlled uncertainty, and robust execution. Do not mechanically maximize raw win probability, do not mechanically maximize estimated EV, and do not chase tiny modelled edge differences.  
**Normal standalone odds range:** 1.50–3.00 decimal.  
**Exceptional short-price zone:** 1.40–1.49 under a stricter policy.  
**Normal daily search/output targets:** Mon–Thu 2–5, Friday 4–10, Saturday 7–13, Sunday 4–10. These are search/output aims, never quotas or hard caps.  
**Default staking:** 1 unit = 2.5% of current staking bankroll; normal stakes 1–2u; exceptional maximum 3u.  
**Portfolio rule:** no cumulative daily turnover cap; maximum simultaneous open liability approximately 60% of staking bankroll, with materially tighter correlated-cluster limits.  
**Operating-cost constraint before proven profitability:** target <= £10/month fixed infrastructure/data spend, with no assumption of a large mandatory one-off API purchase.  
**Execution philosophy:** official supported interfaces only; venue-agnostic execution layer; no unsupported browser automation.  
**Default bet lifecycle:** outcome bets hold to settlement unless a separately validated strategy version declares another lifecycle.

---

# 1. Executive decision

Project Genesis is an autonomous betting system, not a tipster workflow and not a price-trading robot.

Its job is to:

1. continuously inventory validated sports/markets;
2. screen a broad slate efficiently;
3. identify plausible candidates;
4. collect and freeze point-in-time current evidence;
5. estimate outcome probabilities using validated sport/market models;
6. reject weak, stale, unsupported, contradictory, overpriced, or operationally unsafe candidates;
7. build a diversified portfolio of the best qualified opportunities available that day;
8. size those bets using deterministic tiered unit staking and portfolio limits;
9. place approved bets automatically through a supported execution service when live mode is explicitly enabled;
10. normally hold outcome bets to settlement;
11. reconcile orders and settlement exactly;
12. evaluate whether the complete end-to-end policy produces long-run profit and well-calibrated selections prospectively.

The system is allowed to bet frequently enough to be useful. It should actively search broadly enough that a normal slate commonly produces multiple selections. Conservatism must not become an excuse to search only a tiny corner of the market.

At the same time, Genesis must never relax standards merely because the daily target has not yet been met.

The central operating principle is:

> **Breadth before leniency.** If Genesis is producing too few good bets, expand validated sports, markets, data coverage, and candidate generation before weakening qualification standards.

---

# 2. Fixed user objective

## 2.1 Project-level objective

The ultimate success criterion is **long-run net profitability and ROI after realistic execution, commission, settlement, and operating costs**.

Genesis does not pursue profit by maximizing tiny estimated EV differences among thousands of bets. It pursues profit by finding a diversified daily set of bets that are well supported by models and current research and are offered at prices that are not clearly poor.

## 2.2 What Genesis must not collapse into

Genesis must not become:

- a heavy-favourite selector that simply chooses the lowest available odds;
- an expected-value maximizer that rejects otherwise attractive bets because a modelled edge is +1.2% rather than +2.0%;
- a price-drift or closing-line-value optimizer;
- an arbitrage engine;
- a market-making or scalping system;
- a Martingale/loss-chasing system;
- a daily-quota machine that lowers thresholds to manufacture picks.

## 2.3 Daily output aims

The default search/output aims are:

| Day | Normal target range |
|---|---:|
| Monday–Thursday | 2–5 bets |
| Friday | 4–10 bets |
| Saturday | 7–13 bets |
| Sunday | 4–10 bets |

These ranges are **not hard minimums or maximums**.

Rules:

- Genesis must not lower standards because it is below the daily target.
- Genesis must not stop searching merely because it has reached the lower end of the range.
- If only 0–1 bets genuinely qualify, 0–1 bets are placed.
- If more than the nominal upper target genuinely qualify and risk/correlation limits permit them, Genesis may place more.
- The target changes **search intensity and coverage**, not qualification thresholds.

---

# 3. Odds policy

## 3.1 Default standalone profile

The primary V1 standalone betting profile is:

- **Normal:** 1.50–3.00 decimal;
- **Exceptional short-price:** 1.40–1.49;
- **Below 1.40:** not eligible as a standard standalone bet;
- **Above 3.00:** not part of the normal V1 profile; may later be enabled as a separately validated higher-variance strategy profile.

## 3.2 Why an odds floor exists

Without a floor, a system that likes high win probability can drift toward 1.20–1.40 favourites and create a cosmetically attractive hit rate while producing weak economics.

The 1.50 normal floor is therefore a behavioural guardrail, not a claim that every bet above 1.50 is good.

## 3.3 Exceptional 1.40–1.49 policy

A 1.40–1.49 standalone selection may qualify only if:

- the strategy/model is strongly validated in that exact support region;
- current evidence is complete and fresh;
- critical participant/lineup uncertainty is absent;
- the price-sanity margin is not negative;
- model uncertainty is within the strategy's stricter short-price threshold;
- correlation/risk constraints pass.

The exceptional zone exists to avoid rejecting an unusually strong bet merely because the price is 1.47, while preventing Genesis from becoming a favourites bot.

---

# 4. What a “good bet” means

Genesis must not use an opaque 0–100 confidence score as the reason a bet qualifies.

A good bet is a candidate that passes a set of separately auditable conditions.

The decision record should expose at least:

```text
model_probability
conservative_probability
model_support_status
calibration_status
uncertainty_status
evidence_completeness_status
critical_evidence_status
contradiction_status
price_sanity_status
odds_profile_status
execution_status
risk_status
correlation_status
candidate_expiry_status
final_gate_result
```

The UI may later display a friendly summary, but the underlying decision must remain decomposable.

---

# 5. Price sanity without EV chasing

## 5.1 Core principle

Price matters because a high-probability event can still be a poor bet at a bad price.

However, Genesis must not require a large positive modelled edge or optimize candidates by edge percentage.

## 5.2 Break-even probability

For every candidate, calculate a venue-appropriate break-even probability:

```text
p_break_even = probability required to break even at the executable price,
after relevant commission/fees where applicable.
```

For a simple commission-free back bet at decimal odds O:

```text
p_break_even = 1 / O
```

The execution/settlement adapter owns commission-aware variants.

## 5.3 Near-fair tolerance

Define:

```text
price_sanity_margin = model_probability - p_break_even
```

Initial V1 rule for the normal 1.50–3.00 profile:

- margin >= 0.00: normal price-sanity PASS;
- -0.02 <= margin < 0.00: **near-fair tolerance zone**; may still qualify if all other model/evidence gates are strong and no other soft concern is present;
- margin < -0.02: FAIL price sanity.

The -2 percentage-point tolerance is an **initial policy parameter**, not a discovered law of betting. It must be versioned and tested prospectively. It exists because small probability-estimation errors can make a nominal +1% or -1% modelled edge meaningless, and the user's preference is not to reject attractive bets over tiny estimated differences.

For the exceptional 1.40–1.49 zone, negative price-sanity margin is not allowed.

Genesis must never describe a tolerance-zone bet as “known negative EV.” The correct interpretation is that its central probability estimate sits slightly below the nominal break-even line within model uncertainty.

## 5.4 Price sanity is a gate, not the ranking objective

Among otherwise qualified bets, Genesis does **not** rank by the largest `price_sanity_margin` or estimated EV.

Price sanity prevents obvious overpayment. It does not define the mission.

---

# 6. Candidate qualification

A candidate can qualify only if every mandatory gate passes.

## 6.1 Readiness gates

1. sport/market adapter exists;
2. the exact market family is approved for the strategy version;
3. source/data capability for that competition/event is currently READY;
4. identity mapping is unambiguous;
5. the model artifact is present and hash-matched;
6. the model is inside its validated support region;
7. calibration status is supported for that region;
8. the candidate uses a frozen evidence pack;
9. the candidate is reproducible from frozen inputs.

## 6.2 Current-evidence gates

1. all required critical evidence categories are present;
2. critical evidence is still fresh;
3. required participant/lineup/role/non-runner states meet strategy-specific rules;
4. unresolved critical contradictions are absent;
5. no source/evidence timestamp violates the point-in-time boundary;
6. any expected/uncertain evidence is allowed only where the sport strategy explicitly permits it.

## 6.3 Probability/uncertainty gates

1. calibrated probability exists;
2. a conservative/uncertainty-aware estimate exists;
3. uncertainty is inside a predeclared support threshold for that model/market;
4. stability checks defined by the strategy card pass;
5. selected-set calibration for the active strategy has not triggered quarantine.

There is no single universal minimum win probability across all odds and markets.

## 6.4 Price gates

1. actual observed odds are inside the active odds profile;
2. price sanity passes Section 5;
3. the market is not using stale or invalid odds;
4. executable price/size assumptions meet the strategy's execution rules.

## 6.5 Risk/portfolio gates

1. single-bet stake is within allowed unit tier;
2. simultaneous open liability remains <= hard portfolio cap;
3. correlated-cluster exposure remains within its cap;
4. no duplicate candidate/order intent exists;
5. no kill condition is active;
6. order/account reconciliation state is healthy.

## 6.6 Fail-closed behaviour

Any missing critical field, schema mismatch, timeout, unknown state, gate exception, ambiguous identity, stale evidence, or corrupted artifact must result in PASS or execution block, never automatic qualification.

---

# 7. PASS reason taxonomy

At minimum, support structured reason codes:

```text
PASS_MISSING_EVIDENCE
PASS_STALE_EVIDENCE
PASS_CONTRADICTION
PASS_CRITICAL_UNCERTAINTY
PASS_IDENTITY_AMBIGUOUS
PASS_MODEL_OUT_OF_SUPPORT
PASS_CALIBRATION_UNSUPPORTED
PASS_ODDS_OUTSIDE_PROFILE
PASS_PRICE_SANITY_FAIL
PASS_LIQUIDITY_FAIL
PASS_RISK_LIMIT
PASS_CORRELATION_LIMIT
PASS_EXPIRED_CANDIDATE
PASS_EXECUTION_UNAVAILABLE
PASS_CONFIG_MISMATCH
PASS_GATE_ERROR
PASS_UNKNOWN_STATE
PASS_DATA_CAPABILITY_NOT_READY
PASS_STRATEGY_NOT_APPROVED
QUALIFY_ALL_GATES_PASSED
```

Free-text explanation may accompany a reason code but cannot replace it.

---

# 8. Ranking and portfolio construction

## 8.1 Do not rank the whole slate by raw probability

Raw robust win probability across very different odds ranges naturally favours short prices. Genesis therefore must not simply sort every qualified candidate from highest to lowest `p_lower`.

## 8.2 No opaque master score

Do not create a mysterious weighted score that combines model probability, evidence, EV, source count, LLM sentiment, and uncertainty.

## 8.3 Deterministic portfolio ordering

After hard qualification:

1. assign each candidate a **strategy-defined strength tier** using only auditable model/evidence fields;
2. group candidates by meaningful dependence/correlation cluster;
3. prefer higher strength tiers before lower tiers;
4. within the same tier and comparable price/support region, prefer stronger conservative probability and lower uncertainty;
5. use price sanity as a secondary guard/tie-breaker, not as an edge-maximization target;
6. prefer portfolio diversification when two candidates are otherwise comparable;
7. apply deterministic final tie-breaking by stable candidate ID.

Raw probability should not be compared naively between, for example, a 1.55 football favourite and a 2.70 player market as though they represented the same opportunity class.

## 8.4 Strength tiers

The common core supports stake tiers of:

```text
1.0u
1.5u
2.0u
2.5u
3.0u
```

Each sport/market strategy card must predeclare the exact evidence/model conditions that map a candidate to a tier. No LLM may assign a tier subjectively.

Tier conditions may use:

- uncertainty band;
- calibration/support quality;
- evidence completeness;
- critical evidence certainty;
- model stability;
- validated component agreement;
- price-sanity class;
- prospective selected-set performance.

Tier rules must not use post-outcome information or ad hoc “gut feel.”

---

# 9. Daily search intensity: breadth before leniency

Genesis should be designed to search enough validated opportunities to make the day-of-week output aims plausible.

If output is persistently below target, investigate in this order:

1. insufficient sport/competition coverage;
2. narrow candidate generation;
3. unsupported market families that could be validated next;
4. stale/poor data-source coverage;
5. unnecessarily late research scheduling;
6. overly strict operational requirements unsupported by evidence;
7. only then consider whether a qualification rule itself is mis-specified.

Do **not** lower qualification thresholds merely to hit the daily range.

The system should record:

```text
markets_screened
candidate_universe_size
candidates_modelled
candidates_researched
candidates_qualified
bets_placed
passes_by_reason
near_miss_candidates
search_coverage_by_sport
```

This allows diagnosis of “too conservative” behaviour without forcing bets.

---

# 10. Staking and bankroll policy

## 10.1 Unit definition

```text
1 unit = 2.5% of the staking bankroll
```

At a £100 staking bankroll:

```text
1.0u = £2.50
1.5u = £3.75
2.0u = £5.00
2.5u = £6.25
3.0u = £7.50
```

## 10.2 Stake limits

- most placed bets should normally fall in the 1–2u range;
- 2.5u is reserved for unusually strong validated candidates;
- 3u is the absolute individual-bet maximum under the initial risk policy;
- the research/LLM layer cannot increase the unit schedule;
- stake tier is a deterministic function of the approved strategy card and current portfolio risk.

## 10.3 Bankroll scaling

The staking bankroll should be rebased periodically rather than after every single result.

Initial policy:

- upward rebase: once per week at the scheduled bankroll checkpoint;
- downward rebase: permitted immediately when a configured drawdown trigger is crossed;
- exact downward trigger remains a versioned risk parameter to be determined by simulation before live deployment;
- no autonomous increase in unit percentage above 2.5% without explicit human approval and a new risk-policy version.

## 10.4 No daily turnover cap

Genesis has **no hard cumulative daily amount-staked cap**.

Capital may be reused as earlier Asian/European events settle before later European/US events.

Risk is governed primarily by simultaneous liability and correlation, not by arbitrary total daily turnover.

## 10.5 Simultaneous open liability

Initial hard rule:

```text
maximum simultaneous open liability ~= 60% of current staking bankroll
```

This includes appropriate liability for:

- matched open bets;
- partially matched orders;
- unmatched exposure that could still match;
- pending/unknown orders where exposure cannot yet be ruled out.

The 60% figure is an initial risk-policy parameter to stress-test before live activation.

## 10.6 Correlated-cluster exposure

A much tighter cap applies to bets depending on substantially the same underlying outcome.

Initial design target:

```text
strongly correlated cluster cap ~= 10–12.5% of bankroll
```

Examples of shared risk:

- several bets from the same football match script;
- multiple selections depending on the same player availability;
- several horse bets dependent on the same track/going assumption;
- duplicated exposure to the same team across related markets;
- same event/meeting or shared evidence pack where failure is common-mode.

The exact starting cap must be confirmed by simulation and may vary by strategy family.

---

# 11. Correlation model

V1 does not need a mathematically perfect covariance matrix.

It does need deterministic dependence groups.

Candidate and open-order records should support:

```text
event_id
meeting_id
competition_id
participant_ids
market_family
shared_evidence_ids
selection_dependency_group
correlation_cluster_ids
```

The risk engine must see matched, partially matched, pending, and unknown exposure before granting another stake.

A richer covariance model may be added later if it demonstrably improves risk control.

---

# 12. Immutable evidence and point-in-time causality

## 12.1 Time semantics

Every relevant record should distinguish, where applicable:

```text
event_time
published_at
retrieved_at
ready_at
valid_from
valid_to
superseded_by
```

`event_time` alone is never sufficient to prove historical availability.

For decision features, the critical rule is:

> A record may influence a candidate only if it was available, retrieved, parsed, validated, and ready by the candidate's evidence cutoff.

## 12.2 Three operational times

Keep distinct:

```text
evidence_cutoff_ts
candidate_decision_ts
execution_check_ts
```

New research appearing after the evidence pack is frozen cannot silently mutate an old candidate.

If material critical evidence changes before execution:

1. invalidate the old candidate version;
2. create/freeze a new evidence pack;
3. generate a new candidate decision hash;
4. requalify from scratch.

## 12.3 PIT interface

Strategy/model code must not read unrestricted historical tables directly.

Provide a controlled interface such as:

```text
as_of_query(entity, decision_ts)
feature_view(feature_set_id, decision_ts)
```

It must reject future, late-arriving, superseded, or retrospectively revised records that were not valid/ready at the requested time.

---

# 13. Evidence packs

Before qualification, freeze the complete current-research evidence pack.

Each pack must include or reference:

```text
evidence_pack_id
evidence_pack_hash
evidence_manifest_hash
frozen_at
source_artifact_hashes
extractor_versions
prompt_schema_hash
contradiction_links
freshness/expiry state
```

Corrections create new versions; they never mutate the old pack.

A later auditor must be able to reconstruct exactly what Genesis knew and did not know when a candidate was generated.

---

# 14. LLM/research-agent role

LLMs may:

- discover relevant current sources;
- summarize source material for operator display;
- extract structured claims from prose;
- normalize entities into constrained candidate mappings;
- flag contradictions;
- propose experiments/features;
- diagnose model/system failures;
- generate human-readable explanations from stored evidence and gate results.

LLMs may not:

- directly set live probability;
- assign a subjective live confidence percentage;
- directly choose stake size;
- override a failed gate;
- override risk limits;
- submit a live order;
- alter protected evaluation rules;
- rewrite immutable evidence;
- resolve a critical contradiction after seeing an outcome;
- promote their own strategy to live.

## 14.1 Structured ResearchEvidence

Every AI-extracted current-information claim should contain:

```text
entity/event
claim_category
normalized_claim
source_artifact_hash
source_timestamp
retrieval_timestamp
ready_at
evidence_span/reference
reliability_tier
status = CONFIRMED | EXPECTED | UNCERTAIN | CONTRADICTED
expiry
extractor_version
prompt_schema_hash
contradiction_links
```

No free-text LLM “confidence” field is accepted as a decision input.

## 14.2 Quantitative impact of research

Current research should affect probability only through validated, versioned quantitative features/models.

Where no validated quantitative mapping exists, research may:

- satisfy or fail an eligibility gate;
- increase uncertainty;
- force PASS;
- flag a candidate for requalification;
- appear in the operator explanation.

It must not arbitrarily move a probability from 0.50 to 0.70 because an LLM finds the narrative persuasive.

---

# 15. Critical evidence refresh before execution

Qualification is not permission to submit an order forever.

Immediately before submission, perform a **CriticalEvidenceRefresh** appropriate to the sport/market.

Do not necessarily re-run the entire research pipeline. Refresh only volatile critical categories.

Examples:

Football player-related markets:

- confirmed starting status;
- injury/withdrawal status;
- expected role/minutes if material;
- major late team news.

Horse racing:

- runner still active;
- non-runner changes;
- jockey/runner status;
- material going/conditions changes where strategy-dependent.

Tennis:

- participant still active;
- withdrawal/retirement/injury news where available;
- schedule/venue state if material.

Any material change invalidates the existing candidate and requires a new candidate version or PASS.

---

# 16. Selection-aware statistics and winner's curse

Scanning a large slate and selecting only the best-looking candidates creates selection bias even if the underlying model is broadly calibrated.

Genesis must therefore evaluate the **complete selection policy**, not just the forecasting model.

The frozen policy is conceptually:

```text
inventory full eligible slate
-> generate candidate universe
-> model candidates
-> gather required current evidence
-> hard qualification
-> tier/rank qualified candidates
-> construct risk-compliant portfolio
```

Then evaluate the selections produced by that exact process on fresh/protected/prospective data.

## 16.1 Required safeguards

- retain every screened candidate, not only placed bets;
- record candidate-universe size and selection rank;
- pre-register candidate-generation and selection rules;
- account for adaptive model/prompt/threshold search;
- use shrinkage/regularization appropriate to the model class;
- use protected/prospective evidence for final claims;
- test null simulations where useful to estimate how extreme the “best” candidate can look by chance.

Do not bolt on an arbitrary mathematical winner's-curse penalty merely because the slate is large. Prefer end-to-end selection-policy validation.

---

# 17. Calibration and evaluation

## 17.1 Selected-set calibration is mandatory

A model can be calibrated across all candidates and still be badly overconfident among the tiny subset Genesis actually selects.

Therefore report calibration for:

- all eligible predictions;
- the qualified set;
- the actually selected/placed set;
- predefined odds/support regions;
- chronological periods.

## 17.2 Dependence-aware evaluation

Do not treat every bet as independent.

Where appropriate, use:

- event/day/meeting clustering;
- block bootstrap;
- hierarchical/mixed-effects analysis;
- other predeclared dependence-aware methods.

## 17.3 Primary project metrics

The project-level outcome metrics are:

- net profit after commission/fees/costs;
- ROI/yield;
- bankroll growth/decline;
- drawdown;
- return concentration;
- reliability of prospective performance.

These are the ultimate measures of whether Genesis is making money.

## 17.4 Forecast/selection metrics

Also report:

- observed win rate;
- predicted win probability;
- selected-set calibration;
- Brier/log loss where appropriate;
- calibration by fixed odds/support bands;
- selection volume;
- PASS rate/reasons;
- market-baseline comparison;
- uncertainty coverage;
- prospective research contribution.

## 17.5 Diagnostics, not daily optimization targets

Track but do not optimize daily candidate ranking for:

- estimated EV percentage;
- CLV/BSP movement;
- raw hit rate alone;
- average odds alone;
- number of bets;
- source count;
- narrative strength;
- LLM confidence;
- market volume alone.

---

# 18. PASS evaluation

PASS is a first-class action and must be logged.

Store all passed candidates with frozen inputs and reason codes.

Do not assess PASS quality by simply comparing raw win rate of passed vs placed bets; that is confounded by odds and market type.

Preferred evaluation methods include:

- threshold-neighbourhood analysis;
- odds/support-matched comparisons;
- protected gate ablation studies;
- counterfactual “remove this gate” experiments;
- calibration of candidates near qualification boundaries.

A no-bet day is valid. PASS thresholds must not be tuned repeatedly on protected outcomes.

---

# 19. Protected evaluation

Protected evaluation is owned by a trusted boundary the research agent cannot modify.

Requirements:

- sealed dataset/campaign manifests;
- no raw-label access for research roles;
- registered experiment required before protected access;
- monotonic non-refundable attempt accounting;
- failed/crashed attempts still consume budget;
- family-level/campaign-level attempt limits;
- frozen evaluator artifact/version;
- no arbitrary tiny-slice queries;
- small-cell suppression;
- no raw stack traces/error messages that leak outcomes;
- append-only request audit log;
- controlled summaries only.

If Luna can edit the protected evaluator, it is not protected.

---

# 20. Experiment governance

Every substantive experiment records:

```text
family_id
experiment_id
parent_id
hypothesis
sport/market family
dataset release
candidate universe
features
evidence policy
target
model class
hyperparameter/search budget
training/validation/protected periods
selection policy
odds profile
stake/execution assumptions
primary metrics
secondary metrics
attempt budget
result/disposition
```

Changing prompts, extraction schemas, thresholds, subgroup filters, feature preprocessing, model class, seeds, market families, or primary metrics can constitute adaptive search and must be accounted for.

Protected campaign looks are finite evidence. Repeated confirmation spends the holdout.

---

# 21. Multi-sport architecture

The common core owns:

- immutable evidence;
- point-in-time access;
- identity/provenance contracts;
- experiment governance;
- candidate schema;
- gate engine;
- strategy registry;
- bankroll/risk engine;
- correlation control;
- execution interfaces;
- order state machine;
- settlement ledger;
- protected evaluation;
- audit/observability;
- dashboard/operator controls.

Sport/market adapters own:

- domain-specific feature definitions;
- evidence categories;
- required-evidence rules;
- probability models;
- support regions;
- candidate generation;
- market/settlement metadata;
- sport-specific freshness/invalidation triggers.

Sport adapters may **not**:

- submit orders;
- change live risk caps;
- write directly to settlement ledger;
- bypass PASS/gates;
- read protected labels;
- change execution mode.

---

# 22. Initial sport programme

## 22.1 Horse racing

Horse racing remains a high-value initial branch because of existing Hoofs/Race Shape/Betfair work and rich market/outcome structure.

However:

- Hoofs fields are external model outputs until exact semantics/version behaviour are verified;
- public confidence/rank/minimum-back fields are not automatically treated as calibrated probabilities;
- Race Shape must preserve raw source text and deterministic/versioned extraction;
- report timing/version provenance must be captured prospectively where historical proof is weak;
- non-runner, going, declaration, identity, and settlement rules are critical.

## 22.2 Football

Football should be developed early because it provides large global daily coverage and many candidate market families.

Start with market families where:

- historical data are strong;
- settlement is simple;
- current information can be timestamped reliably;
- the execution venue supports the product.

Dynamic lineup/injury information must distinguish final known state from what was actually available before the decision.

## 22.3 Tennis

Tennis is suitable for an early adapter where surface/form/serve-return data and participant availability are well defined.

Avoid assuming retrospective injury information was known at the historical decision point.

## 22.4 Later sports

Candidates include:

- basketball;
- baseball;
- UFC/MMA;
- badminton;
- other sports where data and execution support are demonstrably ready.

The system should expand breadth only after each adapter passes data-readiness and evaluation gates.

---

# 23. Market capability registry

A market is not “supported” merely because an API returns it.

Track separately:

```text
market_supported_by_data_adapter
market_supported_by_model
market_supported_by_execution_venue
market_settlement_rules_known
market_liquidity_policy_known
market_approved_by_strategy
market_live_allowed
```

Any required false/unknown capability causes PASS.

---

# 24. Source and data readiness

Every external source/provider should record:

```text
source_id
provider
access method
cost tier
entitlement/licensing class
historical availability class
point-in-time reliability
revision behaviour
coverage
rate/quota limits
schema/version information
current operational status
```

Dynamic research features should be prospectively captured unless the provider can demonstrate trustworthy historical point-in-time snapshots.

---

# 25. OddsPapi budget and call economy

The current operational planning assumption supplied by the user is a free allowance of approximately 250 billable calls/month per legitimate account.

Genesis V1 should fit within **one legitimate allowance** and must not rely on rotating accounts/keys to evade quota limits.

Default budget:

```text
hard daily target: <= 7 billable current-data calls
monthly planning target: <= 220 billable calls
reserve: >= 30 calls/month
```

Use batching, caching, and execution windows.

The number of bets must not map one-to-one to API calls.

Typical scheduling concept:

```text
early morning: Asian slate/window
morning: global inventory
midday: European pre-event refresh
afternoon: European execution window
evening: late Europe / early North America
night: US execution window
one flexible retry/contingency call
```

Static metadata should be cached aggressively.

Any endpoint documented as non-metered at implementation time may be used accordingly, but current provider rules must be reverified before deployment.

---

# 26. Cloud/autonomous runtime

Luna/Codex builds and repairs Genesis. Luna is **not** the always-running runtime.

The end-state runtime is ordinary deterministic/cloud software.

Target architecture:

```text
CLOUD SCHEDULER
    |
    v
SLATE / ODDS INGEST
    |
    v
MODEL PRE-SCREEN
    |
    v
SHORTLIST
    |
    v
CURRENT RESEARCH / EVIDENCE CAPTURE
    |
    v
FROZEN EVIDENCE PACK
    |
    v
PROBABILITY + QUALIFICATION
    |
    v
PORTFOLIO / RISK
    |
    v
EXECUTION WINDOW RECERTIFICATION
    |
    v
PAPER OR LIVE BROKER ADAPTER
    |
    v
LEDGER / SETTLEMENT / DASHBOARD
```

The user's laptop should not need to remain on.

## 26.1 Cost target

Before demonstrated profitability:

- target fixed infrastructure/data cost <= £10/month;
- prefer serverless/scheduled jobs over an always-on expensive VM;
- do not purchase expensive sports data or live API access without explicit user approval;
- do not make the architecture dependent on a large mandatory one-off purchase.

The exact cloud provider is an implementation choice and should be selected on current free/low-cost availability at deployment time.

---

# 27. Execution venue abstraction

Genesis must not be architecturally dependent on a single bookmaker/exchange.

Provide a common execution interface with venue-specific adapters.

Betfair may be supported for research/history/development where useful, but the project must not assume the user will pay a large live-key activation fee.

Before any real-money deployment, identify at least one officially supported execution venue whose actual access/costs fit the user's budget.

Rules:

- official/permitted APIs only;
- no unsupported browser automation;
- no requirement to buy an expensive credential merely to continue development;
- any venue's terms, fee, limits, and API capabilities must be reverified immediately before live-readiness approval.

---

# 28. Execution recertification and order state machine

## 28.1 Final execution recertification

Immediately before order submission:

1. verify strategy still ACTIVE;
2. verify candidate not expired;
3. refresh critical volatile evidence;
4. recheck market state;
5. recheck actual executable odds against active profile and candidate policy;
6. verify required liquidity/size;
7. re-run risk/correlation limits;
8. check no kill condition;
9. check no duplicate/unknown order intent.

A candidate approved earlier may still be rejected at execution time.

## 28.2 Order states

At minimum:

```text
ORDER_INTENT_CREATED
RISK_APPROVED
SUBMISSION_PENDING
SUBMISSION_SENT
ACK_RECEIVED
REJECTED
PARTIALLY_MATCHED
FULLY_MATCHED
UNMATCHED
CANCEL_PENDING
CANCELLED
CANCEL_FAILED
UNKNOWN
RECONCILIATION_REQUIRED
SETTLED
VOID
```

## 28.3 Idempotency

Each candidate decision hash may create at most one active live order intent for that strategy/version unless an explicitly versioned replacement rule says otherwise.

Use a deterministic client idempotency key where supported.

A timeout after submission is not permission to submit again.

## 28.4 UNKNOWN means stop

If actual broker state is unknown:

```text
state = UNKNOWN
reconciliation_required = true
block new affected-market/account exposure
```

Query the venue/account state and reconcile before retrying or continuing.

---

# 29. Candidate decision hash and reproducibility

Each candidate should have a stable decision hash built from frozen decision inputs, for example:

```text
candidate_decision_hash = hash(
  strategy_version,
  strategy_config_hash,
  odds_profile_hash,
  sport_adapter_version,
  event_id,
  market_id,
  selection_id,
  side,
  evidence_cutoff_ts,
  candidate_decision_ts,
  evidence_pack_hash,
  feature_manifest_hash,
  model_artifact_hash,
  calibration_artifact_hash,
  gate_policy_hash
)
```

Risk approval and order intent reference this hash; they should not redefine the betting thesis.

Every important run should also preserve a reproducibility manifest including:

```text
git_commit_hash
dependency_lock_hash
runtime/container hash
config_hash
dataset_release_hash
model/calibration hashes
prompt template hash
extractor schema hash
evidence pack hash
feature manifest hash
random seeds
timezone policy
command/run mode
```

---

# 30. Settlement ledger

Profitability claims come only from the tested settlement ledger.

Ledger design must handle:

- matched fragments;
- partial fills;
- unmatched cancellation;
- commission/fees;
- non-runners;
- voids;
- dead heats;
- corrections/resettlements;
- order cancellations;
- actual venue/account reconciliation.

P/L reports may not derive from CandidateBet objects, assumed fills, or notebook shortcuts.

A new market family cannot become live until its settlement edge cases have adversarial tests.

---

# 31. Strategy lifecycle and operating modes

Strategy lifecycle:

```text
IDEA
-> EXPLORATION
-> WALK_FORWARD
-> PROTECTED_CONFIRMATION
-> PROSPECTIVE_SHADOW
-> PAPER
-> MICRO_LIVE_ELIGIBLE
-> APPROVED_LIVE
-> MONITORED
-> QUARANTINED / RETIRED
```

Operating modes:

```text
OFFLINE_RESEARCH
SHADOW
PAPER
MICRO_LIVE
LIVE
DISABLED
KILL_SWITCH_ACTIVE
```

Mode transitions require explicit human authorization and an audit record.

The research agent cannot promote a strategy or enable live mode.

No per-bet human confirmation is required once a strategy is explicitly approved live.

---

# 32. Trust zones

Use practical isolation rather than premature distributed complexity.

## Zone A — Research/LLM

May research, extract, model, propose, diagnose.

Must not possess:

- live broker credentials;
- raw protected holdout labels;
- risk-policy write authority;
- live-mode authority;
- settlement-ledger write authority.

## Zone B — Evidence/PIT

Owns immutable artifacts, manifests, point-in-time access, dataset releases.

## Zone C — Deterministic decision

Owns features, model artifacts, candidate generation, gate engine, PASS/QUALIFY.

No LLM dependency is required at final decision time once structured evidence is frozen.

## Zone D — Risk

Owns stakes, open liability, correlation caps, kill conditions, single-use approvals.

## Zone E — Execution

Owns broker credentials, order state machine, reconciliation.

No LLM in the order path.

## Zone F — Protected evaluation

Owns holdout labels, campaign budgets, controlled metrics.

Research cannot modify it.

## Zone G — Audit/governance

Owns experiment/strategy registries, config versions, mode transitions, approvals, audit logs.

Early V1 may remain a modular monorepo, but protected evaluation and future live execution should run as separate trusted processes/services.

---

# 33. Kill conditions

Block new betting when any of the following is true:

- stale essential feed;
- evidence pipeline failure;
- model/config artifact mismatch;
- account/order state cannot be reconciled;
- execution API instability creates unknown exposure;
- duplicate-order risk;
- open-liability cap reached;
- correlation-cluster cap reached;
- strategy quarantined;
- settlement/ledger integrity failure;
- protected live-readiness condition violated;
- global emergency stop active.

Kill switch stops **new bets**. It does not automatically liquidate existing outcome bets merely because prices move against them.

---

# 34. Dashboard and explainability

The operator dashboard is for oversight, not subjective per-bet approval.

## 34.1 Today

Show:

- sports/markets currently active;
- odds/data call budget used/remaining;
- markets screened;
- candidates modelled/researched;
- qualified bets;
- placed bets;
- PASS reason distribution;
- current open liability;
- correlated-cluster exposure;
- bankroll/current unit size;
- system health and kill state.

## 34.2 Bet detail

Show the actual decision trace:

```text
selection / market
odds at qualification
odds at execution
model probability
conservative probability
break-even probability
price-sanity class
model support/calibration status
uncertainty status
critical evidence status
contradictions
source/evidence links
candidate decision hash
strategy version
stake tier / units
risk approval
order/match state
lifecycle
settlement
```

Then generate a concise human-readable explanation from those stored facts.

Do not invent or expose hidden chain-of-thought as an explanation. The explanation should be a decision trace grounded in actual evidence and gate results.

## 34.3 Rejected candidate detail

For near-miss candidates, display the exact PASS reason(s), e.g.:

```text
PASS_STALE_EVIDENCE
Expected starter not confirmed before cutoff.
```

This lets the user follow Genesis without converting the system into manual betting.

---

# 35. Development sequence v0.4

## Phase 0 — V0.3→V0.4 reconciliation

Before new feature work:

- inspect current fresh Genesis repository;
- map every v0.4 requirement to EXISTING / PARTIAL / MISSING / CONFLICTING;
- do not rebuild working foundations unnecessarily;
- preserve legacy repositories read-only;
- update PROJECT_STATE.md.

**Exit:** approved gap analysis and migration plan.

## Phase 1 — Enforced foundations

Priorities:

1. bitemporal/PIT query layer;
2. append-only evidence manifest and frozen evidence packs;
3. deterministic candidate hashes;
4. fail-closed gate engine and reason-code taxonomy;
5. protected-evaluation service boundary and attempt accounting;
6. reproducibility manifest;
7. adversarial leakage/property tests.

**Exit:** documented principles are encoded as enforceable contracts.

## Phase 2 — Ledger/risk/order contracts

Implement:

- settlement ledger;
- unit/staking policy interfaces;
- simultaneous liability accounting;
- correlation groups;
- single-use risk approvals;
- order state machine;
- idempotency;
- UNKNOWN/reconciliation behaviour;
- paper broker adapter.

No live credentials.

**Exit:** fault-injection and settlement tests pass.

## Phase 3 — Data/source capability and call-budget layer

Implement:

- source capability registry;
- sport/competition readiness states;
- OddsPapi quota tracker/batcher/cache;
- scheduled global execution windows;
- prospective current-evidence capture.

**Exit:** daily slate can be collected within the configured call budget.

## Phase 4 — Horse racing evidence/model branch

Audit actual Hoofs/Race Shape semantics and provenance, ingest market/outcome data, establish baseline models, and prospectively capture reports.

**Exit:** validated horse candidate generation; shadow only.

## Phase 5 — Football branch

Build initial market families with strong historical/current data and broad daily coverage.

**Exit:** calibrated candidate generation and current-evidence pipeline; shadow only.

## Phase 6 — Tennis branch

Build initial supported markets and evidence rules.

**Exit:** calibrated candidate generation; shadow only.

## Phase 7 — Multi-sport portfolio/selection policy

Implement v0.4 odds profile, price-sanity gate, strategy-defined strength tiers, daily search targets, portfolio construction, unit staking, 60% hard open-liability cap, and correlation limits.

**Exit:** deterministic end-to-end paper selections from frozen inputs.

## Phase 8 — Cloud-capable autonomous PAPER Genesis

Deploy scheduled/event-driven runtime with:

- slate ingestion;
- candidate screen;
- research capture;
- evidence freeze;
- models;
- qualification;
- portfolio/risk;
- paper execution;
- settlement;
- dashboard.

Laptop is not required to remain on.

**Exit:** several weeks of uninterrupted prospective paper operation with complete audit trail.

## Phase 9 — Protected/prospective confirmation

Evaluate the complete selection policy, selected-set calibration, PASS gates, dependence, and profitability on fresh evidence.

**Exit:** promotion decision per strategy family.

## Phase 10 — Live venue feasibility

Identify an officially supported execution venue whose current costs/access fit the user's budget. Reverify terms at that time.

Do not purchase a large one-off credential unless the user explicitly approves it and the evidence clearly justifies the expenditure.

**Exit:** execution venue selected or live deployment deferred.

## Phase 11 — Micro-live

Only after explicit human authorization:

- isolated credentials;
- tiny real stakes;
- approved strategies;
- hard caps;
- order/reconciliation testing;
- no change to model thresholds merely because money is live.

**Exit:** operational integrity demonstrated.

## Phase 12 — Live scaling

Scale through the unit/bankroll policy only after prospective live evidence remains consistent with validation.

---

# 36. First research/evaluation programme

## Experiment 0 — Leakage and accounting adversaries

Inject:

- future outcomes;
- final lineups;
- later corrections;
- final BSP/closing prices;
- post-decision research;
- dropped losers;
- duplicate rows;
- same-name identity collisions;
- settlement sign errors;
- optimistic fill assumptions.

Any successful leakage/fictitious-performance attack blocks performance claims.

## Experiment 1 — Market baseline by support region

Establish a strong market-only probability baseline inside the normal odds profile and sport/market support regions.

## Experiment 2 — Sport-specific outcome model

Evaluate calibrated sport/market probability model relative to baseline.

## Experiment 3 — Current research contribution

Prospectively compare the frozen model policy with the same policy using structured current-evidence features/gates.

## Experiment 4 — Selection-policy validation

Evaluate the complete slate→candidate→gate→portfolio process, including winner's-curse effects and selected-set calibration.

## Experiment 5 — PASS gate ablations

On protected/fresh evidence, remove one gate at a time to assess whether it contributes meaningful selection quality.

## Experiment 6 — Staking/risk stress tests

Replay candidate streams under:

- 1–3u schedule;
- 60% open-liability cap;
- proposed correlation caps;
- different sequencing/time-zone overlap;
- clustered loss scenarios.

Do not change selection results during a staking test.

## Experiment 7 — Execution fault tests

Paper/mock tests for duplicate submissions, timeout after submit, partial fills, cancel failure, unknown state, restart recovery, settlement correction.

## Experiment 8 — Autonomous paper runtime

Run Genesis prospectively without manual selection intervention and measure uptime, data freshness, daily search coverage, output volume, calibration, and net paper P/L under conservative fill assumptions.

---

# 37. Promotion/live-readiness criteria

No fixed universal sample count or “one full season” requirement is imposed across every sport.

Each strategy family must preregister:

- minimum sample/information requirement;
- calendar duration/regime coverage;
- uncertainty/calibration target;
- selected-set performance criteria;
- profitability/economic sanity criteria;
- allowed protected-campaign looks;
- execution readiness requirements.

A result may be **INCONCLUSIVE** rather than PASS/FAIL if evidence is insufficient.

Before automatic real-money placement is considered:

- Experiment 0 adversaries pass;
- selected-set calibration is not materially broken;
- point-in-time provenance is defensible;
- protected/prospective evaluation is complete enough for the registered criterion;
- no unresolved critical identity/source/settlement weakness exists;
- execution state machine passes fault injection;
- paper runtime operates autonomously and reproducibly;
- human explicitly approves the strategy version, venue, bankroll, and risk policy.

---

# 38. Model/agent authority

## Luna / coding agent may autonomously modify

- parsers;
- feature implementations;
- model training code;
- ordinary tests/fixtures;
- diagnostics;
- adapters under fixed core contracts;
- dashboards;
- documentation;
- performance optimizations that preserve invariants;
- ordinary bug fixes.

## Luna may propose but must not autonomously weaken/change

- protected evaluation controls;
- holdout definitions/access;
- attempt accounting;
- point-in-time rules;
- evidence immutability;
- PASS fail-closed behaviour;
- settlement arithmetic invariants;
- live execution authority;
- risk-cap percentages;
- staking unit percentage;
- live-mode transitions;
- broker credential paths;
- idempotency/unknown-state rules;
- strategy-promotion status;
- tests enforcing protected invariants.

Changes to those require explicit human approval and a versioned decision record.

---

# 39. Required adversarial/contract tests

At minimum:

## Evidence/PIT

- future record rejected;
- late-arriving record rejected;
- revised historical record cannot mutate old decision;
- artifact overwrite/delete rejected;
- evidence pack mutation changes hash;
- direct strategy raw-table bypass denied.

## Protected evaluation

- raw label query denied;
- one-event/tiny-cell query denied or suppressed;
- failed attempt still consumed;
- attempt counter cannot reset;
- evaluator modification blocked;
- unregistered protected request denied.

## Candidate/gates

- same frozen inputs => same candidate hash;
- missing critical evidence => PASS;
- contradiction => PASS where critical;
- config hash mismatch => PASS;
- gate exception => PASS;
- unsupported market => PASS;
- price-sanity failure => PASS.

## Risk/execution

- duplicate candidate submission blocked;
- risk approval replay rejected;
- expired approval rejected;
- timeout after submit does not duplicate order;
- unknown state blocks new exposure;
- partial fill reconciles correctly;
- mode SHADOW/PAPER cannot reach real-order path;
- kill switch blocks new orders.

## Settlement

- partial fill then cancel;
- void;
- dead heat;
- non-runner;
- commission edge cases;
- corrections/resettlement;
- duplicate settlement event;
- ledger/account reconciliation.

## Concurrency

- two workers same candidate;
- simultaneous risk approvals;
- evidence update during decision;
- mode change during execution;
- concurrent correlated selections.

## Research/LLM

- expected claim cannot silently become confirmed;
- no LLM probability field accepted;
- prompt/schema change creates new extraction version;
- missing evidence span downgrades/rejects per policy;
- post-result contradiction resolution cannot mutate historical evidence.

---

# 40. Documentation contract

Maintain at minimum:

```text
PROJECT_STATE.md
ARCHITECTURE.md
DATA_DICTIONARY.md
SOURCE_AVAILABILITY.md
ASSUMPTIONS.md
RESEARCH_PROTOCOL.md
RULES_AND_ACCOUNTING.md
RISK_POLICY.md
EXECUTION_POLICY.md
TEST_EVIDENCE.md
OPERATIONS_RUNBOOK.md
AUDIT_LOG.md
EXPERIMENT_REGISTRY
STRATEGY_CARDS/
DECISIONS/
```

Every milestone distinguishes:

- implemented/proven behaviour;
- assumptions;
- unsupported capabilities;
- unresolved evidence;
- known risks;
- next required proof.

---

# 41. Facts and assumptions requiring re-verification

Before relying operationally on any external provider, reverify current official terms.

Items explicitly identified by the 18 September 2026 external-verification audit include:

- Betfair delayed/live application-key capabilities and fees;
- Betfair stream/order/rate/concurrency limits;
- commission/account-specific terms;
- settlement rules for each activated market;
- historical-data package fields/coverage;
- Hoofs field semantics/versioning/publication timing;
- Race Shape timing/version provenance;
- OddsPapi current quota/batching/non-metered endpoint rules;
- execution API availability/cost for any venue considered for live use;
- licensing/entitlement terms for any data source used systematically.

Do not embed a changing provider fee or rate limit into project law.

---

# 42. Definition of success

Success is not:

- hitting the daily target by lowering standards;
- backing mostly heavy favourites;
- finding the largest theoretical EV number;
- an impressive backtest;
- a high raw win rate;
- a persuasive LLM narrative;
- a profitable week;
- a pretty dashboard.

Success is:

> **An autonomous, auditable, low-cost multi-sport system that repeatedly finds a useful daily portfolio of genuinely good bets, places them only when model support, current evidence, price, uncertainty, execution and risk all justify the action, and produces sustainable prospective net profit without hidden leakage, uncontrolled exposure, or subjective AI overrides.**

---

# 43. Immediate instruction to the implementation agent

Do **not** start by implementing new betting strategies.

First reconcile the current v0.3-based repository against this v0.4 blueprint.

Required first deliverable:

```text
V03_TO_V04_GAP_ANALYSIS.md
```

For every material v0.4 requirement, classify:

```text
EXISTING
PARTIAL
MISSING
CONFLICTING
NOT_YET_APPLICABLE
```

For each PARTIAL/MISSING/CONFLICTING item, identify:

- current modules/files;
- required migration;
- dependency order;
- tests needed;
- whether the change touches a protected invariant;
- whether human approval is required before implementation.

Do not rebuild working foundations unnecessarily.

Do not enable live betting.

Do not modify legacy repositories.

Update `PROJECT_STATE.md` and create a concise handoff after the gap analysis.
