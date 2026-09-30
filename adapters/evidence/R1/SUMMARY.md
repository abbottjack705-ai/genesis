# V0.5 slice-1 hostile-audit remediation R1 (R-1 .. R-4)

> **Status of this commit (added 2026-09-30):** R1 remediates the FIRST hostile audit of `cfcff3d` (`audit_oracle/audit_cfcff3d`, findings F-01..F-04). A later, controlling audit (`audit_oracle/hostile_audit_cfcff3d`, HA-01..HA-14) and a parallel one (`ccr-c8695f69-sghhe5`, HA-000..HA-017) supersede and extend it; they are remediated by the commits that follow R1, with their own evidence directories. R1 is therefore an intermediate commit, not a certification candidate.

| | |
| --- | --- |
| Base (audited candidate) | `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` |
| Architecture authority | `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe` (`V05_ADAPTER_ARCHITECTURE.md` r3) |
| Audit package | `C:\Users\abbot\a8\v05_prep\audit_oracle\audit_cfcff3d\` - verified against its `ARTIFACT_MANIFEST.sha256` before and after this work (13/13 OK); never written to |
| Scope | exactly `REMEDIATION_HANDOFF.md` R-1 .. R-4 (findings F-01 .. F-04). Nothing else: F-05 .. F-13 are untouched, and F-44 / F-08 (`RAW_PUBLISH_FAILED`) is **not** implemented |
| Remediation commit | the commit that adds this file, on `v05-slice1-impl` directly on top of `cfcff3d` (not amended; not pushed) |

Everything is under `adapters/`. The six frozen trees are unchanged (`TREES.txt`, `GUARDS.txt`). No credential, no
provider or network contact, no gate record, no G2, no READY capability outside a throwaway test registry.

## Method (RED before the production change)

1. `REPRO_BEFORE.txt` - an independent reproduction script (`repro_findings.py`) run on the unmodified candidate:
   F-01 in all three places a sanitized error comes from, F-02 with a relaxed limits file, F-03 with one and with
   all requested tournaments omitted.
2. `RED.txt` - the R-1 .. R-4 tests run against the **unmodified** `cfcff3d` production code, before any production
   edit: 69 tests, failures=38, errors=7, skipped=1. R-1, R-2 and R-3 fail or error (the errors are the new
   context field and scan hook that do not exist yet); R-4 passes, because R-4 needs no production change - the
   defence exists, the tests add the real-OS coverage.
3. The production changes below, then `GREEN.txt` (complete adapter suite), `MUTATION.txt`, `FROZEN.txt` +
   `FROZEN_COMPARE.txt`, `COMPILE.txt`, `DIFFCHECK.txt`, `TREES.txt`, `GUARDS.txt`, `PROBES.txt`,
   `REPRO_AFTER.txt`, `SYMLINK_CHECK.txt` and `F04_REAL_SYMLINK_RECIPE.md`; `HASHES.sha256` covers all of them.

Evidence hygiene (disclosed): the first `RED.txt` and `REPRO_BEFORE.txt` printed forms of the fixed PUBLIC test
sentinel (`adapter_tests/support.py`, never a credential) in failure diffs and in the reproduction output. They
were replaced by `<SENTINEL-FORM>` with `redact_sentinel.py` (kept here; verified line by line with the
implementation's section-7.6 scanner; a note in each header states the count), so `adapters/` stays clean under
the auditor's secret sweep as the S0-S7 evidence is. The R-1 tests were then changed so their failure messages
never print such a form (message-only change; the R-1 mutants were re-run against the final test file).

## Finding by finding

### F-01 / R-1 - the sanitized transport error is scanned before it is persisted (design 7.6 item 3)

- Every non-empty `sanitized_error` reaches the ledger only through `AcquisitionRunner._finish_no_response`
  (`oddspapi/acquisition.py`): from `sanitize_exception` (a transport that raises), from a transport-reported
  error, and from the HTTPS transport's own boundary. It now first calls `_scanned_error`, which runs the capture's
  section-7.6 scanner over the canonical JSON of the whole record. On a hit the row is still written (the attempt
  happened) but the record becomes `{"class": "REDACTED_EXCEPTION_CLASS", "errno": null}`; the caller's `detail`
  is the placeholder too. With no key configured (fixture mode) the record is kept as sanitized.
- `oddspapi/transport.py`: the named constant `REDACTED_EXCEPTION_CLASS`. `oddspapi/raw_capture.py`: a public
  `RawCapture.hits_secret(data)` (the scanner the capture already holds).
- Tests: `test_v05_r1_sanitized_error.py` (six key forms - identifier, verbatim, lower case, hex, 16-char fragment,
  percent-encoded - through a raising transport, a reporting transport and the real HTTPS transport; clean records
  kept exactly; no scanning without a key; a spy proving the record is scanned before the `acq_completed` append)
  and TX-01's new `NAMED` case end to end in a subprocess (connect / write / read headers / decode).

### F-02 / R-2 - the architecture-fixed gate bounds cannot be changed through configuration (design 16.3/16.4)

- `oddspapi/authority.py`: `GATE_LIMITS_SHA256` pins the SHA-256 of `config/oddspapi_gate_limits.json`, exactly as
  `FROZEN_MANIFEST_SHA256` pins the module manifest; `load_gate_limits` refuses any other bytes before parsing.
  A relaxed, tightened or merely reformatted file is refused, so changing a bound needs a code change naming the
  new digest.
- Option (b) of the handoff, not (a): FRZ-10 (design 18) forbids numeric literal bounds anywhere in
  `genesis_adapters`, and the static scanner enforces it; the digest pin keeps the numbers out of code and still
  makes them unchangeable. The numbers themselves are pinned by a test with the design's own values (5, 72, 35).
- Tests (`test_v05_authority.GateLimitPinTests`): the shipped file holds exactly 5 / 72 h / 35 d; the pin is the
  shipped file's digest; nine altered files (+1 and far above each bound, a tighter value, the same values
  reformatted, a trailing space) are refused at load; the operator CLI refuses a config directory with relaxed
  limits in both `approve` (nothing written) and `run`.

### F-03 / R-3 - a missing requested tournament is an unproven omission, never an ABSENT tombstone (design 12.4, F-15)

- `oddspapi/parser.py`: `ParseContext.requested_competitions` (required) holds the request's competitions; a
  requested competition with no in-scope fixture in the payload makes the response partial. Only an exactly typed
  `int` tournament id (not `"8"`, `8.0` or `true`) of the pinned sport that maps to the competition counts as
  present. A partial response emits its well-formed books, records `PARTIAL_RESPONSE` (REJECTED /
  MISSING_EVIDENCE) and writes no tombstone at all (F-15).
- `oddspapi/derivation.py`: `odds_inputs` reads the requested set from the stored canonical request whose SHA-256
  is the acquisition's request hash, so normalization, `verify_derivation` and a rebuild read the same set
  (`oddspapi/pipeline.py` passes the request root at both call sites).
- `oddspapi/normalize.py`: `CODE_VERSION` `mb-normalize-1` -> `mb-normalize-2` - design 9.2: a change of code
  semantics creates a new `derivation_version` (and source). No derivation outside test scratch roots exists.
- A tournament whose fixture IS returned but carries no odds is a proven absence (its expected books become ABSENT);
  a tournament with no fixture at all cannot be told apart from an omitted one in the flat ODDS format, so it is
  treated as unproven.
- Tests (`test_v05_r1_requested_tournaments.py`, through the real runtime and at the pure parser): every requested
  tournament present with markets (proven absences kept); a requested tournament present with no odds (ABSENT);
  one of two omitted; all omitted; identical and contradictory duplicate blocks of the present tournament; a
  requested tournament present only as `"8"` / `8.0` / `true` / another sport / an unrequested id; a block missing
  its odds list; a request naming only the present tournament (complete); restart after a crash at every emission
  step of the partial response, resume, `verify_all` and a rebuild into empty stores - and in every case zero
  ABSENT documents and zero `BOOK_ABSENT` coverage entries from an unproven omission, with the omitted
  tournament's earlier OPEN heads still usable through the reader.

### F-04 / R-4 - real-OS link coverage without privilege; the genuine symlink case stays open

- No production change (`credential.py` is byte-identical to `cfcff3d`).
- `test_v05_credential.UnprivilegedLinkAttackTests`, ported from the auditor's probe but built in a stand-in
  repository in the scratch directory (the real worktree is never written): a junction resolving into the
  repository and one into the runtime root, and a hard link whose second name is inside the repository - all
  refused `CREDENTIAL_PERMISSIONS` - plus two controls that must load (a plain file, and a junction to an allowed
  folder), so a blanket refusal cannot pass.
- `MUTATION.txt` shows the gap they close: a loader that stops following junctions survives every S7-era credential
  test and is killed only by these tests.
- The real symbolic-link test (`test_f04_a_link_is_refused`) still **skips** here and is **not** reported as
  passing: this account lacks `SeCreateSymbolicLinkPrivilege`, Developer Mode is off and the session is not
  elevated (`SYMLINK_CHECK.txt`: `os.symlink` -> WinError 1314). `F04_REAL_SYMLINK_RECIPE.md` is the exact recipe
  to run it once in a qualifying Windows environment.

## Existing tests changed, and why

| Test | Change | Reason |
| --- | --- | --- |
| `test_v05_parser_schema` `test_an_empty_response_is_complete_and_tombstones_every_expected_book` | now `..._to_a_request_that_named_tournaments_is_partial_and_tombstones_nothing` | it asserted the F-03 defect itself |
| `parser_support.make_ctx` | passes `requested_competitions` (the base request: tournaments 17 and 8) | the context field is required |
| `emit_support.make_capture_ctx` | declares `HARNESS_REQUEST` = tournament 17 | the emission harness's `small_payload()` holds only tournament 17; four emission tests would otherwise model a two-tournament request answered with one |
| `test_v05_tx01` harness | a `NAMED` fault kind | R-1 end to end |

## Counts

| Suite | `cfcff3d` (S7) | R1 |
| --- | --- | --- |
| Adapter suite (`GREEN.txt`) | 573 OK (skipped=1) | **601 OK (skipped=1)**: +28 tests; the one skip is the real-symlink test |
| Frozen suite (`FROZEN.txt`, `FROZEN_COMPARE.txt`) | 493 OK (skipped=1) | **493 OK (skipped=1)**, IDENTICAL to the S0 baseline |
| RED (`RED.txt`: R-1..R-4 tests vs the unmodified production code) | - | 69 run: failures=38, errors=7, skipped=1 |
| Mutation (`MUTATION.txt`) | 57 / 56 killed / 1 equivalent | 16 / 16 killed (+ the R-1 re-run 6/6 and the R-4 differential) |
| Auditor probes (`PROBES.txt`) | as audited | credential links UNEXPECTED=0; detector PASS; boundary MISMATCHES=0; secret sweep unexpected=1 (the audited hex-alphabet false positive) expected=3; no-network VIOLATIONS=1 (the suite's deliberate self-test) |

New tests (28): `test_v05_r1_sanitized_error` 6, `test_v05_r1_requested_tournaments` 13 (9 runtime + 4 parser),
`test_v05_authority.GateLimitPinTests` 4, `test_v05_credential.UnprivilegedLinkAttackTests` 4, TX-01 `NAMED` 1.
One existing test was rewritten (the empty-response test above), so the count is 573 + 28 = 601.
Remaining skips: adapter suite 1 (`test_f04_a_link_is_refused`, no symlink privilege on this host); frozen suite 1
(its own pre-existing symlink test, unchanged since the S0 baseline).

## Deviations and decisions

1. R-2 uses the handoff's option (b), a digest pin, because option (a)'s literal constants would break FRZ-10.
2. R-3 bumps `CODE_VERSION` (design 9.2).
3. R-3 makes the whole response partial when any requested competition is missing (F-15; handoff R-3), so it also
   suppresses tombstones for the present tournaments of that response; they reappear on the next complete capture.
4. R-1 replaces the whole record on a hit and does not halt (handoff R-1).
5. R-4 runs its link attacks in a stand-in repository instead of the real worktree.
6. The first RED and REPRO transcripts were redacted for the public test sentinel (see "Evidence hygiene").
