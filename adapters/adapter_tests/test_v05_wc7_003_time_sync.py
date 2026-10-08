"""WC7-003: the Windows live time-sync attestation follows the ratified design 6.1 rule.

Healthy only when ``w32tm /query /status`` exits 0, Leap Indicator is exactly 0, Stratum is greater than 0, and
Source is present and is neither Local CMOS Clock nor Free-running System Clock. Missing, repeated or unparseable
required fields fail closed. ``time_sync_attestation`` itself is never mocked: these tests feed synthetic or captured
``w32tm`` text through the real code path, and only ``subprocess.run`` and the platform check are patched. No test
touches the host clock or the network.
"""

from __future__ import annotations

import unittest
from unittest import mock

from genesis_adapters import cli

# Captured on the certified Windows host, 2026-10-08 (cert/v05-r7-windows, W05_post_session_gate_2026-10-08.txt).
CAPTURED_UNSYNCHRONIZED = (
    "Leap Indicator: 3(not synchronized)\n"
    "Stratum: 0 (unspecified)\n"
    "Precision: -23 (119.209ns per tick)\n"
    "Root Delay: 0.0230632s\n"
    "Root Dispersion: 8.2903772s\n"
    "ReferenceId: 0x00000000 (unspecified)\n"
    "Last Successful Sync Time: 07/10/2026 22:06:30\n"
    "Source: time.windows.com,0x9 \n"
    "Poll Interval: 10 (1024s)\n"
)


def w32tm_status(leap="0 (no warning)", stratum="3 (secondary reference - syncd by (S)NTP)",
                 source="time.windows.com,0x9", last_sync="08/10/2026 09:15:00", omit=(), extra=()):
    """Synthetic ``w32tm /query /status`` text in the real layout. ``omit`` drops a label; ``extra`` appends lines."""

    lines = {
        "Leap Indicator": f"Leap Indicator: {leap}",
        "Stratum": f"Stratum: {stratum}",
        "Precision": "Precision: -23 (119.209ns per tick)",
        "Root Delay": "Root Delay: 0.0312500s",
        "Root Dispersion": "Root Dispersion: 10.0000000s",
        "Last Successful Sync Time": f"Last Successful Sync Time: {last_sync}",
        "Source": f"Source: {source}",
        "Poll Interval": "Poll Interval: 10 (1024s)",
    }
    body = [text for label, text in lines.items() if label not in omit]
    return "\n".join(body + list(extra)) + "\n"


class WindowsAttestationRule(unittest.TestCase):
    """Direct calls to the Windows attestation function, with synthetic or captured output."""

    def attest(self, stdout, returncode=0):
        return cli.windows_time_sync_attestation(returncode, stdout)

    def test_healthy_output_is_synchronized(self):
        result = self.attest(w32tm_status())
        self.assertIs(result["synchronized"], True)
        self.assertEqual(result["method"], "w32tm")
        self.assertEqual(result["source"], "time.windows.com,0x9")
        self.assertEqual(result["leap_indicator"], 0)
        self.assertEqual(result["stratum"], 3)
        self.assertEqual(result["last_successful_sync"], "08/10/2026 09:15:00")

    def test_captured_unsynchronized_host_output_is_refused(self):
        result = self.attest(CAPTURED_UNSYNCHRONIZED)
        self.assertIs(result["synchronized"], False)
        self.assertEqual(result["leap_indicator"], 3)
        self.assertEqual(result["stratum"], 0)
        self.assertEqual(result["source"], "time.windows.com,0x9")
        self.assertEqual(result["last_successful_sync"], "07/10/2026 22:06:30")

    def test_leap_indicator_3_is_refused_even_with_a_positive_stratum(self):
        self.assertIs(self.attest(w32tm_status(leap="3(not synchronized)"))["synchronized"], False)

    def test_stratum_0_is_refused(self):
        self.assertIs(self.attest(w32tm_status(stratum="0 (unspecified)"))["synchronized"], False)

    def test_local_cmos_clock_source_is_refused(self):
        self.assertIs(self.attest(w32tm_status(source="Local CMOS Clock"))["synchronized"], False)

    def test_free_running_system_clock_source_is_refused(self):
        self.assertIs(self.attest(w32tm_status(source="Free-running System Clock"))["synchronized"], False)

    def test_unsynchronized_source_names_are_refused_regardless_of_case(self):
        self.assertIs(self.attest(w32tm_status(source="LOCAL cmos CLOCK"))["synchronized"], False)
        self.assertIs(self.attest(w32tm_status(source="free-running system clock"))["synchronized"], False)

    def test_missing_source_is_refused(self):
        result = self.attest(w32tm_status(omit=("Source",)))
        self.assertIs(result["synchronized"], False)
        self.assertEqual(result["source"], "")

    def test_empty_source_is_refused(self):
        self.assertIs(self.attest(w32tm_status(source=""))["synchronized"], False)

    def test_missing_leap_indicator_is_refused(self):
        result = self.attest(w32tm_status(omit=("Leap Indicator",)))
        self.assertIs(result["synchronized"], False)
        self.assertIsNone(result["leap_indicator"])

    def test_missing_stratum_is_refused(self):
        result = self.attest(w32tm_status(omit=("Stratum",)))
        self.assertIs(result["synchronized"], False)
        self.assertIsNone(result["stratum"])

    def test_malformed_leap_value_is_refused(self):
        for leap in ("zero", "0x0", "", "-0"):
            with self.subTest(leap=leap):
                result = self.attest(w32tm_status(leap=leap))
                self.assertIs(result["synchronized"], False)
                self.assertIsNone(result["leap_indicator"])

    def test_malformed_stratum_value_is_refused(self):
        for stratum in ("three", "3x", "", "-1"):
            with self.subTest(stratum=stratum):
                result = self.attest(w32tm_status(stratum=stratum))
                self.assertIs(result["synchronized"], False)
                self.assertIsNone(result["stratum"])

    def test_non_zero_w32tm_exit_is_refused_even_with_healthy_fields(self):
        self.assertIs(self.attest(w32tm_status(), returncode=1)["synchronized"], False)

    def test_contradictory_repeated_required_field_is_refused(self):
        self.assertIs(self.attest(w32tm_status(extra=("Leap Indicator: 3(not synchronized)",)))["synchronized"],
                      False)
        self.assertIs(self.attest(w32tm_status(extra=("Source: Local CMOS Clock",)))["synchronized"], False)
        self.assertIs(self.attest(w32tm_status(extra=("Stratum: 2 (secondary)",)))["synchronized"], False)

    def test_repeated_required_field_with_identical_value_is_still_refused(self):
        self.assertIs(self.attest(w32tm_status(extra=("Stratum: 3 (secondary reference)",)))["synchronized"], False)

    def test_last_successful_sync_is_recorded_but_not_gated(self):
        result = self.attest(w32tm_status(last_sync="01/01/2020 00:00:00"))
        self.assertIs(result["synchronized"], True)
        self.assertEqual(result["last_successful_sync"], "01/01/2020 00:00:00")

    def test_missing_last_successful_sync_does_not_by_itself_refuse(self):
        result = self.attest(w32tm_status(omit=("Last Successful Sync Time",)))
        self.assertIs(result["synchronized"], True)
        self.assertIsNone(result["last_successful_sync"])

    def test_no_output_at_all_is_refused(self):
        self.assertIs(self.attest("")["synchronized"], False)


class WindowsAttestationThroughTheCli(unittest.TestCase):
    """``time_sync_attestation`` runs unmodified; only the platform check and ``subprocess.run`` are patched."""

    def run_on_windows(self, stdout, returncode=0):
        completed = mock.Mock(returncode=returncode, stdout=stdout, stderr="")
        with mock.patch.object(cli.sys, "platform", "win32"), \
                mock.patch("subprocess.run", return_value=completed) as run:
            result = cli.time_sync_attestation()
        self.assertEqual(run.call_args.args[0], ["w32tm", "/query", "/status"])
        return result

    def test_healthy_host_is_synchronized(self):
        self.assertIs(self.run_on_windows(w32tm_status())["synchronized"], True)

    def test_captured_unsynchronized_host_is_refused(self):
        result = self.run_on_windows(CAPTURED_UNSYNCHRONIZED)
        self.assertIs(result["synchronized"], False)
        self.assertEqual(result["leap_indicator"], 3)

    def test_non_zero_exit_is_refused(self):
        self.assertIs(self.run_on_windows(w32tm_status(), returncode=1)["synchronized"], False)


if __name__ == "__main__":
    unittest.main()
