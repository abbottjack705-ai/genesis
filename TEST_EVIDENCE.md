# Test evidence

Updated: 2026-09-25

## Current audit disposition and staged gates

Astra's independent R10 audit returned **HOLD / NOT APPROVED**. The R10 results
below remain historical evidence, not proof of A1–A8 closure. S1 A1+A2 is
locally green: the two new Astra regression modules ran RED against isolated
clean `166f923` (13 methods, 35 invariant assertion failures, no setup/import
errors), then GREEN (13/13). Retained R5/R6/R7/R10 suites passed 27/27.
The complete suite passed 123/123 in 38.344 seconds outside the sandbox, and
`python -m compileall -q src tests` passed. Exact transcripts and SHA-256
evidence are under `remediation_evidence/S1/`.

An initial sandboxed full run had nine unrelated Windows `multiprocessing.Pipe`
access-denied errors in unchanged R9 tests and one obsolete legacy expectation
that permitted submission after material evidence change. The legacy test was
strengthened to assert the block while retaining timeout/reconciliation coverage;
the sandbox failure transcript is retained. The independent full rerun passed.
S2a A3 strict replay also ran RED on `166f923` and S1 (7 methods, 10 invariant
assertion failures each), then GREEN 7/7; final full suite 130/130 and
`compileall` passed. Evidence: `remediation_evidence/S2a/`.
S2b A7 risk admission ran RED on `166f923` and S2a (9 methods, six invariant
assertion failures each), then GREEN 9/9; impacted suites passed 56/56 and
the final full suite passed 139/139. The final `compileall` passed. Evidence:
`remediation_evidence/S2b/`. S3a's 11 A5 regressions were RED on `166f923`
and the approved pre-fix head `3729022` with 11 behavioral failures each,
zero import/setup errors; targeted exact-manifest and R3 tests are 22/22
green; final post-hardening full suite 150/150 and `compileall` passed.
The initial unprivileged Windows multiprocess failures and temporary
approval-service rejection are retained. Exact transcripts are in
`remediation_evidence/S3a/`.
S3b A4's final 23-method set was RED on sealed `166f923` and clean S3a
`4f04c0a` (43 invariant assertion failures each, no setup/import errors).
A same-worktree side/price mismatch test was RED before its fix. The final
S3b targeted suite passed 51/51, retained S1/S2 and R5–R10 passed 81/81,
the full suite passed 173/173, and `compileall` passed. Exact transcripts,
commands and hashes: `remediation_evidence/S3b/`.
S4 A6's 11 independent tests were RED on sealed `166f923` and clean S3b
`42f7540` (15 invariant assertion failures each, no setup/import errors).
The targeted cache/R8/foundation gate passed 39/39, the full suite passed
184/184, and `compileall` passed. Exact evidence is under
`remediation_evidence/S4/`.
S5 A8's 12 independent hostile methods were RED on isolated clean `166f923`
and clean S4 `0032ee7`, with 12 invariant assertion failures and zero
setup/import errors on each. Under separately approved ADR-0003 v1, the
research program now runs only in a distinct isolated process with a sealed
label-free launch and exact hashed program identity; the trusted label-owning
evaluator remains a different process and executes no research callback.
Targeted A8 plus retained R9 passed 23/23; explicit retained R0-R10 plus S1-S4
passed 184/184. That retained transcript's reported 39174.655-second elapsed
includes a host/session pause. The mandatory independent discovery run passed
196/196 in 288.095 seconds and `compileall` passed. Exact evidence is under
`remediation_evidence/S5/`. **The overall Astra HOLD remains; no GO is
granted.**

The independent post-S5 hostile audit of clean `27dd525` also returned
**HOLD / NOT APPROVED** with B1–B8. T1 addresses only B1, B2, B3 and B7.
Its initial 28-method B1/B2/B3/B7 set produced 29 deliberate invariant
failures on an isolated `27dd525`, with zero import/setup errors; the four
original Astra probes produced four intended failures. Additional RED runs
cover release-proof ownership and legal paths, mode/safety fencing and
legacy-v2 settlement compatibility. The finalized T1 gate passed 70/70,
retained R0–R10 plus S1–S5 passed 196/196, full discovery passed 266/266 in
865.285 seconds, and the explicit restart/concurrency/crash gate passed 36/36.
`compileall` and `git diff --check` passed. Exact commands, output identities,
retained-fixture reconciliation and the authority decision memo are in
`remediation_evidence/T1/`.

T2 starts from sealed T1 `d130c21668b769c371cfa4a4a75c3f382af1af71` and
addresses B6 only. The original unmodified Astra B6 probe produced its intended
assertion failure with zero errors. The independent T2 module was RED with five
assertion failures and zero errors, while both legacy identity controls passed.
After the versioned acyclic approval-ledger repair it passed 7/7. The full
final repository gate passed 273/273 in 165.800 seconds and `compileall` passed. A
retained targeted run's one pre-test Windows pipe permission denial is preserved;
the exact isolated permitted rerun passed. Exact commands and evidence are in
`remediation_evidence/T2/`. **B4/B5/B8 and the overall HOLD remain; no GO is
granted.**

T3 starts from sealed T2 `4214f38886d5046f76a3fa8002889f02a701187f` and
addresses B4/B5 only. The original unmodified probes were RED with two intended
assertion failures and zero errors. The independent pre-production module ran
12 tests with ten invariant assertion failures, zero errors and two legal
controls already green. Pre-seal review added two class-state adversaries; both
were assertion-based RED on sealed T2 and current pre-fix T3, with zero errors.
After the ADR-0003 implementation repair, the expanded module passed 15/15,
the original probes passed 2/2, and retained S5/R9/protected tests passed 25/25.
Full discovery passed 288/288 in 178.191 seconds;
`compileall` passed. Exact evidence is under `remediation_evidence/T3/`.
**B8 and the overall HOLD remain; no GO is granted.**

## Deterministic gate

Command:

```text
python -m unittest discover -s tests -t . -v
```

R10 pre-documentation result: **110 tests passed, 0 failed, 0 errored** in
26.759 seconds. This includes the original 28-test audited foundation suite,
all R1–R9 remediation regressions, and the R10 integrated recovery matrix.
No safety or concurrency test was skipped.

The post-documentation final rerun also passed **110/110** in 25.851 seconds.

Compilation:

```text
python -m compileall -q src tests
```

Result: **passed**.

The tests are deterministic, synthetic and offline. They use repository-local
scratch directories and do not access a network, provider, venue, credential,
protected external dataset or historical outcome source.

## Explicit remediation groups

| Required group | Primary evidence |
|---|---|
| qualification authority | `test_remediation_r3_qualification.py` — 11 tests |
| order uniqueness and risk binding | `test_remediation_r6_execution.py` — 9 tests |
| exact 3u/stake/liability risk | `test_remediation_r5_risk.py` — 8 tests |
| settlement lineage | `test_remediation_r7_settlement.py` — 7 tests |
| PIT capability, observation and evidence freeze | `test_remediation_r2_causal_evidence.py` — 9 tests |
| ranking invariants | `test_remediation_r4_ranking.py` — 6 tests |
| append concurrency | `test_remediation_r1_persistence.py` — 4 tests plus R10 stress |
| quota boundaries/authority/concurrency | `test_remediation_r8_quota.py` — 14 tests |
| protected evaluator IPC/attempts | `test_remediation_r9_protected.py` — 11 tests |
| complete restart/fault matrix | `test_remediation_r10_integration.py` — 3 tests |
| Astra S1 mandatory submission and reservation | `test_astra_s1_submission.py`, `test_astra_s1_reservation.py` — 13 tests |
| Astra S2a strict active replay | `test_astra_s2_replay.py` — 7 tests |
| Astra S2b cross-store risk admission | `test_astra_s2_admission.py` — 9 tests |
| Astra S3a exact manifest and PIT | `test_astra_s3_manifest.py` — 11 tests |
| Astra S3b trusted output and v3 adversaries | `test_astra_s3_output.py`, `test_astra_s3_v3_adversarial.py` — 23 tests |
| Astra S4 immutable cache authority | `test_astra_s4_cache.py` — 11 tests |
| Astra S5 research/evaluator process isolation | `test_astra_s5_process.py` — 12 tests |
| T1 B1 authoritative dependence | `test_astra_t1_dependence.py` — 9 tests |
| T1 B2 current portfolio | `test_astra_t1_portfolio.py` — 5 tests |
| T1 B3 proof-bearing release | `test_astra_t1_release.py`, `test_astra_t1_release_proof.py`, `test_astra_t1_release_integration.py`, `test_astra_t1_release_concurrency.py`, `test_astra_t1_legacy_release.py` — 38 tests |
| T1 B7 strategy/mode fencing and composition | `test_astra_t1_strategy.py`, `test_astra_t1_mode.py`, `test_astra_t1_composition.py` — 18 tests |
| T2 B6 acyclic exact human approval | `test_astra_t2_b6_approval.py` — 7 tests |
| T3 B4/B5 exact protected bytes and reachable state | `test_astra_t3_protected_integrity.py` — 15 tests |

Individual test methods combine closely related rows of the binding T-F01
through T-F15 matrix. Each batch checkpoint records the exact matrix rows it
closes; `remediation_evidence/R10/FINDING_TRACEABILITY.md` maps every finding to
the production functions and primary tests.

## RED-before and GREEN-after evidence

- R0 ran a separate hostile probe against the untouched audited baseline and
  reproduced F01–F15, including an F12 chain fork. The primary suite remained
  clean. Evidence: `remediation_evidence/R0/red_before_probe.py` and
  `red_before_result.json`.
- R1–R6 use the retained R0 observations as their RED-before evidence; their
  batch checkpoint files record targeted and full GREEN results.
- R7, R8 and R9 ran their exact new hostile tests/probes in detached clean
  checkpoint worktrees before production edits. Their `RED_BEFORE.md` and
  `GREEN.md` files preserve the before/after results.
- R10 introduced no new production fix. Its three integration tests are
  green characterization/fault evidence over already-remediated code, so no
  fabricated R10 RED is claimed.
- S1 added independent A1/A2 regressions before the production fix, ran them
  on an isolated clean checkout of `166f923`, then repaired and reran them.
  The original failed probe output is retained, not overwritten.
- T1 ran independent B1/B2/B3/B7 regressions on an isolated clean checkout of
  `27dd525` before production edits. It separately retained the original Astra
  probe failures, expanded concurrency/restart/legal-path RED runs, and a
  four-failure legacy-v2 compatibility RED before the additive proof schema.
  No failed transcript was replaced; `remediation_evidence/T1/GREEN_FINAL.md`
  records the final gates.
- T2 preserved Astra's original B6 cycle reproduction unchanged, then added an
  independent assertion-based RED suite on sealed T1 before production edits.
  The authority classification memo preceded the compatible versioned repair;
  no ADR content or historical identity was rewritten.
- T3 preserved the original B4/B5 probe failures on sealed T2 and added an
  independent 12-test RED suite before production edits. Its authority memo
  preceded the repair and classified it under unchanged ADR-0003 v1. The later
  outside-root positive-hardening case and two assertion-RED class-state cases
  expand the final module to 15 tests without replacing or inflating the
  historical RED claims.

## Concurrency and fault stress

### F12 repeated append stress

- Runs: 20 independent bounded repetitions.
- Per run: 8 spawned processes × 10 appends behind one start barrier.
- Expected/verified per run: 80 unique rows, one chain, monotonic sequence
  1–80.
- Aggregate: 20/20 passed, 0 failures, 1,600 expected records, 66.398 seconds.
- Each child join is bounded to 30 seconds.

### Cross-component campaigns

Three repeated campaigns each ran eight tests:

- transactional unique conditional append;
- candidate-unique order creation;
- same-fill initial settlement;
- daily quota admission;
- normal-month quota ceiling;
- restarted reserve-authorization ceiling;
- final protected-attempt reservation;
- process death inside append transaction.

Result: **3/3 campaigns passed; 24/24 test executions**, 17.363 seconds.

### Process-death injection

A child process exited with code 91 from inside `AppendOnlyJsonl.transaction()`
after acquiring serialization and verifying the existing row, but before
returning an append payload. The previous head still verified as one row; a
subsequent append succeeded and the two-row chain verified.

## Restart/rehydration matrix

`R10IntegratedRecoveryTests` reached every defined order state and restarted a
fresh adapter from durable authorities:

- 17/17 states had an explicit result;
- `SUBMISSION_PENDING`, `SUBMISSION_SENT`, `UNKNOWN` and
  `RECONCILIATION_REQUIRED` restarted reconciliation-blocking;
- all other states replayed exactly.

It separately replayed all 7 `ExposureState` values:

- MATCHED, PARTIALLY_MATCHED, UNMATCHED, PENDING and UNKNOWN remained open;
- SETTLED and VOID remained terminal/non-reserved;
- 7/7 values replayed byte/field-equivalently.

R5/R6 tests additionally prove bankroll head, safety/kill state, approval,
approval consumption, reservation, order identity/history, corrupt-schema
failure, duplicate index, terminal release and the consume-before-bind crash
boundary.

## Replay and isolation results

- Evidence: deterministic legacy metadata import; exact observation replay;
  legacy packs audit-only; structured evidence changes propagate through pack
  and candidate identity.
- Settlement: restart reproduces current heads; WIN→LOSS→WIN and void/cancel
  lineages conserve exact final effective P/L; concurrent initial writers yield
  one head.
- Quota: approved active Interpretation A passes 190/191/220/221/250/251,
  daily 7/8, authorization binding/revocation/expiry/grant, restart and race
  tests. Interpretation B is test-only.
- Protected evaluation: exact hashed research programs execute only in an
  isolated third process that starts before protected labels are materialized
  and before evaluator IPC exists. It receives only sealed frames and cannot
  receive a label path/store or evaluator endpoint. The trusted label-owning
  evaluator remains distinct, consumes durable non-refundable attempts and
  executes no arbitrary research callback. T3 additionally proves that the
  source bytes verified are the bytes executed, cached callables cannot cross
  identities, and reachable raw-label or unsupported opaque capabilities fail
  closed.
- Legacy reachability: a source scan found the legacy qualification/protected
  names only in their defining modules. Behavioral guards prove authoritative
  qualification does not route through the legacy qualifier and registered V2
  campaigns cannot select the unsafe harness.

## What these tests do not prove

They do not prove profitability, calibration on real sport data, provider
availability or terms, the assumed OddsPapi allowance, source entitlement,
cloud cost, sport/market semantics, venue reconciliation, deployed protected
service isolation, or live readiness. No strategy search, outcome experiment,
external call or real protected campaign was run.

The implementation remains NO-GO for a read-only adapter. T1/T2/T3 local green
does not resolve B8 or replace integrated hostile review and explicit checkpoint
approval.
