# Project Genesis architecture

## Audit disposition (2026-09-22)

Astra's independent audit of R10 commit `166f923` returned **HOLD / NOT
APPROVED**. S1 locally closed A1/A2; S2a locally closed A3 strict active-state
replay. A7 and A4–A8 remain open; this diagram is a
foundation map, not an adapter, shadow-research or live-money GO.

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
inside that transaction. This does not repair A7's earlier risk-admission
read-before-transaction window. S2a now rejects incompatible active risk,
bankroll and safety rows on startup and transactional replay. Recovery must not
silently heal, truncate, choose a branch, or infer missing identity.

## Trust boundaries

```text
Label-loading caller / research callback (current local launcher)
  can retain raw labels in its address space: A8 NOT CLOSED
                 |
                 | bounded canonical JSON IPC
                 v
Spawned trusted evaluator process (checkpoint-test mode only)
  owns labels and fixed campaign/frame registration
  reserves a durable non-refundable attempt first
  executes no arbitrary research callback
  returns only a certificate or fixed generic error
```

Real protected activation is disabled pending independent review. The legacy
in-process callback path is explicitly named unsafe, requires a synthetic
test-only opt-in, and rejects registered V2 campaigns.

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
- Astra A4/A5 show that material decision outputs and exact required PIT inputs
  are not yet bound to that identity; new qualification authority remains HOLD.
- Tier is strict and strategy-approved. Invalid or missing tier never degrades to
  a usable default.
- Across equal-tier incomparable groups there is no quality comparison. A stable
  identity-driven round-robin provides deterministic diversification; group or
  market labels carry no quality meaning.

## Restart semantics

- Risk replays bankroll, safety, approvals, consumption and reservations.
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
  strategies, lifecycle timeline and `StrategyDecisionContract`.
- `provenance.py`, `pit.py`, `capabilities.py`: source contracts, versioned
  source/market capability, bitemporal records and mandatory as-of reads.
- `evidence.py`, `evidence_pack.py`, `canonical.py`, `decision.py`: content,
  observations, structured evidence, frozen packs and candidate identity.
- `selection.py`, `policy.py`: authoritative qualification, immutable
  qualification records, strict tiers, price gates and unbiased ranking.
- `risk.py`: durable bankroll/safety/exposure ownership, exact derived risk and
  approvals.
- `execution.py`: provider-neutral PAPER order identity, binding, recertification,
  mandatory S1 pre-pending and pre-sent checks, state replay, mode and kill control.
- `ledger.py`, `accounting.py`: authoritative fills, settlement lineages and
  deterministic Decimal payoff primitives.
- `quota.py`, `config/oddspapi_quota_policy_v2.json`: digest-pinned approved A
  policy, test-only B and atomic reserve authority; A6 cache proof remains open.
- `protected.py`, `evaluation.py`: sealed frames, frozen predictions, durable
  attempt accounting, trusted evaluator IPC and explicit legacy test harness.
- `candidate_runs.py`, `coverage.py`, `selection_evaluation.py`: complete
  candidate retention, non-quota search telemetry and aggregate evaluation.

## Legacy and deferred boundaries

The caller-facts `qualify_v04` function and in-process protected harness remain
only for deterministic legacy/synthetic audit replay. No production module imports
or calls them. Pre-audit artifacts may be read only through explicit migrations;
they are never silently promoted to post-audit authority.

Future adapters, providers, sport models, strategy cards, real protected
campaigns, venue reconciliation, cloud services and live activation require
separate authority, implementation, tests and approval. Nothing in this
remediation checkpoint authorizes that work.
