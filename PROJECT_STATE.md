# Project Genesis state

Updated: 2026-09-21

## Current milestone

The V2.1 hostile-audit remediation batches R0 through R10 are implemented and
green in the local repository. The checkpoint is ready for the required fresh,
independent hostile implementation audit.

This is not an adapter GO decision. Genesis remains **NO-GO for the first
read-only sport/source adapter** until an independent audit finds no unresolved
CRITICAL/HIGH adapter-gating weakness and the checkpoint receives explicit
review/approval.

No strategy research, outcome experiment, source or venue adapter, external API,
credential, cloud deployment, dashboard, live order path, chaos-certification
system, or £100 canary was added.

## Frozen authority and repository lineage

- V2.1 authority ZIP SHA-256:
  `a3a8e191be2176551e6ae99367f601eddd08b93fd7434432c2e84ca4b4d448e0`.
- V2.1 inner foundation snapshot SHA-256:
  `1015cf7507f5aebce87f812367df3c77eebe58da15a0fa478acfb8d168201585`.
- Manifest verification: 156/156 entries, zero failures.
- Audited Git baseline: `ae9cfa11128a476b2ec7f598df3d68e30b91f156`, tagged
  `v0.4-audited-v2.1-baseline`.
- R0 through R9 green commits: `8625e7b`, `afc56b7`, `f8f91ff`,
  `f42bd8d`, `169ef9d`, `28d5013`, `8bb86f3`, `b1f22e5`, `d486297`,
  and `128d392`.
- The exact final R10 commit/tree identity is generated after the green commit
  in the external re-audit manifest; a commit cannot truthfully contain its own
  final identity.

## Remediated foundation invariants

- JSONL remains the authoritative append-only history. A sibling SQLite file is
  only a cross-process transaction coordinator for verified read/check/append.
- PIT decision reads require an append-only source-capability authority resolved
  as of decision time; retrieval after the cutoff is inadmissible.
- Raw content, observations, source contracts, structured research evidence,
  frozen evidence packs, and candidate decision identity are distinct and
  replayable.
- `QualificationAuthority.evaluate()` resolves every identity and gate from
  required authorities. Caller booleans and the legacy qualifier cannot produce
  post-audit `QUALIFY`. Successful qualification persists one immutable
  `QualificationRecord`.
- Ranking has no exceptional-short, market-family, group-label, raw-odds, raw-EV,
  or incomparable raw-probability quality shortcut. It ranks only within explicit
  comparability groups and deterministically diversifies across groups.
- Risk owns durable bankroll, qualification, safety, approval, and exposure state;
  derives stake and BACK/LAY liability; enforces `1u = 0.025` and the hard 3u cap;
  and survives restart.
- Paper execution enforces one order-intent lineage per candidate hash, exact
  consumed risk-approval binding, authority-owned recertification, durable mode
  and kill state, and reconciliation blocking after ambiguous restart.
- Settlement has one current economic head per fill. Corrections, voids, and
  cancellations require the current same-fill head and record distinct
  `delta_pnl` and `effective_pnl`.
- OddsPapi Interpretation A is the approved active offline policy: normal budget
  220, protected reserve 30, assumed provider ceiling 250, daily billable limit 7.
  Interpretation B is test-only. Reserve use requires durable, exact authority.
- Protected evaluation uses sealed frames, frozen predictions, a separate spawned
  label-owning evaluator, bytes-only canonical JSON IPC, durable non-refundable
  attempts, and controlled certificates/errors. Real protected activation remains
  disabled; only the explicit local-checkpoint test switch is available pending
  independent boundary review.

## R10 verification

- Full original-plus-remediation suite: **110 tests passed, 0 failures, 0
  errors**.
- `python -m compileall -q src tests`: passed.
- F12 stress: 20/20 bounded runs passed; each run used 8 processes × 10 appends,
  for 1,600 expected records and zero chain forks/corruption.
- Cross-component stress: 3/3 campaigns passed, 8 concurrency/fault tests per
  campaign, 24/24 executions total.
- Restart matrix: all 17 order states and all 7 risk exposure states passed their
  explicit restart disposition checks.
- Process-death injection after transaction acquisition/verified read and before
  append preserved the previous valid head and allowed a later valid append.
- Source scan found no import or call of `qualify_v04`,
  `LegacyUnsafeProtectedEvaluationBoundary`, or
  `LegacyInProcessEvaluationHarness` outside their defining modules. Registered
  V2 campaigns and authoritative qualification have behavioral route guards.

Detailed traceability and results are under `remediation_evidence/R0` through
`remediation_evidence/R10`.

## Compatibility and migration state

Legacy records remain readable only where an explicit deterministic migration is
defined. Incomplete candidate/evidence/risk/order records, ambiguous duplicate
settlements, unsupported active schemas, and inferred quota interpretations are
audit-only or fail closed. No missing identity, observation time, tier, order,
settlement, or quota intent is inferred.

## Residual external facts and risks

- No independent post-build hostile audit has yet been performed in this task.
- The OddsPapi 250-call ceiling is a planning assumption, not verified provider
  evidence; no provider integration exists.
- The protected evaluator is an offline local process boundary, not a deployed
  label vault/service, and real campaigns remain disabled.
- No real source availability, entitlement, revision behavior, sport semantics,
  model calibration, profitability, cloud cost, venue reconciliation, or live
  readiness is evidenced.
- Market/venue-specific settlement rules remain future adapter work.

## Safe next step

Perform the frozen Astra hostile re-audit against the exact R10 commit and bundle.
Do not start a sport/source adapter or any later Genesis phase unless that audit
closes all relevant CRITICAL/HIGH findings and the checkpoint is explicitly
approved.
