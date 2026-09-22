# S2a A3 RED-before

Date: 2026-09-22. The sealed `166f9230a0fb773cad2ac3619b5f98989d78a818` checkout (`../s1-red-baseline`) and the immediately preceding green S1 commit `283523851031470fd7226ebc27ceacba0151689d` checkout (`../s2a-red-s1`) were both clean and detached. The `tests/test_astra_s2_replay.py` module was loaded from the working repository while `sys.path[0]` was each checkout's `src` directory; the imported source path is printed in each transcript.

Exact test runner pattern:

```powershell
python -c "import sys,unittest;sys.path.insert(0,r'C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\s1-red-baseline\src');import genesis;print('BASELINE_SOURCE='+genesis.__file__,flush=True);suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_astra_s2_replay');result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())"
```

For the preceding S1 checkpoint, substitute `s2a-red-s1\src` and label `PRIOR_SOURCE`. Both runs exited 1 with **7 methods, 10 invariant assertion failures, zero setup/import errors**. They reproduce Astra's hash-valid unsupported active approval and additional unknown/missing/invalid active risk, bankroll and safety states, including restart, illegal consumption and a transaction-entry injection. Full outputs: `RED_166F923.txt` SHA-256 `bd885d8015507bb8104ef475f5c527a9569f8073d16e8f8c9f297d30232240b7`; `RED_S1_HEAD.txt` SHA-256 `a956147da73237d1c9b0981bc33a76c46ab57f01501154f13699bb913e25a89b`. Test module SHA-256 `674b023d9c03eb9e8c0fd76cc5e78d34f38290861762349b5316bebf33f591a4`.
