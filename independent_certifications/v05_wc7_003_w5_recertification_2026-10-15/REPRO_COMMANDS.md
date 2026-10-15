# Commands and exit codes (W5 WC7-003 recertification, subject 2e8290e, attempt 2026-10-15)

| # | Command | Exit | Note |
|---|---|---|---|
| 1 | `git worktree add --detach /c/Users/abbot/fz/w5rc-r2 2e8290ea7a8a26d4796de893036c12a0d05b7b2b` | 0 | fresh clean subject checkout |
| 2 | `git rev-parse HEAD` (subject) | 0 | 2e8290ea7a8a26d4796de893036c12a0d05b7b2b |
| 3 | `git status --porcelain` (subject, before probes) | 0 | empty |
| 4 | `git diff --check deec08ffc66c56d156bc09addf548c62166cea17 HEAD` and `git diff --check` (subject) | 0, 0 | |
| 5 | `git hash-object` of cli.py, the WC7-003 test module, V05_ADAPTER_ARCHITECTURE.md | 0 | equals `git rev-parse HEAD:<path>` |
| 6 | `git diff --quiet 4f11606 HEAD -- src` and `git diff --quiet v0.4-foundation-freeze HEAD -- src` (subject) | 0, 0 | frozen src unchanged |
| 7 | `python -B probes/w5_raw_w32tm_capture.py evidence` (runs `w32tm /query /status`, bytes only, no text-mode decode) | 0 | w32tm returncode 0, 324 bytes, LF-only, Leap Indicator 0 / Stratum 5 |
| 8 | `python -B probes/w5_real_startup_attestation.py evidence/W05_real_startup_attestation.json` (real `cli.time_sync_attestation()` from the clean checkout, no mock) | 0 | synchronized=true |
| 9 | `sc.exe query w32time`, `sc.exe qc w32time`, `Get-Service w32time` | read-only | Running; start type DEMAND_START (Manual) |
| 10 | `(cd adapters && PYTHONPATH="<adapters/src>;<src>" PYTHONPYCACHEPREFIX=<temp> python -B -m unittest -v adapter_tests.test_v05_wc7_003_time_sync)` | 0 | Ran 76 tests, OK, 810.1 s; transcript in evidence/ |
| 11 | `git status --porcelain` (subject, after probes and tests) | 0 | empty |
| 12 | `git ls-remote origin`, `git rev-parse 2285f24:independent_certifications`, `git ls-tree -r 2285f24 independent_certifications \| sha256sum`, `git show 6b3eb43:<2026-10-14 path>` hashed against SHA256SUMS_2026-10-14.txt | 0 | see INTEGRITY_HISTORY.txt |

Probe note: `probes/w5_raw_w32tm_capture.py` is byte-identical to the 2026-10-14 probe. `probes/w5_real_startup_attestation.py`
differs from it only in `clean_src`, which points to `C:\Users\abbot\fz\w5rc-r2\adapters\src` instead of `...\w5rc\...`.
