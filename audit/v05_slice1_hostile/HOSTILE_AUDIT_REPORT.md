# PROJECT GENESIS — V0.5 SLICE-1 INDEPENDENT HOSTILE AUDIT

| Field | Value |
| --- | --- |
| Candidate named by the brief | worktree `C:\Users\abbot\fz\g`, branch `v05-slice1-impl`, commit `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` |
| Architecture authority | `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe` (`V05_ADAPTER_ARCHITECTURE.md` r3) — **obtained and read in full** |
| Frozen foundation | `2278e2a68083f7ac58d796b1ed9c43d50020b6b0`, tag `v0.4-foundation-freeze` — **obtained, tree identity recomputed** |
| Audit environment | Linux x86_64, Python 3.11.15, fresh clone of `github.com/abbottjack705-ai/genesis`; no access to the auditor's Windows host, to `C:\Users\abbot\a8\v05_prep\audit_oracle\`, or to `C:\Users\abbot\a8\genesis_lab\C_reliability_audit\` |
| Audit date | 2026-09-29 |
| Package location | `audit/v05_slice1_hostile/` on branch `ccr-c8695f69-sghhe5` (outside any implementation worktree; `cfcff3d` untouched) |

---

## VERDICT

**V0.5 S0–S7 HOSTILE AUDIT — REMEDIATION REQUIRED**

**Basis of the verdict (read this first).** The verdict is a *fail-closed withholding of
certification*, not a code-defect verdict. Commit `cfcff3d` and the eight stage commits
`63e06a1 … cfcff3d` do not exist on any ref of the only repository this audit can reach.
`git fetch origin cfcff3d…` is refused by GitHub (`not our ref`), and the remote holds
exactly four branches (`ccr-dc07c30b-wxq872` = `c8dfafd`, `v0.5-adapters` = `2278e2a`,
`claude/windows-containment-module-qfk13i` = `2278e2a`, `t6-remediation` = `4f11606`).
The branch `v05-slice1-impl` was never pushed. The prepared oracle directory and the
Expedition C material live on the auditor's Windows host and are equally unreachable.

Under the audit's own doctrine (c8dfafd §11.5: "A failure never passes by omission"),
**zero** of the implementer's claims can be marked verified, so GREEN cannot be issued.
The single BLOCKER finding (HA-000) is procedural: make the candidate reachable and
re-run this package. No code remediation is prescribed for `cfcff3d` itself, because
none of its code was examined.

**What this package delivers instead of a verdict on code:**

1. Independent verification of everything that does *not* depend on the candidate
   (§2 below): frozen-tree identity, the frozen-suite baseline, and eight facts about
   the frozen authority that the candidate must respect, three of which are new attack
   material the implementer's test matrix does not obviously cover (HA-001, HA-002,
   HA-011).
2. An executable, self-tested oracle (`oracle/`) that runs against the candidate checkout
   in minutes and covers audit areas 1, 2, 4, 5 (expected table), 6, 7, 9, 12, 13 and 15
   without trusting any implementer scanner, fixture or helper.
3. A complete attack plan with exact reproduction steps for the areas that require the
   candidate (`REPRO_COMMANDS.md`), a pre-analysis of the nine named deviations against
   c8dfafd (`DEVIATION_REVIEW.md`), the F-44 assessment (`F44_ASSESSMENT.md`), and an
   implementation-ready handoff (`REMEDIATION_HANDOFF.md`).

---

## 1. Scope actually executed

| Audit area (brief §) | Status | Where |
| --- | --- | --- |
| 1 Frozen foundation — tree identity of `2278e2a` and `c8dfafd` | **VERIFIED** (six tree SHAs equal the freeze record and §2.1) | `TEST_RESULTS.md` §1 |
| 1 Frozen foundation — tree identity of `cfcff3d` | NOT EXECUTED (unreachable) | `oracle/oracle_frozen_identity.py` |
| 1 FRZ-09 provenance + CRLF fail-closed | NOT EXECUTED on candidate; oracle self-tested against a normalizing guard (caught) and a byte-exact guard (passes) | `oracle/oracle_provenance_crlf.py`, `TEST_RESULTS.md` §4 |
| 1 Frozen suite baseline | **VERIFIED on Linux at `c8dfafd`**: 493 run, 19 skipped, OK | `TEST_RESULTS.md` §2 |
| 2 Request identity / quota / A-2 | Frozen-ledger semantics **VERIFIED** (HA-001, HA-009); candidate NOT EXECUTED | `oracle/oracle_quota_semantics.py`, `REPRO_COMMANDS.md` §A2 |
| 3 Crash recovery / A-3 | Crash-point matrix prepared (16 checkpoints, expected restart behaviour each); NOT EXECUTED | `REPRO_COMMANDS.md` §A3, HA-011 |
| 4 PIT head selection / A-4 | Expected table generated from the **frozen** PIT store (8 scenarios × µs cutoff grid); candidate NOT EXECUTED; authority gap HA-002 found | `oracle/EXPECTED_PIT_HEADS.json` |
| 5 Differential verifier parity / A-5 | Oracle side prepared (frozen `verify_for_pack` rule extracted); candidate NOT EXECUTED | `REPRO_COMMANDS.md` §A5 |
| 6 Secret safety | 40-case corpus generated with expected verdicts (§7.6 forms + adversarial extras); candidate NOT EXECUTED | `oracle/SECRET_CORPUS.json` |
| 7 Transport / time boundary | W1–W4 edge table generated (6 boundaries incl. leap Feb, year end); coarse-clock T1 analysis done; candidate NOT EXECUTED | `oracle/EXPECTED_BOUNDARY_EDGES.json`, HA-008 |
| 8 Schema / status fail-closed | Deviation pre-analysis done; candidate NOT EXECUTED | `DEVIATION_REVIEW.md` |
| 9 Quota / billing | Frozen ceilings **VERIFIED** (250/220/30/7 enforced by `require_operational`; 8th daily unit blocked; reserve never self-authorizes; forged cache hit impossible; HA-003) | `TEST_RESULTS.md` §3 |
| 10 Immutability / corrections | Frozen `immutable_write` / `PITStore.append` semantics read; candidate NOT EXECUTED | `REPRO_COMMANDS.md` §A10 |
| 11 Windows-specific | Cannot be executed on Linux; certification gap and icacls locale hazard recorded | HA-004, HA-005 |
| 12 Test TLS private key | Generic assessment done; oracle prepared | HA-006, `oracle/oracle_tls_key_check.py` |
| 13 24 documented deviations | `SUMMARY.md` unreachable; the nine named deviations pre-classified with the exact condition that decides each | `DEVIATION_REVIEW.md` |
| 14 F-44 | Assessed against c8dfafd in full | `F44_ASSESSMENT.md`, HA-007 |
| 15 Mutation / test quality | Independent scanner and corpus prepared; one impossible-test hazard identified (HA-003) | `oracle/oracle_static_scan.py` |

---

## 2. Independently verified facts (no implementer artefact used)

**2.1 Frozen tree identity.** At both `2278e2a` and `c8dfafd`:

| Tree | Object ID |
| --- | --- |
| `src` | `51cb635bc42b993815b6c02a23c4c3ceb7d98476` |
| `tests` | `e90b298180068fec03ba7e2fa81957082e7fb3ce` |
| `config` | `abd22db01ff482a8da84634ee740ba382b68c804` |
| `tools` | `a0e3411edb4e068fd4708050516cb6870834e7ac` |
| `DECISIONS` | `cc97ec6f841f1e3fbe6dbb57c9cb6e1ac24fdb64` |
| `v04_pack` | `3c3c1c27d80ed6f10c32ac6605a5f438b2e7de12` |

All six equal `V04_FOUNDATION_FREEZE.md` and c8dfafd §2.1. `git diff --stat 2278e2a c8dfafd`
is exactly one file, `V05_ADAPTER_ARCHITECTURE.md` (+2526). No frozen blob is stored with
CRLF (`git ls-files --eol`). The architecture commit is therefore a valid base.

**2.2 Frozen suite baseline (Linux, `c8dfafd`).** `python -m unittest discover -s tests -t . -v`:
`Ran 493 tests`, `OK (skipped=19)`. The 19 skips are all Windows-only containment tests
(9 "Windows OS confinement primitives", 4 "cannot create an AppContainer", 3 "N2 owner
identities caselessly only on Windows", 1 each for 8.3 names, open-file delete, `os.startfile`).
This matches c8dfafd §21 A11 ("the freeze record's 493/1-skip is Windows; Linux skips the
containment tests"). Consequence for FRZ-04: the implementer's "493 OK, 1 skip" is a
*Windows* count; a Linux re-run must be compared with 493/19, not 493/1.

**2.3 Frozen quota ledger facts** (`oracle/QUOTA_SEMANTICS_OUTPUT.json`, produced by running
the frozen `QuotaLedger` with the (250, 220, 30, 7) fixture):

| Fact | Frozen behaviour | Why it matters |
| --- | --- | --- |
| Q-A | `request()` with the same `request_id` **and identical fingerprint** (same `occurred_at`, units, hash) returns the original `allowed=True` decision again, writes **no** row, raises **nothing** | c8dfafd §14.4 promises `RegistryConflict` only for a *new* `occurred_at`. A restart that re-derives the deterministic `request_id` and re-uses a persisted `Tq` is told "allowed" and can re-send under the old debit. **HA-001** |
| Q-B | Same ID, different `occurred_at` → `RegistryConflict("quota request ID cannot be reused with another payload")` | §14.4 as written |
| Q-C | `occurred_at` earlier than the ledger head → **blocked decision** `quota_event_time_regressed`, not an exception | The adapter must map it to a halt (F-03), not to NOT_ATTEMPTED-and-retry-later. **HA-009** |
| Q-D | 8th unit in a UTC day → `daily_quota_exhausted`; 31 days × 7 = **217** units is the most a calendar month can hold at 1 unit/attempt, so `normal_monthly_budget` (220) is **unreachable** with 1-unit debits | §18 Q-03 "221st normal unit → blocked" cannot be reached with 1-unit ODDS calls under the active policy. **HA-003** |
| Q-E | `BudgetClass.RESERVE` with no authorization → blocked `normal_monthly_budget_not_exhausted` | Reserve never self-authorizes |
| Q-F | `billable_units=0` → `ValueError` | Why NON_METERED still debits ≥ 1 (§14.2) |
| Q-G | Day attribution is by `occurred_at` date: 7 units at 23:59:5x and an 8th at 00:00:00.000000 next day is **allowed** | This is precisely the edge §14.6 guards |
| Q-H | Caller-supplied `CachedData(verified=True)` never yields `verified_cache_hit` | A cache hit cannot be forged around the store |

**2.4 Frozen PIT head-selection facts** (`oracle/EXPECTED_PIT_HEADS.json`): tie on `valid_from`
→ `PITViolation` (AMBIGUOUS) from the later `ready_at` onward; tombstone with `valid_to=None`
stays head forever; **S4: a newer OPEN record whose `valid_to` is earlier than the older
OPEN record's `valid_to` makes the OLDER record the unique admissible head again in
`[valid_to_new, valid_to_old)`** under the frozen verifier. c8dfafd forbids revival only for
tombstones (§12.2 rules 4–6) and computes the adapter-only pre-match refusal from the head's
own `scheduled_start_as_known`, which is the *older* (later) kickoff. **HA-002.**

**2.5 Boundary guard.** An independent W1–W4 implementation gives the guard zone
`[23:57:00, 00:02:00)` UTC with (60 s, 120 s) and the seven-point edge pattern
`SEND, refuse, refuse, refuse, refuse, refuse, SEND` at every boundary tested (plain day,
30→31 and 31→30 month, 28 Feb 2027, 29 Feb 2028, 31 Dec 2026). The candidate's BND-01/02
must reproduce this table exactly.

---

## 3. Findings

Severity is as the brief defines it. "Status" says whether the finding was demonstrated on
frozen code (DEMONSTRATED), is a property of the authority text (AUTHORITY), or can only be
settled on the candidate (PENDING). Full fields are in `FINDINGS.csv`.

| ID | Sev | Status | One-line |
| --- | --- | --- | --- |
| HA-000 | BLOCKER | DEMONSTRATED | Candidate `cfcff3d` / branch `v05-slice1-impl` unreachable from any accessible repository; every implementer claim unverified; certification withheld |
| HA-001 | HIGH | DEMONSTRATED (frozen) / PENDING (candidate) | Identical-fingerprint quota replay is silently "allowed" by the frozen ledger; the candidate must never call `request()` for an attempt that already has a `quota_decided` or ledger row, and must never send on a replayed decision |
| HA-002 | MEDIUM | AUTHORITY / PENDING | OPEN→OPEN revival: frozen verifier makes an older OPEN price the unique head again when a newer OPEN record expires first (kickoff moved earlier); c8dfafd §12.2/§12.3 do not cover it; the reader must add an adapter-only refusal or an ADR must accept it |
| HA-003 | LOW | DEMONSTRATED (frozen) | §18 Q-03 "221st normal unit" is unreachable with 1-unit debits (max 217/month); if the candidate's Q-03 claims otherwise it is tautological or uses a test policy without saying so |
| HA-004 | MEDIUM | AUTHORITY / PENDING | Real-symlink refusal branch of the credential loader has only simulated `lstat` coverage; certification of a security boundary needs one run on a Windows host with `SeCreateSymbolicLinkPrivilege` or Developer Mode |
| HA-005 | MEDIUM | PENDING | `icacls` human-readable output is locale-dependent (principal names) and inheritance-flag rich; parsing it fail-closed is fragile. Verify unknown-line → refuse; recommend SDDL via `icacls <file> /save` (locale-independent) |
| HA-006 | LOW | PENDING | Committed `adapters/adapter_tests/fixtures/tls/server.key`: flagged by gitleaks/trufflehog/detect-secrets/GitHub push protection; shipped by `git archive`; must be proven unreachable from runtime paths and marked `export-ignore` |
| HA-007 | INFO | AUTHORITY | F-44 (I/O failure during raw publish): current behaviour is safe and does not violate c8dfafd; it loses diagnostic fidelity (T1, status, headers of a received response) and mislabels the outcome as ORPHANED_RESERVATION; additive semantics are a hardening for a later ADR, not a certification requirement |
| HA-008 | INFO | PENDING | Coarse-clock `T1 > T0` by re-reading the trusted clock is a conforming interpretation (precedent §13.2 step 2) **only if** the loop is bounded by the drift budget (`ClockFault` otherwise), uses no literal sleep (FRZ-10), and stamps T1 after the body is complete |
| HA-009 | INFO | DEMONSTRATED (frozen) | Quota time regression is a blocked *decision* (`quota_event_time_regressed`), not an exception; the candidate must halt on it (F-03) |
| HA-010 | INFO | DEMONSTRATED | Linux frozen-suite baseline is 493/19-skip; FRZ-04 comparisons must be per platform |
| HA-011 | MEDIUM | AUTHORITY / PENDING | Crash between PIT appends of one response: `record_id` is deterministic but `ready_at = T3` is re-stamped on resume, so re-appending the already-appended book raises `RegistryConflict` (permanent halt for that response) unless the adapter recognises the existing record; c8dfafd §14.4/§11.4 do not say which. Verify and pin |
| HA-012 | LOW | PENDING | Expected scope "at Tq" via frozen `as_of_query(source_id=…)` requires a READY capability; before G3 the scope would always be empty and no ABSENT tombstone could ever be produced during G2R, contradicting AC-4's expectation of an observed ABSENT transition. Verify how the candidate computes scope pre-READY |

---

## 4. What would turn this verdict GREEN

1. Push `v05-slice1-impl` (all of `63e06a1 … cfcff3d`) to `origin`, or provide the
   `oracle_out/` directory produced by `oracle/run_oracle.ps1` on the Windows host together
   with `adapters/evidence/S7/SUMMARY.md`.
2. Re-run this package end to end. Every oracle check must PASS, every PENDING finding must
   be closed with evidence, and HA-001/HA-002/HA-011 must each have a candidate test that
   fails on a deliberately broken variant.
3. HA-004 needs one privileged Windows run; HA-006 needs the `export-ignore` attribute and
   the runtime-unreachability proof.

Nothing in this report modifies `cfcff3d`, the frozen trees, or the authority.
