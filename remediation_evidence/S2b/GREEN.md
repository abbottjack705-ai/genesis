# S2b A7 GREEN — current-head risk admission

Date: 2026-09-22. **Locally green for the A3+A7 risk group only; A4–A6/A8 remain HOLD.**

`RiskEngine.approve()` now acquires the risk log write lock and read-locks the bankroll, safety and qualification logs before resolving any mutable owner state. Within that one fenced JSONL approval transaction it strictly replays active exposure, reads current heads, checks the exact requested bankroll snapshot and qualification, derives stake and BACK/LAY liability from the frozen policy, applies open/correlation caps, and fsyncs the approval. A writer before lock entry is observed; a writer after lock entry cannot commit until approval is durable. SQLite remains a coordinator only, JSONL the business truth. A post-fsync coordinator failure leaves one replayable approval, not a fork or blind retry. No stake/risk percentage, tier, settlement or PAPER-only rule changed.

| Gate | Exact command | Result/evidence |
|---|---|---|
| New A7 targeted | `python -m unittest tests.test_astra_s2_admission -v` | Exit 0, 9/9; `GREEN_TARGETED.txt` |
| Retained impacted | `python -m unittest tests.test_remediation_r5_risk tests.test_remediation_r6_execution tests.test_remediation_r7_settlement tests.test_remediation_r10_integration tests.test_astra_s1_submission tests.test_astra_s1_reservation tests.test_astra_s2_replay tests.test_astra_s2_admission -v` | Exit 0, 56/56; `GREEN_IMPACTED.txt` |
| Full regression | `python -m unittest discover -s tests -t . -v` | Exit 0, 139/139 in 52.220s; `GREEN_FULL_SUITE.txt` |
| Compilation | `python -m compileall -q src tests` | Exit 0 |

Windows spawn/Pipe tests ran outside the sandbox because unchanged R9 multiprocessing tests produce sandbox `WinError 5`; the full suite result is an independent outside-sandbox run. Logs were captured with PowerShell `2>&1 | Tee-Object` and the Python exit code was preserved by `exit $LASTEXITCODE`.

SHA-256: `GREEN_TARGETED.txt` `1C81B62CC98BEE7103CDA1D6AC25A263C3469DB0B9D9CED4C51E46C4742B8F46`; `GREEN_IMPACTED.txt` `111726011D3D3B5AED26A91954BB2785563CD671E5BFBDC0C6D693C5E01C2F86`; `GREEN_FULL_SUITE.txt` `D98202A77E7369CCF4F63BEC57C4C601938D1D79DD9093F06ABD5E6FBDB69F94`; `src/genesis/risk.py` `F1F250A31F4CF26D9226F5D19B8EAFD2CE1237CEFA76AD39A6AFE60919B97A59`; `tests/test_astra_s2_admission.py` `D52EDC46199FFD258255F5F20FAC5CB39622DF628B1BE6F1514814E2B99C8F37`.

Diff review: S2b changes only the `approve()` admission critical section, adds independent A7 regressions and evidence, and narrows state claims. R0–R10/S1/S2a tests were neither deleted nor weakened. No external source/venue path, adapter, shadow-research or live-money GO was added. A4/A5 qualification identity/PIT remain separately open despite the qualification log fence; A6 cache and A8 process isolation remain open. A fresh independent hostile re-audit and explicit checkpoint approval are still required.
