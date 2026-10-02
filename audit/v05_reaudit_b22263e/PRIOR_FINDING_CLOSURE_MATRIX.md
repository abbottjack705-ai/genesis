# PRIOR_FINDING_CLOSURE_MATRIX — b22263e against every prior finding

**Vocabulary.** The required classes are CLOSED, PARTIALLY CLOSED, STILL REPRODUCIBLE, REGRESSED,
SUPERSEDED and NON-FINDING. This re-audit adds one class, **NOT DETERMINABLE**: the decisive evidence
needs b22263e, which is unreachable (RA-000).

A NOT DETERMINABLE row is **not** closed, and it counts against certification. No row below is classified
CLOSED: closing a finding requires running its decisive check against b22263e.

**Two prior audits exist.**

| Part | Audit | Where | What this re-audit knows of it |
| --- | --- | --- | --- |
| **A** | the **controlling** cfcff3d audit (7 BLOCKERs, 17 repro probes) | local only: `C:\Users\abbot\a8\v05_prep\audit_oracle\hostile_audit_cfcff3d\` | only the one-line class descriptions in the request (RA-003) |
| **B** | the origin-hosted cfcff3d audit, `37b86fb`, `audit/v05_slice1_hostile` (HA-000…HA-017) | origin | read in full; manifest verified 74/74 |

The finding semantics in Part A are therefore reconstructed from the request and the authority, not from
the controlling text. Each row states the closure criterion this auditor will apply.

## Part A — controlling audit (classes named in the request)

| Ref | Prior class (request wording) | Classification on b22263e | Closure criterion (c8dfafd) | Decisive check(s) | Re-auditor note |
| --- | --- | --- | --- | --- | --- |
| CB-1 | BLOCKER: credential disclosure paths | NOT DETERMINABLE | No §7.6 form of the key in any durable byte, stdout, stderr, log, exception record or traceback local. Scan precedes every durable write. Uninspectable bodies are never persisted (§7.6, §7.7, D15, F-11/F-11b, REQ-04, SEC-01…05, TX-01) | a06 (corpus 40 cases + pipeline), a07 TX-01, driver R04 "exception text extraction sites", R05 history sweep | The exact disclosure paths of the controlling audit are unknown. Every R04 REVIEW site (`str(exc)`, `exc.args`, f-string of an exception, traceback text) must be shown to be scanned or never persisted |
| CB-2 | BLOCKER: send at the hard deadline | NOT DETERMINABLE | No request byte written when T0 ≥ `Tq + request_timeout_seconds`. Abort at the deadline. T0 read immediately before the first byte. No zero or `None` socket timeout. No RESPONSE with T1 ≥ deadline (§14.6 rule 3, §6.2, BND-04) | **p20 D1–D5** (self-tested against 4 broken mocks), a07, mutants in MUTATION_REVIEW §4 | 37b86fb a07 tested only T0 == deadline at the start of `send` (RA-004) |
| CB-3 | BLOCKER: rejected evidence becoming usable after restart | NOT DETERMINABLE | A rejected or quarantined response never yields a normalized document or PIT record, before or after a crash and restart. Resume re-applies the status, skew and content-type checks (§11.1, §14.4, F-06…F-14) | **p21 R1–R4** (valid body carried by every rejection; crash after `completed`) | Not attacked by 37b86fb (RA-006) |
| CB-4 | BLOCKER: PIT recovery failures | NOT DETERMINABLE | A crash at any emission checkpoint resumes to the baseline artifacts and record IDs: exactly one observation per artifact, one PIT record per book, `ready_at ≥ parse_ready_at ≥ T1`, `verify_all` total (§11.4, PIT-08, PIT-09) | a02_a03 C09–C13; driver R07 adapter suite | 37b86fb passed these on cfcff3d. The remediation may have changed the resume path |
| CB-5 | BLOCKER: invalidation recovery failures | NOT DETERMINABLE | A durably recorded invalidation becomes effective after restart without operator re-issue. Exactly one recorded, one applied and one INVALIDATED PIT record. Earlier cutoffs unchanged (§13.2, INV-01…04) | **p22 I1–I6**, a02_a03 C14–C16 | 37b86fb C14–C16 recovered only by re-issue (RA-005) |
| CB-6, CB-7 (and any further) | "all other BLOCKERs in HOSTILE_AUDIT_REPORT.md" | NOT DETERMINABLE (text unavailable) | — | the controlling audit's own 17 repro probes, re-run | The count of distinct BLOCKERs behind CB-1…CB-5 is unknown. At least two further BLOCKERs exist if the five classes are one each |
| CO-1 | Sanitized exception secret scanning | NOT DETERMINABLE | The sanitized record `{class, errno}` and any recorded exception text pass `scan_for_secret` before write (§7.6 item 3, §7.7(a)) | a07 TX-01, driver R04, a06 | — |
| CO-2 | Omitted requested tournament completeness | NOT DETERMINABLE | Omission of a requested tournament yields no ABSENT. A genuine absence in a complete response does (§12.4, F-15, F-30) | **p24 T1 + T2** | Over-correction is checked too (RA-007) |
| CO-3 | Architecture-fixed / gate-limit pinning | NOT DETERMINABLE | G2 ≤ 5 requests and ≤ 72 h, G2R ≤ 35 days, not widenable by an edited or operator-selected config (§16.3, §16.4, §16.6) | a14, **p25 L1–L2** | Same as HA-015 |
| CO-4 | Retrospective READY / operator-chosen approval time | NOT DETERMINABLE | READY `recorded_at` and gate `granted_at` come from the trusted clock at approval. A G2R UNKNOWN anchor exists. No cutoff before approval replays as usable (§16.2, §16.4, §16.5) | a13, **p25 A1–A5**, driver R04 (no time flag on approval parsers) | Same as HA-013 |
| CO-5 | SECRET_ECHO reset authority | NOT DETERMINABLE | After SECRET_ECHO or AUTH_REJECTED, sends stay halted until a G1 granted after the halt names a different credential fingerprint (§7.6, §14.3) | **p25 R1–R6** (both halt kinds), a13 last check | Same as HA-014, extended to AUTH_REJECTED and to G1 records that predate the halt |
| CO-6 | Test TLS / CA seams | NOT DETERMINABLE | The live transport trusts only the system store. No CA or connect option in a production parser. A test key ships in no archive and names no provider host (§7.6, §19 S7) | driver R04 (CLI trust seam), R05 (export-ignore, archive, certificate SAN), a12 | Same as HA-006 |
| CO-7 | G2/G2R configuration authority | NOT DETERMINABLE | The G2R `plan_digest`, `derivation_version` and `policy_digest` are compared with the running plan and config (§16.4, §16.6) | p25 L1, a14; a dedicated G2R `plan_digest` probe once the candidate's API is visible | Same as HA-015, second half |
| CO-8 | Crash/restart durability | NOT DETERMINABLE | The 16-checkpoint crash matrix: no resend under an old debit, orphan reconciliation, resume to baseline (§11.1, §14.4) | a02_a03 C01–C16, p21, p22, p23 | — |

## Part B — origin-hosted audit 37b86fb (HA-000…HA-017)

| ID | Prior status (cfcff3d) | Classification on b22263e | Basis / decisive check |
| --- | --- | --- | --- |
| HA-000 | INFO (was BLOCKER): candidate not on origin | **STILL REPRODUCIBLE** (now RA-000, BLOCKER) | Reproduced for b22263e *and* cfcff3d: `not our ref`, `No commit found` (`evidence/pin_transcript.txt`) |
| HA-001 | CLOSED | NOT DETERMINABLE | a02_a03 C01–C08: 0 sends, 0 `reserve()` after restart |
| HA-002 | CLOSED | NOT DETERMINABLE | a04 against `EXPECTED_PIT_HEADS.json` (regenerated identically here) |
| HA-003 | CLOSED | NOT DETERMINABLE | Read the Q-03 test at b22263e |
| HA-004 | OPEN (needs a privileged run) | **OPEN — not closed by the candidate's own account** (RA-001, CERTIFICATION GAP) | The implementer reports the real-symlink test still skips. Not independently re-run (no candidate, no Windows) |
| HA-005 | CLOSED; residual INFO | NOT DETERMINABLE | a11 real ACLs plus the localized parser table |
| HA-006 | CONFIRMED (LOW) | NOT DETERMINABLE (claimed remediated) | driver R04 / R05, a12 K2 / K3 |
| HA-007 | ASSESSED (F-44 safe, not blocking) | **SUPERSEDED** by this package's `F44_ASSESSMENT.md` (RA-002): REQUIRED BEFORE G2 | New consequence: protective halts can be pre-empted (§11.1 order) |
| HA-008 | CLOSED | NOT DETERMINABLE | a07 clocks, p20 |
| HA-009 | CLOSED | NOT DETERMINABLE | Q-07 / a07 |
| HA-010 | CONFIRMED platform fact | **NON-FINDING** (re-confirmed) | Linux at c8dfafd: 493 / skipped=19, here twice, the second time with the network block. The Windows baseline 493 / skipped=1 is from the record |
| HA-011 | CLOSED (reuse pinned) | NOT DETERMINABLE | a02_a03 C11a–C11d |
| HA-012 | CLOSED | NOT DETERMINABLE; reasoning partly SUPERSEDED by RA-007 | a10 HA-012, p24 |
| HA-013 | CONFIRMED (MEDIUM) | NOT DETERMINABLE (claimed remediated) | a13, p25 A1–A5, driver R04 |
| HA-014 | CONFIRMED (LOW) | NOT DETERMINABLE (claimed remediated) | a13, p25 R1–R6 |
| HA-015 | CONFIRMED (LOW) | NOT DETERMINABLE (claimed remediated) | a14, p25 L1–L2 |
| HA-016 | REVIEWED (oracle harness) | **NON-FINDING** for the candidate | Oracle unchanged. Its PIT, edge, corpus and quota outputs regenerate byte-identically on Linux |
| HA-017 | OPEN (human): no ADR-A001 | NOT DETERMINABLE (RA-010) | No `adapters/` tree on any origin ref |

## Remediation-era deviations (attack area 25)

The remediation's own deviation list is in the unreachable remediation report. None of it is reviewed
here. Of the 24 cfcff3d deviations (37b86fb `DEVIATION_REVIEW.md`), these touch the remediated surface and
**must be re-reviewed at b22263e**:

| Item | Subject | Related finding |
| --- | --- | --- |
| 10 | `complete_hint` | CO-2 / RA-007 |
| 12, 15 | gate limits and `LIVE_SEND` | CO-3 / CO-7 |
| 13 | operator times and `reset` | CO-4 / CO-5 |
| 16 | symlink skip | RA-001 |
| 19 | strict credential file | RA-008 |
| 20, 24 | CA seam and test key | CO-6 |

Every new deviation must be classified with the 37b86fb vocabulary: CONFORMING INTERPRETATION, STRICTER
BUT SAFE, AUTHORITY AMBIGUITY, UNAUTHORIZED SEMANTIC CHANGE or DEFECT.
