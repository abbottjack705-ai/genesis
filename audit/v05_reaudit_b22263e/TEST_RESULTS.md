# TEST_RESULTS — what actually ran in this re-audit, and what did not

**Environment.** Claude Code cloud session, Linux 6.18 container, Python 3.11.15, git 2.43.0,
OpenSSL 3.0.13. Clone of `abbottjack705-ai/genesis`, every origin ref fetched. Date 2026-10-02 (UTC).

**Not available:**

- the candidate b22263e and the predecessor cfcff3d;
- the Windows host and its paths (`C:\Users\abbot\…`);
- the remediation report, the controlling audit, the oracle directory and the Expedition C material.

**Everything below ran against reachable commits or against the re-auditor's own tools.** No result in this
file is a statement about b22263e, except §0, which records that it cannot be reached.

## 0. Pinning the candidate — CANNOT RUN (RA-000)

Transcript: `evidence/pin_transcript.txt`. Driver output: `evidence/driver_b22263e/`.

| Attempt | Result |
| --- | --- |
| `git ls-remote origin` | 7 refs: `ccr-c8695f69-sghhe5`→37b86fb, `ccr-dc07c30b-wxq872`→c8dfafd, `claude/windows-containment-module-qfk13i`→2278e2a, `t6-remediation`→4f11606, `v0.5-adapters`→2278e2a, tag `v0.4-foundation-freeze`→a5ca3c9 (peeled 2278e2a), HEAD→4f11606 |
| fetch all heads and tags | no b22263e, no cfcff3d, no stage commit 63e06a1…9c35c5c |
| `git fetch origin cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` | `fatal: remote error: upload-pack: not our ref …` (exit 128). Not in the repository's object store at all |
| GitHub API `get_commit` b22263e / cfcff3d | `No commit found for SHA` (both) |
| GitHub pull requests (all states) | none |
| Connected Google Drive search | one unrelated V0.4 file (`SOL_HOSTILE_AUDIT_v0.4.md`, 2026-09-20) |
| `run_reaudit.py --candidate b22263e` | `R00 CANNOT_RUN`, exit 2 |

## 1. Frozen foundation identity (attack area 1, reachable commits only) — PASS

The six tree SHAs are identical at the certified baseline 4f11606, the tag target 2278e2a, the authority
c8dfafd and the prior-audit commit 37b86fb:

| Tree | SHA |
| --- | --- |
| `src` | `51cb635b…8476` |
| `tests` | `e90b2981…b3ce` |
| `config` | `abd22db0…c804` |
| `tools` | `a0e3411e…34e7ac` |
| `DECISIONS` | `cc97ec6f…db64` |
| `v04_pack` | `3c3c1c27…7de12` |

All equal the values in c8dfafd §2.1.

- **Tag.** `v0.4-foundation-freeze` = annotated tag a5ca3c96 → commit 2278e2a.
- **Authority.** Blob `30c4ca7d43fe11504e873e25944f9bdd30079253`.
- **Authority diff.** `git diff --stat 2278e2a c8dfafd` = `V05_ADAPTER_ARCHITECTURE.md` only (+2526).
- **Frozen-tree diff.** `git diff --name-status 2278e2a c8dfafd -- <six trees>` is empty.

## 2. Frozen suite at c8dfafd, Linux — PASS (HA-010 re-confirmed)

```text
$ python3 -B -m unittest discover -s tests -t .          (clean detached worktree at c8dfafd)
Ran 493 tests in 126.094s
OK (skipped=19)
```

- **Log:** `evidence/frozen_suite_c8dfafd_linux.log`.
- **FRZ-03:** `git status --porcelain -- <six trees>` was empty afterwards; only the ignored `__pycache__`.
- **Baselines:** this equals the Linux baseline of the 37b86fb package (493 / 19). The Windows baseline
  (493 / skipped=1) is from the freeze record and 37b86fb; it was not re-run here.
- **Warning:** the suite prints a `UserWarning: Duplicate name: 'git-blobs/source/program.py'` from a frozen
  test's zip writer. This is frozen behaviour.

## 3. Frozen suite with all network access blocked — PASS (attack area 24, foundation part)

**Run.** The re-auditor's audit-hook block (`reaudit/netblock_site/`) was installed in the parent process
and in every child Python process, through `sitecustomize`. With it, the frozen suite ran in a fresh clone
whose six trees equal c8dfafd's (the driver self-test GOOD commit):

```text
Ran 493 tests in 136.259s
OK (skipped=19)
```

**Coverage.** Across that run (the frozen suite plus the one-process synthetic adapter suite), 249 Python
processes installed the block. They made zero non-loopback connect or resolve attempts. The only network
events in the log are the synthetic loopback test's own two (127.0.0.1).

**Evidence.** `evidence/selftest_driver/GOOD/{frozen_suite.log, netblock_attempts.jsonl}`.

**Scope.** This proves the **frozen** suite is network-free. The candidate's adapter suite was not run
(no candidate).

**Block self-test** (`evidence/selftest_netblock.txt`):

| Attempt | In-process | In a child process |
| --- | --- | --- |
| connect to 192.0.2.1 | BLOCKED | BLOCKED |
| resolve example.com | BLOCKED | BLOCKED |
| resolve api.oddspapi.io | BLOCKED | BLOCKED |
| 127.0.0.1 / localhost | allowed | allowed |

Without the block, the same resolution succeeds (control).

## 4. FRZ-09 expectation and the CRLF precondition (attack areas 1–2) — PASS

- `evidence/FRZ09_EXPECTED_ENTRIES.json` was generated independently from `git ls-tree -r 51cb635…`. It
  holds 36 modules, each with its blob SHA-1 (verified as `sha1("blob <n>\0"+bytes)`) and SHA-256. No
  frozen blob contains CR. Its SHA-256 is `11e6518d…2349`. Any b22263e manifest must equal it entry for
  entry; driver check R02 compares them in a layout-agnostic way.
- In an LF worktree at c8dfafd, **36/36** modules match their blob SHA-256.
- In a `core.autocrlf=true` checkout on Linux (`git ls-files --eol` shows `i/lf w/crlf`), **0/36** match.
  A correct FRZ-09 guard must therefore refuse that checkout (A-1). The driver's R03 performs exactly this
  attack against the candidate.

## 5. Prior oracle regenerated on Linux — PASS (the yardstick is sound)

**Package integrity.** The 37b86fb package was extracted from Git. Its `ARTIFACT_MANIFEST.sha256` verifies
74/74.

**Regeneration.** Its four candidate-independent generators were re-run against the frozen code at c8dfafd
(`evidence/oracle_regen_c8dfafd_linux/`):

| Oracle | Output vs the committed file |
| --- | --- |
| `oracle_pit_head_expected.py` | `EXPECTED_PIT_HEADS.json` **identical** (dd01e290…) |
| `oracle_boundary_guard_edges.py` | `EXPECTED_BOUNDARY_EDGES.json` **identical** (58e60a64…) |
| `oracle_secret_corpus.py` | `SECRET_CORPUS.json` **identical** (cd35b1ea…; 40 cases, 36 expected hits) |
| `oracle_quota_semantics.py` | `QUOTA_SEMANTICS_OUTPUT.json` **identical** (Q-A…Q-H) |

The comparison normalized line endings to LF.

## 6. Re-auditor tools: self-tests — PASS

### Driver self-test — `run_reaudit.py`, 22/22 expectations met

Evidence: `evidence/selftest_driver/`.

**GOOD candidate.** A synthetic candidate on top of c8dfafd with a minimal `adapters/` tree. It passes every
check (45 PASS, 3 INFO, 2 REVIEW, 0 FAIL, 0 CANNOT_RUN), including:

- the CRLF refusal;
- export-ignore of a test key;
- all 167 test IDs present (166 tabled in §18, plus FM-11b);
- both suites run under the network block.

**BAD variants.** Each fails exactly the check family it targets:

| Variant | What it breaks | Checks that fail |
| --- | --- | --- |
| B1 | a file under `src/` | tree SHA, adapters-only |
| B2 | one wrong manifest hash | FRZ-09 parity |
| B3 | a guard that normalizes CRLF | A-1 |
| B4 | `--ca-file` on `run`, `--at` on `approve-ready` | trust seam, operator time |
| B5 | network import, `except KeyboardInterrupt`, `return` in `finally`, a literal timeout, `sleep` | FRZ-06, FRZ-11 ×2, FRZ-10; sleep → REVIEW |
| B6 | a key and certificate for `api.oddspapi.io` without export-ignore | export-ignore, archive, certificate SAN |
| B7 | BND-04 removed | test-ID set |
| B8 | a test connecting to 192.0.2.1 | no-network |

### Other tools

| Tool | Result | Evidence |
| --- | --- | --- |
| `mutate_sites.py` | 7/7 expectations met | `evidence/selftest_mutate_sites.txt` |
| `probes/p20_deadline_stages.py` against mock transports | the correct mock passes; GT, EARLY_T0, ZERO_TO and LATE_READ each fail on their defect (D1; D1+D3; D1+D2; D4) | `evidence/selftest_p20.txt` |
| probes p20–p25 against a tree with no candidate | every probe exits **2** (CANNOT_RUN), never 0 | `evidence/probe_dryrun_without_candidate.txt` |

The `mutate_sites.py` results:

| Mutant | Result |
| --- | --- |
| deadline `<` → `<=` | KILLED |
| 8 reset-authority mutants | KILLED |
| polling `>=` → `>` on a stalled clock | TIMEOUT |
| the equivalent site | SURVIVED |

It also never mutates unchanged lines and restores the checkout byte-for-byte.

## 7. NOT RUN — every attack area against b22263e

Each row names the decisive command. All are in `reaudit/run_all.sh` and `REPRO_COMMANDS.md` §B.

| # | Attack area | Status | Decisive check |
| --- | --- | --- | --- |
| 1 | Frozen tree identity / FRZ-09 at b22263e | NOT RUN | driver R01, R02; oracle 01/02 |
| 2 | CRLF checkout fail-closed | NOT RUN | driver R03; a01 |
| 3 | Request identity / old-debit replay / may-have-sent | NOT RUN | a02_a03 C01–C08 |
| 4 | Raw publication crash recovery | NOT RUN | a02_a03 C07a/b, C08a/b; p23 |
| 5 | PIT unique head, ties, stale/newer blocking | NOT RUN | a04 vs the regenerated table |
| 6 | Invalidation crash/restart convergence | NOT RUN | p22; a02_a03 C14–C16 |
| 7 | Rejected/quarantined evidence across restart | NOT RUN | p21 |
| 8 | Hard deadline equality | NOT RUN | p20 D1–D5; a07 |
| 9 | Coarse clocks, rollback, guard windows, UTC boundaries | NOT RUN | a07 (edge table regenerated identically); CLK tests |
| 10 | Credential containment, disclosure paths | NOT RUN | a06, a07 TX-01, a11, driver R04/R05 |
| 11 | Sanitized exception records and secret scanning | NOT RUN | a07 TX-01; driver R04 exception-text sites |
| 12 | KeyboardInterrupt/SystemExit clean context | NOT RUN | a07 TX-01; driver R04 FRZ-11 |
| 13 | Redirect, TLS, CA trust | NOT RUN | p21 (302); a12; driver R04/R05 |
| 14 | Unknown schema/status/content | NOT RUN | a08; p21 (`text/html`) |
| 15 | Tournament omission vs genuine ABSENT | NOT RUN | p24 |
| 16 | Quota debit vs provider billability | NOT RUN | oracle 09 (frozen facts identical); BILL-01…05 at b22263e |
| 17 | Reserve authority | NOT RUN | driver R04 FRZ-07 |
| 18 | G2/G2R gate and limit pinning | NOT RUN | p25 L1–L2; a14 |
| 19 | READY/grant time | NOT RUN | p25 A1–A5; a13 |
| 20 | Security-halt reset authority | NOT RUN | p25 R1–R6 |
| 21 | Corrections, supersession, immutability | NOT RUN | a10 |
| 22 | Deterministic replay (claim: 128 byte-identical files) | NOT RUN | PIT-09 at b22263e; the implementer's replay command, re-run twice and diffed |
| 23 | Mutation quality, equivalent survivor | NOT RUN | `mutate_sites.py`; a15; MUTATION_REVIEW |
| 24 | No-network guarantee (adapter suite) | NOT RUN (frozen suite PASS, §3) | driver R07 |
| 25 | Remediation-era deviations | NOT RUN | remediation report + PRIOR_FINDING_CLOSURE_MATRIX, deviations section |

## 8. Implementer claims

| Claim | Status here |
| --- | --- |
| Adapter suite 690 OK, 1 real-symlink skip | NOT VERIFIED. The skip is itself RA-001 |
| Frozen suite 493 OK, identical to baseline | NOT VERIFIED at b22263e. Linux baseline re-confirmed at c8dfafd (493 / 19); Windows baseline is 493 / 1 per the record |
| All 167 architecture test IDs present | NOT VERIFIED at b22263e. **Count consistent:** §18 tables 166 IDs, and FM-01…43 "including F-11b" makes 167. Driver R06 checks presence |
| All 17 controlling repro probes NOT REPRODUCED | NOT VERIFIED (probes unavailable) |
| Deterministic replay: 128 byte-identical durable files | NOT VERIFIED |
| Mutation: 128 / 127 killed / 1 equivalent; R3 timeout rerun killed in 91 s | NOT VERIFIED; equivalence NOT ACCEPTED (MUTATION_REVIEW) |
| Secret sweep clean | NOT VERIFIED (driver R05 does it over the history authority..candidate) |
| Compile / diff / provenance / freeze checks pass | NOT VERIFIED at b22263e |
| Six frozen tree SHAs unchanged | VERIFIED on every reachable commit; NOT VERIFIED at b22263e |
| Nothing outside `adapters/` changed | NOT VERIFIED (driver R01 checks it, including predecessor..candidate) |
| No credentials, provider calls, G2, READY or live betting | NOT VERIFIED (driver R04/R05/R07 and p25 check the code-visible parts) |
