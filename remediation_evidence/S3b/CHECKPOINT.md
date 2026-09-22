# S3b / Astra A4 evidence checkpoint

Date: 2026-09-22 UTC.

Authority: approved `ADR-0002 v1`, SHA-256
`7e851df9898f3a257a87b602bc1a7f6011ebae1397d42c17b8727c84e554ae00`.
Audited sealed base: `166f9230a0fb773cad2ac3619b5f98989d78a818`.
Immediately preceding S3a green base:
`4f04c0a7a996250480d870ecae920a03812e894d`.

## RED before implementation

The final independent test sources were loaded from the S3b worktree while
`genesis` production modules were loaded from each named clean worktree. Each
transcript prints the resolved production module path and exact baseline SHA.
The same 23 tests failed with 43 invariant assertions on each baseline. There
were no import, collection or setup errors.

Test source hashes:

- `test_astra_s3_output.py`:
  `df9666a20aadc6d3b0d501de38527c757a3a3485afeeab9b35527e65b7ef64f7`
- `test_astra_s3_v3_adversarial.py`:
  `d0e0a73ef8f7d753628f1125f1e3470e3c88975564f34bbbaaaa8356afb28528`

Transcript hashes:

- `RED_FINAL_166F923.txt`:
  `3e4f6764bc2044a8641f9a47878b4b7785ed8d9d00ef18caa5a264649c29e05a`
- `RED_FINAL_S3A_HEAD.txt`:
  `479c5134d6a7ac3e7b642591b4355fe40c0809c21c6f3a6ed408085eaf95d0d3`

The command form used for both clean worktrees was:

```text
python -c "import sys,unittest,subprocess; from pathlib import Path; import tests; base=Path(r'<resolved-clean-worktree>'); sys.path.insert(0,str(base/'src')); import genesis; print('BASE_SHA',subprocess.check_output(['git','-C',str(base),'rev-parse','HEAD'],text=True).strip(),flush=True); print('GENESIS_SOURCE',genesis.__file__,flush=True); suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_astra_s3_output','tests.test_astra_s3_v3_adversarial']); result=unittest.TextTestRunner(verbosity=1).run(suite); sys.exit(not result.wasSuccessful())"
```

The earlier incremental RED transcripts are retained unchanged. They document
the initial copied-output failures before the final adversarial set was closed.

## GREEN after implementation

Commands and results:

```text
python -m unittest tests.test_astra_s3_manifest tests.test_astra_s3_output tests.test_astra_s3_v3_adversarial tests.test_remediation_r3_qualification tests.test_remediation_r4_ranking -v
51 tests passed in 84.199s

python -m unittest tests.test_astra_s1_reservation tests.test_astra_s1_submission tests.test_astra_s2_admission tests.test_astra_s2_replay tests.test_remediation_r5_risk tests.test_remediation_r6_execution tests.test_remediation_r7_settlement tests.test_remediation_r8_quota tests.test_remediation_r9_protected tests.test_remediation_r10_integration -v
81 tests passed in 60.976s

python -m unittest discover -s tests -t . -v
173 tests passed in 97.162s

python -m compileall -q src tests
PASS
```

Transcript hashes:

- `GREEN_TARGETED.txt`:
  `f3632792e58c934d10356fc23ac313a8b7263e5b6107c486211a0dde6cd743c5`
- `GREEN_RETAINED.txt`:
  `5b0098ad409b7953ba5c5c30f39028390d182f8f9f31ad23ab90cdcffb104464`
- `GREEN_FULL.txt`:
  `25e86959fcdb65aa16ff63b46047a17e9f8347218a6a2d3a80f676ee677c65f2`
- `GREEN_COMPILEALL.txt`:
  `7ce159b3c681b0631e9fbfa517de026d89af37302db17ed25ad70e7484a0443a`

## Scope and disposition

This checkpoint locally closes A4 under the approved ADR. Candidate-v3 binds
the exact manifest, evidence pack, decision contract and trusted immutable
decision output. New qualification, risk and order actions require the v3
lineage and an active rule binding with a separate operator approval. Existing
candidate-v1/v2 identities and historical records remain unchanged and
readable; old sent/matched histories may complete settlement.

No strategy-specific model, calibration, tier formula/cutoff, expiry duration,
adapter, shadow campaign or live path is approved. Operational qualification
therefore remains fail-closed. A6 and A8 remain open, and the overall Astra
disposition remains HOLD pending their remediation and a fresh hostile audit.
