# T1 B1/B2/B3/B7 RED-before evidence — 2026-09-23

Audited source baseline and immediate pre-fix production HEAD:
`27dd525c1fd7d531c4833c4bf7e44204a9345f19`. The separate detached
`work/t1-red-baseline` worktree is at that exact commit. Only the four new
untracked test files were copied into that worktree; no baseline production
file was edited. The source worktree's production files also remain at the
same HEAD. The original post-S5 failed probe packet is untouched.

Final independent test-source SHA-256 values:

| Test file | SHA-256 |
| --- | --- |
| `tests/test_astra_t1_dependence.py` | `8c96ac7c48d32744046cf8505f2380381366fbb0797525e580c77670e3a78a13` |
| `tests/test_astra_t1_portfolio.py` | `8aac1ccbaef4c781199766ee93042ecb38582a0259d3ec4cff2ea82613f6ca92` |
| `tests/test_astra_t1_release.py` | `b5a56d481ceb58e965d7f11ca264a7bb229cb9a207627ffcb65ffa5606ea9503` |
| `tests/test_astra_t1_strategy.py` | `26be3333a41cfad4cfdffc4eccd2efde19672de77c4516114e1ac7d5b6c76a01` |

Run from `work/t1-red-baseline`:

```powershell
python -m unittest tests.test_astra_t1_dependence tests.test_astra_t1_portfolio tests.test_astra_t1_release tests.test_astra_t1_strategy -v 2>&1 | Tee-Object -FilePath '..\genesis-remediation\remediation_evidence\T1\red_baseline_final.txt'; $testExit=$LASTEXITCODE; Write-Output "EXIT_CODE=$testExit"; exit $testExit
```

The command exited **1**: 28 test methods, 29 invariant assertion failures
(including subtests), zero errors/import/setup failures. Positive
characterization cases remain green. The exact transcript is
`red_baseline_final.txt`, SHA-256
`91726254d1cb6dbc6c407a7f43bad5642fec6dc3284585901256f19cc2cddf9e`.
Earlier partial RED transcripts (`red_baseline_partial.txt` and
`red_baseline_all.txt`) remain retained without replacement.

The original independent Astra B1/B2/B3/B7 tests were also rerun against
the same pre-fix `27dd525` source without invoking the script's `__main__`
write of its historical observations file. Exact command from the task root:

```powershell
python -c "import runpy,unittest; g=runpy.run_path(r'outputs\GENESIS_V04_S5_ASTRA_PROBES.py'); cls=g['NewInvariants']; names=('test_b1_risk_uses_output_correlation_not_caller_omission','test_b2_new_submission_rechecks_current_total_exposure','test_b3_release_requires_terminal_order_or_settlement_proof','test_b7_strategy_withdrawal_is_fenced_through_send'); suite=unittest.TestSuite(cls(n) for n in names); result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(not result.wasSuccessful())" 2>&1 | Tee-Object -FilePath 'work\genesis-remediation\remediation_evidence\T1\red_original_B1_B2_B3_B7.txt'; $testExit=$LASTEXITCODE; Write-Output "EXIT_CODE=$testExit"; exit $testExit
```

Exit **1**: four original tests, four invariant assertion failures, zero
errors. Transcript `red_original_B1_B2_B3_B7.txt`, SHA-256
`c92e9d9e05fc04f83cc8f9bbf3b3303fccd310ff62c64bea421efb94991a180e`.
This command used the main pre-fix worktree (also exactly `27dd525`), while
the independent test command above used the detached baseline worktree.

No GREEN or checkpoint claim is made here. The audited source remains HOLD.
