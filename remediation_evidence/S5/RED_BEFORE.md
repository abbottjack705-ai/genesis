# S5 / Astra A8 RED-before record

Independent process-boundary regressions were added before any S5 production
change. Exact baseline/current commands, SHAs and failing invariant assertions
are preserved in the adjacent transcripts. Import, collection and fixture
setup errors are not acceptable RED evidence.

Test source SHA-256:
`81b46756abe12b211f8e6200c2c9b1b450e2e375d93c10da4dd56e73e8db09da`.

## Sealed audited baseline

Baseline SHA: `166f9230a0fb773cad2ac3619b5f98989d78a818`.

```text
python -c "import sys,unittest,subprocess; from pathlib import Path; import tests; base=Path(r'..\s1-red-baseline').resolve(); sys.path.insert(0,str(base/'src')); import genesis; print('BASE_SHA',subprocess.check_output(['git','-C',str(base),'rev-parse','HEAD'],text=True).strip(),flush=True); print('GENESIS_SOURCE',genesis.__file__,flush=True); suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_astra_s5_process'); result=unittest.TextTestRunner(verbosity=2).run(suite); sys.exit(not result.wasSuccessful())"
```

Result: 12 tests, 12 failing invariant assertions, 0 errors. The retained-label
probe produced Brier `0.3229` instead of the label-free `0.01`, proving that the
old callback observed the trusted parent's retained label/path. Transcript
`RED_166F923.txt` SHA-256:
`36b90a4311d1167ece0e7e2d064d024d19d2be83cbdb3eaed23d34e544ec7edc`.

## Immediately preceding green checkpoint

Baseline SHA: `0032ee76f6a5137a70a22b79b1207c9554e37694` (S4/A6).

```text
python -m unittest tests.test_astra_s5_process -v
```

Result: 12 tests, the same 12 failing invariant assertions, 0 errors. Transcript
`RED_S4_HEAD.txt` SHA-256:
`26f05a16b4cc5a9671824367157f6531f09a49c4daf578af6c0e057d4dd44ddb`.

No S5 production source was changed. ADR-0003 v1 remains proposed and requires
explicit approval before implementation.
