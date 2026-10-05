# Windows certification test results

## Candidate and suites

All executable candidate checks used detached HEAD be898d3865685ac0261cdb255008db902b030521 and Python 3.12.10 on the ThinkPad. The first interactive suite transcripts were interrupted and are preserved as incomplete evidence; only the completed detached reruns below count.

| Run | Result | Baseline / interpretation | Transcript |
| --- | --- | --- | --- |
| Full adapter | 917 tests, 0 failures, 0 errors, 2 skips; OK; 1906.056 s | Independent R7 audit: 917, 0, 0, 2. One skip is real symlink privilege, missing W1 coverage. POSIX mode 0600 skip is Windows-inapplicable and W3 used NTFS ACLs instead. | evidence/W11_adapter_rerun.stderr.txt; evidence/W11_adapter_rerun.stdout.txt |
| Complete frozen V0.4 | 493 tests, 0 failures, 0 errors, 1 skip; OK; 1153.255 s | Approved S0 and independent R7 audit: 493, 0, 0, 1. Skip is real symlink privilege, not a W1 pass. | evidence/W11_frozen_rerun.stderr.txt; evidence/W11_frozen_baseline_compare.txt |
| FRZ-09 final provenance | 3 tests, 0 failures/errors/skips; OK | Loaded modules match frozen manifest, frozen worktree clean, non-loopback sentinel clear. | evidence/W12_provenance.txt |

Full suite command lines and bytecode isolation are in REPRO_COMMANDS.md. All staged candidate files match raw Git blobs. Two empty untracked suite runtime files were recorded and removed; evidence/W00_suite_runtime_cleanup.txt shows the cleanup. Final integrity evidence is in evidence/W00_integrity_final.txt.

## Direct W1-W15 probes

| Items | Measured result | Transcript |
| --- | --- | --- |
| W1/W2/W3/W8 | Real symlink creation failed WinError 1314; actual junction policy 3/3; real NTFS ACL cases 4/4; long credential 3/3, long runtime/evidence paths worked, long Git checkout failed | evidence/W01_W02_W03_W08_ntfs.txt; evidence/W08_long_runtime_evidence.txt; evidence/W08_long_repo_checkout.txt; evidence/W08_long_clone_checkout.txt |
| W4 | Holder acquired; concurrent contender refused; holder force-killed by taskkill /F; next contender acquired | evidence/W04_killed_lock.txt |
| W5 | w32tm status reported time.windows.com,0x9, recent sync and leap indicator 0 | evidence/W05_w32tm.txt |
| W6 | Genuine console CTRL_C_EVENT child exit 3221225786 = 0xC000013A | evidence/W06_real_ctrl_c.txt |
| W7/W10 | 18 real loopback socket stalls with coarse clock 1, 4, 16 ms; all NO_RESPONSE; largest measured overshoot 17.596 ms; full distributions in transcript | evidence/W07_W10_coarse_socket_soak.txt |
| W9 | Stock trust 47 CAs, hostile CA env case variants rejected, verify required, hostname true, keylog absent | evidence/W09_trust_case_variants.txt |
| W12 | Raw candidate checkout 756/756 blob matches, core.autocrlf=false, FRZ-09 pass | evidence/W12_raw_checkout.txt; evidence/W12_provenance.txt |
| W13 | Throwaway TLS server loaded, but temporary leaf.key inherited SYSTEM, Administrators and OWNER RIGHTS ACL entries; mode 0o666, owner-only false; key removed | evidence/W13_pki_acl_corrected.txt |
| W14 | 80 concurrent contexts / 16 workers, zero exceptions, stock 47/47 CA parity, verify/hostname true, keylog absent, env unchanged | evidence/W14_tls_concurrency.txt |
| W15 | Actual Windows randomized .invalid and single-label lookups measured; deadlines observed and no late sockets. Controlled 100-stall soak left 100 daemon workers alive 15 s, then all recovered on release; median 30.209 ms, max 35.846 ms for 20 ms deadline | evidence/W15_real_dns_and_100_soak.txt; evidence/W15_single_label_windows.txt; evidence/W15_dns_exhaustion.txt; evidence/W15_dns_shutdown.txt |

No real provider request or real credential was used. W1 and W8 remain OPEN; W11 remains OPEN because its relevant symlink skip lacks direct coverage. W13 is FAIL. Other W statuses and residuals are in WINDOWS_CHECKLIST.md.

