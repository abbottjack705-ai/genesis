# Project Genesis V0.5 R7 remediation candidate

| | |
| --- | --- |
| Status | **R7 implementation candidate. Not self-certified; submit for a fresh independent hostile audit.** |
| Branch | `ccr-f8478091-s6i6d1` |
| Starting checkpoint | `c38df0f92715b07c7dce971f05740024a7359248` |
| Hostile audit answered | R6 audit commit `2ef9fa0` (`independent_audits/v05_r6_hostile_reaudit/` in that audit commit), verdict REMEDIATION REQUIRED |
| Validation host | Windows 11, CPython 3.12.10; Windows certification remains **OPEN** |
| Scope | Oddspapi adapter and its tests/evidence only; six frozen V0.4 trees unchanged |

This completion continues the already-pushed R7 implementation at `c38df0f`; it does not restart from the V0.5 initial implementation. The R7 production changes in `acquisition.py`, `derivation.py`, `quiescence.py`, and `transport_http.py` are unchanged from that checkpoint. This candidate adds the stronger historical-settlement regression, makes one deadline test deterministic, and fixes two Windows-specific test-harness assumptions discovered during the full suite. The focused mutation campaign targets the R7 invariants and kills all 16 listed mutants, including the historical R01b settlement algorithm.

## R7 findings

- **RA6-001 — closed for candidate:** every attempt's durable verdict is settled. Missing rejection coverage remains pending even when a later verdict is already fully settled; the R01b regression exercises this ordering and recovery.
- **RA6-002 — closed for candidate:** quota divergence is durable on the response verdict and remains unusable across uninterrupted, restarted, replayed, rebuilt, and reset run orders.
- **RA6-003 — closed for candidate:** TLS context construction does not mutate or consult environment variables; trust roots and the TLS floor are set explicitly, including the Windows system stores.
- **RA6-004 — closed for candidate:** DNS resolution is bounded by the remaining transport deadline; an expired deadline starts no lookup, and an abandoned resolver is a daemon.
- **RA6-009 — closed for candidate:** the regression suite includes crash/partial-settlement recovery, including an older unsettled verdict behind a later settled verdict.

The remaining findings are recorded in `FINDINGS_STATUS.csv`. RA6-005 and RA6-006 concern derivation-source versioning and version-blind rejection of retained captures. The repository documents the operational new-root rule for a source change, but design 13.3 and the rejection semantics leave a material policy decision unresolved; R7 does not invent an architecture decision. RA6-007 is an INFO replay-validation gap whose effect is denial of a capture, not making one usable. RA6-008 concerns multiple `Date` header occurrences in raw capture and is outside the R7 changes. RA6-010 concerns the frozen V0.4 foundation and was not changed.

## Validation

Evidence transcripts are retained beside this file. CPython 3.12.10 on Windows 11: targeted R7 57/57; replay 2/2; provenance 3/3; full adapter 917 passed with 2 platform skips; frozen V0.4 493 passed with 1 platform skip; compileall and integrity checks passed; final no-network sentinel passed; focused mutation campaign 16/16 killed. The first full-adapter run is retained as `FULL_ADAPTER_INITIAL.txt`: it exposed two test-harness assumptions (a fixed count of unopened sockets, and an open control key-log file on Windows). Those were corrected to test the actual invariant and release the test handle; the full suite then passed. No production behavior or assertion was weakened.

Only CPython 3.12 is installed/available through the Python launcher on this host, so 3.11 and 3.13 were not run. The W1-W15 Windows certification is **OPEN**; the suite's two expected platform skips include real symbolic-link privilege and POSIX-mode checks. No provider calls, credentials, gate records, live betting, merge, or pull request were used or created.

## Handoff

A fresh independent hostile audit should review the final code/tests commit and this evidence-only commit against RA6-001 through RA6-010, verify the evidence hashes, and decide the recorded open findings. This package is an implementation candidate, not a certification.
