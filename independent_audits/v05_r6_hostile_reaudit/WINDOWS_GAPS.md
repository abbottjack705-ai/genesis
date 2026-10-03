# Windows gaps (R6 re-audit)

## WINDOWS SYMLINK CERTIFICATION: OPEN

This audit ran on **Linux 6.18 (Firecracker VM, 4 vCPU), CPython 3.11.15 / 3.12.3 / 3.13.14, OpenSSL 3.0.13**. It is
**not** a Windows host and **no Windows-only check was run**. Nothing below is marked passed from Linux evidence.

The only Windows suite evidence in the repository (`adapters/evidence/FINAL/…`, 690 tests) is for `9f846d8`/`b22263e`
and is **stale** for the audited code commit `4ed66de4e2f3161464b9205583b3ee7a97133904` (R6 changed the transport, the
strict decoder, the ledger, the policy digest and added 169 tests). I agree with the implementer's
`adapters/evidence/R6/WINDOWS_RECERTIFICATION.md` that certification is OPEN and with its work list; I add the items in
section 3, which come from findings of this audit.

## 1. Not run here (each still OPEN, against `4ed66de`)

| # | Requirement | Status |
| --- | --- | --- |
| W1 | Real NTFS **symbolic link** to a valid key file refused by `CredentialSource` (test runs, does not skip; account with `SeCreateSymbolicLinkPrivilege`; recipe `adapters/evidence/R1/F04_REAL_SYMLINK_RECIPE.md`) | OPEN |
| W2 | **Junction** into the repository, into the runtime root, and to an allowed folder: each refused | OPEN |
| W3 | Owner-only **ACL** check (`icacls`): inherited ACL, Users-readable ACL, Administrators ACL, domain/localized accounts | OPEN |
| W4 | `msvcrt.locking` **lock release** after `taskkill /F` of a process holding `run.lock` | OPEN |
| W5 | `w32tm /query /status` time-sync attestation path (source ≠ `Local CMOS Clock`) | OPEN |
| W6 | TX-01 with the real **`STATUS_CONTROL_C_EXIT`** (`0xC000013A`) for an uncaught `KeyboardInterrupt` | OPEN |
| W7 | **Coarse-clock** soak: `T0 < T1`, no spurious `CLOCK_FAULT` through `_reading_after` on a 1–16 ms wall clock | OPEN |
| W8 | **MAX_PATH** / long-path behaviour of runtime roots, evidence and scope paths | OPEN |
| W9 | Production trust from the **Windows certificate stores** (`ssl.create_default_context()` on Windows also calls `set_default_verify_paths`, so `SSL_CERT_FILE`/`SSL_CERT_DIR` matter there too) while the three variables are hidden; Windows `os.environ` is case-insensitive | OPEN |
| W10 | **Windows socket timing** of the absolute deadline (`settimeout` granularity, `time.monotonic` resolution): measured overshoot of the slow-drip, slow-head and handshake-stall cases (Linux: ≤ 4 ms, `evidence/r01_deadline_*.txt`) | OPEN |
| W11 | Full adapter suite (859) and frozen V0.4 suite (493, FRZ-04 count comparison via `verify.compare_frozen_transcripts`) **at `4ed66de`** | OPEN |
| W12 | LF-only deployment checkout (`core.autocrlf=false`; FRZ-09 fails closed on CRLF) | OPEN |
| W13 | Throwaway-PKI loopback tests (`tls_support`, `PkiMinterTests`, owner-only key-file assertion adapted/skipped on NTFS, never silently passing) | OPEN |

## 2. What the Linux run does and does not show

* POSIX real-symlink refusal and hard-link refusal: **verified on Linux** (adapter suite, 859 OK, no skips). This says
  nothing about NTFS reparse points, junctions or ACLs.
* The frozen suite's 19 Linux skips are Windows-only tests (AppContainer/Job objects, N2 caseless owners,
  `os.startfile`, 8.3 short names); they ran nowhere in this audit.

## 3. Additional Windows items raised by this audit's findings

| # | From | What a Windows run must also record |
| --- | --- | --- |
| W14 | RA6-003 | `tls_context()` mutates `os.environ` (process-global). On Windows `os.environ` maps to the process environment block via `_wputenv`; repeat `probes/t02_tls_env_race.py` there (concurrent context construction must never trust an environment CA, never raise `KeyError`) — or, preferably, re-run it after the RA6-003 fix |
| W15 | RA6-004 | Name resolution on Windows (DNS Client service, `getaddrinfo` timeouts, LLMNR/NetBIOS fallback) is outside the absolute deadline: measure a stalled resolver against the deadline |

None of W1–W15 may be inferred from this Linux audit.
