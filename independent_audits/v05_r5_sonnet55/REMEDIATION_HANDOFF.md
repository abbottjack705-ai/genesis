# Remediation handoff (for the implementer; the auditor changed nothing)

Audited: `b22263e582386f04e5b7939e511757940ffdfbe0` (code `9f846d8abcd7383d6acae78294f0aefaba08e630`).
Authority: `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe`. Verdict: **REMEDIATION REQUIRED** (one BLOCKER, three MEDIUM).
Every item below has a deterministic reproduction in `probes/` and a transcript in `evidence/`.
**Do not weaken a test, edit the architecture, or touch the six frozen trees to make any item pass.** Keep each fix
minimal; each needs the stated regression to be written RED first against the unmodified candidate.

## Required before G2R / G3 (blocking)

### R-A  `RA5-001` BLOCKER — make the response→document path total, and give it a durable, recoverable verdict

Minimal requirement:

1. `parser.parse_odds_response` and `normalize.build_documents` must never raise for provider-controlled content.
   Reachable today (all schema-valid HTTP-200 bodies): `decimal.Overflow` (any numeric literal with exponent beyond the
   parser's `Context(prec=40)` Emax in a field copied through `_comparable`/`decimal_text`, e.g. `changedAt: 1E+999999999`),
   `UnicodeEncodeError` (a lone surrogate in any `players.*` status/price/changedAt/… string, via the frozen
   `canonical_json` UTF-8 encode), `IdentityTypeError` (`participant1Id` ≥ 65 digits passes the `int` type test and then
   fails `native_id`'s 64-character grammar), `RecursionError` (≈500–990 nested levels in a typed field; `json.loads`
   accepts them, `_comparable`/`validate_closed` do not).
2. Every such condition becomes a defined taxonomy outcome (`SCHEMA_REJECTED` / `PARTICIPANT_AMBIGUOUS` / `NOT_JSON` …)
   with coverage. Record it in the **`acq_completed.failure` verdict before that row is written** (the HA-04 mechanism:
   run the parse inside the content-check stage), so `successful_capture()` is false and `resume()` can never re-derive
   it.
3. Bound JSON nesting depth and per-field numeric exponent in `jsonstrict`/schema validation (policy-digested fields;
   no literals, FRZ-10).
4. `quiescence.pending_work` must not be able to refuse reads forever: an unparseable capture needs a terminal durable
   state. If a halt is intended instead, it must be a durable `acq_halted` row that `reset` can clear — today the
   exception is re-raised by every `resume()`, `cli run --mode G2R` cannot start, and `reset` does not help
   (`probes/p119b_no_remedy.py`).

Required regression (RED first): (a) the four minimised repros as unit tests at parser level **and** end to end
through `AdapterRuntime.acquire → resume → reader` (outcome defined, no exception, `pending_work() == ()`, a later
healthy capture usable); (b) a seeded property/fuzz test over every leaf of the base ODDS fixture with the hostile
literal pool in `probes/p116_fuzz2.py` (must find zero escaping exceptions); (c) the same for the FIXTURES snapshot
builder (currently clean) so it stays that way.

### R-B  `RA5-003` MEDIUM — close the production trust boundary for real

* The live CLI must refuse to run when `SSL_CERT_FILE`, `SSL_CERT_DIR` (and any other trust-store override the
  interpreter honours) is set, or `tls_context()` must load the system store explicitly without environment overrides.
* Do not commit a private key whose certificate names the production host. Generate the loopback CA/leaf at test time
  into a temporary directory (and use a non-production SAN with an explicit `server_hostname` in the test context), or
  at minimum constrain the test CA with name constraints and a short validity and remove the leaf key from the tree.
* "Release exclusion" must be enforced, not documented: add a test that fails if any file under `fixtures/tls/**` is
  reachable from a built distribution/archive, **and** one that fails if the committed material can make the production
  `tls_context()` verify (`probes/p70_tls_env.py` is the reproduction).

Required regression: the p70 scenario must end in `SSLCertVerificationError`/refusal; static test that no private key
blob exists under `adapters/`.

### R-C  `RA5-004` MEDIUM — enforce the hard deadline on the response phase of a real socket

Per-`recv` timeouts do not bound a slow-drip body: a 3 s deadline held the transport for 40.6 s and returned
`RESPONSE` with `T1` 37 s past the deadline (`probes/p11_slowdrip.py`); the runner then discards it, but only after the
single writer (holding the run lock) has been held. The "attempt is aborted at the deadline" property of §14.6 rule 3
needs an absolute bound: e.g. non-blocking/`select`-driven reads that recompute the remaining time on **every** read,
or a watchdog that closes the socket at the deadline. Mutants M03/M04 (read-loop/connect deadline checks removed)
survived the suite, so the tests do not exercise this branch.

Required regression: a **real loopback socket** test with a slow-drip server whose total body time exceeds the deadline;
assert the call returns by `deadline + ε` with `NO_RESPONSE`/`TRUNCATED`, never `RESPONSE`.

### R-D  `RA5-002` MEDIUM — make header handling total

`parse_http_date` catches `(TypeError, ValueError, IndexError)` but `email.utils.parsedate_to_datetime` can raise
`OverflowError` (`Date: Mon, 01 Jan 99999999999 00:00:00 GMT`). The exception escapes `validate()` after the raw
evidence is published and before `acq_completed`, so the attempt is orphaned (debit stands, data lost, process
crashes) instead of quarantined `CLOCK_SKEW` (§6.1, F-12). Catch `ArithmeticError`/`Exception` and treat any
unparseable `Date` as `CLOCK_SKEW`.

Required regression: Date-header fuzz (huge year, NUL, non-ASCII, 5000 digits) ⇒ `CLOCK_SKEW` quarantine, no exception.

## Required before the corresponding gate, lower priority

| Finding | Do | Regression |
| --- | --- | --- |
| `RA5-005` LOW | Wrap the two un-guarded `self._stamp()` calls in `_acquire` (after `quota.reserve`) and `_send` (T0) so a `ClockFault` yields the same durable `CLOCK_FAULT` halt as the other windows | clock raising on read #3 and #4 of an attempt ⇒ `AcquisitionHalt(CLOCK_FAULT)` + `acq_halted` row (`probes/p12_runner_deadline.py`) |
| `RA5-006` LOW | Replace `$` with `\Z`/`fullmatch` in every identity/request/map grammar (`ids.py`, `maps.py`, `endpoints.py`, `schema.py`, `invalidation.py`, `config.py`) | `native_id("abc\n")`, `build_request(bookmaker=["pinnacle\n"])` rejected |
| `RA5-007` LOW | Restrict the credential grammar to printable ASCII at load (simplest), or add Latin-1/mojibake views to the **body** scan as already done for headers (HA-07) | non-ASCII key echoed as Latin-1 / mojibake in a body ⇒ `SECRET_ECHO` |
| `RA5-008` LOW | Enforce the architecture-fixed cap of 3 declared bookmakers in code (reject `declared_bookmakers_max > 3` outside a test policy) | policy with `declared_bookmakers_max: 50` refused by the operational loader |
| `RA5-009` LOW | Compare `upstream_version` and `content_type` in `verify_response_derivation` (§11.3 values) | observation with altered `upstream_version`/`content_type` rejected |
| `RA5-010` LOW | Obtain a provider completeness signal at G2, or extend the "unproven omission" rule to fixtures/bookmakers in a present tournament; record in the G2 report which holds | omitted fixture inside a present tournament ⇒ no ABSENT tombstone |
| `RA5-011` LOW | Treat a present but unparseable provider-usage header as `QUOTA_DIVERGENCE`-class uncertainty (halt/quarantine) | `x-requests-used: 1e5` etc. ⇒ halt |
| `RA5-012` LOW | Add the missing negative tests: late response at `T1 == deadline`/`+1µs`, runner `T0 == deadline`, real-socket read deadline, a credential made only of percent-encodable characters echoed double-encoded and with escaped slashes, altered observation `valid_to`, a document derived under an unpinned scope (the claimed *equivalent* mutant is killable, `probes/p160_equiv_mutant.py`), 0400 key file, gate validity end, duplicate G2 hashes; withdraw the "equivalent" label | mutants M03, M04, M07, M08, M09, M22, M26, M27, M28, M30, M35, M37, M46 and the R3 survivor killed |
| `RA5-013` LOW | Make the simulated-`lstat` test not patch the global `os.lstat` (patch only for the credential path) so it runs on POSIX | suite is green on Linux/CPython 3.11 with no skips |

## Recommended, no gate dependency

`RA5-014` replace syntactic static scanners with a stronger gate or document that they are lint (aliases,
`from contextlib import suppress as s`, `signal.signal(SIGINT, SIG_IGN)`, `__import__("socket")` all evade);
`RA5-015` persist the transport's real write-boundary `T0`; `RA5-016` ratify `reset` by ADR;
`RA5-017` decide on `RAW_PUBLISH_FAILED` (see `F44_ASSESSMENT.md`); `RA5-019` consider whether a *read* may append a
permanent invalidation on a persistent verifier exception.

## Certification still owed outside the code

`WINDOWS SYMLINK CERTIFICATION: OPEN` and the checklist in `WINDOWS_GAPS.md` §4. Re-run the full Windows suites at the
final remediated commit; the existing Windows evidence is for `9f846d8` and will be stale.

## What NOT to change

The architecture-conformant behaviours verified in `HOSTILE_REAUDIT_REPORT.md` §3 (deadline equality, boundary guard,
crash/restart convergence for all runner and emission checkpoints, rejected-evidence non-revival, secret scanning of
ASCII forms, gate-limit pin, halt/reset authority, READY time authority, frozen provenance) should stay byte-for-byte.
