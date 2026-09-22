# Test evidence

Updated: 2026-09-22

## Current audit disposition and S1 gate

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
**A3–A8 remain open; no GO is granted.**

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
| protected evaluator IPC/attempts (A8 research-process isolation open) | `test_remediation_r9_protected.py` — 11 tests |
| complete restart/fault matrix | `test_remediation_r10_integration.py` — 3 tests |
| Astra S1 mandatory submission and reservation | `test_astra_s1_submission.py`, `test_astra_s1_reservation.py` — 13 tests |

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
- Protected evaluation: the evaluator has exact frames and durable attempt
  accounting, but A8 shows the caller may own labels and execute research
  callbacks in that same process. Existing client-object inspection does not
  establish the required process/address-space isolation.
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

The implementation remains NO-GO for a read-only adapter until the fresh
independent hostile audit and explicit checkpoint approval are complete.
