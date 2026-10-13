# WC7-003 W5 Windows Time-Sync Recertification: Result

Exact tested SHA: 2e8290ea7a8a26d4796de893036c12a0d05b7b2b

WC7-003 W5 RECERTIFICATION: FAIL

Blocker: environmental Windows-time blocker. The real host was not healthy according to Genesis, so the run stopped fail-closed, as the recertification rule requires.

Evidence:
- evidence/W05_w32tm_query_status_stdout_raw.bin: raw stdout of the genuine `w32tm /query /status` (return code 0, 290 bytes, LF-only framing). The host reports `Leap Indicator: 3(not synchronized)` and `Stratum: 0 (unspecified)`, with the last successful sync on 12/10/2026 20:11:30.
- evidence/W05_real_startup_attestation.json: the unmocked production `time_sync_attestation()` returned synchronized=false, leap_indicator=3, stratum=0, source=time.windows.com,0x9, last_successful_sync=12/10/2026 20:11:30.

Not run because of the stop condition: the healthy-control transcript and the unhealthy G2/G2R refusal replays. Nothing in this record claims them.

Not done: no attestation was faked, patched, relaxed or manufactured. No `w32tm /resync` or other clock change was made. The W5 step can only be repeated after a healthy host synchronization is restored by the operator.

Historical certification at 2285f24 is unchanged, and cert/v05-r7-windows is still at 2285f24. No production or test file changed. The WC7-003 foundation remediation gate is NOT closed by this record. Windows live/provider/betting activation remains NOT AUTHORIZED.
