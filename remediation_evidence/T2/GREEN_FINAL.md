# T2 / B6 final green evidence

Date: 2026-09-25 (Europe/London)

Base commit: `d130c21668b769c371cfa4a4a75c3f382af1af71`

Base tree: `15253d9c3b8e474509e05d43f10db04b7b949b4a`

Scope: B6 only. The authority classification and exact construction appear in
`T2_B6_DECISION_MEMO.md`. B4, B5 and B8 remain open. No GO is granted.

## RED-before

The original unmodified Astra B6 probe ran against sealed T1 through the real
production validator and failed its intended assertion: 1 run, 1 failure, 0
errors. Exact command/output: `ORIGINAL_B6_RED_T1.txt`.

The independent T2 module then ran on sealed T1 before production changes: 7
tests, 5 explicit invariant assertion failures, 0 errors; the historical v1 and
golden identity controls already passed. Exact command/output:
`INDEPENDENT_B6_RED_T1.txt`.

Neither failed transcript was overwritten.

## Targeted B6 GREEN

Command:

```text
python -m unittest tests.test_astra_t2_b6_approval
```

Exact output:

```text
.......
----------------------------------------------------------------------
Ran 7 tests in 0.433s

OK
```

This covers the real unmodified-validator positive workflow, missing/wrong/
future/tampered/revoked grants, wrong binding and scope, absent authority,
restart/idempotent replay, concurrent publication, legacy-v1 resolution, and
golden historical candidate-v1/v2/v3 plus binding-v1 hashes.

## Retained impacted GREEN

Command:

```text
python -m unittest tests.test_remediation_r3_qualification tests.test_astra_s3_output tests.test_astra_s3_v3_adversarial tests.test_remediation_r5_risk tests.test_remediation_r6_execution tests.test_astra_t1_composition tests.test_astra_t1_dependence
```

Exact terminal result (65 progress dots preceded the separator):

```text
----------------------------------------------------------------------
Ran 65 tests in 38.605s

OK
```

An earlier sandboxed verbose run reached 64 passing tests but Windows denied
creation of a multiprocessing pipe before the remaining unchanged test body.
The exact isolated permitted rerun passed. That infrastructure transcript is
preserved in `RETAINED_SANDBOX_FAILURE_AND_RERUN.txt`.

## Complete repository GREEN

Command:

```text
python -m unittest discover -s tests -t .
```

Exact terminal result (273 progress dots preceded the separator):

```text
----------------------------------------------------------------------
Ran 273 tests in 165.800s

OK
```

The full discovery includes all retained R0–R10, S1–S5, T1 release/legal-path,
restart, concurrency, crash, PID/IPC, quota and protected-isolation tests.

Compilation command and exact output:

```text
python -m compileall -q src tests
```

Exit code: 0. Output: empty.

Diff-integrity command:

```text
git diff --check
```

Exit code: 0. Output contained only Git's Windows LF-to-CRLF working-copy
warnings; no whitespace error was reported.

Frozen-authority integrity command:

```text
git diff --exit-code HEAD -- DECISIONS/ADR-0002-s3-manifest-and-candidate-v3.md DECISIONS/ADR-0002-v1-approval-2026-09-22.md src/genesis/decision.py
```

Exit code: 0. Output: empty. ADR-0002 remains SHA-256
`7e851df9898f3a257a87b602bc1a7f6011ebae1397d42c17b8727c84e554ae00`.

`HASHES.sha256` was independently re-read and checked after creation:
`HASH_MANIFEST_OK entries=17`.

## Truthful disposition

B6 is locally repaired and reviewable as an independent checkpoint. The old
impossible v1 cyclic construction remains rejected and preserved as historical
RED; new v2 references are acyclic and version-disjoint. No real strategy
authority was created. Genesis remains HOLD / adapter NO-GO pending B4/B5/B8,
an integrated hostile re-audit, and explicit review.
