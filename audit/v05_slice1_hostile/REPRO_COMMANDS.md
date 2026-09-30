# REPRO_COMMANDS — exact reproduction per audit area

Every command below was run for this audit on the Windows host against a **fresh clone of the candidate**
(`cfcff3dbb285eaa48a6cfc1eceedb91e27662c81`, obtained from the local branch `v05-slice1-impl`, see
`TEST_RESULTS.md` §0) — **except** two that the host's memory pressure stopped: the candidate's adapter
suite completed only 411 of 573 tests in isolation, and `attacks/a15_mutation.py` was not run (both are
re-audit requirements; `TEST_RESULTS.md` §4, §A15). Run them on a host with no other suite running. Results are in `TEST_RESULTS.md`, raw outputs in `oracle_out_win_cfcff3d/` and
`attack_out/`. Nothing here trusts an implementer transcript, helper, count or scanner: the oracle
(`oracle/`) and the attacks (`attacks/`) are auditor-written. The attacks import only the candidate's
production package, the frozen `genesis` package, and the committed fixture *files* (re-hashed against
`FIXTURES.sha256` before use).

## 0. Setup (both platforms)

```bash
# 0.1 obtain the candidate (it is NOT on origin; see HA-000). From the host that holds the branch:
git -c core.autocrlf=false clone --no-hardlinks --no-checkout <path-or-url-holding-v05-slice1-impl> cand
git -C cand config core.autocrlf false
git -C cand checkout --detach cfcff3dbb285eaa48a6cfc1eceedb91e27662c81
git -C cand rev-parse HEAD            # must print cfcff3dbb285eaa48a6cfc1eceedb91e27662c81
git -C cand fsck --no-dangling        # must be silent
# 0.2 a second checkout with the machine default core.autocrlf=true (A-1 / CRLF attack)
git clone --no-hardlinks --no-checkout <same source> cand_crlf && git -C cand_crlf checkout --detach cfcff3d
# 0.3 the audit package
git clone -b ccr-c8695f69-sghhe5 https://github.com/abbottjack705-ai/genesis.git audit
cd audit/audit/v05_slice1_hostile
# Windows + Git Bash only: `python3` is the Store stub; put a shim first on PATH
mkdir -p ~/shim && printf '#!/bin/sh\nexec python "$@"\n' > ~/shim/python3 && chmod +x ~/shim/python3
export PATH=~/shim:$PATH
# every attack runs with -B and a fresh bytecode prefix (the candidate's guard requires both)
export PYTHONPYCACHEPREFIX="$(mktemp -d)"
```

## 1. Frozen foundation (area 1)

```bash
bash oracle/run_oracle.sh ../../../cand cfcff3dbb285eaa48a6cfc1eceedb91e27662c81 oracle_out_win_cfcff3d
#   01_frozen_identity: I-1..I-7 (tree SHAs, diff scope, no-touch list, LF blobs, nested .gitattributes, S0..S7 chain)
#   02_provenance_crlf: P-1..P-5 (P-3 = CRLF attack in a copy; P-4 = one-byte edit control)
#   frozen suite (unchanged command; Windows baseline 493 / skipped=1, Linux 493 / skipped=19 - HA-010)
#   adapter suite (-B, fresh PYTHONPYCACHEPREFIX)
python -B attacks/a01_manifest_crlf.py --repo ../../../cand --crlf-repo ../../../cand_crlf --out attack_out/a01.json
#   P-1 criterion on the candidate's real manifest layout ("entries", keys relative to src/),
#   manifest pin in verify.py, canonical bytes; the startup guard and the adapter suite inside the
#   autocrlf=true checkout must REFUSE (MODULE_HASH_MISMATCH), never normalize.
```

## 2. Request identity, quota, A-2 (area 2) and crash recovery, A-3 (area 3)

```bash
python -B attacks/a02_a03_crash_matrix.py --repo ../../../cand --out attack_out/a03.json
python oracle/oracle_quota_semantics.py --repo ../../../cand     # frozen facts Q-A..Q-H (QUOTA_SEMANTICS_OUTPUT.json)
```

Method: each case runs ONE fixture ODDS acquisition through the real runtime
(`pipeline.open_runtime`, real frozen stores, test quota policy `(250, 220, 30, 7)`, a configured
`Secret` so the secret screen runs), kills it at the checkpoint with a `BaseException` subclass
(`Crash`: no adapter handler may catch it, 7.7), opens a fresh runtime over the same root with a clock
60 s later than the last durable row, calls `resume()`, then re-acquires the very same plan item.
Checks in every case: the restarted runtime makes **zero sends and zero `QuotaGate.reserve` calls** for
the known attempt; at most one Genesis debit for the attempt and none added by the restart; the same
plan item comes back `DUPLICATE`/`REFUSED`; no `.pending` temp file is left by an in-process crash.

### A3 — the 16-checkpoint crash matrix

Frozen facts used (`oracle/QUOTA_SEMANTICS_OUTPUT.json`): **Q-A** the frozen ledger answers a
same-ID/identical-fingerprint request with the original `allowed` decision and writes no row (so the
adapter, not the ledger, must prevent a replay); **Q-B** same ID with a new `occurred_at` raises
`RegistryConflict`; **Q-C** time regression is a *blocked decision*, not an exception.

| # | Crash point (injection) | Durable state at the crash | Expected restart behaviour (authority) |
| --- | --- | --- | --- |
| C01 | before the quota ledger row (runner hook `before_quota`) | `acq_planned` only; no ledger row | nothing reserved, nothing sent: reconciled `NOT_RESERVED` / `NOT_SENT`; same plan item never re-requested; a new attempt may be planned (14.4, 11.1 "each step durable before the next") |
| C02 | after the quota ledger row, before `quota_decided` (hook `after_quota`) | ledger `quota_billable_call`; acquisition `planned` | debit stands, no refund (14.2); reconciled `ORPHANED_RESERVATION` / `NOT_SENT`; `request()` is **not** called again (Q-A would silently re-allow an identical fingerprint - HA-001; Q-B would halt on a new `Tq`) (14.4, F-35) |
| C03 | after `acq_quota_decided` (hook `after_quota_decided`) | + `quota_decided{Tq}` | as C02 |
| C04 | after `acq_sent`, before the transport (hook `after_sent`) | + `sent{T0}` | `ORPHANED_RESERVATION` / `MAY_HAVE_BEEN_SENT`; never re-sent under the same ID; retry only as `attempt+1` with a fresh `Tq` and a new debit (14.2 "Retry", 14.4) |
| C05 | transport: (a) dies before the response, (b) body received, result lost | as C04 | as C04 (a request that may have reached the provider is never resent automatically) |
| C06 | inside the secret screen (scanner raises) | as C04; nothing about the body persisted | as C04; no body byte, hash or derivative anywhere (7.6) |
| C07 | raw publish: (a) temp written, link not done (a hard kill also leaves a `*.pending` temp - planted), (b) object linked, observation not written | as C04 (+ a stray temp, or an orphan content-addressed object) | as C04; the stray temp and orphan object are inert (frozen `immutable_write` is idempotent for identical bytes); F-44 is the unclassified case (HA-007, `F44_ASSESSMENT.md`) |
| C08 | the `completed` row: (a) before it, (b) after it | (a) as C07b; (b) + `completed{T1, raw_observation_id}` | (a) as C04; (b) resume normalization deterministically, **new** `T2`/`T3` stamped at resume (14.4 bullet 2) |
| C09 | each normalized publish: after `T2` before the first, after the first, after the last | + some normalized observations | resume reuses each existing observation (exactly one under the contract) and publishes the rest; artifacts byte-identical to a no-crash run (11.4 last paragraph, PIT-08, EV-03) |
| C10 | after the first structured evidence | + one `ResearchEvidence` | idempotent (content-addressed; the digest pins the original observation) |
| C11 | each PIT append: after `T3` before the first, after the first, a middle one, the last | + some PIT records | never a second record for an artifact (record_id keyed on the artifact, 11.4); the already-appended records are **recognised and reused**, not re-appended, and must not halt (HA-011 - the candidate pins "reuse"); new records get the resume `T3` |
| C12 | after coverage | + coverage entries | exactly once per deterministic entry id |
| C13 | (a) after the `normalized` row, (b) after the identity rows | + `normalized{T2,T3,...}` (+ identity rows) | resume verifies completeness and (re)applies the identity rows last (8.3: the pinned prefix must stay a prefix) |
| C14 | invalidation: after the ledger row (`after_recorded`) | + `invalidation_recorded` | re-running the same invalidation completes it: no second recorded row (13.2 rows never duplicated) |
| C15 | invalidation: after the INVALIDATED document publish | + INVALIDATED observation | deterministic artifact reused; one PIT record |
| C16 | invalidation: after the invalidation PIT append | + INVALIDATED PIT record | recognised; one `invalidation_applied` row; head effect `INVALIDATED_HEAD_EMITTED` |

Common post-conditions for every "completed" case: the resumed history equals a no-crash baseline in
normalized artifact hashes, PIT `record_id`s and identity head; `verify_all()` re-derives every
normalized document; every PIT record has exactly one observation and `ready_at >= parse_ready_at >= T1`.
For every uncompleted case: no PIT record; `send_state = MAY_HAVE_BEEN_SENT` exactly when `acq_sent` was
durable; `attempt+1` is a new `request_id` with its own debit and exactly one send.

## 4/5. PIT head selection (A-4) and verifier parity (A-5)

```bash
python oracle/oracle_pit_head_expected.py --repo ../../../cand --out oracle_out_win_cfcff3d/EXPECTED_PIT_HEADS.json
python -B attacks/a04_a05_reader_parity.py --repo ../../../cand \
       --expected oracle_out_win_cfcff3d/EXPECTED_PIT_HEADS.json --out attack_out/a04.json
```

Each oracle scenario (S1 single, S2 tie, S3 invalidated tombstone, S4 newer-expires-first, S5
correction chain, S7 published-after-D, S8 two sources) is rebuilt in real frozen stores with the
oracle's exact times. At every oracle cutoff the attack (1) calls `reader.admissible_head`, (2) builds a
manifest pinning **each** record and runs the **frozen** `verify_for_pack` (auditor-built bodies, not the
candidate's builder), and (3) requires: reader usable ⇒ its record is the verifier's unique accepted
record; reader refusal while the verifier accepts ⇒ a documented adapter-only refusal (12.3 step 7,
deviation 8, 13.4). HA-002 is decided on S4 in `[valid_to_new, valid_to_old)`.

## 6. Secret safety (area 6)

```bash
python oracle/oracle_secret_corpus.py --repo ../../../cand --out oracle_out_win_cfcff3d/SECRET_CORPUS.json
python -B attacks/a06_secrets_pipeline.py --repo ../../../cand --corpus oracle_out_win_cfcff3d/SECRET_CORPUS.json \
       --out attack_out/a06.json
```

The pipeline attack echoes the configured key through the real runtime (body raw / UTF-16 BE / percent /
base64 offset 1 / hex / threshold fragment / non-allowlisted header value / header name / 5xx body /
gzip-decoded only / wire-only after a gzip member) and expects `SECRET_ECHO`: halt, no raw object,
metadata-only quarantine, capability `BLOCKED`, and **no §7.6 form of the key and no body hash in any
file under the runtime root** (auditor detector, independent of `secrets.py`). Unsupported / nested
encodings and a gzip bomb must be `UNINSPECTABLE_BODY` with no raw evidence. SEC-05 plants the corpus
as files and runs `verify.scan_runtime_for_secret`.

## 7. Transport and time boundary (area 7)

```bash
python oracle/oracle_boundary_guard_edges.py --out oracle_out_win_cfcff3d/EXPECTED_BOUNDARY_EDGES.json
python -B attacks/a07_transport_time.py --repo ../../../cand \
       --edges oracle_out_win_cfcff3d/EXPECTED_BOUNDARY_EDGES.json --out attack_out/a07.json
```

Checks: `boundary_guard` equals the oracle W1–W4 table at every edge (and reschedules to the first
permitted microsecond); an in-process TX-01 variant with an auditor fault-injecting connection
(ordinary `Exception` carrying the keyed URL in message/args/notes/cause/context/`url`/`filename` at
connect, write, read-head, read-body; a warning naming the URL; `KeyboardInterrupt(url)`,
`SystemExit(37)`, `SystemExit(url)`, `SystemExit(None)` - fresh instance `from None`, no keyed frame
local); BND-04 deadline; HA-008 stuck clock, 16 ms clock, stuck wall clock under `SystemUtcClock`, and
a transport reporting `T1 == T0` must halt the runner `CLOCK_FAULT`.

## 8. Schema and status fail-closed (area 8)

```bash
python -B attacks/a08_schema_status.py --repo ../../../cand --out attack_out/a08.json
```

One mutation per probe of the committed fixture on the pure parser: unknown / mistyped event status,
finished event with prices, outcome `active` false / `"true"` / null, null / 1.0 / string price on an
ACTIVE outcome, `bookmakerIsActive` false / 1 / missing, unknown keys at outcome / market / bookmaker /
event / envelope scope, `startTime` absent with no fixture join, a `+01:00` offset, a naive timestamp.
No probe may leave an affected book OPEN; the scope of the effect must match §10.1.

## 10. Immutability and corrections (area 10)

```bash
python -B attacks/a10_immutability.py --repo ../../../cand --out attack_out/a10.json
```

F-32 (conflicting bytes at the raw object path), F-33 (a PIT record id reused with other content),
EV-02 (tampered raw bytes fail `verify_all`), INV-04 automatic invalidation, PIT-06/INV-01 (as-of at
`T3_inv − 1 µs` unchanged, at `T3_inv` INVALIDATED), PIT-04/ST-05 (SUSPENDED blocks an older OPEN
inside and after its TTL), HA-012 (ABSENT tombstones with **no** READY capability), INV-02.

## 11. Windows-specific (credential loader)

```bash
python -B attacks/a11_windows_credential.py --repo ../../../cand --out attack_out/a11.json
```

Real ACLs via `icacls` (owner-only accepted; Everyone, BUILTIN\Users by SID, a DENY ACE, re-enabled
inheritance refused), CRLF line, two lines, second hard-link name, fingerprint mismatch, key in another
environment variable, file inside the runtime root, a directory junction resolving into the runtime
root, a real file symlink (needs `SeCreateSymbolicLinkPrivilege` / Developer Mode - reported NOT RUN
otherwise, never passed), and a table of synthetic localized `icacls` outputs through a patched
`subprocess.run` (HA-005). A privileged Windows run is still required for the symlink case (HA-004).

## 12. Test TLS private key (area 12)

```bash
python oracle/oracle_tls_key_check.py --repo ../../../cand --commit cfcff3d
python -B attacks/a12_tls_ca.py --repo ../../../cand --commit cfcff3d --out attack_out/a12.json
```

## 13. The 24 documented deviations

Read `adapters/evidence/S7/SUMMARY.md` §"Deviations and interpretations" at the candidate; each
classification and its evidence is in `DEVIATION_REVIEW.md`.

## 14. F-44

See `F44_ASSESSMENT.md`; exercised by crash-matrix cases C07a/C07b (the durable state an I/O failure
during raw publication leaves is the same as a crash at that point).

## 15. Mutation and test quality

```bash
python -B attacks/a15_mutation.py --repo ../../../cand --out attack_out/a15.json
python oracle/oracle_static_scan.py --repo ../../../cand --json oracle_out_win_cfcff3d/13_static_scan.json
```

18 auditor-chosen mutants of security-critical lines (duplicate-attempt guard, HA-002 refusal, W1 edge,
process-control re-raise, hard-link check, HA-011 comparison, UTF-16 BE form, header scan, published_at
parity, expected scope, gzip trailing data, CLI test-CA gate, G2 call budget, quota time regression,
provenance hashing, coarse-clock T1, `T_inv` tie, reconciliation `send_state`), each applied to a COPY
of the candidate tree and run against the candidate's own relevant test modules; each must be killed,
and the unmutated modules must pass first.

## New findings HA-013/HA-014 (operator times, reset) and HA-015 (gate limits)

```bash
python -B attacks/a13_ready_backdate.py --repo ../../../cand --out attack_out/a13.json
python -B attacks/a14_gate_limits.py --repo ../../../cand --out attack_out/a14.json
```

## Candidate adapter suite, isolated (must run alone on the host)

```bash
cd ../../../cand && PYTHONPYCACHEPREFIX="$(mktemp -d)" python -B -m unittest discover -s adapters/adapter_tests -t adapters -v
```
