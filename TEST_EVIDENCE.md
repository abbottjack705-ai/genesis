# Test evidence

## Current deterministic result

Command:

```text
python -m unittest discover -s tests -t . -v
```

Result on 2026-09-18: **28 tests passed, 0 failed, 0 errored**.

Compilation command:

```text
python -m compileall -q src tests
```

Result: **passed**.

The test harness uses the repository-local `work/test_runtime/` scratch area
because this Windows environment denies the Python private temp directory.
No test accesses a network, bookmaker, live credential, protected external
dataset, or historical outcome source.

## V0.3 contracts retained and passing

- content-addressed evidence is idempotent and conflicting metadata is not
  silently overwritten;
- evidence manifest tampering is detected;
- future-ready inputs and future-label fields fail closed;
- protected evaluation returns a certificate without passing labels to the
  strategy callback;
- Decimal odds, implied probability, back/lay P&L, commission, voids,
  non-runners, and dead-heat arithmetic are deterministic;
- experiment attempts consume a finite budget and qualification is PASS-first;
- structured logging redacts credential-like fields;
- canonical serialization and tree hashing are reproducible.

## V0.4 foundation contracts covered

- policy versioning, unit tiers, daily search aims as non-quota telemetry, and
  provisional near-fair price-sanity handling;
- source capability readiness, future `ready_at` rejection, and controlled PIT
  access;
- frozen evidence-pack hash identity and manifest replay;
- deterministic decision-hash changes when a material input changes;
- expanded candidate-run retention and coverage summary semantics;
- exact V0.4 PASS taxonomy, UNKNOWN-as-PASS behaviour, and tier/region-aware
  ordering rather than whole-slate raw-probability ranking;
- all/qualified/selected aggregate evaluation, dependence-group counts, and
  PASS-reason aggregation;
- protected small-cell suppression, failed-attempt consumption, and exhausted
  campaign accounting;
- risk unit calculation, cluster/liability limits, single-use approvals,
  unknown-exposure blocking, rebase rules, and append-only risk audit;
- paper idempotency, state transitions, timeout → UNKNOWN → reconciliation,
  critical-evidence invalidation, and recertification;
- fill/settlement ledger P/L, correction deltas, and ledger hash-chain replay;
- quota exhaustion, reserve protection, verified cache hits, and runtime
  budget primitives.

## Deliberate non-coverage

The tests do not prove profitable betting, model calibration on real sport
data, source availability, provider terms, cloud cost, market-specific
settlement rules, venue reconciliation, protected-process isolation, or live
readiness. Those remain future review gates. No strategy research or outcome
experiment was run.
