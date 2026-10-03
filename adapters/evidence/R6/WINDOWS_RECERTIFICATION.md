# R6 - Windows certification: STILL OPEN, and what a fresh human run must record

**Nothing in this file is a certification.** The R6 candidate was built and validated on Linux 6.18 (Firecracker VM),
CPython 3.11.15. A Linux result is never a Windows result, and none of the items below was run on Windows. In
particular the **real NTFS symbolic-link / junction credential test is neither run nor passed** here: it stays OPEN
(audit finding RA5-018; `evidence/R1/F04_REAL_SYMLINK_RECIPE.md`).

The Windows evidence that exists in the repository (`evidence/FINAL/ADAPTER_SUITE.txt`, `FROZEN.txt`, 690 tests, one
skip) is for `9f846d8` / `b22263e` and is **stale** for this candidate: RA5-001..004 changed the transport, the strict
decoder, the pipeline, the ledger and the policy digest (a new `derivation_version`, by design), and R6 added 169
tests. It proves nothing about the R6 commit.

## What a qualifying Windows host must record against the R6 commit (with transcripts and hashes)

The seven items of the audit's `WINDOWS_GAPS.md` section 4, restated for this candidate:

1. **Real-symlink credential test passes (does not skip)** - create an NTFS symbolic link to a valid key file and run
   `adapter_tests.test_v05_credential` on an account holding `SeCreateSymbolicLinkPrivilege` (recipe in
   `evidence/R1/F04_REAL_SYMLINK_RECIPE.md`). Also run the **junction** case (a junction into the repository and into
   the runtime root, and a junction to an allowed folder): the loader must refuse each.
2. **Adapter and frozen suites at the final R6 commit** - `python -B -m unittest discover -s adapters/adapter_tests -t
   adapters -v` (expected: every test passes; at most the one symlink skip if the privilege is missing, which would then
   leave item 1 open) and `python -m unittest discover -s tests -t . -v` (frozen V0.4: 493 tests, count-identical to the
   S0 baseline via `verify.compare_frozen_transcripts`).
3. **TX-01 with the real `STATUS_CONTROL_C_EXIT`** (`0xC000013A`) for an uncaught `KeyboardInterrupt`.
4. **Coarse-clock soak** - `T0 < T1` ordering and no spurious `CLOCK_FAULT` through the transport's `_reading_after`
   loop on the real Windows wall clock (1-16 ms tick).
5. **Owner-only ACL check** of the credential file against an inherited ACL, a Users-readable ACL and an Administrators
   ACL (`icacls` rendering, domain/localized accounts).
6. **Lock release** - `kill -9`-equivalent (`taskkill /F`) of a process holding `run.lock`; the next process must acquire
   it (`msvcrt.locking` release-on-death).
7. **LF-checkout assertion** in the actual deployment checkout (`core.autocrlf=false`; FRZ-09 fails closed on CRLF).

## New for R6 (each is platform-sensitive code or a platform-sensitive test)

8. **Throwaway PKI and the loopback HTTPS tests on Windows** - `adapter_tests/tls_support.py` mints the CA and leaf in
   pure Python and hands them to OpenSSL through `cadata=` and one 0600 key file in a temporary directory.
   `test_v05_r6_tls_boundary.py` (including `PkiMinterTests`, which compares the minter with OpenSSL's own verdicts and
   subject-hash file names) and every loopback test (`test_v05_tx01`, `test_v05_transport_http`,
   `test_v05_r6_deadline`) must pass. The "owner-only key file" assertion is a POSIX-mode check; record how it behaves
   on NTFS (it is skipped or adapted, never silently passing).
9. **Production trust on the Windows certificate stores** - `transport_http.tls_context()` must still load the OS trust
   (`ssl.create_default_context()` reads the Windows stores) while ignoring `SSL_CERT_FILE`, `SSL_CERT_DIR` and
   `SSLKEYLOGFILE`. `os.environ` names are case-insensitive on Windows: confirm that a lower- or mixed-case spelling of
   each variable is hidden too, and that the variables are restored afterwards.
10. **The absolute deadline on Windows sockets** - `test_v05_r6_deadline` (slow-drip body and head, a handshake that never
    completes, the runner's late-response branches) uses real loopback sockets, threads and `time.monotonic()`. Windows
    `socket.settimeout` granularity and the monotonic clock's resolution (15.6 ms on older CPython) must not make a
    deadline test flaky or let a response outlive the deadline by more than the suite's slack. Record the observed
    overshoot of `send()` past the deadline for the slow-drip cases.
11. **Credential grammar and the lstat test** - `test_v05_credential` now patches `os.lstat` for the credential path only
    (RA5-013): confirm it passes on Windows (path normalisation of the compared path), and that the ASCII-only key
    grammar (RA5-007) accepts a real provider-style key written with CRLF-free line ending by the Windows tooling that
    will be used to create the file (a stray BOM or CR is refused by design).
12. **`CredentialModeTests` is POSIX-only** - it is skipped on Windows by `unittest.skipIf`; the Windows equivalent is item 5.

## Why R6 does not change the answer

No code in this candidate was exercised on Windows, the real-symlink case still cannot be created on the build host,
and the R6 transport/TLS/deadline changes are exactly the kind of code whose platform behaviour only a Windows run can
show. The honest status after R6 is therefore unchanged: **Windows certification OPEN**; everything above is the work
list for a fresh human certification against the new commit.
