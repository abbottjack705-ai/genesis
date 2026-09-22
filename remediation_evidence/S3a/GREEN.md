# S3a/A5 evidence — green checkpoint

Date: 2026-09-22 UTC. Pre-fix approved HEAD:
`3729022a7d38ee43b2100f512abe76728e8291e0`. Sealed independent R10
baseline: `166f9230a0fb773cad2ac3619b5f98989d78a818`.

The 11-test `tests.test_astra_s3_manifest` module was run with each isolated
checkout's `src` prepended to `sys.path`, using
`unittest.defaultTestLoader.loadTestsFromName` and `TextTestRunner(verbosity=2)`.
`RED_166F923.txt` and `RED_APPROVED_HEAD.txt` print the exact source path and
baseline SHA. Both runs fail 11/11 behavioral invariant assertions, with no
import/setup errors. The tests preserve existing R3 fixture semantics on the
old checkout and create exact synthetic manifest objects only on S3a source.

Exact RED commands from the main repository workdir (each redirected with
`2>&1 | Tee-Object -FilePath` to its corresponding transcript; PowerShell then
exited with `$LASTEXITCODE`):

```powershell
python -c "import sys,unittest; sys.path.insert(0,r'C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\s1-red-baseline\src'); import genesis; print('BASELINE_SHA=166f9230a0fb773cad2ac3619b5f98989d78a818',flush=True); print('BASELINE_SOURCE='+genesis.__file__,flush=True); result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_astra_s3_manifest')); sys.exit(not result.wasSuccessful())"
python -c "import sys,unittest; sys.path.insert(0,r'C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\s3a-red-approved\src'); import genesis; print('PRIOR_SHA=3729022a7d38ee43b2100f512abe76728e8291e0',flush=True); print('PRIOR_SOURCE='+genesis.__file__,flush=True); result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_astra_s3_manifest')); sys.exit(not result.wasSuccessful())"
```

Current targeted command:
`python -m unittest tests.test_astra_s3_manifest tests.test_remediation_r3_qualification -v`.
Result: 22/22, `GREEN_TARGETED.txt`.

First full command:
`python -m unittest discover -s tests -t . -v`.
The unprivileged attempt ran 150 tests with 12 Windows `multiprocessing.Pipe`
access-denied errors in retained S2/R9 tests (`GREEN_FULL_UNESCALATED.txt`).
The permitted full rerun passed 150/150 (`GREEN_FULL.txt`) before a final
source-contract replay validation hardening. Targeted 22/22 was repeated after
that change. `python -m compileall -q src tests` passed after the change,
`GREEN_COMPILEALL.txt`. A first attempt at the final full rerun could not
launch because automatic approval review reported a usage limit, not an unsafe
command. The later permitted **post-hardening** rerun passed 150/150 in 63.591s
(`GREEN_FULL_FINAL.txt`). No failure was hidden or replaced.

Transcript SHA-256 hashes:

| Transcript | SHA-256 |
|---|---|
| `RED_166F923.txt` | `2aee1dcc0febbd6dfe7e17a62dc97e6509d106717da10fc666c8fa2e7ec73d93` |
| `RED_APPROVED_HEAD.txt` | `09c10472db99a1f041c88f26ba44988e6cb0dcbabcbfaf4ba036a0df351af287` |
| `GREEN_TARGETED.txt` | `5e6c33e90c3de055076341cd0899f8a26df2b527df033a46d66438cf82ed814a` |
| `GREEN_FULL_UNESCALATED.txt` | `0290622806d9d4b2d5b8da8c7187c709e1dcd030435cbd1a4a0505d4331ec51b` |
| `GREEN_FULL.txt` | `5062d70f8f3394b5d2eee425d3f5eefbf8e1283841d495b9cc8cbefc68a98a48` |
| `GREEN_COMPILEALL.txt` | `c1e97067c5f479a44a6f57297a0a8f87a59d181c3c529910f8bf059094bc3abb` |
| `GREEN_FULL_FINAL.txt` | `d510809422691b1cb68104f04a78cdf206e9c6ffcfafb72b41e23f61bcaf2fb2` |

No policy, odds, unit, risk, quota, hold-to-settlement, candidate-v1/v2 hash,
adapter, protected research or live-money behavior is deliberately changed.
A4/S3b, A6 and A8 remain HOLD. S3a is local closure, not independent audit GO.
`git diff --cached --check` reported only a trailing space in the verbatim
failed multiprocess test output; the source/docs diff check was clean. The
raw failed transcript is preserved byte-for-byte.
