# T1 B1/B2/B3/B7 final green evidence

Date: 2026-09-24
Audited base/HEAD before commit:
`27dd525c1fd7d531c4833c4bf7e44204a9345f19`

All commands ran from `work/genesis-remediation`. Windows process gates were
run with the required host permissions; no test was skipped.

## Original hostile reproductions with repaired outcomes

```powershell
python -m unittest tests.test_astra_t1_dependence.AstraB1DependenceTests.test_d01_original_shared_cluster_caller_omission_cannot_approve tests.test_astra_t1_portfolio.CurrentPortfolioSubmissionTests.test_original_late_55_blocks_fresh_recertification_and_sent_append tests.test_astra_t1_release.AstraB3ReleaseTests.test_l01_sent_order_bare_settled_cannot_release_full_envelope tests.test_astra_t1_strategy.AstraStrategyFenceTests.test_true_read_then_committed_withdrawal_cannot_append_new_action -v
```

Result: **4/4 passed**, 0 failures/errors, 10.831 seconds.

## Consolidated T1 gate

```powershell
python -m unittest tests.test_astra_t1_dependence tests.test_astra_t1_portfolio tests.test_astra_t1_release tests.test_astra_t1_release_proof tests.test_astra_t1_release_integration tests.test_astra_t1_release_concurrency tests.test_astra_t1_legacy_release tests.test_astra_t1_strategy tests.test_astra_t1_mode tests.test_astra_t1_composition -q
```

Exact result:

```text
----------------------------------------------------------------------
Ran 70 tests in 207.941s

OK
```

## Retained R0–R10 and S1–S5 gate

The explicit retained command named the 27 pre-T1 modules from
`tests.test_accounting` through `tests.test_astra_s5_process`.

Exact result:

```text
----------------------------------------------------------------------
Ran 196 tests in 364.446s

OK
```

## Full repository suite

```powershell
python -m unittest discover -s tests -t . -v
```

Exact result:

```text
----------------------------------------------------------------------
Ran 266 tests in 865.285s

OK
```

## Explicit restart/concurrency/crash gate

```powershell
python -m unittest tests.test_astra_t1_release_concurrency tests.test_astra_t1_legacy_release tests.test_astra_s1_submission tests.test_astra_s2_admission tests.test_remediation_r10_integration tests.test_remediation_r1_persistence -q
```

Exact result:

```text
----------------------------------------------------------------------
Ran 36 tests in 228.924s

OK
```

## Static gates

```powershell
python -m compileall -q src tests
git diff --check
```

Both exited 0. `compileall` produced no output. `git diff --check` reported no
whitespace errors; Git emitted only expected LF→CRLF working-copy notices.

After the four checkpoint documents and final diff-review evidence were
updated, the four original hostile fixed-outcome tests were rerun once more:
**4/4 passed**, zero failures/errors, 10.637 seconds. A final
`python -m compileall -q src tests` and `git diff --check` again exited 0;
only the expected LF→CRLF notices were printed.

## Final source identities before commit

| File | SHA-256 |
|---|---|
| `registry.py` | `4DECA4AD79CF002BB78F92FE858FB923C098A7B61DD0115F26D533DCB3FD983E` |
| `risk.py` | `D8F451AA11AFF026015AEEA9E2528F9CE3D7953843726B52DDB49666548483E3` |
| `execution.py` | `132A876177905C725233014ACE7D5DC18F334FA53C15042F29B23D87778648E5` |
| `release_proof.py` | `244FBC82A8C9E7F048E6962D8395541E7086BDD287A7F395F2ECF873D75D9358` |
| `test_astra_t1_dependence.py` | `AA045C5ADA121FEA9922B1E00EA4E37EBB80BFA67813620374BE5A175F789EA7` |
| `test_astra_t1_portfolio.py` | `8AAC1CCBAEF4C781199766EE93042ECB38582A0259D3EC4CFF2EA82613F6CA92` |
| `test_astra_t1_release.py` | `B5A56D481CEB58E965D7F11CA264A7BB229CB9A207627FFCB65FFA5606EA9503` |
| `test_astra_t1_release_proof.py` | `74DB34805F20C5DB768EF403684E5D46674111B277A40407B2592B447D4B865F` |
| `test_astra_t1_release_integration.py` | `AE7B1318A75A5D7ABDD42B6B10A57F23DFCB248C6897A7F4FD778CAA80CDC4F7` |
| `test_astra_t1_release_concurrency.py` | `CC7C322FE73B01A37A9BF7E87C628EC0AF3C58133FD2CA5FE6F4EEF763355ED7` |
| `test_astra_t1_legacy_release.py` | `A9241C3998C13DBA19317BD3B7F03D8AF6D0E06996AEBF3B16D2CB58157A9E6A` |
| `test_astra_t1_strategy.py` | `26BE3333A41CFAD4CFDFFC4ECCD2EFDE19672DE77C4516114E1AC7D5B6C76A01` |
| `test_astra_t1_mode.py` | `6E5F3D8B229E4753598B1A79A07D2CB5B848DE2ABF28A27F7160F30C15E04CB1` |
| `test_astra_t1_composition.py` | `5F781F0E332B6EE0119C0B43923526E451402BDB7C2238EC49B3EEA3EDF9B724` |

These results establish a local T1 checkpoint only. B4/B5/B6/B8 and the
overall post-S5 hostile-audit HOLD remain. No adapter, strategy, protected
campaign, shadow-research or live-money GO is granted.
