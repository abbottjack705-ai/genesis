# Test results (R6 re-audit, code `4ed66de4e2f3161464b9205583b3ee7a97133904`)

Host: Linux 6.18 (Firecracker VM, 4 vCPU); CPython 3.11.15, 3.12.3 (Ubuntu build), 3.13.14; OpenSSL 3.0.13.
**Not Windows.** All transcripts are in `evidence/`; probes in `probes/`. The host environment carries
`SSL_CERT_FILE` (an egress-proxy CA bundle), which every suite run below therefore exercised against the R6
environment-hiding code.

## 1. Suites

| Run | Result | Transcript |
| --- | --- | --- |
| Adapter suite, CPython 3.11.15 | **Ran 859, OK** (0 skipped) | `adapter_suite_python3.11.txt` |
| Adapter suite, CPython 3.12.3 | **Ran 859, OK** | `adapter_suite_python3.12.txt` |
| Adapter suite, CPython 3.13.14 | **Ran 859, OK** | `adapter_suite_python3.13.txt` |
| Adapter suite inside `unshare -rn` (only `lo`; external connect → errno 101) | **Ran 859, OK** | `netns_suite_py311.txt` |
| Independent audit hook over the whole suite (R5 harness) | 859 run, 0 errors/failures, 60 socket events, **2 non-loopback** | `nonet_py311.json` |
| Call-site attribution of non-loopback attempts (new hook with test id + frames) | both `getaddrinfo`, from `test_v05_transport_http.py:173` (`192.0.2.1`) and `:175` (`genesis.example.invalid`), test `ConnectionFailureTests.test_the_suite_refuses_any_non_loopback_contact`; refused by the suite's hook before resolution | `n01_nonet_callsites_py311.json` |
| Frozen V0.4 suite, quiet host | **Ran 493, OK (skipped=19)** — count-identical to the Linux pre-R6 baseline (R5 audit, implementer) | `frozen_suite_py311_quiet.txt` |
| Frozen V0.4 suite, first run under audit CPU load | Ran 493, **FAILED (failures=1, skipped=19)**: `T6HardLinkAliasTests.test_t6_concurrent_writers_through_a_toggled_hard_link_keep_one_valid_chain` | `frozen_suite_py311.txt` |
| That frozen test alone, 10× quiet / 10× under 4 busy loops | 10/10 pass / **9/10 pass, 1 fail** (same F-3b assertion) — RA6-010 (frozen foundation, out of R6 scope) | `frozen_t6_flake_characterization.txt`, `frozen_t6_contention_failure.log` |
| Worktree after the suites | clean; frozen tree SHAs unchanged | `worktree_status_after_suites*.txt` |

## 2. RA5-001 campaigns (all against `4ed66de`)

| Campaign | Size | Outcome classes | Defects |
| --- | --- | --- | --- |
| A13 targeted end-to-end corpus | 29 | 14 NORMALIZED, 12 CAPTURE_REJECTED, 3 DERIV_REJECTED (fifth class) — each followed by restart ×2, `verify_all`, reader, a later healthy capture, reader | **0**; reader usable after the later capture in 29/29 |
| A10 end-to-end fuzz, seeds 101/202/303/404 | 1 738 (seeds 303/404 stopped early by a harness bug in my generator, fixed; records up to the stop are valid) | 1 105 NORMALIZED, 633 CAPTURE_REJECTED | **0** |
| A10 end-to-end fuzz with the later-healthy-capture step, seeds 505/606 | 1 500 | 886 NORMALIZED, 613 CAPTURE_REJECTED, 1 DERIV_REJECTED | **0** (no escape, no pending work, reader usable after the later capture) |
| A11 pure-stage fuzz past the capture checks, seed 11 | 20 000 | 19 942 PASS→DOCS, 54 envelope-rejected, 4 PASS→ENVELOPE (fifth class) | **0**: safety net caught nothing; no non-determinism; no stack-depth dependence; no emission-precondition failure |
| A12 exhaustive single-substitution sweep | 121 330 bodies over 1 668 leaf paths | 119 438 PASS→DOCS; 1 668 TOO_DEEP (exactly the depth-51 body at every leaf; depth 50 accepted everywhere); 206 envelope; 18 PASS→ENVELOPE (`fixtureId` only) | **0** (same checks as A11) |
| A01 crash between `acq_derivation_rejected` and its coverage entry | 2 scenarios | CONTROL (newest attempt): coverage written by `settle_last` | **ATTACK (older attempt, G2→G2R): coverage never written — RA6-001** |
| V01 parts D/E | 5-capture script ×2 roots; 3 restarts; PIT-09 rebuild | 178 durable files, **0 differ**; verdicts unchanged across restarts; rebuild artifact set identical | 0 |
| R5 fuzzers on R6 (`p114` 6 000, `p116` 10 000, `p117`, `p119` 8 000, `p121` 250) | 24 250+ | — | "no exception escaped" in each (`r5probes_on_R6/`) |

Seeds and exact bodies: A10 records every case (`evidence/fuzz_records/a10_seed*.jsonl`: ops, classification,
restart/reader results); `probes/regen_a10.py <seed> <i>` regenerates the exact body of any case. A11/A12 are
deterministic per seed (A12 has no randomness).

Total RA5-001 bodies exercised with evidence: **144 597** (+24 250 from R5's fuzzers).

## 3. RA5-002, RA5-003, RA5-004 probes

| Probe | Result |
| --- | --- |
| D01 `parse_http_date` (55 corpus + 20 000 seeded) ×3 interpreters | never raises; every non-None result aware UTC |
| D01 runner, 61 Date variants × `require_date` on/off | 45 unusable → durable `CLOCK_SKEW` + quarantine + suspension, 16 usable accepted; **0 orphans** after restart |
| T01 production trust vs retired CA + leaf key (history-restored), 7 scenarios | BASE: S1–S4 **BREACH**; R6 3.11/3.12/3.13: **all held**; 127 system CAs kept; env restored; no key log |
| T02 concurrent `tls_context()` (4×300) with `SSL_CERT_FILE`=retired CA | **9/1198, 12/1197, 12/1196 contexts trust the retired CA; `KeyError` 2–4×/run; observer sees variable missing ~95 %** — RA6-003 |
| T03 protocol floor | 3.11/3.13: TLS 1.2 with or without `OPENSSL_CONF`; **3.12.3: env `OPENSSL_CONF` lowers floor to TLS 1.0** (cert still refused) — RA6-003 |
| R01 real-socket deadline, 16 scenarios ×3 interpreters, D = 3 s | worst overshoot **4 ms**; no RESPONSE after the deadline |
| R02 stalled resolver (isolated user+mount+net namespace) | **10.0 s** (1 nameserver) / **28.0 s** (3 nameservers) held against 3 s — RA6-004 |

## 4. Secondary findings and versioning

| Probe | Result |
| --- | --- |
| Q01 usage header × 7 forms, R6 and BASE | R6: every form halts, **and every form's response becomes 12 usable OPEN documents after a restart** (uninterrupted: none, reads refused) — RA6-002; BASE: same for `99999`, malformed forms accepted and derived at once |
| L01 RA5-006/008 edges | trailing LF/CRLF/NUL/space/Unicode-digit ids and request values rejected; bookmaker ceiling 0/4/50/true/3.0/"3" refused |
| V01 A/B/C | new derivation source (`mb-normalize-3`, `mb1-eee12f31dd5c2597`, new policy digest); stale G2R pin **refused**; BASE-written root under R6 → `EVIDENCE_CONFLICT` halt at every start — RA6-005 |
| R5 probe set on R6 (`r5probes_on_R6/`), diffed against R5's own transcripts on the base | every probe of a previously closed class prints **identical** output; every RA5-001/002/004/005/006/008/009/011 probe flips from defect to held (`p113`, `p118`, `p119b`, `p123`, `p124`, `p12`, `p110`, `p60` L5, `p90` H, `p150`, `p11` 3.0 s TRUNCATED); `p70` is moot on R6 (the committed CA no longer exists; T01 replaces it); `p115` has nothing to minimise because `p114` found nothing |
| Implementer's 17-probe controlling-audit script | R6-adapted: **0/17 reproduced**; unadapted FINAL variant: 1/17, the HA-13 probe's `export-ignore` criterion evaluated on a file that no longer exists (`git grep` finds no private-key block in any tracked file at `4ed66de`; no `.key/.pem/.crt` tracked) — false positive, not a reopening |

## 5. Mutation (re-run on `4ed66de`, full suite fail-fast per mutant, 3 parallel scratch worktrees)

| Campaign | Specs | Killed | Survived | Other |
| --- | --- | --- | --- | --- |
| R5 independent 51 + control (`mutants.json`, `mutants_round2.json`) | 52 | 49 | M00 control (as required) | M15, M37: BAD_SPEC (anchor text rewritten by R6) |
| Implementer's re-anchored M15/M37 (`mutants_r6_adapted.json`), semantics re-checked by me (M15: same `+1000000` loosening of the `reported > debited` comparison in R6's rewritten condition; M37: `valid_to` replaced by `publisher_timestamp` on both sides of the R6 tuple) | 2 | 2 | — | — |
| This audit's R6-targeted set (`mutants_r6_audit.json`) | 51 (X00 control + 50) | 49 | X00 control (as required) | X36 TIMEOUT = suite hangs in `test_a_peer_that_accepts_but_never_completes_the_tls_handshake_cannot_hold_the_transport` (confirmed in isolation, `x36_confirm.txt`) → detected |
| Extra per-worker controls | 2 | — | both survived | — |

**All 51 R5 mutants are killed on R6** (49 directly, M15/M37 through their verified re-anchoring); **all 50 of my
R6-targeted mutants are detected** (49 failing tests, 1 hang). Every no-op control survived, so the environment produced
no false kills; every first failing test is semantically tied to its mutation (`mutation_table.md`). No surviving mutant
needs an equivalence argument. Note: the RA6-001 defect is a *scenario* gap (a crash at a checkpoint no test crashes
at), which single-line operator mutation does not expose — my X18 (settle does not locate the rejection row) is killed
only through the no-crash path.

## 6. Modified tests: OLD assertions run against R6 code

See `old_tests_against_R6.txt` and report §4. Summary: reader — only the hash-order precondition fails; jsonstrict —
only `NOT_JSON`→`TOO_DEEP`/`NUMBER_OUT_OF_RANGE` (still rejections); parser_schema — signature-only; credential — the old
test errors on Linux exactly as on the base; tx01/loopback — removed `TEST_CA` only; r2 HA-13 — `export-ignore` rule
gone with the files, replaced by stronger "no material" tests.
