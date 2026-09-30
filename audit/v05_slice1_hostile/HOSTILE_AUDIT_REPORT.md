# PROJECT GENESIS — V0.5 SLICE-1 INDEPENDENT HOSTILE AUDIT

| Field | Value |
| --- | --- |
| Candidate | `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` (branch `v05-slice1-impl`, S0 `63e06a1` … S7 `cfcff3d`) — **obtained and audited** (session 2) |
| Architecture authority | `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe` (`V05_ADAPTER_ARCHITECTURE.md` r3, blob `30c4ca7…`) — read in full |
| Frozen foundation | `2278e2a68083f7ac58d796b1ed9c43d50020b6b0`, tag `v0.4-foundation-freeze` — six tree SHAs verified at `c8dfafd` and at `cfcff3d` |
| Audit environment | Session 1: Linux, Python 3.11.15 (candidate unreachable). Session 2: Windows 11, Python 3.12.10, Git Bash, fresh `--no-hardlinks` clones of the candidate (LF and `core.autocrlf=true`) |
| Audit dates | 2026-09-29 (session 1), 2026-09-29/30 (session 2) |
| Package | `audit/v05_slice1_hostile/` on branch `ccr-c8695f69-sghhe5`; nothing in `cfcff3d`, the frozen trees or the authority was modified |

---

## VERDICT

**V0.5 S0–S7 HOSTILE AUDIT — REMEDIATION REQUIRED**

**Basis.** The candidate's core safety machinery holds under independent attack: frozen-foundation
identity and runtime provenance (including the CRLF fail-closed rule), request identity and quota replay,
a 16-checkpoint crash matrix, PIT head selection with verifier parity (135 cutoffs against the frozen
`verify_for_pack`), secret safety through the real runtime, the transport exception boundary and time
rules, and schema/status fail-closed behaviour all passed. Every previously PENDING finding about those
properties (HA-001, HA-002, HA-003, HA-005, HA-008, HA-009, HA-011, HA-012) is **closed with evidence**.

Certification is nevertheless withheld because:

1. **HA-013 (MEDIUM, new, confirmed):** the operator commands take their times from the operator, not
   from the trusted clock. `approve-ready` writes the READY capability row with `recorded_at = --at`,
   `approve` stores a gate record's `granted_at` exactly as written in the record file, and no runtime
   code registers the G2R `UNKNOWN` row that would anchor the capability timeline. A READY row can
   therefore be dated before the approval — demonstrated: a cutoff taken between a capture and the
   approval replays as usable. This contradicts c8dfafd §16.5 (`recorded_at=now`), §16.2 (`granted_at`
   from the trusted clock) and §16.4, is not among the 24 documented deviations, and is an
   **unauthorized semantic change** affecting the PIT integrity of the READY gate.
2. **HA-006 (LOW, confirmed):** a private key matching a certificate for the real provider host
   `api.oddspapi.io` is committed, ships in `git archive`, and the **production** `run` command accepts
   `--ca-file` (with a loopback `--connect`), so the live transport can be made to trust only that test
   CA. Session 1 made `export-ignore` and runtime unreachability explicit GREEN conditions; neither holds.
3. **HA-004 (MEDIUM, open):** the real-symlink refusal of the credential loader is still certified only by
   a simulated `lstat`; this Windows account lacks the symlink privilege (`winerror 1314`), so the one
   privileged run the finding requires could not be made. It is recorded as outstanding, not waived.

No CRITICAL or HIGH finding is open. The implementation-level remediation is small (see
`REMEDIATION_HANDOFF.md` R1, R2); HA-004 needs only a privileged run.

**Two checks are incomplete, and both are required before GREEN.** The candidate's own adapter suite
could not be run to completion in isolation: its clean portion passed 411 of 573 tests with no failure
before the host reaped it for low memory, and an earlier full run that overlapped a parallel audit session
(`errors=16`, 12 h) is not used as evidence either way. The mutation attack (`attacks/a15_mutation.py`) was
prepared but not run for the same reason. Neither changes this verdict: a complete run could only add
findings, and the confirmed findings above already require remediation.

**Independence disclosure (read with the verdict).** This session runs on the same model family that
authored the S4–S7 commits (their trailers name it), and the host's shared memory index held notes written
by the implementing session. Those notes and every implementer artefact (transcripts, counts, SUMMARY
claims, test helpers) were treated as untrusted: every conclusion above rests on the auditor-written oracle
and attacks, which import only the candidate's production package, the frozen `genesis` package and the
committed fixture *files*. Whether this review meets the "independent hostile review" standard of
c8dfafd §16.5 AC-9 is for the human owner to decide. A second agent session audited the same candidate on
the same host concurrently (`C:\Users\abbot\aud\`); its results were not read before this verdict was fixed
and are not relied on.

---

## 1. Scope executed (session 2)

| Audit area | Status | Evidence |
| --- | --- | --- |
| 1 Frozen foundation: tree identity, diff scope, no-touch list, LF blobs, stage chain | **PASS** (I-1…I-7) | `oracle_out_win_cfcff3d/01_frozen_identity.json` |
| 1 FRZ-09 manifest parity and provenance guard | **PASS** (P-2, P-3 CRLF refused, P-4; P-1 criterion via `a01`: 36/36) | `02_provenance_crlf.json`, `attack_out/a01.json` |
| 1 A-1 CRLF checkout | **PASS**: guard refuses `MODULE_HASH_MISMATCH`; suite fails closed | `a01` |
| 1 Frozen suite at `cfcff3d` | **PASS**: 493 / skipped=1 (Windows baseline) | `frozen_suite_tail.txt` |
| 1 `diff --check`, `compileall`, FRZ-03 | **PASS** | TEST_RESULTS §1 |
| Adapter suite (candidate's own) | **NOT COMPLETED**: clean portion 410 ok / 1 skipped / 0 failed over 411 of 573 tests, then reaped for host memory; the first full run (errors=16, 12 h) overlapped a parallel session and is not used | `adapter_suite_rerun_full.txt`, TEST_RESULTS §4 |
| 2 Request identity / quota / A-2 (HA-001) | **PASS**, HA-001 closed | `a03` C01–C08 |
| 3 Crash recovery / A-3, 16 checkpoints (HA-011) | **PASS**, HA-011 closed (reuse pinned) | `a03`, `a03_c07_rerun` |
| 4/5 PIT head selection and verifier parity (HA-002) | **PASS**, HA-002 closed | `a04`, `a04.table.json` |
| 6 Secret safety | **PASS** (corpus 0/40 mismatches; 16/16 pipeline) | `06_secret_corpus.txt`, `a06` |
| 7 Transport / time boundary (HA-008) | **PASS**, HA-008 closed | `a07` |
| 8 Schema / status fail-closed | **PASS** (21/21) | `a08` |
| 9 Quota / billing | **PASS** (frozen Q-A…Q-H reproduce on Windows; HA-003 closed; HA-009 closed) | `09_quota_semantics.txt` |
| 10 Immutability / corrections (HA-012) | **PASS**, HA-012 closed | `a10` |
| 11 Windows-specific (HA-004, HA-005) | HA-005 closed; **HA-004 open** (symlink not creatable on this account) | `a11` |
| 12 Test TLS private key (HA-006) | **FAIL** — HA-006 confirmed | `12_tls_key.txt`, `a12` |
| 13 The 24 deviations | reviewed item by item | `DEVIATION_REVIEW.md` |
| 14 F-44 | assessed; safe, not blocking | `F44_ASSESSMENT.md` |
| 15 Mutation / test quality | **NOT RUN** (18 mutants prepared; host memory) | `attacks/a15_mutation.py` |
| — Operator gate times (new) | **FAIL** — HA-013, HA-014, HA-015 | `a13`, `a14` |

## 2. Independently verified facts

**2.1 Frozen tree identity.** At `2278e2a`, `c8dfafd` and `cfcff3d`: `src 51cb635b…`, `tests e90b2981…`,
`config abd22db0…`, `tools a0e3411e…`, `DECISIONS cc97ec6f…`, `v04_pack 3c3c1c27…`. All 185 changed paths
since `c8dfafd` are under `adapters/`.

**2.2 Frozen suite baselines.** Windows at `cfcff3d`: 493 / skipped=1. Linux at `c8dfafd`: 493 /
skipped=19 (HA-010). FRZ-04 comparisons must be per platform.

**2.3 Frozen quota facts** (Q-A…Q-H, `oracle/QUOTA_SEMANTICS_OUTPUT.json`) reproduce unchanged on Windows.
In particular Q-A: the frozen ledger re-answers an identical-fingerprint request `allowed` with no new row;
the candidate's protection against a replay is its acquisition ledger, which the crash matrix proves holds
at every pre-completion checkpoint (0 sends, 0 `reserve()` calls after restart).

**2.4 Frozen PIT facts** (`oracle/EXPECTED_PIT_HEADS.json`, regenerated identically on Windows). The S4
OPEN→OPEN revival exists in the frozen verifier (it accepts the older record in
`[valid_to_new, valid_to_old)`); the candidate refuses it with `STALE`.

**2.5 Boundary guard.** The candidate's W1–W4 guard equals the independent table at every edge of six
boundaries (plain day, 30→31, 31→30, 28 Feb 2027, 29 Feb 2028, year end) and reschedules to the first
permitted microsecond.

## 3. Findings

Full fields in `FINDINGS.csv`. Status vocabulary: CLOSED (evidence shows the property holds), CONFIRMED
(evidence shows the defect), OPEN (not decidable in this environment), plus INFO items.

| ID | Sev | Status | One-line |
| --- | --- | --- | --- |
| HA-000 | INFO (was BLOCKER) | CLOSED for this audit; push OPEN | Candidate still not on origin; obtained from the local branch and bound by SHA |
| HA-001 | HIGH (frozen fact) | CLOSED | Identical-fingerprint quota replay cannot be reached: a known attempt is never re-requested (0 sends, 0 `reserve()` after every crash) |
| HA-002 | MEDIUM | CLOSED | OPEN→OPEN revival refused by the reader (`STALE`) at every cutoff where the frozen verifier revives |
| HA-003 | LOW | CLOSED | Q-03 reaches 220 with a visible test policy and blocks the 221st |
| HA-004 | MEDIUM | OPEN | Real-symlink refusal still needs one privileged Windows run (`winerror 1314` here) |
| HA-005 | MEDIUM | CLOSED | `icacls` parsing is fail-closed on real NTFS ACLs and on localized/unknown outputs; SID comparison recommended |
| HA-006 | LOW | CONFIRMED | Committed key for a `api.oddspapi.io` cert ships in `git archive`; the live CLI accepts an injected CA |
| HA-007 | INFO | ASSESSED | F-44 is safe, not a violation, not blocking (`F44_ASSESSMENT.md`) |
| HA-008 | INFO | CLOSED | Coarse-clock `T1` re-read is bounded, literal-free and halts on a stuck clock |
| HA-009 | INFO | CLOSED | Quota time regression halts `CLOCK_FAULT` |
| HA-010 | INFO | CONFIRMED | Platform baselines 493/1 (Windows) and 493/19 (Linux) |
| HA-011 | MEDIUM | CLOSED | Mid-append crash: already-appended PIT records are reused; response may carry two `ready_at` values (safe) |
| HA-012 | LOW | CLOSED | Expected scope ignores READY; ABSENT tombstones are produced during G2R |
| **HA-013** | **MEDIUM** | **CONFIRMED (new)** | READY row / gate `granted_at` take operator-chosen times; no G2R UNKNOWN anchor; retroactive READY demonstrated |
| HA-014 | LOW | CONFIRMED (new) | `reset` clears a `SECRET_ECHO` / `AUTH_REJECTED` halt without a re-G1 |
| HA-015 | LOW | CONFIRMED (new) | G2/G2R bounds live in an unpinned, operator-selectable config file (a 50-request, 1000-hour G2 record accepted); G2R `plan_digest` unchecked |
| HA-016 | INFO | REVIEWED | Oracle harness mismatches (P-1 layout, P-5/X-11 token heuristics, X-05 exception subclasses) - not candidate defects; oracle unchanged |
| HA-017 | INFO | OPEN (human) | No G0 record (`ADR-A001`) in `adapters/DECISIONS/` |

## 4. What turns this verdict GREEN

1. R1 (HA-013) and R2 (HA-006) of `REMEDIATION_HANDOFF.md`, each with its RED→GREEN regression test, on
   commits added after `cfcff3d`.
2. One privileged Windows run of `attacks/a11_windows_credential.py` with the symlink case refused (HA-004).
3. A re-run of this package from a fresh clone of the remediated head, on a host with no other suite
   running: every `attacks/a*.py` check PASS (a13 included; a14 if R4 is taken), the frozen suite 493 /
   skipped=1, the candidate's adapter suite fully GREEN in an isolated run (not yet achieved here), every
   `a15` mutant killed or explained, FRZ-03 clean.

R3–R6 (HA-014, HA-015, HA-005 residual, F-44) are recommended hardening before G1 and do not by
themselves block GREEN.
