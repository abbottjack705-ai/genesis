# Project Genesis architecture

## Current V0.4 foundation flow

```text
source capability + PIT records
              |
              v
immutable evidence objects
              |
              v
frozen evidence pack + reproducibility manifest
              |
              v
canonical candidate + decision hash
              |
              +--> append-only candidate-run / coverage retention
              |
              v
ordered fail-closed V0.4 gates
              |
              +--> PASS reason / selection evaluation aggregates
              |
              v
strategy-tier portfolio ordering
              |
              v
risk reservation + correlation / liability checks
              |
              v
paper order state machine + UNKNOWN reconciliation
              |
              v
fill / settlement ledger
```

The current repository stops at offline and paper contracts. There is no
network call, live credential, venue adapter, browser automation, or real-
money order path.

## Trust boundaries

```text
Research / extraction
  may produce structured evidence and proposals
  may not set probability, stake, risk, labels, or orders
              |
              v
Evidence / PIT boundary
  owns immutable artifacts, source capabilities, as-of queries, and packs
              |
              v
Deterministic decision boundary
  owns canonical candidates, hashes, gates, PASS, and portfolio ordering
              |
              v
Risk boundary
  owns units, exposure, correlation, kill checks, and single-use approvals
              |
              v
Paper execution boundary
  owns order states, idempotency, and reconciliation contracts
              |
              v
Settlement boundary
  owns fill/settlement/correction ledger events and P/L arithmetic
```

Protected evaluation remains an in-process tested skeleton plus a
fail-closed campaign/attempt interface. It must become a separately trusted
process/service before protected campaigns. Future labels are stored and
passed separately from decision frames.

## Layout

- `src/genesis/repro.py`: canonical JSON, SHA-256, atomic immutable writes.
- `src/genesis/evidence.py`: content-addressed evidence objects and existing
  evidence manifest.
- `src/genesis/evidence_pack.py`: frozen evidence packs and pack manifests.
- `src/genesis/provenance.py`, `time.py`, and `pit.py`: source contracts,
  capability readiness, bitemporal records, and controlled PIT queries.
- `src/genesis/canonical.py`: participant, event, market, research-evidence,
  and extended candidate schemas.
- `src/genesis/decision.py`: candidate decision hashes and reproducibility
  manifests.
- `src/genesis/capabilities.py`: fail-closed market capability registry.
- `src/genesis/labels.py`: separate decision-time facts and future labels.
- `src/genesis/registry.py`: dataset, experiment, attempt, and strategy
  registries with backward-compatible V0.4 experiment fields.
- `src/genesis/candidate_runs.py`, `coverage.py`: full-run retention,
  non-quota search telemetry, coverage, and exclusions.
- `src/genesis/selection.py`, `reasons.py`, `policy.py`: V0.4 policy,
  price-sanity, exact PASS taxonomy, gates, and tier/region ordering.
- `src/genesis/selection_evaluation.py`, `evaluation.py`, `protected.py`:
  selected-set aggregates, protected evaluator skeleton, campaign budgets,
  suppression, and non-refundable attempts.
- `src/genesis/risk.py`: bankroll units, reservations, exposure states,
  correlation/liability limits, rebase decisions, and risk audit.
- `src/genesis/execution.py`: paper-only order state machine, recertification,
  idempotency, mode authority, and kill switch.
- `src/genesis/accounting.py`, `ledger.py`: deterministic payoff primitives
  and append-only fill/settlement/correction ledger.
- `src/genesis/quota.py`, `runtime.py`: offline quota/cache contracts and
  provider-neutral scheduler/cost/runtime ports.
- `src/genesis/config.py`, `config/defaults.json`, `requirements.lock`:
  dependency-pinned, live-disabled configuration.
- `src/genesis/logging.py`: structured redacted JSONL audit events.

## Persistence and identity rules

Evidence objects, evidence packs, decision inputs, registries, candidate runs,
risk events, order transitions, quota reservations, and ledger events are
content-addressed or append-only. Corrections create new records and reference
prior records; they do not rewrite history. V0.4 decision, risk, and order
records are tied to a candidate decision hash and deterministic idempotency
key.

## Deliberate non-inheritance

The MLB legacy engine and `m9_repair` remain outside this repository. Their
chronology and validation ideas are represented only through new generic
contracts and tests. No legacy model assumptions, market definitions, source
timestamps, or optimizer settings are imported.

## Deferred architecture

The future runtime may add scheduled cloud jobs, durable storage, caches,
monitoring, source adapters, sport models, and official venue adapters behind
these interfaces. Provider selection, credentials, live authority, and
market-specific settlement rules require separate verification and approval.
