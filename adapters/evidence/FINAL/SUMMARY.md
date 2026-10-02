# V0.5 hostile-audit remediation - final isolated validation

| | |
| --- | --- |
| Failed candidate (unchanged) | `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` |
| Code under validation | R5 `9f846d8abcd7383d6acae78294f0aefaba08e630` (this directory is added by an evidence-only commit on top) |
| Remediation commits | R1 `875656e`, R2 `72cca77`, R3 `a6fd975`, R4 `2e1fb27`, R5 `9f846d8` |
| Architecture authority | `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe` |
| Controlling audit | `C:\Users\abbot\a8\v05_prep\audit_oracle\hostile_audit_cfcff3d\` (manifest 10/10 OK; never written to) |

Machine rule: before every heavy step no other Python process was running (each transcript header records the count
and the power state); steps ran one at a time. Heavy steps were started only with enough battery or on AC power, so
that no run could be cut by a critical-battery sleep (one earlier R2 run was, see `R2/MUTATION.txt`). The mutation
gate checked power before each round, not during it: AC was lost during R3 and the host slept through exactly one
mutant, which was re-run (mutation notes below).

## Results

| File | What | Result |
| --- | --- | --- |
| `ADAPTER_SUITE.txt` | full adapter suite | Ran 690, OK, skipped=1 |
| `FROZEN.txt`, `FROZEN_COMPARE.txt` | full frozen V0.4 suite | Ran 493, OK, skipped=1; IDENTICAL to the S0 baseline |
| `SUBSET_HOSTILE_REGRESSION.txt` | R1-R5 remediation modules, credential link attacks, gate-limit pin | Ran 127, OK, skipped=1 (real symlink) |
| `SUBSET_CRASH_RECOVERY.txt` | crash/restart convergence matrix | Ran 123, OK |
| `SUBSET_PIT_INVALIDATION.txt` | PIT / invalidation / reader matrix | Ran 71, OK |
| `SUBSET_DEADLINE_BOUNDARY.txt` | deadline / UTC boundary / clock matrix | Ran 58, OK |
| `SUBSET_CREDENTIAL_SECRET.txt` | credential / secret matrix (TX-01 subprocesses included) | Ran 112, OK, skipped=1 (real symlink) |
| `NO_NETWORK.txt` | full adapter suite under the oracle's independent network audit hook | Ran 690: 688 OK, skipped=1, errors=1; ORACLE NETWORK VIOLATIONS=1 - both are the suite's own deliberate guard self-test (see `NO_NETWORK_NOTE.txt`); no test reached any non-loopback address |
| `MUTATION_R1.txt` .. `MUTATION_R5.txt` | every remediation mutant re-run against the final code | 128 mutants (R1 16, R2 40, R3 34, R4 21, R5 17): 127 killed by the final suite, 1 equivalent survivor (the one R3 recorded); one R3 TIMEOUT was a host sleep, re-run KILLED - see mutation notes |
| `MUTATION_R3_RERUN.txt` | targeted re-run of the one mutant whose run spanned the host sleep | baseline PASS; KILLED (91 s) |
| `REPRO_CONTROLLING.txt` | 17 reproduction probes (controlling, parallel, earlier) | reproduced=0, not_reproduced=17, probe_errors=0 |
| `REPLAY.txt` | two uninterrupted fixture runs, every durable file by SHA-256 | 128 files, same set, none different |
| `COMPILE.txt`, `DIFFCHECK.txt` | compileall; `git diff --check` (cfcff3d..HEAD and worktree) | clean |
| `TREES.txt` | six frozen tree SHAs; nothing outside `adapters/` changed; cfcff3d ancestor | unchanged / none / yes |
| `GUARDS.txt` | freeze guard, frozen worktree clean, module-provenance guard | PASS / PASS / PASS (`9a50e370...fdf`) |
| `FREEZE_ORACLE.txt` | oracle freeze/placement check | HARD=1 (tool false positive, below), REVIEW=9, INFO=6 |
| `INVENTORY.txt` | section-18 IDs and skip audit of `ADAPTER_SUITE.txt` | 167/167 IDs; one skip (real symlink) |
| `SECRET_SWEEP.txt`, `SECRET_SWEEP_NOTE.txt` | oracle 166-form sentinel sweep: src, config, README, evidence, tests, remediation git history | no secret anywhere. src: 2 hits, both the known hex-alphabet tool false positive (`authority.py`, as audited; `acquisition.py`, a new instance from R3); config/README 0; evidence 0; tests: the sentinel in test code only; git history: 1 hit, the same R3 line. The note locates and adjudicates every hit |

## Notes

- `FREEZE_ORACLE.txt` HARD `FZ-06 ... credential.py`: the oracle's regex matches the file name prefix `credential`;
  the file is the design-7.5 loader source, byte-identical to `cfcff3d`, and sentinel-free - the same tool false
  positive the earlier audit recorded (`audit_cfcff3d/TEST_RESULTS.md`). REVIEW items: the three TLS fixtures
  (HA-13: release-excluded, unreferenced by production code), no in-repository G0 record (human), and the five
  deliberately named `v05(R<n>)` remediation commit subjects.
- `REPRO_CONTROLLING.txt` was re-run once during this validation after a defect **in the reproduction script** (not
  in the product) was found and fixed: its wrapper reported any probe exception as NOT REPRODUCED. The HA-07 probe
  hit the remediated halt (`AcquisitionHalt: SECRET_ECHO`) and so never judged the durable state. The wrapper now
  reports a third outcome, PROBE ERROR, which fails the run; the HA-07 probe catches the halt and checks the
  completed row and every runtime file (the implementation's scanner and an independent raw-byte search). Diff:
  `scripts/repro_probe_fix_during_final_validation.diff.txt`.
- `NO_NETWORK.txt`: the one ERROR and the one recorded violation are the same deliberate act - the suite's self-test
  `test_the_suite_refuses_any_non_loopback_contact` connects to `192.0.2.1` (TEST-NET-1, never routed) to prove the
  suite's own loopback-only hook raises `RuntimeError`; the oracle's hook, registered first, raises `PermissionError` at
  name resolution instead, so the test errors on the exception type. `NO_NETWORK_NOTE.txt` isolates it: under the
  oracle the same single error and violation (deterministic), without the oracle the test passes (and it passes in
  `ADAPTER_SUITE.txt`). No other test of the 690 made any non-loopback attempt. Not changed (no scope broadening):
  the test is correct for its purpose; it asserts its own guard's exception type.
- The scripts used are kept under `scripts/` as `.txt` (not executable from the evidence tree), including the
  mutation helper (`mutate2.py`) and the mutant definitions of every FINAL group (`muts_<group>.py`), so each
  mutant's exact edit is on record.
- `HASHES.sha256` covers every transcript and script here (not this summary).
- The single skip everywhere is `test_f04_a_link_is_refused` (no symlink privilege): real-symlink certification
  remains OPEN; recipe in `R1/F04_REAL_SYMLINK_RECIPE.md`.

## Mutation notes

Each transcript lists a mutant twice (live, then in the group summary). Per distinct mutant:

- **R1 `a hit keeps its errno (re-anchored)` SURVIVED its R1 group.** R2 rewrote `_scanned_error`; the errno-on-hit
  path has since been pinned by `test_v05_r2_transport_boundary`, not by R1's module. The identical deletion is R2's
  `a key-bearing errno is kept`, KILLED in `MUTATION_R2.txt` [r2_acquisition]. The final suite kills it; at R1 it was
  killed by R1's own tests (`R1/MUTATION.txt`).
- **R3 `clock faults not halted`** survives [r3_acq_legacy] and is KILLED by [r3_acq_clockfault]. This is the same
  pattern `R3/MUTATION.txt` recorded: the dedicated test was added in R3 for exactly this mutant.
- **R3 `verify accepts a scope not pinned before the send` SURVIVED**: equivalent on every reachable state, as
  recorded and reasoned in `R3/MUTATION.txt`. It is reported, not counted as killed.
- **R3 `normalization accepts a capture without a pinned scope` TIMEOUT (39655 s) is a host sleep, not a verdict.**
  System log: AC went offline at 2026-10-01T12:34:25Z (Kernel-Power 105, AcOnline=false). The host entered sleep at
  12:38:45Z (Kernel-Power 42, Reason=0, button/lid) and hibernated at 16:41:55Z (Kernel-Power 42, TargetState=5). It
  resumed on AC at 23:37:46Z (Power-Troubleshooter 1). The helper's duration counts the sleep (39655 s, about 11 h), and
  every other mutant's duration is in its normal range (at most 137 s), so no other verdict spans the gap. The mutant was
  re-run alone with the same helper, module list and MUT_TIMEOUT, under a Windows keep-awake request
  (`scripts/keepawake.py.txt`): baseline PASS, **KILLED (91 s)**, the same verdict R3 recorded (`R3/MUTATION.txt`,
  53 s). `MUTATION_R3.txt` is kept exactly as recorded.
- AC also went offline at 2026-10-02T00:17:31Z during R5, at 82% charge. R5 finished at 00:21:16Z with no sleep
  event.

Totals: R1 15 + 1 (killed by the identical R2 mutant), R2 40/40, R3 33/34 + 1 equivalent, R4 21/21, R5 17/17.
