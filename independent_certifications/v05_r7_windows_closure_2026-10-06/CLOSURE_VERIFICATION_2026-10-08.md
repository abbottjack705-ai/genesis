# Genesis V0.5 R7 Windows certification closure: Administrator-session verification

Date: 2026-10-08

**WINDOWS CERTIFICATION: PASS**

**WINDOWS LIVE/PROVIDER ACTIVATION: NOT AUTHORIZED — WC7-003 OPEN**

These are two separate determinations. The certification verdict is that every W1–W15 item passes for production candidate `be898d3` with certification support `deec08f`; W8 passes under the short-path constraint. The activation status is that no Windows live acquisition or provider activation is authorized while LOW production defect WC7-003 is open. Scope and residuals are listed below.

This file verifies the Administrator session run on 2026-10-07 against the closure rule in `WINDOWS_CERTIFICATION_REPORT.md` (2026-10-06): "Do not issue `WINDOWS CERTIFICATION: PASS` until the Administrator session records W1, W5, and W11 PASS." That report, `WINDOWS_CHECKLIST.md`, and the session's own `SHA256SUMS.txt` are not edited. They remain the record of the OPEN state on 2026-10-06. The immutable historical FAIL at `cert/v05-r7-windows` `68b1fbc5340a41605900df2c23da29ec4edf91fb` is unchanged.

## Identity

- Production candidate: `be898d3865685ac0261cdb255008db902b030521`, detached LF checkout `C:\Users\abbot\a8\v05_prep\genesis_r7_candidate_lf`.
- Certification support: `deec08ffc66c56d156bc09addf548c62166cea17` (`R7_W13_LF`). It differs from the candidate only in `adapters/adapter_tests/tls_support.py` and `adapters/adapter_tests/test_v05_r6_tls_boundary.py`.
- Certification probes: `credential_ntfs.py` and `raw_checkout.py` from `independent_certifications/v05_r7_windows/probes` at `68b1fbc`.
- Rechecked on 2026-10-08: candidate HEAD `be898d3`, support HEAD `deec08f`, and certification tree HEAD `68b1fbc`. All three have zero `git status --porcelain` lines, and `core.autocrlf=false`. The probes therefore ran unchanged.

## What actually ran

The script that produced the passing evidence is **not** the prepared `Run-R7-Admin-W1-W11.ps1`. Its SHA-256 `BA489AB5…` is unchanged since 2026-10-06. The executed script was a corrected copy, `C:\Users\abbot\Downloads\Run-R7-Admin-W1-W11-CORRECTED.ps1`, saved at 22:33:31, seven seconds before the run began. It is now preserved as `executed/Run-R7-Admin-W1-W11-CORRECTED.ps1`, SHA-256 `31ad871ac46e545c9ac25cfb33c626402547f6a0a280da2adb809012a903b39c`. A line diff against the prepared script shows the following changes:

1. Native commands run through `Start-Process` with separate stdout/stderr files. The prepared script used `*>`, `1>` and `2>` redirection under Windows PowerShell 5.1 with `$ErrorActionPreference='Stop'`. That form writes UTF-16 output and converts native stderr lines into errors, and unittest writes its progress to stderr. Therefore W1 and the final raw check now produce `.stdout.txt`/`.stderr.txt` pairs rather than one `.txt` file.
2. The precondition requiring `SeCreateSymbolicLinkPrivilege` to appear in `whoami /priv` was removed. The recorded token lists it (state `Disabled`, as usual for an elevated token before use), so the prepared precondition would also have passed.
3. `Set-StrictMode`, evidence-directory creation and UTF-8 resync capture were added.
4. The acceptance checks are textually identical: W5 regexes, the W1 `CREATED`/`real_symlink_refused` match, targeted tests `ok` and not skipped, adapter `Ran 919` with `OK (skipped=1)`, frozen `Ran 493` with no skip, final raw probe, and clean worktrees. `#requires -RunAsAdministrator` is retained.

The change is mechanical. It does not weaken any acceptance criterion. It is nevertheless a deviation from the prepared and hashed script, and it is recorded here for that reason.

### Earlier attempt files in this directory

The following three UTF-16 files predate the passing run. They were produced by `*>` redirection, which matches the prepared script or manual commands. They record no script identity:

| File | mtime (2026-10-07) | Content | Disposition |
| --- | --- | --- | --- |
| `W05_admin_resync.txt` | 22:06:30 | `w32tm /resync` completed successfully | Elevated resync. It is the sync that the passing run's status reports (`Last Successful Sync Time 22:06:30`). |
| `W01_admin_real_symlink_probe.txt` | 22:20:56 | `W1_REAL_SYMLINK OPEN create_failed … winerror 1314`; all other cases match | **Superseded. It is not counted.** Its token is unrecorded. Developer Mode is not enabled (`AppModelUnlock` has no values), and the medium token still lacks the privilege. This is consistent with a non-elevated run, but the cause is not established. |
| `W00_admin_raw_checkout_final.txt` | 22:21:14 | HEAD `be898d3`, 756 tracked, 0 mismatches | Consistent with the passing run's final check. It is not relied on. |

## Verification of the 2026-10-07 22:33–23:02 run

| Check | Observation | Result |
| --- | --- | --- |
| Session manifest | All 39 entries in `SHA256SUMS.txt` (23:02:20) match current bytes, and no unlisted file existed before this verification | OK |
| Elevation | `W01_admin_token.txt` (22:33:38) lists SeDebug (Enabled), SeTakeOwnership, SeBackup, SeRestore and SeCreateSymbolicLink. This is an elevated administrator token. | OK |
| **W5** | `W05_admin_w32tm_status.txt` (22:33:38): Leap Indicator 0, stratum 5, source `time.windows.com,0x9`, last sync 22:06:30, root dispersion 8.29 s. Recorded before W1 and W11 ran. | **PASS** |
| **W1** | `W01_admin_real_symlink_probe.stdout.txt`: `W1_REAL_SYMLINK CREATED is_symlink True`; `CASE real_symlink_refused … ACTUAL CREDENTIAL_PERMISSIONS MATCH True`; stderr empty. The other 10 cases and the W3 inherited-ACL outcome (W2 junctions, W3 ACLs, W8 310–313-character paths) are line-for-line identical to `W01_W08_credential_ntfs.txt` (2026-10-06). | **PASS** |
| W11 targeted | `test_f04_a_link_is_refused … ok` and `test_h3_directory_alias_is_the_same_owner_and_file_symlink_is_not … ok`, with no skip | OK |
| **W11** adapter | 919 tests in 1159 s, `OK (skipped=1)`. The only skip is `test_only_mode_0600_is_accepted` (POSIX mode, inapplicable on Windows). There are 0 FAIL and 0 ERROR lines. | **PASS** |
| **W11** frozen V0.4 | 493 tests in 539 s, `OK` with no skip. There are 0 FAIL and 0 ERROR lines. | **PASS** |
| W11 baseline compare | The test-name sets are identical to the 2026-10-05 pre-privilege runs for both suites. Per-test outcomes differ only in those two symlink tests, which moved from `skipped` to `ok`. The adapter counts match the 919-test support baseline, and the frozen counts match S0 (493) with the previously skipped test now executed. | OK |
| Final integrity | `W00_admin_raw_checkout_final.stdout.txt` (23:02:18): HEAD `be898d3`, 756 tracked, 0 raw-blob mismatches, `core.autocrlf=false`. Both checkouts were clean after the suites, and are still clean on 2026-10-08. | OK |

## Item disposition for this closure attempt

| Status | Items |
| --- | --- |
| PASS | W1, W2, W3, W4, W5, W6, W7, W9, W10, W11, W12, W13, W14, W15 |
| PASS with constraint | W8: Windows deployments must use a bounded short local repository root. The tested root has 50 characters. Arbitrarily deep Git working-tree roots are unsupported. |
| OPEN / FAIL | none |

The per-item basis for W2–W4, W6–W10 and W12–W15 is unchanged from `WINDOWS_CHECKLIST.md` (2026-10-06).

## New finding WC7-003 (LOW production defect): the Windows live time-sync gate accepts an unsynchronized clock

`adapters/src/genesis_adapters/cli.py:245` `time_sync_attestation()` is the gate meant to ensure that, without an attestation, there is no live acquisition (architecture design 6.1). On Windows it reports `synchronized: True` whenever `w32tm /query /status` exits 0 and `Source:` is not `Local CMOS Clock` or `Free-running System Clock`. It ignores `Leap Indicator: 3 (not synchronized)`, `Stratum: 0` and the age of the last successful sync. The Linux branch, by contrast, requires `NTPSynchronized=yes`.

Observed on this host: `W05_post_session_gate_2026-10-08.txt` was captured at 2026-10-08 12:42 BST from the unchanged pinned candidate. `w32tm` reports Leap Indicator 3, stratum 0, reference ID unspecified, and last successful sync 2026-10-07 22:06:30, more than 14 hours earlier, although `w32time` is Running. Under the same conditions the product returns `{'synchronized': True, 'method': 'w32tm', 'source': 'time.windows.com,0x9'}`. The same unsynchronized state was observed on 2026-10-06 (`W05_current_w32tm_status.txt`). So on this host the gate would admit a live run and durably record a false "synchronized" attestation in the state the host is usually in.

The implementation follows the design's Windows rule literally (`source ≠ Local CMOS Clock`). The weakness is therefore in that rule as well as in the code. The certification's own W5 acceptance (Leap 0, stratum ≠ 0, non-local source) is stricter than the product gate. The function is mocked in every adapter test (`test_v05_tx01.py:134`, `test_v05_r3_runner_state.py:610`, `test_v05_r4_pit_recovery.py:166`, `test_v05_r5_operator.py:196`), so no test exercises its parsing.

Severity is LOW for three reasons:
- The per-response `Date` cross-check (`clock_skew_max_seconds` = 120) quarantines responses, which bounds undetected local clock error at about 120 s.
- The `SystemUtcClock` wall/monotonic drift and regression checks catch clock jumps.
- Live acquisition remains behind G1/G2 and is not active.

The defect is in the accuracy of an evidence record, and it affects PIT margins only within that bound. It does not block this certification, under the same standard that kept W15 PASS with LOW RA7-001.

Recommended for the next candidate: on Windows, require Leap Indicator ≠ 3, stratum ≠ 0 and a recent `Last Successful Sync Time`. Record the parsed fields in the attestation, and add an unmocked parser test that uses captured `w32tm` text, including the text in this directory. Amend design 6.1 to match. This changes production code, so it needs a new candidate and audit; it is not done here.

## Operational observation (environment, not product)

This host's Windows Time service does not keep synchronization. It recovered only after a manual elevated `w32tm /resync`, and by the next morning it had lost sync again despite a 1024 s poll interval. W5 attests the host during the certification session, as the original W5 did; it does not attest the host now. Before any Windows live run, fix the host's NTP path and confirm Leap Indicator 0 at run start. Because of WC7-003, the product will not enforce this.

## Residuals carried

- **RA7-001** (LOW, open): resolver daemon workers accumulate during a persistent DNS stall and recover after release. This is from W15.
- **WC7-002** (INFO, accepted under the W8 constraint): Git cannot create or enter repository roots of about 280 characters.
- **WC7-003** (LOW production defect, new, open): the Windows time-sync gate accepts an unsynchronized clock, as described above. Windows live/provider activation is not authorized while it is open.
- **W15-OS** (INFO, reviewed): no LLMNR/NetBIOS-specific stall attribution.
- **WC7-001** (LOW): closed for support state `deec08f` by W13. It remains part of the historical FAIL.
- **W1-PRIV** (INFO): closed by the elevated session.

## Scope

This verdict covers production candidate `be898d3` with certification support `deec08f` on this Windows 11 host (10.0.26200, CPython 3.12) under the W8 short-path constraint. **WINDOWS LIVE/PROVIDER ACTIVATION: NOT AUTHORIZED — WC7-003 OPEN.** The certification is not authorization for Windows deployment, live acquisition, provider activation or betting, and it does not amend or reclassify the historical FAIL at `68b1fbc`. No provider call or real credential was used. No production, test or probe file was changed by this verification.

## Added on 2026-10-08

- `CLOSURE_VERIFICATION_2026-10-08.md` (this file)
- `README.md` (pointer to the final result)
- `.gitattributes` (stores this byte evidence without end-of-line conversion)
- `FINDINGS_2026-10-08.csv`
- `W05_post_session_gate_2026-10-08.txt`
- `executed/Run-R7-Admin-W1-W11-CORRECTED.ps1`
- `SHA256SUMS_2026-10-08.txt` covers every file in this directory except itself, including the session's `SHA256SUMS.txt`.
