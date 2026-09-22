# Project Genesis state

Updated: 2026-09-22

## Current milestone

The V2.1 R0–R10 checkpoint was independently audited at `166f923`.
Astra returned **HOLD / NOT APPROVED** (A1 CRITICAL, A2–A8 HIGH). S1 has
locally repaired A1+A2 and passed its targeted and full regression gates;
the remaining A3–A8 are open and require staged remediation and a fresh
independent hostile re-audit. The original R0–R10 history is preserved.

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
- `QualificationAuthority.evaluate()` requires its configured authorities and
  persists an immutable `QualificationRecord` on success. Astra A4/A5 show that
  mutable material outputs and unrelated same-event PIT rows can still enter
  qualification; this boundary is not yet closed.
- Ranking has no exceptional-short, market-family, group-label, raw-odds, raw-EV,
  or incomparable raw-probability quality shortcut. It ranks only within explicit
  comparability groups and deterministically diversifies across groups.
- Risk owns durable bankroll, qualification, safety, approval, and exposure state;
  derives stake and BACK/LAY liability and enforces `1u = 0.025` and the hard 3u
  cap. A3 unsupported active replay and A7 cross-store risk admission remain open.
- S1 PAPER execution enforces one order-intent lineage per candidate hash,
  exact consumed approval plus active reservation binding, and mandatory fresh
  recertification at pending and sent. S1 fences the known durable safety/risk/
  market/refresh heads during the order append. Ambiguous restart still blocks
  blind retry; this is not a claim that A3/A7 are closed.
- Settlement has one current economic head per fill. Corrections, voids, and
  cancellations require the current same-fill head and record distinct
  `delta_pnl` and `effective_pnl`.
- OddsPapi Interpretation A is the approved active offline policy: normal budget
  220, protected reserve 30, assumed provider ceiling 250, daily billable limit 7.
  Interpretation B is test-only. Reserve use requires durable, exact authority;
  A6 shows caller-declared cache proof is not yet trustworthy.
- Protected evaluation uses sealed frames, frozen predictions, a separate spawned
  label-owning evaluator, bytes-only canonical JSON IPC, durable non-refundable
  attempts, and controlled certificates/errors. A8 shows research callbacks may
  run in the label-loading caller process, so process/address-space isolation is
  not established. Real protected activation remains disabled.

## R10 verification (historical, before Astra's audit)

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

## S1 verification

- Isolated clean `166f923` baseline: new A1/A2 tests RED, 35 assertion
  failures, zero setup/import errors. The original Astra probe is preserved and
  now stops at its first kill-switch submission attempt with a safe block.
- S1 new tests: 13/13 passed, including invalidation at pending and sent,
  own/other UNKNOWN, VOID/SETTLED, restart, and deterministic authority-writer
  interleavings. Retained R5/R6/R7/R10: 27/27 passed.
- Full regression: 123/123 passed outside the sandbox. A sandboxed first run
  was inconclusive due to Windows `multiprocessing.Pipe` WinError 5 in unchanged
  R9 tests and an outdated legacy test expectation corrected without dropping
  its timeout coverage. `compileall` passed.
- Exact commands and outputs: `remediation_evidence/S1/`. Local green is
  partial; no adapter, research or live GO follows.

## Compatibility and migration state

Legacy records remain readable only where an explicit deterministic migration is
defined. Incomplete candidate/evidence/risk/order records, ambiguous duplicate
settlements, unsupported active schemas, and inferred quota interpretations are
audit-only or fail closed. No missing identity, observation time, tier, order,
settlement, or quota intent is inferred.

## Residual external facts and risks

- The independent R10 hostile audit occurred and returned HOLD. A fresh
  post-remediation hostile re-audit has not yet occurred.
- The OddsPapi 250-call ceiling is a planning assumption, not verified provider
  evidence; no provider integration exists.
- The protected evaluator is an offline local process, but A8 process isolation
  of arbitrary research is open; there is no deployed vault/service.
- No real source availability, entitlement, revision behavior, sport semantics,
  model calibration, profitability, cloud cost, venue reconciliation, or live
  readiness is evidenced.
- Market/venue-specific settlement rules remain future adapter work.

## Safe next step

Proceed to S2 (A3+A7) only after the S1 green commit, using new RED evidence
against `166f923`, then continue A4+A5, A6 and A8 in dependency order. A new
independent hostile re-audit and explicit checkpoint approval are still required
before any adapter or later Genesis phase.
