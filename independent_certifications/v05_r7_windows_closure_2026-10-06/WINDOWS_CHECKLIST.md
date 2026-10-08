# R7 Windows closure checklist — 2026-10-06

Production `be898d3865685ac0261cdb255008db902b030521`; certification support `deec08ffc66c56d156bc09addf548c62166cea17`. Statuses below apply to this new attempt. Historical evidence remains at certification commit `68b1fbc5340a41605900df2c23da29ec4edf91fb`.

| Item | Status | Basis |
| --- | --- | --- |
| W1 real NTFS symlink credential refusal | OPEN | Current token lacks `SeCreateSymbolicLinkPrivilege`; unchanged probe returned WinError 1314. `W01_current_token.txt`, `W01_W08_credential_ntfs.txt`. Administrator script prepared. |
| W2 junction paths | PASS | Previous real NTFS junction evidence remains applicable to byte-identical production code; unchanged combined probe reran here. `W01_W08_credential_ntfs.txt`. |
| W3 credential ACLs | PASS | Previous inherited, Users, Administrators and owner-only NTFS cases remain applicable; unchanged combined probe reran here. `W01_W08_credential_ntfs.txt`. |
| W4 killed-process lock | PASS | Immutable prior certification evidence `evidence/W04_killed_lock.txt`; production code unchanged. |
| W5 time-sync attestation | OPEN | Fresh `w32tm /query /status` reports leap indicator 3 and stratum 0. Resync from this token was denied. `W05_current_w32tm_status.txt`; Administrator script prepared. Prior synchronized result remains historical only. |
| W6 actual Ctrl-C exit status | PASS | Immutable prior certification evidence `evidence/W06_real_ctrl_c.txt`; production code unchanged. |
| W7 coarse-clock soak | PASS | Immutable prior certification evidence `evidence/W07_W10_coarse_socket_soak.txt`; production code unchanged. |
| W8 long paths / supported deployment root | PASS with constraint | Exact pinned checkout works at the 50-character local root, raw/provenance match, long credentials and long runtime/evidence paths work. `W08_git_checkout.txt`, `W08_raw_checkout.txt`, `W08_short_path.txt`, `W08_path_tests.stderr.txt`, `W01_W08_credential_ntfs.txt`. Arbitrarily deep Git roots are unsupported. |
| W9 Windows production TLS trust | PASS | Immutable prior certification evidence `evidence/W09_trust_case_variants.txt`; production code unchanged. |
| W10 Windows socket timing | PASS | Immutable prior certification evidence `evidence/W07_W10_coarse_socket_soak.txt`; production code unchanged. |
| W11 complete suites and frozen compare | OPEN | Support adapter 919/0 failures/2 skips; frozen 493/0 failures/1 skip. Two real-link skips await privilege. `W11_pre_privilege_adapter.stderr.txt`, `W11_pre_privilege_frozen.stderr.txt`. |
| W12 LF checkout / provenance | PASS | New raw 756/756 check, clean worktrees, tree identity and FRZ-03/09/non-loopback sentinel 3/3. `W00_integrity.txt`, `W00_raw_candidate_final.txt`, `W08_path_tests.stderr.txt`. |
| W13 throwaway PKI ACL | PASS | Unchanged probe on real NTFS: owner-only true, TLS key loaded, cleanup true. `W13_pki_acl.txt`. |
| W14 TLS concurrency | PASS | Immutable prior certification evidence `evidence/W14_tls_concurrency.txt`; production TLS code unchanged. |
| W15 resolver deadline / RA7-001 | PASS | Immutable prior certification evidence `evidence/W15_real_dns_and_100_soak.txt`, `evidence/W15_dns_exhaustion.txt`, `evidence/W15_dns_shutdown.txt`; known LOW residual persists. |

Current overall result: **WINDOWS CERTIFICATION: OPEN** because W1 and W11 have not executed under a suitable token and W5 currently lacks a synchronized time attestation. No W1 or W11 PASS is inferred from their skipped runs.
