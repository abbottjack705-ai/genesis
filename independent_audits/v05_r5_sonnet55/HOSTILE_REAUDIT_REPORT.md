# Project Genesis V0.5 — independent hostile re-audit of the remediated adapter candidate

## V0.5 R5 HOSTILE RE-AUDIT — REMEDIATION REQUIRED

## WINDOWS SYMLINK CERTIFICATION: OPEN

| | |
| --- | --- |
| Exact audited (evidence) commit | `b22263e582386f04e5b7939e511757940ffdfbe0` (`v05-slice1-impl`) |
| Exact code commit under validation | `9f846d8abcd7383d6acae78294f0aefaba08e630` (parent of the audited commit) |
| Architecture authority | `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe` (`V05_ADAPTER_ARCHITECTURE.md` r3) |
| Preserved original failed candidate | `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` (ancestor, verified) |
| Frozen V0.4 foundation | `2278e2a68083f7ac58d796b1ed9c43d50020b6b0` / tag `v0.4-foundation-freeze` |
| Auditor | independent hostile re-auditor (model-assisted); no implementation code was modified, no provider call, no credential, no gate record, no READY, no PR/merge |
| Audit host | Linux 6.18 (VM, 4 vCPU), CPython 3.11.15 — **not Windows** |
| Audit branch | `audit/v05-r5-sonnet55` (created from exactly `b22263e`); artifacts only under `independent_audits/v05_r5_sonnet55/` |

Headline: the R1–R5 remediation genuinely closed every previously reproduced BLOCKER **as reproduced by the earlier audits**,
and my independent attacks could not re-open any of them. But the remediated code still fails under hostile conditions in a
**new** way inside the same "acquisition state across crash and restart" family: **a single schema-valid HTTP-200 response can
permanently wedge normalization, restart and every read** (`RA5-001`, BLOCKER). Three further MEDIUM defects were reproduced
(`RA5-002`, `RA5-003`, `RA5-004`). Per the verdict rule, a reproducible architecture/safety blocker means
**REMEDIATION REQUIRED**.

## 1. Startup verification (all checks performed before any semantic audit)

| # | Check | Result |
| --- | --- | --- |
| 1 | `git fetch origin --prune --tags` and `b22263e` exists on origin (`origin/v05-slice1-impl` = `b22263e…`) | PASS |
| 2 | Parent of `b22263e` is `9f846d8abcd7383d6acae78294f0aefaba08e630` | PASS |
| 3 | `cfcff3d…` is an ancestor of `b22263e` (and `c8dfafd`, `2278e2a` are ancestors) | PASS |
| 4 | `9f846d8..b22263e` is evidence-only | PASS — 73 paths, **all** `A` (added), **all** under `adapters/evidence/FINAL/` |
| 5 | Everything since `c8dfafd` is confined to the adapter scope | PASS — 14 commits; paths touched: `adapters/evidence` 215, `adapters/adapter_tests` 68, `adapters/src` 35, `adapters/config` 8, `adapters/README.md`, `adapters/DECISIONS`, `adapters/.gitattributes`. Nothing outside `adapters/` (root docs and `remediation_evidence/**` untouched) |
| 6 | Frozen V0.4 trees recomputed with `git rev-parse b22263e:<tree>` | PASS — `src 51cb635…`, `tests e90b298…`, `config abd22db…`, `tools a0e3411…`, `DECISIONS cc97ec6…`, `v04_pack 3c3c1c2…`, identical to the frozen foundation, to `c8dfafd` and to §2.1 of the architecture |
| 7 | Architecture read as it existed at `c8dfafd` | DONE (full read, 2,526 lines) **before** any remediation evidence |
| 8 | R1–R5 history read only after the authority | DONE |

No pinned relationship differed from the claims. (`DECISIONS/` holds only a README: there is no in-repository G0
acceptance record, ADR-A001 — a human action, noted as INFO.)

Independence: all of `adapters/evidence/**` was treated as untrusted. Another audit package exists on origin
(`ccr-fd2032c3-zvphjn`, `audit/v05_reaudit_b22263e/`); it states the candidate was *unreachable* in its environment
(its `RA-000`), contains no executed results on `b22263e`, and was read only **after** my principal findings (`RA5-001`…`RA5-004`) had been reproduced. It is
not used as evidence. Its remark that a false ABSENT tombstone is "usability-safe but not evidence-safe" (`RA-007`) is
consistent with my `RA5-010`.

## 2. Verification of the implementer's claims (not trusted; each independently challenged)

| Claim | Independent result |
| --- | --- |
| Adapter suite 690 OK, one real-symlink skip | **Not reproduced as stated** — Linux/CPython 3.11: 690 run, **689 OK + 1 ERROR, 0 skips** (the real-symlink test *runs and passes* on POSIX; a *simulated-lstat* test errors because it patches the global `os.lstat`, finding `RA5-013`). Same result inside a loopback-only network namespace |
| Frozen suite 493 OK, one baseline skip | **Platform-different, no regression**: Linux/CPython 3.11 `Ran 493, OK (skipped=19)`. All 19 skips are Windows-only (AppContainer/Job-object confinement, N2 caseless owners, `os.startfile`, 8.3 short names; §21 A11 predicts this). The Windows `493 OK, 1 skip` is therefore **not reproduced and cannot be here**; the FRZ-04 count comparison is not meaningful on Linux. The six frozen trees and the worktree were verified unchanged after the run (`evidence/frozen_suite_linux.txt`) |
| 167/167 architecture test IDs present | Consistent: my own parse of §18 expands to 166 IDs, every one matched by a test name or a `Frz*` class (counting differences only) |
| 17 hostile repro probes, 0 reproduced | The implementer's own script `adapters/evidence/FINAL/scripts/repro_controlling_final.py.txt` **does run on Linux** (`PYTHONPATH=adapters python -B …`): `reproduced=0 not_reproduced=17 probe_errors=0` (`evidence/implementer_repro17_linux.txt`). That is *their* probe set, not independent evidence; note its HA-13 probe checks only CLI options and `git archive`, so it cannot see `RA5-003`. My own ≈45 probes re-attacked every prior class (none re-opened) and found four defect classes outside those 17 |
| Deterministic replay byte-identical | **Reproduced** independently: two fresh roots, same clock/script, 174 durable files, 0 differing |
| Remediation mutation suite: 128 mutants, 127 killed, 1 equivalent | Not re-run. Independent campaign of **51** single-line mutants of safety branches (no-op control behaves): **37 killed, 14 survived**; every survivor I could probe is a *missing test*, not wrong code (non-equivalence shown by running the same probe on a pristine and a mutated tree). The R3 "equivalent" survivor is **not** equivalent: it is killable through public store APIs (`RA5-012`) |
| Frozen trees unchanged | **Verified** (§1) |
| No provider/API calls | **Verified** — independent audit hook over the full suite: 24 socket events, only loopback plus two refused pre-connect `getaddrinfo` attempts (`192.0.2.1`, `genesis.example.invalid`) that are the suite's own deliberate guard self-test (`test_v05_transport_http.py:173-175`); full suite also passed inside `unshare -rn` with only `lo` |
| No credential use | **Verified** — only synthetic keys (`AUD1T-…`, the repository's public sentinel); no credential file, no environment key |
| No persistent READY | **Verified** — no `authority.jsonl`/`capabilities.jsonl` committed; `OperationalStatus.READY` appears only in `cli.py approve-ready` |
| No betting/model activation | **Verified** by search — no strategy/order/stake terms under `adapters/src` |

## 3. Results by mandatory hostile area

Legend: **HELD** = could not be broken; **FINDING** = a defect reproduced (see `FINDINGS.csv`); evidence file names refer to
`evidence/` and probes to `probes/`.

| Area | Verdict | Summary (independent evidence) |
| --- | --- | --- |
| **A** Credential / secret containment | HELD for ASCII credentials; FINDINGS `RA5-003`, `RA5-007` | 25 echo forms (raw, case, percent, double, `\u` all/mixed/upper, hex, base64 ×3 alignments + URL-safe, exact and one-short fragment, UTF-16/32, gzip decoded-only and wire-only, header value/name, dirty content-type) → halt/quarantine with **zero** leaking files and nothing different after restart (own detector shares no code with the candidate). Transport boundary: 24 attacks (key in message/args/filename/notes/cause/context/warnings/class name/errno; `KeyboardInterrupt`, `SystemExit(int/None/str/bool/float/huge/-1)` at open/write/head/body/close; `KeyboardInterrupt` raised inside the ordinary handler; non-constructible `BaseException`; `GeneratorExit`) → sanitized or fresh exceptions with `__cause__/__context__` `None`, no notes, no key in any product frame local. Residuals: a non-ASCII key echoed as Latin-1/mojibake in a **body** is stored (`RA5-007`); the production TLS context can be redirected by `SSL_CERT_FILE` (`RA5-003`) |
| **B** Hard deadline / clocks | HELD for "no request byte at/after the deadline"; FINDINGS `RA5-004`, `RA5-005` | Transport: deadline at entry, at write, inside connect/TLS/`settimeout`, during write/head/body → never writes at or after the deadline; `deadline−1µs` writes. Runner: slow work between debit and send (61 s ⇒ not sent; 59.9 s ⇒ sent with the right `deadline_at`); `T1 ≥ deadline` ⇒ response discarded (`DeadlineExceeded`), `deadline−1µs` ⇒ accepted. Boundary guard W1–W4 vs an independent oracle: **21,200 points, 0 mismatches** (day/month/leap/year edges, 5 policies). Residuals: a real slow-drip response holds the transport 13× past the deadline (`RA5-004`); a `ClockFault` in two spots escapes raw without a durable halt (`RA5-005`); the late-response guard and several deadline branches are **not covered by any test** (mutants M03/M04/M07/M08 survive) |
| **C** Quota / request replay | HELD | Crash at every runner checkpoint (`before_quota … after_completed`), restart, same plan item ⇒ never re-sent (`DUPLICATE`/`REFUSED ORPHANED_RESERVATION`), explicit `RETRY` ⇒ fresh id and fresh debit; reserve never requested (mutant M36 killed); retries refused unless closed and retryable (`PlanRefused`). Provider-usage divergence halts; **a present but unparseable usage header is ignored** (`RA5-011`) |
| **D** Raw evidence / publication | HELD | Crash at every emission checkpoint (`after_t2 … after_pit:N … after_coverage`) of a second capture with an older head: converged states identical to an uninterrupted run, 24 PIT rows/24 unique ids, one T3 per response, exactly-once coverage; the reader refuses (`DATA_CAPABILITY_NOT_READY`) between the crash and the restart |
| **E** Rejected / quarantined evidence | HELD (16 outcomes); see `RA5-001` for the new class | wrong type, malformed, empty, duplicate keys, NaN, invalid UTF-8, envelope, oversize, skew, secret echo, nested encoding, 301/401/429/500, truncated: after restart **0 PIT, 0 normalized, `pending_work` empty**; secret echo / 401 keep every source `BLOCKED` |
| **F** PIT head / recovery | HELD | newer SUSPENDED/BLOCKED/INVALIDATED/expired heads never fall back (`STALE`, `BLOCKED`, `INVALIDATED`); TTL edge `vt−1µs` usable, `vt` not; cutoffs around `T3`; ties are unreachable through a monotonic clock and are covered by `PITViolation→AMBIGUOUS` |
| **G** Invalidation recovery | HELD | invalidate then restart: `D>T3_inv` ⇒ `INVALIDATED`; historical cutoffs before it unchanged; the old price never revives |
| **H** Derivation verification | HELD for output bytes; FINDINGS `RA5-009`, `RA5-012` | unknown kind, missing scope/request files, altered scope bytes, altered `retrieved_at`/`valid_to`/`publisher_timestamp` all **fail**; **`upstream_version` and `content_type` are not compared** (passes by omission, `RA5-009`) |
| **I** Provider completeness / ABSENT | HELD at tournament granularity; FINDING `RA5-010` | present with data / present-but-empty (ABSENT, proven) / one omitted / all omitted / wrong sport / string id ⇒ no tombstone when unproven. **An omitted fixture inside a present tournament still manufactures ABSENT tombstones** (authority-conformant, F-30; deviation 10) |
| **J** READY / approval time | HELD | backdated `granted_at` refused; within-skew value overwritten with the trusted clock; `--at`/`args.at` ignored by `approve-ready`; READY stamped "now"; cutoffs before approval ⇒ `DATA_CAPABILITY_NOT_READY`; at/after ⇒ usable (real system clock, no patching) |
| **K** Halt / reset authority | HELD | SECRET_ECHO reset refused until a G1 for a *rotated* fingerprint; same-key re-G1 refused; AUTH_REJECTED needs any later G1; mutant M17 killed |
| **L** Fixed gate / G2 limits | HELD for gate limits; FINDING `RA5-008` | edited limits file refused at load (SHA-256 pin); pristine limits refuse 6 requests, 73 h, 36 d. The **3-bookmaker** cap (§8.4) is an unbounded policy field (`declared_bookmakers_max: 50` loads) |
| **M** TLS test material / production seams | FINDING `RA5-003` | no CLI option and no production import of the material; **but** `SSL_CERT_FILE=<test-ca.pem>` alone makes the unmodified production `tls_context()` complete a handshake with the committed leaf (private key committed, SAN `api.oddspapi.io`, valid to 2046, unconstrained CA) and the keyed request line reaches the server; `export-ignore` protects only `git archive` |
| **N** Windows path / link safety | **OPEN — not certified** | POSIX symlink and hard-link refusal verified here; NTFS symlinks/junctions/ACLs not reproducible — see `WINDOWS_GAPS.md` |
| **O** CRLF / frozen provenance | HELD | CRLF-converted frozen module, an extra trailing newline, a same-length byte swap, a shadow `genesis` on `PYTHONPATH`, a competing lower-precedence `genesis`: all fail closed by **bytes** (`MODULE_HASH_MISMATCH`/`COMPETING_GENESIS`); an mtime-only change correctly passes |
| **P** Network boundary | HELD | independent audit hook + netns (see §2) |
| **Q** Mutation / test quality | FINDING `RA5-012`, `RA5-014` | 51 independent mutants: 37 killed / 14 survived (`mutation_results_round1/2.jsonl`). Survivors: runner/transport deadline branches (M03/M04/M07/M08/M09), exact-size body (M22), double-encoded-percent and JSON-slash detectors (M26/M27), base64 core minimum (M28), 0400 key file (M30), gate validity end (M35), `verify_derivation` `valid_to` comparison (M37), duplicate G2 request hashes (M46), quarantine-metadata re-scan (M40, probably equivalent). Non-equivalence proven for M26, M37, M08/M09 and the R3 "equivalent" survivor. SEC-01's encoded-form cases are masked by the fragment detector for ordinary keys. Implementer mutants are R1–R5 deltas only, run against module-restricted tests written to kill them. Static scanners are evadable (`RA5-014`) |

## 4. Prior BLOCKERs and their independent status

Severities and identifiers are as cited by the implementer's own R1–R5 summaries (the controlling audit package itself
is Windows-local and not available to me).

| Prior finding | Class | Independent status |
| --- | --- | --- |
| F-01 sanitized error scanned | HIGH | **CLOSED** (class-name, errno, chained/context, warnings attacks) |
| F-02 gate bounds pinned | MED | **CLOSED** |
| F-03 omitted tournament ⇒ ABSENT | HIGH | **CLOSED** at tournament granularity (residual `RA5-010`) |
| F-04 real symlink | MED | **CLOSED on POSIX; WINDOWS OPEN** |
| HA-01 exception class name is untrusted text | BLOCKER | **CLOSED** |
| HA-02 `close()` inside the process-control boundary | BLOCKER | **CLOSED** (mutants M05/M06 killed) |
| HA-03 no request byte at/after the hard deadline | BLOCKER | **CLOSED** for sends (`RA5-004` is the *response* phase, not a send) |
| HA-04 every verdict durable; restart converges | BLOCKER | **CLOSED** for the reproduced class (16 outcomes, restart-stable). **New reproduction in the same family: `RA5-001`** |
| HA-05 pending invalidation never leaves the old price usable | BLOCKER | **CLOSED** |
| HA-06 one T2/T3 per response, quiescence | BLOCKER | **CLOSED** (mutants M33/M34 killed) |
| HA-07 header octets / reversible forms | BLOCKER | **CLOSED** for headers and ASCII keys; body-path non-ASCII residual `RA5-007` |
| HA-08 every received byte screened | HIGH | **CLOSED** (wire-scan mutant M24 killed; the exact-size-body mutant M22 survives — a missing boundary test, not a defect) |
| HA-09 CLOCK_SKEW not re-armed by the date alone | HIGH | **CLOSED** |
| HA-10 retry state machine | MED | **CLOSED** |
| HA-11 scope pinned before the send | MED | **CLOSED** (the verifier check exists and works; its test is missing, `RA5-012`) |
| HA-12 verifier mandatory on every read | HIGH | **CLOSED** |
| HA-13 / P:HA-006 test TLS material, production trust boundary | LOW | **STILL OPEN (re-graded MEDIUM)** — `RA5-003` |
| P:HA-013 operator-chosen time | MED | **CLOSED** |
| P:HA-014 reset without fresh authority | LOW | **CLOSED** |

## 5. New findings (severity-ordered; full detail in `FINDINGS.csv`)

| ID | Sev | One line |
| --- | --- | --- |
| `RA5-001` | **BLOCKER** | Four classes of schema-valid provider content raise out of the "pure" parser (`decimal.Overflow`, `UnicodeEncodeError`, `IdentityTypeError`, `RecursionError`); the capture is already `completed/success`, so every `resume()` re-raises, `cli run --mode G2R` cannot start, the reader refuses forever, and operator `reset` cannot help |
| `RA5-002` | MEDIUM | A `Date` header with a huge year raises `OverflowError` out of `validate()` after raw evidence is published and before `acq_completed`: crash + orphaned debit instead of `CLOCK_SKEW` quarantine |
| `RA5-003` | MEDIUM | Production `tls_context()` honours `SSL_CERT_FILE`/`SSL_CERT_DIR`; a committed leaf private key for `api.oddspapi.io` + a 20-year unconstrained test CA make that a credential-theft primitive; `export-ignore` is the only "enforcement" |
| `RA5-004` | MEDIUM | The "hard" deadline is only per-`recv`; a real slow-drip response held the transport 40.6 s against a 3 s deadline (tests use fakes) |
| `RA5-005` … `RA5-011` | LOW | raw `ClockFault` windows; trailing-LF in `$` grammars; non-ASCII-credential body path; `declared_bookmakers_max`; verifier ignores two metadata fields; fixture-level ABSENT; malformed usage header fail-open |
| `RA5-012`, `RA5-013` | LOW | overstated mutation claim (killable "equivalent", untested deadline branches); Linux-failing "every platform" test |
| `RA5-014` … `RA5-019` | INFO | syntactic static scanners; write-ahead `T0`; `reset` authority; F-44; Windows symlink OPEN; reads that append invalidations |

## 6. Why the verdict is REMEDIATION REQUIRED (and what it does *not* mean)

* `RA5-001` is reproducible, deterministic and unrecoverable by any operator action, violates §15 D13 ("every failure path
  produces no usable observation … and writes a coverage/exclusion record"), §11.1 (the parser is pure and total) and
  §14.4 (restart must resume normalization deterministically), and makes G3 AC-1/AC-2 unattainable. It is fail-closed — no
  unsafe datum is ever consumed, no secret escapes, no quota is exceeded — so it is an availability/convergence blocker
  for **G2R and G3**, not a data-safety breach. It does **not** affect G2 (raw capture only, nothing normalized).
* Nothing found re-opens a previously reproduced blocker; the remediation quality for those classes is high.
* The **implementation audit result** is therefore: REMEDIATION REQUIRED (one BLOCKER, three MEDIUM, nine LOW).
  The **external/platform certification condition** is separate and still open: **WINDOWS SYMLINK CERTIFICATION: OPEN**.

## 7. What this audit did not do

* No provider contact, no credential, no G1/G2/G2R/G3 action (all forbidden and not performed).
* The controlling Windows-local audit package and the implementer's `oracle_secret_sweep.py` were not available; I wrote
  independent equivalents (own secret detector, own boundary oracle, own fuzzers). Their 17-probe script was re-run only as a
  cross-check.
* Windows behaviour is not reproduced (see `WINDOWS_GAPS.md`); the `msvcrt`/`icacls`/`w32tm`/coarse-clock paths ran nowhere.
* The mutation campaign is a sample (51 mutants over the safety branches), not exhaustive.
* Findings are about commit `b22263e`; any remediation commit must be re-audited.

Companion artifacts: `FINDINGS.csv`, `TEST_RESULTS.md`, `REPRO_COMMANDS.md`, `DEVIATION_REVIEW.md`, `F44_ASSESSMENT.md`,
`WINDOWS_GAPS.md`, `REMEDIATION_HANDOFF.md`, `ARTIFACT_MANIFEST.sha256`; probes in `probes/`, transcripts in `evidence/`.
