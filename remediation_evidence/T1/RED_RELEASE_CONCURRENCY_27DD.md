# B3 release/concurrency RED-before evidence

Date: 2026-09-23

The production source was the clean detached checkpoint
`27dd525c1fd7d531c4833c4bf7e44204a9345f19` in
`work/t1-red-baseline`. The new test module was loaded read-only from the main
worktree, so no production or retained test in the detached checkout was
modified.

Exact command, run from `work/t1-red-baseline`:

```powershell
python -c "import importlib.util,pathlib,sys,unittest; sys.path.insert(0,str(pathlib.Path.cwd()/'src')); import genesis; p=pathlib.Path(r'C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\genesis-remediation\tests\test_astra_t1_release_concurrency.py'); print('BASELINE_SHA=27dd525c1fd7d531c4833c4bf7e44204a9345f19',flush=True); print('BASELINE_SOURCE='+str(pathlib.Path(genesis.__file__).resolve()),flush=True); print('TEST_SOURCE='+str(p.resolve()),flush=True); spec=importlib.util.spec_from_file_location('tests.test_astra_t1_release_concurrency',p); m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(m)); print('RUN='+str(result.testsRun)); print('FAILURES='+str(len(result.failures))); print('ERRORS='+str(len(result.errors))); raise SystemExit(0 if result.wasSuccessful() else 1)"
```

Result: exit 1; **5 methods, 6 invariant assertion failures, zero
errors/import/setup failures**. Both deterministic concurrency schedules are
separate failing subtests. Every failure reports that B3 lacks its durable
proof-bearing synthetic PAPER owner; the test converts the baseline's missing
module into an explicit invariant assertion rather than collection failure.

Preserved artifacts:

- `tests/test_astra_t1_release_concurrency.py` SHA-256:
  `EA01AE1902240FF5CA90F48FB02C4E207AE1761818D247531CB0A0F943CA4942`
- `red_release_concurrency_27dd.txt` SHA-256:
  `58EC556EA07C6EBE138EEC2550CB1B590E8030A4B6FA8C8E7F895C3A12540E3C`

The cases are synthetic PAPER-only and grant no operational adapter,
strategy, campaign, shadow-research, or live-money approval. No closure or GO
claim is made here.
