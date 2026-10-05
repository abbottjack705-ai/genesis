# Independent test results

| Check | Result | Raw evidence |
| --- | --- | --- |
| Pin, ancestry, clean candidate, frozen trees, R7 SHA manifest | PASS; 22 evidence-only files, 21 matching hashes | `evidence/integrity.txt` |
| R7 targeted | 57 passed, 462.044 s | `evidence/targeted_r7.txt` |
| Full adapter | 917 passed, 2 Windows platform skips, 1429.825 s | `evidence/full_adapter.txt` |
| Final no-network guard | PASS; no non-loopback attempt by the suite | final test in `evidence/full_adapter.txt` |
| Frozen V0.4 | 493 passed, 1 skip, 835.477 s | `evidence/frozen_v04.txt` |
| Frozen S0 transcript comparison | Identical counts: 493/0 failures/0 errors/1 skip | `evidence/frozen_compare.txt` |
| Replay/rebuild | 2 passed | `evidence/replay.txt` |
| Final provenance | 3 passed | `evidence/provenance.txt` |
| Compileall | PASS | `evidence/compile.txt` |
| Prior hostile R6 rejection/poison/Date/quota/TLS/replay/provenance/F-44 reproducers | Key safety outcomes held on R7; the prior provenance .pth case is inconclusive; quota needed UTF-8 output and provenance needed Windows tempfile | `evidence/prior_*.txt` |
| New combined content-plus-quota crash probe | Three restarts; one halt, two coverage effects, zero documents | `evidence/combined_failure_crash.txt` |
| TLS concurrency and stock trust parity | 80 contexts, 16 workers; 47/47 stock CAs | `evidence/tls_concurrency.txt` |
| DNS repeated stalls/late activity/shutdown | Deadline held; 12 live abandoned workers until release; no late socket; child exited | `evidence/dns_exhaustion.txt`, `evidence/dns_shutdown.txt` |
| Mutation | Supplied 16/16; independent 5/5, no-op 5/5 | `MUTATION_EVIDENCE.md` |

All production/test runs used CPython 3.12.10 with `-B` and isolated bytecode or `PYTHONDONTWRITEBYTECODE`. The initial replay/provenance command lacked `PYTHONPATH` and failed at import before tests ran; the corrected reruns above passed. The initial prior quota probe hit Windows cp1252 while printing fullwidth digits; `PYTHONIOENCODING=utf-8` corrected this harness-only issue.
