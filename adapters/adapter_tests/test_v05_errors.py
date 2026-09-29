"""FM-00: AdapterFailure -> frozen ReasonCode mapping is total and single-valued."""

from __future__ import annotations

import unittest

from genesis.reasons import ReasonCode

from genesis_adapters import errors as err

# Every detail code named in design section 15 (F-01 .. F-43, incl. F-11b) plus the reader,
# invalidation and quota codes named elsewhere in the design.
SECTION_15_CODES = {
    "GATE_MISSING", "CIRCUIT_OPEN", "LIVE_CLOCK_REQUIRED", "TEST_POLICY_IN_LIVE", "QUOTA_BLOCKED",
    "CLOCK_FAULT", "CREDENTIAL_MISSING", "CREDENTIAL_PERMISSIONS", "CREDENTIAL_FINGERPRINT_MISMATCH",
    "NO_RESPONSE", "TRUNCATED_BODY", "OVERSIZE_BODY", "REDIRECT_REFUSED", "AUTH_REJECTED",
    "RATE_LIMITED", "PROVIDER_ERROR", "SECRET_ECHO", "UNINSPECTABLE_BODY", "CLOCK_SKEW",
    "NOT_JSON", "INVALID_UTF8", "DUPLICATE_KEYS", "NONFINITE_NUMBER", "WRONG_CONTENT_TYPE",
    "ENVELOPE_SCHEMA_MISMATCH", "PARTIAL_RESPONSE", "OUT_OF_SCOPE_COMPETITION",
    "OUT_OF_SCOPE_BOOKMAKER", "OUT_OF_SCOPE_MARKET", "OUT_OF_SCOPE_LINE", "LINE_UNIDENTIFIED",
    "CONTRADICTORY_DUPLICATE", "INCOMPLETE_SELECTIONS", "UNMAPPED_OUTCOME", "INVALID_PRICE",
    "PRICE_INCOHERENT", "IDENTITY_CONFLICT", "PARTICIPANT_AMBIGUOUS", "UNKNOWN_EVENT_STATUS",
    "UNKNOWN_MARKET_STATUS", "UNKNOWN_OUTCOME_STATUS", "CONTRADICTORY_STATUS", "MARKET_SUSPENDED",
    "OUTCOME_INACTIVE", "EVENT_NOT_PREMATCH", "PREMATCH_WINDOW_CLOSED", "TIMESTAMP_NAIVE",
    "TIMESTAMP_NON_UTC", "TIMESTAMP_INVALID", "TIMESTAMP_FUTURE", "EVENT_START_INVALID",
    "EVENT_METADATA_STALE", "BOOK_ABSENT", "CONFIG_DIGEST_MISMATCH", "EVIDENCE_CONFLICT",
    "PIT_APPEND_CONFLICT", "CACHE_MISS", "ORPHANED_RESERVATION", "DATA_CAPABILITY_NOT_READY",
    "AMBIGUOUS_SOURCE", "QUOTA_DIVERGENCE", "SCHEMA_DRIFT", "NOT_PUBLISHED_AT_CUTOFF",
    "PARITY_FAILURE", "INVALIDATED", "MODULE_PROVENANCE", "QUOTA_REPLAY_BROKEN",
    "WINDOW_BOUNDARY_GUARD", "MISSING_OR_STALE", "STALE", "AMBIGUOUS", "DERIVATION_UNVERIFIED",
    "PROVIDER_ERROR_NOTICE", "OPERATOR_INVALIDATION", "SUSPENDED", "ABSENT", "BLOCKED",
}


class MappingTests(unittest.TestCase):
    def test_fm00_mapping_is_total_and_single_valued(self):
        members = {m.name for m in err.AdapterFailure}
        self.assertEqual(set(err.REASON_CODE_MAP), members)
        for failure in err.AdapterFailure:
            code = err.REASON_CODE_MAP[failure]
            self.assertIsInstance(code, ReasonCode, failure.name)
            self.assertEqual(err.reason_code(failure), code)
            self.assertEqual(err.reason_code(failure.value), code)
        # every enum value equals its name (stable, greppable codes)
        for failure in err.AdapterFailure:
            self.assertEqual(failure.value, failure.name)

    def test_fm00_every_section_15_code_is_enumerated(self):
        self.assertLessEqual(SECTION_15_CODES, {m.name for m in err.AdapterFailure})

    def test_fm00_specific_coverage_reason_codes_from_the_design_table(self):
        expected = {
            "QUOTA_BLOCKED": ReasonCode.ATTEMPT_BUDGET_EXHAUSTED,
            "RATE_LIMITED": ReasonCode.ATTEMPT_BUDGET_EXHAUSTED,
            "WINDOW_BOUNDARY_GUARD": ReasonCode.ATTEMPT_BUDGET_EXHAUSTED,
            "SECRET_ECHO": ReasonCode.ARTIFACT_TAMPERED,
            "UNINSPECTABLE_BODY": ReasonCode.SCHEMA_REJECTED,
            "CLOCK_SKEW": ReasonCode.CRITICAL_UNCERTAINTY,
            "IDENTITY_CONFLICT": ReasonCode.AMBIGUOUS_IDENTITY,
            "PARTICIPANT_AMBIGUOUS": ReasonCode.AMBIGUOUS_IDENTITY,
            "CONTRADICTORY_STATUS": ReasonCode.CONTRADICTORY_EVIDENCE,
            "EVENT_NOT_PREMATCH": ReasonCode.EXPIRED,
            "PREMATCH_WINDOW_CLOSED": ReasonCode.EXPIRED,
            "EVENT_METADATA_STALE": ReasonCode.STALE_EVIDENCE,
            "SCHEMA_DRIFT": ReasonCode.SCHEMA_REJECTED,
            "QUOTA_REPLAY_BROKEN": ReasonCode.ARTIFACT_TAMPERED,
            "OUT_OF_SCOPE_COMPETITION": ReasonCode.UNSUPPORTED_MARKET,
            "INVALID_PRICE": ReasonCode.PRICE_SANITY_FAILED,
            "PRICE_INCOHERENT": ReasonCode.CONTRADICTORY_EVIDENCE,
            "NO_RESPONSE": ReasonCode.MISSING_EVIDENCE,
            "PARTIAL_RESPONSE": ReasonCode.MISSING_EVIDENCE,
            "REDIRECT_REFUSED": ReasonCode.SOURCE_CONTRACT_VIOLATION,
            "AUTH_REJECTED": ReasonCode.CONFIGURATION_MISMATCH,
            "MODULE_PROVENANCE": ReasonCode.CONFIGURATION_MISMATCH,
            "QUOTA_DIVERGENCE": ReasonCode.CONFIGURATION_MISMATCH,
        }
        for name, code in expected.items():
            self.assertEqual(err.REASON_CODE_MAP[err.AdapterFailure[name]], code, name)

    def test_unknown_codes_are_refused(self):
        with self.assertRaises(KeyError):
            err.reason_code("NOT_A_CODE")

    def test_unusable_to_pass_mapping_for_reader_results(self):
        from genesis.reasons import ReasonCode as R
        self.assertEqual(err.pass_reason("STALE"), R.PASS_STALE_EVIDENCE)
        self.assertEqual(err.pass_reason("MISSING_OR_STALE"), R.PASS_STALE_EVIDENCE)
        self.assertEqual(err.pass_reason("DATA_CAPABILITY_NOT_READY"), R.PASS_DATA_CAPABILITY_NOT_READY)
        self.assertEqual(err.pass_reason("AMBIGUOUS_SOURCE"), R.PASS_DATA_CAPABILITY_NOT_READY)
        for name in ("SUSPENDED", "ABSENT", "BLOCKED", "INVALIDATED", "AMBIGUOUS",
                     "NOT_PUBLISHED_AT_CUTOFF", "PARITY_FAILURE", "PREMATCH_WINDOW_CLOSED",
                     "DERIVATION_UNVERIFIED"):
            self.assertIsInstance(err.pass_reason(name), ReasonCode, name)
            self.assertTrue(err.pass_reason(name).value.startswith("PASS_"), name)


if __name__ == "__main__":
    unittest.main()
