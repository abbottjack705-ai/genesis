# R7 Windows certification: OPEN

This file records what the current Windows run proves and what remains for a fresh, complete W1-W15 certification. It is not a certification. The host was Windows 11-10.0.26200-SP0 with CPython 3.12.10. The complete 917-test adapter suite passed; the two expected skips were the real symbolic-link credential test (the account lacks the required privilege) and the POSIX mode test. Frozen V0.4, replay, provenance, targeted R7, compileall, and integrity checks also passed. See the adjacent raw transcripts.

Windows-specific items still open include:

1. Real NTFS symbolic-link and junction credential-path tests under an account with the necessary privilege, including links into the repository/runtime root and an allowed external folder.
2. Owner-only credential ACL cases for inherited, Users-readable, and Administrators ACLs, with the actual deployment identity and localized account names.
3. `STATUS_CONTROL_C_EXIT` (`0xC000013A`) for an uncaught `KeyboardInterrupt` in the launched process.
4. Forced process termination while holding `run.lock`, followed by successful lock acquisition by the next process.
5. LF-checkout assertion in the deployment checkout with `core.autocrlf=false`.
6. Coarse-clock/deadline soak and measured slow-drip deadline overshoot on the supported deployment Windows/Python build.
7. Windows trust-store behavior under lower/mixed-case environment spellings, restoration/non-mutation checks, and the production trust-store integration boundary.
8. Windows behavior for the throwaway PKI, loopback HTTPS, TLS key-file cleanup, resolver deadline, credential grammar, and path-specific `lstat` tests on the deployment image.
9. A complete W1-W15 run against the final code/tests commit with transcripts and hashes, followed by review of the remaining INFO/platform findings.

The current full suite is Windows evidence, but does not cover every item above and therefore does not change the certification status. The real symlink case and owner ACL verification remain particularly important. Do not report Windows certification as passed until the complete checklist is independently executed against the final candidate.
