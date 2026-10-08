# Genesis V0.5 R7 Windows certification closure attempt

Date: 2026-10-06  
Current verdict: **WINDOWS CERTIFICATION: OPEN**

This is a new closure attempt. The earlier `cert/v05-r7-windows` result at `68b1fbc5340a41605900df2c23da29ec4edf91fb` remains an immutable historical FAIL. This report does not amend or reclassify that evidence.

## Identity and authority

- Production candidate: `be898d3865685ac0261cdb255008db902b030521`.
- Certification-support commit: `deec08ffc66c56d156bc09addf548c62166cea17`.
- Independent delta review: PASS, as reported with this closure request. The local delta inspection confirms that only `adapters/adapter_tests/tls_support.py` and `adapters/adapter_tests/test_v05_r6_tls_boundary.py` changed.
- The `src`, `tests`, `config`, `tools`, `DECISIONS`, `v04_pack`, and `adapters/src` Git trees match the production candidate exactly. The detached LF production checkout has 756/756 raw blob matches and a clean status; the support checkout is clean. See `W00_integrity.txt`, `W00_raw_candidate_final.txt`, and `W00_delta_scope.txt`.
- This attempt used synthetic credentials, local files, and loopback TLS only. It made no provider call and did not activate betting.

## Closure results

**W13 PASS.** The unchanged original `pki_acl.py` certification probe was run against `deec08...` on real NTFS. `leaf.key` existed with an ACL naming only `JACK\abbot:(F)`, `OWNER_ONLY_ACL True`; the temporary TLS server loaded its key, and the key was removed. Its Windows `st_mode` still prints `0o666`, which is not the NTFS access decision. See `W13_pki_acl.txt`. The prior WC7-001 failure is closed for this new support state, while remaining part of the historical certification.

**W8 PASS within an explicit deployment constraint.** The tested local repository root is `C:\Users\abbot\a8\v05_prep\genesis_r7_candidate_lf` (50 characters). Git successfully checked out the exact pinned commit there. Raw checkout verification matched 756/756 blobs; FRZ-03, FRZ-09, and the non-loopback sentinel passed. The unchanged NTFS credential probe handled 310–313 character credential cases with the expected allow/refuse results. A certification-only probe exercised a 290-character runtime path with the real adapter run lock and a 305-character evidence file, verified its SHA-256, reacquired the lock, and removed the temporary paths. Credential and provenance unit tests ran 18 tests with zero failures/errors; their only skip was W1's real symlink. See `W08_git_checkout.txt`, `W08_raw_checkout.txt`, `W08_short_path.txt`, `W01_W08_credential_ntfs.txt`, and `W08_path_tests.stderr.txt`.

The deployment constraint is: **“On Windows, Genesis must be checked out/deployed at a bounded short local repository path. Arbitrarily deep Git working-tree roots are unsupported.”** The previous checklist explicitly accepted a documented short-path constraint as the alternative to a deployment-representative long repository checkout. The V0.5 project authority does not require arbitrary-depth Git roots, and the user directed this supported-path resolution. The prior Git failure at approximately 280 characters remains an INFO deployment limitation; no candidate source change is justified.

**W1 OPEN.** The current medium-integrity token has no `SeCreateSymbolicLinkPrivilege`, and Administrators is deny-only. The unchanged probe again reported `os.symlink` WinError 1314. No junction or mock is counted as W1 evidence. See `W01_current_token.txt`, `W01_current_token_groups.txt`, and `W01_W08_credential_ntfs.txt`.

**W5 OPEN on the current host.** A fresh `w32tm /query /status` reports `Leap Indicator: 3 (not synchronized)`, stratum 0, and source `time.windows.com,0x9`. The earlier synchronized result remains historical evidence but cannot attest the host now. A normal `w32tm /resync` request from this medium-integrity token was denied. The Administrator session must resync if needed and record a healthy status. See `W05_current_w32tm_status.txt`.

**W11 OPEN pending W1.** The completed support-state adapter suite passed 919 tests with two skips: the real symlink test and the platform-inapplicable POSIX-mode test. The complete frozen V0.4 suite passed 493 tests with one real symlink skip. Counts and failures are otherwise clean. The 18 targeted short-path tests also passed with the real symlink skip. These are not a W11 PASS until genuine link coverage executes in both complete suites. See `W11_pre_privilege_adapter.stderr.txt` and `W11_pre_privilege_frozen.stderr.txt`.

## W1/W5/W11 human-only session

An Administrator token is required to determine whether the local rights assignment supplies `SeCreateSymbolicLinkPrivilege` and to exercise a genuine NTFS link. This Codex process cannot approve its own Windows UAC prompt. Open PowerShell **as Administrator**, then run this single command:

```powershell
& 'C:\Users\abbot\OneDrive\Desktop\GENESIS_F1_8ae25e7_REMEDIATED\R7_W13_results\closure_2026-10-06\Run-R7-Admin-W1-W11.ps1'
```

The script checks both commit IDs and clean worktrees, records the elevated token, obtains a synchronized Windows time attestation (requesting a normal resync if necessary), runs the original W1 probe unchanged, requires a real created symlink and credential refusal, runs both targeted symlink tests, then reruns the complete adapter and frozen suites. It requires the adapter's only remaining skip to be the POSIX-mode test and the frozen suite to have no skip. It rechecks raw candidate bytes and clean worktrees. It stops without claiming PASS if the time source remains unsynchronized, the token lacks the symlink privilege, or any required observation fails. The script was parsed successfully but has not been run as Administrator.

## Residuals and decision

The prior W2–W4, W6–W7, W9–W10, W12, and W14–W15 PASS evidence remains applicable because production/frozen bytes are identical. W15 retains known LOW RA7-001 (daemon resolver workers accumulate during a persistent stall and recover after release); its protocol-specific Windows DNS Client/LLMNR/NetBIOS stall attribution remains a coverage limitation. W8 retains the INFO Git deep-root limitation and the explicit supported path constraint. The current W5 time-sync gap is an environment condition, not a new product defect. No new BLOCKER, HIGH, or MEDIUM product defect was found in this closure attempt.

Do not issue `WINDOWS CERTIFICATION: PASS` until the Administrator session records W1, W5, and W11 PASS. The previous FAIL remains unchanged; successful privileged evidence belongs to this new attempt.
