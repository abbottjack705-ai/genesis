# S1 RED-before — sealed Astra R10 checkpoint

Date: 2026-09-22. Findings: A1 CRITICAL and A2 HIGH only.

- Sealed implementation commit: `166f9230a0fb773cad2ac3619b5f98989d78a818`.
- Sealed tree: `070301384f286f79eceeb5296f9fe41125876390`.
- Isolated detached worktree: `../s1-red-baseline`, verified clean before and after.
- The source imported for the run was `../s1-red-baseline/src/genesis/__init__.py`, printed as `BASELINE_SOURCE` in `RED_BASELINE.txt`. New test modules were loaded from this working repository without copying or mutating the sealed checkout.
- New test SHA-256: `test_astra_s1_submission.py` `2a39404b2eea23e57b749669e4f0f3dd9e9b926677708ba35f1fbf4ad98e520b`; `test_astra_s1_reservation.py` `bc3400f3d890c6c477625a2f1f6433cd22456e0978af125c6fa6e536d3115706`.

Exact command, run from the main remediation repository:

```powershell
python -c "import sys,unittest;sys.path.insert(0,r'C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\s1-red-baseline\src');import genesis;print('BASELINE_SOURCE='+genesis.__file__,flush=True);suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_astra_s1_submission','tests.test_astra_s1_reservation']);result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())"
```

Result: **exit 1; 13 test methods, 35 invariant assertion failures, zero setup/import errors**. Full exact output: `RED_BASELINE.txt` (SHA-256 `0178fb3c29c42099134a951de3847a0f6ba293d3cdfe8f9cd7f8e7f6c2bd4983`). The failures include the original kill/expiry/closed-market bypass, failed refresh/material-change/price/liquidity/strategy bypass at both legal submission phases, own UNKNOWN/VOID/SETTLED recertification, missing/conflicting reservation, restart, a transaction-entry interleaving, and absence of a check inside a crashed submission transaction.

The pre-fix working HEAD was the same `166f923`; the same two modules were also run directly with `python -m unittest tests.test_astra_s1_submission tests.test_astra_s1_reservation -v` before production edits, yielding failing invariant assertions. The independent Astra report, original probe, results and ZIP outside this repository remain unchanged. No R0–R10 commit was reverted or rewritten.
