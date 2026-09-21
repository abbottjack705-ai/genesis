# Project Genesis V0.3 → V0.4 gap analysis

**Status:** Baseline gap analysis updated after approved foundation migration  
**Date:** 2026-09-18  
**Repository:** the fresh Genesis repository in this workspace  
**Authoritative pack:** `v04_pack/Genesis_v0.4_Implementation_Pack/`  
**Pack SHA-256:** `B3EC282FA431002D0AD14C999B88C902BA398FC02CD479BD4DA13C465CB1B0F9`

## 1. Scope and authority

The user's request is the controlling instruction for this document. The V0.4
files are treated as the specification. The original analysis below is kept as
the pre-implementation baseline; the post-migration status section records
only claims supported by current code and tests.

This analysis therefore:

- preserves the current Genesis implementation and all existing V0.3 files;
- preserves `C:\Users\abbot\Documents\sports-lab` and
  `C:\Users\abbot\Documents\Codex\2026-09-11\ca\work\m9_repair` as
  read-only legacy material;
- unpacks the supplied V0.4 pack into `v04_pack/` only;
- does not add strategies, outcome experiments, network adapters, credentials,
  live betting, or provider-specific deployment;
- records ambiguity as a gap instead of inferring provider or sport semantics.

The complete supplied pack was read. The primary comparison sources were:

1. `01_PROJECT_GENESIS_v0.4.md`;
2. `02_AUDIT_RECONCILIATION_v0.4.md`;
3. `03_PROJECT_LAWS_v0.4.md`;
4. `04_CHANGELOG_v0.3_TO_v0.4.md`;
5. `05_DECISION_AND_RISK_POLICY_v0.4.md`;
6. `06_RUNTIME_AND_COST_TARGET_v0.4.md`;
7. `07_RISK_POLICY_DRAFT.yaml`;
8. `08_ODDSPAPI_BUDGET_DRAFT.yaml`;
9. `09_V0.4_ACCEPTANCE_CHECKLIST.md`;
10. the three supplied prompt files, treated as subordinate process guidance.

## 2. Repository baseline inspected

The current repository is a fresh, offline-only V0.3 foundation. Relevant
existing files are:

- `src/genesis/repro.py`, `evidence.py`, `provenance.py`, and `time.py` for
  hashing, immutable publication, provenance, and UTC/PIT primitives;
- `src/genesis/canonical.py` and `labels.py` for sport-neutral records and
  decision/future-label separation;
- `src/genesis/registry.py` for dataset, experiment, attempt, and strategy
  registries;
- `src/genesis/coverage.py` for coverage and exclusion ledgers;
- `src/genesis/evaluation.py` for the protected-evaluation interface skeleton;
- `src/genesis/selection.py` and `reasons.py` for PASS-first gates and reason
  codes;
- `src/genesis/accounting.py` for deterministic odds, exposure, and settlement
  arithmetic;
- `src/genesis/config.py`, `config/defaults.json`, and `requirements.lock` for
  pinned configuration and dependencies;
- `src/genesis/logging.py` for structured redacted JSONL audit events;
- `PROJECT_STATE.md`, `ARCHITECTURE.md`, `SOURCE_AVAILABILITY.md`,
  `RESEARCH_PROTOCOL.md`, `RULES_AND_ACCOUNTING.md`, and `TEST_EVIDENCE.md`;
- the seven existing test modules under `tests/`.

The baseline suite previously passed 14 tests with no failures or errors, and
`compileall` passed. The suite is synthetic and offline; it is not evidence of
profitability, model quality, data availability, or live readiness.

## 3. Classification legend

| Classification | Meaning in this analysis |
|---|---|
| **EXISTING** | The current repository already enforces the material V0.4 contract, with no migration required for this concern. |
| **PARTIAL** | A sound foundation exists, but material fields, enforcement, or scope are still missing. |
| **MISSING** | No current implementation or enforceable interface exists. |
| **CONFLICTING** | Current behaviour or documented policy would violate the V0.4 contract if reused unchanged. |
| **NOT_YET_APPLICABLE** | Intentionally deferred until a later phase; no implementation should be added during this analysis. |

## 4. Executive result

The V0.3 foundation is reusable and should be extended, not rewritten. The
strongest existing contracts are content-addressed evidence, append-only
hash-chain logs, basic availability/PIT checks, future-label separation,
dataset/experiment/strategy registries, PASS-first qualification, and
deterministic arithmetic.

The material V0.4 gaps are:

1. a controlled bitemporal `as_of_query`/`feature_view` boundary rather than
   only timestamp validation;
2. frozen, reconstructible evidence packs and deterministic candidate decision
   hashes;
3. an expanded canonical candidate/market/source capability model;
4. exact V0.4 fail-closed reason taxonomy, price sanity, odds profiles, and
   tier/portfolio ordering;
5. full candidate retention and selected-set/PASS evaluation governance;
6. units, bankroll/liability, dependence groups, single-use approvals, and
   unknown-exposure risk interfaces;
7. paper-mode order state/idempotency/reconciliation and a settlement ledger;
8. source capability/quota, provider-neutral venue, and cloud-runtime
   interfaces;
9. deterministic policy configuration and the associated adversarial tests.

No live venue, OddsPapi entitlement, Hoofs/Race Shape semantics, sport model,
or provider fee/rate-limit fact is currently verified. These are recorded as
capability or re-verification dependencies, not guessed.

## 5. Requirement classification matrix (pre-migration baseline)

The classifications and “current evidence” in this section describe the
repository immediately before the approved migration. They are preserved for
auditability; the post-migration status in Section 9 is the current claim.

### 5.1 Objective, laws, and selection behaviour

| ID | Material V0.4 requirement | Classification | Current evidence and impact |
|---|---|---|---|
| GOV-01 | Ultimate objective is sustainable long-run net profit/ROI through a diversified daily portfolio; do not mechanically maximise raw probability, EV, price drift, or quotas. | **CONFLICTING** | `README.md` and the V0.3 framing describe the old probability-first foundation, and `src/genesis/selection.py::rank_qualified` orders the whole qualified set by `conservative_probability`. The repository has no strategy, but this ranking cannot be carried forward unchanged. |
| GOV-02 | Normal standalone odds are 1.50–3.00; 1.40–1.49 is an exceptional stricter zone; below 1.40 and above 3.00 are outside the initial profile. | **PARTIAL** | `CandidateBet` validates only `odds > 1`; `GenesisConfig` has an opaque `odds_profile` string. There is no executable normal/exceptional policy. |
| GOV-03 | Daily search/output aims are Mon–Thu 2–5, Fri 4–10, Sat 7–13, Sun 4–10; aims are neither quotas nor caps, and breadth precedes leniency. | **MISSING** | No day-aware search-intensity policy, slate metrics, near-miss record, or explicit non-quota guard exists. `max_bets_per_day` in `config/defaults.json` is the wrong concept and is zero by default. |
| GOV-04 | PASS is valid; standards must not be weakened to hit a target; no opaque confidence score. | **PARTIAL** | PASS-first gates and a `ReasonCode` enum exist, but V0.4's decomposable fields and no-opaque-ranking rule are not complete, and raw probability still drives ranking. |
| GOV-05 | Prohibited drift: favourite bot, pure EV ranker, price-trading/arbitrage/scalping, Martingale, or quota picker. | **EXISTING for the current offline boundary** | No such strategy or live capability exists; `RESEARCH_PROTOCOL.md` explicitly prohibits strategy search, edge experiments, and live orders in the foundation. Future ranking/config changes must preserve this invariant. |

### 5.2 Evidence, provenance, and point-in-time causality

| ID | Material V0.4 requirement | Classification | Current evidence and impact |
|---|---|---|---|
| EVD-01 | Evidence bytes are immutable/content-addressed and manifests are append-only/tamper-evident. | **EXISTING** | `src/genesis/evidence.py` and `repro.py` use full SHA-256, no-overwrite publication, atomic writes, and a hash-chained manifest; tests cover idempotence and tampering. |
| EVD-02 | Source provenance and availability contracts distinguish historical, prospective, derived, assumed, live, unknown, and future-label states. | **PARTIAL** | `src/genesis/provenance.py` and `SOURCE_AVAILABILITY.md` cover the classes and basic window checks. V0.4 additionally requires provider capability, entitlement, revision, coverage, quota, schema, and operational readiness records, which are absent. |
| EVD-03 | Records distinguish `event_time`, `published_at`, `retrieved_at`, `ready_at`, `valid_from`, `valid_to`, and `superseded_by`; ready-by-cutoff is enforced. | **PARTIAL** | `time.py`, `EvidenceMetadata`, `MarketSnapshot`, `DecisionFact`, and `ProvenanceRef` cover some fields and enforce `ready_at`. Publication validity, supersession, and a uniform bitemporal record are missing. |
| EVD-04 | Strategy/model code can use only a controlled `as_of_query(entity, decision_ts)` or `feature_view(feature_set_id, decision_ts)` that rejects late/future/superseded records. | **MISSING** | The current code validates supplied objects but has no query service, feature-view contract, revision selection, or denial of unrestricted historical-table access. |
| EVD-05 | Freeze a complete evidence pack before qualification, with pack/manifest/source/extractor/prompt/schema hashes, contradictions, and expiry; corrections create new versions. | **MISSING** | `CandidateBet` has only an opaque `evidence_pack_id`; there is no `EvidencePack`, frozen manifest, pack hash, or reconstruction API. |
| EVD-06 | Corrections never mutate history and material pre-execution changes invalidate the candidate and require a new pack/version. | **PARTIAL** | Immutable artifacts and append-only logs provide the base, but there is no supersession/invalidation relation or pre-execution refresh contract. |
| EVD-07 | Every candidate has a deterministic decision hash over frozen strategy/config/odds/adapter/evidence/feature/model/calibration/gate inputs, and risk/order records reference it. | **PARTIAL** | Canonical serialization and hashes exist, and `CandidateBet` is serializable, but no decision-hash schema or downstream reference exists. |
| EVD-08 | Structured research evidence contains source span/timestamp/retrieval/ready/expiry/extractor/prompt schema/contradictions, and an LLM cannot directly set probability, stake, gates, or orders. | **PARTIAL** | `ResearchEvidence` has normalized claims, source refs, status, retrieval, expiry, extractor version, and contradictions. It lacks `ready_at`, evidence span, prompt schema hash, and an enforcing extractor/decision boundary. |

### 5.3 Canonical data and capability contracts

| ID | Material V0.4 requirement | Classification | Current evidence and impact |
|---|---|---|---|
| DATA-01 | Canonical sport/event/market/participant schemas support identity, event/meeting/competition, market family, selection, source and settlement metadata. | **PARTIAL** | `canonical.py` has participant, event, market snapshot, research evidence, and candidate records. It lacks meeting/competition IDs, explicit market capability/settlement/liquidity fields, validity lineage, and the expanded correlation/dependency identifiers. |
| DATA-02 | A market capability registry separately tracks data, model, venue, settlement, liquidity, strategy approval, and live eligibility. | **MISSING** | No capability registry or fail-closed lookup exists. `selection.qualify` accepts only a single `market_supported` boolean. |
| DATA-03 | Candidate records expose model/conservative probability, calibration, uncertainty, evidence, contradiction, price, odds, execution, risk, correlation, expiry, and final gate status. | **PARTIAL** | `CandidateBet` has probabilities, evidence completeness, uncertainty flags, contradiction, odds, timestamps, and reasons, but not the V0.4 status dimensions, price-sanity calculation, calibration/support hashes, tier, portfolio IDs, or execution/risk state. |
| DATA-04 | Retain every screened candidate and record universe size, rank, research/model/qualification stages, PASS reasons, near misses, and sport coverage. | **PARTIAL** | `CoverageLedger`/`ExclusionLedger` can record availability/exclusion, but there is no candidate-universe/run schema or retention pipeline. |

### 5.4 Qualification, ranking, and statistical governance

| ID | Material V0.4 requirement | Classification | Current evidence and impact |
|---|---|---|---|
| SEL-01 | Qualification order includes source readiness, PIT/frozen pack, model support/calibration, critical freshness, contradiction, odds, price sanity, uncertainty, portfolio, and execution readiness; all unknowns fail closed. | **PARTIAL** | `selection.qualify` has a small explicit gate set and returns PASS on failure, but it does not enforce the V0.4 ordering or all gates. |
| SEL-02 | Support the exact structured PASS taxonomy, including missing/stale evidence, contradiction, identity, model support/calibration, odds, price, liquidity, risk, correlation, expiry, execution, config, unknown, capability, and strategy approval. | **PARTIAL** | `reasons.py` contains useful generic reasons such as `STALE_EVIDENCE`, `PRICE_SANITY_FAILED`, and `UNKNOWN_ORDER_STATE`, but names and coverage do not match the V0.4 taxonomy and there is no taxonomy version/validation. |
| SEL-03 | Do not rank the whole slate by raw probability or opaque score; use auditable strategy-defined strength tiers, dependence, comparable regions, diversification, and stable IDs. | **CONFLICTING** | `rank_qualified` sorts by conservative probability before stable ID. V0.4 requires replacement with tiered portfolio ordering; this is a behavioural migration, not a cosmetic rename. |
| SEL-04 | Unit tiers 1.0, 1.5, 2.0, 2.5, 3.0 are deterministic from an approved strategy card; LLMs cannot assign tiers. | **MISSING** | No unit, tier, bankroll, strategy-card mapping, or stake decision interface exists. |
| STAT-01 | Retain the full candidate universe and evaluate the complete slate→gate→tier→portfolio policy, not only the forecasting model. | **MISSING** | `evaluation.py` evaluates a callback over supplied frames and returns Brier only; it has no candidate-run manifest, selection policy, rank, or portfolio evaluation. |
| STAT-02 | Report calibration for all eligible, qualified, selected/placed sets, support/odds regions, and chronological periods; use dependence-aware methods. | **MISSING** | There is no calibration report or dependence grouping in the current package. |
| STAT-03 | Evaluate PASS as a first-class action with threshold-neighbourhood, matched, protected gate-ablation, and counterfactual interfaces. | **MISSING** | PASS is logged as a selection result, but no PASS evaluation data model or protected ablation interface exists. |
| STAT-04 | Protected evaluation has sealed manifests, no raw labels, registered requests, non-refundable campaign/family budgets, evaluator freeze, small-cell suppression, controlled summaries, and append-only request audit. | **PARTIAL** | `ProtectedEvaluationService` keeps labels private to an in-process closure and `ExperimentRegistry` has basic non-refundable attempts. There is no trusted process boundary, campaign/family budget, sealed evaluator, suppression, side-channel policy, or request audit. |
| STAT-05 | Experiment registry records the full experiment/provenance schema and accounts for adaptive search, prompt/schema/threshold/model/seed/market changes. | **PARTIAL** | `ExperimentSpec` and attempts cover identity, hypothesis, dataset, features, periods, metrics, and a finite budget. It lacks evidence policy, candidate universe, model class, search details, odds/stake/execution assumptions, prompt/schema changes, and campaign/family accounting. |

### 5.5 Risk, execution, and settlement

| ID | Material V0.4 requirement | Classification | Current evidence and impact |
|---|---|---|---|
| RSK-01 | `1u = 2.5%` of current staking bankroll; deterministic 1–3u tiers; 3u hard single-bet maximum; weekly upward and trigger-based downward rebase. | **MISSING** | `accounting.py` has money and liability arithmetic, while `config.py` has an old `max_daily_stake`; neither implements bankroll or unit policy. |
| RSK-02 | No cumulative daily turnover cap; simultaneous open liability about 60% of bankroll, including matched, partial, unmatched, pending, and unknown exposure. | **PARTIAL** | `MatchedFragment.liability` is reusable arithmetic, but there is no exposure ledger. `max_daily_stake` is conceptually conflicting and must not become the V0.4 risk control. |
| RSK-03 | Deterministic event/meeting/competition/participant/market/evidence/dependency/correlation groups and a 10–12.5% initial cluster limit. | **MISSING** | No correlation/dependence IDs or risk aggregation exist. |
| RSK-04 | Single-use risk approval, no duplicate intent, kill condition, and fail-closed treatment of pending/unknown exposure. | **MISSING** | No risk approval object, approval consumption, kill switch, or order/exposure state exists. |
| EXE-01 | Provider-neutral official execution interface with venue adapters; no unsupported browser automation or mandatory expensive Betfair key. | **MISSING** | There is deliberately no execution module. The absence is correct for this phase, but a paper-capable interface is required before later runtime work. |
| EXE-02 | Pre-submission recertification refreshes volatile evidence, market/odds/liquidity, strategy, expiry, risk/correlation, kill, duplicate, and unknown state. | **MISSING** | No execution boundary or `CriticalEvidenceRefresh` contract exists. |
| EXE-03 | Order state machine includes intent, risk approval, submission, acknowledgement, partial/full/unmatched, cancellation, UNKNOWN, reconciliation, and settlement; retries are idempotent. | **MISSING** | No order or venue state module exists. |
| EXE-04 | Operating modes and transitions require explicit human authorization/audit; research cannot enable live mode or place orders; kill switch blocks new bets only. | **PARTIAL** | `OperationalMode` and `StrategyRegistry` lifecycle/approval references exist, and live is disabled. There is no mode transition service, human authorization artifact, kill-switch state, or paper/live separation. |
| SET-01 | All P/L derives from a tested settlement ledger, not candidate objects or assumed fills; handle fragments, cancellation, fees, corrections, and reconciliation. | **PARTIAL** | `accounting.py` has deterministic primitives for back/lay, commission, void, non-runner, and dead heat, and `MatchedFragment` supports fragments. There is no append-only ledger, fill/correction/reconciliation model, or source-of-truth report. |
| SET-02 | Each activated market family has venue-specific settlement edge-case tests before live use. | **NOT_YET_APPLICABLE** | No market family or venue is activated. The migration must create the test interface, but specific rules require a later approved venue/source. |

### 5.6 Runtime, cost, source budget, and operational readiness

| ID | Material V0.4 requirement | Classification | Current evidence and impact |
|---|---|---|---|
| OPS-01 | Deterministic configuration and dependency locking cover policy versions, unit/risk/odds/selection/mode settings, and reproducibility hashes. | **PARTIAL** | `config.py` validates a JSON config against `requirements.lock` and computes a digest. It does not model the V0.4 policy documents, config schema version, or complete run manifest. |
| OPS-02 | Source readiness records provider, access, cost, entitlement, historical/PIT reliability, revision, coverage, quota, schema, and operational status. | **MISSING** | `SourceContract` is a useful availability primitive, but no source capability/readiness registry is implemented and no external source is active. |
| OPS-03 | OddsPapi operates within one legitimate allowance: <=7 billable current-data calls/day, <=220/month, >=30 reserve; batching/caching; hard fail-safe when exhausted; no key rotation. | **MISSING** | No call ledger, quota policy, batching/cache interface, or fail-closed odds capability exists. The YAML in `v04_pack/` is a planning draft, not current code or verified provider terms. |
| OPS-04 | End-state cloud scheduler/stateless jobs/small durable DB/immutable object store/cache/dashboard/monitoring; laptop need not remain on. | **MISSING** at interface level; deployment is **NOT_YET_APPLICABLE** | The repository is a local offline library. No scheduler, worker, durable store, cache, dashboard, or monitoring interface exists. Actual provider selection must wait for current cost/terms verification. |
| OPS-05 | Fixed pre-profit infrastructure/data target is <=£10/month and no large mandatory one-off API purchase. | **MISSING** as a cost-control contract; live procurement is **NOT_YET_APPLICABLE** | No cost ledger or budget check exists. No purchase should be made during this migration. |

### 5.7 Documentation, boundaries, and testing

| ID | Material V0.4 requirement | Classification | Current evidence and impact |
|---|---|---|---|
| DOC-01 | Project state, architecture, laws, risk, assumptions, source availability, acceptance evidence, and migration state stay aligned with V0.4. | **PARTIAL** | Strong V0.3 foundation docs exist, but they explicitly describe V0.3/current foundation and there is no V0.4 risk policy, execution policy, capability registry, or migration handoff. This analysis intentionally does not rewrite them. |
| DOC-02 | Research/LLM, evidence/PIT, deterministic decision, risk, execution, and protected-evaluation trust zones are enforced by authority boundaries. | **PARTIAL** | The current package has logical separation and no live credentials/order path, but no separate risk/execution authority or protected process boundary. |
| DOC-03 | Future labels remain separate from decision-time inputs. | **EXISTING** | `labels.py`, `DecisionFact`, `DecisionFrame`, `FutureOutcomeLabel`, dataset manifest disjointness, and tests enforce the current generic boundary. |
| DOC-04 | Config, reason codes, logs, registry records, and arithmetic are deterministic and auditable. | **PARTIAL** | Canonical hashes, append-only registries, Decimal arithmetic, and redacted JSONL exist. V0.4 needs policy-version hashes, exact reason taxonomy, decision/run IDs, and stronger audit/reconciliation coverage. |
| TEST-01 | Synthetic adversarial tests cover future-data leakage and ready-by-decision semantics. | **EXISTING** for current contracts | `tests/test_time_and_labels.py` covers future-ready inputs and future-label fields. It does not yet cover bitemporal query/revision or frozen-pack mutation. |
| TEST-02 | Deterministic probability/odds/accounting and reproducibility tests exist. | **EXISTING** for current primitives | Existing tests cover Decimal odds, probabilities, back/lay, commission, void/non-runner/dead heat, canonical serialization, and tree hashes. |
| TEST-03 | V0.4 adversarial/property/concurrency tests cover selection bias, PASS, dependence, risk caps, idempotency, UNKNOWN, settlement ledger, quota, and side channels. | **MISSING** | The current 14-test suite has no implementation to exercise these contracts. Tests should be added with each future migration stage, before live capability. |
| LEG-01 | Legacy repositories remain read-only; Hoofs/Race Shape/Betfair assumptions are not silently inherited. | **EXISTING** | `LEGACY_INVENTORY.md` records `m9_repair` and other material as read-only, and no legacy code is imported. The V0.4 horse-racing note remains a future adapter dependency, not a reusable fact. |
| SPORT-01 | Horse racing, football, tennis, and later adapters are expanded only after data/model/settlement/execution readiness. | **NOT_YET_APPLICABLE** | No sport adapter or strategy is active. Implementing one now would violate the requested gap-analysis scope. |
| LIVE-01 | Live activation, credentials, real-money venue, and provider terms are only considered after paper/prospective evidence and explicit human approval. | **NOT_YET_APPLICABLE** | Live is disabled and no credentials exist. The boundary is a protected future gate, not a Phase 0 implementation target. |

## 6. Migration detail for PARTIAL, MISSING, and CONFLICTING items

The following rows give the required current files, smallest safe change,
dependencies, risks, tests, and approval needs. “Protected invariant” means a
change could affect leakage prevention, immutable history, reproducibility,
PASS/fail-closed behaviour, or live-authority boundaries.

| IDs | Affected current files/modules | Smallest safe migration | Dependencies/order | Migration risk / protected invariant | Tests required before acceptance | Human approval before implementation |
|---|---|---|---|---|---|---|
| GOV-01, GOV-02, GOV-03, GOV-04, SEL-03 | `README.md`, `src/genesis/selection.py`, `src/genesis/canonical.py`, `config/defaults.json` | Freeze a versioned V0.4 policy object. Replace raw-probability whole-slate sorting with explicit strategy tier/region/portfolio interfaces. Add normal and exceptional odds profile evaluation and day-of-week search metrics without making a quota or cap. | First freeze policy schemas; then candidate fields; then gates; portfolio ordering comes after dependence fields. | **High.** A ranking or target change can silently create favourite bias or quota-driven bets. Preserve PASS-first and stable-ID determinism. | Table tests for odds boundaries, non-quota targets, raw-probability cross-region ordering, stable ties, PASS at every failed gate, and “no early stop at lower target.” | Yes for policy semantics and any change to the V0.3 objective/ranking invariant. |
| EVD-02, EVD-03, EVD-04, OPS-02 | `src/genesis/provenance.py`, `src/genesis/time.py`, `src/genesis/evidence.py`, `SOURCE_AVAILABILITY.md` | Add a versioned source capability/readiness record and a controlled PIT repository API. Represent valid intervals, publication/retrieval/ready times, revisions, supersession, and admissibility at a requested cutoff. Do not remove current checks. | Schema/policy version first; evidence metadata and append-only revision records; controlled query; adapter integration last. | **Critical.** Incorrect revision selection or late-arriving acceptance creates future-data leakage and invalidates all evaluation. | Future-ready rejection, late-arriving rejection, valid interval boundary tests, supersession selection, unknown capability fail-closed, immutable correction tests, and property tests over timestamp orderings. | Yes for PIT semantics, source entitlement assumptions, and any protected boundary change. |
| EVD-05, EVD-06, EVD-07, OPS-01 | `src/genesis/evidence.py`, `src/genesis/canonical.py`, `src/genesis/repro.py`, `src/genesis/registry.py` | Add immutable `EvidencePack`/manifest records, pack freeze/version rules, candidate decision-hash builder, and a reproducibility manifest. Make corrections produce a new pack and candidate version. | Controlled PIT/evidence metadata must exist first; model/calibration/feature artifact hashes then become required hash inputs. | **Critical.** Mutable pack membership or incomplete hash inputs permits decision drift and false reconstruction. Preserve old evidence object hashes and append-only manifests. | Same-input same-hash; changed source/config/model hash changes decision hash; pack freeze rejects mutation; missing hash fails closed; correction invalidates old candidate; full replay reconstructs the decision. | Yes before changing canonical candidate identity or making a pack eligible for qualification. |
| EVD-08, DATA-03 | `src/genesis/canonical.py`, `src/genesis/labels.py`, `src/genesis/evidence.py`, `RESEARCH_PROTOCOL.md` | Extend research evidence with `ready_at`, evidence span, prompt schema hash, and explicit claim status. Add a structured extractor boundary that returns evidence/uncertainty/contradiction only; do not accept LLM probability, stake, or gate overrides. | Evidence/PIT and pack freeze first; extractor schema is hashed into the pack; quantitative model mapping remains a later approved strategy concern. | **High.** Narrative fields can become an untracked second probability model or post-outcome correction path. Preserve label separation and no-direct-LLM invariant. | Schema rejects free-text confidence/p; LLM output cannot call risk/order APIs; evidence status and expiry gates behave deterministically; post-outcome claims are rejected. | Yes for any LLM/data authority change. |
| DATA-01, DATA-02, DATA-04, SEL-01, SEL-02 | `src/genesis/canonical.py`, `src/genesis/coverage.py`, `src/genesis/selection.py`, `src/genesis/reasons.py` | Extend canonical IDs/fields, add a market capability registry, add candidate-run/universe retention records, and version the exact V0.4 reason taxonomy. Refactor `qualify` into a pure ordered gate object that fails closed on UNKNOWN. | Evidence pack/PIT and policy schemas; then candidate/run records; then gate engine; portfolio and execution status later. | **High.** Broadening schemas can accidentally make absent fields default-pass. Do not infer capabilities from an API response. | Missing/unknown field tests; capability matrix false/unknown → PASS; exact code serialization; gate ordering; all candidates retained including excluded/near-miss; replay of a candidate run. | Yes for gate taxonomy and capability policy; no approval for additive tests. |
| STAT-01, STAT-02, STAT-03 | `src/genesis/evaluation.py`, `src/genesis/registry.py`, `src/genesis/selection.py`, `src/genesis/coverage.py` | Add candidate-universe/run manifests, selection-policy artifacts, rank/portfolio outputs, calibration report interfaces, dependence-aware grouping, and PASS/ablation request types. Keep the current Brier skeleton as a low-level primitive. | Candidate decision hashes, run retention, dependence IDs, and experiment/campaign registry must precede evaluation reports. | **Critical.** Evaluating only placed bets creates selection bias and may make PASS appear profitable for the wrong reason. Protected datasets must remain label-private. | Full-universe retention; selected-set vs all/qualified calibration shape; chronological/dependence blocks; PASS threshold-neighbourhood and matched analyses; no hidden candidate drop. | Yes for protected metric definitions and selection-policy changes. |
| STAT-04, STAT-05 | `src/genesis/evaluation.py`, `src/genesis/registry.py`, `RESEARCH_PROTOCOL.md` | Replace the in-process skeleton for protected campaigns with a trusted-boundary interface and sealed evaluator artifact. Add family/campaign budgets, monotonic attempt ledger, small-cell suppression, controlled errors, and append-only request audit. Expand experiment spec to include V0.4 governance fields. | Candidate/run manifests and registry versioning; evaluator isolation; only then protected campaigns. | **Critical.** Side channels, retry refunds, tiny slices, or evaluator edits leak labels and consume protected evidence invisibly. | Crash/timeout consumes attempt; repeated request cannot refund; tiny-cell suppression; label absence in process/API/logs; immutable evaluator version; unauthorized evaluator mutation rejected; campaign/family budgets enforce. | Yes for protected-access boundary and every protected campaign. |
| RSK-01, RSK-02, RSK-03, RSK-04 | `src/genesis/accounting.py`, `src/genesis/config.py`, `src/genesis/canonical.py` | Add versioned risk policy, bankroll/unit calculator, exposure ledger, deterministic dependence groups, correlation cluster aggregation, single-use risk approvals, and UNKNOWN exposure blocking. Deprecate `max_daily_stake` as a V0.4 hard control; retain only as an explicit legacy field until removed by a reviewed config migration. | Candidate/correlation IDs and order states; policy config; then risk calculation; execution adapter later. | **Critical.** Concurrent approvals or omission of pending/unknown exposure can exceed caps. Do not silently reinterpret old daily stake fields. | Decimal unit/stake boundary tests; 3u maximum; no daily turnover cap; 60% liability aggregation across states; cluster cap; concurrent approval single-use; duplicate decision/order; UNKNOWN blocks affected exposure; deterministic replay. | Yes for risk policy values, bankroll rebasing, and any live-eligible risk change. |
| EXE-01, EXE-02, EXE-03, EXE-04 | New `src/genesis/execution.py` and `risk.py` interfaces; `src/genesis/config.py`, `registry.py`, `selection.py` | Define provider-neutral paper interface, critical refresh result, order state machine, idempotency key, reconciliation boundary, mode/kill-switch authority, and adapter contract. Implement only a deterministic mock/paper adapter in the later migration; do not add credentials or live adapter. | Candidate decision hash → risk approval → recertification → paper order state → reconciliation. | **Critical.** Retry after timeout can duplicate an order; a default UNKNOWN can leak exposure; mode authority can be bypassed. No LLM or research callback may reach this boundary. | State transition table; idempotent repeated submit; timeout → UNKNOWN/reconciliation; duplicate intent rejection; critical evidence invalidation; mode authorization audit; kill blocks new orders but does not rewrite settled history. | Yes for mode authority, order semantics, venue terms, and any live adapter. |
| SET-01 | New `src/genesis/ledger.py`; `src/genesis/accounting.py` | Keep arithmetic primitives and add an append-only fill/order/settlement/correction ledger. Derive P/L only from matched fragments, venue rules, commission, cancellations, voids, non-runners, dead heats, and reconciliation records. | Paper order state and venue-neutral fill schemas; market-specific rules; then reporting. | **Critical.** Arithmetic can be correct while ledger lifecycle is wrong, manufacturing profit. Preserve settlement-boundary quantization and immutable corrections. | Fragment/partial-fill/cancel tests; commission and settlement variants; correction/resettlement lineage; reconciliation mismatch; P/L never reads `CandidateBet` assumptions; property tests for conservation. | Yes before a market family or venue is declared paper/live eligible. |
| OPS-03, OPS-04, OPS-05 | New `src/genesis/quota.py`, runtime interfaces; `src/genesis/config.py`, `logging.py` | Add provider-neutral call-budget ledger and cache/batch request planner with hard fail-closed exhaustion. Define scheduler/job/storage/monitoring ports and a cost ledger without choosing a cloud provider or purchasing data. | Source capability registry; provider term verification; then quota policy; runtime ports; deployment last. | **High.** Quota pressure must never force selections, and a provider's changing free allowance must not be treated as project law. | Daily/monthly/reserve boundary tests; one request for batch; cache hit no billable call; exhausted quota blocks odds-dependent decisions; no key rotation; cost overrun blocks deployment plan; deterministic job replay. | Yes for provider terms, cost target exceptions, and deployment. |
| DOC-01, DOC-02, OPS-01, TEST-03 | `PROJECT_STATE.md`, `ARCHITECTURE.md`, `TEST_EVIDENCE.md`, current config/docs | After implementation milestones—not now—update documentation with actual evidence links, trust-zone authority, policy hashes, and test results. Add tests before each protected-contract change. | The code contracts and tests must exist before claims are updated. | **Medium/High.** Documentation can overstate readiness; current V0.3 status must not be marked V0.4 complete prematurely. | Documentation consistency check; all matrix classifications trace to code/tests; full suite and adversarial suite; no optimistic checklist marks without evidence. | Yes for policy/objective changes; documentation-only factual updates otherwise. |

## 7. Protected invariants that migration must preserve

These are non-regret boundaries already present or explicitly required by
V0.4:

1. raw evidence is content-addressed, immutable, and never overwritten;
2. append-only manifests and registries are verified before replay;
3. every decision input is UTC-normalized and ready by its cutoff;
4. future outcome labels cannot enter decision frames;
5. protected attempts are monotonic and never refunded;
6. PASS is fail-closed and has a structured reason;
7. no LLM or research callback can set live probability, stake, risk, or order;
8. no unknown broker/exposure state is treated as safe;
9. settlement reports use actual ledger events, not candidate assumptions;
10. live credentials and legacy repositories remain outside this workspace's
    current implementation scope.

## 8. Explicitly deferred, not silently omitted

The following are not implementation gaps to close in this task:

- Hoofs, Race Shape, Betfair, OddsPapi, bookmaker, or other provider
  integration until terms, entitlement, timing, and schema are verified;
- sport-specific models, candidate strategies, edge searches, backtests, or
  outcome experiments;
- selection of a cloud provider or purchase of any API/credential;
- real-money execution, micro-live, live mode, or live venue approval;
- market-family-specific settlement rules without an identified venue;
- any claim of profitability, calibration, or live readiness.

These are marked `NOT_YET_APPLICABLE` where appropriate and remain later
gates in the migration plan.

## 9. Post-migration implementation status

Status labels below are evidence-backed and narrower than the original gap
classification. `IMPLEMENTED` means code and deterministic tests support the
foundation contract. `PARTIAL` means an interface exists but a protected,
durable, provider, or production boundary remains. `REMAINING` means no code
was added because the requirement is deliberately deferred.

| Gap IDs | Current status | Evidence |
|---|---|---|
| GOV-01–04, OPS-01, RSK-01–02 | **IMPLEMENTED for foundation policy interfaces** | `policy.py`, extended `config.py`, `selection.py`, and V0.4 tests; strategies and empirical validation remain absent. |
| EVD-02–04, DATA-02 | **IMPLEMENTED for synthetic controlled PIT/capability interfaces** | `pit.py`, `capabilities.py`, and future-ready/unknown-capability tests; no external source is active. |
| EVD-05–08, DATA-03 | **IMPLEMENTED for frozen-pack/hash contracts; partial adapter integration** | `evidence_pack.py`, `decision.py`, extended canonical records, and hash mutation tests; source-store supersession automation remains partial. |
| DATA-01, DATA-04, SEL-01–02 | **IMPLEMENTED for canonical/gate/run interfaces** | extended `canonical.py`, `candidate_runs.py`, exact V0.4 reasons, `qualify_v04`, and retention tests. |
| SEL-03–04 | **IMPLEMENTED for deterministic policy ordering** | tier/odds-region ordering and unit policy tests; no strategy card exists. |
| STAT-01–03 | **PARTIAL** | `selection_evaluation.py` provides aggregate all/qualified/selected and PASS-ablation request shapes; no protected prospective calibration campaign has run. |
| STAT-04–05 | **PARTIAL** | `protected.py` provides suppression and monotonic attempt reservations; evaluator remains in-process and full campaign governance is not production-isolated. |
| RSK-01–04 | **IMPLEMENTED for offline reservation contracts; partial durability** | `risk.py` and tests cover units, caps, correlation, UNKNOWN blocking, single-use approvals, rebase, and audit; no production exposure service exists. |
| EXE-01–04 | **IMPLEMENTED for paper-only state contracts; live remains deferred** | `execution.py` covers recertification, idempotency, state transitions, mode authority, and kill switch; no venue adapter or credentials. |
| SET-01 | **IMPLEMENTED for generic ledger foundation; market rules deferred** | `ledger.py`, correction-aware P/L, and replay tests. |
| SET-02 | **REMAINING** | No market family or venue is activated. |
| OPS-02–05 | **PARTIAL** | `pit.py`, `quota.py`, and `runtime.py` provide readiness/quota/cost ports; no provider terms, cloud deployment, or external calls. |
| DOC-01–04, TEST-01–03 | **PARTIAL/IMPLEMENTED as documented** | state, architecture, evidence, and 28-test results updated; separate-process protected evaluation and production observability remain. |
| LEG-01 | **IMPLEMENTED** | Legacy repositories remain unchanged and no code is imported. |
| SPORT-01, LIVE-01 | **REMAINING / NOT YET APPLICABLE** | No sport adapter, strategy, credential, provider, or live capability was added. |

## 10. Safe conclusion

The V0.3 foundation is a valid base for V0.4, but it is not V0.4-complete.
The first implementation work after review should extend PIT/evidence-pack
and reproducibility contracts, then the pure gate/candidate-run interfaces,
then protected evaluation and risk/paper execution contracts. Existing
evidence, time, registry, accounting, and label-separation code should be
preserved and tested against the new contracts rather than rewritten for
names alone.
