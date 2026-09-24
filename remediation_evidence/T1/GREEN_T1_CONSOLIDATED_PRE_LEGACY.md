# Consolidated T1 gate before legacy-v2 proof repair

Date: 2026-09-24

Command:

```powershell
python -m unittest tests.test_astra_t1_dependence tests.test_astra_t1_portfolio tests.test_astra_t1_release tests.test_astra_t1_release_proof tests.test_astra_t1_release_integration tests.test_astra_t1_release_concurrency tests.test_astra_t1_strategy tests.test_astra_t1_mode tests.test_astra_t1_composition -q
```

Exact result:

```text
----------------------------------------------------------------------
Ran 66 tests in 168.461s

OK
```

This closes only the consolidated B1/B2/B3/B7 test set at the current
uncommitted checkpoint. It does not close the retained/full-suite gate, the
separate legacy-v2 settlement-proof conflict, or any GO status.
