# T3 / B4+B5 final green evidence

Date: 2026-09-25 (Europe/London)

Base commit: `4214f38886d5046f76a3fa8002889f02a701187f`

Base tree: `31f00dabaaf320835f8aaf7d041ab5c75bc1b83c`

Scope: B4 and B5 only. The authority classification and exact construction are
in `T3_B4_B5_AUTHORITY_MEMO.md`. B8 remains open. No GO is granted.

## RED-before

The original, unmodified Astra B4/B5 probes ran against sealed T2 through the
real worker and produced two intended assertion failures, zero errors. B4
certified the new digest while returning cached-old Brier `0.01` instead of
`0.25`; B5 certified raw labels reachable through an object. Exact command and
output: `ORIGINAL_B4_B5_RED_T2.txt`.

The independent test module then ran before production changes on sealed T2:
12 tests, ten explicit invariant assertion failures, zero errors, with two legal
controls already green. Exact command and output:
`INDEPENDENT_B4_B5_RED_T2.txt`. The final thirteenth outside-root case is a
post-RED hardening control and is not misrepresented as part of that RED count.
Pre-seal diff review then found class state reachable through an empty instance
and a from-imported class. Both additional methods were assertion-based RED on
sealed T2 and the then-current worker, with zero errors; exact evidence is in
`CLASS_STATE_RED_T2_AND_CURRENT.txt`. No failed transcript was overwritten.

## Targeted T3 GREEN

Command:

```text
python -m unittest tests.test_astra_t3_protected_integrity -q
```

Exact terminal result:

```text
----------------------------------------------------------------------
Ran 15 tests in 12.637s

OK
```

The tests cover exact verified-byte execution, no cached callable across
identities, sequential changed-module execution, import-time path mutation,
ambiguous/outside origins, stale references, object dictionaries, slots,
function attributes, custom imported holders, deep collections/cycles, opaque
capabilities, program-defined class state, from-imported class holders, legal
label-free programs, and nonrefundable restart behavior.

## Original hostile probes GREEN

Command:

```text
python -c "import runpy,unittest; p=runpy.run_path(r'..\\..\\outputs\\GENESIS_V04_S5_ASTRA_PROBES.py',run_name='astra_t3_final'); c=p['NewInvariants']; s=unittest.TestSuite([c('test_b4_cached_module_cannot_impersonate_changed_program_bytes'),c('test_b5_raw_label_inside_object_is_rejected')]); x=unittest.TextTestRunner(verbosity=1).run(s); print('B4_SECOND_BRIER='+str(p['OBSERVATIONS']['B4']['second_certificate']['metrics']['brier'])); print('B5_OBSERVATION='+repr(p['OBSERVATIONS'].get('B5'))); print('RUN='+str(x.testsRun)+' FAILURES='+str(len(x.failures))+' ERRORS='+str(len(x.errors))); raise SystemExit(not x.wasSuccessful())"
```

Exact final result: 2 tests in 1.543s, `OK`, `FAILURES=0`, `ERRORS=0`. B4's second
certificate has Brier `0.25`; B5 records `{'blocked': True}`.

## Retained protected/isolation GREEN

Command:

```text
python -m unittest tests.test_astra_s5_process tests.test_remediation_r9_protected tests.test_protected_evaluation_and_logging -q
```

Exact terminal result:

```text
----------------------------------------------------------------------
Ran 25 tests in 27.118s

OK
```

This retains distinct PID/address-space execution, sealed launch/IPC, parent
label isolation, exact requests and frames, output suppression, attempt quota,
crash/restart/non-refund, concurrency and real-campaign disablement.

## Complete repository GREEN

Command:

```text
python -m unittest discover -s tests -t . -q
```

Exact terminal result:

```text
----------------------------------------------------------------------
Ran 288 tests in 178.191s

OK
```

Compilation command and exact output:

```text
python -m compileall -q src tests
```

Exit code: 0. Output: empty.

The first compact targeted rerun inside the restricted sandbox was unable to
create its isolated system-temp label files and ended with 13 setup permission
errors. No invariant ran or failed. The immediately repeated permitted run is
the earlier 13/13 result; the final expanded 15/15 run is recorded above. This
infrastructure event did not alter source or tests.

## Identity and scope integrity

- Approved ADR-0003 SHA-256 remains
  `0fd4c63deb7a8431c41d7869163ccf79ce0295b63b585c8e4c3a0695f1dafaad`.
- Approval-note SHA-256 remains
  `f5a2556b1b3dfd30a9643f3f68045494bb3eb50564f8db757c1b62373162a5e4`.
- `ResearchProgramRef-v1`, its canonical preimage and every historical program
  digest are unchanged. Candidate-v1/v2/v3, binding-v1 and all T2 identity
  controls remain green through the complete suite.
- The only production file changed by T3 is
  `src/genesis/protected_research_worker.py`; program topology, campaign,
  certificate, frame, attempt and activation contracts are unchanged.

## Truthful disposition

B4/B5 are locally repaired and reviewable as one independent T3 checkpoint.
This is not hostile approval. B8 and the overall HOLD remain. No real strategy,
adapter, shadow research, protected campaign or live-money GO is granted.
