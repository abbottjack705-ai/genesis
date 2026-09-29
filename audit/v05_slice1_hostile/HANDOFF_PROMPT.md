# Handoff prompt — finish the V0.5 slice-1 hostile audit package

(Copy everything below the line into the next model's task.)

---
You are continuing an independent hostile audit of Project Genesis V0.5 slice 1. Read
`audit/v05_slice1_hostile/HOSTILE_AUDIT_REPORT.md`, `FINDINGS.csv`, `TEST_RESULTS.md` and
`oracle/README.md` on branch `ccr-c8695f69-sghhe5` of `abbottjack705-ai/genesis` first.
Do NOT modify the candidate (`cfcff3d`), the frozen trees (`src tests config tools
DECISIONS v04_pack`), or `V05_ADAPTER_ARCHITECTURE.md` at `c8dfafd`. Do not implement fixes.

State so far
- Architecture authority `c8dfafd` was read in full; frozen tree identity of `2278e2a` and
  `c8dfafd` verified; Linux frozen-suite baseline at `c8dfafd` = 493 run / 19 skipped / OK.
- Candidate commit `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` (branch `v05-slice1-impl`,
  worktree `C:\Users\abbot\fz\g`) was NOT reachable from origin. Current verdict is
  "V0.5 S0–S7 HOSTILE AUDIT — REMEDIATION REQUIRED", fail-closed on HA-000 only.
- A self-tested oracle exists in `audit/v05_slice1_hostile/oracle/` (8 scripts + wrappers).
- 13 findings HA-000..HA-012 are recorded; HA-001 (identical-fingerprint quota replay),
  HA-002 (OPEN→OPEN revival under the frozen verifier) and HA-011 (crash between PIT
  appends) are new attack material demonstrated on frozen code and still PENDING on the
  candidate.

Your tasks, in order
1. Check whether `v05-slice1-impl` / `cfcff3d` is now on origin (`git fetch origin
   cfcff3dbb285eaa48a6cfc1eceedb91e27662c81`). If not, stop after step 2 and say so.
2. Write the four missing package files in `audit/v05_slice1_hostile/`:
   - `REPRO_COMMANDS.md`: per audit area, exact commands. Include the 16-checkpoint crash
     matrix for area 3 (before/after: quota ledger row, acquisition quota_decided, sent,
     transport complete, secret screen, raw publish temp/link, completed row, each
     normalized publish, structured evidence, each PIT append, coverage, normalized row,
     invalidation ledger row, INVALIDATED doc publish, invalidation PIT append) with the
     expected restart behaviour from c8dfafd §11.1/§11.4/§14.4/§13.2 and the frozen facts
     in `oracle/QUOTA_SEMANTICS_OUTPUT.json`.
   - `DEVIATION_REVIEW.md`: classify all 24 deviations in `adapters/evidence/S7/SUMMARY.md`
     (once reachable) as CONFORMING INTERPRETATION / STRICTER BUT SAFE / AUTHORITY
     AMBIGUITY / UNAUTHORIZED SEMANTIC CHANGE / DEFECT, citing c8dfafd sections. Until
     then, pre-classify the nine named ones with the deciding condition: formulas vs
     examples (§14.6 W1–W4 are normative); optional ODDS startTime (§8.3: absent → fixture
     join or BLOCKED, never OPEN without S); null price (§10 rule 5: ACTIVE+null →
     CONTRADICTORY_STATUS); independent bookmakerIsActive allowlist (must live in
     `oddspapi_v4_status_map.json`, inside status_map_digest; false/unknown → no price);
     expected scope at Tq (§12.4 literal; see HA-012); separate approve-ready command
     (§16.5/§16.6: TTY + phrase + G3 record required); coarse-clock T1 (HA-008 conditions);
     stricter credential line-ending rule (§7.5, STRICTER BUT SAFE if no content leak);
     two reader refusals stricter than design (§12.3 step 7, must be deterministic in D).
   - `F44_ASSESSMENT.md`: expand HA-007 — safe (no resend, debit stands, F-35 reconcile),
     diagnostic loss (T1/status/headers not durable, mislabelled ORPHANED_RESERVATION),
     no c8dfafd violation, additive RAW_PUBLISH_FAILED semantics = later ADR, not
     certification-blocking. Do not implement F-44.
   - `REMEDIATION_HANDOFF.md`: minimal, implementation-ready items for Sonnet: (1) push the
     branch; (2) run `oracle/run_oracle.ps1` on Windows and attach `oracle_out/`;
     (3) conditional items HA-001/002/004/005/006/011/012 exactly as `FINDINGS.csv`
     `minimal_remediation` + `regression_test` state, each gated on its verification.
   Regenerate `ARTIFACT_MANIFEST.sha256` (`find . -type f ! -name ARTIFACT_MANIFEST.sha256
   | sort | xargs sha256sum`), commit, push to `ccr-c8695f69-sghhe5`.
3. If the candidate IS reachable: run `oracle/run_oracle.sh <repo> cfcff3d… <out>` on it,
   run its adapter suite with `-B` and a fresh `PYTHONPYCACHEPREFIX`, then execute the
   attacks in REPRO_COMMANDS.md for areas 2, 3, 4/5 (compare `reader.admissible_head`
   against `oracle/EXPECTED_PIT_HEADS.json` for every scenario and cutoff), 6 (run
   `oracle_secret_corpus.py --repo`), 7, 8, 10, 12, 15. Read `adapters/evidence/S7/
   SUMMARY.md` and finish DEVIATION_REVIEW.md. Close or confirm each PENDING finding with
   evidence, add new findings with the full field set, and re-issue the verdict as exactly
   one of "V0.5 S0–S7 HOSTILE AUDIT — GREEN" or "V0.5 S0–S7 HOSTILE AUDIT — REMEDIATION
   REQUIRED". Windows-only checks (HA-004 real symlink, HA-005 icacls locale) cannot pass
   on Linux; record them as requiring a privileged Windows run rather than waiving them.
4. Treat every implementer transcript, test count and SUMMARY claim as untrusted until
   reproduced. Never weaken the oracle to make the candidate pass.
