"""R6 / RA5-002 - the ``Date`` header is provider-controlled text, so every value, however pathological, must end in
a defined, durable verdict (``CLOCK_SKEW``, design 6.1, 6.4, 15 F-12) and never in an exception raised after the raw
evidence was published and before ``acq_completed`` (which orphaned the attempt: crash, a debit that stands and a
lost response).

The invariant is tested at three levels: the pure parser (total over a hostile corpus and a seeded fuzz), the
capture's content check (a header that is present but unusable is never accepted, in either capture mode) and the
acquisition runner (a durable ``completed`` row carrying the verdict, quarantine, suspension, and nothing left for a
restart to reconcile).
"""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone

from genesis_adapters import errors as err
from genesis_adapters.oddspapi.raw_capture import parse_http_date

from .support import FixedClock, build_rig, odds_item, ok, read_jsonl, scratch_root

BASE = "2026-10-01T12:00:00.000000Z"
JSON = (("content-type", "application/json"),)
UTC = timezone.utc

# values that are never a parseable UTC instant (several used to be an exception out of ``parse_http_date``)
UNUSABLE = {
    "huge_year": "Mon, 01 Jan 99999999999 00:00:00 GMT",                         # OverflowError (the audit's repro)
    "year_just_over_c_int": "Mon, 01 Jan 2147483648 00:00:00 GMT",
    "year_10000": "Mon, 01 Jan 10000 00:00:00 GMT",
    "negative_year": "Mon, 01 Jan -2026 00:00:00 GMT",
    "digits_5000_year": "Mon, 01 Jan " + "9" * 5000 + " 00:00:00 GMT",
    "digits_5000_day": "Mon, " + "9" * 5000 + " Jan 2026 00:00:00 GMT",
    "digits_5000_time": "Mon, 01 Jan 2026 " + "9" * 5000 + ":00:00 GMT",
    "nul_suffix_year": "Thu, 01 Oct 2026\x00 12:00:00 GMT",
    "nul_inside": "Thu, 01 Oct 20\x0026 12:00:00 GMT",
    "offset_huge": "Thu, 01 Oct 2026 12:00:00 +99999999999",
    "offset_negative_huge": "Thu, 01 Oct 2026 12:00:00 -99999999999",
    "offset_out_of_day": "Thu, 01 Oct 2026 12:00:00 +2500",
    "offset_nonzero": "Thu, 01 Oct 2026 12:00:00 +0100",
    "empty": "",
    "blank": "   ",
    "only_zone": "GMT",
    "garbage": "not a date",
    "naive": "Thu, 01 Oct 2026 12:00:00",
    "second_61": "Thu, 01 Oct 2026 12:00:61 GMT",
    "hour_99": "Thu, 01 Oct 2026 99:00:00 GMT",
    "month_13": "Thu, 01 Foo 2026 12:00:00 GMT",
}
# a well-formed instant padded beyond ``header_value_max_chars``: it parses, but the header allowlist drops it
OVERSIZE = {
    "padded_300": "Thu, 01 Oct 2026 12:00:01 GMT" + " " * 300,
    "padded_200000": "Thu, 01 Oct 2026 12:00:00 GMT" + " " * 200_000,
}
# values the standard library reads leniently as a real instant (a two-digit-style year, trailing junk, Unicode
# digits): not unusable, but they must still reach a verdict and never raise
LENIENT = {
    "year_0000_reads_as_2000": "Mon, 01 Jan 0000 00:00:00 GMT",
    "trailing_non_ascii": "Thu, 01 Oct 2026 12:00:00 GMT é中퟿",
    "fullwidth_digits": "Thu, 01 Oct ２０２６ 12:00:00 GMT",
}
HOSTILE = {**UNUSABLE, **LENIENT, **OVERSIZE}


class ParseHttpDateIsTotalTests(unittest.TestCase):
    def test_no_hostile_value_raises(self):
        for name, value in HOSTILE.items():
            with self.subTest(name):
                parse_http_date(value)                           # a raw exception here is the defect (RA5-002)

    def test_every_unusable_value_is_none(self):
        for name, value in UNUSABLE.items():
            with self.subTest(name):
                self.assertIsNone(parse_http_date(value))

    def test_the_whole_representable_calendar_is_parsed_or_refused_never_raised(self):
        for year in (1, 2, 1969, 1970, 2026, 9998, 9999):
            with self.subTest(year=year):
                moment = parse_http_date(f"Mon, 01 Jan {year:04d} 00:00:00 GMT")
                self.assertTrue(moment is None or (moment.tzinfo is not None and moment.utcoffset() == timedelta(0)))
        low = parse_http_date("Mon, 01 Jan 0001 00:00:00 GMT")
        high = parse_http_date("Fri, 31 Dec 9999 23:59:59 GMT")
        self.assertEqual(high, datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC))      # the last instant converts exactly
        self.assertTrue(low is None or low.tzinfo is not None)

    def test_a_well_formed_gmt_date_still_parses_to_the_exact_instant(self):
        self.assertEqual(parse_http_date("Thu, 01 Oct 2026 12:00:01 GMT"), datetime(2026, 10, 1, 12, 0, 1, tzinfo=UTC))
        for zone in ("+0000", "UT", "UTC", "Z"):
            with self.subTest(zone=zone):
                self.assertEqual(parse_http_date(f"Thu, 01 Oct 2026 12:00:01 {zone}"),
                                 datetime(2026, 10, 1, 12, 0, 1, tzinfo=UTC))
        self.assertIsNone(parse_http_date("Thu, 01 Oct 2026 12:00:01 +0001"))      # an offset is never normalized
        self.assertIsNone(parse_http_date("Thu, 01 Oct 2026 12:00:01"))            # naive

    def test_a_seeded_fuzz_over_date_shaped_strings_never_raises(self):
        rng = random.Random(20261003)
        weekdays = ["Mon", "Thu", "xxx", "", "Mon,", "\x00", "99999999999"]
        days = ["01", "1", "31", "32", "00", "-1", "9" * 12, "9" * 5000, "١", "", "1e3"]
        months = ["Jan", "Oct", "Dec", "Foo", "", "\x00", "janvier"]
        years = ["2026", "99999999999", "9" * 400, "0", "-1", "10000", "9999", "0001", "26", "\ud800", "", "1\x002",
                 "2147483647", "2147483648", "4294967296", "9223372036854775808"]
        times = ["12:00:00", "99:99:99", "12:00", "12:00:00.5", "-1:00:00", "\x00", "", "9" * 4300 + ":00:00",
                 "12:00:" + "9" * 20]
        zones = ["GMT", "UTC", "+0000", "-0000", "+9999", "-9999999999", "+0100", "", "GMT\x00", "EST", "é"]
        for _ in range(3000):
            text = rng.choice([" ", "  ", "\t", ""]).join(
                [rng.choice(weekdays), rng.choice(days), rng.choice(months), rng.choice(years),
                 rng.choice(times), rng.choice(zones)])
            parsed = parse_http_date(text)                                              # must not raise
            self.assertTrue(parsed is None or (parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)),
                            text[:80])


def skew_rig(root, raw_date, *, require_date: bool):
    def step(clock):
        return ok(b"[]", headers=JSON + (("date", raw_date),), latency=1.0)

    return build_rig(root, capture=True, script=[step], clock=FixedClock(BASE, step_micros=0),
                     require_date=require_date)


def rows_of(rig, record_type):
    return [row for row in read_jsonl(rig.acq_path) if row["record_type"] == record_type]


class PathologicalDateIsAQuarantineVerdictTests(unittest.TestCase):
    """Whatever the value, the attempt ends in a durable verdict: for an unusable Date it is CLOCK_SKEW (F-12) with
    the raw kept, a quarantine row, sends suspended and one coverage entry - in live capture mode (Date required) and
    in fixture mode alike."""

    def check(self, name, value, *, require_date, skew: bool = True):
        with scratch_root() as root:
            rig = skew_rig(root, value, require_date=require_date)
            outcome = rig.runner.acquire(odds_item())                       # an exception here is RA5-002
            (done,) = rows_of(rig, "acq_completed")                         # a durable verdict row, whatever it is
            self.assertEqual((done["outcome"], done["http_status"]), ("RESPONSE", 200), name)
            self.assertIsNotNone(done["raw_observation_id"], "the raw evidence stays (design 15 F-12)")
            if not skew:
                self.assertIn(outcome.failure, (None, err.AdapterFailure.CLOCK_SKEW), name)
                self.assertEqual(done["failure"], outcome.failure.value if outcome.failure else None)
                return
            self.assertEqual(outcome.failure, err.AdapterFailure.CLOCK_SKEW, name)
            self.assertEqual(done["failure"], "CLOCK_SKEW")
            self.assertEqual(len(rows_of(rig, "acq_quarantined")), 1)
            self.assertEqual([row["reason"] for row in rows_of(rig, "acq_sends_suspended")], ["CLOCK_SKEW"])
            entry = read_jsonl(rig.coverage_path)[-1]
            self.assertEqual((entry["status"], entry["note"]), ("quarantined", "CLOCK_SKEW"))
            # restart-stable: nothing is open, so nothing is reconciled, and the next send stays refused
            again = build_rig(root, capture=True, quota_ledger=rig.quota_ledger, cache=rig.cache,
                              clock=FixedClock("2026-10-01T12:05:00.000000Z", step_micros=1000),
                              require_date=require_date)
            self.assertEqual(again.runner.reconcile_after_restart(), ())
            self.assertEqual(rows_of(again, "acq_reconciled"), [])
            blocked = again.runner.acquire(odds_item(window="w2"))
            self.assertEqual((blocked.outcome, blocked.failure), ("REFUSED", err.AdapterFailure.CIRCUIT_OPEN))

    def test_every_unusable_value_is_a_clock_skew_quarantine_in_live_mode(self):
        for name, value in UNUSABLE.items():
            with self.subTest(name):
                self.check(name, value, require_date=True)

    def test_every_present_but_unusable_value_is_a_clock_skew_quarantine_in_fixture_mode_too(self):
        # fixture mode only forgives a MISSING header; one that is there and unusable never passes (CLK-04)
        for name, value in UNUSABLE.items():
            with self.subTest(name):
                self.check(name, value, require_date=False)

    def test_lenient_values_still_reach_a_verdict_in_both_modes(self):
        for name, value in LENIENT.items():
            for require_date in (True, False):
                with self.subTest(name, require_date=require_date):
                    self.check(name, value, require_date=require_date, skew=False)

    def test_an_over_long_date_header_is_present_not_missing(self):
        """The header allowlist drops a value longer than ``header_value_max_chars``; for Date that must not read as
        'no Date header' (which fixture mode accepts) - it is a present, unusable time claim."""

        for name, value in OVERSIZE.items():
            for require_date in (True, False):
                with self.subTest(name, require_date=require_date):
                    self.check(name, value, require_date=require_date)

    def test_the_missing_header_rule_is_unchanged(self):
        for require_date, expected in ((True, err.AdapterFailure.CLOCK_SKEW), (False, None)):
            with self.subTest(require_date=require_date), scratch_root() as root:
                rig = build_rig(root, capture=True, script=[ok(b"[]", headers=JSON, latency=1.0)],
                                clock=FixedClock(BASE, step_micros=0), require_date=require_date)
                self.assertEqual(rig.runner.acquire(odds_item()).failure, expected)

    def test_a_seeded_fuzz_through_the_runner_always_ends_in_a_verdict(self):
        rng = random.Random(7)
        pieces = ["Mon", "Thu", "01", "99999999999", "2147483648", "Oct", "2026", "12:00:00", "GMT", "+0000", "\x00",
                  "é", "9" * 50, "-1", " ", ",", ":"]
        for index in range(25):
            value = " ".join(rng.choice(pieces) for _ in range(rng.randint(1, 8)))
            with self.subTest(index=index, value=value[:60]), scratch_root() as root:
                rig = skew_rig(root, value, require_date=True)
                outcome = rig.runner.acquire(odds_item())
                self.assertIn(outcome.failure, (None, err.AdapterFailure.CLOCK_SKEW))
                self.assertEqual(len(rows_of(rig, "acq_completed")), 1)           # a verdict row exists either way


class SkewBoundaryAtTheDateEdgesTests(unittest.TestCase):
    """The edges of the representable calendar compare against ``T1`` without an overflow (the difference of two
    in-range datetimes always fits a ``timedelta``): far-past and far-future dates are plain skew."""

    def test_the_first_and_last_representable_instants_are_skew_not_errors(self):
        for text in ("Mon, 01 Jan 0001 00:00:00 GMT", "Fri, 31 Dec 9999 23:59:59 GMT"):
            for require_date in (True, False):
                with self.subTest(text, require_date=require_date), scratch_root() as root:
                    rig = skew_rig(root, text, require_date=require_date)
                    self.assertEqual(rig.runner.acquire(odds_item()).failure, err.AdapterFailure.CLOCK_SKEW)


if __name__ == "__main__":
    unittest.main()
