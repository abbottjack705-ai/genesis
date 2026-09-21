# Project Genesis V0.4 migration plan

**Status:** Approved foundation migration implemented with documented partial boundaries  
**Date:** 2026-09-18  
**Depends on:** `V03_TO_V04_GAP_ANALYSIS.md`  
**Scope:** V0.3 foundation → V0.4 foundation contracts  
**Explicitly excluded:** strategies, outcome experiments, network APIs, credentials, live orders, and live deployment

## 1. Planning authority and guardrails

The supplied V0.4 blueprint is authoritative for implementation decisions. The
user approved this plan for foundation implementation. The implementation
instructions embedded in the pack are followed only within the user's stated
offline/paper-only boundary.

The current Genesis repository remains the authoritative implementation. The
unpacked pack under `v04_pack/` is source material. The legacy repositories
remain read-only and are not migration inputs except through the explicit
decisions already recorded in `LEGACY_INVENTORY.md`.

Migration principles:

1. preserve working V0.3 foundations and their tests;
2. make leakage prevention and fail-closed behaviour stronger before adding
   breadth or convenience;
3. add interfaces and paper/mock contracts before any venue-specific code;
4. version policy/artifacts instead of silently changing old meaning;
5. keep decision-time inputs and future labels physically/logically separate;
6. never let daily targets, quota pressure, or missing data create a bet;
7. require explicit human approval for protected-evaluation, risk-policy,
   mode-authority, provider, and live-boundary changes.

## 2. Target dependency order

```text
V0.3 baseline freeze
        |
        v
Versioned V0.4 policy/config schemas
        |
        v
PIT + source capability + evidence revisions
        |
        v
Frozen evidence packs + reproducibility manifest + candidate decision hash
        |
        v
Expanded canonical candidate/run/capability records
        |
        v
Pure fail-closed gates + exact reason taxonomy + odds/price policy
        |
        +------------------------------+
        v                              v
Full candidate retention        Protected evaluation boundary
and portfolio interfaces        and attempt governance
        |                              |
        +--------------+---------------+
                       v
Risk units/liability/correlation/single-use approvals
                       |
                       v
Paper order state/idempotency/UNKNOWN/reconciliation
                       |
                       v
Settlement ledger and accounting reports
                       |
                       v
Quota/source-budget and provider-neutral runtime interfaces
                       |
                       v
Cloud deployment and sport/venue adapters (later, separately approved)
```

The arrows are hard dependencies for correctness, not merely preferred
project management order. For example, a gate cannot safely use a price or
model artifact until its evidence pack and decision hash can be reconstructed;
a risk cap cannot be trusted until pending/unknown order exposure has a defined
state.

## 3. Ordered migration stages

### Stage 0 — Baseline freeze and review checkpoint

**Purpose:** establish the V0.3 reference before any implementation change.

**Keep:** `src/genesis/repro.py`, `evidence.py`, `provenance.py`, `time.py`,
`labels.py`, `registry.py`, `coverage.py`, `evaluation.py`, `accounting.py`,
`selection.py`, `logging.py`, current docs, and the existing tests.

**Actions after this plan is approved:**

- record the exact repository tree, dependency lock digest, current test
  result, and V0.4 pack digest;
- introduce no strategy or external data;
- keep live disabled and no credential paths present;
- create a migration branch/commit only when repository permissions and human
  review permit it.

**Exit evidence:** baseline tests pass; no legacy status changes; current
decision/reproducibility tests remain green.

**Risk:** low, but do not rewrite V0.3 documentation as if V0.4 were already
implemented. The current user instruction requires that documentation update
to remain deferred during this task.

### Stage 1 — Policy and deterministic configuration contracts

**Gap IDs:** GOV-01–04, OPS-01, RSK-01–02.

**Smallest change:** add versioned, parsed policy objects for:

- objective/selection behaviour;
- normal and exceptional odds profiles;
- day-of-week search aims as telemetry targets only;
- unit fraction, tiers, max single stake, open-liability and correlation
  parameters;
- operating mode and live-disabled defaults;
- exact reason-taxonomy version.

Retain the old `max_daily_stake` field only as a migration/deprecation field;
do not use it as a V0.4 hard daily turnover limit. Replace the opaque
`odds_profile` string with a versioned policy hash while keeping deterministic
config digesting.

**Dependencies:** none beyond the frozen baseline.

**Tests:** boundary values, decimal serialization, config digest stability,
old-config rejection or explicit migration, day-target non-quota behaviour,
normal/exceptional odds classification, and no accidental live enablement.

**Approval:** human approval required for objective/ranking semantics, risk
percentages, tier rules, and any config default that could change behaviour.

### Stage 2 — Bitemporal PIT and source capability boundary

**Gap IDs:** EVD-02–04, DATA-02, OPS-02.

**Smallest change:** preserve current UTC and ready-by checks, then add:

- immutable source capability/readiness records;
- publication, retrieval, ready, valid interval, and supersession fields;
- a controlled `as_of_query`/`feature_view` interface;
- explicit unknown/late/revised-source rejection;
- source cost, entitlement, quota, revision, coverage, schema, and operational
  status fields;
- capability checks that fail closed rather than infer support from an API
  response.

Do not add a live source adapter. A synthetic in-memory/file implementation is
enough to test the boundary.

**Dependencies:** Stage 1 policy versioning; current `evidence.py`,
`provenance.py`, `time.py`, and `labels.py` remain the low-level base.

**Tests:** all timestamp orderings; late-arriving but event-time-old records;
valid interval selection; superseded record selection; unknown capability;
requested cutoff exactly on `ready_at`; rejected future and retrospective
revision; replay from immutable source records.

**Approval:** human approval required for the PIT interpretation and source
availability classes. No provider entitlement is assumed.

**Risk:** critical. A permissive fallback here would invalidate every later
calibration or profitability claim.

### Stage 3 — Frozen evidence packs and reproducibility identity

**Gap IDs:** EVD-05–08, DATA-03, OPS-01.

**Smallest change:** introduce immutable, append-only records for:

- evidence-pack membership and manifest hash;
- frozen time and evidence cutoff;
- source artifact hashes, extractor version, prompt/schema hash,
  contradiction links, and freshness/expiry state;
- feature, model, calibration, strategy, gate, and config hashes;
- candidate decision hash;
- complete run/reproducibility manifest including code/dependency/runtime
  hashes, timezone, mode, command, and seeds.

Extend `CandidateBet` only where required to carry these identity references;
do not create a second mutable candidate representation. A material source
correction creates a new pack and candidate version and marks the old version
invalid for future execution.

**Dependencies:** Stage 2 controlled PIT and source metadata.

**Tests:** same frozen inputs → same pack and decision hashes; any material
input change → different hash; pack mutation rejected; missing hash fails
closed; corrected evidence never rewrites old records; complete replay
reconstructs the candidate decision.

**Approval:** human approval required before the hash input contract is frozen.

**Risk:** critical. The decision hash becomes the identity referenced by risk,
orders, evaluation, and audit; changing it later requires a versioned schema.

### Stage 4 — Canonical candidate, capability, coverage, and gate contracts

**Gap IDs:** DATA-01–04, SEL-01–02, GOV-04.

**Smallest change:** extend existing dataclasses and ledgers, rather than
rewriting them, to include:

- event/meeting/competition/participant dependency identifiers;
- market family, settlement, liquidity, and capability references;
- calibration/support/uncertainty/evidence/contradiction/price/odds/
  execution/risk/correlation status fields;
- candidate run and full-universe retention records;
- near-miss and PASS records;
- versioned exact V0.4 reason codes;
- a pure ordered gate engine that treats missing/unknown as PASS/block.

`CoverageLedger` and `ExclusionLedger` should remain append-only. A gate must
not silently convert an absent capability into `True`.

**Dependencies:** Stage 3 hashes and frozen pack; Stage 1 odds/price policy.

**Tests:** schema completeness; unknown capability; exact code serialization;
gate order; expiry; stale/contradictory evidence; all candidate states retained;
run replay; one failed gate does not become QUALIFY through a later override.

**Approval:** human review of reason taxonomy and qualification order.

### Stage 5 — V0.4 price sanity and deterministic portfolio interfaces

**Gap IDs:** GOV-01–04, SEL-03–04, RSK-01–03.

**Smallest change:** implement pure arithmetic/policy interfaces for:

- commission-aware break-even probability;
- `price_sanity_margin = model_probability - break_even`;
- normal non-negative pass, near-fair `[-0.02, 0)` only under strong
  conditions, and exceptional-zone non-negative requirement;
- strategy-defined strength tiers from auditable fields;
- deterministic ordering by tier, comparable support/price region,
  conservative probability/uncertainty, diversification, and stable ID;
- unit conversion from bankroll at 2.5% with a 3u single-bet ceiling.

Do not add any model or strategy. Use fixtures only to test policy arithmetic.
The ordering must remove the current raw-probability conflict without claiming
that price margin is the optimization objective.

**Dependencies:** Stages 1, 3, and 4; dependency/correlation IDs before
portfolio construction.

**Tests:** exact odds boundaries; commission variants; near-fair tolerance;
exceptional negative margin; no opaque score; cross-region raw-probability
ordering; tier determinism; 1u/3u and bankroll rounding; stable tie breaks.

**Approval:** human approval required for policy parameters and any change that
could increase selection volume or stake.

### Stage 6 — Selection-aware and protected evaluation

**Gap IDs:** STAT-01–05.

**Smallest change:** preserve the local Brier skeleton as a test double and
add interfaces for:

- full slate/candidate-universe retention;
- preregistered selection-policy and portfolio artifacts;
- all/qualified/selected calibration reports;
- odds/support/chronological regions;
- dependence-aware event/day/meeting blocks;
- PASS threshold-neighbourhood, matched, and gate-ablation requests;
- campaign/family budgets and non-refundable attempt receipts;
- evaluator-version freeze, small-cell suppression, controlled summaries, and
  append-only request audit.

Only after the interface is proven should the protected evaluator move to a
separate process/service. The research role must never receive labels, raw
stack traces, or evaluator write authority.

**Dependencies:** Stages 3–5, especially decision hashes, full retention, and
dependence identifiers.

**Tests:** crashed/timeout requests consume attempts; repeated attempts do not
refund; tiny cells suppress; labels absent from callback and logs; evaluator
mutation denied; all candidates included; selected-set calibration differs
from all-set calibration when fixtures require it; PASS ablation is
pre-registered and bounded.

**Approval:** human approval required for protected campaign budgets,
evaluation metrics, and boundary implementation.

**Risk:** critical. No strategy search or protected outcome access should begin
until these controls are independently reviewed.

### Stage 7 — Risk, exposure, correlation, and approval consumption

**Gap IDs:** RSK-01–04.

**Smallest change:** add a pure risk engine plus append-only risk records for:

- bankroll snapshot and weekly/drawdown rebase decisions;
- unit tier and stake;
- matched, partial, unmatched, pending, and UNKNOWN exposure;
- event/meeting/competition/participant/shared-evidence dependency groups;
- correlated cluster aggregation at a versioned 10–12.5% initial target;
- approximately 60% simultaneous open-liability hard cap;
- single-use risk approval keyed by candidate decision hash;
- duplicate/kill/unknown blocks.

No order placement is added here. Risk calculations must be usable in offline
and paper fixtures first.

**Dependencies:** Stages 1, 3–5; order state vocabulary may be defined here
and implemented in Stage 8.

**Tests:** exact Decimal exposure; pending/unknown included; concurrent
approval consumption; duplicate decision hash; cluster cap; 60% cap; no
daily turnover cap; weekly upward and drawdown-triggered downward rebase;
fail-closed missing portfolio state.

**Approval:** human approval required for risk policy values, correlation
interpretation, and bankroll rebasing.

### Stage 8 — Paper execution boundary and reconciliation state machine

**Gap IDs:** EXE-01–04.

**Smallest change:** define a provider-neutral interface and a deterministic
paper/mock adapter with:

- final critical-evidence refresh result;
- strategy/expiry/market/price/liquidity/risk/kill/duplicate checks;
- order intent tied to one candidate decision hash and one idempotency key;
- all V0.4 order states;
- timeout → `UNKNOWN` + `RECONCILIATION_REQUIRED`;
- no retry until venue/account state is reconciled;
- mode and kill-switch authority records.

No credentials, network calls, browser automation, or real-money adapter is
permitted in this stage.

**Dependencies:** Stages 3, 4, 7; settlement ledger follows the fill schema.

**Tests:** every legal/illegal state transition; repeated submit; restart;
timeout; partial fill; cancellation; stale critical evidence; changed odds;
unknown exposure; mode authorization; kill switch blocking new but not
rewriting existing orders.

**Approval:** human approval required for mode authority and order semantics.

### Stage 9 — Settlement ledger and accounting source of truth

**Gap IDs:** SET-01–02.

**Smallest change:** add an append-only ledger for order intents, fills,
cancellations, settlement events, corrections, fees, and reconciliation. Keep
the current Decimal arithmetic as the calculation kernel. Reports must be
derived from ledger events only.

**Dependencies:** Stage 8 fill/order schemas plus a named market-family
settlement rule. Generic primitives can be tested before a venue is selected;
venue-specific rules remain deferred.

**Tests:** matched fragments; partial/unmatched cancellation; void/non-runner;
back/lay commission; dead heat; corrections/resettlements; ledger conservation;
reconciliation mismatch; candidate assumed fill cannot create P/L.

**Approval:** human review before declaring any market family paper/live
eligible.

### Stage 10 — Quota, source-budget, and runtime ports

**Gap IDs:** OPS-02–05.

**Smallest change:** add provider-neutral interfaces for:

- billable-call accounting and monthly/daily/reserve limits;
- batching, cache hits, targeted refresh, and execution windows;
- quota exhaustion → no new odds-dependent decision;
- scheduled/stateless job execution;
- durable registry/object-store/cache/dashboard/monitoring ports;
- cost ledger and budget alert/fail-closed policy.

The OddsPapi YAML remains a planning assumption until official provider terms
are reverified. Do not create an account, call an endpoint, rotate keys, or
select a cloud vendor as part of the migration.

**Dependencies:** source capability registry and paper lifecycle; no live
adapter dependency.

**Tests:** <=7 daily, <=220 monthly, >=30 reserve boundaries; batched request
accounting; cache no-call; exhausted quota; provider error with only verified
fresh cache allowed; no quota circumvention; deterministic job retry.

**Approval:** human approval required for provider terms, budget exceptions,
and cloud deployment.

### Stage 11 — Sport and venue adapters, then live-readiness gates

**Status:** not part of the current V0.3→V0.4 foundation migration.

After Stages 1–10 pass review, a separate work item may define a read-only
sport adapter. Each adapter must supply identity, PIT, evidence, model support,
settlement, liquidity, and capability contracts before candidate generation.
Hoofs/Race Shape/Betfair material remains untrusted until semantics and timing
are verified. A venue adapter must be official/supported and fit the cost and
credential constraints; unsupported browser automation is out of scope.

Real-money activation requires a separate human-approved readiness review,
including protected/prospective evidence, paper reconciliation, venue terms,
credential isolation, risk policy, and an explicit live authorization artifact.

## 4. Migration risk register

| Risk | Why it matters | Control |
|---|---|---|
| PIT boundary accepts late data | Creates invisible future leakage. | Controlled query only; adversarial timestamp/revision tests; fail closed on UNKNOWN. |
| Evidence pack is mutable | Historical decisions cannot be reconstructed. | Content hashes, freeze state, append-only corrections, replay tests. |
| Candidate hash omits a material input | Two different decisions appear identical. | Versioned hash input manifest and changed-input tests. |
| Raw probability returns as the ranking objective | Recreates favourite bias and contradicts V0.4. | Tier/region/dependence ordering contract; regression fixture with mixed odds. |
| Daily target becomes a quota | Weak bets are manufactured. | Target telemetry only; explicit lower/upper target tests; PASS allowed at zero. |
| PASS records are discarded | Gate value and selection bias cannot be measured. | Full candidate-run retention and append-only PASS records. |
| Protected evaluator leaks through errors or retries | Holdout evidence is spent or exposed. | Trusted boundary, suppression, monotonic budgets, controlled errors/logs. |
| Pending/UNKNOWN exposure is omitted | Risk caps are bypassed during broker ambiguity. | Explicit exposure states; UNKNOWN blocks affected continuation. |
| Duplicate retry after timeout | Real-money duplicate order risk. | One idempotency key; UNKNOWN/reconciliation before retry. |
| Ledger trusts candidate assumptions | Fake P/L and false profitability. | Fill/settlement ledger as sole report source; conservation tests. |
| Quota pressure forces bets | Provider limits become a selection bias. | Cache/batch/quota ledger; exhaustion blocks odds-dependent decisions. |
| Old V0.3 config is silently reinterpreted | Policy drift is unauditable. | Versioned migration, explicit deprecation, config hash, approval. |
| Legacy assumptions leak into Genesis | Sport/source timing or model semantics become unverified facts. | Read-only inventory; deliberate adapter import only after V0.4 contracts. |
| Documentation overstates completion | Reviewers may approve an unimplemented boundary. | Evidence links, test results, and checklist changes only after actual implementation. |

## 5. Definition of done for the foundation migration

The V0.3→V0.4 foundation migration may be considered complete only when all
of the following are evidenced in code and tests:

- V0.4 policy/config hashes are deterministic and live remains disabled;
- source capability and controlled PIT access reject future, late, unknown, or
  superseded decision inputs;
- evidence packs and candidate decision hashes are immutable and replayable;
- candidate, capability, coverage, gate, and PASS records are complete;
- odds/price/tier/ranking policy is explicit and not an opaque score;
- all candidates are retained and selected-set/PASS evaluation is bounded;
- protected evaluation has a trusted boundary and non-refundable accounting;
- unit/liability/correlation/single-use risk contracts work in offline/paper
  mode;
- paper order state, idempotency, UNKNOWN reconciliation, and critical refresh
  are tested;
- settlement P/L is ledger-derived and adversarially tested;
- quota/runtime ports fail closed and do not require a provider or credential;
- current V0.3 tests remain green and new adversarial tests are recorded;
- no strategy, sport model, network integration, credential, or live order was
  added merely to demonstrate the architecture.

This definition of done remains the full foundation acceptance gate. The
implementation ledger below records which parts are complete and which remain
partial or deliberately deferred.

## 6. First safe implementation slice after approval

The first coherent slice—Stages 1–3—has been implemented: policy/config
versioning, controlled synthetic PIT/source records, and frozen evidence-pack
plus decision-hash contracts. Stages 4–5 were also implemented to make those
identities useful to gates and deterministic policy ordering. Stages 6–10 now
have offline foundation interfaces and tests, with the partial boundaries below.

## 7. Implementation ledger

| Stage | Status | Implemented evidence | Remaining boundary |
|---|---|---|---|
| 0. Baseline freeze | **COMPLETE** | Existing V0.3 suite retained; legacy repositories unchanged. | No repository commit was created because the workspace began without a committed baseline and the host's Git index permissions remain restricted. |
| 1. Policy/config | **COMPLETE** | `policy.py`, extended config, non-quota daily aims, provisional price tolerance, deterministic tests. | Empirical validation and strategy cards are intentionally absent. |
| 2. PIT/source capability | **COMPLETE as synthetic interface** | `pit.py`, market/source capability registries, fail-closed tests. | No real source is active; provider terms remain unverified. |
| 3. Evidence identity | **COMPLETE as foundation interface** | `evidence_pack.py`, `decision.py`, candidate identity fields, immutable/replay tests. | Automatic integration of all source-store supersession metadata remains future work. |
| 4. Canonical/gates/retention | **COMPLETE as foundation interface** | extended canonical records, V0.4 reasons, `qualify_v04`, candidate-run store, coverage telemetry. | No active sport candidate generator exists. |
| 5. Price/portfolio policy | **COMPLETE as foundation interface** | break-even/price-sanity, tier/region ordering, unit policy and tests. | No strategy-defined tier card or empirical policy validation. |
| 6. Selection/protected evaluation | **PARTIAL** | aggregate selected-set/PASS evaluation interfaces and protected attempt/suppression boundary. | Separate trusted process/service and full campaign governance are required before protected campaigns. |
| 7. Risk | **PARTIAL** | units, reservations, liability/correlation/UNKNOWN checks, rebase, single-use approvals, audit log. | Durable exposure lifecycle and restart rehydration are not implemented. |
| 8. Paper execution | **PARTIAL** | provider-neutral paper state machine, idempotency, recertification, mode authority, kill switch. | Persistent order rehydration and venue reconciliation are not implemented. |
| 9. Settlement ledger | **COMPLETE as generic foundation** | append-only fills/settlements/corrections and deterministic P/L tests. | Market/venue-specific settlement rules and activation remain deferred. |
| 10. Quota/runtime ports | **PARTIAL** | quota/reserve/cache and cost/scheduler ports with deterministic tests. | No provider/cloud deployment, monitoring, or external call. |
| 11. Sport/live | **NOT STARTED / NOT YET APPLICABLE** | Deliberately no adapter, strategy, credential, or live path. | Requires separate research, provider verification, paper evidence, and human approval. |

The authoritative current status is also recorded in `PROJECT_STATE.md`,
`TEST_EVIDENCE.md`, and `HANDOFF.md`.
