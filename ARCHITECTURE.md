# Project Genesis architecture

## Audit disposition (2026-09-25)

Astra's independent audit of R10 commit `166f923` returned **HOLD / NOT
APPROVED**. S1 locally closed A1/A2; S2a/S2b locally closed A3/A7; S3a
locally closed A5's exact-input correspondence. S3b locally binds A4's trusted
decision outputs to candidate-v3 and downstream new-risk/order lineage.
S4 locally closes A6's cache-authority defect. S5 locally closes A8's
process/address-space defect under approved ADR-0003 v1. The independent
post-S5 hostile audit of commit `27dd525` then returned **HOLD / NOT APPROVED**
with B1-B8. T1 locally repairs B1, B2, B3 and B7. T2 locally repairs B6's
circular approval construction without changing the approved binding preimage.
B4, B5 and B8 remain open, and T1/T2 still require hostile review. This diagram is a
foundation map, not an adapter, shadow-research, protected-campaign or
live-money GO.

## Remediated V0.4 foundation flow

```text
append-only SourceContract + source/market capability timelines
                              |
                              v
content object -> immutable observations -> controlled PIT read
                              |
                              v
structured ResearchEvidence -> frozen evidence pack
                              |
                              v
StrategyDecisionContract + canonical candidate identity
                              |
                              v
QualificationAuthority -> durable QualificationRecord or PASS
                              |
                              v
explicit comparable-group ranking / deterministic diversification
                              |
                              v
durable bankroll + risk derivation -> single-use RiskApproval
                              |
                              v
candidate-unique PAPER intent -> exact binding -> state/reconciliation
                              |
                              v
fill -> one-head settlement/correction/void lineage -> effective P/L
```

The repository stops at generic offline/PAPER contracts. It has no network
client, source or sport adapter, venue integration, browser automation,
credential, cloud deployment, dashboard, or real-money order path.

## Authority and persistence boundary

All safety-critical histories use `AppendOnlyJsonl`. Before a mutation, the
complete JSONL chain is verified inside a SQLite `BEGIN IMMEDIATE` critical
section; that log's precondition and append are one cross-process operation.
The canonical JSONL row is flushed and fsynced. SQLite stores only a coordination
generation and is never business truth.

S1 submission holds the risk, bankroll, safety, market and critical-refresh
coordinator locks through its order append and recertifies from those owners
inside that transaction. S2a rejects incompatible active risk, bankroll and
safety rows on startup and transactional replay. S2b risk admission holds the
risk, bankroll, safety and qualification-log coordinator locks while it reads
their current heads, derives stake/liability, checks open exposure/correlation
and fsyncs a new approval. Bankroll/safety writers are ordered against that
admission; a pre-lock change is observed and a later change is ordered after
the approval. S3a/S3b separately fence exact PIT/decision-output identity.
S4 resolves cache references through immutable bytes and an append-only
provider/policy/request/freshness/invalidation authority under the quota
transaction fence. S5 launches a separately isolated research process before
trusted labels are materialized and before the evaluator channel is created.
T1 derives dependence only from the bound decision output, recalculates current
portfolio capacity from authoritative heads, fences durable strategy and PAPER
mode heads through each new-risk/pending/sent append, and permits reservation
release only from a durable exact reconciliation proof. The T1 legacy-v2 path
is a separate audit-settlement-only schema: it can finish an already existing
matched PAPER order, but can never authorize qualification, new risk, pending
or send.
T2 adds an operator-owned append-only approval ledger. A PAPER-only v2 approval
reference is reserved before the unchanged binding-v1 hash is computed; a
subsequent exact human grant binds that stable reference to the final binding
hash. Qualification, risk, intent, pending and send fence the approval ledger
head with their durable append. Historical raw-64-hex v1 approval-note meaning
and all binding/candidate/output hash algorithms are unchanged.
Recovery must not silently heal, truncate, choose a branch, or infer missing
identity.

## Trust boundaries

```text
Label-owning trusted launcher
  retains labels; never executes an accepted research program
                 |
                 | label-free sealed frames + exact ResearchProgramRef
                 v
Isolated research process (distinct PID/address space)
  starts before label materialization and evaluator-channel creation
  receives no raw labels, label path, label store or evaluator endpoint
  imports the exact hashed top-level stateless program
  returns only an exact frozen-prediction artifact or generic failure
                 |
                 | prediction artifact identity only
                 v
Spawned trusted evaluator process (distinct PID; checkpoint-test mode only)
  owns labels and fixed campaign/frame registration
  reserves a durable non-refundable attempt first
  executes no arbitrary research callback
  returns only a certificate or fixed generic error
```

Real protected activation is disabled pending independent review. The legacy
in-process callback path is explicitly named unsafe, requires a synthetic
test-only opt-in, and rejects registered V2 campaigns.

A quota cache hit resolves a content-addressed `VerifiedCacheEntry` from the
configured cache authority. Its actual bytes, provider, active quota-policy
digest, exact provider-request hash, capture/expiry and invalidation history
must match at decision time. The cache authority log is fenced through the
durable quota decision; a caller `verified` flag has no authority.

```text
QualificationAuthority
  resolves exact strategy contract, lifecycle-at-decision, market capability,
  evidence/PIT identity, policy, risk view and execution view
  persists one immutable qualification record only after all gates pass
                 |
                 v
RiskEngine
  owns current bankroll, hard unit law, derived stake/liability, exposures,
  safety state, approval issuance and single-use consumption
                 |
                 v
PaperExecutionAdapter
  owns candidate uniqueness, exact approval binding, current market/refresh
  recertification, state history and restart reconciliation
                 |
                 v
SettlementLedger
  owns fill identity, one current settlement head and economic P/L replay
```

## Identity and ranking rules

- A raw object's intrinsic identity is hash plus byte length. Content type and
  retrieval/source facts belong to immutable observation identity.
- A post-audit provenance reference contains the exact observation ID.
- Every material `ResearchEvidence` field contributes to its digest; frozen pack
  and candidate identity consequently change when material evidence changes.
- `StrategyDecisionContract` pins every non-candidate decision input, including
  exact odds profile, adapter version, market capability and comparability group.
- The post-audit qualifier recomputes candidate identity from authorities.
- S3a resolves the pack's exact content-addressed input manifest, source
  binding/capability head, observation/raw bytes, structured evidence and PIT
  row/head at the frozen cutoff. The PIT and source heads are fenced through
  qualification append; a same-event substitute cannot certify the pack.
- S3b leaves every historical candidate-v1/v2 hash and record untouched but
  makes them audit-only for new qualification, risk, pending and sent events.
  Candidate-v3 binds the exact manifest, pack, contract and content-addressed
  DecisionOutput-v1. Qualification resolves an active, unambiguous approved
  rule binding and reproduces every output through its pinned resolver;
  copied candidate fields cannot authorize a changed probability, uncertainty,
  price, dependence, tier or expiry. Risk and orders verify the v3
  qualification/output lineage; risk side and requested odds must match the
  trusted side and existing output band. Revocation blocks new risk and sends.
  No strategy-specific model, tier formula or expiry rule is approved here:
  operational qualification remains fail-closed without separate approval.
- T2 resolves B6 with the disjoint
  `strategy-output-approval-v2:<reservation-record-hash>` namespace. Reservation,
  exact grant and revocation are closed append-only events; missing, wrong,
  future-dated, conflicting, tampered or revoked authority fails closed. The
  namespace is plumbing only: it does not approve any actual model, calibration,
  strategy tier formula/cutoff or expiry duration.
- T1 makes `DecisionOutput-v1.correlation_cluster_ids` authoritative for risk.
  A caller's non-empty copy is comparison-only and must match; omission cannot
  erase dependence. The canonical output membership is persisted on the risk
  approval/reservation and replay must agree with the bound output.
- Tier is strict and strategy-approved. Invalid or missing tier never degrades to
  a usable default.
- Across equal-tier incomparable groups there is no quality comparison. A stable
  identity-driven round-robin provides deterministic diversification; group or
  market labels carry no quality meaning.

## Restart semantics

- Risk replays bankroll, safety, approvals, consumption and reservations.
- A consumed reservation remains fully charged through pending, match, partial
  fill, UNKNOWN and reconciliation. It reaches `SETTLED` or `VOID` only through
  an exact, current, durable release proof fenced with order, fill, settlement
  and risk heads. Bare terminal labels do not release capacity. A later fill or
  incompatible correction invalidates a prior proof conservatively and restores
  UNKNOWN/full charge.
- Existing historical exposure remains factual even when it exceeds a current
  limit; hold-to-settlement is preserved while every unsafe new action is
  denied. Capacity checks count the order's own reservation exactly once.
- One candidate decision hash has one order-intent lineage across terminal state,
  key changes, processes and restart.
- `SUBMISSION_PENDING`, `SUBMISSION_SENT`, `UNKNOWN`, and
  `RECONCILIATION_REQUIRED` restart as reconciliation-blocking; there is no blind
  resend.
- A crash after approval consumption but before order binding is detected as an
  orphan consumption and blocks reconciliation.
- Settlement replays exact current heads and checks that total event deltas equal
  current effective fill outcomes.
- Quota and protected-attempt ledgers replay their budgets and authorizations;
  process failure never refunds protected attempts.

## Module map

- `registry.py`: append transaction coordinator, datasets, experiments,
  strategies, durable lifecycle heads and `StrategyDecisionContract`.
- `provenance.py`, `pit.py`, `capabilities.py`: source contracts, versioned
  source/market capability, bitemporal records and mandatory as-of reads.
- `evidence.py`, `evidence_pack.py`, `canonical.py`, `decision.py`: content,
  observations, structured evidence, frozen packs and candidate identity.
- `selection.py`, `policy.py`: authoritative qualification, immutable
  qualification records, strict tiers, price gates and unbiased ranking.
- `risk.py`: durable bankroll/safety/exposure ownership, output-derived
  dependence, current portfolio admission, exact derived risk, approvals and
  proof-bearing reservation release.
- `execution.py`: provider-neutral PAPER order identity, binding, recertification,
  mandatory pre-pending/pre-sent checks, durable strategy/mode fencing, state
  replay and kill control.
- `release_proof.py`: exact PAPER order/fill/settlement proof ownership,
  including the separate legacy-v2 audit-settlement-only proof schema.
- `ledger.py`, `accounting.py`: authoritative fills, settlement lineages and
  deterministic Decimal payoff primitives.
- `quota.py`, `config/oddspapi_quota_policy_v2.json`: digest-pinned approved A
  policy, test-only B, atomic reserve authority and immutable exact cache proof.
- `protected.py`, `protected_research_worker.py`, `evaluation.py`: sealed
  frames, exact hashed research-program references, isolated research execution,
  frozen predictions, durable attempt accounting, trusted evaluator IPC and an
  explicit legacy test harness.
- `candidate_runs.py`, `coverage.py`, `selection_evaluation.py`: complete
  candidate retention, non-quota search telemetry and aggregate evaluation.

## Legacy and deferred boundaries

The caller-facts `qualify_v04` function and in-process protected harness remain
only for deterministic legacy/synthetic audit replay. No production module imports
or calls them. Pre-audit artifacts may be read only through explicit migrations;
they are never silently promoted to post-audit authority.

Historical v2 candidate and qualification identities remain unchanged. An
already consumed and matched v2 PAPER order may release only through
`offline-paper-legacy-release-proof-v1`, which binds the exact durable v2
qualification row and complete current terminal evidence. It has no fabricated
decision-output identity and is deliberately unusable for any new action.

Future adapters, providers, sport models, strategy cards, real protected
campaigns, venue reconciliation, cloud services and live activation require
separate authority, implementation, tests and approval. Nothing in this
remediation checkpoint authorizes that work.
