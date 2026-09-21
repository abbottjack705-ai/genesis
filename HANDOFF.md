# Project Genesis V0.4 foundation handoff

Date: 2026-09-18  
Status: approved foundation migration implemented offline/paper-only

## Completed

- V0.4 policy/config contracts with normal 1.50–3.00 odds, exceptional
  1.40–1.49 policy, provisional versioned approximately -2pp near-fair
  tolerance, non-quota daily search aims, 1u = 2.5%, tiered stakes, 60%
  liability, and correlation controls.
- Controlled synthetic source capability and bitemporal PIT interfaces.
- Immutable evidence packs, append-only pack manifests, candidate decision
  hashes, reproducibility manifests, and expanded canonical records.
- Market capabilities, candidate-run retention, coverage telemetry, exact V0.4
  PASS taxonomy, fail-closed V0.4 gates, and tier/region ordering.
- Selected-set/PASS aggregate evaluation interfaces and protected campaign
  attempt/suppression controls.
- Offline risk reservations, single-use approvals, rebase policy, unknown
  exposure blocking, correlation/liability checks, and risk audit events.
- Paper-only order state machine, idempotency, critical refresh recertification,
  UNKNOWN reconciliation state, mode authority, and kill switch.
- Append-only fill/settlement/correction ledger using existing Decimal payoff
  arithmetic.
- Offline quota/cache and provider-neutral runtime/cost ports.

## Remaining

- Separate trusted-process protected evaluator with full side-channel controls.
- Durable risk/exposure/order services with restart rehydration and venue
  reconciliation.
- Integration of all evidence-store supersession metadata into pack creation.
- Real source capability verification and any read-only source adapter.
- Sport models, strategy cards, outcome research, cloud deployment, provider
  selection, credentials, venue adapters, and live execution.
- Market-family and venue-specific settlement rules.

## Tests

```text
python -m unittest discover -s tests -t . -v
Ran 28 tests
OK

python -m compileall -q src tests
PASSED
```

The tests are deterministic, synthetic, and offline. They are not evidence of
profitability, calibration on real sport data, provider availability, or live
readiness.

## Material files added or changed

Added modules:

- `src/genesis/policy.py`
- `src/genesis/pit.py`
- `src/genesis/capabilities.py`
- `src/genesis/evidence_pack.py`
- `src/genesis/decision.py`
- `src/genesis/candidate_runs.py`
- `src/genesis/selection_evaluation.py`
- `src/genesis/protected.py`
- `src/genesis/risk.py`
- `src/genesis/execution.py`
- `src/genesis/ledger.py`
- `src/genesis/quota.py`
- `src/genesis/runtime.py`
- `tests/test_v04_foundation.py`

Changed modules/docs:

- `src/genesis/config.py`, `canonical.py`, `registry.py`, `reasons.py`,
  `selection.py`
- `config/defaults.json`
- `PROJECT_STATE.md`, `ARCHITECTURE.md`, `TEST_EVIDENCE.md`,
  `V03_TO_V04_GAP_ANALYSIS.md`, `V04_MIGRATION_PLAN.md`

No legacy repository was modified.

## Unresolved design questions

1. What independent trusted-process mechanism will host protected evaluation,
   and what controlled summary/error protocol will it expose?
2. Which durable storage/runtime is affordable under the <=£10/month target?
3. Which source/provider can prove point-in-time availability, entitlement,
   revision semantics, and current quota terms?
4. Which sport/market adapter should be first after the foundation audit, and
   what exact strategy-card tier/support/settlement rules will it declare?
5. Which officially supported paper/live venue, if any, satisfies cost,
   liquidity, API, and credential-isolation requirements?
6. What simulation or prospective evidence will set the downward bankroll
   trigger and exact correlated-cluster cap within the approved starting range?

## Blocked items

The following are blocked by intentionally unavailable or unverified external
state, not by a code failure: provider terms/entitlements, external data,
venue credentials, cloud pricing/deployment, sport semantics, and
market-specific settlement rules. No network call or credential work was
attempted.

## Recommended next step

Run an independent hostile audit of the new PIT/evidence-pack, protected
evaluation, risk, and paper-state contracts. If accepted, implement durable
restart/reconciliation boundaries in offline/paper fixtures first; only then
begin a read-only sport/source capability study. Do not begin strategy search
or live execution.
