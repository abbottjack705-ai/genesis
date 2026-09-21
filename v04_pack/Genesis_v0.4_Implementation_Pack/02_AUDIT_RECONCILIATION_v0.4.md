# Project Genesis v0.4 — Multi-Model Audit Reconciliation

**Date:** 18 September 2026  
**Purpose:** Record how v0.3, five independent review perspectives, and subsequent user clarifications were reconciled into the authoritative v0.4 blueprint.

This is not a vote. Recommendations were accepted only where they improved validity or implementation without changing the user's objective.

---

# 1. Sources reconciled

## Source A — Project Genesis v0.3

Starting architecture:

- immutable evidence;
- point-in-time decision boundary;
- protected evaluation;
- deterministic risk/execution;
- PASS-first selection;
- sport-specific models/adapters;
- automatic execution as end state;
- hold-to-settlement default;
- no generic stop-loss/cash-out;
- initial win-probability-first framing.

## Source B — Gemini 3.6 Flash Extended decision-science audit

Primary concerns:

- raw win-probability ranking degenerates toward shortest prices;
- price-agnostic high-confidence betting can be negative EV;
- large-slate top-K selection creates winner's-curse bias;
- LLM research must not arbitrarily alter probabilities;
- sport-specific models/common selection core are appropriate.

## Source C — Perplexity external-verification audit

Primary concerns:

- real Betfair API/delayed/live behaviour and costs;
- delayed production credentials are not a sandbox;
- settlement/reconciliation details;
- account-specific commission and API limitations;
- Hoofs/Race Shape semantics/provenance uncertainty;
- retrospective lineup/injury state is not automatically point-in-time evidence;
- data/source entitlements and sport-specific availability;
- explicit UNKNOWN broker state.

## Source D — Grok operational-failure audit

Primary concerns:

- critical evidence changes between qualification and execution;
- correlation across bets;
- stale odds/liquidity at submission;
- duplicate orders after restart/timeouts;
- LLM turning rumours into confirmed evidence;
- role/minutes uncertainty;
- immutable strategy lifecycle;
- concurrency bypassing risk caps;
- UI/ledger state mismatch;
- stale evidence packs;
- quota pressure forcing picks;
- settlement bugs feeding false history;
- kill checks must run before every order.

## Source E — DeepSeek using the Nemotron statistical-red-team prompt

Primary concerns:

- winner's curse from broad slate screening;
- selected-set rather than only marginal calibration;
- LLM latent leakage/high-dimensional adaptive search;
- dependence across events/days/participants;
- multiple comparisons;
- PASS evaluation;
- odds-band/hit-rate gaming;
- protected holdout spending;
- optimistic execution/settlement assumptions;
- diagnostic drift into post-hoc optimization.

## Source F — Qwen 3.8 Max software-architecture review

Primary concerns:

- documented invariants must become technical contracts;
- bitemporal PIT semantics and controlled `as_of` access;
- protected-evaluation side channels;
- attempt accounting can be gamed;
- opaque confidence composites;
- LLM indirect influence;
- evidence pack freezing;
- deterministic candidate hashes;
- fail-closed PASS;
- order state machine/idempotency;
- process/trust boundaries;
- reproducibility manifests;
- adversarial/property/concurrency tests;
- explicit agent authority limits.

## Source G — User clarifications after audits

Final clarified intent:

- ultimate project objective is profit/ROI;
- user does not want the system to obsess over a couple of modelled EV percentage points;
- user wants daily bets, not merely a tiny number of heavy favourites;
- daily aims: Mon–Thu 2–5, Fri/Sun 4–10, Sat 7–13;
- targets must not be forgotten in the name of conservatism and must not be pursued by weakening standards;
- normal odds 1.50–3.00; 1.40–1.49 exceptional;
- initial bankroll £100;
- 1u = 2.5%; tiered stakes through 3u / £7.50 maximum at £100;
- no cumulative daily turnover cap;
- about 60% maximum simultaneous open liability, with capital reused across Asian/European/US event windows;
- cloud-autonomous runtime preferred; laptop should not need to stay on;
- pre-profit fixed cost target about £10/month;
- large one-off API expenses such as hundreds of pounds are not realistic;
- OddsPapi usage should fit within <8 billable calls/day through batching/caching.

---

# 2. Major reconciliation decisions

## 2.1 Objective: CHANGE from v0.3

**v0.3:** maximize robust probability of winning inside an odds band.  
**v0.4:** maximize sustainable long-run profit/ROI through a daily portfolio of genuinely good bets, while avoiding both raw-probability/favourite bias and tiny-edge EV chasing.

**Reason:** User clarified profit is the actual project objective and daily bet quality should not collapse into heavy favourites.

**Status:** ACCEPT USER CLARIFICATION / SUPERSEDES V0.3.

---

## 2.2 Short-odds degeneracy

**Gemini / Qwen finding:** raw probability ranking naturally chooses shorter odds.

**Decision:** ACCEPT THE FAILURE MODE, REJECT EV-MAXIMIZER REPLACEMENT.

v0.4 changes:

- normal odds floor 1.50;
- separate 1.40–1.49 stricter zone;
- no ranking of the entire slate by raw probability;
- strategy-defined strength tiers;
- raw probability comparisons only inside comparable support/price regions;
- portfolio diversification included in deterministic ordering.

---

## 2.3 Price sanity

**Gemini recommendation:** mandatory +3 percentage-point edge over market.  
**Qwen recommendation:** conservative probability above break-even plus buffer.

**Decision:** MODIFY.

The user explicitly does not want an otherwise strong bet rejected over a tiny estimated EV difference.

v0.4 therefore uses:

```text
margin = model_probability - commission-adjusted break-even probability
```

Initial policy:

- >=0: normal PASS;
- -2 percentage points to 0: near-fair tolerance under strong conditions;
- below -2 percentage points: FAIL;
- exceptional 1.40–1.49 bets require non-negative margin.

This is a guardrail against obvious overpayment, not a daily edge-ranking target.

---

## 2.4 Winner's curse / slate selection bias

**Gemini + DeepSeek convergence:** selecting top estimates from a huge slate creates upward bias.

**Gemini solution:** explicit extreme-value correction formula.  
**DeepSeek solution:** selection-adjusted evaluation, shrinkage, fresh confirmation.

**Decision:** ACCEPT THE PROBLEM; MODIFY THE SOLUTION.

v0.4 does not mandate one universal formula based on raw candidate count. Instead it requires:

- retain all candidates;
- predeclare candidate universe and selection policy;
- selected-set calibration;
- end-to-end evaluation of the actual slate→gate→portfolio algorithm;
- regularization/shrinkage appropriate to model class;
- protected/prospective validation;
- optional null simulation to quantify how extreme best-of-slate noise can look.

---

## 2.5 LLM probability adjustment

**Gemini:** bounded log-odds evidence update.  
**Grok:** separate model and evidence-adjusted probability.  
**DeepSeek/Qwen:** LLM research should be a noisy structured feature source, not a direct probability setter.

**Decision:** REJECT direct qualitative probability adjustment; ACCEPT structured evidence architecture.

v0.4 rule:

- LLM extracts/structures point-in-time evidence;
- if a feature's quantitative effect is validated, a frozen model may use it;
- otherwise evidence may affect eligibility, uncertainty, contradictions, or PASS;
- no LLM-generated probability/confidence field is accepted live.

---

## 2.6 Opaque confidence score

**Qwen + user:** an assumed “confidence %” can be misleading.

**Decision:** STRONGLY ACCEPT.

v0.4 exposes separate auditable fields rather than a hidden 0–100 score.

Stake tiers must be strategy-defined from explicit fields, not subjective LLM confidence.

---

## 2.7 Daily volume

**v0.3:** conservative 0–3/day.  
**User:** wants meaningful daily action across sports.

**Decision:** SUPERSEDE V0.3.

v0.4 aims:

- Mon–Thu 2–5;
- Fri 4–10;
- Sat 7–13;
- Sun 4–10.

These are search/output targets, never minimum quotas or hard maximums.

Named principle added: **Breadth before leniency.**

---

## 2.8 PASS evaluation

**Gemini:** proposed a raw passed-vs-qualified win-rate metric.  
**DeepSeek:** PASS should be evaluated as first-class action.

**Decision:** ACCEPT PASS evaluation, REJECT raw AES-style comparison as sufficient.

v0.4 uses:

- complete PASS logging;
- odds/support-matched analysis;
- threshold-neighbourhood analysis;
- protected gate ablation/counterfactual experiments.

---

## 2.9 Selected-set calibration

**DeepSeek:** calibration over all candidates can hide overconfidence among the actual 0–N picks.

**Decision:** STRONGLY ACCEPT.

v0.4 requires calibration reporting for:

- all predictions;
- qualified set;
- selected/placed set;
- fixed support/odds regions;
- chronological periods.

---

## 2.10 Dependence/correlation

**Grok + DeepSeek + Qwen:** same-event/day/team/meeting/evidence dependencies invalidate naive independent risk/evaluation.

**Decision:** STRONGLY ACCEPT.

v0.4 includes:

- deterministic correlation/dependency groups;
- tight correlated-cluster exposure cap;
- dependence-aware evaluation;
- future richer covariance modelling only if justified.

---

## 2.11 Staking

**User decision:** units and tiered stakes.

**Decision:** ACCEPT AS PROJECT POLICY.

v0.4:

- 1u=2.5% bankroll;
- tiers 1, 1.5, 2, 2.5, 3u;
- 3u hard initial single-bet maximum;
- weekly upward rebase;
- faster downward protection under a configured drawdown trigger;
- no autonomous increase in unit percentage.

Exact tier mapping remains strategy-specific and must be validated/auditable.

---

## 2.12 Open liability vs daily turnover

**User decision:** no cap on cumulative daily money wagered; about 60% max open liability at once.

**Decision:** ACCEPT.

v0.4 removes v0.3's generic “maximum daily amount staked” concept as a hard project law.

Capital may turn over across Asian, European and US time windows.

Risk is governed by current liability/correlation.

---

## 2.13 Critical evidence refresh

**Grok:** qualification can become stale before placement.

**Decision:** STRONGLY ACCEPT.

v0.4 introduces `CriticalEvidenceRefresh` immediately before execution, limited to volatile sport/market-critical facts rather than an expensive full research rerun.

Material change creates a new candidate version or PASS.

---

## 2.14 PIT/bitemporal semantics

**Qwen + Perplexity:** final historical state is not the same as information actually known at decision time.

**Decision:** STRONGLY ACCEPT.

v0.4 formalizes:

```text
event_time
published_at
retrieved_at
ready_at
valid_from
valid_to
superseded_by
```

and requires a controlled `as_of` interface.

---

## 2.15 Frozen evidence packs and candidate hashes

**Qwen:** without content-addressed frozen packs and deterministic decision hashes, later reconstruction can drift.

**Decision:** STRONGLY ACCEPT.

v0.4 requires:

- frozen evidence pack before qualification;
- immutable pack hashes;
- extractor/prompt/source hashes;
- deterministic candidate decision hash;
- risk/order objects reference the candidate rather than redefining it.

---

## 2.16 Protected evaluation side channels

**Qwen:** label leakage can occur via tiny slices, logs, error messages, repeated micro-tests, evaluator modification.

**Decision:** STRONGLY ACCEPT.

v0.4 protected evaluator:

- separate trusted boundary;
- no raw labels;
- small-cell suppression;
- monotonic non-refundable attempts;
- controlled summaries;
- no arbitrary filters/debug leakage;
- research agent cannot modify evaluator.

---

## 2.17 Execution UNKNOWN/idempotency

**Perplexity + Grok + Qwen:** ambiguous broker acknowledgement is a major duplicate-order risk.

**Decision:** STRONGLY ACCEPT.

v0.4 adds:

- explicit order state machine;
- deterministic/idempotent order intent;
- single-use risk approval;
- UNKNOWN/RECONCILIATION_REQUIRED;
- affected new exposure blocked until actual state is known.

---

## 2.18 Settlement

**Perplexity + Grok + Qwen:** settlement bugs can manufacture fictitious performance.

**Decision:** STRONGLY ACCEPT.

All P/L derives from the tested settlement ledger. New market families require adversarial settlement tests before live use.

---

## 2.19 Betfair dependency and cost

**Perplexity:** live Betfair access carries important credential/cost/production-data constraints.  
**User:** cannot realistically pay hundreds of pounds unless profit is nearly certain.

**Decision:** REMOVE BETFAIR LIVE KEY AS AN ARCHITECTURAL ASSUMPTION.

v0.4:

- keeps a venue-neutral execution interface;
- may use Betfair data/history/development where useful;
- requires current verification of any live venue later;
- pre-profit cost target <=£10/month;
- no large mandatory one-off credential is assumed.

---

## 2.20 OddsPapi usage

**User:** 250 free calls/month available; wants <8/day.  
**Decision:** design to one legitimate allowance rather than key rotation.

v0.4 planning target:

- <=7 current-data billable calls/day;
- <=220/month;
- >=30-call reserve;
- batching/caching/execution windows;
- bet count does not equal call count.

Provider rules must be reverified at implementation time.

---

## 2.21 Cloud/autonomous operation

**User:** wants laptop-free autonomous operation, ideally almost free.

**Decision:** ACCEPT AS END-STATE RUNTIME REQUIREMENT.

v0.4 separates:

- Luna/Codex as engineering/research agent;
- Genesis as scheduled/event-driven cloud runtime.

Cloud provider is deliberately not frozen; select based on current cost/free tier at deployment.

---

# 3. Auditor recommendation matrix

| Source | Recommendation | Resolution |
|---|---|---|
| Gemini | Short-odds degeneracy is real | ACCEPT |
| Gemini | Mandatory +3pp edge | MODIFY/REJECT AS UNIVERSAL |
| Gemini | Extreme-value formula based on N | REJECT AS UNIVERSAL; use end-to-end selection evaluation |
| Gemini | Bounded LLM log-odds update | REJECT for V1 |
| Gemini | Sport-specific models/common core | ACCEPT |
| Gemini | Remove casual longshot exceptions | ACCEPT |
| Perplexity | Delayed credential != sandbox | ACCEPT / reverify operationally |
| Perplexity | Account/market-specific commission | ACCEPT |
| Perplexity | Historical/current data provenance warnings | ACCEPT |
| Perplexity | Hoofs/Race Shape not self-authenticating | ACCEPT |
| Perplexity | UNKNOWN execution state | ACCEPT |
| Perplexity | Sport/data capability gates | ACCEPT |
| Grok | Execution-time critical evidence refresh | ACCEPT |
| Grok | Correlation graph/groups | ACCEPT, simple deterministic V1 |
| Grok | Recheck price/liquidity at submit | ACCEPT |
| Grok | Duplicate/restart protection | ACCEPT |
| Grok | Explicit evidence-status enum | ACCEPT |
| Grok | Model vs LLM “evidence-adjusted probability” | REJECT/MODIFY; no unvalidated second probability |
| Grok | Immutable strategy lifecycle | ACCEPT |
| Grok | Continuous kill checks before each order | ACCEPT |
| DeepSeek/Nemo | Winner's curse | ACCEPT |
| DeepSeek/Nemo | Selected-set calibration | STRONGLY ACCEPT |
| DeepSeek/Nemo | Full candidate retention | ACCEPT |
| DeepSeek/Nemo | Hierarchical Bayesian shrinkage mandatory | MODIFY; require appropriate regularization, not one model family |
| DeepSeek/Nemo | One full season before live | REJECT AS UNIVERSAL; use preregistered information/duration criteria |
| DeepSeek/Nemo | PASS first-class evaluation | ACCEPT |
| DeepSeek/Nemo | ROI/CLV always diagnostic only | MODIFY: ROI is ultimate project outcome, not daily ranking target |
| Qwen | Technical enforcement over documentation | STRONGLY ACCEPT |
| Qwen | PIT `ready_at`/as-of layer | STRONGLY ACCEPT |
| Qwen | Protected evaluator side-channel controls | STRONGLY ACCEPT |
| Qwen | Candidate decision hashes | ACCEPT |
| Qwen | Fail-closed PASS reason taxonomy | ACCEPT |
| Qwen | Direct LLM probability prohibited | ACCEPT |
| Qwen | Full live process isolation now | MODIFY; interfaces now, heavy runtime isolation before MICRO_LIVE |
| Qwen | Cryptographic signatures everywhere now | MODIFY; hash/version/freeze now, stronger signing where trust boundary requires later |
| Qwen | No autonomous changes to protected invariants | ACCEPT |

---

# 4. Items intentionally left parameterized

The following are not forgotten; they remain parameters to determine through simulation/validation rather than arbitrary universal constants:

- exact per-strategy stake-tier mapping;
- exact drawdown threshold that triggers immediate downward bankroll rebase;
- exact correlated-cluster cap within the initial 10–12.5% design range;
- sport/market-specific uncertainty thresholds;
- support-region definitions;
- minimum sample/information requirements for promotion;
- current live execution venue;
- exact cloud provider;
- current provider pricing/rate limits;
- higher-variance >3.00 strategy policy.

Changing these later requires a versioned decision, not silent mutation.

---

# 5. Fixed “do not drift back” list

Do not allow future agents/auditors to silently turn Genesis into:

- pure favourite selection;
- pure EV ranking;
- price-drift trading;
- arbitrage/market making;
- a 0–3 picks/day ultra-conservative system that stops searching too early;
- a daily quota system that manufactures picks;
- an LLM narrative selector;
- a platform requiring a £499 one-off credential simply to function;
- a laptop-bound process that consumes Luna usage continuously;
- a system where a high-level confidence number hides uncertainty/evidence problems.

The authoritative project intent is the v0.4 blueprint plus `PROJECT_LAWS_v0.4.md`.
