# T6 WIP checkpoint: F-3 risk-log integrity (NOT the T6 candidate)

This checkpoint repairs only finding F-3 of the independent T5 review (both
surfaces, F-3a and F-3b). F-1 and F-2 are not started. It is not the T6
candidate, carries no package and grants no authority: the foundation stays
HOLD for protected, shadow and live work.

## Base and scope

| Item | Value |
|---|---|
| Branch | `t6-remediation` |
| Base (F-4 checkpoint) | commit `c3d27d91cf9108dce3ddce084b11c532ce4ab99d`, tree `36d5945094cf6f53e465f05c6728dfcd766d88dc`, parent `6c2464e470fd5f82f53839492593a0c0ac1cd51f` (frozen T5) |
| Review report (read only) | `C:\Users\abbot\gv\out\GENESIS_V04_T5_INDEPENDENT_VERIFICATION_REPORT.md`, SHA-256 `edca08baa8d14d45d8e62cb33a415b6ab65295eabba48bbe27875386e7b22af8` |
| Auditor probes (read only) | `probe_owner_alias.py` `1e9501e6…`, `probe_hardlink_mirror.py` `bbcc6017…`, recorded T5 results `probe_owner_alias_t5.txt` `34e64b2e…`, `probe_hardlink_mirror_t5.txt` `96befea2…`; all equal the review's hash list |

T5 history, the F-4 checkpoint, every earlier `remediation_evidence/` file
(including the committed `F4_*` files) and all review evidence under
`C:\Users\abbot\gv` are unchanged. The checkpoint's own commit, tree and parent
cannot appear inside the commit; they are recorded after committing.

Changed paths relative to the F-4 checkpoint:

- `src/genesis/registry.py`: single-name rule and exact append (F-3b).
- `src/genesis/risk.py`: replay-checked risk-log storage; `RiskAuditLog.append`
  removed (F-3a).
- `src/genesis/owner_binding.py`: module docstring only.
- `tests/test_astra_t6_risk_log_integrity.py`: 12 new permanent tests.
- `tests/test_astra_s1_reservation.py`, `tests/test_astra_s2_replay.py`,
  `tests/test_astra_t1_dependence.py`: retained-test amendment (below).
- `remediation_evidence/T6/`: this record, three evidence scripts, transcripts
  and `F3_EVIDENCE_HASHES.sha256`.

## Invariant

No supported or externally reachable risk-log mutation path, and no filesystem
alias accepted as an independent authority, irreversibly mutates a risk log
unless the resulting durable log has first been shown to preserve replay
validity under the correct single-owner locking domain.

## F-3a: the public append surface

**Finding.** `RiskAuditLog.append(event_type, payload)` wrote any row without
the N3 replay check. A factual exposure reusing an approval ID then made every
later replay fail with `duplicate risk exposure identity`, permanently. The
underlying storage (`RiskAuditLog.log.append` / `.transaction`) was the same
unguarded path one attribute away.

**Repair (`risk.py`).**

- `RiskAuditLog.append` is removed. It had no caller, and a generic,
  domain-named event append would let a caller write risk events that no
  RiskEngine action admitted.
- `RiskAuditLog.log` is now `_RiskLogStorage`, an `AppendOnlyJsonl` whose
  `transaction` (and therefore `append`) appends a row only after the risk
  engine composed over it has replayed the exact resulting history, chain
  fields included, under the log's lock:
  - A RiskEngine action passes its own `_ReplayChecked` builder, which the
    storage accepts as is (no second replay). This is the unchanged N3 check.
  - Any other builder, such as a direct `append`, is wrapped in the same
    replay by the storage's engine.
  - With no engine the storage appends nothing.
- `RiskEngine` requires this storage and binds itself to it at construction;
  the first engine composed over a log object keeps the binding. An engine
  whose `audit_log` is later swapped for a new object therefore cannot write
  through the unbound new storage.

Every risk row therefore replays before it is written, whichever public path
wrote it. Semantic authorisation is still the RiskEngine actions' job: a
replay-valid row written directly through the storage object is a raw history
write, outside the same-user trust boundary as T5 documented for sidecar
deletion and byte edits.

## F-3b: filesystem aliases

**Finding.** Owner identity and the SQLite coordinator lock follow the path.
A hard link (no privilege on NTFS) gave a second path to the same bytes with its
own sidecars and its own lock. A mirror bound cleanly and approved, and an
append through the mirror inside the real log's critical section broke the
real chain permanently.

**Repair (`registry.py`, the single choke point for every append-only log).**
`AppendOnlyJsonl.transaction` appends a row only if, at write time:

- every read-lock participant is its file's single name;
- the target is its file's single name, is the same file (device and inode)
  that was read, and holds exactly the verified bytes.

"Single name" means no second hard link (`st_nlink == 1`), not a symlink, and
the name's final component resolves to itself. That last condition excludes
Windows 8.3 short names and symlinks. A target that was absent when read is
created exclusively (`O_CREAT | O_EXCL`); an existing one is opened without
creation. Read-only transactions are unaffected, so an aliased composition can
still be opened and read.

Consequences:

- While an alias exists, no write reaches the file through any of its names,
  including when the alias appears inside an open critical section. The
  original name is refused too: there is no durable way to tell which name is
  the original. That is a fail-closed, removable refusal; at T5 the same event
  was permanent chain corruption. Removing the alias restores the authority,
  and its history is untouched.
- A mirror with a fresh risk log over hard-linked bankroll and qualification
  owners (an H1 bypass through hard links, which was RED at the checkpoint)
  can no longer admit risk. Its approval's read-lock participants are aliased.
- Directory junctions, directory symlinks, equivalent paths (`..`, letter
  case) and relocated trees keep one canonical name and one lock, and work as
  before.

**Found during the enumeration, not in the review:** Windows 8.3 short names.
Short names are generated on this volume (`risk.jsonl` is also `RISK~1.JSO`).
A short name is a second name for one file with `st_nlink == 1`, so the first
version of the repair missed it. At that stage a short-name writer appended to
the real log under its own lock; the real writer's size check then refused its
own write, so the chain stayed intact in that sequential case. The final rule
refuses short names, and
`test_t6_short_name_alias_of_the_risk_log_is_refused` covers it (RED at the
checkpoint).

## Every risk-log write path (enumerated)

Static inventory, from `F3_WRITE_PATH_ENUMERATION.txt`:

- Five RiskEngine actions write the risk log, each through `_replay_checked`:
  `record_exposure`, `approve`, `consume_for_order`, `transition_reservation`
  and `release_with_proof`.
- Three read-only transactions (`attach_release_proofs`, `reserved_exposures`,
  `risk_ok`) use builders whose only return value is `None`.
- `execution.py` and `release_proof.py` use the risk log only as a read-lock
  participant or for reads.
- `_RiskLogStorage` is the only `AppendOnlyJsonl` subclass. `RiskAuditLog` is
  its only constructor.
- The only byte-level writer of any append-only log in `src/` is
  `AppendOnlyJsonl._append_exactly`. The other write primitives in `src/` are:
  - `repro.immutable_write`: content-addressed immutable evidence (temporary
    file, hard link, unlink of the temporary);
  - `logging.JsonlAuditLogger.emit`: the operational event log;
  - the research worker's IPC and devnull handles.

Dynamic trace: the complete test discovery (376 tests, 0 failures, 0
errors, 1 skip) was run with `AppendOnlyJsonl._append_exactly` instrumented.
Every one of the 447 write attempts that reached a risk log is classified by storage
class, by whether its engine replayed that exact chained row first, and by the
source entry point:

| Writes | Storage class | Replay | Outcome | Entry point |
|---|---|---|---|---|
| 188 | `_RiskLogStorage` | replay-checked | written | `approve` |
| 138 | `_RiskLogStorage` | replay-checked | written | `execution.bind_risk` (through risk) |
| 48 | `_RiskLogStorage` | replay-checked | written | `record_exposure` |
| 30 | `_RiskLogStorage` | replay-checked | written | `release_with_proof` |
| 12 | `_RiskLogStorage` | replay-checked | written | direct storage `transaction` (valid legacy rows planted by retained tests) |
| 7 | `_RiskLogStorage` | replay-checked | written | `transition_reservation` |
| 2 | `_RiskLogStorage` | replay-checked | written | `consume_for_order` |
| 1 | `_RiskLogStorage` | replay-checked | written | `execution.transition` |
| 5 | `_RiskLogStorage` | replay-checked | refused at write | aliases |
| 11 | raw `AppendOnlyJsonl` | none | written | the retained tests' explicit raw-history instruments |
| 5 | raw `AppendOnlyJsonl` | none | refused at write | aliases |

Writes through the risk-log storage that were not replay-checked: **0**.
Children started by multi-process tests are not instrumented, but they run the
same code.

A first instrumented run was discarded. The script then lacked a `__main__`
guard, so each test worker started with `spawn` re-ran the whole enumeration
(83 nested runs, 79 worker errors). The guarded script was re-run in a fresh
clean clone; that run produced the transcript above. Transcripts produced in
the work clone before this fix list the script's earlier hash
(`dbddeb0a…`) among the uncommitted paths; those runs did not execute it.

Outside the boundary (documented, not closed):

- A generic `AppendOnlyJsonl(<risk path>)` constructed by other code, and
  byte-level file edits, are raw history writes. They still cannot write
  through an alias.
- Calling the base-class `AppendOnlyJsonl.transaction` on the storage object,
  or assigning its private `_engine`, is deliberate circumvention of the
  storage guard.

## Evidence

All transcripts were written as UTF-8 with LF by their scripts, in short-path
`core.autocrlf=false` clones under `C:\Users\abbot\t6\`; no test ran in the
OneDrive repository.

- Environment: Windows 11 Pro 10.0.26200, CPython 3.12.10, Git 2.55.0.windows.3,
  8 CPUs.
- Source hashes: checkpoint `registry.py` `aee1863c…` and `risk.py` `fcec4408…`
  (equal to T5's); repaired `registry.py` `47c71926…` and `risk.py` `acc1b430…`.
- Transcript headers record every uncommitted path with its SHA-256.

### RED (F-4 checkpoint source)

**`F3_RED_AUDITOR_PROBES.txt`.** Both auditor probes were run unmodified, twice,
by `F3_AUDITOR_PROBES_DRIVER.py`:

- The runs are identical, and every key equals the review's recorded T5 value.
- F-3a: the colliding append is appended; replay and a later exposure fail
  with `duplicate risk exposure identity`.
- F-3b: `both appended (no mutual exclusion)`; the real log fails with
  `registry hash chain is broken`.
- The driver also runs a variant of `probe_owner_alias.py` that differs in
  exactly one block: the colliding append is wrapped so a refusal is recorded
  instead of stopping the probe. On RED it reproduces every key.

**`F3_RED_T6_TESTS_ON_F4_CHECKPOINT.txt`.** Ten of the 12 new tests fail for
the F-3 reasons (18 failures, 1 error); the two positive controls pass.

**`F3_RED_HARDLINK_STRESS.txt`.** Concurrent writers through the real name and
a toggled hard link: the real risk log was corrupted in 10 of 10 runs (broken
chain or garbled record).

### GREEN (repaired source)

**`F3_GREEN_AUDITOR_PROBES.txt`.**

- The unmodified `probe_owner_alias.py` now stops at its colliding append with
  `AttributeError` (the method no longer exists); its other keys are therefore
  printed by the one-block variant.
- In the variant, the same row offered to the storage is refused with
  `duplicate risk exposure identity`, and replay and the later exposure are
  `ok`.
- `probe_hardlink_mirror.py`:
  - the interleaved append is refused;
  - the real log `verifies` and `real_engine_after` is `ok`;
  - the mirror's and the real engine's approvals are refused while the alias
    exists.
- Unchanged: `junction_alias_approve` stays `[true, "risk_approved"]` and
  `hardlinked_bankroll_approve` stays `[false, "owner_authority_mismatch"]`.

**`F3_GREEN_HARDLINK_STRESS.txt`.**

- 0 of 10 runs corrupted, and no alias row ever reached the real log.
- The race was exercised: 3 to 11 real-name writes per run were refused while
  the link existed.
- The permanent concurrency test passed 10 of 10 repetitions.

**`F3_GREEN_RISK_SUITES.txt`.** 217 tests OK, 1 skipped. The set is the 12 F-3
tests plus every retained N2, N3, H1, O-5, risk, replay, release, concurrency,
restart, registry and execution suite.

**`F3_FULL_SUITE_AND_STATIC.txt`.** complete discovery in a fresh clone with the final
bytes and no concurrent load:

- **376 tests OK, 1 skipped**, 394.0 s. That is the F-4 checkpoint's 364 plus
  the 12 F-3 tests; the skip is the Windows symlink-privilege test H3.
- `compileall -q src tests tools remediation_evidence/T6` exits 0.
- `git diff --check c3d27d9` exits 0.

**`F3_STATIC_GATES.txt`.** `git diff --cached --check` over the complete staged
change set (excluding only itself and the hash list), the staged file list,
and an empty frozen-path diff for `DECISIONS`, `v04_pack`, `config`,
`V04_MIGRATION_PLAN.md`, `requirements.lock`, `pyproject.toml`, `tools`,
`src/genesis/protected.py` and every `remediation_evidence/` directory's
earlier files.

## Retained-test amendment (seven lines in three files)

Seven lines in three retained tests planted deliberately invalid risk history
(unsupported schemas, colliding identities, invalid transitions, late
consumptions, a forged row before any engine exists) through the risk log's own
storage object, as a raw-history instrument. That object now refuses exactly
such rows, which is the F-3a repair itself. Each line now plants the identical
row through `AppendOnlyJsonl(<same risk log path>)`. No row, fixture or
assertion changed.

| File | Lines |
|---|---|
| `test_astra_s1_reservation.py` | 1 |
| `test_astra_s2_replay.py` | 5, including one `transaction` injection |
| `test_astra_t1_dependence.py` | 1 |

Neutrality:

- **(a)** `F3_NEUTRALITY_A_AMENDED_TESTS_ON_F4_CHECKPOINT.txt`: on the
  unchanged checkpoint source, `type(RiskAuditLog(p).log) is AppendOnlyJsonl`
  is `True`, so the new instrument runs the identical code over the same path
  and writes identical bytes. The three amended files pass (22 tests OK).
- **(b)** `F3_NEUTRALITY_B_ORIGINAL_TESTS_ON_T6_SOURCE.txt`: the files exactly
  as committed at the checkpoint, on the repaired source, fail 11 times. Each
  failure starts at one of the seven seeding lines with the storage's refusal:
  `s1_reservation:160`; `s2_replay:64, 94 (x4), 131, 236 (x2)`; `t1_dependence:329`.
  The eleventh is the assertion after the refused injection at
  `s2_replay:179`.

The retained `record_exposure` and `approve` collision tests (T5 N3), the H4
"every risk append is replay-checked" test and the monkeypatched transaction
wrappers in the concurrency suites run unchanged and pass.

## Residuals and limits

- **File symlinks** cannot be created on this host (WinError 1314). The
  symlink branches of the single-name rule are reasoned, not executed. So is
  the retained H3 test (still skipped here): its adapter over a file-symlinked
  order log still constructs, because the constructor only reads and registers
  already-bound owners, and its later write is refused.
- **Other aliases not detected:**
  - Linux bind mounts (privileged), which give a second path with
    `st_nlink == 1`.
  - Network or SMB paths to a local file; these are not analysed.
- **Engine binding:** the first RiskEngine composed over a `RiskAuditLog`
  object validates writes made directly through that object.
- **Unchanged T5 residuals:** whole-deployment copies (forks) and first-composer
  trust.
- **Not in this checkpoint:**
  - F-1 and F-2.
  - Top-level documents (`HANDOFF.md`, `PROJECT_STATE.md`, `TEST_EVIDENCE.md`,
    `ARCHITECTURE.md`); update them at the T6 candidate.
  - Protected-set load reruns.
  - Any package or candidate.
  - An organisationally independent review.
