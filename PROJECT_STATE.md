# Project Genesis state

Updated: 2026-09-18

## Current milestone

The approved V0.3 → V0.4 foundation migration is implemented as an
offline/paper-only contract layer in this fresh Genesis repository. No betting
strategy, outcome-model search, external network/API call, credential, venue
adapter, or real-money execution capability has been added.

## V0.4 foundation implemented

- versioned V0.4 starting policy objects for odds profiles, provisional near-
  fair tolerance, non-quota daily search aims, units, tiers, liability, and
  correlation limits;
- dependency-pinned configuration remains deterministic and live-disabled;
- source capability records and a controlled synthetic bitemporal PIT store;
- immutable frozen evidence packs, pack manifests, decision hashes, and
  reproducibility manifests;
- expanded candidate fields for PIT, evidence, model/calibration, price,
  execution, risk, correlation, dependency, and decision identity;
- market capability registry that fails closed on false or unknown required
  capability;
- append-only candidate-run retention and non-quota search coverage telemetry;
- V0.4 exact PASS reason taxonomy and an ordered fail-closed `qualify_v04`
  interface; the legacy `qualify` call remains for compatibility;
- deterministic price-sanity arithmetic and tier/region-aware qualification
  ordering; the near-fair tolerance is explicitly provisional and not an
  empirical result;
- selection-aware aggregate evaluation for all, qualified, and selected sets,
  PASS reasons, dependence groups, and protected PASS-ablation request shape;
- protected-evaluation campaign/attempt boundary with suppression and
  non-refundable reservation semantics layered over the existing label-private
  evaluator skeleton;
- deterministic bankroll units, open-liability/correlation checks, pending
  and UNKNOWN exposure blocking, single-use risk approvals, rebase rules, and
  append-only risk audit events;
- provider-neutral paper order state machine, idempotency, timeout → UNKNOWN →
  reconciliation, critical-evidence recertification, mode authority, and
  kill-switch contracts;
- append-only fill/settlement ledger with correction deltas and existing
  Decimal payoff arithmetic as the calculation kernel;
- offline quota ledger/cache policy and provider-neutral scheduler/cost/runtime
  ports; no provider or cloud selection has been made.

## Test evidence

The complete deterministic suite currently passes: **28 tests, 0 failures,
0 errors**. `python -m compileall -q src tests` also passes. The suite uses the
repository-local `work/test_runtime/` scratch area because this Windows
environment denies the Python private temp directory.

The tests cover the original V0.3 contracts plus V0.4 policy boundaries,
provisional price tolerance, PIT capability/ready-time rejection, frozen pack
hashing, decision-hash changes, candidate retention, non-quota search
telemetry, fail-closed gates, selected-set summaries, protected attempt
consumption/suppression, risk caps and unknown exposure, paper idempotency and
reconciliation, ledger corrections, quota exhaustion, and append-only audit
chains.

## Remaining or deliberately partial

- protected evaluation is still an in-process tested boundary skeleton; a
  separate process/service with stronger side-channel controls is required
  before any protected campaign;
- selected-set reports are aggregate interfaces, not evidence of calibration or
  profitability;
- risk reservations, paper orders, and some runtime ports are not yet backed by
  a durable production service or restart rehydration protocol;
- `EvidenceStore` metadata does not yet automatically emit every V0.4
  supersession field; the controlled PIT record layer carries those semantics;
- no source/provider is active; Hoofs, Race Shape, Betfair, OddsPapi, football,
  tennis, and other sport data remain unverified capabilities;
- no sport-specific model, strategy card, outcome experiment, cloud deployment,
  live venue, credential, or real-money order path exists;
- market-family-specific settlement rules and venue reconciliation remain
  future approval gates.

## Legacy boundary

`C:\Users\abbot\Documents\sports-lab` and
`C:\Users\abbot\Documents\Codex\2026-09-11\ca\work\m9_repair` remain
read-only legacy material. No legacy file was modified or imported. Reuse
decisions remain in `LEGACY_INVENTORY.md`.

## Safe next step

Review the partial trust-boundary and durability items, then independently
audit the foundation contracts before any read-only sport adapter or
prospective data capture is introduced. Do not begin strategy research or live
execution as part of this foundation milestone.
