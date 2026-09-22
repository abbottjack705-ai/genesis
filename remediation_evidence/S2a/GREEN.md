# S2a A3 GREEN — strict active-state replay

Date: 2026-09-22. **Locally green for A3 only; A7 and A4–A8 remain HOLD.**

`RiskEngine` now validates the entire risk event sequence on startup and at transactional replay: exact type/schema, required fields, approval/consumption/reservation identities, duplicate IDs/candidate approvals and legal state transitions. Bankroll and safety histories reject incompatible or incomplete hash-valid active rows and broken parent/time heads. Unknown active scope is not guessed as zero liability. JSONL remains business truth; SQLite remains a coordinator. No existing risk percentage, stake tier or settlement rule changed.

| Gate | Exact command | Result |
|---|---|---|
| New targeted | `python -m unittest tests.test_astra_s2_replay -v` | Exit 0, 7/7 |
| Impacted retained + S1 | `python -m unittest tests.test_remediation_r5_risk tests.test_remediation_r6_execution tests.test_remediation_r10_integration tests.test_astra_s1_submission tests.test_astra_s1_reservation tests.test_astra_s2_replay -q` | Exit 0, 38/38 before the final illegal-consumption case was added; all 39 are covered by the final full run |
| Full regression | `python -m unittest discover -s tests -t . -v` | Exit 0, **130/130**, 41.588s; `GREEN_FULL_SUITE.txt` |
| Compilation | `python -m compileall -q src tests` | Exit 0 |
| Diff | `git diff --check` before staging | Exit 0; line-ending advisories only |

SHA-256: `GREEN_FULL_SUITE.txt` `92f276cd7ec57e1c2e17fd0f43b44828db2d4a1ee3a6232a6c9cb4fddf56f4da`; `src/genesis/risk.py` `7e3f45f538e3025055fc0a993fe970669eeda07667094722f7c746b5fcedc918`; `tests/test_astra_s2_replay.py` `674b023d9c03eb9e8c0fd76cc5e78d34f38290861762349b5316bebf33f591a4`.

A7's pre-transaction bankroll/safety read race remains open. Do not grant adapter, substantive shadow-research or live-money GO.
