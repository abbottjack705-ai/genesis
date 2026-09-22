# S3b/A4 initial RED checkpoint — historical

This records the first partial RED run. `CHECKPOINT.md` and the
`RED_FINAL_*` transcripts contain the final 23-test pre-fix evidence and the
completed green gate. The evidence below is preserved verbatim as an earlier
stage artifact.

Date: 2026-09-22 UTC. Audited base `166f9230a0fb773cad2ac3619b5f98989d78a818`;
immediately prior green S3a `4f04c0a7a996250480d870ecae920a03812e894d`
(tree `71b24d7b240b910d43d6b5d5ae7b10690a039d9c`).

Independent module `tests/test_astra_s3_output.py` has 11 RED methods on
each clean baseline, all invariant assertions, no setup/import errors.
The first nine show that original/copy-mutated candidate-v2 output values
still QUALIFY under the old hash: raw/conservative probability, uncertainty,
observed price, price band, another allowed tier, expiry and dependence.
The remaining two require domain-separated v3 output and strict closed
encoding. The test source is loaded from this worktree, but production source
from each path printed in the corresponding transcript.

Commands were `python -c` with `sys.path.insert(0, <baseline>/src)`,
`unittest.defaultTestLoader.loadTestsFromName('tests.test_astra_s3_output')`,
`unittest.TextTestRunner(verbosity=2)` and exit on `not result.wasSuccessful()`;
stdout/stderr were captured via `2>&1 | Tee-Object` to the transcript names.
The complete SHA and loaded module path are printed at the top of each log.

| Transcript | SHA-256 |
|---|---|
| `RED_166F923.txt` | `fc6e4278f7aa5af64c7ed1bc048b139fa2e8d56c1c8535af176fe54f1bf71146` |
| `RED_S3A_HEAD.txt` | `bc1fd26122c46de14c8ac611105028116cdec1ebe1c223d95a8d1ed3dc2437e3` |

Partial production work only: a separate v3 hash function and strict
content-addressed `DecisionOutput-v1` schema/store. Its two isolated contract
tests pass, and `compileall` passes. This is **not** trusted resolver/binding,
v3 qualification, risk/order lineage, or A4 closure. Nine legacy-new-
qualification tests remain intentionally RED. No S3b commit should be made
before the exact approved-ADR scope is implemented and all stage gates pass.
Historical candidate-v1/v2 hash functions and persisted records are unchanged.
