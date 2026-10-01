# V0.5 slice-1 controlling hostile-audit remediation R2 - the credential and transport boundary

| | |
| --- | --- |
| Failed candidate (unchanged) | `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` |
| Base of this commit | R1 `875656e9328d1af2a95429457a0ac04eb9ccf6dc` |
| Architecture authority | `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe` (`V05_ADAPTER_ARCHITECTURE.md` r3) |
| Controlling audit | `C:\Users\abbot\a8\v05_prep\audit_oracle\hostile_audit_cfcff3d\` (manifest 10/10 OK before and after; never written to) |
| Findings | HA-01 (BLOCKER), HA-02 (BLOCKER), HA-03 (BLOCKER), HA-07 (BLOCKER), HA-08 (HIGH), HA-13 (LOW); parallel audit P:HA-006 (LOW) |
| Commit | the commit that adds this file, on `v05-slice1-impl` on top of R1 (not amended; not pushed) |

Everything is under `adapters/`; the six frozen trees are unchanged (`TREES.txt`, `GUARDS.txt`). No credential, no
provider or network contact, no gate record, no G2, no READY capability outside throwaway test registries.

## Method

1. `RED.txt` - the R2 tests (with their neighbouring cases) run against the **unmodified R1 production code**, in a
   separate git worktree at `875656e` with the current `adapter_tests` copied in: 65 tests, failures=65, errors=4
   (subtests counted). The tests that pass there are controls or properties R1 already had (listed below).
2. The production changes below, then `GREEN.txt` (complete adapter suite), `MUTATION.txt`, `FROZEN.txt` +
   `FROZEN_COMPARE.txt`, `COMPILE.txt`, `DIFFCHECK.txt`, `TREES.txt`, `GUARDS.txt`; `HASHES.sha256` covers them.

Tests passing on R1 in `RED.txt`, by design: `test_ha02_an_ordinary_error_in_close_changes_nothing_that_was_received`,
`test_ha03_a_slow_connect_and_tls_setup_that_reaches_the_deadline_prevents_the_write` (R1 already re-checked the
remaining time after `open`), `test_ha03_one_microsecond_before_the_deadline_the_request_is_written`,
`test_ha07_ascii_keys_and_clean_headers_are_unaffected`, `test_ha08_a_clean_oversize_identity_body_is_still_stored_truncated`
(controls); `test_ha01_through_the_acquisition_path_no_durable_file_carries_the_key` and
`test_ha01_the_record_is_scanned_again_exactly_as_it_will_be_persisted` (R1's persistence-point scan, kept through
the restructuring); `test_tx01_r2_an_ordinary_or_key_named_error_in_close_is_contained` (control); the R1 tests.

## Finding by finding

### HA-01 (BLOCKER) - an exception class name is untrusted text

- `oddspapi/transport.py`: `safe_label(name, max_chars, hit)` keeps a class name only if it is a plain ASCII
  identifier (`[A-Za-z_][A-Za-z0-9_]*`, no trailing newline), at most `header_value_max_chars` long and free of every
  section-7.6 form of the key; anything else becomes `REDACTED_EXCEPTION_CLASS`. `safe_errno(code, max_chars, hit)`
  keeps an `errno` only if it is an `int` whose decimal form is bounded and key-free (an `errno` can carry key
  digits, or be too large to serialize at all - `json.dumps` refuses ints beyond 4300 digits). `sanitize_exception`
  applies both shape rules at the source.
- `oddspapi/transport_http.py`: `HttpsTransport` builds the section-7.6 `SecretScanner` for its own key at
  construction and screens label and errno **before any `TransportResult` exists**; the integer errno keeps its
  meaning when only the label is tainted.
- `oddspapi/acquisition.py` `_scanned_error`: at persistence, shape rules first, then the whole record is scanned,
  then each field, then the record exactly as it will be persisted (nothing of it is kept if that still hits).
- Behaviour change against R1 (disclosed): R1 dropped the errno together with a tainted class; the errno is now
  kept unless its own digits carry a key form (HA-01: "preserve errno semantics"). `test_v05_r1_sanitized_error`
  was updated for exactly that expectation, and its spy test for the additional per-field scans.

### HA-02 (BLOCKER) - `close()` inside the process-control boundary

`send` is now an inner `try/except Exception/finally` (the `finally` closes the connection inside a nested
`try/finally` that clears the local) wrapped by the package's single outer `except BaseException` clause (FRZ-11: still
exactly one). A `KeyboardInterrupt`/`SystemExit` raised by `close()` - alone or after another one raised during the
exchange - leaves as a fresh instance: class and integer status kept, no text, cause, context, notes, and no
transport frame local carrying the key. An ordinary error in `close()` changes nothing that was received. TX-01 has a
new `close` fault stage (subprocess, end to end) for `KeyboardInterrupt`, the three `SystemExit` forms, an ordinary
error and a key-named class.

### HA-03 (BLOCKER) - no request byte at or after the hard deadline

T0 is read immediately before the first request byte (after connect, TLS and the socket timeout set-up) and the
write is refused if T0 is at or after `Tq + request_timeout_seconds`; the transport's `request_started_at` is that
reading. Tests: the audit's probe (the clock reaches the deadline inside `settimeout`) and a slow connect/TLS set-up
write nothing; one microsecond earlier writes once; T0 equals the reading at the write boundary.

Authority note (for human ratification, not a stop): design 6.2 defines T0 as "immediately before the first request
byte is written", while 11.1 orders `acquisition(sent, T0) -> transport (total)` and 14.6 rule 3 puts connect and
TLS inside the transport. The durable `acq_sent.T0` therefore stays the write-ahead reading taken just before the
transport is called (its presence is what proves "maybe sent", design 14.4); the transport's own T0 and the
deadline check are bound to the write boundary. Moving the durable row after TLS would need either a callback into
the runner inside the transport's single process-control clause (FRZ-11) or a two-phase transport, and would change
what the G2 `max_calls` counter (`acq_sent` rows) counts.

### HA-07 (BLOCKER) - header octets and every reversible decode form

`http.client` decodes header bytes as Latin-1, so a non-ASCII key echoed as UTF-8 octets is only visible after
re-encoding. `raw_capture.header_octet_forms` screens every header name and value (capture and quarantine metadata)
as UTF-8 **and** as the original wire octets. `secrets.reversible_views` adds the Latin-1 re-encoding of a durable
file's UTF-8 text and of its JSON-unescaped text to `verify.scan_runtime_for_secret`, so the durable sweep finds such
a form in any file. Tests: a non-ASCII key in `etag`, `last-modified`, `x-requests-used`, `date`, `content-type` and
in a header name is a SECRET_ECHO with nothing kept; through the runtime nothing reversible to the key is durable,
including the quarantine's `content_type`.

### HA-08 (HIGH) - every received byte is screened

The body scan covers the whole received wire (the cap + 1 probe byte included) before any retention decision, for
identity and content-encoded bodies; a fragment ending at every position 26 .. 33 around a 32-byte cap is caught.

### HA-13 (LOW) and P:HA-006 (LOW) - test TLS material and the production trust boundary

`cli.py run` lost `--connect` and `--ca-file` (and `_loopback`); it always builds
`HttpsTransport(secret, credential_param=..., policy=...)`, i.e. the system trust store and the pinned host.
`tls_context()` takes no CA. Tests construct the transport with a loopback test-CA context themselves
(`loopback_support.test_ca_context`, the TX-01 harness patches `HttpsTransport` in its own subprocess).
`adapters/.gitattributes` marks `adapter_tests/fixtures/tls/**` `export-ignore`, so the throwaway key (its CA key was
destroyed after signing) is in no source archive; no production module references the material (static test). The
README says so.

## Changed files

Production: `oddspapi/transport.py`, `oddspapi/transport_http.py`, `oddspapi/acquisition.py`, `oddspapi/raw_capture.py`,
`secrets.py`, `oddspapi/verify.py`, `cli.py`; `adapters/.gitattributes`, `adapters/README.md`.
Tests: new `test_v05_r2_transport_boundary.py`; changed `test_v05_tx01.py`, `test_v05_cli.py`, `test_v05_authority.py`,
`test_v05_transport_http.py`, `test_v05_r1_sanitized_error.py`, `loopback_support.py`.

## Notes

- Reproduction compatibility: the audit's HA-03 script passes `policy=SimpleNamespace(max_response_bytes,
  read_chunk_bytes, wall_monotonic_drift_max_ms)`. `HttpsTransport` now builds the section-7.6 scanner at
  construction and needs the real policy's `secret_fragment_min_chars_floor`, `secret_fragment_min_chars_divisor`
  and `header_value_max_chars`; a re-audit should pass the pinned policy (`genesis_adapters.config.load_policy`).
- Evidence hygiene: no file here holds a form of the public test sentinel or of the non-ASCII test key; the R2
  tests print only ASCII, key-free values in failure messages (an earlier RED capture that did print such forms was
  discarded, not redacted, and the tests fixed).
- `MUTATION.txt` explains the one aborted mutation run (the machine went to sleep on a critical-battery event).

## Results

- `GREEN.txt`: complete adapter suite - Ran 634, OK, skipped=6: `test_f04_a_link_is_refused` (no symlink privilege;
  real-symlink certification remains OPEN, see R1) and five `LiveGateTests` that use the real clock and skip
  themselves inside the UTC day-boundary guard zone - the run crossed 00:00 UTC. `GREEN_SUPPLEMENT.txt` re-runs
  that module outside the zone: 15 tests, OK, no skip.
- `FROZEN.txt` / `FROZEN_COMPARE.txt`: frozen V0.4 suite - Ran 493, OK, skipped=1 - IDENTICAL to the recorded baseline.
- `TREES.txt`, `GUARDS.txt`: the six tree SHAs at HEAD, no frozen path changed or dirty, freeze and module-provenance
  guards PASS (manifest sha256 `9a50e370...4fdf`). `COMPILE.txt`, `DIFFCHECK.txt`: clean.
- `MUTATION.txt`: 40 mutants over 7 files - all KILLED by their unit modules (transport 10/10, transport_http 10/10,
  acquisition 8/8, raw_capture 5/5, secrets 2/2, verify 1/1, cli 4/4); TX-01 additionally kills the 3 close-boundary
  mutants end to end.
