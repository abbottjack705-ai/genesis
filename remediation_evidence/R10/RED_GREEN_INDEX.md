# RED-before / GREEN-after index

## R0 global hostile reproduction

The untouched audited snapshot was probed before production changes:

- script: `remediation_evidence/R0/red_before_probe.py`;
- structured result: `remediation_evidence/R0/red_before_result.json`;
- result: `ALL_EXPECTED_UNSAFE_BEHAVIOURS_REPRODUCED`;
- findings: F01 through F15, including an observed F12 append-chain fork.

This separate probe preserved the green original suite. R1 through R6 use these
retained observations as their RED-before basis, then record their targeted/full
GREEN results in `R1_CHECKPOINT.md` through `R6_CHECKPOINT.md`.

## Exact later-batch detached probes

| Batch | Clean pre-fix checkpoint | RED evidence | GREEN evidence |
|---|---|---|---|
| R7 | `8bb86f3` | `R7/RED_BEFORE.md`: exact seven-test module non-green (2 failures, 5 errors) | `R7/GREEN.md`, `R7_CHECKPOINT.md`: 7/7 targeted, 82/82 full |
| R8 | `b1f22e5` | `R8/red_before_probe.py`, `R8/RED_BEFORE.md`: double subtraction, fake cache, 8/8 daily race admission | `R8/GREEN.md`, `R8_CHECKPOINT.md`: 14/14 targeted, 96/96 full |
| R9 | `d486297` | `R9/red_before_probe.py`, `R9/RED_BEFORE.md`: direct/callback label recovery, callback in label PID, 2/2 final-attempt admission | `R9/GREEN.md`, `R9_CHECKPOINT.md`: 11/11 targeted, 107/107 full |

The detached worktrees were removed after evidence capture; no frozen checkpoint
was modified.

## R10 integrated verification

R10 introduces no new finding or production remediation and therefore does not
claim a fictional RED. It adds green integration evidence for gaps that were
already closed:

- process death inside the append transaction;
- every defined order restart state;
- every defined risk exposure replay state;
- 20 repeated F12 multiprocess runs;
- repeated cross-component concurrency/fault campaigns;
- legacy-route reachability scan.

The final full suite is 110/110 and compileall is green.
