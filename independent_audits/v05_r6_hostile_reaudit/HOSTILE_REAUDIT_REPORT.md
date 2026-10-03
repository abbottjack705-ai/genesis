# Project Genesis V0.5 — independent hostile re-audit of the R6 remediation candidate

## V0.5 R6 HOSTILE RE-AUDIT — REMEDIATION REQUIRED

## WINDOWS SYMLINK CERTIFICATION: OPEN

| | |
| --- | --- |
| Audited code + tests commit | `4ed66de4e2f3161464b9205583b3ee7a97133904` (branch `ccr-689a0c12-vys6ag`) |
| Candidate branch tip (evidence only) | `435cdbaa0ce9702307c4780746aec30e7f3da2e9` (adds only `adapters/evidence/R6/CANDIDATE.txt`) |
| Parent / R5 evidence base | `b22263e582386f04e5b7939e511757940ffdfbe0` (code `9f846d8…`) |
| Prior independent audit (read-only, unchanged) | `audit/v05-r5-sonnet55` @ `472f2603b0ded3e0199609d59f19185f7c8e4294` (verdict REMEDIATION REQUIRED) |
| Architecture authority | `V05_ADAPTER_ARCHITECTURE.md` r3 (identical at the candidate) |
| Frozen V0.4 foundation | tag `v0.4-foundation-freeze` → `2278e2a…` |
| Audit host | Linux 6.18 (Firecracker VM, 4 vCPU), CPython 3.11.15 / 3.12.3 / 3.13.14, OpenSSL 3.0.13 — **not Windows** |
| Audit branch | `ccr-e2058000-556doy`, created from exactly `435cdba`; artifacts only under `independent_audits/v05_r6_hostile_reaudit/` |
| Auditor | independent hostile re-auditor (did not implement R6). No implementation code modified, no provider call, no credential, no gate record, no READY, no PR, no merge |

**Headline.** R6 genuinely closes the four R5 primary defects as reproduced: I could not produce a poison-pill wedge
(RA5-001) with 144 597 end-to-end, pure-stage and exhaustive single-substitution bodies (including a 29-case targeted corpus);
the Date path is total (RA5-002); the production trust store can no longer be redirected to the retired CA with its
leaf key restored from history (RA5-003); and every socket phase is bounded by one absolute deadline with ≤ 4 ms
overshoot (RA5-004). No previously closed BLOCKER/HIGH re-opened. But the new durable-rejection mechanism has a
**crash-window durability hole** (RA6-001, MEDIUM, new), the RA5-011 fix **broadened an inherited restart-dependent
fail-open of F-37** (RA6-002, MEDIUM), the TLS fix is **not thread-safe** (RA6-003, LOW, new), and the deadline invariant
still **does not hold for name resolution** — measured 28 s against a 3 s deadline (RA6-004, LOW). Two MEDIUM defects in
the restart-convergence family that the R5 handoff treats as blocking before G2R/G3 means **REMEDIATION REQUIRED**.

## 1. Startup integrity (all performed before any functional audit)

| # | Check | Result |
| --- | --- | --- |
| 1 | `4ed66de` parent is `b22263e`; `435cdba` parent is `4ed66de`; no merge commit in `b22263e..435cdba` | PASS |
| 2 | `git diff 4ed66de 435cdba` = one added file `adapters/evidence/R6/CANDIDATE.txt` naming `4ed66de` (and `HASHES.sha256` = `aeb0a057…`, which matches) | PASS |
| 3 | `origin/audit/v05-r5-sonnet55` = `472f260…`; its parent is `b22263e`; `ARTIFACT_MANIFEST.sha256` verifies 120/120; every file of the package is covered | PASS |
| 4 | `b22263e..4ed66de` touches 67 paths, **all under `adapters/`** (src 17; adapter_tests 16 = 13 modified/new test and support modules + 3 deleted TLS fixture files; config 1; evidence 31; `README.md`; `.gitattributes`); `git diff b22263e 4ed66de -- . ':!adapters'` is empty | PASS |
| 5 | Six frozen trees at `4ed66de` **and** `435cdba` equal the freeze tag: `src 51cb635b…`, `tests e90b2981…`, `config abd22db0…`, `tools a0e3411e…`, `DECISIONS cc97ec6f…`, `v04_pack 3c3c1c27…` | PASS |
| 6 | No PR artefact, no unrelated modification; `adapters/` tree at the candidate `b0463d69…` as recorded | PASS |
| 7 | `adapters/evidence/R6/HASHES.sha256`: 30/30 entries verify; every file under `evidence/R6/` except `HASHES.sha256` itself is covered (`CANDIDATE.txt` arrives after, in the tip, and records the `HASHES.sha256` digest) | PASS |

No foundational pin or frozen-tree invariant failed, so the audit proceeded on exactly `4ed66de`.

## 2. Verification of the implementer's claims (each independently challenged)

| Claim | Independent result |
| --- | --- |
| Adapter suite 859 OK, 0 skipped (3.11/3.12/3.13) | **Reproduced**: 859 OK on 3.11.15, 3.12.3 and 3.13.14 (`evidence/adapter_suite_python3.1x.txt`); 859 OK inside `unshare -rn` (loopback only) |
| Frozen suite 493 OK, skipped=19 (Linux) | **Reproduced on a quiet host** (`evidence/frozen_suite_py311_quiet.txt`); count-identical to the pre-R6 Linux baseline. A first run **under CPU contention** failed one frozen test (`T6HardLinkAliasTests…toggled_hard_link…`): 0/10 failures quiet, 1/10 under 4 busy loops — frozen code, byte-identical at the freeze, out of R6 scope (RA6-010, INFO, reported for the foundation owners) |
| No-network: 2 non-loopback attempts, both the guard self-test | **Reproduced and independently attributed**: my hook records the running test and frames — both `getaddrinfo` attempts come from `test_v05_transport_http.py:173` and `:175` in `test_the_suite_refuses_any_non_loopback_contact`, refused before any packet (`evidence/n01_nonet_callsites_py311.json`) |
| RA5-001 closed; "safety net never catches a known class" | **Closed as a wedge** (§3.1). Safety net: caught **nothing** in every campaign of mine. **But** the claimed crash idempotency of the new verdict is false for a non-newest attempt (RA6-001) |
| RA5-002 closed | **Closed** (§3.2), 3 interpreters; INFO note on multiple `Date` headers (RA6-008) |
| RA5-003 closed | **Closed for the single-threaded production path** with the retired CA **and its leaf private key** restored from history (§3.3). New: the environment hide/restore is not thread-safe (RA6-003) |
| RA5-004 closed; `getaddrinfo` residual disclosed | **Closed for connect/TLS/send/receive** (≤ 4 ms overshoot, 16 scenarios × 3 interpreters). The disclosed residual is **practical**: 10 s (1 nameserver) and 28 s (3 nameservers) against a 3 s deadline (RA6-004) |
| Modified tests are refinements, not weakenings | **Confirmed** by running every OLD assertion against R6 (§4) |
| Secondary RA5-005…013 fixed | Confirmed, except that the RA5-011 fix broadens RA6-002 (§5) |
| All 51 R5 mutants killed, M00 survives; M15/M37 re-anchored | See §6 (re-run on R6 by me, not taken from `AUDIT_HARNESS_MUTATION.txt`) |
| Deterministic replay; new derivation source by design | **Reproduced**: two fresh roots, same script (healthy + derivation-rejected + capture-rejected + ambiguous-participant captures): 178 durable files, 0 differing; rejections stable over 3 restarts and a PIT-09 rebuild; stale G2R pin refused. Opening an R5-era root with R6 halts as a tamper-class `EVIDENCE_CONFLICT` at every start (RA6-005, LOW) |

## 3. Primary findings — independent closure verdicts

### 3.1 RA5-001 (BLOCKER) — poison pill / durable terminality: **CLOSED as a wedge; residual RA6-001 (MEDIUM)**

What I attacked, all on `4ed66de` (transcripts in `evidence/`):

* **Targeted end-to-end corpus** (`a13_corpus_e2e.py`, 29 cases, each: acquire → restart + resume ×2 → `verify_all` →
  reader → a *later healthy capture* → reader → `pending_work`): R5's four classes (A `1E+999999999`, B lone `\ud800`,
  C 70-digit participant, D 600-deep betslip), the fifth class (`fixtureId` outside the grammar, 65 chars, trailing LF),
  64/65-digit participant ids, a negative id, prices at `1E±1000` (accepted) and `1E±1001` (rejected), 1001/1002-digit
  integers, 3000-digit mantissas, an exponent beyond `Decimal`, deep betslips (rejected; the exact 50-accepted /
  51-rejected edge is proven at every leaf by A12), escaped surrogate pair (valid),
  lone low surrogate, reversed pair, a surrogate key, a 200 000-element shallow array. **29/29: terminal verdict,
  nothing pending, restart-stable, reader usable again after the later capture.**
* **End-to-end fuzz** (`a10_fuzz_e2e.py`, 3 238 cases): seeds 101/202/303/404/505/606 (505/606 add a later healthy capture), hostile literal
  pools (exponent boundaries both signs, zero with huge exponent, surrogate variants, 64/65-char ids, depth landing on
  49/50/51/52, duplicate keys, broad/shallow structures, hostile map keys). **0 escapes, 0 non-terminal states, 0
  pending after restart, 0 reader escapes.**
* **Pure-stage fuzz past the capture checks** (`a11_fuzz_pure.py`) and an **exhaustive single-substitution sweep**
  (`a12_sweep_pure.py`: every leaf × every capture-passing hostile literal + every map key × hostile keys): each body is
  checked for determinism, **caller-stack-depth independence** (derive re-run with ~120 frames of headroom), and the
  **emission preconditions** that `emit_documents` evaluates *outside* the boundary (frozen `BitemporalRecord`,
  `ResearchEvidence`, claim serialisation). **No safety-net catch, no non-determinism, no depth dependence, no emission
  failure.** Every capture-PASS → derivation-reject pair is the documented fifth class (`ENVELOPE_SCHEMA_MISMATCH` from
  the parser's `fixtureId` grammar check, which the capture-time check lacks).
* **Code review of the boundary.** `derive()` wraps parse + document building; `_inputs()` (before it) reads only durable,
  non-provider facts and a total FIXTURES snapshot builder; emission (after it) consumes documents whose time fields
  the parser bounds (`T1 ≥ S − guard` suppresses the event, so OPEN `valid_to > valid_from`). Rejection writing
  (`reject_derivation`) cannot fail replay validation on the path that calls it (state checked `COMPLETED` first).
* **The new ledger row.** `acq_derivation_rejected` is a row of the same hash-chained, replay-validated
  `AppendOnlyJsonl` as every other acquisition row (integrity-protected exactly as the rest — a chain, not a MAC).
  Replay refuses it after `NORMALIZED`, after a failed completion, twice, before completion, with an unknown failure or
  non-text detail; `acq_normalized`/`acq_quarantined` after it are refused, so it **cannot be forged into usability or
  confused with a derivation**. It is deterministic (byte-identical replay) and stable across restarts and PIT-09.
  Weaker points (role/outcome not re-checked, `derivation_version` unvalidated and never consulted) are INFO
  (RA6-006, RA6-007): a forged row can only *deny* a capture.
* **Crash boundaries.** Before the row: a restart re-derives deterministically to the same verdict (held). After the row
  for the **newest** attempt: `settle_last` writes the coverage entry (held). After the row for an **older** attempt —
  the normal G2 (raw only) → first G2R start (`resume()` derives every G2 capture in ledger order) flow — the REJECTED
  coverage entry is **never written** and nothing reports it: **RA6-001**.

### 3.2 RA5-002 (MEDIUM) — Date totality: **CLOSED**

`parse_http_date` over 55 hostile values + 20 000 seeded date-shaped strings on 3.11/3.12/3.13: never raises, every
non-`None` result is aware UTC (`d01_date_totality_*.txt`). Through the runner (live-like `require_date=True` and fixture
mode): all 45 unusable values (huge/negative/zero years, Feb 29/30, 24:00, :60/:61, non-GMT zones, `-0000`, naive,
NUL/CRLF/non-ASCII, 255/400/5000-digit fields, empty, over-long dropped values) → durable `acq_completed{CLOCK_SKEW}`,
quarantine row, next-day suspension, **0 orphans** after restart. Mapping every unusable `Date` to `CLOCK_SKEW` is the
governing taxonomy, not convenience: §6.1 "In live mode a missing or unparseable `Date` header also quarantines
(`CLOCK_SKEW`)", F-12. Lenient forms (`UT`, `UTC`, `Z`, RFC 850, two-digit and `0001`→2001 years) are accepted only if
within skew (`d02_accepted_forms_py311.txt`) — harmless for a skew cross-check. Multiple `Date` headers: only the first
kept value is judged (RA6-008, INFO).

### 3.3 RA5-003 (MEDIUM) — TLS trust boundary: **CLOSED for the production (single-threaded) path; RA6-003 (LOW)**

The retired CA, leaf certificate (SAN `api.oddspapi.io`, valid to 2046) and **leaf private key** were restored from
`b22263e` history into scratch at run time only (never committed; sha256 prefixes in `evidence/t01_*`). A loopback
server presents the retired leaf; each client is a fresh interpreter using the unmodified production `tls_context()`
(`t01_tls_trust.py`):

| Scenario | BASE `b22263e` | R6 3.11 | R6 3.12 | R6 3.13 |
| --- | --- | --- | --- | --- |
| `SSL_CERT_FILE` set before interpreter start | **BREACH** (handshake, keyed line seen) | held | held | held |
| `SSL_CERT_DIR` (hashed dir) before start | **BREACH** | held | held | held |
| all three incl. `SSLKEYLOGFILE` | **BREACH** | held, no key log written | held | held |
| all three set after import, before `tls_context()` | **BREACH** | held | held | held |
| lower/mixed-case names | held | held | held | held |
| `OPENSSL_CONF` with `system_default` `VerifyCAFile`/`ChainCAFile` | held | held | held | held |
| no variable (control) | held | held | held | held |

In every R6 case: `check_hostname=True`, `CERT_REQUIRED`, `keylog_filename=None`, 127 system CAs still loaded
(legitimate OS trust kept, not widened), the variables restored. **Under threads** (`t02_tls_env_race.py`) the
process-global hide/restore breaks: concurrent `tls_context()` calls returned contexts **trusting the retired CA**
(9/1198 on 3.11, 12/1197 on 3.12, 12/1196 on 3.13), raised **`KeyError`** from the check-then-pop (2–4 per run), and an
unrelated thread saw `SSL_CERT_FILE` missing for ~95 % of its reads during construction. Second facet
(`t03_tls_floor.py`): production never pins `minimum_version`; on the Ubuntu CPython 3.12.3 build the stock floor is
`MINIMUM_SUPPORTED`, so an environment `OPENSSL_CONF` lowers it to TLS 1.0 and a TLS 1.0-only server gets past
negotiation (certificate still refused; 3.11/3.13 keep TLS 1.2). Together: **RA6-003** (LOW: the live runner constructs
one context in one thread, and a lowered floor does not defeat certificate verification; the function's guarantees
silently depend on both).

### 3.4 RA5-004 (MEDIUM) — absolute transport deadline: **CLOSED for socket phases; RA6-004 (LOW)**

Real loopback TLS server, production `HttpsTransport` (only loopback address + a minted-CA context injected), `D = 3 s`,
wall-clock occupancy measured (`r01_deadline_python3.1x.txt`, identical on 3.11/3.12/3.13):

| Scenario | held / overshoot | outcome |
| --- | --- | --- |
| slow-drip headers 1 B/0.15 s; slow-drip body; chunked drip; drip at 0.9 s/B (inside a per-call timeout) | 3.001 s / +1 ms | NO_RESPONSE / TRUNCATED |
| stall before first byte; raw-TCP handshake stall; whole handshake dripped 1 B/10 ms by a relay | 3.001–3.004 s | NO_RESPONSE |
| connect stalls on 5 resolved addresses (full accept queue) | 3.002 s | NO_RESPONSE (time shared, not 5×) |
| complete response ~0.05 s after the deadline | 3.002–3.004 s | NO_RESPONSE (never RESPONSE) |
| response ~0.10 s before; handshake answered 0.15 s before | 2.90 / 2.85 s | RESPONSE (correct) |
| D = 0, 1 ms, 50 ms | ≤ 3 ms | NO_RESPONSE / NO_RESPONSE / RESPONSE |
| trusted clock steps back 60 s after open | 3.001 s | TRUNCATED (deadline only moves earlier) |
| SIGALRM every 20 ms (EINTR storm) during a drip | 3.001 s | TRUNCATED |

Send is one small TLS record (kernel-buffered); I found no way to make it block on loopback (not a defect). **Name
resolution** is outside the deadline (`transport_http.py:148`). In an isolated user+mount+net namespace with a stalled
fake resolver on `lo` (the production `_Connection` resolving the harmless name `genesis-audit-stall.invalid`):
**10.0 s held against 3 s with glibc defaults and one nameserver, 28.0 s with three nameservers** (no request byte is
ever written late — T0 is checked after connect). That is a practical violation of §14.6 rule 3 occupancy of the same
order as the original 40.6 s finding, but bounded by the stub resolver and without accounting impact: **RA6-004**.

## 4. Modified existing tests — hostile review

Every OLD assertion (from `b22263e`) was run against R6 code (`evidence/old_tests_against_R6.txt`):

| Test | Old assertion on R6 | Verdict |
| --- | --- | --- |
| `test_v05_reader` head-selection | 15/16 pass; the one failure is `assertNotIn(position, (0, 4))` → position 0: the new derivation version's record-id hash order put the newest record first, so the test's *precondition* (naive picks wrong) no longer held. The new loop keeps the identical reader assertions and fails if no candidate places the newest strictly inside | **constructive** (protected invariant unchanged) |
| `test_v05_jsonstrict` | (with a shim supplying the two new required bounds) only `test_pathological_nesting…` differs: `NOT_JSON` → `TOO_DEEP` (and `1`×6000 → `NUMBER_OUT_OF_RANGE`) — still `StrictJsonError`, still rejected | **refinement** (more precise code, same fail-closed invariant) |
| `test_v05_parser_schema` | 15/15 pass with the shim | signature-only change |
| `test_v05_credential` | old global `os.lstat` patch errors on Linux exactly as on the base (RA5-013 test defect); R6's path-specific patch keeps the refusal assertion | **repair** |
| `test_v05_tx01`, `loopback_support` | `TEST_CA` import fails (file removed); R6 passes the per-run CA instead — scenario and assertions unchanged | **infrastructure-only** |
| `test_v05_r2_transport_boundary` HA-13 | `export-ignore` assertion fails (rule removed with the files); replaced by "no fixtures/tls dir" + R6 tests "no key block under `adapters/`", "no key/cert file", git `ls-files -- adapters` | **stronger** (scope note: the static scan covers `adapters/` only) |
| Python TLS-floor assertion | was an R6-new test (not protected); now asserts the production context's floor equals the stock context's. Production never pinned a floor (base or R6); on Ubuntu 3.12 the stock floor is OpenSSL-config-dependent | not a weakening of a protected test (INFO note in RA6-003) |

## 5. Secondary R6 claims

| ID | Independent result |
| --- | --- |
| RA5-005 clock reads | Held (R5 `p12` re-run in `evidence/r5probes_on_R6/`; my mutants X44/X45 — §6) |
| RA5-006 `\Z` | Held: every identifier grammar in `adapters/src` ends in `\Z` (grep); `native_id('abc\n')`, `build_request(bookmaker=['pinnacle\n'])`, Unicode-digit ids/dates rejected (`l01_low_checks.txt`) |
| RA5-007 printable-ASCII key | Held at the loader (mutant X46) |
| RA5-008 ceiling 3 | Held: 0/4/50/`true`/`3.0`/`"3"` refused, 1 and 3 load (`l01_low_checks.txt`) |
| RA5-009 verifier fields | Held: `upstream_version`, `content_type` now compared (mutants X42/X43); provider/source_type/licensing/availability are contract-pinned at publish and reader-checked |
| RA5-011 malformed usage → `QUOTA_DIVERGENCE` | **Fails closed as claimed**, but see **RA6-002**: the disclosed "restart still derives the capture" is not merely an architecture question — it contradicts F-37 ("Observation / head: none", evidence "acquisition + headers") and makes the outcome restart-dependent (uninterrupted: no observation, reads refused; after restart: 12 usable OPEN documents from that very response while the halt is in force). Inherited for "reported > debited" (BASE reproduces); R6 extends it to every unreadable header form |
| RA5-012 survivors | See §6 |
| RA5-013 portable lstat | Held (859 OK on Linux) |

## 6. Mutation

Re-run by me on `4ed66de` (not taken from `AUDIT_HARNESS_MUTATION.txt`), R5's harness unchanged, full suite fail-fast
per mutant, three scratch worktrees, every worker starting with the no-op control (per-mutant table:
`evidence/mutation_table.md`, raw: `evidence/mutation_results_all.jsonl`).

* **R5's 51-mutant campaign:** the control M00 survives (and two extra per-worker controls); **49 killed directly**; M15 and
  M37 report `BAD_SPEC` because R6 rewrote their anchor lines. I inspected the implementer's re-anchored versions: M15-adapted
  applies the identical `+ 1000000` loosening to the `reported > genesis_debited` comparison inside R6's rewritten
  condition, and M37-adapted removes `valid_to` from both sides of R6's longer comparison tuple — the same semantic
  operations on the intended lines. **Both are killed** (by `test_fm37_and_q09_provider_usage_above_the_genesis_debit_halts`
  and `test_every_alteration_of_the_observation_metadata_is_rejected`). All 14 R5 survivors are now killed by
  semantically matching tests.
* **My R6-targeted campaign (50 + control):** skipping terminal-rejection persistence, treating rejection as success,
  re-pending a rejected capture, narrowing/moving the `derive()` catch, one extra nesting level (dict and list), surrogates
  permitted (value and key), exponent/digit bounds off by one, `InvalidOperation`/`RecursionError` escaping the decoder,
  identifier grammar widened or `$`-anchored, participant id back to an exception, four replay-rule relaxations,
  rejection coverage status, rejected-instead-of-halt for a normalized capture, non-total FIXTURES snapshot, hidden
  refusal in `acquire()`, the old Date exception tuple, dropped-Date-as-absent, unparseable Date accepted, each
  environment variable un-hidden, keylog/restore/hostname changes, receive/send not armed, deadline `max`/reset,
  unbounded connect/handshake, a tiny timeout instead of refusal, usage header fail-open / length cap / kept-headers
  presence, each verifier field omitted, both clock-fault guards, the key grammar and the bookmaker ceiling. **49 killed,
  1 detected by hang (X36, unbounded handshake: the handshake-stall test never returns, confirmed in isolation), 0
  survivors.** No equivalence claim is needed. The suite is strong on operator-level changes; RA6-001 is a crash
  *scenario* the suite never exercises (RA6-009).

## 7. Previously closed findings — independent status on R6

R5's own probe set re-run against `4ed66de` (`evidence/r5probes_on_R6/`) and the implementer's 17-probe script run
unadapted and adapted (`evidence/repro17_*_variant_on_R6.txt`):

| Prior finding | Status on `4ed66de` |
| --- | --- |
| HA-01 … HA-12 (BLOCKER/HIGH/MED) | **CLOSED** — every R5 probe of these classes (`p20`, `p40`–`p43`, `p50`–`p55`, `p80`, `p95`, `p130`, `p131`, `p140`, …) prints output identical to R5's transcript on the base; implementer's script 0/17 (adapted) |
| HA-03 (no request byte at/after the deadline) | **CLOSED**, and the response phase is now bounded too (§3.4) |
| HA-04 (every verdict durable; restart converges) | **CLOSED** for every class reproduced so far, including all RA5-001 classes; the new verdict type has the crash-window gap RA6-001, and the inherited F-37 behaviour RA6-002 is a convergence defect of the same family — neither re-opens a reproduced HA-04 case, both are reported as new findings |
| HA-13 / P:HA-006 (test TLS material, trust boundary) | **CLOSED** (no material tracked, production trust not redirectable single-threaded); the unadapted 17-probe script's single "reproduced" line is a false positive on a non-existent file; residual RA6-003 |
| F-01 … F-04 (POSIX) | **CLOSED** (F-04 real symlink and hard link refused on Linux; Windows OPEN) |
| P:HA-013 / P:HA-014 | **CLOSED** (`p60`, `p61` identical to R5; M17/M19/M38/M41/M47 killed) |

No previously closed BLOCKER or HIGH re-opened.

## 8. Findings (severity-ordered; full detail in `FINDINGS.csv`)

| ID | Sev | New / inherited | One line |
| --- | --- | --- | --- |
| RA6-001 | **MEDIUM** | new (R6) | A crash (or an I/O error) between `acq_derivation_rejected` and its coverage entry for a capture that is **not the newest attempt** (G2 → first G2R start) loses the REJECTED coverage record permanently: `settle_last` only settles the newest attempt |
| RA6-002 | **MEDIUM** | inherited, broadened by R6 (RA5-011) | A `QUOTA_DIVERGENCE` response yields no observation in the uninterrupted run but is derived into usable observations at the next start, contrary to F-37 and to restart convergence |
| RA6-003 | LOW | new (R6) | `tls_context()` hides the variables by mutating `os.environ`: concurrent calls trust an environment CA, raise `KeyError`, and leak the removal to other threads |
| RA6-004 | LOW | residual of RA5-004 (disclosed; re-graded with measurement) | Name resolution is outside the absolute deadline: 10 s / 28 s held against 3 s |
| RA6-005 | LOW | inherited mechanism, triggered by R6's new derivation source | A runtime root written under the previous `derivation_version` halts at every start as `EVIDENCE_CONFLICT` (tamper class, QUARANTINED coverage) instead of an explicit derivation-source refusal or §13.3 handling |
| RA6-006 | INFO | new | The terminal rejection is derivation-version-blind: a capture rejected under one source is excluded from every later source and from PIT-09 |
| RA6-007 | INFO | new | Replay of `acq_derivation_rejected` does not re-check role/outcome/status/raw id nor validate `derivation_version`; any `AdapterFailure` is accepted (forgery ⇒ denial only) |
| RA6-008 | INFO | new | Multiple `Date` headers: only the first kept one is judged; a second unusable or over-long `Date` is ignored |
| RA6-009 | INFO | new | Test gap: the claimed crash idempotency of `reject_derivation` has no checkpoint test (no test references `after_derivation_rejected`) |
| RA6-010 | INFO | frozen foundation (out of R6 scope) | Frozen V0.4 test `T6HardLinkAliasTests…toggled_hard_link…` fails 1/10 under CPU contention (0/10 quiet) |

Still open from R5 and unchanged by R6 (accepted as such): RA5-010 (LOW, authority ambiguity), RA5-014…017, RA5-019
(INFO), RA5-018 (Windows, OPEN).

## 9. Verdict

* **Implementation audit: REMEDIATION REQUIRED.** Rule applied: any open BLOCKER/HIGH, or any MEDIUM in a family the
  previous handoff marked "required before G2R/G3 (blocking)", fails the gate. RA6-001 and RA6-002 are MEDIUM defects in
  exactly the R3/R5 "acquisition state across crash and restart" family. No BLOCKER or HIGH is open, and no previously
  closed BLOCKER/HIGH re-opened. RA5-001…RA5-004 are closed as reproduced; RA6-001…004 are what remains.
* **External/platform certification: WINDOWS SYMLINK CERTIFICATION: OPEN** (no Windows host; prior Windows evidence is for
  `9f846d8` and stale). A Linux pass is not Windows certification.

## 10. What this audit did not do

No provider contact, credential, gate record, G1/G2/G2R/G3 action, PR or merge. No Windows run. The retired TLS key was
used only in scratch space and is not committed. Fuzzing and mutation are samples, not proofs. Findings concern
`4ed66de`; any remediation commit must be re-audited.

Companion artifacts: `FINDINGS.csv` (generated by `probes/make_findings.py`), `TEST_RESULTS.md`, `REPRO_COMMANDS.md`,
`WINDOWS_GAPS.md`, `REMEDIATION_HANDOFF.md`, `ARTIFACT_MANIFEST.sha256`; probes in `probes/` (this audit's `a*/d*/l*/n*/q*/r*/t*/v*`
plus R5's harness and probes, unchanged, used for the cross-checks); transcripts in `evidence/` (scratch prefix replaced by
`$AUDIT_WORK`, see `evidence/host_env.txt`).
