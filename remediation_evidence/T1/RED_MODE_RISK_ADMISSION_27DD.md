# B7 mode/risk-admission final RED-before evidence

Date: 2026-09-24

Production source was the detached audited checkpoint
`27dd525c1fd7d531c4833c4bf7e44204a9345f19` in
`work/t1-red-baseline`. The finalized test source was loaded read-only from the
active remediation worktree. No baseline production file was modified.

Test source SHA-256:
`6E5F3D8B229E4753598B1A79A07D2CB5B848DE2ABF28A27F7160F30C15E04CB1`.

Exact command, run from `work/t1-red-baseline`:

```powershell
python -c "import importlib.util,pathlib,sys,unittest; sys.path.insert(0,str(pathlib.Path.cwd()/'src')); import genesis; p=pathlib.Path(r'C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\genesis-remediation\tests\test_astra_t1_mode.py'); print('BASELINE_SHA=27dd525c1fd7d531c4833c4bf7e44204a9345f19',flush=True); print('BASELINE_SOURCE='+str(pathlib.Path(genesis.__file__).resolve()),flush=True); print('TEST_SOURCE='+str(p.resolve()),flush=True); spec=importlib.util.spec_from_file_location('tests.test_astra_t1_mode',p); m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(m)); print('RUN='+str(result.testsRun)); print('FAILURES='+str(len(result.failures))); print('ERRORS='+str(len(result.errors))); raise SystemExit(0 if result.wasSuccessful() else 1)"
```

Exact result footer:

```text
----------------------------------------------------------------------
Ran 8 tests in 35.663s

FAILED (failures=8)
RUN=8
FAILURES=8
ERRORS=0
```

The eight failures were invariant assertions, not import or setup errors:

- DISABLED mode incorrectly authorized `SUBMISSION_PENDING` and
  `SUBMISSION_SENT` (two failures).
- a crash/partial transition after the mode row but before its paired safety
  row incorrectly authorized both phases (two failures).
- a missing durable mode owner incorrectly authorized pending (one failure).
- risk admission exposed no durable mode authority, so current coherent PAPER
  mode could not be required (one failure).
- the same missing authority meant a partial mode/safety transition could not
  be denied at risk admission (one failure).
- an unpaired safe safety row was incorrectly treated as coherent PAPER
  permission (one failure).

The two legal controls passed on the sealed base: coherent PAPER permits the
synthetic action, and a post-order settlement remains legal after mode disable.
This is PAPER-only evidence and grants no operational or live GO.
