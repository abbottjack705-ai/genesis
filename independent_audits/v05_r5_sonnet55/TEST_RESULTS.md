# Test results (independent, Linux)

Host: Linux 6.18 (VM), CPython 3.11.15, 4 vCPU, git 2.43.0, OpenSSL 3.0.13 (`evidence/host_env.txt`). Windows results from the
implementer are **not** reproduced and are not treated as equivalent (see `WINDOWS_GAPS.md`). Transcripts are in `evidence/`.

## 1. Summary table

| Item | Implementer's claim | Independent result | Evidence |
| --- | --- | --- | --- |
| Adapter suite | 690 OK, 1 skip (real symlink) | **Ran 690, FAILED (errors=1), 0 skips** — 689 OK; the real-symlink test **ran and passed** (POSIX); the one error is `test_f04_a_link_reported_by_lstat_is_refused_on_every_platform` (`RA5-013`). 88.6 s; identical result (92.9 s) inside a loopback-only network namespace | `adapter_suite_linux.txt`, `netns_suite.txt` |
| Adapter suite under an independent network audit hook | no non-loopback contact | 690 run, 24 socket events, **2 non-loopback `getaddrinfo` attempts** (`192.0.2.1`, `genesis.example.invalid`), both from `test_v05_transport_http.py:173-175` (the suite's deliberate guard self-test, refused before any connect) | `nonet.json` |
| Frozen V0.4 suite | 493 OK, 1 skip (Windows) | **Ran 493, OK, skipped=19** (all Windows-only: AppContainer/Job confinement, N2 caseless owners, `os.startfile`, 8.3 names; §21 A11). Not comparable with the Windows 492/1 baseline; no failure | `frozen_suite_linux.txt` |
| Frozen trees / worktree after both suites | unchanged | **unchanged** (`git rev-parse HEAD:<tree>` equal to the freeze; `git status --porcelain` empty) | §6 of the report |
| `compileall -q src tests adapters/src adapters/adapter_tests` | clean | rc 0 | — |
| `git diff --check c8dfafd..b22263e` (excluding evidence) | clean | rc 0, no output | — |
| 167/167 architecture test IDs | present | consistent: own parse of §18 gives 166 expanded IDs, all matched by a test name or a `Frz*` class | — |
| 17 reproduction probes | 0 reproduced | implementer's script re-run on Linux: `reproduced=0 not_reproduced=17 probe_errors=0` (**their** probes; cannot see `RA5-003`) | `implementer_repro17_linux.txt` |
| Deterministic replay | byte-identical | **reproduced**: two fresh roots, 174 durable files, 0 differ | `p130_replay.txt` |
| Mutation suite | 128 mutants, 127 killed, 1 equivalent | not re-run; independent **51 mutants: 37 killed, 14 survived** (§3); the "equivalent" survivor is killable | `mutation_results_round1/2.jsonl` |
| Secret sweep | clean | **clean** except (i) two hex-alphabet fragment false positives in `authority.py`/`acquisition.py` (and one in frozen `protected_research_worker.py`), (ii) the committed test private key `adapter_tests/fixtures/tls/server.key` (`RA5-003`) | §5 |

## 2. Independent hostile probes (outcome per probe)

"HELD" = the attack failed; "DEFECT" = reproduced (finding id). Each probe prints its own data; see `evidence/<probe>.txt`.

| Probe | Area | Outcome |
| --- | --- | --- |
| p10_deadline | B | HELD: no request byte at/after the deadline (entry, T0, connect/TLS, settimeout, write, head, body) |
| p11_slowdrip | B | DEFECT `RA5-004` (40.6 s vs 3 s on a real socket) |
| p12_runner_deadline | B/C | HELD (slow-work 61 s not sent; T1 ≥ deadline discarded); DEFECT `RA5-005` (raw ClockFault, reads 3/4) |
| p131_guard_oracle | B | HELD: 21,200 points, 0 mismatches vs independent W1–W4 oracle |
| p20_quota_replay | C | HELD at all 7 runner checkpoints (no resend; retry = fresh id + debit) |
| p150_usage | C | DEFECT `RA5-011` |
| p40_emit_crash | D/F | HELD at the 10 emission checkpoints reached (an 11th index, `after_pit:12`, is never reached by this fixture); converged states identical |
| p140_rejected_restart | E | HELD: 16 rejected/quarantined outcomes stay unusable after restart |
| p41/p42/p43 | F/G | HELD (no fallback; STALE; invalidation never revives; crash during restart completion converges) |
| p90_derivation | H | HELD for bytes/scope/request/valid_to; DEFECT `RA5-009` (upstream_version, content_type) |
| p30_completeness | I | HELD for omitted/empty/wrong-sport tournaments; `RA5-010` (fixture-level) |
| p60_operator / p61_reset | J/K/L | HELD; DEFECT `RA5-008` (declared_bookmakers_max) |
| p50/p51/p52/p54 | A | HELD (25 + 6 + 24 + 13 attack variants) |
| p53_nonascii / p55 | A | DEFECT `RA5-007` (body path); p55 shows double-encoded detector load-bearing |
| p70_tls_env | M | DEFECT `RA5-003` |
| p80_provenance | O | HELD (CRLF, newline, byte swap, shadow, competing) |
| p100_static_evasion | Q | `RA5-014` |
| p95_f44 | F-44 | safe; diagnostics lost (`F44_ASSESSMENT.md`) |
| p110_regex_nl | — | DEFECT `RA5-006` |
| p113/p118/p119b/p112/p115/p116/p119/p120/p124 | E/I | **DEFECT `RA5-001` (BLOCKER)** |
| p122/p123 | A | DEFECT `RA5-002` |
| p117/p121 | fuzz controls | no escape (FIXTURES builder; 250 full-pipeline iterations) |
| p130_replay | — | HELD (deterministic) |
| p160_equiv_mutant | Q | DEFECT `RA5-012` (equivalent label wrong) |
| p170_dev7 | deviations 6, 7 | as classified in `DEVIATION_REVIEW.md` |

## 3. Independent mutation campaign (51 mutants + control)

Method: `probes/mutate.py` applies **one** textual edit to a scratch worktree, runs the full adapter suite fail-fast through
`probes/runner_ff.py` (which deselects only the single platform-baseline error `RA5-013`), records KILLED/SURVIVED, restores
the file. Control `M00` (no-op) must survive and did.

| ID | Result | Secs | Mutation | Killed by (first failing test) |
| --- | --- | --- | --- | --- |
| M00 | SURVIVED | 98 | CONTROL: no-op edit must SURVIVE (suite green on the mutation worktree) |  |
| M01 | KILLED | 84 | transport entry deadline >= -> > | test_bnd04_nothing_is_written_at_or_after_the_deadline |
| M02 | KILLED | 62 | transport T0-before-write deadline >= -> > | test_ha03_the_deadline_arriving_after_the_timeout_setup_prevents_the_write |
| M03 | SURVIVED | 100 | transport: no remaining check after connect/TLS (HA-03 slow connect) |  |
| M04 | SURVIVED | 96 | transport: read loop ignores deadline |  |
| M05 | KILLED | 57 | transport: process-control SystemExit keeps raw code (text leak) | test_ha02_system_exit_from_close_keeps_its_status_and_drops_its_text |
| M06 | KILLED | 58 | transport: re-raise the ORIGINAL control exception, not a fresh one | test_ha02_keyboard_interrupt_from_close_leaves_fresh |
| M07 | SURVIVED | 97 | runner: T0 before send >= -> > |  |
| M08 | SURVIVED | 96 | runner: late response (T1>=deadline) accepted |  |
| M09 | SURVIVED | 94 | runner: T1 == deadline accepted (>= -> >) |  |
| M10 | KILLED | 3 | guard W1 strict -> non-strict | test_bnd01_day_conditions_bind_alone_when_month_boundaries_are_out_of_reach |
| M11 | KILLED | 3 | guard W3 >= -> > | test_bnd01_day_conditions_bind_alone_when_month_boundaries_are_out_of_reach |
| M12 | KILLED | 3 | guard W2 (month) removed | test_bnd02_leap_february_has_a_29th_day |
| M13 | KILLED | 3 | guard W4 (month start) removed | test_bnd02_month_conditions_bind_alone_when_day_boundaries_are_out_of_reach |
| M14 | KILLED | 2 | retry limit off by one | test_q05_attempt_limit_backoff_window_headroom_and_circuit |
| M15 | KILLED | 16 | provider usage divergence threshold loosened | test_fm37_and_q09_provider_usage_above_the_genesis_debit_halts |
| M16 | KILLED | 1 | 3xx treated as success | test_f07_redirects_are_refused_never_followed |
| M17 | KILLED | 75 | reset: any later G1 clears SECRET_ECHO (no rotation required) | test_p014_a_secret_echo_halt_is_cleared_only_after_a_g1_for_a_rotated_key |
| M18 | KILLED | 21 | approve: stated granted_at skew bound becomes 10 years | test_real_package_has_no_forbidden_numeric_literals |
| M19 | KILLED | 75 | approve-ready: no capability floor | test_p013_ready_is_never_recorded_before_the_sources_latest_capability_row |
| M20 | KILLED | 29 | reader: no STALE refusal when a newer capture expired | test_rdr01_reader_builder_and_frozen_verifier_agree_on_the_whole_grid |
| M21 | KILLED | 27 | parser: omitted requested tournaments no longer make a response partial | test_an_empty_response_to_a_request_that_named_tournaments_is_partial_and_tombstones_nothing |
| M22 | SURVIVED | 95 | raw: exact-size body treated as oversize |  |
| M23 | KILLED | 10 | raw: unsupported/nested content-encoding treated as identity | test_fm11b_an_uninspectable_body_is_quarantined_metadata_only_without_a_halt |
| M24 | KILLED | 58 | raw: wire body not scanned (decoded only) | test_ha08_a_content_encoded_oversize_body_is_screened_on_its_wire_bytes |
| M25 | KILLED | 79 | raw: gzip trailing/second member tolerated | test_gzip_with_trailing_or_second_member_data_is_uninspectable |
| M26 | SURVIVED | 97 | secrets: double-encoded percent not decoded twice |  |
| M27 | SURVIVED | 94 | secrets: JSON \/ escape not normalised |  |
| M28 | SURVIVED | 96 | secrets: base64 core min length off by one |  |
| M29 | KILLED | 5 | credential: hard-link count not required to be 1 | test_f04_a_file_with_a_second_hard_link_name_is_refused |
| M30 | SURVIVED | 97 | credential: group/other bits only (0400 accepted) |  |
| M31 | KILLED | 61 | safe_errno: key-bearing errno no longer screened | test_ha01_an_errno_carrying_key_digits_is_dropped_and_the_label_kept |
| M32 | KILLED | 6 | emit: conflicting PIT row under same record_id tolerated | test_f33_a_pit_record_that_differs_from_the_intended_one_halts_and_is_never_replaced |
| M33 | KILLED | 9 | emit: resume re-stamps T3 instead of reusing durable T3 | test_a3_a_crash_at_every_emission_checkpoint_resumes_to_the_same_durable_history |
| M34 | KILLED | 74 | quiescence: pending invalidation not a blocker | test_ha05_a_pending_invalidation_leaves_nothing_readable_until_a_start_completes_it |
| M35 | SURVIVED | 96 | authority: validity end exclusive |  |
| M36 | KILLED | 1 | quota: RESERVE budget class used | test_a2_a_reconciled_orphan_is_retried_only_under_a_fresh_identity_and_debit |
| M37 | SURVIVED | 97 | verify: observation metadata not compared (valid_to) |  |
| M38 | KILLED | 75 | approve: stated-granted_at bound widened WITHOUT a numeric literal (re-do of M18) | test_p013_approve_stamps_granted_at_with_the_trusted_clock_and_refuses_a_chosen_one |
| M39 | KILLED | 61 | raw: response header NAMES no longer screened | test_ha07_a_non_ascii_key_echoed_in_a_header_name_is_a_secret_echo |
| M40 | SURVIVED | 97 | raw: quarantine metadata not re-scanned (defence in depth) |  |
| M41 | KILLED | 77 | reset: an AUTH_REJECTED circuit is cleared without any later G1 | test_p014_an_auth_rejection_is_cleared_only_after_a_new_g1 |
| M42 | KILLED | 17 | reader: published_at > D no longer refused | test_fm39_a_head_published_after_the_cutoff_is_unusable_with_no_fallback |
| M43 | KILLED | 7 | emit: an existing observation with different content is reused | test_f32_an_observation_that_contradicts_the_derivation_halts_and_publishes_nothing_more |
| M44 | KILLED | 675 | quiescence: run lock blocks instead of refusing (LOCK_NB removed) | test_ha06_a_cli_run_is_refused_while_another_process_holds_the_lock |
| M45 | KILLED | 5 | credential: files inside the repo / runtime root allowed | test_f04_a_file_inside_the_repository_or_the_runtime_root_is_refused |
| M46 | SURVIVED | 88 | authority: duplicate request hashes in a G2 record allowed |  |
| M47 | KILLED | 74 | run: G2R no longer anchors the source UNKNOWN | test_p013_a_g2r_cli_start_anchors_the_running_source_unknown_once |
| M48 | KILLED | 61 | acquisition: a secret-bearing persisted error record is kept | test_ha01_the_record_is_scanned_again_exactly_as_it_will_be_persisted |
| M49 | KILLED | 1 | acquisition: a 429 circuit for one role blocks nothing | test_f09_429_opens_the_role_circuit_until_the_next_utc_day |
| M50 | KILLED | 3 | live gate: time-sync attestation not required | test_g01_without_every_gate_element_nothing_is_sent |
| M51 | KILLED | 81 | live: sending allowed without a secret scanner | test_f04_live_mode_without_a_secret_scanner_halts_before_any_quota_call |

Survivors: M03, M04, M07, M08, M09, M22, M26, M27, M28, M30, M35, M37, M40, M46. Classification and proofs: `FINDINGS.csv` `RA5-012`. M18 was killed only by the FRZ-10
numeric-literal scanner (my edit introduced a literal); it was redone as M38 (no literal) and killed behaviourally.

## 4. Platform separation

* **PLATFORM-INDEPENDENT PASS**: everything under §2 marked HELD, the two suites' logic, replay, oracle, provenance guard.
* **WINDOWS-SPECIFIC VERIFIED FROM REPO EVIDENCE ONLY**: `adapters/evidence/FINAL/ADAPTER_SUITE.txt` (690 OK, 1 skip),
  `FROZEN.txt` (493 OK, 1 skip), `R1/SYMLINK_CHECK.txt` (WinError 1314).
* **WINDOWS-SPECIFIC NOT REPRODUCED HERE**: NTFS symlinks/junctions, `icacls` ACL check, `msvcrt` lock, `w32tm`, coarse clock,
  `STATUS_CONTROL_C_EXIT`, antivirus sharing violations, MAX_PATH.
* **WINDOWS CERTIFICATION STILL REQUIRED**: see `WINDOWS_GAPS.md` §4.  **WINDOWS SYMLINK CERTIFICATION: OPEN.**

## 5. Static / provenance / secret checks

* `compileall` rc 0; `git diff --check` rc 0; frozen tree SHAs unchanged at `b22263e` and after running both suites.
* CRLF/byte provenance: see `p80_provenance.txt` (CRLF-altered frozen module, extra newline, same-length byte swap → `MODULE_HASH_MISMATCH`; shadow/competing `genesis` → `COMPETING_GENESIS`; an mtime-only change correctly passes; an unlisted, never-imported file passes — consistent with §2.4, which checks loaded modules).
* Secret sweep: `grep` for private-key blocks → only `adapters/adapter_tests/fixtures/tls/server.key`; no `apiKey=` values, no
  token-prefix strings; public sentinel `GENESIS-SENTINEL-KEY-0123456789abcdef` only in tests (never under `adapters/evidence`,
  `adapters/config`, `adapters/README.md`, `remediation_evidence`); my own detector (no shared code) found no key form there.
