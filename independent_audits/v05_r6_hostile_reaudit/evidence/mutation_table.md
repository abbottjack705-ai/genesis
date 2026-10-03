
### R5 independent campaign (re-run on 4ed66de)

| id | file | mutation | result | first failing test |
| --- | --- | --- | --- | --- |
| M00 | clock.py | CONTROL: no-op edit must SURVIVE (suite green on the mutation worktree) | SURVIVED |  |
| M01 | transport_http.py | transport entry deadline >= -> > | KILLED | test_bnd04_nothing_is_written_at_or_after_the_deadline (test_v05_transport_http) |
| M02 | transport_http.py | transport T0-before-write deadline >= -> > | KILLED | test_ha03_the_deadline_arriving_after_the_timeout_setup_prevents_the_write (test_v05_r2_transport_boundary) |
| M03 | transport_http.py | transport: no remaining check after connect/TLS (HA-03 slow connect) | KILLED | test_a_connect_that_uses_up_the_deadline_writes_nothing_and_arms_no_non_positive_timeout (test_v05_r6_deadline) |
| M04 | transport_http.py | transport: read loop ignores deadline | KILLED | test_exactly_at_the_deadline_nothing_more_is_read (test_v05_r6_deadline) |
| M05 | transport_http.py | transport: process-control SystemExit keeps raw code (text leak) | KILLED | test_ha02_system_exit_from_close_keeps_its_status_and_drops_its_text (test_v05_r2_transport_boundary) |
| M06 | transport_http.py | transport: re-raise the ORIGINAL control exception, not a fresh one | KILLED | test_ha02_keyboard_interrupt_from_close_leaves_fresh (test_v05_r2_transport_boundary) |
| M07 | acquisition.py | runner: T0 before send >= -> > | KILLED | test_no_request_is_started_at_or_after_the_deadline (test_v05_r6_deadline) |
| M08 | acquisition.py | runner: late response (T1>=deadline) accepted | KILLED | test_a_response_after_the_deadline_is_discarded (test_v05_r6_deadline) |
| M09 | acquisition.py | runner: T1 == deadline accepted (>= -> >) | KILLED | test_a_response_received_exactly_at_the_deadline_is_discarded (test_v05_r6_deadline) |
| M10 | acquisition.py | guard W1 strict -> non-strict | KILLED | test_bnd01_day_conditions_bind_alone_when_month_boundaries_are_out_of_reach (test_v05_boundary) |
| M11 | acquisition.py | guard W3 >= -> > | KILLED | test_bnd01_day_conditions_bind_alone_when_month_boundaries_are_out_of_reach (test_v05_boundary) |
| M12 | acquisition.py | guard W2 (month) removed | KILLED | test_bnd02_leap_february_has_a_29th_day (test_v05_boundary) |
| M13 | acquisition.py | guard W4 (month start) removed | KILLED | test_bnd02_month_conditions_bind_alone_when_day_boundaries_are_out_of_reach (test_v05_boundary) |
| M14 | acquisition.py | retry limit off by one | KILLED | test_q05_attempt_limit_backoff_window_headroom_and_circuit (test_v05_acquisition) |
| M15 | acquisition.py | provider usage divergence threshold loosened | BAD_SPEC (anchor rewritten by R6; see -adapted) |  |
| M16 | acquisition.py | 3xx treated as success | KILLED | test_f07_redirects_are_refused_never_followed (test_v05_acquisition) |
| M17 | cli.py | reset: any later G1 clears SECRET_ECHO (no rotation required) | KILLED | test_p014_a_secret_echo_halt_is_cleared_only_after_a_g1_for_a_rotated_key (test_v05_r5_operator) |
| M18 | cli.py | approve: stated granted_at skew bound becomes 10 years | KILLED | test_real_package_has_no_forbidden_numeric_literals (test_v05_frz10) |
| M19 | cli.py | approve-ready: no capability floor | KILLED | ERROR test_p013_ready_is_never_recorded_before_the_sources_latest_capability_row (test_v05_r5_operator) |
| M20 | reader.py | reader: no STALE refusal when a newer capture expired | KILLED | test_rdr01_reader_builder_and_frozen_verifier_agree_on_the_whole_grid (test_v05_manifest) |
| M21 | parser.py | parser: omitted requested tournaments no longer make a response partial | KILLED | test_an_empty_response_to_a_request_that_named_tournaments_is_partial_and_tombstones_nothing (test_v05_parser_schema) |
| M22 | raw_capture.py | raw: exact-size body treated as oversize | KILLED | test_the_capture_accepts_a_body_of_exactly_the_cap_and_flags_one_byte_more (test_v05_r6_low_findings) |
| M23 | raw_capture.py | raw: unsupported/nested content-encoding treated as identity | KILLED | test_fm11b_an_uninspectable_body_is_quarantined_metadata_only_without_a_halt (test_v05_failure_matrix) |
| M24 | raw_capture.py | raw: wire body not scanned (decoded only) | KILLED | test_ha08_a_content_encoded_oversize_body_is_screened_on_its_wire_bytes (test_v05_r2_transport_boundary) |
| M25 | raw_capture.py | raw: gzip trailing/second member tolerated | KILLED | test_gzip_with_trailing_or_second_member_data_is_uninspectable (test_v05_secret_capture) |
| M26 | secrets.py | secrets: double-encoded percent not decoded twice | KILLED | test_the_key_echoed_percent_encoded_once_twice_and_three_times_is_detected (test_v05_r6_low_findings) |
| M27 | secrets.py | secrets: JSON \/ escape not normalised | KILLED | test_the_key_echoed_through_the_pipeline_halts_and_leaves_nothing_durable (test_v05_r6_low_findings) |
| M28 | secrets.py | secrets: base64 core min length off by one | KILLED | test_a_base64_core_of_exactly_the_minimum_length_is_detected (test_v05_r6_low_findings) |
| M29 | credential.py | credential: hard-link count not required to be 1 | KILLED | test_f04_a_file_with_a_second_hard_link_name_is_refused (test_v05_credential) |
| M30 | credential.py | credential: group/other bits only (0400 accepted) | KILLED | test_only_mode_0600_is_accepted (test_v05_r6_low_findings) |
| M31 | transport.py | safe_errno: key-bearing errno no longer screened | KILLED | test_ha01_an_errno_carrying_key_digits_is_dropped_and_the_label_kept (test_v05_r2_transport_boundary) |
| M32 | emit.py | emit: conflicting PIT row under same record_id tolerated | KILLED | test_f33_a_pit_record_that_differs_from_the_intended_one_halts_and_is_never_replaced (test_v05_emit) |
| M33 | emit.py | emit: resume re-stamps T3 instead of reusing durable T3 | KILLED | ERROR test_a3_a_crash_at_every_emission_checkpoint_resumes_to_the_same_durable_history (test_v05_emit_crash) |
| M34 | quiescence.py | quiescence: pending invalidation not a blocker | KILLED | test_ha05_a_pending_invalidation_leaves_nothing_readable_until_a_start_completes_it (test_v05_r4_pit_recovery) |
| M35 | authority.py | authority: validity end exclusive | KILLED | test_a_g1_record_is_valid_through_its_last_instant_inclusive (test_v05_r6_low_findings) |
| M36 | quota_gate.py | quota: RESERVE budget class used | KILLED | test_a2_a_reconciled_orphan_is_retried_only_under_a_fresh_identity_and_debit (test_v05_acquisition) |
| M37 | derivation.py | verify: observation metadata not compared (valid_to) | BAD_SPEC (anchor rewritten by R6; see -adapted) |  |
| M38 | cli.py | approve: stated-granted_at bound widened WITHOUT a numeric literal (re-do of M18) | KILLED | test_p013_approve_stamps_granted_at_with_the_trusted_clock_and_refuses_a_chosen_one (test_v05_r5_operator) |
| M39 | raw_capture.py | raw: response header NAMES no longer screened | KILLED | test_ha07_a_non_ascii_key_echoed_in_a_header_name_is_a_secret_echo (test_v05_r2_transport_boundary) |
| M40 | raw_capture.py | raw: quarantine metadata not re-scanned (defence in depth) | KILLED | test_a_key_spanning_fields_of_the_record_leaves_no_optional_metadata (test_v05_r6_low_findings) |
| M41 | cli.py | reset: an AUTH_REJECTED circuit is cleared without any later G1 | KILLED | test_p014_an_auth_rejection_is_cleared_only_after_a_new_g1 (test_v05_r5_operator) |
| M42 | reader.py | reader: published_at > D no longer refused | KILLED | ERROR test_fm39_a_head_published_after_the_cutoff_is_unusable_with_no_fallback (test_v05_failure_matrix) |
| M43 | emit.py | emit: an existing observation with different content is reused | KILLED | test_f32_an_observation_that_contradicts_the_derivation_halts_and_publishes_nothing_more (test_v05_emit) |
| M44 | quiescence.py | quiescence: run lock blocks instead of refusing (LOCK_NB removed) | KILLED | test_ha06_a_cli_run_is_refused_while_another_process_holds_the_lock (test_v05_r4_pit_recovery) |
| M45 | credential.py | credential: files inside the repo / runtime root allowed | KILLED | test_f04_a_file_inside_the_repository_or_the_runtime_root_is_refused (test_v05_credential) |
| M46 | authority.py | authority: duplicate request hashes in a G2 record allowed | KILLED | test_a_g2_record_pins_distinct_request_hashes (test_v05_r6_low_findings) |
| M47 | cli.py | run: G2R no longer anchors the source UNKNOWN | KILLED | test_p013_a_g2r_cli_start_anchors_the_running_source_unknown_once (test_v05_r5_operator) |
| M48 | acquisition.py | acquisition: a secret-bearing persisted error record is kept | KILLED | test_ha01_the_record_is_scanned_again_exactly_as_it_will_be_persisted (test_v05_r2_transport_boundary) |
| M49 | acquisition.py | acquisition: a 429 circuit for one role blocks nothing | KILLED | test_f09_429_opens_the_role_circuit_until_the_next_utc_day (test_v05_acquisition) |
| M50 | authority.py | live gate: time-sync attestation not required | KILLED | test_g01_without_every_gate_element_nothing_is_sent (test_v05_authority) |
| M51 | acquisition.py | live: sending allowed without a secret scanner | KILLED | test_f04_live_mode_without_a_secret_scanner_halts_before_any_quota_call (test_v05_secret_capture) |
| M15-adapted | acquisition.py | provider usage divergence threshold loosened (the audit's M15 re-anchored on R6's rewritten condition) | KILLED | test_fm37_and_q09_provider_usage_above_the_genesis_debit_halts (test_v05_failure_matrix) |
| M37-adapted | derivation.py | verify: observation metadata not compared (valid_to) (the audit's M37 re-anchored on R6's longer tuple) | KILLED | test_every_alteration_of_the_observation_metadata_is_rejected (test_v05_r6_low_findings) |

### R6-targeted campaign of this audit

| id | file | mutation | result | first failing test |
| --- | --- | --- | --- | --- |
| X00 | clock.py | CONTROL: no-op edit must SURVIVE | SURVIVED |  |
| X01 | pipeline.py | RA5-001 skip terminal rejection persistence | KILLED | test_a_rejection_is_a_durable_verdict_with_coverage_and_no_observation (test_v05_r6_poison_pill) |
| X02 | derivation.py | RA5-001 a rejected capture is still a successful capture (re-derive) | KILLED | test_a_rejected_capture_is_not_a_successful_capture_for_any_reader_of_the_ledger (test_v05_r6_poison_pill) |
| X03 | quiescence.py | RA5-001 a rejected capture stays pending for ever (reads refused) | KILLED | test_every_class_ends_in_a_defined_restart_stable_state (test_v05_r6_poison_pill) |
| X04 | derivation.py | RA5-001 narrow the total boundary to two families | KILLED | ERROR test_a_duplicate_plan_item_reports_why_the_attempt_was_rejected (test_v05_r6_poison_pill) |
| X05 | jsonstrict.py | RA5-001 one extra nesting level accepted (dict) | KILLED | test_a_container_chain_of_exactly_max_depth_is_accepted_and_one_more_is_too_deep (test_v05_jsonstrict) |
| X06 | jsonstrict.py | RA5-001 one extra nesting level accepted (list) | KILLED | test_a_container_chain_of_exactly_max_depth_is_accepted_and_one_more_is_too_deep (test_v05_jsonstrict) |
| X07 | jsonstrict.py | RA5-001 lone surrogate permitted in a string VALUE | KILLED | test_a_bound_error_carries_no_payload_text (test_v05_jsonstrict) |
| X08 | jsonstrict.py | RA5-001 lone surrogate permitted in a KEY | KILLED | test_a_lone_surrogate_anywhere_is_invalid_text (test_v05_jsonstrict) |
| X09 | jsonstrict.py | RA5-001 decimal exponent bound off by one (loosened) | KILLED | test_a_decimal_literal_is_bounded_by_its_adjusted_exponent_in_both_directions (test_v05_jsonstrict) |
| X10 | jsonstrict.py | RA5-001 integer digit bound off by one (loosened) | KILLED | test_an_integer_literal_is_bounded_by_the_same_measure (test_v05_jsonstrict) |
| X11 | jsonstrict.py | RA5-001 Decimal InvalidOperation escapes the decoder | KILLED | ERROR test_an_exponent_beyond_what_a_decimal_can_represent_is_out_of_range_never_an_arithmetic_error (test_v05_jsonstrict) |
| X12 | jsonstrict.py | RA5-001 RecursionError escapes the decoder | KILLED | ERROR test_a_chain_beyond_the_decoders_own_recursion_limit_is_too_deep_not_a_crash (test_v05_jsonstrict) |
| X13 | ids.py | RA5-001/006 native id grammar widened to 65 characters | KILLED | test_id02_string_grammar_and_int_range (test_v05_ids) |
| X14 | parser.py | RA5-001 participant id outside grammar is an exception again (safety net instead of F-22) | KILLED | test_a_participant_id_outside_the_grammar_blocks_only_that_fixtures_books (test_v05_r6_poison_pill) |
| X15 | acquisition.py | RA5-001 replay: rejection accepted after a FAILED completion | KILLED | test_a_verdict_is_only_for_a_response_that_passed_its_content_checks (test_v05_r6_poison_pill) |
| X16 | acquisition.py | RA5-001 replay: rejection accepted after NORMALIZED | KILLED | test_a_normalized_attempt_cannot_be_rejected_and_a_rejected_one_cannot_be_normalized (test_v05_r6_poison_pill) |
| X17 | acquisition.py | RA5-001 replay: unknown failure code accepted | KILLED | test_an_unknown_failure_code_and_a_missing_attempt_are_refused (test_v05_r6_poison_pill) |
| X18 | acquisition.py | RA5-001 settle() does not locate the rejection row (crash between row and coverage) | KILLED | test_a_rejection_is_a_durable_verdict_with_coverage_and_no_observation (test_v05_r6_poison_pill) |
| X19 | acquisition.py | RA5-001 rejection coverage status REJECTED -> NOT_ATTEMPTED | KILLED | test_a_rejection_is_a_durable_verdict_with_coverage_and_no_observation (test_v05_r6_poison_pill) |
| X20 | pipeline.py | RA5-001 an already NORMALIZED capture that stops deriving is 'rejected' instead of halting | KILLED | ERROR test_a_normalized_capture_that_stops_deriving_is_an_integrity_halt_not_a_rejection (test_v05_r6_poison_pill) |
| X21 | parser.py | RA5-001 FIXTURES snapshot builder no longer total | KILLED | ERROR test_the_snapshot_builder_turns_any_exception_into_an_unusable_join (test_v05_r6_poison_pill) |
| X22 | pipeline.py | RA5-001 acquire() hides the derivation refusal from its outcome | KILLED | ERROR test_every_exception_family_from_document_building_is_a_terminal_verdict (test_v05_r6_poison_pill) |
| X23 | raw_capture.py | RA5-002 parse_http_date catches only the old tuple | KILLED | ERROR test_a_seeded_fuzz_over_date_shaped_strings_never_raises (test_v05_r6_date_header) |
| X24 | raw_capture.py | RA5-002 a Date dropped for length reads as 'no Date' | KILLED | test_an_over_long_date_header_is_present_not_missing (test_v05_r6_date_header) |
| X25 | raw_capture.py | RA5-002 bypass: unparseable Date accepted | KILLED | test_every_present_but_unusable_value_is_a_clock_skew_quarantine_in_fixture_mode_too (test_v05_r6_date_header) |
| X26 | transport_http.py | RA5-003 environment CA trust restored (only the key log hidden) | KILLED | test_every_variable_at_once_does_not_authorize_the_production_context (test_v05_r6_tls_boundary) |
| X27 | transport_http.py | RA5-003 SSL_CERT_DIR not hidden | KILLED | test_every_variable_at_once_does_not_authorize_the_production_context (test_v05_r6_tls_boundary) |
| X28 | transport_http.py | RA5-003 SSLKEYLOGFILE not hidden | KILLED | test_the_key_log_file_named_by_the_environment_is_never_written (test_v05_r6_tls_boundary) |
| X29 | transport_http.py | RA5-003 explicit keylog_filename=None removed | KILLED | test_the_context_is_asserted_not_trusted (test_v05_r6_tls_boundary) |
| X30 | transport_http.py | RA5-003 environment not restored | KILLED | test_the_environment_is_restored_even_when_the_context_cannot_be_built (test_v05_r6_tls_boundary) |
| X31 | transport_http.py | RA5-003 host-name verification disabled | KILLED | ERROR test_r1_the_real_https_transport_boundary_is_scanned_too (test_v05_r1_sanitized_error) |
| X32 | transport_http.py | RA5-004 receive not armed from the absolute deadline | KILLED | test_a_send_and_a_receive_are_armed_before_they_block (test_v05_r6_deadline) |
| X33 | transport_http.py | RA5-004 deadline may move LATER (max instead of min) | KILLED | test_settimeout_can_only_pull_the_deadline_in (test_v05_r6_deadline) |
| X34 | transport_http.py | RA5-004 deadline reset on every bound (per recv loop / per settimeout) | KILLED | test_settimeout_can_only_pull_the_deadline_in (test_v05_r6_deadline) |
| X35 | transport_http.py | RA5-004 connect attempts not bounded | KILLED | test_each_resolved_address_is_tried_under_the_time_that_is_left (test_v05_r6_deadline) |
| X36 | transport_http.py | RA5-004 TLS handshake not bounded | KILLED (suite hangs: handshake-stall test; confirmed in x36_confirm.txt) | test_v05_r6_deadline.SlowPeerOnRealSocketsTests.test_a_peer_that_accepts_but_never_completes_the_tls_handshake_cannot_hold_the_transport |
| X37 | transport_http.py | RA5-004 send not armed | KILLED | test_a_send_and_a_receive_are_armed_before_they_block (test_v05_r6_deadline) |
| X38 | transport_http.py | RA5-004 exhausted deadline arms a tiny timeout instead of refusing | KILLED | test_no_address_is_tried_once_an_earlier_attempt_used_up_the_deadline (test_v05_r6_deadline) |
| X39 | acquisition.py | RA5-011 unreadable usage header fails OPEN | KILLED | test_a_crash_between_the_completed_row_and_the_halt_still_halts_after_restart (test_v05_r6_low_findings) |
| X40 | acquisition.py | RA5-011 usage figure length cap removed | KILLED | ERROR test_every_unreadable_value_halts_as_a_quota_divergence (test_v05_r6_low_findings) |
| X41 | acquisition.py | RA5-011 presence judged from the kept (allowlisted) headers again | KILLED | test_every_occurrence_is_judged_not_only_the_first (test_v05_r6_low_findings) |
| X42 | derivation.py | RA5-009 verifier omits upstream_version | KILLED | test_every_alteration_of_the_observation_metadata_is_rejected (test_v05_r6_low_findings) |
| X43 | derivation.py | RA5-009 verifier omits content_type | KILLED | test_every_alteration_of_the_observation_metadata_is_rejected (test_v05_r6_low_findings) |
| X44 | acquisition.py | RA5-005 quota-decision clock fault escapes raw | KILLED | ERROR test_a_fault_before_the_send_sends_nothing (test_v05_r6_low_findings) |
| X45 | acquisition.py | RA5-005 T0 clock fault escapes raw | KILLED | ERROR test_a_fault_before_the_send_sends_nothing (test_v05_r6_low_findings) |
| X46 | credential.py | RA5-007 non-printable/non-ASCII key accepted at load | KILLED | test_every_other_octet_is_refused_as_not_a_key (test_v05_r6_low_findings) |
| X47 | config.py | RA5-008 operational bookmaker ceiling not enforced | KILLED | test_a_policy_above_the_architecture_limit_is_refused_by_the_operational_loader (test_v05_r6_low_findings) |
| X48 | ids.py | RA5-006 native id grammar anchored with $ again | KILLED | test_native_ids_and_identity_kinds (test_v05_r6_low_findings) |
| X49 | schema.py | RA5-006 schema map-key grammar anchored with $ again | KILLED | test_response_schema_map_keys (test_v05_r6_low_findings) |
| X50 | endpoints.py | RA5-006 request text grammar anchored with $ again | KILLED | test_endpoint_specifications (test_v05_r6_low_findings) |

Extra per-worker no-op controls: M00-w2 SURVIVED (182s), M00-w3 SURVIVED (181s)
