# T5 local green evidence (N1, N2, N3, O-5, O-1/O-2/O-3; H1, PA-1)

Date: 2026-09-26 (Europe/London)

Base: sealed T4 `ac6b66be9dc119a75a0dfb772890cfd2c3919c52` (tree
`730b931ed8f6b5fa066a60e9de8467f5d6b6ebd7`), through unmodified WIP resume
commits `220c4d0`, `582459b` and `42e46c7c0cbe0eee725172f9f56586c91f8040e5`.
Classification and construction: `T5_AUTHORITY_MEMO.md`. No GO is granted.

Environment for every T5 run below: Windows 11 Pro 10.0.26200, CPython
3.12.10 (64-bit), Git for Windows with system `core.autocrlf=true`. The
repository lives at a OneDrive path; tests and probes ran in short-path
`core.autocrlf=false` clones under `C:\Users\abbot\t5\` whose `src`, `tests`
and `tools` bytes were mirrored from the repository and checked equal before
the gates (MAX_PATH and sync interference are environment hazards, not product
behaviour). The earlier WIP N1 evidence (`N1_*`) was produced under Python
3.13.5/Linux and is retained unchanged.

## Baseline RED on the target platform (`42e46c7`)

`python -m unittest discover -s tests -t . -v` — transcript
`T5_BASELINE_WINDOWS_42e46c7_FULL.txt`: **351 tests, 24 failures, 0 errors**
in 350.603 s. The 24 failures are exactly the pre-existing RED inventory:

- N2 `test_astra_t5_owner_binding`: 13 (five split risk-owned owners, two
  split-registry send phases, kill-switch-hiding split, swapped attribute,
  split market, second order log, shadow release owner, ledger substitution);
- N3 `test_astra_t5_risk_replay_integrity`: 3;
- O-5 `test_astra_t5_approval_ordering`: 4 (three grant modes plus the
  backdated grant);
- O-1/O-2/O-3 `test_astra_t5_package_evidence`: 4.

Every other test passed, including all 70 protected/N1/PA-1 tests (S5 12, R9
11, T3 15, closure 15, IPC 13, lifecycle 4): the WIP N1 work passed its first
Windows / CPython 3.12.10 run.

## Hostile pre-audit RED

- `T5_HOSTILE_H1_RED_WIP.txt` — the new hostile suite on the WIP after the
  N2/N3/O-5/package repairs: 8 tests, 3 failures (H1 in all three forms), 1
  error, 1 skip. The error is a setup mistake in the first version of
  `test_h2_swapped_order_log_cannot_create_bind_or_send` (it copied an order
  log that did not exist yet); the test was corrected and the transcript kept.
- `T5_HOSTILE_RED_ON_T4.txt` — the final hostile suite on sealed T4 source
  (test modules copied in, then removed): 9 tests, 12 failures, 1 error, 1
  skip. Only the positive relocation case passes; H1, both H2 attacks, H4, the
  H5 package cases and H6 fail on T4.

## Retained-test amendments and neutrality

`T5_RETAINED_AMENDMENT_NEUTRALITY.txt`: on sealed T4 the raw-seeded rows are
byte-identical to the rows the pre-T5 API wrote (same record hashes), and the
original and amended S1/T1-dependence modules pass there (15/15). On T5 the
original setups are refused exactly by N3 (`duplicate risk exposure identity`)
and O-5 (`missing or ambiguous approved output binding`); the amended modules
pass (15/15).

## Intermediate runs (history, not sealing gates)

- `T5_INTERMEDIATE_FULL_RUN_1_STOPPED.txt` — stopped and not a valid run: my
  neutrality script swapped test files inside the same clone while it ran. It
  did expose two real issues: the two retained setups above, and an
  intermediate N3 design that added a `validate=` keyword to
  `AppendOnlyJsonl.transaction`, which broke retained T1 release-concurrency
  tests that wrap `transaction` with fixed signatures (their failures are in
  that transcript; an isolated rerun, not retained, showed 4 failures and 1
  error). N3 was redesigned to wrap its builders instead.
- `T5_INTERMEDIATE_FULL_RUN_2_PRE_H1.txt` — separate clone, before H1: 351/351
  OK in 420.752 s.
- A third full run on source bytes before the N1 scan fix and before H6 passed
  359 tests (1 skip) in 400.660 s; it is not retained.

## N1 platform rerun finding (RED first)

`T5_FINAL_GATES_ATTEMPT_1_R9_TIMEOUT.txt` (360 tests: 1 failure, 1 error, both
retained R9) and `T5_FINAL_GATES_ATTEMPT_2_LIFECYCLE_TIMEOUT.txt` (361 tests: 1
error, WIP lifecycle) failed intermittently in full discovery while the
targeted protected set passed. Diagnosis, measurement and repair are in the
memo. `test_astra_t5_worker_scan_cost.py` was RED twice before the final fix
(`T5_N1_SCAN_COST_RED.txt`: 2,974 path resolutions for 112 paths;
`T5_N1_SCAN_COST_RED_2.txt`: 2,975 root checks for 112 paths).
`T5_N1_LATENCY_AB.txt` compares the WIP and T5 workers: unloaded median
`run()` 2.16 s → 0.15 s; the retained lifecycle sequence under eight busy CPU
processes 11/12 failures → 0/12, and under sixteen 0/12 for T5.
`T5_N1_LATENCY_AB_INTERMEDIATE.txt` measured the first partial fix.

## Final sealing gates

Transcript: `T5_FINAL_GATES_GREEN.txt`, 2026-09-26T13:09:28Z to
2026-09-26T13:24:22Z. Input bytes (`src`, `tests`, `tools`) are listed at its
top and were verified unchanged at its end.

```text
python -m unittest -v tests.test_astra_t5_owner_binding tests.test_astra_t5_risk_replay_integrity tests.test_astra_t5_approval_ordering tests.test_astra_t5_package_evidence tests.test_astra_t5_hostile_preaudit
Ran 31 tests in 22.571s
OK (skipped=1)

python -m unittest -v tests.test_astra_s5_process tests.test_remediation_r9_protected tests.test_astra_t3_protected_integrity tests.test_astra_t5_protected_closure tests.test_astra_t5_ipc_request_binding tests.test_astra_t5_worker_lifecycle tests.test_astra_t5_worker_scan_cost
Ran 71 tests in 70.313s
OK

python -m unittest discover -s tests -t . -v        (pass 1 of 2)
Ran 361 tests in 367.934s
OK (skipped=1)

python -m unittest discover -s tests -t . -v        (pass 2 of 2)
Ran 361 tests in 430.030s
OK (skipped=1)

python -m compileall -q src tests tools              exit 0
git diff --check                                     exit 0
git diff --exit-code HEAD -- DECISIONS/ v04_pack/ V04_MIGRATION_PLAN.md config/ requirements.lock pyproject.toml src/genesis/protected.py
                                                     exit 0 (no delta)
```

The only skip is `test_h3_directory_alias_is_the_same_owner_and_file_symlink_is_not`:
this Windows account lacks the symlink privilege (`WinError 1314`). The
T4-inherited duplicate-name `zipfile` warning comes from its hostile tamper
fixture before the verifier rejects that archive.

## Independent auditor probes and stress on the final bytes

The auditor's probes were extracted unmodified from
`GENESIS_V04_T1_T4_INDEPENDENT_HOSTILE_REAUDIT_EVIDENCE.zip` (SHA-256
`785109cb9310136eb72a8d8424fec011c2e6ff1b67e074d7a8a04143d53a91e8`, matching
its sidecar) and run against the final T5 bytes, with sealed T4 alongside for
contrast: `T5_AUDITOR_PROBES_FINAL.txt`, `T5_AUDITOR_STRESS_FINAL.txt`.

- `AUDIT_STRESS_CAMPAIGN.py`: **131/131 OK** in 219.810 s (20× multiprocess append, 3× the retained S5 stress set, 3× the T1 release-concurrency/composition/strategy/mode modules, T2 concurrent publication and the T3 restart case)
- N3 collision probe: the colliding `record_exposure` is refused
  (`duplicate risk exposure identity`); reads and further exposure succeed. T4:
  appended (bricked).
- N2-c split order-log double send: second log refused
  (`owner_authority_mismatch`), `VIOLATION_one_approval_sent_twice=false`, one
  consumption, 7.5 charged. T4: violation.
- Send-fence probes (8 authorities × 2 phases plus split registry): 18/18 OK.
- B1/B2/B3 probes: 9/10; the shadow-owner release (N2-b) now passes (it fails
  on T4). The remaining failure,
  `A1A2Fixed.test_invalid_submission_variants_block`, fails identically on T4
  and is the auditor's recorded setup error (the last sub-case expects PENDING
  to fail after a refused bare VOID, which leaves the reservation valid).
- B6 end-to-end: the positive path and post-bind revocation/tamper/conflict
  cases pass. The O-5 observation probe and the missing/wrong/late/foreign
  negative probe now stop at setup with `RegistryConflict: strategy-output
  approval is missing or mismatched`: O-5 refuses to record a qualification
  without its prior grant, so the backdated-grant scenario cannot be built.
  The foreign-ledger mode, which that probe never reaches, is covered by H6.
- B4/B5 dynamic-import probes: all four B5 variants rejected. The two B4
  probes stop at their first request with the generic protected failure,
  because N1 refuses a program that imports an unhashed helper; no stale-helper
  certificate can exist.

Earlier runs of the same probes and stress campaign on source bytes before the
N1 scan fix are retained as `T5_AUDITOR_PROBES_PRE_N1_SCAN_FIX.txt` and
`T5_AUDITOR_STRESS_PRE_N1_SCAN_FIX.txt` (131/131 OK in 192.030 s).

## Authorities and historical artifacts

ADR bytes (worktree and HEAD Git blob) equal the approved values: ADR-0002
`7e851df9898f3a257a87b602bc1a7f6011ebae1397d42c17b8727c84e554ae00`, approval
`aea4202fae24d928057d22ddeba884ae6ef0cd6b36aa9e8127e9cbdb6ac8cbb6`, ADR-0003
`0fd4c63deb7a8431c41d7869163ccf79ce0295b63b585c8e4c3a0695f1dafaad`, approval
`f5a2556b1b3dfd30a9643f3f68045494bb3eb50564f8db757c1b62373162a5e4`.
`DECISIONS/`, `v04_pack/`, `config/`, `V04_MIGRATION_PLAN.md`,
`requirements.lock`, `pyproject.toml` and `src/genesis/protected.py` are
unchanged from `42e46c7`. All earlier evidence directories, including `N1_*`,
are byte-unchanged; `.gitattributes` only adds `-text` for
`remediation_evidence/T5/*.txt`, so checkout bytes equal hashed bytes and no
existing blob changes.

## Post-commit gate

The integrated package cannot name the T5 commit until it exists. After the
candidate commit: build the v2 package from that exact clean commit in a fresh
`core.autocrlf=false` clone with `--raw-worktree-root remediation_evidence`,
the six S5 historical originals, the four T1–T4 hostile re-audit artifacts and
both ADR authority pins; verify it against Git and in a new empty extraction
directory with `--expect-commit`, `--require-raw-root` and every
`--require-historical` pin; run the auditor's B8 tamper suite against it; and
record commit/tree/package/manifest/sidecar hashes externally without amending
the commit.

## Truthful disposition

T5 locally repairs N1, N2, N3, O-5 and O-1/O-2/O-3, plus H1 and PA-1 found
during its own hostile review. Local tests, probes and packaging are not
independent hostile approval. Genesis remains **HOLD / adapter NO-GO**; no
adapter, shadow research, protected campaign or live-money work is
authorized, and no strategy, model, tier, TTL or human approval was created.
