# TEST_RESULTS — what actually ran in this audit

Environment: Linux 6.18 x86_64, Python 3.11.15, git clone of `abbottjack705-ai/genesis`,
detached worktree at `c8dfafd`. Nothing from the candidate ran (unreachable, HA-000).

## 1. Frozen-tree identity (executed)

```
$ for ref in 2278e2a c8dfafd; do for d in src tests config tools DECISIONS v04_pack; do git rev-parse $ref:$d; done; done
src        51cb635bc42b993815b6c02a23c4c3ceb7d98476   (both)
tests      e90b298180068fec03ba7e2fa81957082e7fb3ce   (both)
config     abd22db01ff482a8da84634ee740ba382b68c804   (both)
tools      a0e3411edb4e068fd4708050516cb6870834e7ac   (both)
DECISIONS  cc97ec6f841f1e3fbe6dbb57c9cb6e1ac24fdb64   (both)
v04_pack   3c3c1c27d80ed6f10c32ac6605a5f438b2e7de12   (both)
$ git diff --stat 2278e2a c8dfafd
 V05_ADAPTER_ARCHITECTURE.md | 2526 +++++  (1 file)
$ git ls-files --eol --with-tree c8dfafd -- src tests config tools DECISIONS v04_pack | grep -E 'i/crlf|i/mixed' | wc -l
0
$ python oracle/oracle_frozen_identity.py --repo <authority worktree> --commit c8dfafd
I-1 PASS  I-2 PASS  I-3 PASS (0 changed)  I-4 PASS  I-5 PASS  I-6 FAIL (adapters/.gitattributes absent — expected at c8dfafd, which predates S0)
```

Attempt to obtain the candidate:

```
$ git ls-remote origin
c8dfafdff3be611fa6255a03ed361bc46d7ad8fe  refs/heads/ccr-dc07c30b-wxq872
2278e2a68083f7ac58d796b1ed9c43d50020b6b0  refs/heads/claude/windows-containment-module-qfk13i
4f11606615c7650f3bd74c7ccf5d2fb7a5a753c5  refs/heads/t6-remediation
2278e2a68083f7ac58d796b1ed9c43d50020b6b0  refs/heads/v0.5-adapters
a5ca3c96cf04800e03d808d913f612234d8ff1a4  refs/tags/v0.4-foundation-freeze  (-> 2278e2a)
$ git fetch origin cfcff3dbb285eaa48a6cfc1eceedb91e27662c81
fatal: remote error: upload-pack: not our ref cfcff3dbb285eaa48a6cfc1eceedb91e27662c81
$ list_repos(query="genesis") -> only abbottjack705-ai/genesis
```

## 2. Frozen suite at `c8dfafd` (executed, Linux)

```
$ python3 -m unittest discover -s tests -t . -v
Ran 493 tests in 105.856s
OK (skipped=19)
```

Skip reasons (all platform-conditional, none a functional skip):

| Count | Reason |
| --- | --- |
| 9 | Windows OS confinement primitives |
| 4 | environment cannot create an AppContainer |
| 3 | N2 compares owner identities caselessly only on Windows |
| 1 | no 8.3 short names on this platform or volume |
| 1 | only Windows refuses to delete an open file |
| 1 | os.startfile exists only on Windows |

Full log: `frozen_suite_c8dfafd_linux.log` (SHA-256 in `ARTIFACT_MANIFEST.sha256`).

## 3. Frozen quota semantics (executed against frozen `genesis.quota`)

`oracle/QUOTA_SEMANTICS_OUTPUT.json` (verbatim):

```
Q-A_identical_replay:   first=billable_call_reserved replay=billable_call_reserved replay_allowed=true new_rows_written=0 raised=false
Q-B_new_time_same_id:   raised=true  "quota request ID cannot be reused with another payload"
Q-C_time_regression:    allowed=false reason=quota_event_time_regressed raised=false
Q-D_daily_8th:          seventh=(true, billable_call_reserved) eighth=(false, daily_quota_exhausted)
Q-D_normal_221st:       requests_possible_in_31_day_month_at_1_unit=217  (220 unreachable at 1 unit/attempt)
Q-E_reserve_unauthorized: allowed=false reason=normal_monthly_budget_not_exhausted
Q-F_zero_units:         raised=true "billable units must be positive"
Q-G_day_boundary_by_Tq: eighth_across_midnight_allowed=true daily_used_after=1
Q-H_forged_cache:       reason=billable_call_reserved billable_units=1  (no forged hit)
```

## 4. Oracle self-tests (executed)

The oracle must be able to fail. Each detector was run against a synthetic defective
adapter (`selftest/`, not shipped) and against a corrected one.

| Oracle | Planted defect | Result |
| --- | --- | --- |
| `oracle_static_scan.py` | `except KeyboardInterrupt`, bare `except`, `return` in `finally`, `urllib.request` outside transport, subclass of `QuotaLedger`, `QuotaReserveAuthorization` + `BudgetClass.RESERVE`, `OperationalStatus.READY` outside cli, `timeout=30` literal, `logging.getLogger` in transport, text-mode read in provenance guard | every one reported (X-01,02,03,05,06,07,08,11,12 FAIL; X-09/X-10 flagged for review) |
| `oracle_provenance_crlf.py` | guard opens modules in text mode (`newline=None`) | P-3_crlf_refused **FAIL** (guard PASSED the CRLF copy = fail-open detected), P-5 FAIL; control edit still REFUSED |
| `oracle_provenance_crlf.py` | guard reads bytes | all PASS: CRLF copy REFUSED with `ModuleProvenanceError`, clean copy PASSED, edited copy REFUSED |
| `oracle_frozen_identity.py` | run on `c8dfafd` | I-1…I-5 PASS, I-6 FAIL for the right reason |
| `oracle_boundary_guard_edges.py` | — | pattern consistent across 6 boundaries; guard zone `[23:57:00, 00:02:00)` |
| `oracle_pit_head_expected.py` | — | 8 scenarios generated from frozen `PITStore`; S2 tie → AMBIGUOUS; S3/S5 tombstone persistence; S4 OPEN→OPEN revival (HA-002); S7 published_at > D flagged NO_FALLBACK |
| `oracle_secret_corpus.py` | — | 40 cases, 36 expected hits, 4 expected misses (threshold−1 fragment, hex fragment −2, clean control, split chunks) |

One harness bug was found and fixed during self-test (`sys.exit` inside the `try` of the
subprocess harness made the clean control read as REFUSED); the fixed harness is what ships.

## 5. Not executed

Adapter suite, FRZ-09 on the candidate, TX-01, crash matrix, RDR-01 differential,
mutation review, Windows-specific tests, deviation text review: all blocked on HA-000.
`REPRO_COMMANDS.md` gives the exact commands for each.
