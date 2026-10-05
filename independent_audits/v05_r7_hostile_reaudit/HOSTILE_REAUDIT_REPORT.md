# Project Genesis V0.5 R7 — independent hostile re-audit

## PASS FOR NEXT HUMAN CHECKPOINT

## WINDOWS CERTIFICATION: OPEN

| Pin | Independently verified value |
| --- | --- |
| Candidate branch | `ccr-f8478091-s6i6d1` |
| Evidence tip | `b2eabac1da9ed3989de966583a51d97b3834aa9c` |
| Direct parent, code/tests candidate | `be898d3865685ac0261cdb255008db902b030521` |
| Audit branch | `audit/v05-r7-hostile-reaudit`, based on the exact evidence tip |
| Host | Windows NT 10.0.26200.0, CPython 3.12.10 |

This is an implementation verdict for the next human checkpoint. It does not certify Windows W1–W15, authorize any gate, or establish provider behavior. I did not implement R7. All probes used fixtures, local files, or loopback. No provider call or real credential was used.

### Pin and evidence integrity

The requested branch and its remote-tracking ref both resolved to `b2eabac1`; its worktree was clean. `be898d3` is the direct parent and code/tests candidate. The 22 added paths between the two commits are all under `adapters/evidence/R7/`. All 21 entries in R7's SHA-256 manifest matched, and the manifest covers every R7 evidence file except itself. The six frozen V0.4 tree IDs match the freeze tag and their diff is empty. The audit worktree has no production or test edits. See `evidence/integrity.txt`.

### Primary hostile results

| Target | Independent result |
| --- | --- |
| RA6-001 rejection crash consistency | **Closed for R7.** The prior older-capture crash reproducer now reaches DERIVATION_REJECTED with exactly one REJECTED coverage entry and no pending gap, whether the poisoned capture is newest or followed by another attempt. The 57-test target suite exercises cuts before/after the row and coverage append, repeated recovery, conflicting coverage, and an older unsettled rejection behind a later settled rejection. Settlement walks all attempts' last verdicts in ledger order; pending-work reports missing/conflicting rejection coverage. No rejected evidence became usable. |
| RA6-002 QUOTA_DIVERGENCE laundering | **Closed for R7.** The old reproducer found zero new documents after restart for an over-limit header and six unreadable forms. The durable completed row carries QUOTA_DIVERGENCE for an otherwise clean response; every derivation/rebuild consumer also rejects a row with divergent usage. My additional cut after a completed row with malformed JSON **and** unreadable usage converged on one halt, both coverage effects, zero documents, and unchanged state through three restarts. R7 tests also cover reset, replay, rebuild, other roles, and earlier clean evidence. |
| RA6-003 TLS trust | **Closed for R7 on this host.** The retired test CA and leaf key, restored solely to temporary isolated scratch and removed after the probe, failed to authorize a loopback server in seven environment scenarios: SSL_CERT_FILE, SSL_CERT_DIR, SSLKEYLOGFILE, OPENSSL_CONF, combinations, case variants, and control. No keylog was written. Eighty concurrent contexts under hostile variables raised no errors, retained 47/47 stock system CAs, required certificate and hostname verification, and kept the TLS 1.2 floor. The full suite's real loopback TLS tests passed. |
| RA6-004 DNS/deadline | **Caller deadline closed; residual LOW operational finding RA7-001.** Twelve consecutive 20 ms stalls returned in 0.375 s total (maximum 0.035 s), an already expired deadline started no lookup, and releasing late DNS results started zero sockets. A child with a blocked resolver exited in 0.442 s, so no shutdown hang was observed. However, twelve daemon resolver workers remained live simultaneously until the blocked resolver was released. The code has no cancellation or cap for these workers. See below. |

### Residual finding RA7-001 — stalled resolver workers accumulate (LOW)

`_Connection._resolve` creates a daemon thread for every attempt and returns at the absolute deadline without cancelling an unresponsive `getaddrinfo` call (`transport_http.py:145–173`). With a deliberately blocked resolver, twelve sequential timeouts left twelve live workers. They terminated after release, and late results did not initiate a socket. This is a bounded operational resource risk, not a demonstrated deadline bypass or evidence laundering. Live billable attempts are limited by the frozen quota (seven per day, 250 total), and process exit is not held by the daemon workers. It should be reviewed before a higher-volume or long-lived deployment. The governing handoff's blocking threshold is not met by this LOW residual.

### Regression and governing authority

The prior poison-pill probe completed with NUMBER_OUT_OF_RANGE, two clean restarts, and a later healthy response; raw evidence remained available. The prior Date overflow probe kept zero PIT rows and a durable quarantine/suspension. The prior replay probe produced 174 files in each run with no differences, and the 16-case rejected/quarantined response probe yielded zero new PIT or normalized records after restart. The adapted prior provenance probe caught CRLF and trailing-byte changes and direct shadow-package competition; its same-length swap failed at import before hash verification and its absent-target .pth case is inconclusive. The prior F-44 probe remained fail closed with one debit and zero PIT rows. Full adapter and targeted replay/provenance suites also passed. No reopened BLOCKER/HIGH finding was substantiated.

RA6-005 remains an inherited LOW derivation-source/root transition classification issue: design §13.3 defines a new source and R7 README requires a new runtime root, but reuse of an old root is labelled EVIDENCE_CONFLICT. RA6-006 remains an INFO architecture question: §13.3 permits retained-capture re-derivation, while a durable rejection is version blind; the design does not require automatic re-derivation of every rejected capture. RA6-007 is an inherited INFO replay-validation gap with denial, not admission, as its identified consequence. RA6-008 (repeated Date headers) is unchanged by R7 and remains INFO. RA6-010 belongs to byte-identical frozen V0.4 code and remains outside R7 remediation. These classifications are not treated as fresh R7 regressions.

The modified tests were reviewed against `435cdba..be898d3`. The old exact count of unconnected fake sockets became an all-unconnected assertion because DNS expiry may create none; separate tests assert no post-deadline lookup/connection. The lexical ban on the word `cafile` became an AST check of trust-input parameters, while the production context's compiled trust paths are reviewed directly and exercised by TLS tests. The R6 environment-hiding mechanism assertions were replaced with non-mutation, trust, verification and concurrency assertions. The static scanner is narrower in wording, but no production trust override or safety assertion loss was found. Four new R7 test modules cover the changed behavior.

### Independent validation

`TEST_RESULTS.md` records 57/57 targeted, 917 adapter tests with two platform skips and the final no-network sentinel, 493 frozen tests with one skip and an identical S0 count comparison, replay 2/2, provenance 3/3, compile pass, prior reproducers, and integrity pass. R7's campaign killed 16/16 including R01b. Five additional mutants were killed after all five no-op controls survived; no survivor was waived. See `MUTATION_EVIDENCE.md`, scripts and raw transcripts.

### Limits

Only CPython 3.12.10 was available here; 3.11/3.13 were not rerun. The DNS accumulation probe used a deliberately blocked local resolver stub, not a controlled stall of the Windows DNS Client service. The complete W1–W15 certification, privileged NTFS link/junction and ACL checks, deployed identity, and deployment-image timing remain open in `WINDOWS_GAPS.md`.
