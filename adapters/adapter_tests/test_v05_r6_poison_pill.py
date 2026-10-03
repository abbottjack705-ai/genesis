"""R6 / RA5-001 (BLOCKER) - no HTTP-200 body may wedge the response-to-document path.

The defect: four classes of schema-valid provider content raised out of the "pure" parser AFTER the capture was
already recorded as a success (``decimal.Overflow`` from a huge exponent, ``UnicodeEncodeError`` from a lone surrogate,
``IdentityTypeError`` from a 65-digit participant id, ``RecursionError`` from deep nesting). The attempt then had no
durable verdict, so every ``resume()`` re-derived it and raised again, ``pending_work()`` reported it forever, every
read was refused, and an operator ``reset`` changed nothing.

The invariant (design 11.1, 14.4, 15 D13): after ANY syntactically valid HTTP-200 body Genesis reaches a durable,
restart-stable state - a usable observation, or an explicit durable refusal with coverage - and the already published
raw evidence is never touched. Tested here at three levels:

* the four classes (and their neighbours) at parser level and end to end through
  ``acquire -> restart -> resume -> reader``;
* the safety net: whatever else a derivation might raise (``RecursionError``, ``MemoryError``, anything) becomes ONE
  durable terminal verdict that nothing re-derives, also when the policy changed between capture and normalization;
* seeded property tests over every leaf of the base ODDS fixture with the audit's hostile literal pool: the pure stage
  raises nothing, and the safety net is never what catches a known class.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import unittest
from unittest import mock

from genesis.coverage import CoverageStatus

from genesis_adapters import errors as err
from genesis_adapters.oddspapi import acquisition, derivation, normalize, parser, quiescence, verify
from genesis_adapters.oddspapi.acquisition import LedgerInvariantError
from genesis_adapters.secrets import Secret
from genesis_adapters.oddspapi.reader import UsableBook

from . import parser_support as ps
from .pipeline_support import (
    JSON, START, FakeTransport, FixedClock, acquisition_rows, approve, copy_config, coverage_rows, documents, ok,
    odds_item, odds_response, open_rt, pit_rows, reopen,
)
from .support import no_response, scratch_root


def err_placeholder() -> str:
    from genesis_adapters.oddspapi.transport import REDACTED_EXCEPTION_CLASS

    return REDACTED_EXCEPTION_CLASS


# ---------------------------------------------------------------------------------------------------------
# the poison payloads
# ---------------------------------------------------------------------------------------------------------
def first_player(payload):
    fixture = ps.fixture_of(payload)
    market = next(iter(fixture["bookmakerOdds"]["pinnacle"]["markets"].values()))
    return next(iter(next(iter(market["outcomes"].values()))["players"].values()))


def literal(mutator, **literals) -> bytes:
    payload = ps.odds_payload()
    mutator(payload)
    return ps.dump_with(payload, **literals) if literals else ps.dump(payload)


def exponent(payload):
    first_player(payload)["changedAt"] = "@big"


def surrogate(payload):
    first_player(payload)["active"] = "\ud800"


def participant_70_digits(payload):
    ps.fixture_of(payload)["participant1Id"] = int("9" * 70)


def nested(payload):
    first_player(payload)["betslip"] = "@deep"


def fixture_id_bad(payload):
    ps.fixture_of(payload)["fixtureId"] = "not a valid id"


CLASSES = {
    # name: (the body, the verdict a defined durable outcome carries or None when documents are produced)
    "exponent": (lambda: literal(exponent, big="1E+999999999"), "NUMBER_OUT_OF_RANGE"),
    "surrogate": (lambda: literal(surrogate), "INVALID_UTF8"),
    "participant_id_70_digits": (lambda: literal(participant_70_digits), None),
    "nesting_600": (lambda: literal(nested, deep="[" * 600 + "0" + "]" * 600), "NESTING_TOO_DEEP"),
    "nesting_900": (lambda: literal(nested, deep="[" * 900 + "0" + "]" * 900), "NESTING_TOO_DEEP"),
    "fixture_id_outside_grammar": (lambda: literal(fixture_id_bad), "ENVELOPE_SCHEMA_MISMATCH"),
}


class DerivationSpy:
    """Records which acquisitions the pure stage ran for (to prove a terminal verdict is never re-derived)."""

    def __init__(self):
        self.acquisitions = []
        self.real = parser.parse_odds_response

    def __call__(self, raw, ctx):
        self.acquisitions.append(ctx.acquisition_id)
        return self.real(raw, ctx)


def unfinished(rt):
    return quiescence.pending_work(rt.stores)


def reload(rt, seconds: float, **kw):
    return reopen(rt, clock=FixedClock(ps.iso_add(rt.stores.acquisition.rows()[-1]["recorded_at"], seconds=seconds),
                                       step_micros=1000), **kw)


class Scenario:
    """healthy capture -> poison capture -> restart and resume -> later healthy capture -> read."""

    def __init__(self, root, poison: bytes, *, restart_config=None):
        self.root = root
        self.poison = poison
        self.clock = FixedClock(START, step_micros=1000)
        self.rt = open_rt(root, clock=self.clock, script=[odds_response(), ok(poison, headers=JSON)])
        self.rt.acquire(odds_item("w1"))
        approve(self.rt)
        self.entities = sorted({row["entity_id"] for row in pit_rows(self.rt)})
        self.pit_before = len(pit_rows(self.rt))
        self.clock.advance(seconds=900)
        self.error = None
        try:
            self.result = self.rt.acquire(odds_item("w2"))        # the poison capture
        except BaseException as exc:                                # noqa: BLE001 - this IS the defect under test
            self.error, self.result = exc, None
        self.poison_aid = [row for row in acquisition_rows(self.rt)
                           if row["record_type"] == "acq_planned"][1]["acquisition_id"]

    def poison_rows(self, rt=None):
        return [row for row in acquisition_rows(rt or self.rt) if row.get("acquisition_id") == self.poison_aid]

    def restart(self, **kw):
        self.spy = DerivationSpy()
        self.rt2 = reload(self.rt, 100, transport=FakeTransport([odds_response()]), **kw)
        with mock.patch.object(parser, "parse_odds_response", self.spy):
            self.resumed = self.rt2.resume()
        return self.rt2

    def later_healthy_capture_and_read(self):
        self.rt3 = reload(self.rt2, 900, transport=FakeTransport([odds_response()]))
        self.rt3.acquire(odds_item("w3"))
        self.rt4 = reload(self.rt3, 1800)
        cutoff = ps.iso_add(self.rt4.clock.peek(), seconds=30)
        return self.rt4.reader().head(self.entities[0], cutoff)


class FourClassesEndToEndTests(unittest.TestCase):
    """acquire -> restart -> resume -> reader, for each class: a defined outcome, no exception, nothing pending, and a
    later healthy capture is usable again."""

    def test_every_class_ends_in_a_defined_restart_stable_state(self):
        for name, (make, verdict) in CLASSES.items():
            with self.subTest(name), scratch_root() as root:
                scenario = Scenario(root, make())
                self.assertIsNone(scenario.error, f"acquire raised {type(scenario.error).__name__}")
                self.assertEqual(unfinished(scenario.rt), (), "the capture is left pending")
                rows_before = acquisition_rows(scenario.rt)
                coverage_before = coverage_rows(scenario.rt)
                scenario.restart()
                if verdict is not None:        # a refused capture is final; a derived one is re-verified by resume()
                    self.assertNotIn(scenario.poison_aid, scenario.spy.acquisitions, "a restart re-derived it")
                self.assertEqual(unfinished(scenario.rt2), ())
                # restart-stable: nothing new, nothing different
                self.assertEqual(acquisition_rows(scenario.rt2)[:len(rows_before)], rows_before)
                self.assertEqual(coverage_rows(scenario.rt2)[:len(coverage_before)], coverage_before)
                usable = scenario.later_healthy_capture_and_read()
                self.assertIsInstance(usable, UsableBook, f"reads stay refused: {usable!r}")

    def test_a_rejection_is_a_durable_verdict_with_coverage_and_no_observation(self):
        for name, (make, verdict) in CLASSES.items():
            if verdict is None:
                continue
            with self.subTest(name), scratch_root() as root:
                scenario = Scenario(root, make())
                self.assertIsNone(scenario.error)
                rows = scenario.poison_rows()
                kinds = [row["record_type"] for row in rows]
                self.assertNotIn("acq_normalized", kinds)
                # the verdict is the attempt's durable terminal state, whichever row carries it
                carried = [row.get("failure") for row in rows if row["record_type"] in
                           ("acq_completed", "acq_derivation_rejected")]
                self.assertIn(verdict, carried, rows)
                reasons = [entry for entry in coverage_rows(scenario.rt) if entry["note"] == verdict]
                self.assertEqual(len(reasons), 1, "exactly one coverage entry records the rejection")
                self.assertEqual(reasons[0]["status"], "rejected")
                self.assertEqual(reasons[0]["reason_codes"], ["schema_rejected"])
                self.assertEqual(len(pit_rows(scenario.rt)), scenario.pit_before,
                                 "a rejected response produced a PIT record")

    def test_a_participant_id_outside_the_grammar_blocks_only_that_fixtures_books(self):
        with scratch_root() as root:
            scenario = Scenario(root, CLASSES["participant_id_70_digits"][0]())
            self.assertIsNone(scenario.error)
            blocked = [doc for doc in documents(scenario.rt) if doc["market_state"] == "BLOCKED"
                       and "PARTICIPANT_AMBIGUOUS" in doc["state_reasons"]]
            self.assertTrue(blocked, "the books of the affected fixture are BLOCKED with PARTICIPANT_AMBIGUOUS")
            fixture = ps.FIXTURE_A
            self.assertTrue(all(doc["provider_fixture_id"]["value"] == fixture for doc in blocked))
            other = [doc for doc in documents(scenario.rt)
                     if doc["provider_fixture_id"]["value"] == ps.FIXTURE_B and doc["market_state"] != "BLOCKED"
                     and doc["raw_observation_id"] == blocked[0]["raw_observation_id"]]
            self.assertTrue(other, "the other fixture of the same response is unaffected")
            self.assertEqual(unfinished(scenario.rt), ())

    def test_the_published_raw_evidence_is_immutable_and_still_retrievable(self):
        for name, (make, verdict) in CLASSES.items():
            with self.subTest(name), scratch_root() as root:
                body = make()
                scenario = Scenario(root, body)
                scenario.restart()
                completed = [row for row in scenario.poison_rows(scenario.rt2) if row["record_type"] == "acq_completed"][0]
                observation = scenario.rt2.stores.evidence.get_observation(completed["raw_observation_id"])
                stored = scenario.rt2.stores.evidence.get_bytes(observation.artifact_hash)
                self.assertEqual(stored, body)
                self.assertEqual(observation.artifact_hash, hashlib.sha256(body).hexdigest())
                self.assertGreaterEqual(scenario.rt2.stores.evidence.verify_manifest(), 2)   # every row verifies

    def test_no_operator_action_is_needed_afterwards(self):
        """The audit's p119b: ``reset`` cleared nothing and the capture re-raised. Now there is nothing to clear."""

        with scratch_root() as root:
            scenario = Scenario(root, CLASSES["exponent"][0]())
            rows = acquisition_rows(scenario.rt)
            self.assertEqual([r for r in rows if r["record_type"] == "acq_halted"], [])
            scenario.restart()
            self.assertEqual([r for r in acquisition_rows(scenario.rt2) if r["record_type"] == "acq_halted"], [])
            third = reload(scenario.rt2, 900, transport=FakeTransport([odds_response()]))
            third.acquire(odds_item("w3"))                              # sends are not refused by a circuit or halt


# ---------------------------------------------------------------------------------------------------------
class ParserLevelTests(unittest.TestCase):
    """The pure stage on the same bodies: a ParsedResponse (or a defined rejection) and documents, never a raise."""

    def test_the_four_classes_never_raise_out_of_parse_or_build_documents(self):
        for name, (make, verdict) in CLASSES.items():
            with self.subTest(name):
                parsed = ps.parse(make())                        # a raw exception here is the defect
                if parsed.failure is None:
                    ps.documents(parsed)
                else:
                    self.assertEqual(parsed.failure.value, verdict)

    def test_neighbouring_cases_are_defined_too(self):
        cases = {
            "exponent_in_price": lambda p: first_player(p).update(price="@big"),
            "exponent_in_line_field": lambda p: first_player(p).update(handicap="@big"),
            "negative_exponent": lambda p: first_player(p).update(changedAt="@tiny"),
            "surrogate_in_key": lambda p: first_player(p).update({"\ud800": 1}),
            "surrogate_in_status": lambda p: ps.fixture_of(p).update(statusId="\udfff"),
            "surrogate_in_bookmaker_key": lambda p: ps.fixture_of(p)["bookmakerOdds"].update({"\ud800": {}}),
            "participant2_negative": lambda p: ps.fixture_of(p).update(participant2Id=-5),
            "participant_65_digits": lambda p: ps.fixture_of(p).update(participant1Id=int("1" + "0" * 64)),
            "participant_64_digits": lambda p: ps.fixture_of(p).update(participant1Id=int("1" + "0" * 63)),
            "market_key_digits_5000": lambda p: ps.fixture_of(p)["bookmakerOdds"]["pinnacle"]["markets"].update(
                {"9" * 5000: {}}),
            "outcome_key_unicode_digits": lambda p: next(iter(ps.fixture_of(p)["bookmakerOdds"]["pinnacle"][
                "markets"].values()))["outcomes"].update({"²": {}}),
        }
        for name, change in cases.items():
            with self.subTest(name):
                payload = ps.odds_payload()
                change(payload)
                text = json.dumps(payload, sort_keys=True).replace('"@big"', "1E+999999999").replace(
                    '"@tiny"', "1E-999999999")
                parsed = ps.parse(text.encode("ascii"))
                if parsed.failure is None:
                    ps.documents(parsed)

    def test_the_derive_boundary_is_total_and_reports_a_rejection(self):
        for name, (make, verdict) in CLASSES.items():
            with self.subTest(name):
                derived = derivation.derive(make(), ps.make_ctx())
                if verdict is None:
                    self.assertIsNone(derived.failure)
                    self.assertTrue(derived.documents)
                else:
                    self.assertEqual(derived.failure.value, verdict)
                    self.assertEqual(derived.documents, ())


# ---------------------------------------------------------------------------------------------------------
FAULTS = {
    "RecursionError": RecursionError("maximum recursion depth exceeded"),
    "MemoryError": MemoryError(),
    "UnicodeEncodeError": UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed"),
    "decimal_Overflow": __import__("decimal").Overflow(),
    "KeyError": KeyError("x"),
    "ValueError": ValueError("hostile"),
    "AttributeError": AttributeError("none"),
}


class SafetyNetTests(unittest.TestCase):
    """Whatever a derivation raises - known class or not - ends in ONE durable terminal verdict."""

    def injected(self, exc, *, where):
        with scratch_root() as root:
            clock = FixedClock(START, step_micros=1000)
            rt = open_rt(root, clock=clock, script=[odds_response(), odds_response()])
            rt.acquire(odds_item("w1"))
            approve(rt)
            entities = sorted({row["entity_id"] for row in pit_rows(rt)})
            clock.advance(seconds=900)
            target = parser if where == "parse" else normalize
            name = "parse_odds_response" if where == "parse" else "build_documents"
            real = getattr(target, name)
            calls = []

            def fault(*args, **kwargs):
                calls.append(1)
                raise exc

            with mock.patch.object(target, name, fault):
                result = rt.acquire(odds_item("w2"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(unfinished(rt), ())
            rows = acquisition_rows(rt)
            rejected = [r for r in rows if r["record_type"] == "acq_derivation_rejected"]
            self.assertEqual(len(rejected), 1)
            self.assertEqual((rejected[0]["failure"], rejected[0]["detail"]), ("DERIVATION_FAULT", type(exc).__name__))
            self.assertEqual(result.outcome.failure.value, "DERIVATION_FAULT")
            faults = [e for e in coverage_rows(rt) if e["note"] == "DERIVATION_FAULT"]
            self.assertEqual([(e["status"], e["reason_codes"]) for e in faults], [("rejected", ["schema_rejected"])])
            # a restart does not re-derive the refused capture (the real, healthy parser is back: it must not even see it)
            poison_aid = rejected[0]["acquisition_id"]
            spy = DerivationSpy()
            later = reload(rt, 100, transport=FakeTransport([odds_response()]))
            with mock.patch.object(parser, "parse_odds_response", spy):
                resumed = later.resume()
            self.assertNotIn(poison_aid, spy.acquisitions)
            self.assertEqual(len([r for r in acquisition_rows(later) if r["record_type"] == "acq_derivation_rejected"]), 1)
            # and the pipeline is healthy again
            third = reload(later, 900, transport=FakeTransport([odds_response()]))
            third.acquire(odds_item("w3"))
            head = reload(third, 1800).reader().head(entities[0], ps.iso_add(third.clock.peek(), seconds=3000))
            self.assertIsInstance(head, UsableBook)

    def test_every_exception_family_from_parse_is_a_terminal_verdict(self):
        for name, exc in FAULTS.items():
            with self.subTest(name):
                self.injected(copy.copy(exc), where="parse")

    def test_every_exception_family_from_document_building_is_a_terminal_verdict(self):
        for name in ("RecursionError", "UnicodeEncodeError", "KeyError"):
            with self.subTest(name):
                self.injected(copy.copy(FAULTS[name]), where="build")

    def test_a_policy_change_between_capture_and_normalization_cannot_wedge_the_pipeline(self):
        """The capture was a success under one derivation; under another (here a tighter nesting bound) the same raw
        bytes are no longer derivable. That is a rejection, not a crash on every restart."""

        deep = literal(nested, deep="[" * 40 + "0" + "]" * 40)
        with scratch_root() as root:
            first = open_rt(root, clock=FixedClock(START, step_micros=1000), script=[ok(deep, headers=JSON)])
            first.runner.acquire(odds_item("w1"))                       # captured only: capture-time checks pass
            self.assertEqual(unfinished(first), ("a successful ODDS capture is not normalized yet",))
            tight = copy_config(root / "elsewhere")
            policy_file = tight / "oddspapi_slice1_policy.json"
            body = json.loads(policy_file.read_text())
            body["json_max_depth"] = 30
            policy_file.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
            second = reload(first, 100, config_dir=tight, transport=FakeTransport([]))
            self.assertNotEqual(second.config.derivation_version, first.config.derivation_version)
            resumed = second.resume()                                   # a raise here is the poison pill
            self.assertEqual(resumed[1], ())
            self.assertEqual(unfinished(second), ())
            rejected = [r for r in acquisition_rows(second) if r["record_type"] == "acq_derivation_rejected"]
            self.assertEqual([r["failure"] for r in rejected], ["NESTING_TOO_DEEP"])
            self.assertEqual(rejected[0]["derivation_version"], second.config.derivation_version)
            again = reload(second, 100, config_dir=tight)
            self.assertEqual(again.resume()[1], ())
            self.assertEqual(len([r for r in acquisition_rows(again) if r["record_type"] == "acq_derivation_rejected"]), 1)

    def test_a_normalized_capture_that_stops_deriving_is_an_integrity_halt_not_a_rejection(self):
        """A capture that was already normalized cannot be 'rejected': the derivation was deterministic, so a fault
        now is a changed derivation or damaged evidence - the existing durable halt, never a silent rewrite."""

        from genesis_adapters.oddspapi.pipeline import PipelineHalt

        with scratch_root() as root:
            rt = open_rt(root, clock=FixedClock(START, step_micros=1000), script=[odds_response()])
            rt.acquire(odds_item("w1"))
            aid = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_planned"][0]["acquisition_id"]
            with mock.patch.object(parser, "parse_odds_response", side_effect=RuntimeError("changed")):
                with self.assertRaises(PipelineHalt):
                    rt.normalize(aid)
            self.assertEqual([r for r in acquisition_rows(rt) if r["record_type"] == "acq_derivation_rejected"], [])
            self.assertEqual(acquisition_rows(rt)[-1]["record_type"], "acq_halted")


# ---------------------------------------------------------------------------------------------------------
class LedgerRulesForTheTerminalVerdictTests(unittest.TestCase):
    """The replay validation of the new ``acq_derivation_rejected`` row."""

    def poisoned(self, root):
        rt = open_rt(root, clock=FixedClock(START, step_micros=1000), script=[odds_response()])
        with mock.patch.object(parser, "parse_odds_response", side_effect=RuntimeError("x")):
            rt.acquire(odds_item("w1"))
        rows = acquisition_rows(rt)
        return rt, [r for r in rows if r["record_type"] == "acq_planned"][0]["acquisition_id"]

    def test_a_second_verdict_for_an_already_rejected_attempt_is_refused(self):
        with scratch_root() as root:
            rt, aid = self.poisoned(root)
            ledger = rt.stores.acquisition
            at = ledger.last_recorded_at()
            for failure in ("DERIVATION_FAULT", "NOT_A_CODE"):
                with self.subTest(failure=failure):
                    with self.assertRaises(LedgerInvariantError):   # already rejected: a second verdict is refused
                        ledger.append("acq_derivation_rejected", recorded_at=at, acquisition_id=aid, failure=failure,
                                      detail=None, derivation_version=rt.config.derivation_version)

    def test_an_unknown_failure_code_and_a_missing_attempt_are_refused(self):
        with scratch_root() as root:
            rt = open_rt(root, clock=FixedClock(START, step_micros=1000), script=[odds_response()])
            rt.runner.acquire(odds_item("w1"))
            aid = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_planned"][0]["acquisition_id"]
            at = rt.stores.acquisition.last_recorded_at()
            with self.assertRaises(LedgerInvariantError):
                rt.stores.acquisition.append("acq_derivation_rejected", recorded_at=at, acquisition_id=aid,
                                             failure="NOT_A_CODE", detail=None, derivation_version="mb1-x")
            with self.assertRaises(LedgerInvariantError):
                rt.stores.acquisition.append("acq_derivation_rejected", recorded_at=at, acquisition_id="f" * 64,
                                             failure="DERIVATION_FAULT", detail=None, derivation_version="mb1-x")

    def test_a_normalized_attempt_cannot_be_rejected_and_a_rejected_one_cannot_be_normalized(self):
        with scratch_root() as root:
            rt = open_rt(root, clock=FixedClock(START, step_micros=1000), script=[odds_response()])
            rt.acquire(odds_item("w1"))
            aid = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_planned"][0]["acquisition_id"]
            with self.assertRaises(LedgerInvariantError):
                rt.stores.acquisition.append("acq_derivation_rejected", recorded_at=rt.stores.acquisition.last_recorded_at(),
                                             acquisition_id=aid, failure="DERIVATION_FAULT", detail=None,
                                             derivation_version=rt.config.derivation_version)
        with scratch_root() as root:
            rt, aid = self.poisoned(root)
            normalized = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_normalized"]
            self.assertEqual(normalized, [])
            with self.assertRaises(LedgerInvariantError):
                rt.stores.acquisition.append(
                    "acq_normalized", recorded_at=rt.stores.acquisition.last_recorded_at(), acquisition_id=aid,
                    T2=START, T3=START, derivation_version="x", expected_scope_hash=None,
                    identity_registry_head={"sequence": 0, "record_hash": "0" * 64}, normalized_observation_ids=[],
                    pit_record_ids=[], coverage_entry_ids=[])

    def verdict_row(self, rows, aid, **changes):
        """A synthetic verdict row for ``aid`` after ``rows`` (plain dicts: ``_replay`` validates rows, not the chain)."""

        row = {"record_type": "acq_derivation_rejected", "schema_version": rows[-1]["schema_version"],
               "recorded_at": rows[-1]["recorded_at"], "acquisition_id": aid, "failure": "DERIVATION_FAULT",
               "detail": None, "derivation_version": "mb1-x"}
        row.update(changes)
        return row

    def completed_rows(self, root, response):
        rt = open_rt(root, clock=FixedClock(START, step_micros=1000), script=[response])
        rt.runner.acquire(odds_item("w1"))                     # the runner alone: nothing is normalized yet
        rows = acquisition_rows(rt)
        return rt, rows, [r for r in rows if r["record_type"] == "acq_planned"][0]["acquisition_id"]

    def test_a_verdict_is_only_for_a_response_that_passed_its_content_checks(self):
        # (the control: the same rows with a verdict are a valid history)
        with scratch_root() as root:
            _, rows, aid = self.completed_rows(root, odds_response())
            acquisition._replay(rows + [self.verdict_row(rows, aid)])
        # a response that already carries a content verdict is not derived, so it cannot be "rejected" later
        with scratch_root() as root:
            _, rows, aid = self.completed_rows(root, ok(b"not json", headers=JSON))
            self.assertEqual([r["failure"] for r in rows if r["record_type"] == "acq_completed"], ["NOT_JSON"])
            with self.assertRaises(LedgerInvariantError):
                acquisition._replay(rows + [self.verdict_row(rows, aid)])
        # an attempt that completed with no response at all (no T1) has nothing to derive, whatever its failure field
        with scratch_root() as root:
            _, rows, aid = self.completed_rows(root, no_response())
            crafted = [dict(row, failure=None) if row["record_type"] == "acq_completed" else row for row in rows]
            acquisition._replay(crafted)                       # the history itself replays
            with self.assertRaises(LedgerInvariantError):
                acquisition._replay(crafted + [self.verdict_row(crafted, aid)])

    def test_a_verdict_detail_is_text_or_nothing(self):
        with scratch_root() as root:
            _, rows, aid = self.completed_rows(root, odds_response())
            for detail in (None, "RuntimeError", ""):
                with self.subTest(detail=detail):
                    acquisition._replay(rows + [self.verdict_row(rows, aid, detail=detail)])
            for detail in (7, ["RuntimeError"], {"class": "RuntimeError"}, b"RuntimeError", True):
                with self.subTest(detail=detail), self.assertRaises(LedgerInvariantError):
                    acquisition._replay(rows + [self.verdict_row(rows, aid, detail=detail)])

    def test_the_verdict_detail_is_screened_like_every_record_before_it_is_persisted(self):
        # the detail is an exception CLASS NAME: code-defined for any real exception, but screened anyway (design 7.6).
        # A name that is not a plain identifier, or one that is the key itself, is replaced by the fixed placeholder.
        key = "QzXvBnMkLjHgFdSa"                                  # identifier-shaped: only the key-form screen sees it
        cases = {"not an identifier\nat all": err_placeholder(), key: err_placeholder(),
                 "RuntimeError": "RuntimeError"}
        for name, expected in cases.items():
            with self.subTest(name[:12]), scratch_root() as root:
                hostile = type(name, (Exception,), {})
                rt = open_rt(root, clock=FixedClock(START, step_micros=1000), script=[odds_response()],
                             secret=Secret(key))
                with mock.patch.object(parser, "parse_odds_response", side_effect=hostile("x")):
                    rt.acquire(odds_item("w1"))
                verdicts = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_derivation_rejected"]
                self.assertEqual([r["detail"] for r in verdicts], [expected])
                self.assertEqual(verify.scan_runtime_for_secret(root, Secret(key)), ())

    def test_every_content_rejection_the_decoder_and_the_derivation_can_raise_is_a_rejected_coverage_status(self):
        for failure in (err.AdapterFailure.NESTING_TOO_DEEP, err.AdapterFailure.NUMBER_OUT_OF_RANGE,
                        err.AdapterFailure.DERIVATION_FAULT):
            with self.subTest(failure=failure.value):
                self.assertEqual(acquisition._COVERAGE_STATUS[failure], CoverageStatus.REJECTED)
                self.assertEqual(err.reason_code(failure), err.REASON_CODE_MAP[failure])
                self.assertEqual(err.reason_code(failure).value, "schema_rejected")

    def test_a_rejected_capture_is_not_a_successful_capture_for_any_reader_of_the_ledger(self):
        with scratch_root() as root:
            rt, aid = self.poisoned(root)
            rows = derivation.acquisition_rows(rt.stores.acquisition, aid)
            self.assertIn("acq_derivation_rejected", rows)
            self.assertEqual(rows["acq_completed"]["failure"], None)                # the capture itself succeeded...
            self.assertFalse(derivation.successful_capture(rows))                   # ...its derivation did not
            self.assertEqual(rt.stores.acquisition.attempts()[aid].state, "DERIVATION_REJECTED")
            with self.assertRaises(derivation.DerivationError):
                rt.normalize(aid)                                                   # explicit misuse is still refused

    def test_a_retry_plan_item_for_a_rejected_attempt_is_not_retryable(self):
        from genesis_adapters.errors import PlanRefused

        with scratch_root() as root:
            rt, aid = self.poisoned(root)
            retry = odds_item("w1", attempt=2, purpose="RETRY", not_after="2026-10-02T00:00:00.000000Z")
            with self.assertRaises(PlanRefused) as caught:
                rt.runner.acquire(retry)
            self.assertEqual(caught.exception.reason, "NOT_RETRYABLE")

    def test_a_duplicate_plan_item_reports_why_the_attempt_was_rejected(self):
        with scratch_root() as root:
            rt, aid = self.poisoned(root)
            duplicate = rt.runner.acquire(odds_item("w1"))
            self.assertEqual((duplicate.outcome, duplicate.failure.value), ("DUPLICATE", "DERIVATION_FAULT"))


# ---------------------------------------------------------------------------------------------------------
LITERALS = [
    "1E+999999999", "1E-999999999", "-1E+999999999", "1E+999999", "1E+1000000", "0E+999999999", "1e5", "-0", "-0.0",
    "0e0", "9" * 70, "9" * 400, "1" + "0" * 4200, '"2.5"', '"abc"', '""', "true", "false", "null", "[]", "{}",
    '"\\ud800"', '"\\udfff"', '"\\u0000"', '"\\n"', '"a\\nb"', '"\\u00e9"', '"\\ud83d\\ude00"', '"x" ',
    '"2026-10-03T14:00:00.000Z"', '"9999-12-31T23:59:59.999Z"', '"0001-01-01T00:00:00.000Z"',
    '"2026-10-03T14:00:00+99:99"', '"2026-02-30T14:00:00Z"', '"2026-10-03"', "10", "-1", "0", "1",
    "1000000000000000000000000", "18446744073709551616", "2.5", "1.0", "1.01", "1000.0001", '"1"', '"0"', "1.5",
    "[1,2]", '{"a":{"b":{"c":[]}}}', '"' + "A" * 20000 + '"', '"' + "\\ud800" * 10 + '"',
    "[" * 80 + "0" + "]" * 80, "[" * 700 + "0" + "]" * 700, '"9' + "9" * 5000 + '"', '"1E+999999999"', '"-1E-999999999"',
]
KEYS = ["x", "", "a" * 70, "\\ud800", "9" * 5000, "²", "bookmakerOdds", "markets", "outcomes", "players", "price",
        "active", "fixtureId", "tournamentId"]


def paths(node, base=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield base + (key,)
            yield from paths(value, base + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield base + (index,)
            yield from paths(value, base + (index,))


def at(node, path):
    for key in path:
        node = node[key]
    return node


def encode(payload, literals) -> bytes | None:
    text = json.dumps(payload, sort_keys=True)
    for index, value in enumerate(literals):
        text = text.replace('"@L%d"' % index, value)
    try:
        return text.encode("ascii") if text.isascii() else text.encode("utf-8", "surrogatepass")
    except UnicodeError:
        return None


BASE_PAYLOAD = ps.odds_payload()
BASE_PATHS = list(paths(BASE_PAYLOAD))
BASE_LEAVES = [path for path in BASE_PATHS if not isinstance(at(BASE_PAYLOAD, path), (dict, list))]


class FuzzTotalityTests(unittest.TestCase):
    """Seeded property tests over the base ODDS fixture with the audit's hostile pool (probe p116/p119/p120)."""

    BASE, PATHS, LEAVES = BASE_PAYLOAD, BASE_PATHS, BASE_LEAVES

    def pure_stage(self, raw: bytes):
        """The raw pure stage (no safety net): returns the parsed response; any exception is the defect."""

        parsed = parser.parse_odds_response(raw, ps.make_ctx())
        if parsed.failure is None:
            normalize.build_documents(parsed, ps.make_ctx())
        return parsed

    def check(self, raw: bytes):
        parsed = self.pure_stage(raw)
        derived = derivation.derive(raw, ps.make_ctx())
        # the safety net exists for the unknown: no known class may be what it catches
        self.assertNotEqual(derived.failure, err.AdapterFailure.DERIVATION_FAULT, raw[:200])
        self.assertEqual(derived.failure, parsed.failure)

    def test_every_leaf_with_a_lone_surrogate(self):
        for leaf in self.LEAVES:
            payload = copy.deepcopy(self.BASE)
            at(payload, leaf[:-1])[leaf[-1]] = "\ud800"
            self.check(json.dumps(payload, sort_keys=True).encode("ascii"))

    def test_a_seeded_sample_of_leaves_with_each_numeric_and_structural_literal(self):
        rng = random.Random(20261003)
        literals = ["1E+999999999", "1E-999999999", "9" * 70, "9" * 400, "[" * 700 + "0" + "]" * 700,
                    "[" * 80 + "0" + "]" * 80, '"9' + "9" * 5000 + '"']
        for literal_text in literals:
            for leaf in rng.sample(self.LEAVES, 120):
                payload = copy.deepcopy(self.BASE)
                at(payload, leaf[:-1])[leaf[-1]] = "@L0"
                raw = encode(payload, [literal_text])
                self.check(raw)

    def test_a_seeded_mutation_fuzz_with_the_hostile_pool(self):
        rng = random.Random(11)
        for _ in range(900):
            payload = copy.deepcopy(self.BASE)
            for _ in range(rng.choice((1, 1, 2, 3))):
                path = rng.choice(self.PATHS)
                try:
                    op = rng.choice(("lit", "lit", "lit", "del", "addkey", "dupe"))
                    if op in ("lit", "dupe"):
                        at(payload, path[:-1])[path[-1]] = "@L%d" % rng.randrange(3)
                    elif op == "del":
                        parent = at(payload, path[:-1]) if len(path) > 1 else payload
                        if isinstance(parent, dict):
                            parent.pop(path[-1], None)
                    elif op == "addkey":
                        target = at(payload, path)
                        if isinstance(target, dict):
                            target[rng.choice(KEYS)] = "@L%d" % rng.randrange(3)
                except (KeyError, IndexError, TypeError):
                    pass
            raw = encode(payload, [rng.choice(LITERALS) for _ in range(3)])
            if raw is not None:
                self.check(raw)

    def test_the_snapshot_builder_turns_any_exception_into_an_unusable_join(self):
        for name, exc in FAULTS.items():
            with self.subTest(name), mock.patch.object(parser, "_fixture_snapshot", side_effect=copy.copy(exc)):
                self.assertIsNone(parser.build_fixture_snapshot(
                    b"[]", observation_id="o" * 64, retrieved_at=ps.T1, maps=ps.MAPS, policy=ps.POLICY,
                    fixtures_schema=ps.FIXTURES_SCHEMA))

    def test_the_fixtures_snapshot_builder_is_total_too(self):
        rng = random.Random(5)
        base = ps.load_fixture("fixtures.json")
        fixture_paths = list(paths(base))
        for _ in range(500):
            payload = copy.deepcopy(base)
            for _ in range(rng.choice((1, 2))):
                path = rng.choice(fixture_paths)
                try:
                    at(payload, path[:-1])[path[-1]] = "@L0"
                except (KeyError, IndexError, TypeError):
                    pass
            raw = encode(payload, [rng.choice(LITERALS)])
            if raw is None:
                continue
            parser.build_fixture_snapshot(raw, observation_id="o" * 64, retrieved_at=ps.T1, maps=ps.MAPS,
                                          policy=ps.POLICY, fixtures_schema=ps.FIXTURES_SCHEMA)   # must not raise


if __name__ == "__main__":
    unittest.main()
