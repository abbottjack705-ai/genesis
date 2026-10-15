# WC7-003 W5 Windows Time-Sync Recertification: Result (2026-10-15)

Exact tested SHA: 2e8290ea7a8a26d4796de893036c12a0d05b7b2b

WC7-003 W5 RECERTIFICATION: PASS

This is a repeat of the narrow W5 recertification after the operator restored Windows time synchronization. The
2026-10-14 attempt (FAIL, environmental: Leap Indicator 3, Stratum 0) is preserved unchanged at commit 6b3eb43 and is not
superseded in the history.

## Required checks

1. **Clean-checkout provenance.** Fresh detached worktree at 2e8290e. Status empty before and after the probes and tests.
   `git diff --check` exit 0. Parent 896de47. Tracked blobs equal the tree (details: SUBJECT_PROVENANCE.txt). Frozen
   `src` unchanged against 4f11606 and v0.4-foundation-freeze.
2. **Fresh genuine raw `w32tm /query /status`.** Return code 0, 324 bytes, LF-only framing (10 bare LF, 0 CRLF, 0 bare CR).
   Output: `Leap Indicator: 0(no warning)`, `Stratum: 5 (secondary reference - syncd by (S)NTP)`, `Source:
   time.windows.com,0x9`, `Last Successful Sync Time: 15/10/2026 22:08:34`. Captured 2026-10-15T21:11:03Z.
   Evidence: evidence/W05_w32tm_query_status_stdout_raw.bin, evidence/W05_w32tm_query_status_capture.json.
3. **Unmocked production `time_sync_attestation()`** from the clean checkout (module
   `C:\Users\abbot\fz\w5rc-r2\adapters\src\genesis_adapters\cli.py`). Result: `synchronized: true`, `leap_indicator: 0`,
   `stratum: 5`, `source: time.windows.com,0x9`, `method: w32tm`. Evidence: evidence/W05_real_startup_attestation.json.
   The real host was required to be synchronized=True, and it was.
4. **Healthy controls and unhealthy G2/G2R fake-transport zero-send replays.** The WC7-003 test module, unmodified, from the
   clean checkout: `python -B -m unittest -v adapter_tests.test_v05_wc7_003_time_sync`. Result: **Ran 76 tests, OK**, with 0
   failures, 0 errors and 0 skips (810.1 s). Transcript: evidence/W05_wc7_003_unittest_transcript.txt.
   - Healthy controls include `test_healthy_status_sends_exactly_once_in_each_mode`,
     `test_stratum_1_and_15_are_admitted_and_send_exactly_once_in_each_mode`,
     `test_secondary_reference_note_sends_exactly_once_in_each_mode`,
     `test_unrelated_lines_do_not_block_a_healthy_status_in_either_mode` and the real-child-process healthy tests. Each
     sends exactly once in G2 and in G2R.
   - Unhealthy replays through the real LiveGate and acquisition runner, with a fake transport, in G2 and G2R, all refused
     at the gate with zero transport calls: Stratum 0, 16, 17 and 255; every generated contradictory Stratum note;
     invalid-label and malformed-framing tables through the G2R runtime wrapper; malformed status tables.
5. **Integrity and history checks.** See INTEGRITY_HISTORY.txt. Historical certification tree `8113408a` and manifest
   `660fc79f` are unchanged at 2285f24. The 2026-10-14 record is hash-verified and unmodified. No production or test file
   changed.

## Statements

- Exact SHA 2e8290e passed.
- The WC7-003 foundation remediation gate is CLOSED.
- The monolithic adapter-run memory limitation remains a recorded residual.
  Note: during this recertification I searched every ref, the Genesis memory directory, the adapter docs and the
  `remediation_evidence` tree and could not find a document with that exact wording. The operator should attach the
  residual's source reference so the record can be traced.
- Live/provider/betting remains NOT AUTHORIZED.

## Host observations (not gate conditions)

- The `w32time` service is Running. Its start type is now DEMAND_START (Manual); the 2026-10-14 record showed AUTO_START
  (DELAYED). The attestation is healthy. The change was not made by this attempt and is recorded for the operator
  (evidence/W05_environment_and_time_service.txt).
- No `w32tm /resync` or other clock change was made by this attempt. No attestation was faked, patched or relaxed.
- The subject worktree `C:\Users\abbot\fz\w5rc` (2e8290e) from the 2026-10-14 attempt was not used or modified.
