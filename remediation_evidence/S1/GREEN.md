# S1 GREEN checkpoint — A1+A2 only

Date: 2026-09-22. Status: **locally green, partial audit remediation; A3–A8 remain HOLD**.

## Change and invariant

`PaperExecutionAdapter.transition` now performs fresh authority-derived recertification inside the actual `SUBMISSION_PENDING` and `SUBMISSION_SENT` order transaction. It verifies an exact consumed approval/order/candidate/side/stake/liability/odds binding. `RiskEngine.approval_still_valid` requires the exact active PENDING reservation, rejects own or other UNKNOWN, terminal release, missing reservation and conflicting duplicate reservation identity. Submission takes the existing SQLite locks for risk, bankroll, safety, market and refresh logs through JSONL order fsync/commit, so cooperating writers cannot change those heads between check and append. The PAPER-only intent, one candidate/one order lineage, consumed history, restart ambiguity, risk percentages and R7 settlement are preserved. This does **not** close A3 unsupported active replay or A7 risk *admission* serialization; the abstract strategy view has no independent durable writer/fencing contract here.

An original foundation test incorrectly expected submission despite `material_change=True`. It now asserts the block and still verifies timeout→UNKNOWN→reconciliation in a separate genuinely valid paper fixture. No regression was deleted.

## Exact commands and results

| Gate | Command | Result / transcript |
|---|---|---|
| New targeted | `python -m unittest tests.test_astra_s1_submission tests.test_astra_s1_reservation -v` | Exit 0; **13/13**; `GREEN_TARGETED.txt` |
| Retained R5/R6/R7/R10 | `python -m unittest tests.test_remediation_r5_risk tests.test_remediation_r6_execution tests.test_remediation_r7_settlement tests.test_remediation_r10_integration -v` | Exit 0; **27/27**; `GREEN_R5_R6_R7_R10.txt` |
| Full regression | `python -m unittest discover -s tests -t . -v` | Exit 0; **123/123** in 38.344s, run outside sandbox after a Windows pipe denial; `GREEN_FULL_SUITE_ESCALATED.txt` |
| Compilation | `python -m compileall -q src tests` | Exit 0, no diagnostics |
| Source/documentation diff check | `git diff --cached --check -- . ':(exclude)remediation_evidence/S1/RED_BASELINE.txt'` | Exit 0. The unmodified RED unittest transcript itself contains five runner-generated trailing spaces on `...` progress lines; a whole-staged-tree check reports those five evidence lines, not source whitespace errors. The exact RED output is preserved. Git also emitted LF→CRLF advisory warnings. |
| Original Astra probe | `python ..\..\outputs\GENESIS_V04_ASTRA_AUDIT_PROBE.py --repo .` | Expected exit 1: its unmodified first kill-switch case now raises `RegistryConflict: submission recertification blocked: risk_or_safety_state_blocked`; `ORIGINAL_ASTRA_PROBE_BLOCKED.txt`. The original probe aborts at the first safe block, so the independent S1 tests cover the other original cases individually. |

The first sandboxed full run is retained as `SANDBOX_FULL_SUITE_FAILED.txt`. Its nine unchanged R9 Windows `multiprocessing.Pipe` cases raised `PermissionError [WinError 5]`; the tenth failure was the outdated legacy A1 expectation noted above. The later full run outside the sandbox passed all 123 tests. This transcript is not represented as a code defect or silently discarded.

## SHA-256 evidence map

| File | SHA-256 |
|---|---|
| `RED_BASELINE.txt` | `0178fb3c29c42099134a951de3847a0f6ba293d3cdfe8f9cd7f8e7f6c2bd4983` |
| `GREEN_TARGETED.txt` | `ae2d23a9c7a494a688d8f2a188252916b2dbe81932752ad5ff434697301b91ae` |
| `GREEN_R5_R6_R7_R10.txt` | `13110c5e4a112d289e68af7edbdb5eaa85f1a289464c53c110ed1345cfc4e5c3` |
| `GREEN_FULL_SUITE_ESCALATED.txt` | `dd1c844ad2ee2dff8f126a74691ac81fe3d942540d6f39507f2ac0209eee8730` |
| `SANDBOX_FULL_SUITE_FAILED.txt` | `3389d948d18af14f7f240c7d3fd29e1d7da732ea56fa71ccd52c3386e71e3954` |
| `ORIGINAL_ASTRA_PROBE_BLOCKED.txt` | `25a18751456b8c9e455167ca2572dfe8db863c88cf038c07f82c0e7b5b6bb2f0` |
| `src/genesis/execution.py` | `b1776b9c4eb4dd432157b8a6113f184a24bb8ec51613ebda6bb8b49c52159b6a` |
| `src/genesis/risk.py` | `27aa26e9a5c1c0b7731d41699c1db1969eb3c675fd516ed142616871159e4646` |
| `src/genesis/registry.py` | `76b9a601b4b5a48dab91286ebd62d47f1f37d68e3e88bd8d252d2326b0fe443e` |
| `tests/test_astra_s1_submission.py` | `2a39404b2eea23e57b749669e4f0f3dd9e9b926677708ba35f1fbf4ad98e520b` |
| `tests/test_astra_s1_reservation.py` | `bc3400f3d890c6c477625a2f1f6433cd22456e0978af125c6fa6e536d3115706` |
| `tests/test_v04_foundation.py` | `15243398ef266734a3cb5c89dd4868b4a9daac97e702e11f675db618873a310c` |

Review next: S2 A3+A7, then A4+A5, A6, A8 in Astra's binding order, each with new RED against `166f923`. Do not treat this local checkpoint as adapter, substantive shadow-research or live-money GO.
