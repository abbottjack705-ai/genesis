# B3 release/concurrency owner-fence final RED-before evidence

Date: 2026-09-24

Production source was the detached audited checkpoint
`27dd525c1fd7d531c4833c4bf7e44204a9345f19` in
`work/t1-red-baseline`. The finalized test source was loaded read-only from the
active remediation worktree. No baseline production file was modified.

Test source SHA-256:
`CC7C322FE73B01A37A9BF7E87C628EC0AF3C58133FD2CA5FE6F4EEF763355ED7`.

Exact command, run from `work/t1-red-baseline`:

```powershell
python -c "import importlib.util,pathlib,sys,unittest; sys.path.insert(0,str(pathlib.Path.cwd()/'src')); import genesis; p=pathlib.Path(r'C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\genesis-remediation\tests\test_astra_t1_release_concurrency.py'); print('BASELINE_SHA=27dd525c1fd7d531c4833c4bf7e44204a9345f19',flush=True); print('BASELINE_SOURCE='+str(pathlib.Path(genesis.__file__).resolve()),flush=True); print('TEST_SOURCE='+str(p.resolve()),flush=True); spec=importlib.util.spec_from_file_location('tests.test_astra_t1_release_concurrency',p); m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(m)); print('RUN='+str(result.testsRun)); print('FAILURES='+str(len(result.failures))); print('ERRORS='+str(len(result.errors))); raise SystemExit(0 if result.wasSuccessful() else 1)"
```

Exact result footer:

```text
----------------------------------------------------------------------
Ran 9 tests in 49.981s

FAILED (failures=11)
RUN=9
FAILURES=11
ERRORS=0
```

Every failure was the deliberate invariant assertion
`B3 requires a durable proof-bearing synthetic PAPER release owner`; there
were no import or setup errors. The eleven assertion instances cover all nine
methods, including both deterministic interleavings of release versus new
risk and both deterministic interleavings of owner attachment versus
admission. Positive-path cases cover unconsumed approval, proven unmatched
cancellation, live partial-fill conservation, partial-fill plus cancelled
remainder, actual VOID with later terminal correction, crash between durable
proof and release, and duplicate replay across restart.

This final addendum supersedes only the test-source/result counts in earlier
B3 RED notes; all earlier transcripts remain immutable historical evidence.
It is synthetic PAPER-only evidence and grants no operational or live GO.
