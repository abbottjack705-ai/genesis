# Commands and exit codes (W5 WC7-003 recertification, subject 2e8290e)

| # | Command | Exit | Note |
|---|---|---|---|
| 1 | `git worktree add --detach /c/Users/abbot/fz/w5rc 2e8290ea7a8a26d4796de893036c12a0d05b7b2b` | 0 | clean subject checkout |
| 2 | `git rev-parse HEAD` (subject) | 0 | 2e8290ea7a8a26d4796de893036c12a0d05b7b2b |
| 3 | `git status --porcelain` (subject) | 0 | empty |
| 4 | `git diff --check deec08ffc66c56d156bc09addf548c62166cea17 HEAD` and `git diff --check` (subject) | 0, 0 | |
| 5 | `git hash-object` of cli.py, the WC7-003 test module, the design doc | 0 | equals tree blobs |
| 6 | `python -B probes/w5_raw_w32tm_capture.py evidence` (runs `w32tm /query /status`, no text-mode decode) | 0 | w32tm returncode 0, 290 bytes, LF-only |
| 7 | `python -B probes/w5_real_startup_attestation.py evidence/W05_real_startup_attestation.json` (real `cli.time_sync_attestation()`, no mock) | 0 | returned synchronized=false |
| 8 | `sc.exe query w32time`, `sc.exe qc w32time`, `Get-Service w32time` | read-only | service Running, auto (delayed) |
| 9 | `MSYS_NO_PATHCONV=1 w32tm /query /source` | 5 | Access is denied (elevation required); not needed for the decision |
| 10 | history checks (`git ls-remote`, `git rev-parse`, `git ls-tree | sha256sum`, `git diff --quiet`) | 0 | see INTEGRITY_HISTORY.txt |
| 11 | healthy controls and G2/G2R refusal replays | NOT RUN | stop condition: host not healthy per Genesis |
