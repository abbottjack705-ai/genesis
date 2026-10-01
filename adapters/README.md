# adapters/ — Genesis V0.5 slice-1 (OddsPapi, read-only, fixture/offline)

Authority: `V05_ADAPTER_ARCHITECTURE.md` (revision r3) at the repository root. That document
is binding; this directory implements its Stages S0–S7 against deterministic fixtures.

**Nothing here contacts the network, stores a credential, or records an approval.** The
gates G0, G1, G2, G2R and G3 (design section 16) are human actions and are not performed by
any code or test in this tree. Successful ingestion, even at READY, does not authorize PAPER
qualification, strategy readiness or live execution.

## Layout

| Path | Contents |
| --- | --- |
| `src/genesis_adapters/` | production package (sits beside, never inside, the frozen `src/genesis`) |
| `adapter_tests/` | test package (`FixedClock`, `FakeTransport` and other test doubles live only here) |
| `config/` | pinned adapter configuration, policy, maps, closed schemas, frozen-module manifest |
| `evidence/S0 … S7/` | RED/GREEN transcripts, hashes and the final `S7/SUMMARY.md` |
| `DECISIONS/` | reserved for human approval records — **empty on purpose** |

The six frozen trees (`src`, `tests`, `config`, `tools`, `DECISIONS`, `v04_pack`) are never
edited; their tree SHAs must be unchanged at every commit (see "Freeze check").

## Run commands (from the repository root)

The runtime module-provenance guard (design section 2.4) requires isolated bytecode, so the
adapter suite must run with `-B` and a fresh `PYTHONPYCACHEPREFIX`:

```text
# bash
PYTHONPYCACHEPREFIX="$(mktemp -d)" python -B -m unittest discover -s adapters/adapter_tests -t adapters -v

# PowerShell
$env:PYTHONPYCACHEPREFIX = (New-Item -ItemType Directory -Path (Join-Path $env:TEMP ([guid]::NewGuid()))).FullName
python -B -m unittest discover -s adapters/adapter_tests -t adapters -v
```

Expected: every test passes. Where the account cannot create symbolic links (the Windows default), one
credential test is skipped; another test covers the same branch by simulating what `os.lstat` reports. Tests
that need the real UTC clock (TX-01, the loopback CLI run, the live-gate tests) skip inside the day-boundary
guard zone (23:57–00:02 UTC with the pinned policy). An audit hook installed by `adapter_tests/__init__.py`
refuses every network contact except the loopback interface, and the last test asserts that no test attempted
one (the hook's own self-test clears the two refusals it provokes on purpose).

Frozen suite (unchanged command, unchanged meaning; ~10 minutes):

```text
python -m unittest discover -s tests -t . -v
```

Static checks:

```text
python -m compileall -q src tests adapters/src adapters/adapter_tests
git diff --check
```

## Checkout requirement: LF line endings

The runtime module-provenance guard (FRZ-09) compares the **bytes** of every loaded
`genesis.*` module with the frozen Git blob. A checkout that converts line endings (Git for
Windows with `core.autocrlf=true` turns `src/genesis/*.py` into CRLF) therefore fails closed with
`MODULE_HASH_MISMATCH`. This is by design: the guard must not normalize what it verifies, and the
frozen `src/` tree cannot carry an `.gitattributes` rule (that would change a frozen tree SHA).
Clone or configure with LF for the frozen sources:

```text
git clone -c core.autocrlf=false <url>          # or: git config core.autocrlf false  (then re-checkout)
```

Adapter fixtures and pinned config are protected on every checkout by `adapters/.gitattributes`
(`-text`), so only the frozen `src/` needs this setting.

## Freeze check

```text
for t in src tests config tools DECISIONS v04_pack; do git rev-parse HEAD:$t; done
git diff --name-status v0.4-foundation-freeze HEAD -- src tests config tools DECISIONS v04_pack   # must print nothing
```

Expected tree SHAs: `src 51cb635b…`, `tests e90b2981…`, `config abd22db0…`, `tools a0e3411e…`,
`DECISIONS cc97ec6f…`, `v04_pack 3c3c1c27…` (full values in `V05_ADAPTER_ARCHITECTURE.md` section 2.1).

Line endings: `adapters/.gitattributes` stores `adapter_tests/fixtures/**` and `config/**` without
end-of-line conversion so pinned digests hold on every checkout.

## Package map (`src/genesis_adapters`)

| Module | Role |
| --- | --- |
| `provenance_guard.py` | runtime module-provenance guard (FRZ-09) |
| `ids.py`, `jsonstrict.py`, `schema.py`, `clock.py`, `secrets.py`, `config.py`, `errors.py` | primitives: identities, strict JSON, closed schemas, trusted clock, `Secret` and the secret detector, pinned configuration and `derivation_version`, failure taxonomy |
| `credential.py` | the credential file loader (design 7.5; only after G1) |
| `cli.py` | operator command line (the only writer of gate records, READY rows and halt resets) |
| `oddspapi/endpoints.py` | endpoint specs and canonical requests (no credential ever) |
| `oddspapi/quota_gate.py`, `acquisition.py`, `transport.py`, `boundability.py` | frozen quota ledger use, acquisition ledger and runner, boundary guard, retries, crash reconciliation |
| `oddspapi/raw_capture.py` | pre-persistence secret scan, bounded decoding, quarantine, raw evidence |
| `oddspapi/maps.py`, `identity_registry.py`, `parser.py`, `normalize.py` | pure parsing and `MarketBookDocument` normalization |
| `oddspapi/emit.py`, `invalidation.py`, `scope.py`, `capability.py`, `reader.py` | emission, invalidation, expected scope, capability downgrades, the verifier-parity reader |
| `oddspapi/quiescence.py` | the run lock and the unfinished-work check (design 6.3) |
| `oddspapi/derivation.py`, `manifest.py`, `pipeline.py` | `verify_derivation`, manifest bodies, the end-to-end fixture pipeline |
| `oddspapi/scheduler.py`, `authority.py`, `transport_http.py` | window planning, gate checks, the dormant HTTPS transport |
| `oddspapi/verify.py` | freeze guard, runtime secret scan, frozen-transcript comparison |

## Operator command line (only after the human gates; never run by the implementing agent)

All commands run with isolated bytecode (the startup guard refuses otherwise, FRZ-09) and with the
frozen `src` and `adapters/src` on the path:

```text
# bash (PowerShell: set the same two variables with $env:... and use ';' in PYTHONPATH)
export PYTHONPATH="adapters/src:src" PYTHONPYCACHEPREFIX="$(mktemp -d)"
python -B -m genesis_adapters.cli plan   --fixtures F.json --month 2026-10 --as-of 2026-10-01T00:00:00.000000Z --used 0
python -B -m genesis_adapters.cli report --root <runtime root>     # Genesis debit vs provider-reported usage
python -B -m genesis_adapters.cli verify --root <runtime root>     # verify_derivation for 100% of documents
python -B -m genesis_adapters.cli approve --root <runtime root> --record gate.json        # interactive, operator only
python -B -m genesis_adapters.cli approve-ready --root <runtime root> --derivation-version ... \
       --source-id ... --contract-id ... --cost-tier ...                                  # after a G3 record only
python -B -m genesis_adapters.cli reset --root <runtime root> --approval-reference adr:... --reason "..."
python -B -m genesis_adapters.cli run --root <runtime root> --plan plan.json --mode G2|G2R [--clock-check]
```

A plan is a JSON list of `{"role", "params", "window", "purpose", "attempt", "not_after"}` items. The runner
enforces the retry state machine of design 14.3 against the durable ledger before anything is recorded,
debited or sent (hostile audit HA-10): attempt `n > 1` must be a `RETRY` of attempt `n - 1` of the same request
and window, whose outcome was retryable (no response, or 5xx); at most `max_retries_per_window` retries, only
after `retry_min_backoff_seconds`, only before the item's `not_after` (required for a retry) and only with quota
headroom. A refused item stops the run (`refused: <window>: retry not permitted (<reason>)`, nothing written).
After a `CLOCK_SKEW` quarantine every send stays refused until the next UTC day **and** a clean `Date` check
(design 14.6 rule 5, HA-09): `run --clock-check` with a one-item plan sends that item as the probe (every gate
and the quota apply, and it is debited); only a present, in-bounds `Date` header on its response re-arms
ordinary sends, and an operator `reset` never does. Every content verdict is recorded in the attempt's
`completed` row, and its side effects (quarantine, suspension, halt, circuit, capability block, coverage,
metadata cache) are completed again, idempotently, after a crash before anything else runs (HA-04). The
expected scope of an ODDS request is fixed and pinned on its `sent` row before the send (design 12.4, HA-11).

One adapter phase runs at a time (design 6.3, HA-06): `run` holds the OS lock `<runtime root>/run.lock` for its
whole duration and refuses (`refused: another adapter phase holds the run lock`) while another process holds
it; the OS releases it when its holder exits or dies. A run first completes what an interrupted one left
durable - open attempts, verdict side effects, recorded but unapplied invalidations (HA-05) - and a resumed
emission reuses that response's durable T2/T3. While any such work is unfinished, or while the lock is held
elsewhere, every read refuses with `DATA_CAPABILITY_NOT_READY`. Every read re-derives the head it returns
(`verify_derivation`, HA-12); a head that no longer re-derives is refused and invalidated automatically
(`ADAPTER_AUTOMATIC`).

`run` refuses without: a G1 record whose credential fingerprint matches the loaded key; a G2 record
pinning the planned request hashes (G2 mode: raw capture only, at most `max_calls` sends inside its window)
or a G2R record pinning the running `derivation_version` and `policy_digest`; an OS time-sync attestation;
the frozen active quota policy; and the production clock. It always verifies TLS against the system trust
store and connects to the pinned host: there is no option to add a CA or redirect the connection (hostile
audit P:HA-006). `approve`, `approve-ready` and `reset` refuse without an interactive terminal,
the typed confirmation phrase and an `approval_reference` naming an out-of-band artifact (`adr:`,
`signed-tag:`, `pr-approval:` or an `https://` link). Gate bounds live in `config/oddspapi_gate_limits.json`.

Operator times are never chosen by the operator (design 16.2, 16.5; parallel audit P:HA-013): `approve` stamps a
gate record's `granted_at` with the trusted clock at approval (a record file naming a time more than
`clock_skew_max_seconds` away, or not a time at all, is refused), and `approve-ready` has no time option: it
checks the G3 record and records READY at the trusted clock's reading, never earlier than the source's latest
capability row. A capture made before that approval is therefore not usable at any cutoff before it. The first
`run --mode G2R` registers the running source `UNKNOWN` (design 16.4), anchoring its capability timeline.
`reset` clears a security halt only as the design prescribes (P:HA-014): a `SECRET_ECHO` halt only after a G1
record, granted after the halt, for a key no G1 named before it (a rotated key, design 7.6), and an
`AUTH_REJECTED` circuit only after a G1 record granted after it (design 14.3). Other halts reset as before; a
`CLOCK_SKEW` suspension never resets (see above).

## Credential storage, rotation and revocation (G1 prerequisite, design 7.5)

1. The key lives in ONE file named by `GENESIS_ODDSPAPI_CREDENTIAL_FILE`, outside this repository and
   outside the runtime root, holding exactly one line (the key), ended by a single LF or by nothing (a CRLF
   ending, as Windows text-mode writers produce, is refused as `CREDENTIAL_MISSING` rather than guessed at).
   POSIX: mode `0600`, owned by the runner user.
   Windows: an ACL that names only the runner user (`icacls <file> /inheritance:r /grant:r "<user>:F"`).
   No environment variable may hold the key itself; the runner refuses if one does.
2. The G1 record pins the key's fingerprint (`Secret.fingerprint`); a different key is refused.
3. **Rotate**: create the new key at the provider; replace the file's single line; a human records a new G1
   record with the new fingerprint; then revoke the old key at the provider.
4. **Revoke immediately** after any `SECRET_ECHO` (F-11) or `AUTH_REJECTED` (F-08): acquisition is already
   halted and every market-book capability is `BLOCKED`. Revoke the key at the provider, rotate as above,
   review `quarantine.jsonl` (secret-safe metadata only), and only then clear the halt with `reset`.
5. Before G3 and after every run: `verify` plus `verify.scan_runtime_for_secret(root, secret)` must be clean.

## Test-only material

`adapter_tests/fixtures/tls/` holds a throwaway loopback test CA certificate (`test-ca.pem`) and one server
certificate and key (`server.pem`, `server.key`) for the pinned host name; the CA's private key was destroyed
after signing, so no further certificate can be minted from it. They are trusted only by a client that injects
`test-ca.pem`, and only test code can do that: tests construct the transport with a test-CA context and a
loopback address themselves (`loopback_support.test_ca_context`, the TX-01 harness); no production module
references this material and the operator CLI has no CA or address option. The directory is `export-ignore`d
(`adapters/.gitattributes`), so it is never part of a source archive or release. It exists only so the dormant
HTTPS transport can be exercised against 127.0.0.1; the suite's audit hook refuses any non-loopback contact.

## Mutation smoke (optional, evidence in `evidence/S<n>/MUTATION.txt`)

The out-of-tree helper that produced those files applies one source mutation at a time, runs the named test
modules with `PYTHONPATH=adapters` and isolated bytecode, and restores the source in a `finally`. A mutation
counts as killed only if the baseline run (no mutation) passed first.
