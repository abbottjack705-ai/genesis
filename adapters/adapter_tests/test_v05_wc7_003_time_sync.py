"""WC7-003: the Windows live time-sync attestation follows the ratified design 6.1 rule.

Healthy only when ``w32tm /query /status`` exits 0, Leap Indicator is exactly 0, Stratum is 1 through 15, and
Source is present and is neither Local CMOS Clock nor Free-running System Clock. Missing, repeated, malformed or
contradictory required fields fail closed. ``time_sync_attestation`` itself is never mocked: these tests feed synthetic
or captured ``w32tm`` text through the real code path, and only ``subprocess.run`` and the platform check are patched.
The transport tests run that output through the real LiveGate and acquisition runner in G2 and G2R, with a fake
transport. No test touches the host clock or the network.
"""

from __future__ import annotations

import unittest
from datetime import timedelta
from unittest import mock

from genesis_adapters import cli
from genesis_adapters.oddspapi import authority as auth

from . import test_v05_authority as authority_tests
from .pipeline_support import odds_item, open_rt
from .support import scratch_root

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


# The base status of Codex's R2 reproducers: otherwise healthy, with plain Leap Indicator and Stratum values.
CODEX_BASE = "Leap Indicator: 0\nStratum: 3\nSource: time.windows.com,0x9\n"

# Human checkpoint: every field label must be printable ASCII before any case folding. These cases sit beside valid
# required fields, so ignoring the malformed label would incorrectly authorize a send. The rule also applies to
# unrelated and evidence-only fields, and to surrounding label whitespace.
INVALID_LABEL_CHARACTERS = {
    "Kelvin sign": "\u212a", "long s": "\u017f", "zero-width space": "\u200b", "zero-width joiner": "\u200d",
    "no-break space": "\u00a0", "thin space": "\u2009", "combining mark": "\u0301", "Cyrillic letter": "\u0430",
    "NUL": "\x00", "tab": "\t", "vertical tab": "\v", "form feed": "\f", "carriage return": "\r",
    "escape": "\x1b", "DEL": "\x7f",
}
MALFORMED_LABEL_STATUS = {}
for _label, _prefix, _suffix, _value in (("Stratum", "Stra", "tum", "16"),
                                        ("Source", "Sou", "rce", "Local CMOS Clock"),
                                        ("Leap Indicator", "Le", "ap Indicator", "3")):
    for _name, _character in INVALID_LABEL_CHARACTERS.items():
        MALFORMED_LABEL_STATUS[f"label: {_label} with {_name}"] = w32tm_status(
            extra=(f"{_prefix}{_character}{_suffix}: {_value}",))
for _name, _line in {
    "Stratum homoglyph": "Str\u0430tum: 16", "Source homoglyph": "S\u043eurce: Local CMOS Clock",
    "Leap homoglyph": "L\u0435ap Indicator: 3", "full-width Stratum": "\uff33tratum: 16",
    "unrelated Unicode": "Time \u212aSource: w32time", "unrelated NUL": "Precision\x00: -23",
    "unrelated control": "Poll\tInterval: 10", "unrelated DEL": "Root\x7f Delay: 0.03125s",
    "evidence-only Unicode": "Last Successful Sync\u200b Time: 01/01/2020 00:00:00",
    "evidence-only control": "Last Successful Sync\x00 Time: 01/01/2020 00:00:00",
    "leading tab": "\tStratum: 16", "trailing tab": "Stratum\t: 16",
    "leading Unicode whitespace": "\u00a0Source: Local CMOS Clock",
    "invalid unrelated label without a separator": "Prec\u212aision -23",
    "invalid required label without a separator": "Stra\u212atum 16",
    "invalid label with equals separator": "Stra\u212atum=16",
}.items():
    MALFORMED_LABEL_STATUS["label: " + _name] = w32tm_status(extra=(_line,))
for _code in (*range(10), *range(11, 32), 127):
    MALFORMED_LABEL_STATUS[f"label: unrelated ASCII control {_code}"] = w32tm_status(
        extra=(f"Preci{chr(_code)}sion: -23",))

# R3-001: the contradiction phrases, with separators that the Stratum note grammar admits. Every generated note is
# grammar-valid, so each one reaches the semantic check and must be refused.
CONTRADICTION_PHRASES = (("not", "synchronized"), ("not", "synchronised"), ("un", "synchronized"),
                         ("un", "synchronised"), ("un", "specified"))
PLAIN_SEPARATORS = (" ", "  ", "   ", "-", " - ", ".", "/")
WRAPPED_FORMS = ("{a} ({b})", "{a}({b})", "{a}/({b})", "({a}) {b}", "({a})({b})", "({a}) ({b})", "({a})-({b})")
CASE_VARIANTS = ("UNSYNCHRONIZED", "Not Synchronized", "NOT-SYNCHRONISED", "Un-Specified", "un (SYNCHRONIZED)")


def contradictory_notes():
    """Grammar-valid Stratum notes that contain a contradiction phrase: each phrase is cut at every interior position and
    joined by each representative separator, and also appears in parenthesised forms and case variants."""

    notes = set(CASE_VARIANTS)
    for first, second in CONTRADICTION_PHRASES:
        phrase = first + second
        for cut in range(1, len(phrase)):
            for separator in PLAIN_SEPARATORS:
                notes.add(phrase[:cut] + separator + phrase[cut:])
        for form in WRAPPED_FORMS:
            notes.add(form.format(a=first, b=second))
    return sorted(notes)

# Every malformed, contradictory or forbidden required-field case, and the captured unsynchronized host output. Each
# must refuse, and none may reach the transport.
MALFORMED_STATUS = {
    "leap: trailing garbage": w32tm_status(leap="0 garbage"),
    "leap: truncated annotation": w32tm_status(leap="0("),
    "leap: contradictory annotation": w32tm_status(leap="0(not synchronized)"),
    "leap: stray number": w32tm_status(leap="0 3"),
    "leap: unbalanced note": w32tm_status(leap="0 (no warn"),
    "leap: tab, NUL and junk": w32tm_status(leap="0\t\x00junk"),
    "leap: Arabic-Indic digit": w32tm_status(leap="\u0660"),
    "leap: 5000 digits": w32tm_status(leap="0" * 5000),
    "leap: duplicate": w32tm_status(extra=("Leap Indicator: 0",)),
    "leap: contradictory duplicate": w32tm_status(extra=("Leap Indicator = 3",)),
    "leap: near-miss label only": w32tm_status(omit=("Leap Indicator",), extra=("Leap\tIndicator: 0",)),
    "stratum: trailing garbage": w32tm_status(stratum="3 garbage"),
    "stratum: trailing number": w32tm_status(stratum="3 0"),
    "stratum: negative": w32tm_status(stratum="-1"),
    "stratum: empty": w32tm_status(stratum=""),
    "stratum: 5000 digits": w32tm_status(stratum="9" * 5000),
    "stratum: beyond the 8-bit field": w32tm_status(stratum="256"),
    "stratum: contradictory note": w32tm_status(stratum="3 (unsynchronized)"),
    "stratum: contradictory duplicate": w32tm_status(extra=("Stratum: 0",)),
    "stratum: contradictory note, two spaces (R2-001)": w32tm_status(stratum="3 (not  synchronized)"),
    "stratum: contradictory note, three spaces": w32tm_status(stratum="3 (not   synchronized)"),
    "stratum: contradictory note, no space": w32tm_status(stratum="3 (notsynchronized)"),
    "stratum: contradictory note, space inside the word": w32tm_status(stratum="3 (not synchro nized)"),
    "stratum: contradictory note, padded with spaces": w32tm_status(stratum="3 ( not  synchronized )"),
    "stratum: contradictory note, upper case and spaces": w32tm_status(stratum="3 (NOT  SYNCHRONIZED)"),
    "stratum: contradictory note, British spelling": w32tm_status(stratum="3 (not synchronised)"),
    "stratum: unsynchronised with a space": w32tm_status(stratum="3 (un synchronised)"),
    "stratum: unspecified with spaces": w32tm_status(stratum="3 (un  specified)"),
    "stratum: tab inside a contradictory note": w32tm_status(stratum="3 (not\tsynchronized)"),
    "stratum: two spaces before the note": w32tm_status(stratum="3  (not synchronized)"),
    "R2-001 literal reproducer": CODEX_BASE.replace("Stratum: 3", "Stratum: 3 (not  synchronized)"),
    "label: split Stratum beside a valid one (R2-002)": w32tm_status(extra=("Stra tum: 16",)),
    "label: split Leap beside a valid one (R2-002)": w32tm_status(extra=("Le ap Indicator: 3",)),
    "label: NUL inside Source beside a valid one (R2-002)": w32tm_status(extra=("Sou\x00rce: Local CMOS Clock",)),
    "label: colon inside Stratum": w32tm_status(extra=("Stra:tum: 16",)),
    "label: Stratum without a separator": w32tm_status(extra=("Stratum 16",)),
    "label: zero-width space inside Stratum": w32tm_status(extra=("Strat​um: 16",)),
    "label: no-break space inside Leap Indicator": w32tm_status(extra=("Leap Indicator: 3",)),
    "label: carriage return inside Stratum": w32tm_status(extra=("Stra\rtum: 16",)),
    "label: tab before the separator": w32tm_status(extra=("Source\t: Local CMOS Clock",)),
    "label: Stratum with a trailing letter": w32tm_status(extra=("Stratumx: 16",)),
    "R2-002 literal reproducer: split Stratum": CODEX_BASE + "Stra tum: 16\n",
    "R2-002 literal reproducer: NUL inside Source": CODEX_BASE + "Sou\x00rce: Local CMOS Clock\n",
    "R2-002 literal reproducer: split Leap": CODEX_BASE + "Le ap Indicator: 3\n",
    "R3-001 literal reproducer: parenthesised": CODEX_BASE.replace("Stratum: 3", "Stratum: 3 (not (synchronized))"),
    "R3-001 literal reproducer: hyphen": CODEX_BASE.replace("Stratum: 3", "Stratum: 3 (not-synchronized)"),
    "source: double space": w32tm_status(source="Local  CMOS Clock"),
    "source: tab": w32tm_status(source="Local\tCMOS Clock"),
    "source: Unicode whitespace": w32tm_status(source="Local\u00a0CMOS\u2009Clock"),
    "source: NUL": w32tm_status(source="Local CMOS Clock\x00"),
    "source: NUL only": w32tm_status(source="\x00"),
    "source: Free-running double space": w32tm_status(source="Free-running  System Clock"),
    "source: case and outer tab": w32tm_status(source=" \tLOCAL cmos CLOCK \t"),
    "source: duplicate with case variant": w32tm_status(extra=(" SOURCE : time.windows.com,0x9",)),
    "truncated before Source": "Leap Indicator: 0\nStratum: 3\nSour",
    "captured unsynchronized host output": CAPTURED_UNSYNCHRONIZED,
    "no output": "",
}
MALFORMED_STATUS.update(MALFORMED_LABEL_STATUS)


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


class WindowsNumericFieldGrammar(unittest.TestCase):
    """Leap Indicator and Stratum must match the whole w32tm numeric grammar; any other text fails closed."""

    def attest(self, stdout, returncode=0):
        return cli.windows_time_sync_attestation(returncode, stdout)

    def test_prefix_matches_and_trailing_text_are_refused(self):
        for leap in ("0 garbage", "0(", "0(not synchronized)", "0 3", "0 (no warn", "0\t\x00junk", "0 (no warning) x"):
            with self.subTest(leap=leap):
                self.assertIs(self.attest(w32tm_status(leap=leap))["synchronized"], False)
        for stratum in ("3 garbage", "3 0", "3(", "3 (secondary", "3 (x))", "3 (x)junk", "3 (()"):
            with self.subTest(stratum=stratum):
                self.assertIs(self.attest(w32tm_status(stratum=stratum))["synchronized"], False)

    def test_leading_garbage_signs_and_non_ascii_digits_are_refused(self):
        for leap in ("garbage 0", "+0", "00", "0x0", "\u0660", "\uff10"):
            with self.subTest(leap=leap):
                self.assertIs(self.attest(w32tm_status(leap=leap))["synchronized"], False)
        for stratum in ("garbage 3", "+3", "03", "-1", "\u0663"):
            with self.subTest(stratum=stratum):
                self.assertIs(self.attest(w32tm_status(stratum=stratum))["synchronized"], False)

    def test_contradictory_notes_are_refused(self):
        for leap in ("0(not synchronized)", "0 (unsynchronized)", "0 (unspecified)"):
            with self.subTest(leap=leap):
                self.assertIs(self.attest(w32tm_status(leap=leap))["synchronized"], False)
        for stratum in ("3(not synchronized)", "3 (unsynchronized)", "3 (unspecified)"):
            with self.subTest(stratum=stratum):
                self.assertIs(self.attest(w32tm_status(stratum=stratum))["synchronized"], False)

    def test_healthy_leap_zero_carries_no_note_or_the_no_warning_note(self):
        for leap in ("0", "0(no warning)", "0 (No Warning)"):
            with self.subTest(leap=leap):
                result = self.attest(w32tm_status(leap=leap))
                self.assertIs(result["synchronized"], True)
                self.assertEqual(result["leap_indicator"], 0)

    def test_stratum_1_to_15_is_healthy_with_any_note_that_does_not_claim_unsynchronized(self):
        for stratum in ("1", "15", "3", "1 (primary reference - syncd by radio clock)",
                        "3 (secondary reference - syncd by (S)NTP)"):
            with self.subTest(stratum=stratum):
                result = self.attest(w32tm_status(stratum=stratum))
                self.assertIs(result["synchronized"], True)
                self.assertTrue(1 <= result["stratum"] <= 15)

    def test_field_width_is_bounded_without_raising(self):
        # Leap is a 2-bit field and Stratum an 8-bit field; longer digit runs are malformed, not converted.
        for leap in ("4", "0" * 5000):
            with self.subTest(leap=leap):
                result = self.attest(w32tm_status(leap=leap))
                self.assertIs(result["synchronized"], False)
                self.assertIsNone(result["leap_indicator"])
        for stratum in ("256", "9" * 5000):
            with self.subTest(stratum=stratum):
                result = self.attest(w32tm_status(stratum=stratum))
                self.assertIs(result["synchronized"], False)
                self.assertIsNone(result["stratum"])

    def test_empty_numeric_fields_are_refused(self):
        self.assertIs(self.attest(w32tm_status(leap="", stratum=""))["synchronized"], False)
        self.assertIs(self.attest(w32tm_status(stratum=" "))["synchronized"], False)

    def test_duplicate_and_near_miss_required_labels_are_refused(self):
        for extra in ("Leap Indicator: 0", "Leap Indicator = 3", "Leap\tIndicator: 0", "Leap Indicator 0",
                      "Stratum: 0", "STRATUM= 3", "stratum: 3 (secondary reference)"):
            with self.subTest(extra=extra):
                self.assertIs(self.attest(w32tm_status(extra=(extra,)))["synchronized"], False)
        with self.subTest(near_miss_beside_a_valid_field=True):      # the valid Stratum is present, so it is a repeat
            self.assertIs(self.attest(w32tm_status(extra=("Stratum\x00: 3",)))["synchronized"], False)


class WindowsStratumRule(unittest.TestCase):
    """RFC 5905 strata, ratified by the project owner for WC7-003: only 1 through 15 is healthy. Parsing still reads any
    unsigned 8-bit value, so 0, 16, 17 and 255 are recognized and then refused."""

    def attest(self, stratum):
        return cli.windows_time_sync_attestation(0, w32tm_status(stratum=stratum))

    def test_stratum_1_is_potentially_healthy(self):
        result = self.attest("1")
        self.assertIs(result["synchronized"], True)
        self.assertEqual(result["stratum"], 1)

    def test_stratum_15_is_potentially_healthy(self):
        result = self.attest("15")
        self.assertIs(result["synchronized"], True)
        self.assertEqual(result["stratum"], 15)

    def test_stratum_16_is_refused_as_unsynchronized(self):
        result = self.attest("16")
        self.assertIs(result["synchronized"], False)
        self.assertEqual(result["stratum"], 16)

    def test_stratum_17_is_refused_as_reserved(self):
        result = self.attest("17")
        self.assertIs(result["synchronized"], False)
        self.assertEqual(result["stratum"], 17)

    def test_stratum_255_is_refused_as_reserved(self):
        result = self.attest("255")
        self.assertIs(result["synchronized"], False)
        self.assertEqual(result["stratum"], 255)

    def test_stratum_0_is_refused_as_unspecified(self):
        for stratum in ("0", "0 (unspecified)"):
            with self.subTest(stratum=stratum):
                result = self.attest(stratum)
                self.assertIs(result["synchronized"], False)
                self.assertEqual(result["stratum"], 0)

    def test_only_stratum_1_through_15_is_healthy_across_the_whole_8_bit_range(self):
        for value in range(256):
            with self.subTest(stratum=value):
                self.assertIs(self.attest(str(value))["synchronized"], 1 <= value <= 15)


class WindowsContradictoryAnnotationsAndCorruptedLabels(unittest.TestCase):
    """Codex R2-001 and R2-002: contradictory Stratum notes and corrupted required labels fail closed whatever their ASCII
    spacing or case. Unrelated lines that merely contain the same words stay ignored, and benign notes stay healthy."""

    def attest(self, stdout):
        return cli.windows_time_sync_attestation(0, stdout)

    def test_codex_r2_001_reproducer_is_refused(self):
        result = self.attest(CODEX_BASE.replace("Stratum: 3", "Stratum: 3 (not  synchronized)"))
        self.assertIs(result["synchronized"], False)
        self.assertEqual(result["stratum"], 3)               # parsed as evidence; the health decision is what is refused

    def test_contradictory_notes_are_refused_whatever_the_ascii_spacing_and_case(self):
        for note in ("not  synchronized", "not   synchronized", "notsynchronized", "not synchro nized",
                     " not  synchronized ", "NOT  SYNCHRONIZED", "not synchronised", "unsynchronised",
                     "un synchronized", "un  specified", "UNSPECIFIED", "unspecified"):
            with self.subTest(note=note):
                self.assertIs(self.attest(w32tm_status(stratum=f"3 ({note})"))["synchronized"], False)

    def test_malformed_note_spacing_is_refused_by_the_grammar(self):
        for stratum in ("3 (not\tsynchronized)", "3  (not synchronized)", "3 (not synchronized", "3 (not synchronized))"):
            with self.subTest(stratum=stratum):
                self.assertIs(self.attest(w32tm_status(stratum=stratum))["synchronized"], False)

    def test_benign_notes_with_extra_spaces_remain_healthy(self):
        for stratum in ("1 (primary  reference - syncd by radio clock)", "3 (secondary  reference - syncd by (S)NTP)"):
            with self.subTest(stratum=stratum):
                self.assertIs(self.attest(w32tm_status(stratum=stratum))["synchronized"], True)

    def test_corrupted_required_labels_beside_valid_fields_are_refused(self):
        for extra in ("Stra tum: 16", "Le ap Indicator: 3", "Sou\x00rce: Local CMOS Clock", "Stra:tum: 16",
                      "Stratum 16", "Leap Indicator 0", "Strat​um: 16", "Leap Indicator: 3",
                      "Stra\rtum: 16", "Source\t: Local CMOS Clock", "Stratumx: 16", "Sourc e: x", "S\x00tratum: 16"):
            with self.subTest(extra=extra):
                self.assertIs(self.attest(w32tm_status(extra=(extra,)))["synchronized"], False)

    def test_a_corrupted_required_label_alone_is_refused(self):
        self.assertIs(self.attest(w32tm_status(omit=("Stratum",), extra=("Stra tum: 3",)))["synchronized"], False)
        self.assertIs(self.attest(w32tm_status(omit=("Source",),
                                               extra=("Sou\x00rce: time.windows.com,0x9",)))["synchronized"], False)

    def test_unrelated_lines_that_merely_contain_the_words_are_ignored(self):
        extra = ("Time Source: w32time", "Leap second count: 27", "Last sync source: GPS",
                 "Local source of time: x", "ReferenceId: 0x0A0A0A0A (source IP:  10.10.10.10)")
        result = self.attest(w32tm_status(extra=extra))
        self.assertIs(result["synchronized"], True)
        self.assertEqual(result["source"], "time.windows.com,0x9")

    def test_lines_that_begin_with_a_required_label_word_fail_closed(self):
        # Deliberate: a line that starts with a required label word is an attempt at that label, so it is never ignored.
        for extra in ("Stratum limit: 5", "Source IP: 10.10.10.10", "Leap Indicators: 2"):
            with self.subTest(extra=extra):
                self.assertIs(self.attest(w32tm_status(extra=(extra,)))["synchronized"], False)


class WindowsAsciiFieldLabels(unittest.TestCase):
    """The certified English/ASCII format rejects invalid raw labels before normalization, for every field."""

    def test_every_malformed_label_makes_the_attestation_unhealthy(self):
        for label, stdout in MALFORMED_LABEL_STATUS.items():
            with self.subTest(case=label):
                result = cli.windows_time_sync_attestation(0, stdout)
                self.assertIs(result["synchronized"], False)
                self.assertEqual(result["leap_indicator"], 0)
                self.assertEqual(result["stratum"], 3)
                self.assertEqual(result["source"], "time.windows.com,0x9")

    def test_all_inline_ascii_controls_and_del_are_refused_on_unrelated_labels(self):
        # LF separates lines rather than being part of a label; CR inside a label must still be rejected.
        for code in (*range(10), *range(11, 32), 127):
            with self.subTest(code=code):
                stdout = w32tm_status(extra=(f"Preci{chr(code)}sion: -23",))
                self.assertIs(cli.windows_time_sync_attestation(0, stdout)["synchronized"], False)

    def test_valid_ascii_required_labels_keep_case_and_outer_space_handling(self):
        for stdout in (CODEX_BASE, " LEAP INDICATOR : 0\n STRATUM : 3\n SOURCE : time.windows.com,0x9\n",
                       w32tm_status().replace("\n", "\r\n")):
            with self.subTest(stdout=stdout):
                self.assertIs(cli.windows_time_sync_attestation(0, stdout)["synchronized"], True)

    def test_unrelated_printable_ascii_labels_and_evidence_values_keep_their_handling(self):
        stdout = w32tm_status(extra=("Time Source: w32time", "Leap second count: 27", "Unknown field / v2: value"))
        self.assertIs(cli.windows_time_sync_attestation(0, stdout)["synchronized"], True)
        # This design decision concerns labels; evidence-only and unrelated values remain outside the health gate.
        stdout = w32tm_status(last_sync="01/01/2020 00:00:00", extra=("Unknown field: \u212a",))
        self.assertIs(cli.windows_time_sync_attestation(0, stdout)["synchronized"], True)


class WindowsStratumNoteComparisonForm(unittest.TestCase):
    """R3-001: a grammar-valid Stratum note that contains a contradiction phrase is unhealthy, whatever separators,
    parentheses or case it uses. The grammar is unchanged, so every generated note is accepted by it."""

    def attest(self, stratum):
        return cli.windows_time_sync_attestation(0, w32tm_status(stratum=stratum))

    def test_every_generated_contradictory_note_is_grammar_valid_and_unhealthy(self):
        notes = contradictory_notes()
        self.assertGreater(len(notes), 400)               # a systematic set, not two examples
        for note in notes:
            with self.subTest(note=note):
                result = self.attest(f"3 ({note})")
                self.assertEqual(result["stratum"], 3)     # accepted by the grammar, so the semantic check decides
                self.assertIs(result["synchronized"], False)

    def test_r3_001_reproducers_are_unhealthy(self):
        for note in ("not (synchronized)", "not-synchronized"):
            with self.subTest(note=note):
                result = self.attest(f"3 ({note})")
                self.assertIs(result["synchronized"], False)
                self.assertEqual(result["stratum"], 3)

    def test_secondary_reference_note_remains_healthy(self):
        result = self.attest("3 (secondary reference - syncd by (S)NTP)")
        self.assertIs(result["synchronized"], True)
        self.assertEqual(result["stratum"], 3)

    def test_notes_that_only_share_words_with_the_phrases_stay_healthy(self):
        for stratum in ("1 (primary reference - syncd by radio clock)", "3 (not a reference - syncd by (S)NTP)",
                        "3 (synchronized - syncd by (S)NTP)", "2 (secondary reference - syncd by (S)NTP)"):
            with self.subTest(stratum=stratum):
                self.assertIs(self.attest(stratum)["synchronized"], True)


class WindowsSourceValidation(unittest.TestCase):
    """Source is printable ASCII; the forbidden names compare after spacing, case and punctuation are removed."""

    def attest(self, source):
        return cli.windows_time_sync_attestation(0, w32tm_status(source=source))

    def test_forbidden_names_are_refused_in_every_spacing_case_and_punctuation_variant(self):
        for source in ("Local CMOS Clock", "Local  CMOS Clock", "Local   CMOS    Clock", "LOCAL cmos CLOCK",
                       " Local CMOS Clock ", "Local CMOS Clock\u200b", "Free-running System Clock",
                       "Free-running  System Clock", "Free running System Clock", "free-running system clock",
                       "FREE-RUNNING SYSTEM CLOCK", " \tLOCAL cmos CLOCK \t"):
            with self.subTest(source=source):
                self.assertIs(self.attest(source)["synchronized"], False)

    def test_malformed_source_text_is_refused_even_when_it_is_not_a_forbidden_name(self):
        for source in ("time.windows.com\x00", "time\u00a0windows.com", "time.windows.com\t", "time.windows.com\x7f",
                       "Local\tCMOS Clock", "Local\u00a0CMOS\u2009Clock", "\x00", "   ", ""):
            with self.subTest(source=source):
                self.assertIs(self.attest(source)["synchronized"], False)

    def test_genuine_external_sources_are_healthy(self):
        for source in ("time.windows.com,0x9", "time.windows.com,0x9 ", "ntp.example.org", "VM IC Time Provider"):
            with self.subTest(source=source):
                self.assertIs(self.attest(source)["synchronized"], True)

    def test_repeated_source_fields_are_refused(self):
        for extra in (" SOURCE : time.windows.com,0x9", "Source: time.windows.com,0x9", "Source: ntp.example.org"):
            with self.subTest(extra=extra):
                result = cli.windows_time_sync_attestation(0, w32tm_status(extra=(extra,)))
                self.assertIs(result["synchronized"], False)
                self.assertEqual(result["source"], "")


class MalformedWindowsStatusNeverReachesTheTransport(unittest.TestCase):
    """Real ``time_sync_attestation`` output through the real LiveGate and acquisition runner, in G2 and G2R, with a
    fake transport. Each malformed status refuses at the gate before quota or transport. The healthy control sends
    exactly once in each mode, so the refusals come from the parser, not from a harness that never sends."""

    MODES = (auth.MODE_VERIFICATION, auth.MODE_RECURRING)

    def setUp(self):
        self.helper = authority_tests.LiveGateTests()
        self.helper.setUp()                                  # skips inside the day/month boundary guard, as they do
        self.start = authority_tests.now_utc() - timedelta(hours=1)

    def startup_attestation(self, stdout):
        """What the live run records at startup: the real ``time_sync_attestation`` on this ``w32tm`` output."""

        completed = mock.Mock(returncode=0, stdout=stdout, stderr="")
        with mock.patch.object(cli.sys, "platform", "win32"), mock.patch("subprocess.run", return_value=completed):
            return cli.time_sync_attestation()

    def runtime(self, root, mode, attestation):
        item = odds_item()
        if mode == auth.MODE_VERIFICATION:
            records = [authority_tests.g1(self.start),
                       authority_tests.g2(self.start, [item.request.provider_request_hash])]
        else:
            probe = open_rt(root / "probe")
            records = [authority_tests.g1(self.start),
                       authority_tests.g2r(self.start, derivation=probe.config.derivation_version,
                                           policy=probe.config.policy.digest)]
        return self.helper.live_runtime(root, records, mode=mode, attestation=attestation), item

    def test_malformed_status_is_refused_before_any_send(self):
        for label, stdout in MALFORMED_STATUS.items():
            for mode in self.MODES:
                with self.subTest(case=label, mode=mode), scratch_root() as root:
                    rt, item = self.runtime(root, mode, self.startup_attestation(stdout))
                    row = self.helper.refused(rt, item)
                    self.assertEqual(row["detail"], "TIME_SYNC_ATTESTATION")

    def test_healthy_status_sends_exactly_once_in_each_mode(self):
        for mode in self.MODES:
            with self.subTest(mode=mode), scratch_root() as root:
                rt, item = self.runtime(root, mode, self.startup_attestation(w32tm_status()))
                outcome = rt.runner.acquire(item)
                self.assertIsNone(outcome.failure)
                self.assertEqual(len(rt.runner.transport.calls), 1)

    def test_stratum_16_cannot_reach_a_send_in_either_mode(self):
        """RFC 5905 unsynchronized: an otherwise healthy status is refused at the gate, with no transport call."""

        attestation = self.startup_attestation(w32tm_status(stratum="16"))
        self.assertIs(attestation["synchronized"], False)
        self.assertEqual(attestation["stratum"], 16)
        for mode in self.MODES:
            with self.subTest(mode=mode), scratch_root() as root:
                rt, item = self.runtime(root, mode, attestation)
                row = self.helper.refused(rt, item)           # asserts REFUSED and zero transport calls
                self.assertEqual(row["detail"], "TIME_SYNC_ATTESTATION")

    def test_stratum_0_17_and_255_cannot_reach_a_send_in_either_mode(self):
        for stratum in ("0", "17", "255"):
            attestation = self.startup_attestation(w32tm_status(stratum=stratum))
            self.assertIs(attestation["synchronized"], False)
            for mode in self.MODES:
                with self.subTest(stratum=stratum, mode=mode), scratch_root() as root:
                    rt, item = self.runtime(root, mode, attestation)
                    row = self.helper.refused(rt, item)
                    self.assertEqual(row["detail"], "TIME_SYNC_ATTESTATION")

    def test_stratum_1_and_15_are_admitted_and_send_exactly_once_in_each_mode(self):
        for stratum in ("1", "15"):
            attestation = self.startup_attestation(w32tm_status(stratum=stratum))
            self.assertIs(attestation["synchronized"], True)
            for mode in self.MODES:
                with self.subTest(stratum=stratum, mode=mode), scratch_root() as root:
                    rt, item = self.runtime(root, mode, attestation)
                    outcome = rt.runner.acquire(item)
                    self.assertIsNone(outcome.failure)
                    self.assertEqual(len(rt.runner.transport.calls), 1)


    def test_unrelated_lines_do_not_block_a_healthy_status_in_either_mode(self):
        attestation = self.startup_attestation(w32tm_status(extra=("Time Source: w32time", "Leap second count: 27")))
        self.assertIs(attestation["synchronized"], True)
        for mode in self.MODES:
            with self.subTest(mode=mode), scratch_root() as root:
                rt, item = self.runtime(root, mode, attestation)
                outcome = rt.runner.acquire(item)
                self.assertIsNone(outcome.failure)
                self.assertEqual(len(rt.runner.transport.calls), 1)


    def test_every_generated_contradictory_note_is_refused_before_any_send_in_each_mode(self):
        for note in contradictory_notes():
            attestation = self.startup_attestation(w32tm_status(stratum=f"3 ({note})"))
            self.assertIs(attestation["synchronized"], False)
            self.assertEqual(attestation["stratum"], 3)
            for mode in self.MODES:
                with self.subTest(note=note, mode=mode), scratch_root() as root:
                    rt, item = self.runtime(root, mode, attestation)
                    row = self.helper.refused(rt, item)           # REFUSED at the gate, with zero transport calls
                    self.assertEqual(row["detail"], "TIME_SYNC_ATTESTATION")
                if mode == auth.MODE_RECURRING:                   # G2R again through the AdapterRuntime.acquire wrapper
                    with self.subTest(note=note, path="AdapterRuntime.acquire"), scratch_root() as root:
                        rt, item = self.runtime(root, mode, attestation)   # a fresh root: a repeat would be DUPLICATE
                        outcome = rt.acquire(item).outcome
                        self.assertEqual(outcome.outcome, "REFUSED")
                        self.assertIn("GATE_MISSING", str(outcome.failure))
                        self.assertEqual(rt.runner.transport.calls, [])

    def test_secondary_reference_note_sends_exactly_once_in_each_mode(self):
        attestation = self.startup_attestation(w32tm_status(stratum="3 (secondary reference - syncd by (S)NTP)"))
        self.assertIs(attestation["synchronized"], True)
        for mode in self.MODES:
            with self.subTest(mode=mode), scratch_root() as root:
                rt, item = self.runtime(root, mode, attestation)
                outcome = rt.runner.acquire(item)
                self.assertIsNone(outcome.failure)
                self.assertEqual(len(rt.runner.transport.calls), 1)


    def test_invalid_labels_are_also_refused_through_the_g2r_runtime_wrapper(self):
        # Every case already runs through the G2 and G2R runners in test_malformed_status_is_refused_before_any_send.
        for label, stdout in MALFORMED_LABEL_STATUS.items():
            with self.subTest(case=label), scratch_root() as root:
                attestation = self.startup_attestation(stdout)
                self.assertIs(attestation["synchronized"], False)
                rt, item = self.runtime(root, auth.MODE_RECURRING, attestation)
                outcome = rt.acquire(item).outcome
                self.assertEqual(outcome.outcome, "REFUSED")
                self.assertIn("GATE_MISSING", str(outcome.failure))
                self.assertEqual(rt.runner.transport.calls, [])


if __name__ == "__main__":
    unittest.main()
