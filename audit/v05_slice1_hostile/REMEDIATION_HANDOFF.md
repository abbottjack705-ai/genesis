# REMEDIATION_HANDOFF — minimal, implementation-ready items for the implementing model

Scope: the V0.5 slice-1 candidate `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` (branch `v05-slice1-impl`)
against the authority `c8dfafd` (`V05_ADAPTER_ARCHITECTURE.md` r3). Every item below names the finding in
`FINDINGS.csv`, the exact change, and the regression test that must be RED on `cfcff3d` and GREEN after.
The auditor implemented none of it.

Rules that still bind the implementer: never amend or rewrite `63e06a1 … cfcff3d` (add commits on top of
`cfcff3d`); never touch `src tests config tools DECISIONS v04_pack` or the authority; one commit per item
or per coherent group, prefix `v05(R<n>):`; RED/GREEN transcripts under `adapters/evidence/R<n>/`;
re-run the full adapter suite (`-B`, fresh `PYTHONPYCACHEPREFIX`) and the frozen suite (Windows 493 /
skipped=1) for the final remediation commit.

## 0. Procedural (human owner, not the implementer)

1. **HA-000 - make the candidate reachable.** `git -C C:\Users\abbot\fz\g push -u origin v05-slice1-impl`
   (after deciding the remote branch name). This audit obtained `cfcff3d` from the local branch and bound
   it by commit SHA, so the verdict does not depend on the push; a second auditor does.
2. **HA-004 - one privileged Windows run.** Enable Developer Mode (or run elevated) and run
   `python -B attacks/a11_windows_credential.py --repo <candidate>`; the "real file symbolic link" check
   must report `refused`. Attach the output under `adapters/evidence/`.
3. **G0 record.** `adapters/DECISIONS/` holds no ADR-A001 (c8dfafd §16.1, "G0 — architecture accepted
   (before Stage 0)"). Only the human owner may write it; the implementer correctly did not.

## 1. Certification-blocking items

### R1 - HA-013 (MEDIUM): operator-chosen times on READY rows and gate records; no G2R UNKNOWN row

Authority: c8dfafd §16.5 (`SourceCapability(..., operational_status=READY, recorded_at=now, ...)`), §16.2
(`granted_at (trusted clock)`), §16.4 ("During G2R, market-book sources are registered with
operational_status = UNKNOWN"), §13.1/§13.2 (historical as-of never changes).

Change (all in `adapters/src/genesis_adapters/cli.py` and `oddspapi/`):
- `approve-ready`: drop the `--at` argument; read `now = SystemUtcClock(drift_max_ms=policy.wall_monotonic_drift_max_ms,
  floor=<latest capability recorded_at for the source>).now()`; check the G3 record at `now`; register the READY
  row with `recorded_at=now`.
- `approve`: stamp `granted_at` with the same trusted clock (refuse a record file that carries a
  `granted_at` more than `clock_skew_max_seconds` away from it, or overwrite it before `validate_record`).
- G2R start (`cmd_run --mode G2R`, before the first send): if the running `stores.source_id` has no
  capability row, register `UNKNOWN` through `capability.register_downgrade(..., status=UNKNOWN,
  at=clock.now(), reason="G2R_START")`, so the capability timeline is anchored and the frozen registry's
  monotonic `recorded_at` rule forbids any earlier READY row.

Regression test (new, `adapter_tests/test_v05_authority.py`): run `approve` with a record dated
`2000-01-01T00:00:00.000000Z` and `approve-ready`; assert the stored `granted_at` and the READY
`recorded_at` equal the trusted clock reading, and that `reader.admissible_head` at a cutoff between the
capture and the approval is `Unusable(DATA_CAPABILITY_NOT_READY)`. `attacks/a13_ready_backdate.py` must
turn from 3 FAIL to PASS.

### R2 - HA-006 (LOW, confirmed): the committed test key and the CA seam in the live CLI

Authority: c8dfafd §7.6 ("TLS verification uses the system trust store and is never disabled"), §19 S7
("a self-signed CA injected for tests"), OPERATIONS_RUNBOOK X4 / §16.2 (no credential in the repository).

Change:
- `adapters/.gitattributes`: add `adapter_tests/fixtures/tls/** export-ignore`.
- Remove `--connect` and `--ca-file` from the production `cli.py` parser. Move the loopback end-to-end run
  (deviation 20) behind a test-only entry point in `adapter_tests/` that calls `cmd_run`'s internals with
  an injected transport; `HttpsTransport` keeps its `ssl_context`/`connect_address` parameters for tests,
  but `cmd_run` must always build `HttpsTransport(..., ssl_context=None, connect_address=None)`.
- Prefer generating the loopback key/cert at test time (`ssl`/`cryptography` are not required: a key and
  self-signed cert can be generated once per test run with `openssl` if present, or the fixture can keep a
  committed cert whose SAN is `localhost`, not the real provider host). If a committed key stays, add a
  scanner allowlist entry (`.gitleaks.toml` / `.secrets.baseline`) citing its test-only purpose.

Regression tests: `test_v05_cli`: `_parser().parse_args(["run", ..., "--ca-file", "x"])` exits with a usage
error; a static test asserts `cmd_run` passes no CA and no connect address; `git check-attr export-ignore`
is `set` for `server.key`. `attacks/a12_tls_ca.py` K2/K3 must PASS.

## 2. Non-blocking hardening (recommended before G1)

### R3 - HA-014 (LOW): `reset` clears SECRET_ECHO / AUTH_REJECTED without a re-G1

Authority: §7.6 ("For SECRET_ECHO … a human must rotate the key (re-G1)"), §14.3 (401/403: "A human must
re-approve (G1 re-check)"). Change: `cmd_reset` refuses when the latest `acq_halted` / `acq_circuit_opened`
reason is `SECRET_ECHO` or `AUTH_REJECTED` unless the authority ledger holds a G1 record granted after that
row whose `credential_fingerprint` differs from the fingerprint recorded for the halted run (record the
running fingerprint in `runs.jsonl` at start). Test: halt `SECRET_ECHO` → `reset` refused; add a newer G1
with a new fingerprint → `reset` allowed. `attacks/a13_ready_backdate.py` last check must PASS.

### R4 - HA-015 (LOW): unpinned gate limits; G2R `plan_digest` unchecked

Change: pin the SHA-256 of `adapters/config/oddspapi_gate_limits.json` in code (as `verify.FROZEN_MANIFEST_SHA256`
pins the module manifest) and refuse to load a file that differs; optionally make `LiveGate` compare the
G2R record's `plan_digest` with the digest of the plan passed to `cmd_run --plan`. Tests: an edited limits
file is refused; a G2R run with a different plan is refused (if the optional part is taken).

### R5 - HA-005 residual (INFO): compare ACL principals by SID

The loader is fail-closed today (set equality of display names; any unknown or extra principal refuses,
verified on NTFS and with synthetic localized outputs by `a11`). Hardening: parse `icacls <file> /save
<tmp> /q` (SDDL) or `Get-Acl | Select -Expand Sddl` and compare SIDs with the process token's user SID, so
a non-English system cannot produce false refusals. Test: table of captured en-US / de-DE / fr-FR outputs.

### R6 - F-44 (INFO): additive `RAW_PUBLISH_FAILED` semantics

Authority revision, not a patch: see `F44_ASSESSMENT.md` §5. Needs a human-written ADR under
`adapters/DECISIONS/` first.

## 3. Items that need NO change (closed by this audit with evidence)

HA-001, HA-002, HA-003, HA-008, HA-009, HA-011, HA-012 - see `FINDINGS.csv` (status CLOSED) and
`TEST_RESULTS.md`. HA-010 is a platform fact. HA-007 is the F-44 assessment.

## 4. Re-audit

After R1 and R2 (and whatever of R3–R5 is taken), re-run on Windows from a fresh clone:
`bash oracle/run_oracle.sh <repo> <new HEAD> <out>` (update `--stages` in the runner for the new commits),
then every `attacks/a*.py` per `REPRO_COMMANDS.md`. Expected: every attack check PASS except the ones the
remaining open items name, the frozen suite 493 / skipped=1, and FRZ-03 clean. Run the candidate's full
adapter suite and `attacks/a15_mutation.py` **alone on the host** (no parallel audit sessions): this audit
could complete neither because the host ran out of memory (411/573 tests passed before the kill; the
mutation run did not start).
