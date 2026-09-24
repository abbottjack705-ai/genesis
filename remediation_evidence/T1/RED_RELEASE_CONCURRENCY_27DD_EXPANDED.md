# B3 expanded legal-path RED-before evidence

Date: 2026-09-24

Baseline production: clean detached `27dd525c1fd7d531c4833c4bf7e44204a9345f19`
at `work/t1-red-baseline`. The only status entries there were previously
preserved untracked RED test copies; `src/` remained the sealed commit.

Expanded test source SHA-256:
`83DB1AAB00D63A2E801DEE28724D3EC422BFB918ECE9B15C1275B3236BC3A883`

Exact command, run from `work/t1-red-baseline`:

```powershell
python -c "import importlib.util,pathlib,sys,unittest; sys.path.insert(0,str(pathlib.Path.cwd()/'src')); import genesis; p=pathlib.Path(r'C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\genesis-remediation\tests\test_astra_t1_release_concurrency.py'); print('BASELINE_SHA=27dd525c1fd7d531c4833c4bf7e44204a9345f19',flush=True); print('BASELINE_SOURCE='+str(pathlib.Path(genesis.__file__).resolve()),flush=True); print('TEST_SOURCE='+str(p.resolve()),flush=True); spec=importlib.util.spec_from_file_location('tests.test_astra_t1_release_concurrency',p); m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(m)); print('RUN='+str(result.testsRun)); print('FAILURES='+str(len(result.failures))); print('ERRORS='+str(len(result.errors))); raise SystemExit(0 if result.wasSuccessful() else 1)"
```

Exact result footer:

```text
----------------------------------------------------------------------
Ran 8 tests in 4.893s

FAILED (failures=9)
RUN=8
FAILURES=9
ERRORS=0
```

Every failure was the explicit invariant assertion:

```text
AssertionError: B3 requires a durable proof-bearing synthetic PAPER release owner
```

The nine assertion failures comprise eight methods plus both deterministic
subcases of the concurrency method. There were zero import, collection, setup,
or unexpected errors. The console transcript was returned verbatim by the
command and the prior five-method transcripts remain preserved unchanged.

Covered RED legal paths: unconsumed approval; proven zero-fill unmatched
cancellation; live partial conservation; partial fill with terminal head and
cancelled remainder; actual VOID with later same-fill correction; durable
proof/crash/retry; exactly-once replay; and both release/admission serial
orders.
