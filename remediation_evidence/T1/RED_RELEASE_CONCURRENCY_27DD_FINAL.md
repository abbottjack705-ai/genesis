# B3 release/concurrency final RED-before evidence

Date: 2026-09-23

This is the final rerun after strengthening the deterministic race to prove
that the second operation entered the contended risk transaction, remained
blocked until the first commit, and produced the corresponding risk-log
sequence. The earlier transcript and note are retained unchanged as
historical evidence.

Production source was the clean detached checkpoint
`27dd525c1fd7d531c4833c4bf7e44204a9345f19` in
`work/t1-red-baseline`. The finalized test was loaded read-only from the main
worktree; no detached production or retained test was modified.

Exact command, run from `work/t1-red-baseline`:

```powershell
python -c "import importlib.util,pathlib,sys,unittest; sys.path.insert(0,str(pathlib.Path.cwd()/'src')); import genesis; p=pathlib.Path(r'C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\genesis-remediation\tests\test_astra_t1_release_concurrency.py'); print('BASELINE_SHA=27dd525c1fd7d531c4833c4bf7e44204a9345f19',flush=True); print('BASELINE_SOURCE='+str(pathlib.Path(genesis.__file__).resolve()),flush=True); print('TEST_SOURCE='+str(p.resolve()),flush=True); spec=importlib.util.spec_from_file_location('tests.test_astra_t1_release_concurrency',p); m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(m)); print('RUN='+str(result.testsRun)); print('FAILURES='+str(len(result.failures))); print('ERRORS='+str(len(result.errors))); raise SystemExit(0 if result.wasSuccessful() else 1)"
```

Result: exit 1; **5 methods, 6 invariant assertion failures, zero
errors/import/setup failures**. The missing B3 proof owner is reported as an
asserted contract failure in every case, including both concurrency orders.

Final preserved artifacts:

- `tests/test_astra_t1_release_concurrency.py` SHA-256:
  `1546C8385CE9ACDE0D9EE5FB954BD380A002EDA4157BD681194ACC4E05F79486`
- `red_release_concurrency_27dd_final.txt` SHA-256:
  `644C3A911A664BADFD4C793627CC75CF968FA34EC12A6FCA5DFD77708C1942DA`

These are synthetic PAPER-only gates. No closure or GO claim is made.
