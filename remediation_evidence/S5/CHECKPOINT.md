# S5 / Astra A8 green checkpoint

Date (Europe/London): 2026-09-23

Audited checkpoint preserved: `166f9230a0fb773cad2ac3619b5f98989d78a818`.

Immediately preceding green checkpoint: S4/A6
`0032ee76f6a5137a70a22b79b1207c9554e37694`.

## Decision authority

ADR-0003 v1 was explicitly approved exactly as drafted on 2026-09-22.

- ADR: `DECISIONS/ADR-0003-s5-protected-process-boundary.md`
- approved SHA-256:
  `0fd4c63deb7a8431c41d7869163ccf79ce0295b63b585c8e4c3a0695f1dafaad`
- approval note: `DECISIONS/ADR-0003-v1-approval-2026-09-22.md`
- approval-note SHA-256:
  `f5a2556b1b3dfd30a9643f3f68045494bb3eb50564f8db757c1b62373162a5e4`

The approval grants no adapter, shadow-research, protected-campaign or
live-money GO and approves no model, calibration, strategy, tier/expiry rule or
profitability claim.

## RED-before

The final 12-method hostile source SHA-256 is
`81b46756abe12b211f8e6200c2c9b1b450e2e375d93c10da4dd56e73e8db09da`.
`RED_BEFORE.md` preserves the exact baseline commands.

- clean `166f923`: 12 failing invariant assertions, 0 errors;
  `RED_166F923.txt` SHA-256
  `36b90a4311d1167ece0e7e2d064d024d19d2be83cbdb3eaed23d34e544ec7edc`
- clean S4 `0032ee7`: the same 12 failing invariant assertions, 0 errors;
  `RED_S4_HEAD.txt` SHA-256
  `26f05a16b4cc5a9671824367157f6531f09a49c4daf578af6c0e057d4dd44ddb`

The retained-label attack produced Brier 0.3229 rather than the label-free
0.01 on both pre-fix bases. No setup/import failure is counted as RED.

## GREEN gates

Targeted hostile plus retained R9:

```text
python -m unittest tests.test_astra_s5_process tests.test_remediation_r9_protected -v
```

Result: 23/23, 59.516 seconds. Transcript SHA-256:
`a1787a120a5688991807e918e39a5e79cff470dd5dde6e0fd231f74f4d3cf299`.

The explicit retained gate invoked every pre-S5 test module (R0-R10 and
S1-S4), excluding only `tests.test_astra_s5_process`.

```text
python -m unittest tests.test_accounting tests.test_astra_s1_reservation tests.test_astra_s1_submission tests.test_astra_s2_admission tests.test_astra_s2_replay tests.test_astra_s3_manifest tests.test_astra_s3_output tests.test_astra_s3_v3_adversarial tests.test_astra_s4_cache tests.test_config tests.test_evidence tests.test_protected_evaluation_and_logging tests.test_registry_and_selection tests.test_remediation_r1_persistence tests.test_remediation_r10_integration tests.test_remediation_r2_causal_evidence tests.test_remediation_r3_qualification tests.test_remediation_r4_ranking tests.test_remediation_r5_risk tests.test_remediation_r6_execution tests.test_remediation_r7_settlement tests.test_remediation_r8_quota tests.test_remediation_r9_protected tests.test_reproducibility tests.test_time_and_labels tests.test_v04_foundation -v
```

Result: 184/184, 0 failures/errors. The transcript reports 39174.655 seconds
because the Codex host/session was paused overnight while the process remained
attached; that value is not represented as active test runtime. Transcript
SHA-256:
`c8c1c4d0971efda899232e9831947477727d5dedd6843a88c6974197b806b191`.

Mandatory independent discovery:

```text
python -m unittest discover -s tests -t . -v
```

Result: 196/196, 288.095 seconds. Transcript SHA-256:
`d10cb16f8a6bc95b9a0569639eea668a84101d1bbaa570bc6406da846aa71abc`.

Compilation:

```text
python -m compileall -q src tests
```

Result: PASS. Transcript SHA-256:
`b0ea90ab239896fa004eee4145db777673e97ed6f3d2c8c74ac81442e4b30723`.

## Source identities

- `src/genesis/protected.py`:
  `1cfa2a1042ea3a08b7ebfce5275cc26fe86233bb5a6cb2d6903ea5f7baedf5a1`
- `src/genesis/protected_research_worker.py`:
  `042ccce13ddf60c4e51d8b55664e5a9a99dff1305b605e79dad827cd83d3df80`
- retained R9 tests:
  `96b9a6cdc0562fbbb88e8e169ee21fb498c54d7aec10803ebb2eedbcb354799d`
- label-bearing adversary module:
  `f8eb1bfdfa84991386adc2fb2e5b411d0b859a596a8b425af6e96f0c6123a67a`

## Locally closed invariant

An accepted registered research program is an exact hashed top-level stateless
reference and executes only in a separately spawned isolated process. That
process starts before protected labels are materialized and before evaluator
IPC is created, receives only sealed label-free frames, and receives no label,
label root/store/path or evaluator endpoint. The trusted label-owning evaluator
is a distinct process and executes no research callback. Research
failure/timeout/crash consumes the reserved attempt and returns only a generic
failure; concurrency cannot exceed the final attempt.

This is local A8 closure, not audit approval. Real protected activation remains
guarded. The overall Astra disposition remains HOLD pending fresh independent
hostile re-audit and explicit checkpoint review.
