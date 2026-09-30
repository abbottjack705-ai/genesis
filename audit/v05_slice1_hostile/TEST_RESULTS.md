# TEST_RESULTS — what actually ran in this audit

Two sessions contributed. **Session 1** (Linux, Python 3.11.15) could not reach the candidate and
verified only frozen facts (§L below, unchanged). **Session 2** (this continuation, 2026-09-29/30,
Windows 11, Python 3.12.10, Git Bash) obtained the candidate and executed the oracle and every attack.
Raw outputs: `oracle_out_win_cfcff3d/` and `attack_out/` (hashed in `ARTIFACT_MANIFEST.sha256`).

## 0. Obtaining the candidate (HA-000)

```
$ git ls-remote https://github.com/abbottjack705-ai/genesis.git | grep -c cfcff3d        -> 0
$ git fetch origin cfcff3dbb285eaa48a6cfc1eceedb91e27662c81
fatal: remote error: upload-pack: not our ref cfcff3dbb285eaa48a6cfc1eceedb91e27662c81
$ git -C C:\Users\abbot\fz\g rev-parse v05-slice1-impl                                 -> cfcff3dbb285eaa48a6cfc1eceedb91e27662c81
$ git -c core.autocrlf=false clone --no-hardlinks --no-checkout C:\Users\abbot\fz\g cand
$ git -C cand checkout --detach cfcff3dbb285eaa48a6cfc1eceedb91e27662c81 ; git -C cand fsck --no-dangling   (silent)
$ git clone --no-hardlinks --no-checkout C:\Users\abbot\fz\g cand_crlf   (core.autocrlf=true, machine default)
```

Still not on origin; reachable on the host that holds the branch. The object IDs bind the content, so the
audit is of exactly `cfcff3d` whatever the transport. `fz/g` itself was only read (clone), never checked
out or modified.

Chain (first parent from the authority): `c8dfafd → 63e06a1 (S0) → 1bc6001 → 78bedb9 → b95465e → 9de0790 →
ff7f4ba → 9c35c5c → cfcff3d (S7)`, all authored `Claude <noreply@anthropic.com>`.

**Environment contamination (disclosed).** A second agent session was auditing the same candidate on the
same host at the same time (`C:\Users\abbot\aud\`: its own LF/CRLF clones, frozen and adapter suites). Its
runs overlapped the first adapter-suite run of this audit and the host fell to 0.3 GB free RAM; see §4.

## 1. Oracle, area 1 (`oracle_out_win_cfcff3d/01_frozen_identity.*`, `02_provenance_crlf.*`)

| Check | Result |
| --- | --- |
| I-1 six tree SHAs at `cfcff3d` equal the freeze record | PASS (all six) |
| I-2 `git diff --name-status 2278e2a cfcff3d -- <six trees>` empty | PASS |
| I-3 every path changed since `c8dfafd` is under `adapters/` | PASS (185 files) |
| I-4 no-touch list untouched | PASS |
| I-5 no frozen blob stored CRLF/mixed | PASS |
| I-6 `adapters/.gitattributes` protects fixtures with `-text` | PASS |
| I-7 stage chain is exactly S0..S7 | PASS |
| P-1 manifest parity | **FAIL as written - oracle harness layout** (it looks for `modules`/top-level keys; the candidate uses `entries` keyed relative to `src/`). The identical criterion on the real layout: `attacks/a01_manifest_crlf.py` → **PASS** (36/36 entries, blob SHA-1 and SHA-256 equal, `src_tree = 51cb635…`, manifest SHA-256 `9a50e370…2fdf` equals the pin in `verify.py`, canonical LF bytes). The oracle file was not changed. |
| P-2 working-tree bytes of every frozen module equal the frozen blobs (LF clone) | PASS |
| P-3 clean copy control | PASS |
| P-3 CRLF copy refused (`ModuleProvenanceError`) | PASS |
| P-4 one-byte edit refused | PASS |
| P-5 no normalization tokens in `provenance_guard.py` | **FLAG - reviewed, not a defect**: the token hit is `splitlines` on a `git ls-tree` listing (`:69`) and on `.pth` file text (`:231`); module bytes are hashed from `read_bytes()` (`:216`). P-3 proves the dynamic property. |
| A-1 in the `core.autocrlf=true` checkout | the startup guard **REFUSES** (`MODULE_HASH_MISMATCH`), the adapter suite fails closed at package import (`a01`) - PASS |
| `git diff --check c8dfafd cfcff3d` | clean (exit 0) |
| `python -m compileall -q src tests adapters/src adapters/adapter_tests` | exit 0 |
| FRZ-03 `git status --porcelain -- <six trees>` after both suites | 0 lines (only ignored `__pycache__`) |

## 2. Frozen suite at `cfcff3d` (Windows, unchanged command)

```
$ python -m unittest discover -s tests -t .        (oracle run, nothing else of this audit running)
Ran 493 tests in 1414.154s
OK (skipped=1)
```

Equal to the Windows S0 baseline (493 / skipped=1). Linux baseline at `c8dfafd` is 493 / skipped=19 (§L2).

## 3. Oracle, other areas

| Oracle | Result |
| --- | --- |
| 04 PIT head table from the frozen store | regenerated on Windows; identical (LF-normalized SHA-256) to the committed Linux table |
| 07 boundary edges | pattern consistent over 6 boundaries; identical to the committed table |
| 09 quota semantics | Q-A..Q-H reproduce exactly on Windows (`09_quota_semantics.txt`) |
| 06 secret corpus against the candidate's `scan_for_secret` | **0 mismatches / 40 cases** |
| 12 TLS key | one unencrypted PKCS#8 key, test fixtures only; runtime references only `tls_context`/`ssl_context`; **no `export-ignore`**; certificate SAN `api.oddspapi.io` under the test CA |
| 13 static scan | X-01 (one `except BaseException`, in `transport_http.send`), X-02, X-03, X-04, X-06, X-07, X-08, X-12, X-14 PASS. **X-05 FLAG - reviewed**: four empty exception classes subclass the frozen `RegistryConflict` (`acquisition.py:186`, `identity_registry.py:36,40`, `invalidation.py:46`); no method is overridden, no authority class is subclassed (§2.1.3/FRZ-05 criterion met). **X-11 FLAG - reviewed**: no text-mode read is used for hashing (see P-5; `verify.py:57` counts `git status` lines). X-09/X-10/X-13/X-15 review items: bytes `.replace` in `secrets.py:107`; `str()` of header names/values and of a gate name; `__traceback__ = None` clearing - none persists exception text. |

## 4. Candidate adapter suite

- **Run 1 (oracle runner, contaminated):** `Ran 573 tests in 43740.433s — FAILED (errors=16, skipped=1)`.
  Wall time 12 h 9 min with the host at 0.3 GB free and a parallel session's frozen + adapter suites
  overlapping; the runner process itself was then reaped for low memory. Only the 3-line tail was kept.
  **Not used as evidence either way.**
- **Run 2 (re-run started 2026-09-30T08:50:03Z, verbose, `-B`, fresh prefix, nothing else of this audit
  running):** **410 ok, 1 skipped, 0 errors, 0 failures over the first 411 of 573 tests**, then the
  process was reaped by the host for critically low memory while it was inside
  `test_v05_pipeline.TombstoneTests` (the trailing `exit=1` in the transcript is the kill). A third-party
  frozen suite (another audit session, `C:\Users\abbot\a8\v05_prep\hostile_audit_lf`) had started at
  08:51:55Z. Full transcript: `oracle_out_win_cfcff3d/adapter_suite_rerun_full.txt`.
- **Status: NOT COMPLETED.** No test failed in any clean portion; the remaining 162 tests (the rest of
  `test_v05_pipeline` and the modules after it alphabetically: `test_v05_quota_gate`, `test_v05_raw_capture`,
  `test_v05_reader`, `test_v05_request`, `test_v05_scheduler`, `test_v05_schema`, `test_v05_secret_*`,
  `test_v05_secrets`, `test_v05_static`, `test_v05_transport_http`, `test_v05_tx01`,
  `test_v05_zz_final_provenance`) were not executed in an uncontaminated run. A complete isolated run is a
  re-audit requirement (HOSTILE_AUDIT_REPORT §4). Per the host's instruction it was not restarted
  automatically.

## A2/A3. Crash matrix and quota replay (`attack_out/a03.*`, `a03_c07_rerun.*`)

Full run: 199 checks, 197 PASS, 2 harness errors (a `:` in a Windows scratch-directory name, then an
over-broad `os.link` patch that crashed before the raw publish). Both fixed in the harness only; C07a/C07b
re-run: 19/19 PASS. Summary per checkpoint (numbering of `REPRO_COMMANDS.md` §A3):

| # | Result |
| --- | --- |
| C01 | 0 sends / 0 `reserve()` after restart; reconciled `NOT_RESERVED`, `NOT_SENT`; retry `attempt+1` sends once with its own debit |
| C02, C03 | `ORPHANED_RESERVATION`, `NOT_SENT`; ledger rows for the ID stay 1; no `reserve()` on restart (HA-001) |
| C04, C05a, C05b, C06, C07a, C07b, C08a | `ORPHANED_RESERVATION`, `MAY_HAVE_BEEN_SENT`; same plan item → `REFUSED/ORPHANED_RESERVATION`; no PIT record; no body byte stored (C06); planted stray `*.pending` tolerated (C07a) |
| C08b, C09a–c, C10, C11a, C12, C13a, C13b | resume → `NORMALIZED`; artifacts, record ids and identity head equal the no-crash baseline; `verify_all` = 12/12; one observation per PIT record; `ready_at ≥ parse_ready_at ≥ T1` |
| C11b, C11c (HA-011) | resume reuses the already-appended records, no halt, history equals the baseline; the response then carries **2 distinct `ready_at` values** and the `normalized` row's `T3` equals only the resumed ones (documented "reuse" behaviour; safe) |
| C11d | all 12 records carry the pre-crash `T3`; the `normalized` row carries the resume `T3` (diagnostic mismatch only) |
| C14, C15, C16 | re-running the invalidation completes it: exactly `invalidation_recorded` + `invalidation_applied`, one INVALIDATED PIT record, effect `INVALIDATED_HEAD_EMITTED` |
| QuotaGate replay | `reserve()` itself re-answers an identical fingerprint `allowed` with no new row (frozen Q-A); protection is the acquisition ledger, which C01–C08 prove holds |

## A4/A5. Reader parity (`attack_out/a04.json`, `a04.table.json`)

17/17 PASS over 7 scenarios and 135 cutoffs. 45 usable answers, every one independently accepted by the
**frozen** `verify_for_pack` (auditor-built manifests for every record at every cutoff); the verifier never
accepted more than one record. Stricter refusals only where documented: S4 `[valid_to_new, valid_to_old)`
- the verifier accepts the revived OLD record, the reader returns `STALE` (3 cutoffs; HA-002 closed); S8
two READY sources → `AMBIGUOUS_SOURCE` (§13.4). S7 head published after `D` → `NOT_PUBLISHED_AT_CUTOFF`,
no fallback.

## A6. Secret safety through the runtime (`attack_out/a06.json`)

16/16 PASS (after a harness fix: the frozen `OperationalStatus` serializes lowercase `"blocked"`). Eleven
echo shapes (raw, UTF-16 BE, percent, base64 offset 1, hex upper, threshold fragment, header value, header
name, 5xx body, gzip-decoded only, wire-only after a gzip member) → `SECRET_ECHO` halt, 0 raw objects, one
metadata-only quarantine row, capability `blocked`, **no §7.6 form and no body hash in any file under the
runtime root** (auditor detector). Unsupported, nested and bomb encodings → `UNINSPECTABLE_BODY`, no raw
object. SEC-05: `scan_runtime_for_secret` flags exactly the 36 expected corpus files.

## A7. Transport and time (`attack_out/a07.json`)

17/17 PASS: `boundary_guard` equals the oracle W1–W4 table at every edge of 6 boundaries and reschedules to
the first permitted microsecond; TX-01 (in-process) at connect/write/read-head/read-body → sanitized
`{class, errno}` only, warning swallowed; `KeyboardInterrupt(url)` → fresh `KeyboardInterrupt()`,
`SystemExit(37)` → 37, `SystemExit(url)` → 1, `SystemExit(None)` → `()`, all `from None` with no cause,
context, notes or keyed frame local; BND-04 (`T0 ≥ deadline` writes nothing; slow body cut `TRUNCATED`);
HA-008 (stuck clock returned as read within the budget; 16 ms clock gives `T1 > T0`; stuck wall clock →
`ClockFault WALL_CLOCK_JUMP`; a transport reporting `T1 == T0` halts the runner `CLOCK_FAULT` with no
RESPONSE row and no evidence).

## A8. Schema and status (`attack_out/a08.json`)

21/21 PASS. Unknown/mistyped event status → event BLOCKED; finished event with prices →
`CONTRADICTORY_STATUS`; outcome `false` → SUSPENDED, `"true"`/null → BLOCKED; null or 1.0 price on ACTIVE
→ `CONTRADICTORY_STATUS`; string price → `SCHEMA_DRIFT`; `bookmakerIsActive` false → SUSPENDED, `1` or
missing → BLOCKED; unknown key at outcome/market → that book, bookmaker block → event×bookmaker, event →
event, envelope → response REJECTED with zero books and tombstones; `startTime` absent without join →
`EVENT_METADATA_STALE`; `+01:00` → `EVENT_START_INVALID`; naive `changedAt` → `TIMESTAMP_NAIVE`. No probe
left an affected book OPEN.

## A10. Immutability and corrections (`attack_out/a10.json`)

8/8 PASS: F-32 (bytes untouched, halt), F-33 (row not replaced, halt), EV-02 (tampered raw fails
`verify_all`), INV-04 (automatic invalidation), PIT-06/INV-01 (usable at `T3_inv − 1 µs`, INVALIDATED at
`T3_inv`), PIT-04 (SUSPENDED blocks older OPEN inside and after its TTL), **HA-012** (4 ABSENT tombstones
with **0** capability rows), INV-02.

## A11. Windows credential loader (`attack_out/a11.json`)

19/20. Real NTFS ACLs: owner-only → loaded; Everyone, BUILTIN\Users (by SID), DENY ACE, re-enabled
inheritance → `CREDENTIAL_PERMISSIONS`; CRLF / two lines → `CREDENTIAL_MISSING`; second hard-link name,
key in another env var, file in the runtime root, junction resolving into the runtime root → refused;
wrong fingerprint → `CREDENTIAL_FINGERPRINT_MISMATCH`. Synthetic de-DE/fr-FR/SID/DENY/unknown/empty `icacls`
outputs → refused; only-the-user + localized summary line → loaded (HA-005 closed). **Real file symlink:
NOT RUN** — `os.symlink` → `OSError winerror=1314` (privilege not held) on this account (HA-004 open).

## A12. TLS key and CA seam (`attack_out/a12.json`)

2/4: K1 key matches the committed certificate, SAN `api.oddspapi.io`; **K2 FAIL** no `export-ignore`, the key
ships in `git archive`; **K3 FAIL** the production `run` parses `--ca-file`, wires `tls_context(args.ca_file)`
into `HttpsTransport`, which accepts a context trusting only the injected CA (1 CA); K4 non-loopback
`--connect` refused. HA-006 confirmed.

## A13. Operator-supplied times (new HA-013, HA-014) (`attack_out/a13.json`)

0/5 (each check states the design requirement): no `UNKNOWN` capability row after a G2R-style capture (0
rows); `approve` stored `granted_at = 2000-01-01T00:00:00.000000Z` from the record file; `approve-ready
--at 2000-01-01…` wrote the READY row with that `recorded_at`; the reader then returns `UsableBook` at a
cutoff (`12:00:01`) **before** the approval moment (`12:30:00`) — a retroactive READY; `reset` cleared a
`SECRET_ECHO` halt with no G1 record present.

## A14. Gate limits (new HA-015) (`attack_out/a14.json`)

0/1: in a copy of the config directory with `g2_window_hours=10000, g2_requests_cap=500`,
`authority.validate_record` accepts a G2 record pinning 50 requests over 1000 hours; the five pinned
config digests are unchanged (`config_digests_changed: false`).

## A15. Mutation - NOT RUN

`attacks/a15_mutation.py` (18 auditor mutants, each against the candidate's own relevant test modules on a
copy of the tree) was written but not executed: it runs a large part of the adapter suite repeatedly and
the host was at 0.3–0.9 GB free RAM with a parallel audit session running suites. It is a re-audit
requirement. The closures of HA-001/002/011/012 rest on this audit's own attacks (a03, a04, a10), not on
the candidate's tests; the mutants only measure whether the candidate's tests would catch a regression.

---

## L. Session 1 results (Linux, unchanged)

### L1. Frozen-tree identity at `2278e2a` and `c8dfafd`

Six tree SHAs identical to the freeze record at both commits; `git diff --stat 2278e2a c8dfafd` = one file
(`V05_ADAPTER_ARCHITECTURE.md`, +2526); no CRLF blob in the frozen trees; `oracle_frozen_identity.py` at
`c8dfafd`: I-1…I-5 PASS, I-6 FAIL for the right reason (predates S0).

### L2. Frozen suite at `c8dfafd` (Linux)

`Ran 493 tests in 105.856s — OK (skipped=19)`; the 19 skips are the Windows-only containment tests
(9 confinement primitives, 4 AppContainer, 3 caseless owner identities, 1 each 8.3 names, open-file
delete, `os.startfile`). Log: `frozen_suite_c8dfafd_linux.log`.

### L3. Oracle self-tests

Each detector was run against a synthetic defective adapter and a corrected one (static scan: every
planted defect reported; provenance oracle: text-mode guard caught as fail-open, byte-exact guard passes;
harness bug with `sys.exit` inside `try` found and fixed before shipping).
