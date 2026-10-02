# Windows gaps and platform separation

Audit host: Linux 6.18 (Firecracker VM), CPython 3.11.15, `/tmp` on ext4-like local disk, 4 vCPU. The implementer's
evidence was produced on Windows 11 / CPython 3.12.10. **A Linux result is never treated as a Windows result.**

## REAL WINDOWS SYMLINK CERTIFICATION STILL OPEN

The only evidence for the real-symlink case on the implementing host is a *skip*: the account lacked
`SeCreateSymbolicLinkPrivilege` (`adapters/evidence/R1/SYMLINK_CHECK.txt`: `WinError 1314`). The recipe for running it
once in a qualifying environment is `adapters/evidence/R1/F04_REAL_SYMLINK_RECIPE.md`. This audit host is not Windows
and cannot create NTFS symbolic links, junctions, or reparse points. **This is not marked PASS.** It remains an
explicit certification condition and, on its own, does not imply that the rest of the audit fails.

## 1. PLATFORM-INDEPENDENT PASS (reproduced here, logic does not depend on the OS)

* Closed-schema parsing, identity, market/status maps, PIT/reader parity, invalidation, derivation re-verification
  (except the findings in `FINDINGS.csv`), quota gate, retry state machine, UTC boundary guard (21,200-point
  independent oracle, 0 mismatches), crash/restart matrices at every runner and emission checkpoint, deterministic
  replay (174 files byte-identical), secret scanning for the ASCII credential forms in §7.6, gate-limit digest pin,
  halt/reset authority, READY/approval time authority, frozen-tree identities, CRLF/byte provenance of frozen modules.
* Genuine POSIX symlink and hard-link refusal in the credential loader (`test_f04_a_link_is_refused` runs and passes
  on Linux; `test_f04_a_file_with_a_second_hard_link_name_is_refused` passes). This certifies POSIX semantics only.

## 2. WINDOWS-SPECIFIC — VERIFIED FROM REPO EVIDENCE ONLY (not reproduced here)

| Item | Where the claim lives | What I could do here |
| --- | --- | --- |
| Adapter suite `690 OK, 1 skip` | `adapters/evidence/FINAL/ADAPTER_SUITE.txt` | Read the transcript; **not** reproducible: on Linux the suite is `689 OK + 1 ERROR, 0 skips` (finding `RA5-013`) |
| Frozen suite `493 OK, 1 skip` | `adapters/evidence/FINAL/FROZEN.txt`, `V05_ADAPTER_ARCHITECTURE.md` §21 A11 | See `TEST_RESULTS.md` for the Linux run (A11 predicts a different skip set on Linux) |
| Owner-only ACL check of the credential file via `icacls` | `credential.py:36-52`, R2/S7 tests | Code path guarded by `sys.platform == "win32"`; **never executed here** |
| Junction handling (junction into repo / runtime root, junction to an allowed folder) | `test_v05_credential.UnprivilegedLinkAttackTests`, R1 `PROBES.txt` | Junctions do not exist on Linux; the Linux equivalent (symlinked directory component) is refused by the `resolve()` + `_inside` check, which is the same code path |
| `msvcrt.locking` run lock (`quiescence.py`) and its crash-release semantics | R4 tests | Linux uses `fcntl.flock`; semantics of `msvcrt.LK_NBLCK` on a 1-byte range and release-on-process-death **not exercised** |
| Time-sync attestation via `w32tm /query /status` | `cli.py:250-256` | Only the Linux branch (`timedatectl show -p NTPSynchronized`) exists in this host (binary present; not run in a live path) |
| `KeyboardInterrupt` uncaught exit status `0xC000013A` (`STATUS_CONTROL_C_EXIT`) | `test_v05_tx01.py`, `test_v05_cli.py` | Linux asserts `-2` (SIGINT); the Windows constant is **not** reproduced |
| Coarse wall clock (1–16 ms tick) and the T1-re-read loop `_reading_after` | `transport_http.py:116-132`, deviation 18 | Linux `time.get_clock_info("time").resolution` is 1e-9 s; the loop is exercised only through fake clocks. The **real** coarse-clock behaviour (including `time.sleep(tick)` granularity of ~15.6 ms and the frozen-clock bound) is **not reproduced** |
| Antivirus / sharing-violation `OSError` on evidence writes (F-44 trigger class) | n/a | Cannot be produced here; behaviour is characterised with an injected `ENOSPC` only |
| Path-length (`MAX_PATH`) limits for content-addressed evidence/object paths under a long `GENESIS_ADAPTER_ROOT` | not tested by the implementer or by me | Unknown on Windows |

## 3. WINDOWS-SPECIFIC — NOT REPRODUCED HERE

* NTFS symbolic links (open — see above), reparse-point/junction semantics, hard links on NTFS vs the `st_nlink == 1`
  check (Python 3.12 `os.stat` on Windows reports `st_nlink` correctly, but this was **not** verified here).
* Windows ACL inheritance / SID-name rendering differences in `icacls` output (the loader compares lower-cased
  `whoami` output with ACL principals; localized Windows, domain accounts, or `BUILTIN\Administrators` entries would
  change the comparison).
* CRLF on checkout: Git for Windows defaults to `core.autocrlf=true`, which converts `src/genesis/*.py` to CRLF and makes
  FRZ-09 refuse every adapter start (`MODULE_HASH_MISMATCH`). The guard failing closed is **verified here** with an
  independent CRLF-altered copy (`probes/p80_provenance.py`); the *operational* consequence (every default Windows
  checkout is unusable until `core.autocrlf=false` and re-checkout) is documented in `adapters/README.md` and was not
  exercised on Windows.

## 4. WINDOWS CERTIFICATION STILL REQUIRED

Before any live (G1/G2) use on Windows, a human-run certification on a qualifying Windows host must record, with
transcripts and hashes:

1. the real-symlink credential test (recipe in `adapters/evidence/R1/F04_REAL_SYMLINK_RECIPE.md`) — passes, not skips;
2. the adapter and frozen suites at the final remediated commit (the existing evidence is for `9f846d8` and will be
   stale once `RA5-001` is fixed);
3. TX-01 with the real `STATUS_CONTROL_C_EXIT` status;
4. a coarse-clock soak showing `T0 < T1` ordering and no spurious `CLOCK_FAULT` with the transport's re-read loop;
5. the owner-only-ACL check against a file with an inherited, a Users-readable, and an Administrators ACL;
6. a lock-release test: kill -9 a process holding `run.lock`, confirm the next process can acquire it;
7. an LF-checkout assertion run in the actual deployment checkout.

None of these is closed by this audit.
