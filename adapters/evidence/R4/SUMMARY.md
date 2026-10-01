# V0.5 slice-1 controlling hostile-audit remediation R4 - PIT recovery, quiescence and consumption

| | |
| --- | --- |
| Failed candidate (unchanged) | `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` |
| Base of this commit | R3 `a6fd9756b8af13d7272b5eee6958244f2d5ff263` |
| Architecture authority | `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe` (`V05_ADAPTER_ARCHITECTURE.md` r3) |
| Controlling audit | `C:\Users\abbot\a8\v05_prep\audit_oracle\hostile_audit_cfcff3d\` (manifest 10/10 OK; never written to) |
| Findings | HA-05 (BLOCKER), HA-06 (BLOCKER), HA-12 (HIGH); the design 6.3 acquisition-quiescence lock |
| Commit | the commit that adds this file, on `v05-slice1-impl` on top of R3 (not amended; not pushed) |

Everything is under `adapters/`; the six frozen trees are unchanged. No credential, no provider or network contact,
no gate record, no G2, no READY capability outside throwaway test registries.

## Method

1. `RED.txt` - the R4 tests against the **unmodified R3 production code** (`a6fd975`): 10 tests, failures=19,
   errors=12 (subtests counted): mixed T2/T3 after a crash at every emission step, a pending invalidation leaving the
   old price readable, no mandatory verifier, no lock. (Two tests were added and two extended after this capture, to cover
   mutants; they run in `GREEN.txt` and `MUTATION.txt`.) The only change before the RED run was test-side:
   `emit_support.derivation_accepted`.
2. The production changes below, then `GREEN.txt`, `MUTATION.txt`, `FROZEN.txt` + `FROZEN_COMPARE.txt`,
   `COMPILE.txt`, `DIFFCHECK.txt`, `TREES.txt`, `GUARDS.txt`; `HASHES.sha256` covers them.

## Finding by finding

### HA-06 (BLOCKER) - one response, one T2 and one T3, and the quiescence lock

- `oddspapi/emit.py` `emit_documents`: a resumed emission reuses exactly the times the interrupted one made durable
  (`_durable_times`: an observation's `parse_ready_at` is the response's T2, a PIT record's `ready_at` its T3) and
  stamps fresh ones only for a step that left nothing durable. One response carrying two T2 values is an
  EVIDENCE_CONFLICT, two T3 values a PIT_APPEND_CONFLICT. `append_pit_once` now requires the existing record to be
  identical (previously it tolerated a different `ready_at`, which is how one response got two T3s).
  The INVALIDATED head of a resumed invalidation reuses its durable T2/T3 the same way.
- `oddspapi/quiescence.py` (new): `run_lock(root)` is an exclusive OS lock on `<root>/run.lock` (`msvcrt.locking` /
  `fcntl.flock`, append-only file), refused - never queued - while another process holds it, released by the OS when
  its holder dies, re-entrant within one process. Every adapter phase holds it (`AcquisitionRunner.acquire` and
  `reconcile_after_restart`, `PipelineRuntime.acquire` / `normalize` / `resume`, `emit_invalidation`, and `cli.py run`
  for the whole run); `decision_phase(stores)` is the decision runner's side (lock + no unfinished work).
  `pending_work(stores)` lists the durable facts of unfinished adapter work: an attempt still open, a successful ODDS
  capture not yet normalized, a SECRET_ECHO / AUTH_REJECTED verdict whose halt or circuit is not yet recorded, an
  invalidation recorded but not applied. While any exists, or while another process holds the lock, the reader
  refuses (`DATA_CAPABILITY_NOT_READY`, with the reason) - so no decision can observe a half-emitted response, and a
  record appended by a resume with the response's (earlier) T3 was never visible to anyone in between.
- Authority note (for human ratification, not a stop): design 6.2 says T2 and T3 are shared by all books of a
  response; 14.4 says new T2/T3 are stamped at resume. They conflict only when a crash lands between appends of one
  response; this commit follows the controlling audit (reuse the durable times + the 6.3 lock) and stamps new times
  only for steps that left nothing durable.

### HA-05 (BLOCKER) - a pending invalidation never leaves the old price usable

A recorded but unapplied invalidation is unfinished work: every read is refused until it is completed, and every
start completes it, idempotently, without anyone calling `invalidate()` again (`emit.complete_pending_invalidations`,
called by `PipelineRuntime.resume` and by `cli.py run` before its first send; it re-runs the recorded invalidation,
which `emit_invalidation` already completes rather than duplicates). A completed invalidation then reads exactly as
design 13.2 states: unchanged for cutoffs before `T3_inv` (decisions inside `[T_inv, T3_inv)` were excluded by the
lock the emission held), INVALIDATED from `T3_inv` on. (A first draft blocked the record per entity from `T_inv` on;
it was withdrawn because 13.2 keeps every `D < T3_inv` unchanged - INV-01 asserts exactly that.)

### HA-12 (HIGH) - derivation verification is mandatory on every consumption path

`reader.admissible_head(..., derivation_check)` and `MarketBookReader(stores, derivation_check=...)` have no default;
`None` is a refusal (`DERIVATION_UNVERIFIED`); the check now always runs. `manifest.build_manifest_body` requires and
passes the verifier. `PipelineRuntime.reader()` is the production consumer: its `checked_derivation` re-derives every
head and, when that fails, invalidates the observation automatically (design 13.2, `ADAPTER_AUTOMATIC`,
`DERIVATION_DEFECT`) before the head is refused. Existing tests now pass a verifier explicitly: runtime-based tests the
real one (`rt.verify_derivation`); tests on synthetic emit_support stores, which hold nothing re-derivable, the named
accept-all `emit_support.derivation_accepted`.

## Test changes (disclosed)

- New `test_v05_r4_pit_recovery.py`.
- Existing tests that encoded the defects now assert the remediated behaviour: `test_v05_emit_crash` (one T3 per
  response after a crash anywhere; one T2), `test_v05_emit` F-33 (a record differing only in `ready_at` is a
  conflict), `test_v05_pit` PIT-08 (the resumed T3 is the first reading at the resume, the durable T2 being reused)
  and FR-03 (a rejected refresh carries its content verdict in its completed row, as R3 records it -
  `emit_support.seed_acquisition(failure=...)`). `test_v05_failure_matrix` FM-33 is unchanged and passes: a
  forged PIT record for one response's artifact is a second T3, i.e. a PIT_APPEND_CONFLICT.
- Reader / manifest call sites in `test_v05_reader`, `test_v05_invalidation`, `test_v05_manifest`, `test_v05_pit`,
  `test_v05_derivation_source`, `test_v05_failure_matrix`, `test_v05_r1_requested_tournaments` pass a verifier.

## Results

- `GREEN.txt`: complete adapter suite - Ran 678, OK, skipped=1 (`test_f04_a_link_is_refused`: no symlink privilege;
  real-symlink certification stays OPEN, see R1).
- `FROZEN.txt` / `FROZEN_COMPARE.txt`: frozen V0.4 suite - Ran 493, OK, skipped=1 - IDENTICAL to the recorded baseline.
- `TREES.txt`, `GUARDS.txt`: the six tree SHAs at HEAD, no frozen path changed or dirty, freeze and module-provenance
  guards PASS (manifest sha256 `9a50e370...fdf`). `COMPILE.txt`, `DIFFCHECK.txt`: clean.
- `MUTATION.txt`: 21 distinct mutants over 6 files (`emit.py` 6, `reader.py` 4, `quiescence.py` 6, `pipeline.py` 2,
  `manifest.py` 1, `cli.py` 2): 21 KILLED. `the manifest builder does not verify` survived the first run - the only
  manifest test got its refusal from a head the reader had already invalidated - so
  `test_ha12_the_manifest_builder_runs_the_verifier_it_is_given` was added and the mutant re-run against the whole
  R4 module: KILLED. (In the raw run each mutant appears twice: once as it runs, once in the per-file summary.)
- Production side fix found by the full suite (disclosed): the run-lock file is opened append-only (`"ab"`), so the
  adapter's no-rewrite rule (FR-07 static scan) still holds; `quiescence.py` writes nothing to it.
- Evidence secret sweep: `oracle_secret_sweep.py adapters/evidence/R4` - 166 sentinel forms, unexpected=0.
