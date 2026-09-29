# V0.5 slice-1 implementation summary (S0–S7)

Authority: `V05_ADAPTER_ARCHITECTURE.md` r3 at `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe`. Branch
`v05-slice1-impl` (local; no branch was assigned for pushing). Fixture/offline/PAPER only: no OddsPapi
credential, no network or API call, no live smoke, no approval record, no READY capability (the G-03 test
writes one only into a throwaway scratch registry), no strategy, model or betting logic. Every file is under
`adapters/`; the six frozen trees are byte-identical.

Stage commits: S0 `63e06a1`, S1 `1bc6001`, S2 `78bedb9`, S3 `b95465e`, S4 `9de0790`, S5 `ff7f4ba`, S6 `9c35c5c`, S7 = the commit that adds this file

Frozen tree SHAs at every stage commit (checked by `TREES.txt` and the freeze guard):
`src 51cb635bc42b993815b6c02a23c4c3ceb7d98476`, `tests e90b298180068fec03ba7e2fa81957082e7fb3ce`,
`config abd22db01ff482a8da84634ee740ba382b68c804`, `tools a0e3411edb4e068fd4708050516cb6870834e7ac`,
`DECISIONS cc97ec6f841f1e3fbe6dbb57c9cb6e1ac24fdb64`, `v04_pack 3c3c1c27d80ed6f10c32ac6605a5f438b2e7de12`.

## Method

Per stage (design 23): the stage's tests were written, then a RED transcript was captured against the
previous stage's tree (`RED.txt`), then the production code was installed and made GREEN (`GREEN.txt`,
fresh `PYTHONPYCACHEPREFIX`, `-B`), then the frozen suite ran alone on the machine (`FROZEN.txt`) and was
compared with the S0 baseline (`FROZEN_COMPARE.txt`), plus `COMPILE.txt`, `DIFFCHECK.txt`, `TREES.txt`,
`GUARDS.txt` (freeze guard + module-provenance guard verdict) and `HASHES.sha256`. From S2 on, production
code for a stage was drafted before its RED run and held outside the repository during that run, so each
RED transcript reflects the previous stage's tree exactly (noted at the top of every RED file). S4–S7 also
carry `MUTATION.txt` (mutation smoke tests; the harness aborts if the unmutated baseline fails; survivors
found in S5/S6 led to sharper tests and a recorded re-run).

## Freeze and provenance guard output

`GUARDS.txt` of every stage: `freeze guard (six tree SHAs @ HEAD): PASS`, `frozen worktree clean: PASS`,
`module-provenance guard: PASS` (manifest sha256 `9a50e370cb27919ee6b13e85a2b325cdaf6691c3b1168a2bc1294f1604e22fdf`,
15 frozen modules verified by Git blob SHA-1 and SHA-256, bytecode isolated). The S1 frozen run once failed
under CPU contention (two subprocess start-up timeouts while other Python work ran); the transcript is kept
(`S1/FROZEN_RUN1_contention.txt`), the isolation re-runs passed, and the clean re-run is `S1/FROZEN.txt`.

## Per-stage test counts

| Stage | Adapter tests | Adapter result | Frozen suite |
| --- | --- | --- | --- |
| S0 | 38 | OK | 493 tests (890 s), OK (skipped=1) |
| S1 | 136 | OK | 493 tests (831 s), OK (skipped=1) |
| S2 | 202 | OK | 493 tests (787 s), OK (skipped=1) |
| S3 | 246 | OK | 493 tests (901 s), OK (skipped=1) |
| S4 | 373 | OK | 493 tests (1296 s), OK (skipped=1) |
| S5 | 451 | OK | 493 tests (648 s), OK (skipped=1) |
| S6 | 519 | OK | 493 tests (581 s), OK (skipped=1) |
| S7 | 573 | OK (skipped=1) | 493 tests (11144 s), OK (skipped=1) |

## Section 18 test IDs

| ID | Status | Tests (count: first names) |
| --- | --- | --- |
| FRZ-01 | PASS | 1: `test_frz01_six_tree_shas_equal_the_freeze_record` |
| FRZ-02 | PASS | 1: `test_frz02_guard_fails_on_added_file_and_on_edited_config` |
| FRZ-03 | PASS | 3: `test_frz03_dirty_frozen_worktree_is_detected`, `test_frz03_frozen_worktree_is_clean_after_the_suite`, `test_frz03_worktree_clean_over_the_frozen_trees` |
| FRZ-04 | PASS | 1: `test_frz04_transcript_comparison` |
| FRZ-05 | PASS | 3: `test_accepts_public_use`, `test_flags_planted_violations`, `test_real_package_is_clean` |
| FRZ-06 | PASS | 4: `test_network_imports_only_in_transport`, `test_non_network_urllib_parse_is_allowed`, `test_real_package_is_clean` ... |
| FRZ-07 | PASS | 2: `test_flags_reserve_authority`, `test_real_package_is_clean` |
| FRZ-08 | PASS | 3: `test_flags_test_only_names_and_ready`, `test_ready_is_allowed_only_in_the_operator_cli`, `test_real_package_is_clean` |
| FRZ-09 | PASS | 16: `test_frz09_a_modified_frozen_module_fails`, `test_frz09_an_unlisted_module_file_fails`, `test_frz09_clean_isolated_run_passes_and_records_the_verdict` ... |
| FRZ-10 | PASS | 6: `test_accepts_structural_literals`, `test_flags_literals_equal_to_a_large_policy_value_anywhere`, `test_flags_names_that_read_like_bounds_and_defaults` ... |
| FRZ-11 | PASS | 5: `test_except_exception_and_plain_finally_are_fine`, `test_flags_process_control_handlers`, `test_frz11_the_cli_has_no_process_control_handler` ... |
| REQ-01 | PASS | 2: `test_req01_credential_params_and_aliases_are_rejected_not_dropped`, `test_req01_unknown_and_missing_params` |
| REQ-02 | PASS | 3: `test_req02_canonical_request_matches_the_section_7_3_shape`, `test_req02_parameter_and_set_order_never_change_the_hash`, `test_req02_pinned_golden_hash` |
| REQ-03 | PASS | 1: `test_req03_any_identity_change_changes_the_hash` |
| REQ-04 | PASS | 1: `test_req04_no_form_of_the_key_survives_a_full_pipeline_run` |
| REQ-05 | PASS | 3: `test_req05_repr_and_str_are_masked_with_the_fingerprint`, `test_req05_reveal_requires_the_transport_capability`, `test_req05_serialization_and_copying_are_blocked` |
| REQ-06 | PASS | 1: `test_req06_an_exception_naming_the_keyed_url_leaves_only_class_and_errno` |
| REQ-07 | PASS | 1: `test_req07_and_f11_a_body_echoing_the_key_leaves_no_body_bytes_hash_or_derivative` |
| SEC-01 | PASS | 11: `test_sec01_base64_all_alignments_both_alphabets_with_and_without_padding`, `test_sec01_clean_content_is_clean`, `test_sec01_detection_classes_never_expose_offsets_or_text` ... |
| SEC-02 | PASS | 2: `test_sec02_headers_names_and_values_are_scanned`, `test_sec02_the_key_in_any_header_name_or_value_is_caught_even_outside_the_allowlist` |
| SEC-03 | PASS | 2: `test_sec03_secret_in_the_decoded_gzip_body_is_a_secret_echo`, `test_sec03_secret_only_in_the_wire_bytes_is_still_a_secret_echo` |
| SEC-04 | PASS | 1: `test_sec04_quarantine_metadata_is_itself_scanned_and_dirty_fields_are_dropped` |
| SEC-05 | PASS | 3: `test_sec05_empty_and_missing_roots`, `test_sec05_every_form_planted_anywhere_under_the_root_is_found`, `test_sec05_file_names_are_scanned_too` |
| TX-01 | PASS | 3: `test_tx01_keyboard_interrupt_keeps_its_meaning_and_arrives_fresh`, `test_tx01_ordinary_failures_at_every_stage_become_sanitized_results`, `test_tx01_system_exit_keeps_its_status_and_never_prints_text` |
| REQ-08 | PASS | 1: `test_req08_hash_part_source_uri_and_content_addressing` |
| CLK-01 | PASS | 7: `test_clk01_backwards_wall_clock_raises_even_within_the_drift_bound`, `test_clk01_equal_reads_are_allowed_but_never_earlier`, `test_clk01_floor_below_durable_heads_raises` ... |
| CLK-02 | PASS | 1: `test_clk02_a_live_runner_refuses_a_test_clock_and_a_test_quota_policy` |
| CLK-03 | PASS | 1: `test_clk03_replay_rejects_rows_that_violate_the_time_ordering` |
| CLK-04 | PASS | 2: `test_clk04_missing_or_unparseable_date_quarantines_only_in_live_capture_mode`, `test_clk04_the_skew_boundary_is_exact_in_both_directions` |
| TS-01 | PASS | 1: `test_ts01_a_naive_timestamp_blocks_the_book` |
| TS-02 | PASS | 2: `test_ts02_a_zero_offset_in_any_spelling_is_utc`, `test_ts02_an_explicit_non_zero_offset_is_rejected_not_normalized` |
| TS-03 | PASS | 1: `test_ts03_unparseable_or_wrongly_typed_timestamps_are_invalid` |
| TS-04 | PASS | 1: `test_ts04_the_future_tolerance_boundary_is_exact` |
| TS-05 | PASS | 2: `test_ts05_a_start_at_or_before_receipt_while_pre_match_is_contradictory`, `test_ts05_an_invalid_scheduled_start_is_an_event_start_problem` |
| TS-06 | PASS | 1: `test_ts06_at_the_guard_edge_nothing_is_emitted_and_one_microsecond_earlier_the_book_is_open` |
| TS-07 | PASS | 1: `test_ts07_pit_fields_equal_design_11_4_exactly_for_open_and_each_non_open_state` |
| ID-01 | PASS | 5: `test_id01_matches_the_independent_formula_for_every_kind`, `test_id01_no_delimiter_ambiguity`, `test_id01_parts_are_order_independent_and_kinds_are_domain_separated` ... |
| ID-02 | PASS | 6: `test_id02_a_fixture_id_of_the_wrong_json_type_rejects_the_whole_response`, `test_id02_a_fixture_id_outside_the_native_grammar_rejects_the_whole_response`, `test_id02_a_tournament_id_of_the_wrong_type_is_schema_rejected_at_event_scope` ... |
| ID-03 | PASS | 2: `test_id03_a_new_name_for_a_known_participant_appends_one_name_drift_row`, `test_id03_participants_come_from_provider_ids_not_names` |
| ID-04 | PASS | 1: `test_id04_and_f21_rebinding_a_fixture_blocks_its_known_books_and_writes_no_row` |
| ID-05 | PASS | 2: `test_id05_and_f22_a_missing_or_wrongly_typed_participant_id_is_ambiguous`, `test_id05_and_f22_home_equal_to_away_is_ambiguous_and_binds_nothing` |
| ID-06 | PASS | 1: `test_id06_only_the_two_pinned_competitions_are_known` |
| ID-07 | PASS | 2: `test_id07_an_undeclared_bookmaker_is_excluded_and_a_declared_one_is_kept`, `test_id07_the_declared_bookmaker_order_is_irrelevant` |
| ID-08 | PASS | 1: `test_id08_changing_every_display_name_changes_no_id_and_no_artifact` |
| ID-09 | PASS | 2: `test_id09_operational_loader_refuses_fixture_only_maps`, `test_id09_the_operational_loader_refuses_maps_that_still_hold_fixture_only_entries` |
| MKT-01 | PASS | 2: `test_mkt01_three_bookmakers_by_two_families_give_six_distinct_books_per_event`, `test_mkt01_undeclared_bookmakers_and_exchanges_are_excluded_and_counted` |
| MKT-02 | PASS | 2: `test_mkt02_an_exchange_can_never_be_declared`, `test_mkt02_more_than_the_permitted_bookmakers_normalize_only_under_a_larger_policy_limit` |
| MKT-03 | PASS | 4: `test_mkt03_2_4999_is_excluded_and_never_rounded_into_2_5`, `test_mkt03_a_line_typed_as_a_numeric_string_is_read_exactly`, `test_mkt03_only_the_exact_2_5_line_is_emitted_and_other_lines_are_counted_never_merged` ... |
| MKT-04 | PASS | 2: `test_mkt04_and_f18_differing_duplicate_2_5_markets_block_the_book`, `test_mkt04_identical_duplicate_2_5_markets_collapse_to_one_open_book` |
| MKT-05 | PASS | 2: `test_mkt05_a_line_from_an_undeclared_source_is_excluded`, `test_mkt05_a_missing_or_unreadable_line_is_excluded_not_guessed` |
| MKT-06 | PASS | 2: `test_mkt06_and_f19_a_1x2_book_without_the_draw_is_blocked_as_incomplete`, `test_mkt06_and_f19_an_extra_unmapped_outcome_blocks_the_book` |
| MKT-07 | PASS | 7: `test_mkt07_an_active_outcome_without_a_price_is_contradictory`, `test_mkt07_and_f20_parse_level_invalid_prices_block_the_book`, `test_mkt07_and_f20_prices_at_or_below_even_money_on_an_active_outcome_are_contradictory` ... |
| MKT-08 | PASS | 2: `test_mkt08_and_f20_overround_bands_are_inclusive_and_exact`, `test_mkt08_the_over_under_band_is_separate_from_the_1x2_band` |
| MKT-09 | PASS | 1: `test_mkt09_outcomes_are_mapped_by_provider_outcome_id_only` |
| ST-01 | PASS | 2: `test_st01_every_allowlisted_value_maps_exactly`, `test_st01_the_event_states_are_the_documented_ones` |
| ST-02 | PASS | 1: `test_st02_and_f23_an_unknown_event_status_blocks_every_book_of_the_event_and_only_that_event` |
| ST-03 | PASS | 2: `test_st03_and_f23_an_unknown_bookmaker_level_status_blocks_that_bookmakers_books_in_the_event`, `test_st03_and_f23_an_unknown_outcome_status_blocks_that_book_only` |
| ST-04 | PASS | 2: `test_st04_an_inactive_outcome_may_carry_any_price_but_an_active_one_may_not_be_invalid`, `test_st04_and_f24_a_finished_event_with_an_active_price_is_contradictory` |
| ST-05 | PASS | 1: `test_pit04_and_st05_a_suspension_blocks_an_older_open_price_for_good` |
| ST-06 | PASS | 4: `test_st06_a_missing_event_status_is_unknown`, `test_st06_a_status_of_the_wrong_json_type_is_unknown_not_a_number`, `test_st06_matching_is_on_field_json_type_and_value` ... |
| EV-01 | PASS | 2: `test_ev01_identical_bytes_received_twice_are_two_observations_of_one_object`, `test_ev01_raw_bytes_are_stored_byte_exact_under_the_raw_contract` |
| EV-02 | PASS | 1: `test_ev02_tampering_is_detected_and_conflicting_republication_is_refused` |
| EV-03 | PASS | 4: `test_ev03_documents_are_independent_of_ambient_state`, `test_ev03_the_parser_and_normalizer_read_no_clock_file_network_or_randomness`, `test_ev03_the_pipeline_produces_twelve_books_and_every_document_rederives_byte_for_byte` ... |
| EV-04 | PASS | 4: `test_ev04_an_open_document_has_exactly_the_design_9_1_fields`, `test_ev04_identities_are_the_design_8_formulas`, `test_ev04_normalized_observations_match_the_contract` ... |
| EV-05 | PASS | 1: `test_ev05_a_manifest_built_at_d_passes_the_frozen_verifier_unchanged` |
| EV-06 | PASS | 2: `test_ev06_manifests_pinning_a_non_open_head_or_a_superseded_record_fail_the_verifier`, `test_ev06_only_an_open_document_can_supply_a_price` |
| EV-07 | PASS | 3: `test_ev07_and_f13_malformed_payloads_keep_raw_and_reject_coverage`, `test_ev07_oversize_is_retained_truncated_at_the_cap`, `test_ev07_wrong_or_missing_content_type` |
| EV-08 | PASS | 1: `test_ev08_a_partial_payload_emits_present_books_and_no_absent_documents` |
| PIT-01 | PASS | 1: `test_pit01_each_cutoff_sees_the_capture_that_was_ready_then` |
| PIT-02 | PASS | 1: `test_pit02_one_microsecond_before_t3_the_capture_is_not_visible` |
| PIT-03 | PASS | 1: `test_pit03_two_records_with_the_same_valid_from_are_ambiguous` |
| PIT-04 | PASS | 2: `test_pit04_and_st05_a_suspension_blocks_an_older_open_price_for_good`, `test_pit04_the_older_open_record_is_rejected_by_the_frozen_verifier_too` |
| PIT-05 | PASS | 2: `test_pit05_a_partial_or_failed_response_leaves_no_tombstone`, `test_pit05_and_f30_a_complete_response_without_an_expected_book_leaves_an_absent_head` |
| PIT-06 | PASS | 1: `test_inv01_and_pit06_invalidating_the_current_head_changes_only_cutoffs_after_t3_inv` |
| PIT-07 | PASS | 1: `test_pit07_a_derivation_change_hands_over_at_t_fix_and_two_ready_sources_fail_closed` |
| PIT-08 | PASS | 2: `test_pit08_a_crash_between_publication_and_the_pit_append_reuses_the_observation`, `test_pit08_record_ids_are_keyed_on_the_artifact_and_no_record_is_ever_superseded` |
| PIT-09 | PASS | 2: `test_pit09_rebuilding_into_empty_stores_gives_identical_artifacts_and_record_ids`, `test_pit09_rederiving_the_same_captures_into_empty_stores_gives_identical_artifacts_and_record_ids` |
| FR-01 | PASS | 1: `test_fr01_the_ttl_boundary_is_exact` |
| FR-02 | PASS | 1: `test_fr02_valid_to_is_capped_at_the_prematch_guard` |
| FR-03 | PASS | 1: `test_fr03_a_failed_or_blocked_refresh_changes_nothing` |
| FR-04 | PASS | 2: `test_fr04_a_cache_hit_acquisition_can_never_become_an_observation`, `test_fr04_odds_responses_are_never_cached_and_a_hit_never_creates_an_observation` |
| FR-05 | PASS | 2: `test_fr05_a_verified_metadata_cache_hit_costs_nothing_and_creates_no_observation`, `test_fr05_and_f34_expiry_is_a_billable_miss_with_a_recorded_reason` |
| FR-06 | PASS | 1: `test_fr06_an_entry_for_a_different_request_hash_is_never_usable` |
| FR-07 | PASS | 4: `test_fr07_and_f42_altering_a_referenced_cache_object_halts_all_acquisition`, `test_fr07_and_f42_altering_the_cache_authority_row_halts_all_acquisition`, `test_fr07_and_f42_deleting_a_referenced_cache_object_halts_all_acquisition` ... |
| FR-08 | PASS | 2: `test_fr08_changing_any_single_parameter_changes_every_downstream_identity`, `test_fr08_one_changed_policy_value_is_a_new_source_and_old_records_keep_their_valid_to` |
| Q-01 | PASS | 1: `test_q01_every_sent_acquisition_has_exactly_one_prior_allowed_quota_row` |
| Q-02 | PASS | 1: `test_q02_f02_eighth_request_of_a_utc_day_is_blocked_and_never_sent` |
| Q-03 | PASS | 2: `test_q03_the_221st_normal_unit_is_blocked_and_reserve_is_never_requested`, `test_q03_the_runner_only_ever_requests_normal_budget_without_authorization` |
| Q-04 | PASS | 1: `test_q04_failures_keep_their_debit_and_a_retry_is_debited_again` |
| Q-05 | PASS | 3: `test_q05_attempt_limit_backoff_window_headroom_and_circuit`, `test_q05_only_no_response_and_5xx_are_retryable`, `test_q05_zero_retries_configured_means_never` |
| Q-06 | PASS | 2: `test_q06_crash_after_send_becomes_an_orphaned_reservation_and_is_never_resent`, `test_q06_same_request_id_with_a_new_time_makes_the_frozen_ledger_halt` |
| Q-07 | PASS | 1: `test_q07_clock_behind_the_ledger_head_is_a_clock_fault_halt` |
| Q-08 | PASS | 4: `test_q08_admitted_only_when_every_condition_holds`, `test_q08_drops_come_from_the_lowest_priority_up`, `test_q08_the_plan_keeps_the_daily_cap_every_pool_and_the_monthly_projection` ... |
| Q-09 | PASS | 1: `test_fm37_and_q09_provider_usage_above_the_genesis_debit_halts` |
| Q-10 | PASS | 1: `test_q10_the_operational_ledger_loads_the_frozen_active_policy_unchanged` |
| BILL-01 | PASS | 1: `test_bill01_metering_fields_are_separate_from_the_genesis_debit` |
| BILL-02 | PASS | 1: `test_bill02_fixed_weight_role_debits_its_units_in_one_frozen_request` |
| BILL-03 | PASS | 1: `test_bill03_variable_and_unknown_metering_roles_are_refused_and_never_sent` |
| BILL-04 | PASS | 1: `test_bill04_reports_label_the_genesis_debit_and_provider_reported_usage_separately` |
| BILL-05 | PASS | 7: `test_bill05_b2_pre_send_cost_bound`, `test_bill05_documented_figures_for_rolling_and_non_utc_month_windows`, `test_bill05_figures_follow_the_policy_values_not_literals` ... |
| BND-01 | PASS | 4: `test_bnd01_day_conditions_bind_alone_when_month_boundaries_are_out_of_reach`, `test_bnd01_exact_day_edges_from_the_policy_values`, `test_bnd01_the_next_permitted_instant_is_the_boundary_plus_the_skew_margin` ... |
| BND-02 | PASS | 4: `test_bnd02_calculator_arithmetic`, `test_bnd02_exact_month_edges_at_every_rollover`, `test_bnd02_leap_february_has_a_29th_day` ... |
| BND-03 | PASS | 3: `test_bnd03_a_refused_send_makes_no_quota_call_and_writes_no_quota_row`, `test_bnd03_for_a_permitted_send_the_guard_time_and_the_ledger_time_are_one_value`, `test_bnd03_the_guard_runs_on_the_same_read_that_reaches_the_ledger` |
| BND-04 | PASS | 2: `test_bnd04_nothing_is_written_at_or_after_the_deadline`, `test_bnd04_the_attempt_is_cut_at_exactly_the_deadline` |
| BND-05 | PASS | 3: `test_bnd05_loader_rejects_nonpositive_missing_and_wide_guard_zone`, `test_bnd05_loader_rejects_nonpositive_timeout_missing_field_and_wide_guard_zone`, `test_bnd05_request_timeout_alone_changes_every_downstream_identity` |
| BND-06 | PASS | 1: `test_bnd06_no_window_is_ever_planned_inside_a_guard_zone` |
| BND-07 | PASS | 1: `test_bnd07_sends_stay_suspended_until_the_next_utc_day_and_a_clean_date_check` |
| G-01 | PASS | 1: `test_g01_without_every_gate_element_nothing_is_sent` |
| G-02 | PASS | 1: `test_g02_only_pinned_requests_at_most_max_calls_inside_the_window` |
| G-03 | PASS | 1: `test_g03_ready_only_through_the_operator_cli_after_a_g3_record` |
| G-04 | PASS | 2: `test_g04_auth_rejection_blocks_every_market_book_source`, `test_g04_block_every_known_market_book_source` |
| FM-00 | PASS | 4: `test_fm00_every_detail_code_maps_to_exactly_one_frozen_reason`, `test_fm00_every_section_15_code_is_enumerated`, `test_fm00_mapping_is_total_and_single_valued` ... |
| FM-01 | PASS | 1: `test_fm01_a_missing_gate_refuses_before_any_quota_call` |
| FM-02 | PASS | 1: `test_fm02_a_blocked_quota_is_recorded_and_nothing_is_sent` |
| FM-03 | PASS | 1: `test_fm03_a_clock_behind_the_ledger_halts` |
| FM-04 | PASS | 1: `test_fm04_a_credential_problem_refuses_and_halts` |
| FM-05 | PASS | 1: `test_fm05_a_transport_error_keeps_the_debit_and_is_missing_evidence` |
| FM-06 | PASS | 1: `test_fm06_a_truncated_body_is_raw_evidence_only` |
| FM-07 | PASS | 1: `test_fm07_a_redirect_is_refused_and_its_body_kept` |
| FM-08 | PASS | 1: `test_fm08_auth_rejection_blocks_every_market_book_capability_and_opens_the_circuit` |
| FM-09 | PASS | 1: `test_fm09_rate_limiting_is_budget_exhaustion_with_the_retry_after_header_kept` |
| FM-10 | PASS | 1: `test_fm10_a_server_error_is_missing_evidence_with_its_body_kept` |
| FM-11 | PASS | 1: `test_fm11_a_secret_echo_keeps_no_body_quarantines_halts_and_blocks` |
| FM-12 | PASS | 1: `test_fm12_clock_skew_quarantines_keeps_raw_and_suspends_sends` |
| FM-13 | PASS | 1: `test_fm13_and_fm14_bad_json_or_envelope_keep_raw_and_emit_nothing` |
| FM-14 | PASS | 1: `test_fm13_and_fm14_bad_json_or_envelope_keep_raw_and_emit_nothing` |
| FM-15 | PASS | 1: `test_fm15_a_partial_payload_emits_present_books_and_no_tombstones` |
| FM-16 | PASS | 1: `test_fm16_and_fm17_out_of_scope_content_is_counted_never_normalized` |
| FM-17 | PASS | 1: `test_fm16_and_fm17_out_of_scope_content_is_counted_never_normalized` |
| FM-18 | PASS | 1: `test_fm18_a_differing_duplicate_blocks_the_book` |
| FM-19 | PASS | 1: `test_fm19_an_incomplete_outcome_set_blocks_the_book` |
| FM-20 | PASS | 1: `test_fm20_invalid_or_incoherent_prices_block_the_book` |
| FM-21 | PASS | 1: `test_fm21_an_identity_conflict_blocks_known_books_and_quarantines_the_event` |
| FM-22 | PASS | 1: `test_fm22_an_ambiguous_participant_blocks_the_event` |
| FM-23 | PASS | 1: `test_fm23_an_unknown_status_blocks` |
| FM-24 | PASS | 1: `test_fm24_a_contradictory_status_blocks` |
| FM-25 | PASS | 1: `test_fm25_a_suspension_is_available_state_with_a_suspended_head` |
| FM-26 | PASS | 1: `test_fm26_an_event_that_is_no_longer_pre_match_blocks` |
| FM-27 | PASS | 1: `test_fm27_a_capture_inside_the_guard_emits_nothing_for_the_event` |
| FM-28 | PASS | 1: `test_fm28_a_provider_timestamp_anomaly_blocks` |
| FM-29 | PASS | 1: `test_fm29_a_missing_fixture_join_is_stale_metadata` |
| FM-30 | PASS | 1: `test_fm30_an_expected_book_absent_from_a_complete_response_gets_an_absent_head` |
| FM-31 | PASS | 1: `test_fm31_a_configuration_change_halts` |
| FM-32 | PASS | 1: `test_fm32_an_evidence_conflict_halts_and_never_rewrites_existing_bytes` |
| FM-33 | PASS | 1: `test_fm33_a_pit_append_conflict_halts` |
| FM-34 | PASS | 1: `test_fm34_a_metadata_cache_miss_is_a_recorded_genesis_debit` |
| FM-35 | PASS | 1: `test_fm35_an_orphaned_reservation_is_missing_evidence` |
| FM-36 | PASS | 1: `test_fm36_no_ready_or_two_ready_sources_are_unusable` |
| FM-37 | PASS | 1: `test_fm37_and_q09_provider_usage_above_the_genesis_debit_halts` |
| FM-38 | PASS | 1: `test_fm38_schema_drift_blocks_at_its_scope_and_rejects_at_the_envelope` |
| FM-39 | PASS | 1: `test_fm39_a_head_published_after_the_cutoff_is_unusable_with_no_fallback` |
| FM-40 | PASS | 1: `test_fm40_an_invalidation_quarantines_and_heads_the_scope` |
| FM-41 | PASS | 1: `test_fm41_a_module_provenance_failure_refuses_to_start` |
| FM-42 | PASS | 1: `test_fm42_an_altered_cache_object_halts_every_acquisition` |
| FM-43 | PASS | 1: `test_fm43_the_boundary_guard_refuses_before_any_quota_row` |
| SCH-01 | PASS | 7: `test_sch01_a_key_added_to_a_bookmaker_block_blocks_its_books_in_that_event`, `test_sch01_a_key_added_to_a_price_or_a_market_blocks_that_book_only`, `test_sch01_a_key_added_to_an_outcome_blocks_that_book_only` ... |
| SCH-02 | PASS | 2: `test_sch02_a_missing_required_key_is_drift_and_makes_the_response_partial`, `test_sch02_a_wrong_json_type_for_a_known_key_is_drift_at_its_scope` |
| SCH-03 | PASS | 1: `test_sch03_envelope_level_drift_rejects_the_response_with_no_observation_and_no_tombstone` |
| SCH-04 | PASS | 1: `test_sch04_schema_file_change_yields_new_schema_digest_and_derivation_version` |
| RDR-01 | PASS | 2: `test_a5_reader_and_frozen_verifier_agree_on_every_cutoff`, `test_rdr01_reader_builder_and_frozen_verifier_agree_on_the_whole_grid` |
| RDR-02 | PASS | 1: `test_f39_and_rdr02_a_head_published_after_the_cutoff_is_unusable_with_no_fallback` |
| RDR-03 | PASS | 3: `test_rdr03_a_binding_to_another_contract_is_refused`, `test_rdr03_a_capability_head_that_is_not_unique_at_the_cutoff_is_refused`, `test_rdr03_a_missing_binding_is_refused_like_the_verifier_refuses_it` |
| INV-01 | PASS | 1: `test_inv01_and_pit06_invalidating_the_current_head_changes_only_cutoffs_after_t3_inv` |
| INV-02 | PASS | 1: `test_inv02_invalidating_a_superseded_record_writes_no_pit_record_and_changes_no_cutoff` |
| INV-03 | PASS | 4: `test_inv03_a_response_document_is_not_an_invalidation_document`, `test_inv03_a_tampered_ledger_row_fails_verification`, `test_inv03_a_wrong_target_hash_or_pit_record_fails_verification` ... |
| INV-04 | PASS | 3: `test_inv04_a_failed_derivation_check_invalidates_the_head_automatically`, `test_inv04_a_later_genuine_capture_supersedes_the_invalidated_head`, `test_inv04_a_t_inv_equal_to_the_latest_valid_from_is_read_again_until_strictly_later` |


## S7: the dormant live path, proven only against loopback and fixtures

| Property | Evidence |
| --- | --- |
| No test contacts anything but 127.0.0.1 | the audit hook in `adapter_tests/__init__.py` refuses every other `connect`/`getaddrinfo`; `test_no_test_contacted_a_non_loopback_address` runs last; the hook's self-test provokes and clears two refusals (TEST-NET-1 address, `.invalid` name) |
| Transport exception boundary (design 7.7) | TX-01 subprocess cases: ordinary failures at connect/write/read headers/read body/header decode become sanitized `NO_RESPONSE`/`TRUNCATED` rows (class + errno only); `KeyboardInterrupt` exits with the platform SIGINT status and `SystemExit` keeps 37 / 1 (text dropped) / 0, each a fresh instance with no cause, context, notes or keyed frame locals; stdout, stderr and every runtime file are clean of the key in every section-7.6 form |
| TLS and host pinning | verification cannot be switched off (constructor refusal); the server name and `Host` header are always the pinned host; the loopback server holds a certificate for `api.oddspapi.io` from a throwaway test CA; 3xx is a status, never followed |
| Hard deadline (BND-04) | nothing written at or after `Tq + request_timeout_seconds`; a slow server is cut at exactly the deadline (sequence clock) |
| `T0 < T1` on a coarse clock | coarse-clock and stuck-clock transport tests; the end-to-end CLI run on the real clock |
| End-to-end operator `run` (G2-shaped, loopback) | one keyed request on the wire (key only in the query string on the wire), `RESPONSE` row, raw evidence stored, provider-reported usage recorded, no PIT/normalized output, no key anywhere under the runtime root |
| Gates (G-01..G-04, CLK-02) | refusals for each missing element; only pinned hashes, at most `max_calls`, inside the window; G2R pins derivation and policy separately; READY only via `approve-ready` after a G3 record, interactively; 401/403 blocks every market-book source |
| Credential (design 7.5) | outside repo and runtime root, owner-only ACL, one LF line, single name, the checked file is the file read, fingerprint pinned, never in the environment |
| Mutation smoke (`S7/MUTATION.txt`) | 57 mutants over `transport_http`, `credential`, `authority`, `scheduler`, `cli`: 56 killed, 1 equivalent (explained in the file) |

## Audit-oracle requirements (A-1 .. A-5)

| Item | How it is met | Evidence |
| --- | --- | --- |
| A-1 frozen byte provenance / CRLF | The guard compares loaded bytes with the frozen Git blobs and fails closed on a CRLF checkout; it never normalizes. The LF requirement is documented in `adapters/README.md`. | S0 FRZ-09 tests, every `GUARDS.txt` |
| A-2 frozen `request_id` idempotence | `acq_sent` is durable before the transport is called; reconciliation records `send_state` `NOT_SENT` / `MAY_HAVE_BEEN_SENT`; an orphan is never re-sent or re-debited under its identity; a retry is a new attempt with a new `request_id` and a new debit; the frozen ledger's `RegistryConflict` on reuse halts. | S2 `test_a2_*`, `test_q06_*`, S6 `test_a3_a_crash_inside_the_acquisition_*` |
| A-3 crash after a durable append | Every emission step is idempotent: existing artifacts are verified by identity and content and reused, a differing one halts (F-32/F-33), identity rows are applied last, `T2`/`T3` are never reused. Tested by crashing after EVERY checkpoint (emission, invalidation, raw capture) and resuming. | S5 `test_v05_emit_crash`, `test_a3_*` in S3/S5/S6 |
| A-4 PIT head selection | `admissible_head` picks the unique max-`valid_from` admissible record itself (the frozen `as_of_query` result is ordered by `record_id`); a tie is `AMBIGUOUS`; a head that fails any parity check is refused without falling back; an expired newer capture blocks an older price (`STALE`). | S5 `HeadSelectionTests`, PIT-03, RDR-02 |
| A-5 verifier parity | Differential tests publish manifests through the frozen `FeatureInputManifestStore` and call the frozen `verify_for_pack` (public interfaces only) for every candidate record on a cutoff grid; usable ⇔ verifier-accepted, except documented stricter adapter-only refusals. | S5 `test_a5_*`, S6 RDR-01 grid, EV-05/EV-06 |

## F-44 (not taken as authority)

The c8dfafd taxonomy has no row for "a valid response whose immutable raw-evidence publication fails for a
reason other than an immutability or identity conflict". Existing coverage: F-32 (`EVIDENCE_CONFLICT`) covers
publication refused by the frozen store for an immutability/identity conflict — halt, `QUARANTINED /
ARTIFACT_TAMPERED`, existing bytes untouched (S3 and S6 tests). Current behaviour for a plain I/O failure
(e.g. a full disk) during raw publication: the exception propagates out of `acquire` (nothing is swallowed,
no taxonomy code is invented); the durable state is `planned, quota_decided, sent` with the Genesis debit
standing; on restart the attempt is reconciled `ORPHANED_RESERVATION` / `MAY_HAVE_BEEN_SENT` (F-35), is never
re-sent, and a retry needs a fresh identity and debit (test `test_f44_gap_a_plain_io_failure_while_publishing_is_a_crash_and_never_a_verdict`).
Minimal additive proposal (not implemented): a detail code such as `RAW_PUBLISH_FAILED` mapped to
`MISSING_EVIDENCE`, recorded as a `completed` row with `failure` set before the exception is re-raised, and
a halt, with tests for the row, the coverage entry and the restart path. It needs no frozen change.

## Deviations and interpretations (each justified; none weakens an invariant)

1. RED timing: production code for S2–S7 was drafted before each RED run and held outside the repository
   during the run, so every RED transcript reflects the previous stage's tree exactly.
2. Boundability evaluator (design 20.1): the design's UTC-month example disagrees with the B1 formula, and
   the aligned-day fallback example (U=2) with the formal W⁺ count (3). The evaluator follows the formulas,
   i.e. the conservative reading; the table-driven BILL-05 test pins it.
3. Policy fields beyond the 12.1 list (`header_value_max_chars`, `read_chunk_bytes`,
   `max_decompression_ratio`, `secret_fragment_min_chars_floor/_divisor`, `declared_bookmakers_max`): every
   bound the code uses is a digested policy field (FRZ-10), so each extra field is inside `policy_digest`.
4. Metadata cache: only an HTTP 200 response that passed every content check (skew, content type, strict
   JSON, closed envelope) is published to the verified cache; design 11.1 lists the publish before those
   checks. Stricter: a response that is later rejected can never answer a request for 0 units.
5. Reconciliation rows carry `send_state`, and the retry policy has an `ORPHANED` input (A-2).
6. Status map: a bookmaker-level allowlist for `bookmakerIsActive` (true → ACTIVE; false → the bookmaker's
   books SUSPENDED; anything else → BLOCKED `UNKNOWN_MARKET_STATUS`). The design lists event/market/outcome
   levels; the field is a status field in a closed semantic structure, so it had to be allowlisted.
7. ODDS closed schema: `startTime` optional (the design 8.3 fixture join exists for exactly this case) and
   `price` nullable (design 10 rule 5 makes a missing price on an active outcome a contradiction, not drift).
8. Reader: two stricter adapter-only refusals beyond design 12.3 step 7 — `STALE` when a newer capture known
   at `D` has already expired (only possible when the kickoff moved earlier; falling back would present an
   older price after newer information), and a unique-observation requirement for the head's artifact.
9. Expected scope: computed as of `Tq` from the append-only PIT log when the response is normalized (and on
   resume), then pinned by hash. Records appended after `Tq` have `ready_at > Tq`, so the set is identical to
   one computed before sending.
10. `complete_hint` is always `True` in the pipeline: no provider completeness flag is known before G2;
    partiality is detected from missing required lists.
11. F-37 / Q-09: the provider usage header is provisionally `x-requests-used`, read as a UTC-month count
    (design 21 A12: verified at G2). Implemented at S6 because FM-37 needs it.
12. Gate bounds (G2: at most 5 requests and 72 hours; G2R: at most 35 days) live in the pinned
    `config/oddspapi_gate_limits.json` (FRZ-10 forbids literal bounds); it is not part of `derivation_version`
    because gates do not change derivations.
13. The CLI is `genesis_adapters/cli.py` (the S0 static scanner pins `CLI_MODULE = "cli.py"`); design 4 draws
    it under `oddspapi/`. The CLI has one command beyond the design's list, `reset`, the only writer of the
    ledger's existing `acq_operator_reset` row (interactive, operator only). G-03 says READY comes "via
    `cli.py approve`"; the READY write is its own interactive subcommand, `approve-ready`, which refuses without
    a matching G3 record, so the command that appends gate records never touches the capability registry.
14. G2 mode is raw capture only (design 16.3: no normalization emitted operationally).
15. The live-send check is one named gate (`LIVE_SEND`) evaluated by `LiveGate`: G1 with the loaded key's
    fingerprint, a time-sync attestation, and G2 (pinned hashes, call budget, window) or G2R (running
    `derivation_version` and `policy_digest`).
16. Tests that need the real UTC clock outside the day/month guard zone (TX-01, the loopback CLI run, live-gate
    tests) skip for the ~5 minutes per day when it is inside. The real-symlink credential test skips where the
    account cannot create symbolic links (this Windows account cannot); a second test feeds the loader what
    `os.lstat` reports for a link, so that branch runs on every platform.
17. The HTTPS transport stops reading one byte past `max_response_bytes` (raw capture then flags
    `OVERSIZE_BODY`), treats `http.client` returning no data before `Content-Length` as a truncation, and stops
    as soon as `http.client` reports the response complete (it may close the socket at that point).
18. `T0 < T1` on a coarse wall clock (design 6.3). On this machine (Windows, Python 3.12) `time.time_ns()` ticks
    every 1–16 ms, so a fast exchange can read T1 equal to T0 and the runner's ordering check would halt with
    `CLOCK_FAULT`. The transport re-reads the trusted clock, sleeping one reported clock tick at a time
    (`time.get_clock_info("time").resolution`, no literal: FRZ-10), until it moves past T0, bounded by the
    policy's wall/monotonic drift budget. Every T1 is still a genuine reading taken after the last byte; the
    clock itself is unchanged (CLK-01 still allows equal consecutive reads); a clock that does not move is
    returned as read and the runner halts on it. The test `FakeTransport`, when driven by the real clock, waits
    for a later tick in the same way.
19. Credential file (design 7.5, "anything else is refused"), read strictly: one line ended by a single LF or
    by nothing (a CRLF ending is refused as `CREDENTIAL_MISSING` rather than guessed at); a file with a second
    hard-link name is refused (that name could lie inside the repository); the bytes are read from the very
    file that was checked (same device and file id), so a swap between the checks and the read is refused.
20. A loopback end-to-end test runs the operator CLI's `run` through the real HTTPS transport to an in-process
    server (synthetic gate records in a scratch directory, the throwaway test CA, 127.0.0.1 only). It is not the
    G2 smoke: nothing contacts the provider, and the pinned production host is never resolved.
21. G-03 is tested by driving `approve-ready` after a synthetic G3 record in a throwaway scratch registry; a
    `READY` row exists only there, for the duration of that test. No capability anywhere else is `READY`.
22. Tests added during S7 GREEN hardening (after `S7/RED.txt`): the complete-body/chunking, coarse-clock and
    stuck-clock transport tests, the loopback CLI run, the swap/hard-link/stand-in-repository/simulated-link
    credential tests, the gate-window, bound and `sent_counter` authority tests, and the test-CA refusal CLI
    test. Each targets S7 code, and `S7/MUTATION.txt` shows the mutants they were written to kill.
23. `S7/FROZEN.txt` wall time (11144 s) includes a long pause of the host (most likely a sleep) between
    ~15:51Z and ~18:46Z, noted at the top of the file; the counts and results equal the S0 baseline.
24. `adapter_tests/fixtures/tls/server.key` is a committed private key: test-only, for the loopback server's
    certificate from the throwaway CA (whose own key no longer exists). It grants nothing outside a client that
    injects `test-ca.pem`, but a repository secret scanner may flag it on push.
