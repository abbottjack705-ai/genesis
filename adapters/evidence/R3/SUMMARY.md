# V0.5 slice-1 controlling hostile-audit remediation R3 - acquisition state across crash and restart

| | |
| --- | --- |
| Failed candidate (unchanged) | `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` |
| Base of this commit | R2 `72cca77c1c9ce927bf1248140f638a83c95fd77d` |
| Architecture authority | `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe` (`V05_ADAPTER_ARCHITECTURE.md` r3) |
| Controlling audit | `C:\Users\abbot\a8\v05_prep\audit_oracle\hostile_audit_cfcff3d\` (manifest 10/10 OK; never written to) |
| Findings | HA-04 (BLOCKER), HA-09 (HIGH), HA-10 (MEDIUM), HA-11 (MEDIUM) |
| Commit | the commit that adds this file, on `v05-slice1-impl` on top of R2 (not amended; not pushed) |

Everything is under `adapters/`; the six frozen trees are unchanged. No credential, no provider or network contact,
no gate record, no G2, no READY capability outside throwaway test registries.

## Method

1. `RED.txt` - the R3 tests against the **unmodified R2 production code** (`72cca77`): 30 tests, failures=28,
   errors=14 (subtests counted). The failures are the defects themselves (a rejected response revived into 12 PIT
   rows after a restart; content verdicts missing from the completed row; a retry leaving a row, a debit and a send;
   the CLI run sending a retry the state machine forbids; sends re-armed by the date alone and by an operator reset;
   no scope pinned at the send); the errors are the new probe flag, refusal type and row field. The A2 orphan-retry
   test passes there by design (an orphan stays retryable once; it is the control for the new state machine).
2. The production changes below, then `GREEN.txt`, `MUTATION.txt`, `FROZEN.txt` + `FROZEN_COMPARE.txt`,
   `COMPILE.txt`, `DIFFCHECK.txt`, `TREES.txt`, `GUARDS.txt`; `HASHES.sha256` covers them.

## Finding by finding

### HA-04 (BLOCKER) - every verdict is durable in the completed row; restart converges

- `oddspapi/acquisition.py` `_complete`: the content checks (clock skew, content type, strict JSON, closed envelope)
  run **before** the `acq_completed` row, so its `failure` field carries the verdict; `derivation.successful_capture`
  (and with it every resume path and the fixture join) can no longer mistake a rejected response for a successful
  capture. A skewed response's quarantine metadata is written before the row (it needs the transport headers).
- The side effects of a verdict - quarantine, CLOCK_SKEW suspension, halt (SECRET_ECHO, EVIDENCE_CONFLICT,
  QUOTA_DIVERGENCE, CLOCK_FAULT), circuit (AUTH_REJECTED, RATE_LIMITED), capability block, coverage and the metadata
  cache - are a pure function of the durable verdict row (`verdict_effects`, also for refusals, blocked quota
  decisions and reconciliations). `AcquisitionRunner.settle` applies the missing ones in a fixed order, each exactly
  once (presence by the rows after the verdict, coverage entry ids, the cache index, and for the capability block the
  ledger row that follows it); it runs right after the verdict, and again - after a crash - first thing in
  `reconcile_after_restart` and in every `acquire`. Changes against the uninterrupted order (disclosed): the
  capability block now precedes the AUTH_REJECTED circuit row (that row marks the block as applied); the verdict's
  own effects precede a QUOTA_DIVERGENCE halt (previously the divergence halt pre-empted e.g. the SECRET_ECHO
  quarantine, halt and capability block). `capability.block_market_book_sources(skip_blocked=True)` makes the
  pipeline's blocker idempotent; `QuotaGate.cache_indexed` and `RawCapture.stored_bytes` and
  `CanonicalRequest.from_canonical_bytes` let a restart re-publish a lost metadata cache entry exactly.
- Tests (`test_v05_r3_runner_state.DurableVerdictTests`): the verdict in the completed row for wrong content type,
  malformed JSON, envelope mismatch, unsupported encoding, clock skew, missing `Date` (live rule), secret echo, 401,
  429 and 503; a clean restart revives nothing and adds no halt; and a crash right after **each** durable write that
  follows the completed row (counted, so the matrix follows the real writes), then restart, converges to the durable
  history of an uninterrupted run (acquisition rows, coverage, quarantine, capability rows, cache and cache index,
  evidence, PIT) and behaves identically on the next attempt; a secret-echo crash with no `resume` still sends
  nothing; a settled capability block is never re-applied over a human re-approval; a rejected FIXTURES capture is
  never used by the fixture join; a lost metadata cache entry is re-published exactly once.

### HA-09 (HIGH) - after CLOCK_SKEW, the date alone re-arms nothing

`AcquisitionLedger.circuit_open` keeps a CLOCK_SKEW suspension in force until the next UTC day **and** a clean
`Date` check recorded after it (`acq_clock_rearmed`); an operator reset never ends it. From the next day on only a
clock-check probe (`acquire(..., clock_check=True)`, `cli.py run --clock-check` with exactly one plan item) may go
out - through every other gate and the quota (debited); only a present, parseable, in-bounds `Date` header on its
response (`RawCapture.clean_date_check`) writes the re-arm row. Refusal detail before the check:
`CLOCK_SKEW_DATE_CHECK_PENDING`. BND-07 was updated to the explicit probe (it encoded the defect: an ordinary send on
the new day acted as the check). A crash before the re-arm row leaves sends suspended (a new probe is needed).

### HA-10 (MEDIUM) - the retry state machine in the production runner

`AcquisitionRunner._check_retry` runs before anything durable and raises `errors.PlanRefused(reason, not_before)`:
attempt `n > 1` must be a `RETRY` of attempt `n - 1` of the same request and window (closed, not open); its outcome
must be retryable (`retry_decision`: no response or 5xx, or a reconciled crash), within `max_retries_per_window`,
after the backoff, before the item's required `not_after`, and with quota headroom; a first attempt is never a
RETRY. `cli.py run` passes `not_after` from the plan and stops with `refused: ... retry not permitted (<reason>)`.
Refusal by exception rather than a ledger row: no failure code for it exists in the design 15 taxonomy, and nothing
happened. Existing tests that retried the old way (attempt 2 with a SCHEDULED purpose, no window, no backoff:
Q04, A2, and two A3 crash tests) now use the conformant form; their semantics (fresh identity, fresh debit, never
re-sent under the old id) are unchanged. An attempt reconciled as NOT_RESERVED (crashed before its debit) is
retryable like an orphan.

### HA-11 (MEDIUM) - the expected scope is pinned before the send

`AcquisitionRunner(scope_pinner=...)`: for an ODDS request the pipeline computes the expected scope as of `Tq` and
publishes `scopes/<hash>.json` before `acq_sent`, whose new field `expected_scope_hash` carries it (None for metadata
requests). Normalization and resume read exactly that scope (an ODDS capture without one is refused), and
`verify_derivation` / `rebuild_into` require the document's scope to be the one pinned on the sent row.
Test-harness seeds of `acq_sent` (`emit_support`, `test_v05_pit`, the ledger tests) carry the new field.

## Changed files

Production: `oddspapi/acquisition.py`, `oddspapi/pipeline.py`, `oddspapi/raw_capture.py`, `oddspapi/endpoints.py`,
`oddspapi/derivation.py`, `oddspapi/capability.py`, `oddspapi/quota_gate.py`, `errors.py`, `cli.py`; `README.md`.
Tests: new `test_v05_r3_runner_state.py`; changed `test_v05_bnd07.py`, `test_v05_acquisition.py`,
`test_v05_pipeline.py`, `test_v05_raw_capture.py`, `test_v05_pit.py`, `emit_support.py`, `pipeline_support.py`.

## Results

- `GREEN.txt`: complete adapter suite - Ran 665, OK, skipped=1 (`test_f04_a_link_is_refused`: no symlink privilege;
  real-symlink certification stays OPEN, see R1).
- `FROZEN.txt` / `FROZEN_COMPARE.txt`: frozen V0.4 suite - Ran 493, OK, skipped=1 - IDENTICAL to the recorded baseline.
- `TREES.txt`, `GUARDS.txt`: the six tree SHAs at HEAD, no frozen path changed or dirty, freeze and module-provenance
  guards PASS. `COMPILE.txt`, `DIFFCHECK.txt`: clean.
- `MUTATION.txt`: 34 distinct mutants over 7 files (`acquisition.py` 24, `pipeline.py` 4, `raw_capture.py`,
  `derivation.py`, `quota_gate.py`, `capability.py` 1 each, `cli.py` 2): 33 KILLED, 1 SURVIVED. `clock faults not halted`
  survived the first run - no test exercised a CLOCK_FAULT halt raised during the exchange - so
  `test_ha04_a_clock_fault_during_the_exchange_halts_and_converges_after_a_crash` was added and the mutant re-run:
  KILLED. `verify accepts a scope not pinned before the send` survives and is equivalent on every reachable state
  (the adapter always takes the document's scope from its sent row); reported, not counted.
- Test tidy-up carried here (disclosed): unused imports removed from `test_v05_r2_transport_boundary.py` (`ast`) and
  `test_v05_r3_runner_state.py`; the retry tests use `pipeline_support.odds_item(purpose=..., not_after=...)`.
