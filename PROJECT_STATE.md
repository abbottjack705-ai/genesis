# Project Genesis state

Updated: 2026-09-26

## Current milestone

The V2.1 R0–R10 checkpoint was independently audited at `166f923`.
Astra returned **HOLD / NOT APPROVED** (A1 CRITICAL, A2–A8 HIGH). S1 through
S5 locally repaired A1–A8, ending at clean commit `27dd525`. The independent
post-S5 hostile audit then returned **HOLD / NOT APPROVED** with B1–B8. T1
locally repairs B1, B2, B3 and B7 over that exact base. T2 locally repairs B6
over sealed T1 commit `d130c21668b769c371cfa4a4a75c3f382af1af71`; the
resulting sealed T2 commit is `4214f38886d5046f76a3fa8002889f02a701187f`.
T3 locally repairs B4/B5 over that exact T2 base; its pre-seal full suite is
288/288 green. T4 locally repairs B8's evidence representation over sealed T3;
the complete pre-seal suite is 297/297 green. The independent hostile re-audit
of T1–T4 at `ac6b66b` then returned **HOLD / adapter NO-GO** with N1 (HIGH),
N2 (MEDIUM), N3 (LOW) and observations O-1/O-2/O-3/O-5. The T5 candidate locally
repairs all of them (plus H1 and PA-1, found in T5's own hostile review) over
sealed T4 through three WIP resume commits and one candidate commit. T1–T5
still require integrated hostile review. The original R0–R10, S1–S5 and T1–T4
histories and all failed reproduction evidence are preserved.

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
  T1 additionally derives correlation membership from the bound decision output,
  persists that canonical membership, and recomputes current total and correlated
  capacity from authoritative exposure heads. A caller may compare a non-empty
  copy but cannot omit dependence. The order's own reservation is counted once.
- S1 PAPER execution enforces one order-intent lineage per candidate hash,
  exact consumed approval plus active reservation binding, and mandatory fresh
  recertification at pending and sent. S1 fences the known durable safety/risk/
  market/refresh heads during the order append. Ambiguous restart still blocks
  blind retry; at the S1 checkpoint this did not claim that later findings were
  closed.
- T1 fences current strategy lifecycle, coherent PAPER mode/safety, release
  proof, risk, bankroll, qualification, market and refresh heads through each
  relevant new-risk or pending/sent append. A stale active/PAPER read cannot
  survive a committed withdrawal or mode change and authorize a new action;
  an owner that cannot join the durable fence fails closed.
- T1 makes release a proof-bearing lifecycle event. A consumed reservation
  stays fully charged through pending, partial fill, UNKNOWN and reconciliation
  until an exact durable order/fill/settlement proof is validated under the same
  fence. Bare `SETTLED`, `VOID` or cancellation labels cannot create capacity;
  a late fill or incompatible correction restores UNKNOWN/full charge.
- T2 supplies an acyclic, operator-owned approval workflow while preserving the
  exact ADR-0002 binding-v1 preimage. A stable PAPER-only v2 reference is
  reserved first, the final binding hash is then computed, and an exact later
  human grant binds the two in a closed append-only ledger. Revocation and the
  approval head are fenced through qualification, risk and submission actions.
  Historical v1 approval notes and all candidate-v1/v2/v3 hashes retain their
  exact prior meanings.
- Settlement has one current economic head per fill. Corrections, voids, and
  cancellations require the current same-fill head and record distinct
  `delta_pnl` and `effective_pnl`.
- OddsPapi Interpretation A is the approved active offline policy: normal budget
  220, protected reserve 30, assumed provider ceiling 250, daily billable limit 7.
  Interpretation B is test-only. Reserve use requires durable, exact authority;
  S4 replaced caller-declared cache trust with content-addressed cache proof.
- Protected evaluation uses sealed frames, frozen predictions, durable
  non-refundable attempts, controlled certificates/errors and two separately
  spawned processes. The isolated research worker starts before protected label
  materialization and evaluator-channel creation, receives only sealed
  label-free frames plus an exact hashed `ResearchProgramRef`, and cannot
  receive a label path/store or evaluator endpoint. The distinct trusted
  evaluator owns labels and never executes arbitrary research code. Real
  protected activation remains disabled.

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
  A6 and A8 are addressed separately below; the overall audited HOLD remains.

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
  are unchanged. This is local A6 closure only. The overall audit HOLD remains;
  no adapter, research or live GO follows.

## S5 verification (local A8 checkpoint)

- ADR-0003 v1 was separately approved on 2026-09-22 at exact SHA-256
  `0fd4c63deb7a8431c41d7869163ccf79ce0295b63b585c8e4c3a0695f1dafaad`.
  The immutable decision record and its separate versioned approval note are in
  `DECISIONS/`.
- Twelve independent A8 regressions were RED on isolated clean `166f923` and
  clean S4 `0032ee7`: 12 failing invariant assertions and zero setup/import
  errors on each. They cover retained parent labels/environment/path, distinct
  third-PID execution, closed capabilities, direct-callable rejection, exact
  program identity, crash/restart/non-refund, generic exceptions, malformed
  IPC, timeout, module-global labels, final-attempt concurrency and root overlap.
- The final hostile/retained targeted gate passed 23/23. The explicit retained
  R0-R10 and S1-S4 gate passed 184/184; its reported 39174.655-second elapsed
  time includes a host/session pause, not test execution time. The mandatory
  independent full discovery rerun passed 196/196 in 288.095 seconds, and
  `python -m compileall -q src tests` passed.
- Exact commands, outputs and hashes are in `remediation_evidence/S5/`.
  This is local A8 closure only. A fresh hostile re-audit and explicit
  checkpoint decision remain mandatory; no adapter, shadow research, protected
  campaign or live-money GO follows.

## T1 verification (local B1/B2/B3/B7 checkpoint)

- The exact pre-fix source was clean post-S5 commit
  `27dd525c1fd7d531c4833c4bf7e44204a9345f19`. The finalized independent
  B1/B2/B3/B7 tests ran in an isolated checkout and produced 29 deliberate
  invariant failures across 28 methods with zero import/setup errors. The four
  original Astra reproductions also failed for their four intended invariants.
- Additional RED evidence covers the proof owner, every legal release path,
  release/new-risk and owner-attachment interleavings, PAPER mode/safety
  coherence, and the legacy-v2 compatibility boundary. The latter produced
  four deliberate failures before implementation and is reconciled in
  `remediation_evidence/T1/LEGACY_V2_RELEASE_DECISION_MEMO.md`.
- The legacy repair is additive and audit-only. It binds the exact existing v2
  qualification ID and durable row hash plus order, fill and current settlement
  heads. It does not invent a v3 output, alter a historical identity or permit
  qualification, risk, pending or send.
- Original hostile outcomes passed 4/4; the consolidated T1 gate passed 70/70;
  retained R0–R10 and S1–S5 passed 196/196; the full repository passed 266/266
  in 865.285 seconds; explicit restart/concurrency/crash gates passed 36/36;
  `compileall` and `git diff --check` passed.
- Retained S1/S3 fixtures were changed only where their setup depended on the
  invalid bare-terminal-release assumption. Original assertions were preserved
  or strengthened, and all pre-change blobs, diffs and transcripts remain in
  `remediation_evidence/T1/`.
- This is local closure of B1, B2, B3 and B7 only. B4, B5, B6 and B8 and the
  overall hostile-audit HOLD remain. No adapter, strategy, shadow-research,
  protected-campaign or live-money GO follows.

## T2 verification (local B6 checkpoint)

- T2 begins at sealed T1 commit
  `d130c21668b769c371cfa4a4a75c3f382af1af71`, tree
  `15253d9c3b8e474509e05d43f10db04b7b949b4a`. No T1 history was amended.
- Astra's original unmodified B6 probe is preserved as assertion-based RED:
  one intended failure and zero errors. The independent seven-test module was
  also RED on T1 with five explicit missing-owner invariant failures and zero
  errors; its two historical identity controls were already green.
- `T2_B6_DECISION_MEMO.md` classifies the repair as B: compatible versioned
  schema/interface evolution under approved ADR-0002, not a substantive
  contract change. The legacy raw-content-hash v1 path is unchanged.
- The genuine reserve -> final binding -> grant workflow passes through the
  unmodified production validator. Missing, wrong, future, tampered and revoked
  grants; wrong scope/binding; absent authority; restart/replay; and concurrent
  publication all fail or serialize as required. Golden v1/v2/v3 candidate and
  binding hashes are unchanged.
- Targeted T2 passed 7/7. The final full repository passed 273/273 in 165.800 seconds
  and `python -m compileall -q src tests` passed. One earlier retained targeted
  run had a Windows sandbox `CreateFile` permission error before an unchanged
  multiprocessing test body; the exact isolated permitted rerun passed 1/1.
- This is local B6 closure only. B4, B5 and B8 and the overall hostile-audit
  HOLD remain. No actual strategy binding/model/rule, adapter, shadow research,
  protected campaign or live-money GO is granted.

## T3 verification (local B4/B5 checkpoint)

- T3 begins at sealed T2 commit
  `4214f38886d5046f76a3fa8002889f02a701187f`, tree
  `31f00dabaaf320835f8aaf7d041ab5c75bc1b83c`. T1 and T2 history is unchanged.
- Astra's original unmodified B4/B5 probes are preserved RED on T2: two intended
  assertion failures and zero errors. The independent pre-production module ran
  12 tests with ten assertion failures, zero errors and two legal controls green.
  Pre-seal review added two class-state adversaries; both failed by assertion on
  sealed T2 and the then-current worker, with zero errors.
- `T3_B4_B5_AUTHORITY_MEMO.md` classifies the repair as A: implementation of the
  already-approved ADR-0003 contract. The ADR, approval note,
  `ResearchProgramRef-v1`, program digest, process topology and attempt lifecycle
  are unchanged.
- The worker now verifies one exact source origin and source-byte hash before
  target import-time execution, then compiles and executes those same bytes in a
  fresh namespace. It never reuses a cached target callable. A cycle-safe,
  no-depth-cutoff audit rejects labels reachable through object dictionaries,
  slots, function attributes, custom imported holders and deep/cyclic state;
  unsupported opaque or dynamic-reflection capabilities fail closed.
- The final T3 suite passed 15/15; the original probes passed 2/2; retained
  S5/R9/protected tests passed 25/25; the full repository passed 288/288 in
  178.191 seconds; and `python -m compileall -q src tests` passed.
- This is local B4/B5 closure only. B8 and the overall hostile-audit HOLD remain.
  No adapter, strategy, shadow research, protected campaign or live-money GO is
  granted.

## T4 verification (local B8 checkpoint)

- T4 begins at sealed T3 commit
  `39a21328f76cb522bb5b198af1c1e76485d6fe5f`, tree
  `b730ee8423accaaa56308558cf8d3d513e948670`. T1–T3 history is unchanged.
- The standalone historical probe reproduced exactly 192/192 Git-blob/archive
  byte mismatches, zero mismatches after CRLF-to-LF comparison, both approved
  ADR hash mismatches and missing representation labels. It ran four methods
  with five assertion failures and zero errors. Five independent acceptance
  tests were also RED on T3 because no compliant packager existed.
- `T4_B8_AUTHORITY_MEMO.md` classifies the repair as A: the audit explicitly
  requires this packaging correction. No ADR, product identity, source module or
  historical evidence is edited.
- The audit-only tool packages exact target Git blobs, separately labeled raw
  worktree bytes and unchanged historical artifacts. Its closed manifest pins
  approved ADR hashes; deterministic ZIP/sidecar output verifies without Git
  after fresh extraction and optionally cross-checks every source byte against
  the target Git tree. Duplicates, unsafe paths, tampering and representation or
  authority disagreement fail closed.
- Adversarial review of the inherited tool added RED-first hardening: verify
  requires caller-pinned ADR authorities, non-Git manifest rows and fixed fields
  are closed, and raw worktree evidence is limited to Git-tracked files.
- On the final bytes targeted T4 passed 9/9; the full repository passed 297/297
  in 153.972 seconds; and `python -m compileall -q src tests tools` passed. The
  earlier 293/293 run preceded the hardening and is history only.
- This is local B8 closure only. The external package is generated from the
  sealed T4 commit to avoid self-reference, then requires fresh hostile review.
  No adapter, strategy, shadow research, protected campaign or live-money GO is
  granted.

## T5 verification (local N1/N2/N3/O-5/package candidate)

- T5 begins at sealed T4 `ac6b66be9dc119a75a0dfb772890cfd2c3919c52`; WIP resume
  commits `220c4d0`, `582459b` and `42e46c7` are kept unmodified, and the
  candidate is one further commit. `T5_AUTHORITY_MEMO.md` classifies every
  change as A or B; none needs a new ADR version.
- N1/PA-1 (WIP): hashed-program closure, restricted execution, origin guard,
  runtime audit hook, post-execution state checks, one digest per research
  worker and nonce-authenticated canonical IPC. The Windows / CPython 3.12.10
  rerun found an intermittent research timeout caused by the worker's
  per-function path resolution; a RED-first per-scan cache removed it without
  changing what the scan accepts. All 71 protected/retained tests pass there.
- N2: a sidecar owner manifest binds one owner per kind to each risk log by
  lock-equivalent relative location; admission, consumption, send, proof,
  attach, release and rebase refuse split, copied or swapped owners, while
  reopened, equivalent-path, restarted and relocated owners still work. H1
  adds a write-once claim so the bankroll, qualification log and output store
  serve exactly one risk log.
- N3: each risk append replays the exact new row before it is written. O-5: a
  V3 qualification needs its exact unrevoked prior grant at record time.
  O-1/O-2/O-3: package schema v2 with raw-root completeness, canonical manifest
  bytes and commit/raw-root/historical pins.
- Baseline at `42e46c7` on Windows: 351 tests, 24 failures, 0 errors — exactly
  the N2/N3/O-5/package RED inventory. The T5 hostile suite was RED on the WIP
  for H1 and is RED on sealed T4 for H1/H2/H4/H5/H6. Final gates are in
  `remediation_evidence/T5/GREEN_FINAL.md`.
- This is local closure only; the external package is generated from the
  candidate commit. No adapter, strategy, shadow research, protected campaign
  or live-money GO is granted.

## Compatibility and migration state

Legacy records remain readable only where an explicit deterministic migration is
defined. Incomplete candidate/evidence/risk/order records, ambiguous duplicate
settlements, unsupported active schemas, and inferred quota interpretations are
audit-only or fail closed. No missing identity, observation time, tier, order,
settlement, or quota intent is inferred.

## Residual external facts and risks

- The independent R10 hostile audit occurred and returned HOLD. A fresh
  A-finding re-audit occurred after S5 and returned HOLD with B1–B8. T1 locally
  repairs B1/B2/B3/B7, T2 locally repairs B6, T3 locally repairs B4/B5 and T4
  locally repairs B8. The T1–T4 hostile re-audit returned HOLD with N1–N3, which
  the T5 candidate repairs locally. None of these checkpoints has received
  integrated hostile approval.
- T5 owner binding is trust-on-first-use per owner kind; a deliberate fork of a
  whole deployment, or of content into separate stores, is outside what local
  binding can detect.
- The OddsPapi 250-call ceiling is a planning assumption, not verified provider
  evidence; no provider integration exists.
- S5 establishes the local test-harness research/evaluator process boundary,
  but there is no deployed protected vault/service and no real protected
  campaign is authorized.
- No real source availability, entitlement, revision behavior, sport semantics,
  model calibration, profitability, cloud cost, venue reconciliation, or live
  readiness is evidenced.
- Market/venue-specific settlement rules remain future adapter work.

## Safe next step

Build and freshly verify the byte-explicit package of the exact T5 candidate
commit, then submit the complete T1–T5 composition for a new independent
hostile audit.
Explicit audit/checkpoint approval remains mandatory before any adapter or later
Genesis phase.
