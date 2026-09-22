# S2b A7 RED-before — coordinated admission

Date: 2026-09-22. Sealed audited base `166f9230a0fb773cad2ac3619b5f98989d78a818`, tree `070301384f286f79eceeb5296f9fe41125876390`; preceding independently green S2a commit `aed0e5bd43f99061f08de6f0808e4efc76f8b853`, tree `cbbaa04b63e35c66ef8448e2d6663d07e67a8fa2`. Both detached checkouts (`../s1-red-baseline`, `../s2b-red-s2a`) were clean. Neither checkout was changed. The new test module was loaded from this working repository, with `genesis` source selected from each isolated checkout. Windows-spawned workers explicitly select that same checkout source in `_isolated_worker_authority`.

The first seven tests, written before the production fix, failed on four A7 invariant assertions against S2a. The test module was subsequently strengthened with an admission-first process writer fence, explicit child-source selection, and a post-fsync coordinator-failure positive case. The final exact nine-test module was rerun against both untouched checkpoints:

```powershell
python -c "import sys,unittest;sys.path.insert(0,r'C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\s1-red-baseline\src');import genesis;print('BASELINE_SOURCE='+genesis.__file__,flush=True);suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_astra_s2_admission');result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())"
```

For S2a, replace `s1-red-baseline\src` with `s2b-red-s2a\src` and `BASELINE_SOURCE` with `PRIOR_SOURCE`. Both final runs exited 1: **nine methods, six invariant assertion failures, zero import/setup errors**. Failures: 100→10 rebase still admitted 7.5 stake; kill activation still admitted; ambiguous qualification still admitted; rebase-before-admission cross-process still admitted; and both bankroll/safety writers crossed a paused approval's supposed fence. Positive cap/UNKNOWN and uncertain-response cases remained green. Full raw transcripts: `RED_166F923.txt` SHA-256 `FAEAE9C0692F438D9E85697293151C0F1300AE4C3128E0B60D5CF29B30E9A8F3`; `RED_S2A_HEAD.txt` SHA-256 `8FE366DB4D047FEED4366A6AE802CDC147947054385F6493DE7027CDA64C99A0`. Test module SHA-256 `D52EDC46199FFD258255F5F20FAC5CB39622DF628B1BE6F1514814E2B99C8F37`.

These are controlled interleavings, not a probabilistic race benchmark. The original Astra audit report/probe/ZIP and all failed reproduction evidence remain sealed and unchanged.
