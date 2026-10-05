# Genesis V0.5 R7 Windows certification report

WINDOWS CERTIFICATION: FAIL

R7 REMAINS SUITABLE FOR NEXT HUMAN CHECKPOINT: YES, subject to the independent audit's existing LOW RA7-001 and the Windows certification outcome here. This is not authorization for Windows deployment. No new BLOCKER, HIGH or MEDIUM defect was found.

## Identity and scope

The exact certified code/tests candidate is be898d3865685ac0261cdb255008db902b030521. Its R7 evidence-only child is b2eabac1da9ed3989de966583a51d97b3834aa9c; the unchanged independent hostile audit commit is 342d3e4a38634aad8abf7a93ff85f5ebf2012972, itself a child of b2eab. The audit verdict was PASS FOR NEXT HUMAN CHECKPOINT and Windows certification OPEN. This certification branch cert/v05-r7-windows starts at that audit commit and adds only certification artifacts. The production and test paths did not differ between the candidate and audit commits, and the six frozen V0.4 trees matched their freeze tree IDs. R7 and audit SHA manifests verified completely; see evidence/W00_integrity.txt and evidence/W00_integrity_final.txt.

The check ran on the user's Windows Lenovo ThinkPad L380, Windows 10.0.26200.9457, account jack\abbot, CPython 3.12.10. The candidate lived in a separate detached LF checkout with core.autocrlf=false. The existing t6-remediation checkout was not modified. No provider call, real credential, live betting, production execution, permanent trust-store or machine configuration change, code/test edit, remediation, merge, PR or push occurred.

The checked-in independent_audits/v05_r7_hostile_reaudit/WINDOWS_GAPS.md defined W1-W15. The relevant governance was the project laws, V0.5 adapter architecture and V0.4 freeze/provenance requirements. Exact per-item commands, environment, expected and observed outcomes, evidence and residuals are in WINDOWS_CHECKLIST.md and REPRO_COMMANDS.md.

## Disposition by item

| Status | Items |
| --- | --- |
| PASS | W2, W3, W4, W5, W6, W7, W9, W10, W12, W14, W15 |
| OPEN | W1, W8, W11 |
| FAIL | W13 |

W13 makes the overall disposition FAIL. A throwaway loopback TLS private-key file on NTFS inherited SYSTEM, Administrators and OWNER RIGHTS full-control entries, and owner-only ACL verification failed. The key was deleted. This is new LOW finding WC7-001 in the test fixture, with no observed production credential or provider impact. The candidate was not changed.

W1 could not be certified because this account lacks real symlink privilege; os.symlink returned WinError 1314. The symlink suite skips are missing Windows coverage. W8 established that long credential, runtime and evidence paths worked, but Git could not create or enter a 279-285 character candidate repository checkout even with LongPathsEnabled=1 and core.longpaths=true. No deployment repository path constraint was provided, so W8 remains OPEN. W11's counts are green and match baseline, yet the relevant W1 symlink tests skipped; therefore W11 remains OPEN.

W15 confirmed caller deadlines and no late socket during Windows resolver tests. The 100-stall soak also reproduced the known LOW RA7-001: 100 daemon workers remained live for 15 seconds, then all recovered after release. Windows DNS Client was running and actual randomized .invalid and single-label resolution was exercised. A protocol-specific LLMNR/NetBIOS stall was not forced or separately attributed; this is a coverage limitation of the feasible host run, not evidence that those protocols were tested individually.

## Suite and integrity summary

The complete adapter suite finished 917 tests, 0 failures/errors, 2 skips. The complete frozen V0.4 suite finished 493 tests, 0 failures/errors, 1 skip, identical to the approved S0 count. FRZ-09 final provenance passed 3/3. The real-link skips are documented in TEST_RESULTS.md. Raw candidate checkout verification matched 756/756 tracked Git blobs before and after certification. Suite-created empty untracked runtime files were documented and removed; candidate status returned clean. No certification command modified candidate production or test bytes.

Certification findings are in FINDINGS.csv. WC7-001 is LOW; WC7-002 records the Windows Git long-path deployment limitation. RA7-001 remains the independent audit's LOW operational residual. There is no new BLOCKER/HIGH/MEDIUM finding. Full evidence and SHA-256 artifact manifest are in this directory.

