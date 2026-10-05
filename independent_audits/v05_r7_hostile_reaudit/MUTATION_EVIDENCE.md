# Mutation evidence

The targeted suite passed all 57 tests before mutation, providing a baseline for R7's named tests. The supplied 16-mutant campaign was rerun in detached scratch checkout `b2eabac1`; it reported **16/16 killed**, including R01b (restoring the historical newest-planned-only algorithm). A kill required a single named target test to run and fail; harness errors were not counted. See `evidence/r7_mutation_detail.txt`.

The independent campaign in `probes/independent_mutations.py` checked the same scratch checkout pin, ran every named target unchanged first (**5/5 no-op controls survived**), made each one-line mutation, then restored source bytes in `finally`. It killed **5/5**: first-only historical settlement; lost quota halt for a separately malformed response; disabled TLS hostname verification; 100 ms extra resolver grace; hidden conflicting rejection coverage. See `evidence/independent_mutations.txt`.

No non-equivalent survivor or harness error occurred. `git diff --quiet -- adapters/src adapters/adapter_tests` confirmed the scratch production and tests were restored. The candidate and audit branches' R7 production/test files were never edited by mutation.
