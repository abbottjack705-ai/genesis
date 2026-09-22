# Project Genesis state

Updated: 2026-09-22

## Current milestone

The V2.1 R0–R10 checkpoint was independently audited at `166f923`.
Astra returned **HOLD / NOT APPROVED** (A1 CRITICAL, A2–A8 HIGH). S1 has
locally repaired A1+A2; S2a/S2b locally repaired A3/A7. Approved ADR-0002 v1
authorizes S3; S3a locally repairs A5 with a 150/150 final full-suite gate.
S3b locally repairs A4 with a 173/173 full-suite gate. S4 locally repairs A6
with a 184/184 full-suite gate. A8 remains open and requires staged remediation and a fresh
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
  persists an immutable v3 record on success. S3a fences exact PIT/manifest
  correspondence; S3b verifies the content-addressed decision output against
  an independently approved, pinned resolver/rule binding. Without a real
  strategy-specific approval it returns PASS.
- Ranking has no exceptional-short, market-family, group-label, raw-odds, raw-EV,
  or incomparable raw-probability quality shortcut. It ranks only within explicit
  comparability groups and deterministically diversifies across groups.
- Risk owns durable bankroll, qualification, safety, approval, and exposure state;
  derives stake and BACK/LAY liability and enforces `1u = 0.025` and the hard 3u
  cap. S2a rejects unsupported active risk/bankroll/safety replay. S2b
  coordinates current bankroll, safety, qualification and exposure heads
  through the risk approval append. S3b additionally rejects legacy or
  mismatched v3 lineage and a different side or out-of-band requested price.
- S1 PAPER execution enforces one order-intent lineage per candidate hash,
  exact consumed approval plus active reservation binding, and mandatory fresh
  recertification at pending and sent. S1 fences the known durable safety/risk/
  market/refresh heads during the order append. Ambiguous restart still blocks
  blind retry; this is not a claim that A4–A8 are closed.
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

## S2a verification

- Strict active-state replay regressions: RED on clean `166f923` and S1
  `2835238` (7 methods, 10 assertion failures on each); GREEN 7/7.
- Impacted retained plus S1 suite: 38/38 before the final A3 adversary was
  added. Complete final suite: 130/130; `compileall`
  passed. Full outputs and hashes: `remediation_evidence/S2a/`.
- A7 remained open at the S2a checkpoint; S2b below is its separate closure.

## S2b verification

- A7's nine independent regressions: RED on isolated clean `166f923` and
  preceding S2a `aed0e5b` (six invariant assertion failures, zero import/setup
  errors on each); GREEN 9/9. Spawned workers explicitly loaded each selected
  checkout's source. Both rebase-before-admission and authority-writer-after-
  admission-lock schedules, kill, qualification ambiguity, cap competition,
  restart and post-fsync coordinator-commit loss were checked.
- Retained R5/R6/R7/R10 plus S1/S2a/S2b: 56/56; full suite: 139/139;
  `compileall` passed. Exact transcripts/hashes: `remediation_evidence/S2b/`.
- A3+A7 risk group is locally green, not independent audit approval or a GO.

## S3a verification (partial S3 checkpoint)

- ADR-0002 v1 was approved separately on 2026-09-22 with exact SHA-256
  `7e851df9898f3a257a87b602bc1a7f6011ebae1397d42c17b8727c84e554ae00`.
- Eleven independent A5 regressions were RED on sealed `166f923` and the
  preceding approved-head `3729022` (11 invariant assertion failures each,
  no import/setup failures). Exact manifest/observation/PIT/capability replay,
  cutoff selection and append-boundary interleavings are locally green.
- Targeted 22/22, final full suite 150/150 after source-contract replay
  hardening, and `compileall` passed. The first unprivileged run's 12
  Windows multiprocess permission errors and temporary approval-service
  rejection are preserved; the permitted final rerun is green.
- This is local A5 closure only, not independent audit approval.
- S3b's separate local A4 closure follows. There is no model, live adapter,
  shadow or money GO.

## S3b verification (local A4 checkpoint)

- Approved ADR-0002 v1 remains the exact S3 identity authority (SHA-256
  `7e851df9898f3a257a87b602bc1a7f6011ebae1397d42c17b8727c84e554ae00`).
  Existing v1/v2 identity functions and historical hashes are unchanged.
- The final independent A4 set was RED on sealed `166f923` and clean S3a
  `4f04c0a`: 23 methods, 43 invariant assertion failures on each baseline,
  zero import/setup errors. A same-worktree side/price adversary was also RED
  before its risk-boundary repair.
- Candidate-v3 and `qualification-record-v3` bind content-addressed
  DecisionOutput-v1 and the exact FeatureInputManifest-v1. Qualification
  requires a separately approved active rule binding and pinned resolver
  reproduction, not caller copies or a mere self-hash. Risk, intent and
  pending/sent checks retain the output lineage; rule revocation blocks new
  actions. Legacy v1/v2 history remains readable and terminal settlement
  remains legal, but legacy identity cannot authorize new actions.
- Synthetic resolver and binding fixtures exist only in tests. No real model,
  calibration, tier formula/cutoff, expiry TTL, strategy-specific approval,
  adapter, protected research campaign or live path was created. Production
  qualification remains fail-closed. Targeted 51/51, retained 81/81 and full
  173/173 are green; `compileall` passes. Exact evidence is in
  `remediation_evidence/S3b/`.
- This is local A4 closure only, not independent Astra re-audit approval.
  A6 is addressed separately below; A8 and the overall audited HOLD remain open.

## S4 verification (local A6 checkpoint)

- Eleven independent cache-authority tests were RED on sealed `166f923` and
  clean S3b `42f7540`: 15 invariant assertion failures on each baseline, zero
  import/setup errors. The original caller-created `CachedData(verified=True)`
  reproduced Astra's nonexistent-cache bypass.
- `VerifiedCacheStore` now owns content-addressed bytes and exact versioned
  entry identity. Each entry binds provider request, provider, active quota
  policy, capture, expiry, byte length and object hash. Append-only
  invalidation history is resolved at the request time.
- Quota decisions fence the cache authority log through their durable append.
  Persisted cache hits carry the complete proof identity and fail replay when
  the authority/object is missing, tampered, incompatible or unavailable.
  Legacy caller `verified` values cannot authorize a cache hit.
- Targeted cache/R8/foundation tests passed 39/39; full regression passed
  184/184; `compileall` passed. Exact evidence is in
  `remediation_evidence/S4/`.
- Interpretation A, daily/monthly/reserve arithmetic and the one-allowance law
  are unchanged. This is local A6 closure only. A8 and the overall audit HOLD
  remain open; no adapter, research or live GO follows.

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

Review S4, then proceed to A8. A new
independent hostile re-audit and explicit checkpoint approval are still required
before any adapter or later Genesis phase.
