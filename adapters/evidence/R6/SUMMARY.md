# V0.5 slice-1 hostile-audit remediation R6 - the R5 re-audit findings (RA5-001 .. RA5-013)

| | |
| --- | --- |
| Status | **R6 remediation CANDIDATE. Not self-certified.** It must go to a fresh independent hostile re-audit. **Windows certification is OPEN** (see `WINDOWS_RECERTIFICATION.md`). |
| Audited evidence commit (unchanged) | `b22263e582386f04e5b7939e511757940ffdfbe0` (`v05-slice1-impl`) |
| Audited code commit (unchanged) | `9f846d8abcd7383d6acae78294f0aefaba08e630` |
| Re-audit being answered | branch `audit/v05-r5-sonnet55` commit `472f2603b0ded3e0199609d59f19185f7c8e4294`, `independent_audits/v05_r5_sonnet55/` (verdict REMEDIATION REQUIRED; read-only here: not modified, not amended) |
| Architecture authority | `V05_ADAPTER_ARCHITECTURE.md` r3 (identical to `c8dfafd`) |
| This branch | `ccr-689a0c12-vys6ag`, on top of `b22263e` |
| Commit | the commit that adds this file; the SHA is recorded in `CANDIDATE.txt` by the evidence-only commit on top of it, and in the hand-off |
| Build host | Linux 6.18 (Firecracker VM), CPython 3.11.15, OpenSSL 3.0.x. **Not Windows.** |

Everything is under `adapters/`; the six frozen trees are unchanged. No provider contact, no credential, no gate record,
no G2, no READY capability, no live betting or strategy code. No pull request, no merge. Fail-closed behaviour was never
relaxed to make a test pass: every change below either closes a hole, makes a failure durable, or tightens a check.

## 1. Method

1. Reproduce each finding with the audit's own probes against the unmodified tree (`PROBES.txt` shows each probe against the unmodified base and against the candidate).
2. Root-cause it; write the invariant-level regression tests first and watch them fail on the unmodified production code
   (`RED.txt`: the final R6 tests against the untouched `b22263e` `src` and `config`).
3. The smallest principled fix; targeted tests green after each; then the full suites (`GREEN.txt`, `FROZEN.txt`).
4. Mutation: 146 single-line mutants of the new and changed invariants, plus the audit's 14 survivors (`MUTATION.txt`).
5. The audit's probes, fuzzers, no-network hook and the prior rounds' 17 reproduction probes against the candidate.

## 2. The four primary findings

### RA5-001 (BLOCKER) - a syntactically valid HTTP-200 body could wedge the pipeline forever

**Root cause.** Schema-valid provider content raised out of the "pure, total" parser after the capture had already been
recorded as a *successful* capture: `decimal.Overflow` (a numeric literal such as `1E+999999999`), `UnicodeEncodeError`
(a lone `\ud800` surrogate in a key or string), `IdentityTypeError` (a 65-digit participant id), `RecursionError` (deep
nesting). The `completed` row carried no verdict, so every `resume()` re-derived the capture and raised again,
`pending_work()` reported it for ever, every read was refused (`DATA_CAPABILITY_NOT_READY`), and an operator `reset`
changed nothing (probes `p118`, `p119b`, `p124`). Fixing four examples would only have moved the wedge.

**Invariant fixed** (design 11.1, 14.4, 15 D13): after ANY syntactically valid 200 body Genesis reaches a durable,
restart-stable state - usable documents, or an explicit durable refusal with coverage - and the raw evidence is never
touched.

**Implementation.**
- *Precise outcomes at the strict decoder* (`jsonstrict.py`): nesting deeper than the policy bound is `TOO_DEEP`, a numeric
  literal whose adjusted exponent exceeds the bound (either direction) - or that `Decimal` cannot represent at all - is
  `NUMBER_OUT_OF_RANGE`, a lone surrogate anywhere (key or value) is `INVALID_UTF8`; the structure walk is iterative, so
  the recursion limit is no bound and the outcome does not depend on the caller's stack. Both bounds are new
  policy-digested fields (`json_max_depth: 50`, `json_max_number_exponent: 1000`), passed explicitly (no default). New
  taxonomy codes `NESTING_TOO_DEEP`, `NUMBER_OUT_OF_RANGE`, `DERIVATION_FAULT` (frozen reason `SCHEMA_REJECTED`, coverage
  `REJECTED`); one `errors.JSON_FAILURE` map serves capture time and the parser. Such a body is now rejected *before* the
  `completed` row, which carries the verdict (the HA-04 mechanism).
- *Identity*: `_participant` treats an id outside the native-id grammar as `PARTICIPANT_AMBIGUOUS` (F-22), never an
  exception.
- *Totality as an invariant, not a list*: `derivation.derive()` runs parse + document building inside one boundary; any
  `Exception` becomes `DERIVATION_FAULT` (detail = the exception class name, screened like every persisted record).
  `build_fixture_snapshot` is total too (a poisoned FIXTURES capture would have wedged every later ODDS derivation).
  `except Exception` cannot swallow `KeyboardInterrupt`/`SystemExit` (FRZ-11 unchanged).
- *Durable terminal verdict*: a new replay-validated ledger row `acq_derivation_rejected` (only for a COMPLETED, content-
  checked, not-yet-derived response; never after `acq_normalized`; failure code and detail validated), settled into one
  `REJECTED` coverage entry (`AcquisitionRunner.reject_derivation`, idempotent across a crash at every write).
  `successful_capture` is false for such a capture, so `resume()` never re-derives it, nothing is pending, reads are not
  refused for it, and no operator action is needed. A capture that was ALREADY normalized and later fails to derive is
  still an integrity halt (never a silent rewrite). `pipeline.acquire` returns the refusal as the outcome's failure.
- `CODE_VERSION` is `mb-normalize-3`; with the two policy fields this is a **new derivation source** by design (9.2,
  13.3): any earlier G2R pin of the old `derivation_version`/`policy_digest` is stale.

**Found beyond the audit (fixed in the same invariant).** (i) a *fifth* wedge class: a `fixtureId` outside the native-id
grammar made normalization halt the pipeline on every attempt - now a terminal rejection; (ii) the strict decoder itself
leaked `decimal.InvalidOperation` (an `ArithmeticError`, not a `ValueError`) for exponents beyond Decimal's range - a
raw-stage escape, now `NUMBER_OUT_OF_RANGE`.

**Tests.** `test_v05_r6_poison_pill.py` (27): the four classes end to end (`acquire -> restart -> resume -> reader`),
parser level, the safety net for every exception family at parse and at document building (also after a policy change
between capture and normalization), the ledger replay rules for the new row, a seeded property/fuzz sweep of every leaf
of the base ODDS fixture with the audit's hostile literal pool (the pure stage raises nothing and the safety net is never
what catches a known class), and the FIXTURES builder. `test_v05_jsonstrict.py` +17 (exact bound, one more, both exponent
directions, integers, the recursion limit, payload-free errors). Mutants J01-J17, E01-E04, A01-A13, D01-D05, P01-P03,
R01-R03: all killed. Probes `p113 p118 p119b p120 p124` and the fuzzers `p114 p116 p117 p119 p121` (four seeded runs of
10000/8000/12000/12000 iterations): no escape (`FUZZ.txt`).

### RA5-002 (MEDIUM) - a huge-year `Date` header orphaned the attempt

**Root cause.** `parsedate_to_datetime` raises `OverflowError` for a year such as `99999999999`; `parse_http_date` caught
only `(TypeError, ValueError, IndexError)`, and it runs after the raw evidence is published and before `acq_completed`,
so the exception orphaned the attempt (rows stop at `acq_sent`, a debit stands, the response is lost; `p123`).
A related hole: an over-long `Date` was dropped by the header allowlist and then read as "no Date" (accepted when the
capture does not require one).

**Fix.** `parse_http_date` is total (conversion inside the `try`, any exception = unusable). A `Date` that was sent but
is unusable - unparseable, naive, non-GMT, out of range, or dropped for length (`Captured.date_dropped`) - is a
deterministic `CLOCK_SKEW` verdict: quarantine plus the next-day suspension (design 6.1, 6.4, 14.6, F-12), durable in the
`completed` row. **Tests** `test_v05_r6_date_header.py` (12): a corpus split into unusable / leniently-parsed / oversize
values, a seeded fuzz over date-shaped strings, in both capture modes, through the runner (durable row, quarantine,
suspension, nothing for a restart to reconcile), the exact skew boundary. Mutants H01-H07: killed (H03 is equivalent, see
section 5).

### RA5-003 (MEDIUM) - production TLS trust was environment-controlled, and the key to a trusted leaf was committed

**Root cause.** The repository committed a test CA, the PRIVATE KEY of a leaf for `api.oddspapi.io`, and the production
`tls_context()` was the interpreter's stock context, which obeys `SSL_CERT_FILE`/`SSL_CERT_DIR` (and `SSLKEYLOGFILE`).
One environment variable made the unmodified production transport trust that CA, complete the handshake and hand the
keyed request line to anyone with the repository (`p70`: `RESPONSE 200 | server saw keyed request line: True`).

**Fix, three ways.** (1) `tls_context()` builds the stock platform context with those three variables hidden, restored
afterwards (also on failure), and then states `keylog_filename=None`, host-name checking and `CERT_REQUIRED` itself:
legitimate OS trust is kept, nothing the environment adds is. (2) No certificate or key is committed at all: the three
fixture files are deleted, and the loopback tests mint a throwaway PKI per run with the standard library only
(`adapter_tests/tls_support.py`: ECDSA P-256 + a minimal DER writer, verified against OpenSSL; a client trusts the minted
CA only through an explicit `cadata=` context). (3) The retired CA is pinned as a negative vector.
**Tests** `test_v05_r6_tls_boundary.py` (26): the worst-case attacker (a valid CA and a valid leaf for the production host
name) via `SSL_CERT_FILE`, `SSL_CERT_DIR`, all three, and set before the interpreter starts; the control that an explicit
test context does complete the handshake; environment restoration; static checks that no key block or key/certificate
file exists under `adapters/` or in `git ls-files`; the minter against OpenSSL. **Evidence** (`PROBES.txt`, section
`p70_history_attack`): the audit's probe on the unmodified tree reproduces the defect; against R6 production code with
the FULL old attacker material restored from history (old CA and old leaf key) the outcome is `NO_RESPONSE` and the server
never sees a keyed line. Mutants S01-S09: killed. **Operational consequence:** a TLS-inspecting proxy's CA must be
installed in the system store; it can no longer be named by an environment variable.

### RA5-004 (MEDIUM) - a slow-drip response held the transport 40.6 s against a 3 s deadline

**Root cause.** Every `recv` got a fresh socket timeout, and `http.client`'s buffered reader loops raw reads: a peer pacing
bytes just inside the timeout was never timed out. `p11`: `send()` returned after 40.63 s with `RESPONSE` and `T1` 37 s past
the deadline, holding the single writer and its run lock (design 14.6 rule 3: "at the deadline the connection is aborted").

**Fix.** `transport_http._Connection` owns ONE absolute monotonic deadline that only ever moves earlier; every blocking
operation - each connect attempt (each resolved address under the time left), the TLS handshake, the send, and EVERY
receive, head and body bytes included, through `_BoundedSocket`/`_BoundedReader` - is armed from it first, and an
exhausted deadline arms nothing. `_BoundedSocket` keeps the standard-library close contract (a `Connection: close`
response closes the connection object early and keeps reading through its `makefile` reader: the real close waits for the
last reader). The transport's own remaining-time checks and the runner's `T0`/`T1` deadline checks are unchanged. **Result:**
`send_returned_after_s` 3.0 on the same probe, `TRUNCATED`, recorded by the runner as `DeadlineExceeded`, writer released.
**Tests** `test_v05_r6_deadline.py` (30): fake connections on a controlled clock (time re-derived before every operation,
exact equality), the real slow-drip body / slow-drip head / never-completing handshake on loopback sockets, a drip that
finishes in time is still a response, the wrapper over a socket pair, `_Connection` arithmetic on a controlled monotonic
clock (connect attempts, `settimeout` only shortens), the wrapper's close contract, the runner's `T0`/`T1` edges and a slow
peer through the real transport and runner. Mutants T01-T14 and the audit's M03, M04, M07, M08, M09: killed.

## 3. Secondary findings (done only where narrow and safe)

| ID | Sev | R6 | What changed |
| --- | --- | --- | --- |
| RA5-005 | LOW | fixed | the two unguarded clock reads inside an attempt (quota decision stamp, `T0`) and the replay-broken halt stamp now end in a durable `CLOCK_FAULT` halt, no send; sweep over every read index (a fault on the very first read of an EMPTY ledger has no durable timestamp to stamp a halt with: the pre-existing rule of `_halt`, unchanged) |
| RA5-006 | LOW | fixed | every identifier grammar ends in `\Z` instead of `$` (16 patterns in `ids`, `maps`, `endpoints`, `schema`, `invalidation`, `config`, `raw_capture`); `_JSON_TYPE` (a media-type test) and the MULTILINE parsers in `verify.py` are not identifier grammars and are unchanged |
| RA5-007 | LOW | fixed at the loader | `CredentialSource` accepts printable ASCII without a space only (design 7.5 "one line with the key; anything else is refused"); `Secret` itself still accepts any non-control Unicode, so a non-ASCII `Secret` built outside the loader still lacks the body-scan Latin-1 views |
| RA5-008 | LOW | fixed | `OPERATIONAL_DECLARED_BOOKMAKERS = (1, 2, 3)` (design 8.4/MKT-02) enforced by `load_adapter_config` in both loader modes; deliberately not a policy field (a policy edit cannot widen it) and literal-free for FRZ-10; a test-only policy built with `parse_policy` may still declare more (MKT-02). The exchange/kind rule stays in the maps loader, which the runtime runs before any send |
| RA5-009 | LOW | fixed | `verify_response_derivation` also compares `upstream_version` and `content_type` (every emitter-set field the source contract does not itself pin) |
| RA5-010 | LOW | **unchanged** | authority ambiguity (fixture-level omissions inside a present tournament): needs G2 evidence of provider completeness or an ADR; recorded as open |
| RA5-011 | LOW | fixed | a present but unreadable usage header (also over-long, repeated, any case) is uncertainty about the budget and halts like a divergence (`QUOTA_DIVERGENCE`); presence is judged from the headers as received |
| RA5-012 | LOW | fixed | all 14 survivors killed (`MUTATION.txt`); the R3 "equivalent" label is withdrawn (`UnpinnedScopeTests`); M40 is killed, not equivalent |
| RA5-013 | LOW | fixed | the credential link test patched the process-wide `os.lstat`; it now reports a link for the credential path only. Suite green on Linux/3.11 |
| RA5-014 .. 019 | INFO | unchanged | static scanners remain lint; T0 write-ahead reading, `reset` authority, F-44 diagnostics (no redesign of the raw-publish failure model, as instructed), invalidation-on-I/O-error: unchanged. RA5-018 (Windows) stays open |

## 4. Test and configuration changes to existing files (disclosed)

- `test_v05_jsonstrict.py`: a helper supplies the new required bounds; two expectations were **refined**, not weakened
  (deep nesting and a huge exponent were `NOT_JSON`/accepted-by-accident, they are now `TOO_DEEP`/`NUMBER_OUT_OF_RANGE`);
  +17 tests. `test_v05_parser_schema.py` passes the bounds.
- `test_v05_r2_transport_boundary.py`: the HA-13 `export-ignore` assertion is replaced by the stronger "no key material
  exists" tests (`test_v05_r6_tls_boundary.py`); `adapters/.gitattributes` loses the `export-ignore` rule for the deleted files.
- `loopback_support.py`, `test_v05_tx01.py`: use the per-run PKI instead of the committed files.
- `test_v05_credential.py`: RA5-013 (path-specific `lstat` patch).
- `test_v05_reader.py`: `test_the_head_is_the_unique_latest_admissible_record_not_the_first_by_record_id` relied on the
  record-id hash order of one specific derivation version (the new version put the newest record first); it now selects a
  newest price that puts the newest record strictly inside the order, so it holds for every derivation version.
- New: `tls_support.py` and five `test_v05_r6_*` modules (169 new test methods in total; the suite is 690 -> 859).
- Policy: `json_max_depth` (50) and `json_max_number_exponent` (1000), provisional like every slice-1 value (50 and not 64
  because FRZ-10 refuses a policy value equal to an existing numeric literal; the scanner was not touched).
- `adapters/README.md`: the test-only material and trust-boundary notes are rewritten.

## 5. Results (all on the build host; none is a Windows result)

| Check | Result | File |
| --- | --- | --- |
| R6 tests vs UNMODIFIED `b22263e` production code | RED: poison pill 70 failing checks / 27 tests, date 14 / 12, deadline 19 / 30, low findings 72 / 57, TLS 13 / 26, jsonstrict 134 / 25, parser_schema 1 / 15 (subtests counted separately). `test_v05_credential` and `test_v05_reader` pass on both: their edits repair test defects | `RED.txt` |
| Adapter suite | **Ran 859, OK, 0 skipped** (161.4 s; the POSIX real-symlink test runs and passes). The base on this host: 690 run, 1 error (RA5-013) | `GREEN.txt` |
| Frozen V0.4 suite | **Ran 493, OK, skipped=19** (Linux platform skips, design 21 A11): count-identical to the Linux pre-R6 baseline | `FROZEN.txt`, `FROZEN_COMPARE.txt` |
| No-network audit hook (whole suite) | 859 run; 2 non-loopback `getaddrinfo` attempts, both the suite's deliberate guard self-test | `NO_NETWORK.txt` |
| Static | `compileall` clean, `git diff --check` clean, six frozen tree SHAs unchanged (`src 51cb635b...`, `tests e90b2981...`, `config abd22db0...`, `tools a0e3411e...`, `DECISIONS cc97ec6f...`, `v04_pack 3c3c1c27...`), freeze guard and module-provenance guard PASS | `COMPILE.txt`, `DIFFCHECK.txt`, `TREES.txt`, `GUARDS.txt` |
| Fuzz | audit `p116` x2, `p119` x2 (42000 iterations), `p114`, `p117`, `p121`: no escape | `FUZZ.txt` |
| Audit probes on the candidate vs the base | every RA5-001/002/003/004/005/006/008/009/011 probe flips from defect to held | `PROBES.txt` |
| Prior rounds' 17 controlling-audit probes (HA-01..HA-12, F-01..F-04, P:HA-013/014) | 17/17 NOT REPRODUCED with ONE disclosed adaptation (the HA-13 probe assumed a tracked key file whose `export-ignore` protected it; both are gone). Unadapted: 16/17 and that one line | `REPRO17.txt` |
| Mutation (mine) | 146 mutants: 142 killed, 4 equivalent. First pass of the 76-mutant campaign killed 58 and exposed 18 test gaps (replay rules, transport arithmetic and close contract, snapshot totality...); 17 tests were added and 17 of the 18 now die. All 14 audit survivors die | `MUTATION.txt` |
| Mutation (the audit's own harness, `probes/mutate.py`, full suite fail-fast, on a clone of the candidate) | all 51 mutants: 49 killed outright, the no-op control M00 survives as required, and the two whose anchor text R6 rewrote (M15, M37) report `BAD_SPEC` on the original spec and are KILLED once re-anchored (`M15-adapted`, `M37-adapted`). No survivor | `AUDIT_HARNESS_MUTATION.txt` |
| Interpreters | the complete adapter suite on this host's CPython 3.11.15, 3.12 and 3.13: all OK (3.12 first exposed a platform-dependent TLS-floor assertion in an R6 test, since made portable) | `PYTHON_MATRIX.txt` |

Equivalent mutants (each with its argument): `H03` (dropping `moment.tzinfo is None` in `parse_http_date`: a naive datetime's
`utcoffset()` is `None`, and `None != timedelta(0)`); `RA5-009-omit-parser_version` (the evidence layer refuses to publish an
observation whose `parser_version` differs from the source contract's, and the verifier already requires the contract);
`RA5-006-_DATE` (`_render_date` re-checks `fromisoformat(value).isoformat() == value`, which rejects a trailing LF);
`R3b` (a missing pinned scope hash: `pipeline._inputs` refuses to derive an ODDS capture without one, so no RESPONSE
document exists to be verified: with no pinned scope `acquire` raises `DerivationError`). The R3 survivor the audit disproved is NOT among them.

## 6. Remaining known issues and residual risk

- **Windows: OPEN.** No real NTFS symlink/junction test, ACL, lock, `STATUS_CONTROL_C_EXIT`, coarse-clock or checkout check
  was run; the earlier Windows suite evidence is for `9f846d8` and is stale (`WINDOWS_RECERTIFICATION.md`).
- **Name resolution** (`getaddrinfo`) is the one step the interpreter cannot bound with a socket timeout: a stalled resolver
  can still overshoot the deadline. The TLS handshake and every read are bounded; the request is one small TLS record, so
  `sendall` is bounded in practice, not by construction.
- **The retired leaf key remains in Git history** (it cannot be rewritten). Production never trusts it (tested); anyone with
  history can mint certificates for the host, which only matters to a client that trusts the retired CA.
- **Pre-existing, observed, unchanged:** after a `QUOTA_DIVERGENCE` halt, a restart derives that attempt's capture (F-37 says
  "effect on head: none"); the halt itself is durable and blocks sends. The new unreadable-usage halts inherit this. An
  architecture decision, not an R6 change.
- **RA5-011 fails closed on an unexpected counter format.** The usage header's semantics are provisional until G2 (A12): if
  the provider formats the counter in some other way (say `12/250`), every response halts the runner until G2 settles the
  format and the reader is adapted under a new derivation source. That is the intended direction of failure.
- Python builds differ in the TLS floor of the stock context (this host's 3.12 reports none, 3.11 and 3.13 report TLS 1.2);
  production uses the stock context unchanged and the test asserts equality with it, not a number.
- RA5-010 and RA5-014 .. 019 as in section 3. A non-ASCII `Secret` constructed outside the credential loader still lacks
  Latin-1 body-scan views (RA5-007 closed at the only production entry).
- Open to the re-auditor by construction: a hostile reading of the new `derive()` boundary ("any exception becomes a
  verdict") is an invariant; the audit's own fuzzers found nothing, but they are not a proof.

## 7. Interpretations R6 introduces (for the re-auditor to accept or reject; none loosens an invariant)

1. **A new ledger row `acq_derivation_rejected`** (attempt state `DERIVATION_REJECTED`). Design 11.1, 14.4 and 15 D13 require
   every failure to end in "no usable observation + durable coverage" but do not name a row for a failure that happens
   AFTER a response passed its content checks; this is the smallest durable representation of that outcome.
2. **Three additive detail codes** (`NESTING_TOO_DEEP`, `NUMBER_OUT_OF_RANGE`, `DERIVATION_FAULT`), frozen reason
   `SCHEMA_REJECTED`, coverage `REJECTED` (design 15 F-13/F-14 are additive by construction).
3. **Two new provisional policy fields** (`json_max_depth` 50, `json_max_number_exponent` 1000): policy-digested, classified
   `PROVISIONAL_SLICE1_POLICY`, to be revisited with G2R evidence (the committed, documentation-derived ODDS fixture nests ten containers deep; the bound is 50).
4. **`OPERATIONAL_DECLARED_BOOKMAKERS = (1, 2, 3)` is code, not policy**: FRZ-10 forbids numeric tunables in code, and design
   8.4 forbids a policy edit from widening this one. It is a closed set of permitted counts, not a tunable, and the scanner
   was not touched.
5. **The credential grammar is stricter than the design's wording** ("one line with the key"): printable ASCII, no space.
6. **A present but unreadable usage header is a divergence** (design 14.2 "provider-reported usage > Genesis debit" read
   as "the budget cannot be trusted"); A12 says the header itself is provisional until G2.
7. **Production TLS ignores `SSL_CERT_FILE`, `SSL_CERT_DIR`, `SSLKEYLOGFILE`** (design 7.6 says "system trust store"; the
   interpreter's stock context also obeyed these variables).

## 8. Reproduction (from the repository root)

```text
PYTHONPYCACHEPREFIX="$(mktemp -d)" python3 -B -m unittest discover -s adapters/adapter_tests -t adapters -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . -v
PYTHONPYCACHEPREFIX="$(mktemp -d)" python3 -B -m compileall -q src tests adapters/src adapters/adapter_tests
git diff --check; for t in src tests config tools DECISIONS v04_pack; do git rev-parse HEAD:$t; done
```

`scripts/` holds the mutation harness and both campaigns, the probe runner and the chained validation script, as `.txt`.
