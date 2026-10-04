"""R7 / RA6-002 (MEDIUM) - a response that triggers QUOTA_DIVERGENCE must not become usable because the process restarted.

The defect (inherited for "usage above the debit", widened by R6 because every unreadable usage header takes the same
path): the halt was durable but the response's own verdict stayed "clean". The live process correctly derived nothing
from it, but the next start (``resume()``, the first step of every G2R run) saw a successful capture and derived it
into usable OPEN documents - while the halt was still in force. The same durable ledger read "no observation" or "a
usable observation" depending on whether a start had run, against design 15 F-37 ("Observation / head: none; halt")
and the restart-convergence rule of 14.4.

The invariant: the fail-closed decision is part of the response's durable verdict, so the response is unusable in every
run order - uninterrupted, restarted once, restarted repeatedly, replayed or rebuilt - while the halt (and after any
authorized reset of it) is in force. Raw evidence is immutable and kept; evidence of earlier clean attempts stays usable;
nothing already written is rewritten.
"""

from __future__ import annotations

import contextlib
import unittest

from genesis_adapters import errors as err
from genesis_adapters.errors import AcquisitionHalt
from genesis_adapters.ids import gid
from genesis_adapters.oddspapi import acquisition, derivation, pipeline, quiescence
from genesis_adapters.oddspapi.acquisition import AcquisitionLedger
from genesis_adapters.oddspapi.reader import UsableBook, Unusable

from . import parser_support as ps
from .crash_support import cut
from .pipeline_support import (
    JSON, START, FixedClock, acquisition_rows, approve, coverage_rows, documents, fixture_body, fixtures_item, later_than,
    meta_item, ok, odds_item, odds_response, open_rt, pit_rows, reopen, summary,
)
from .support import Crash, scratch_root

A = err.AdapterFailure
USAGE = "x-requests-used"


def usage_headers(*values, name: str = USAGE):
    return JSON + tuple((name, value) for value in values)


OVER_THE_DEBIT = {"above_the_debit": ("3",),   # w1 and w2 debited 2 units in the month; 3 is one more than that "huge": ("99999",), "two_hundred_digits": ("9" * 200,),
                  "a_later_occurrence_above": ("1", "99999")}
UNREADABLE = {"words": ("not a number",), "scientific": ("1e5",), "thousands": ("99,999",), "negative": ("-5",),
              "fullwidth_digits": ("９９",), "empty": ("",), "over_the_kept_length": ("9" * 300,),
              "a_later_occurrence_unreadable": ("1", "oops")}
FORMS = {**OVER_THE_DEBIT, **UNREADABLE}
REPRESENTATIVE = {"above_the_debit": ("3",), "words": ("not a number",)}


def other_fixtures_item(window: str):
    """A FIXTURES request that differs from ``fixtures_item`` (the same request inside its TTL is a cache hit, no send)."""

    from genesis_adapters.oddspapi import endpoints as ep

    from .pipeline_support import SPECS
    from genesis_adapters.oddspapi.acquisition import PlanItem

    request = ep.build_request(SPECS["FIXTURES"], **{"from": "2026-10-02", "to": "2026-10-09", "sportId": 10,
                                                     "tournamentIds": [17, 8]})
    return PlanItem(window_id=window, purpose="SCHEDULED", request=request)


def attempt(window: str) -> str:
    item = odds_item(window)
    return acquisition.attempt_id(item.request.provider_request_hash, window, 1)


class Flow:
    """A healthy w1 (normalized and read), then the divergent w2 in the live process (the halt), then restarts."""

    def __init__(self, root, values, *, extra=(), raw_only: bool = False):
        self.aid, self.first = attempt("w2"), attempt("w1")
        self.clock = FixedClock(START, step_micros=1000)
        script = [odds_response(), odds_response(headers=usage_headers(*values)), *extra]
        self.rt = open_rt(root, clock=self.clock, script=script)
        self.rt.acquire(odds_item("w1"))
        approve(self.rt)
        self.entities = sorted({row["entity_id"] for row in pit_rows(self.rt)})
        self.clock.advance(seconds=900)
        self.raw_only = raw_only

    def divergent(self):
        """The live attempt that must halt (the exception is returned, the state is what a test then inspects)."""

        try:
            (self.rt.runner if self.raw_only else self.rt).acquire(odds_item("w2"))
        except AcquisitionHalt as halt:
            return halt
        raise AssertionError("the divergent response did not halt")

    def restart(self, **kw):
        """A new process over the same root: a clock later than anything the previous one wrote, and the same scripted
        provider (what it has not yet answered is still to come)."""

        if "clock" not in kw:
            now = max(self.rt.clock.peek(), later_than(self.rt))
            kw["clock"] = FixedClock(ps.iso_add(now, seconds=60), step_micros=1000)
        kw.setdefault("transport", self.rt.runner.transport)
        self.rt = reopen(self.rt, **kw)
        return self.rt

    def read(self, rt=None):
        rt = rt or self.rt
        return rt.reader().head(self.entities[0], ps.iso_add(rt.clock.peek(), seconds=30))

    def from_w2(self, rt=None):
        return [d for d in documents(rt or self.rt) if d["acquisition_id"] == self.aid]

    def state(self, rt=None):
        return (rt or self.rt).stores.acquisition.attempts()[self.aid].state


def served(result):
    """What a read yields, reduced to what must not depend on the run order."""

    if isinstance(result, UsableBook):
        return ("usable", result.document["acquisition_id"])
    return ("refused", result.code.value)


def durable_bytes(rt):
    names = ("acquisition.jsonl", "coverage.jsonl", "pit.jsonl", "identity.jsonl")
    return {name: (rt.root / name).read_bytes() if (rt.root / name).exists() else b"" for name in names}


def content(rt):
    coverage = sorted((row["entry_id"], row["entity_id"], row["status"], tuple(row["reason_codes"]), row["note"])
                      for row in coverage_rows(rt))
    rows = sorted((row["record_type"], row.get("acquisition_id"), row.get("failure"), row.get("reason"))
                  for row in acquisition_rows(rt))
    return {"coverage": coverage, "acquisition": rows, "pit": summary(rt)}


def halts(rt):
    return [row["reason"] for row in acquisition_rows(rt) if row["record_type"] == "acq_halted"]


class TheResponseIsUnusableInEveryRunOrderTests(unittest.TestCase):
    def test_every_usage_form_yields_the_same_outcome_uninterrupted_and_after_any_number_of_restarts(self):
        for label, values in FORMS.items():
            with self.subTest(label), scratch_root() as root:
                flow = Flow(root, values)
                before = summary(flow.rt)
                halt = flow.divergent()
                self.assertEqual(halt.code, A.QUOTA_DIVERGENCE)
                # the live process: nothing derived, nothing pending, the earlier clean evidence still served
                uninterrupted = (summary(flow.rt), served(flow.read()), quiescence.pending_work(flow.rt.stores),
                                 flow.state())
                self.assertEqual(uninterrupted[0], before)
                self.assertEqual(uninterrupted[1], ("usable", flow.first))
                self.assertEqual(uninterrupted[2], ())
                self.assertEqual(flow.from_w2(), [])
                for restart in range(1, 4):                              # the first G2R start, and again
                    rt = flow.restart()
                    rt.resume()
                    self.assertEqual(summary(rt), before, f"restart {restart} derived the divergent response")
                    self.assertEqual(flow.from_w2(), [], f"restart {restart}")
                    self.assertEqual(served(flow.read()), uninterrupted[1], f"restart {restart}")
                    self.assertEqual(quiescence.pending_work(rt.stores), (), f"restart {restart}")
                    self.assertEqual(flow.state(), uninterrupted[3], f"restart {restart}")
                self.assertEqual(halts(flow.rt), [A.QUOTA_DIVERGENCE.value], "the halt is still in force, once")

    def test_the_restarted_run_is_identical_to_the_uninterrupted_one(self):
        for label, values in REPRESENTATIVE.items():
            with self.subTest(label), scratch_root() as root:
                flow = Flow(root / "a", values)
                flow.divergent()
                reference = content(flow.rt)
                flow = Flow(root / "b", values)
                flow.divergent()
                flow.restart().resume()
                flow.restart().resume()
                self.assertEqual(content(flow.rt), reference)

    def test_the_g2_raw_only_run_followed_by_the_first_g2r_start_derives_nothing(self):
        # the operator flow: G2 captures raw only (no derivation); the first G2R start resumes every G2 capture
        for label, values in REPRESENTATIVE.items():
            with self.subTest(label), scratch_root() as root:
                flow = Flow(root, values, raw_only=True)
                before = summary(flow.rt)
                flow.divergent()
                flow.restart().resume()
                self.assertEqual(summary(flow.rt), before)
                self.assertEqual(flow.from_w2(), [])
                self.assertEqual(flow.state(), "COMPLETED")

    def test_the_verdict_is_in_the_durable_row_itself_not_in_a_flag_a_process_remembers(self):
        with scratch_root() as root:
            flow = Flow(root, ("99999",))
            flow.divergent()
            completed = [row for row in acquisition_rows(flow.rt) if row["record_type"] == "acq_completed"
                         and row["acquisition_id"] == flow.aid][0]
            self.assertEqual(completed["failure"], A.QUOTA_DIVERGENCE.value)
            self.assertEqual(completed["provider_reported_usage"]["reported"], 99999)
            self.assertIsNotNone(completed["raw_observation_id"])             # the raw evidence is retained

    def test_the_coverage_entry_is_the_one_f37_names_and_exactly_one(self):
        for label, values in REPRESENTATIVE.items():
            with self.subTest(label), scratch_root() as root:
                flow = Flow(root, values)
                flow.divergent()
                flow.restart().resume()
                notes = [(row["status"], tuple(row["reason_codes"])) for row in coverage_rows(flow.rt)
                         if row["note"] == "QUOTA_DIVERGENCE"]
                self.assertEqual(notes, [("not_attempted", ("configuration_mismatch",))])

    def test_a_response_that_failed_for_another_reason_keeps_that_reason_and_still_halts(self):
        # the divergence is the verdict of a response that PASSED its checks; one that failed keeps its own reason (the
        # ordinary content rejection) and the halt and its coverage entry follow exactly as for any other
        with scratch_root() as root:
            rt = open_rt(root, script=[ok(b"{", headers=usage_headers("99999"))])
            with self.assertRaises(AcquisitionHalt) as caught:
                rt.runner.acquire(odds_item("w1"))
            self.assertEqual(caught.exception.code, A.QUOTA_DIVERGENCE)
            completed = [row for row in acquisition_rows(rt) if row["record_type"] == "acq_completed"][0]
            self.assertEqual(completed["failure"], A.NOT_JSON.value)
            self.assertEqual(halts(rt), [A.QUOTA_DIVERGENCE.value])
            self.assertEqual(sorted(row["note"] for row in coverage_rows(rt)),
                             sorted([A.NOT_JSON.value, A.QUOTA_DIVERGENCE.value]))
            before = (acquisition_rows(rt), coverage_rows(rt))
            reopen(rt).resume()
            self.assertEqual((acquisition_rows(rt), coverage_rows(rt)), before)

    def test_a_usage_within_the_debit_is_never_a_divergence(self):
        for value in ("0", "1", " 1 ", "2"):               # up to the debit of 2 is only recorded
            with self.subTest(value), scratch_root() as root:
                flow = Flow(root, (value,))
                flow.rt.acquire(odds_item("w2"))
                self.assertEqual(halts(flow.rt), [])
                self.assertTrue(flow.from_w2())
                flow.restart().resume()
                self.assertTrue(flow.from_w2())


class TheHaltAndItsRecoveryTests(unittest.TestCase):
    def test_a_later_attempt_is_refused_by_the_halt_before_and_after_a_restart(self):
        with scratch_root() as root:
            flow = Flow(root, ("99999",), extra=(odds_response(),))
            flow.divergent()
            transport = flow.rt.runner.transport
            sent = len(transport.calls)                                        # w1 and w2: the whole script so far
            outcome = flow.rt.runner.acquire(odds_item("w3"))
            self.assertEqual((outcome.failure, outcome.detail), (A.CIRCUIT_OPEN, A.QUOTA_DIVERGENCE.value))
            flow.restart().resume()
            outcome = flow.rt.runner.acquire(odds_item("w4"))
            self.assertEqual((outcome.failure, outcome.detail), (A.CIRCUIT_OPEN, A.QUOTA_DIVERGENCE.value))
            self.assertEqual((sent, len(transport.calls)), (2, 2), "a send was made while the halt was in force")

    def test_an_authorized_reset_ends_the_halt_but_never_makes_the_divergent_response_usable(self):
        for label, values in REPRESENTATIVE.items():
            with self.subTest(label), scratch_root() as root:
                flow = Flow(root, values, extra=(odds_response(), odds_response()))
                flow.divergent()
                flow.restart().resume()
                ledger = AcquisitionLedger(flow.rt.root / "acquisition.jsonl")
                ledger.append("acq_operator_reset", recorded_at=later_than(flow.rt, 5),
                              approval_reference="human-review-ticket-1", reason="usage reconciled")
                self.assertIsNone(flow.rt.stores.acquisition.circuit_open("ODDS", later_than(flow.rt, 600)))
                for _ in range(2):                                            # after the reset: starts still derive nothing
                    flow.restart().resume()
                    self.assertEqual(flow.from_w2(), [])
                    self.assertEqual(flow.state(), "COMPLETED")
                healthy = flow.rt.acquire(odds_item("w3"))                    # a subsequent attempt works again
                self.assertIsNone(healthy.outcome.failure)
                self.assertTrue([d for d in documents(flow.rt) if d["acquisition_id"] == attempt("w3")])
                flow.restart().resume()
                self.assertEqual(flow.from_w2(), [])
                self.assertEqual(halts(flow.rt), [A.QUOTA_DIVERGENCE.value])

    def test_earlier_clean_evidence_is_neither_destroyed_nor_rewritten(self):
        with scratch_root() as root:
            flow = Flow(root, ("99999",))
            clean_rows = [dict(row) for row in pit_rows(flow.rt)]
            clean_docs = [flow.rt.stores.evidence.get_bytes(row["payload_hash"]) for row in clean_rows]
            first_ledger = acquisition_rows(flow.rt)
            flow.divergent()
            raw_id = [row for row in acquisition_rows(flow.rt) if row["record_type"] == "acq_completed"
                      and row["acquisition_id"] == flow.aid][0]["raw_observation_id"]
            raw = flow.rt.stores.evidence.get_observation(raw_id)
            raw_bytes = flow.rt.stores.evidence.get_bytes(raw.artifact_hash)
            for _ in range(3):
                flow.restart().resume()
            self.assertEqual([dict(row) for row in pit_rows(flow.rt)], clean_rows)
            self.assertEqual([flow.rt.stores.evidence.get_bytes(row["payload_hash"]) for row in clean_rows], clean_docs)
            self.assertEqual(acquisition_rows(flow.rt)[:len(first_ledger)], first_ledger)      # append-only: untouched
            self.assertEqual(flow.rt.stores.evidence.get_bytes(raw.artifact_hash), raw_bytes)  # raw is immutable
            self.assertEqual(flow.rt.stores.evidence.get_observation(raw_id), raw)
            self.assertEqual(flow.rt.verify_all(), len(clean_rows))                            # still re-derives exactly

    def test_a_replay_and_a_rebuild_never_derive_the_divergent_response(self):
        with scratch_root() as root:
            flow = Flow(root / "source", ("not a number",))
            flow.divergent()
            flow.restart().resume()
            target = pipeline.build_stores(root / "target", derivation_version=flow.rt.config.derivation_version,
                                           policy=flow.rt.config.policy, licensing_note=pipeline.FIXTURE_LICENSING_NOTE)
            rebuilt = pipeline.rebuild_into(flow.rt, target, clock=FixedClock("2026-12-01T00:00:00.000000Z",
                                                                                step_micros=10))
            self.assertEqual(len(rebuilt), 1)                                  # w1 only
            rows = acquisition_rows(flow.rt)
            self.assertFalse([row for row in rows if row["record_type"] == "acq_normalized"
                              and row["acquisition_id"] == flow.aid])
            rec = derivation.acquisition_rows(flow.rt.stores.acquisition, flow.aid)
            self.assertFalse(derivation.successful_capture(rec))
            with self.assertRaisesRegex(derivation.DerivationError, "not a successful ODDS acquisition"):
                flow.rt._inputs(flow.aid)


class CrashBoundariesAroundTheQuotaVerdictTests(unittest.TestCase):
    """The verdict and the response's disposition are ONE durable row; what a crash can cut is the halt and coverage that
    follow it, and the restart completes both. Nothing in any cut makes the response usable."""

    def reference(self, root, values):
        flow = Flow(root, values)
        flow.divergent()
        flow.restart().resume()
        return content(flow.rt)

    def cut_run(self, root, values, hit, where):
        flow = Flow(root, values)
        with cut(AcquisitionLedger, hit, where=where) as state:
            with contextlib.suppress(Crash):
                flow.divergent()
        return flow, state

    def test_a_cut_after_the_verdict_row_still_halts_and_derives_nothing_after_restart(self):
        for label, values in REPRESENTATIVE.items():
            with self.subTest(label), scratch_root() as root:
                reference = self.reference(root / "ref", values)
                flow, state = self.cut_run(
                    root / "cut", values, where="after",
                    hit=lambda args, kwargs: args[0] == "acq_completed" and kwargs.get("acquisition_id") == attempt("w2"))
                self.assertEqual(state["fired"], 1)
                self.assertEqual(halts(flow.rt), [])                          # the halt had not been written yet
                before = summary(flow.rt)
                flow.restart().resume()
                self.assertEqual(halts(flow.rt), [A.QUOTA_DIVERGENCE.value])
                self.assertEqual(summary(flow.rt), before)
                self.assertEqual(flow.from_w2(), [])
                self.assertEqual(content(flow.rt), reference)

    def test_a_cut_between_the_halt_and_the_coverage_entry_converges_after_restart(self):
        for label, values in REPRESENTATIVE.items():
            with self.subTest(label), scratch_root() as root:
                reference = self.reference(root / "ref", values)
                flow, state = self.cut_run(root / "cut", values, where="after",
                                           hit=lambda args, kwargs: args[0] == "acq_halted")
                self.assertEqual(state["fired"], 1)
                flow.restart().resume()
                flow.restart().resume()
                self.assertEqual(flow.from_w2(), [])
                self.assertEqual(content(flow.rt), reference)

    def test_a_cut_before_the_verdict_row_loses_the_response_not_the_safety(self):
        # nothing about the response is durable except the raw bytes: the attempt is an orphan, reconciled on restart, and
        # no document can ever be derived from an attempt that has no completed row
        with scratch_root() as root:
            flow, state = self.cut_run(
                root, ("99999",), where="before",
                hit=lambda args, kwargs: args[0] == "acq_completed" and kwargs.get("acquisition_id") == attempt("w2"))
            self.assertEqual(state["fired"], 1)
            before = summary(flow.rt)
            reconciled = flow.restart().resume()[0]
            self.assertEqual(reconciled, (attempt("w2"),))
            flow.restart().resume()
            self.assertEqual(summary(flow.rt), before)
            self.assertEqual(flow.from_w2(), [])
            self.assertEqual(flow.state(), "RECONCILED")

    def test_the_production_checkpoint_after_completed_is_recovered_the_same_way(self):
        with scratch_root() as root:
            flow = Flow(root, ("99999",))

            def die(step):
                if step == "after_completed":
                    raise Crash()

            flow.restart(runner_checkpoint=die)
            with self.assertRaises(Crash):
                flow.rt.acquire(odds_item("w2"))
            before = summary(flow.rt)
            flow.restart().resume()
            self.assertEqual((halts(flow.rt), summary(flow.rt), flow.from_w2()), ([A.QUOTA_DIVERGENCE.value], before, []))


class OtherRolesTests(unittest.TestCase):
    """A divergent response of any role carries the same verdict: it is no fixture join and no cache entry either."""

    def test_a_divergent_fixtures_response_is_never_the_fixture_join(self):
        with scratch_root() as root:
            clock = FixedClock(START, step_micros=1000)
            rt = open_rt(root, clock=clock, script=[ok(fixture_body("fixtures.json"), headers=JSON),
                                                    ok(fixture_body("fixtures.json"),
                                                       headers=usage_headers("99999"))])
            first = rt.acquire(fixtures_item("wf1"))
            clock.advance(seconds=600)
            with self.assertRaises(AcquisitionHalt):
                rt.acquire(other_fixtures_item("wf2"))
            at = ps.iso_add(clock.peek(), seconds=60)
            for process in (rt, reopen(rt)):                                   # in the live process and after a restart
                snapshot = derivation.fixture_snapshot_for(process.stores, process.config, process.maps, at=at)
                self.assertEqual(snapshot.observation_id, first.outcome.captured.raw_observation_id)

    def test_a_divergent_metadata_response_is_never_cached(self):
        with scratch_root() as root:
            clock = FixedClock(START, step_micros=1000)
            rt = open_rt(root, clock=clock, script=[ok(fixture_body("tournaments.json"), headers=usage_headers("99999")),
                                                    ok(fixture_body("tournaments.json"), headers=JSON)])
            with self.assertRaises(AcquisitionHalt):
                rt.acquire(meta_item("META_TOURNAMENTS", window="wm1"))
            self.assertEqual(rt.gate._index.records(), [])
            restarted = reopen(rt)
            restarted.resume()
            self.assertEqual(restarted.gate._index.records(), [])


class AnEarlierCodeVersionsLedgerIsHonouredTests(unittest.TestCase):
    """A ledger written before the verdict was recorded in the row (completed ``failure`` None, the halt and the usage
    figure present) is read the same way: the usage figure in the very row is the durable disposition."""

    @staticmethod
    def as_an_earlier_version_wrote_it(rt, aid):
        from genesis.registry import AppendOnlyJsonl
        from genesis.repro import canonical_json

        chained, out = [], []
        for row in rt.stores.acquisition.rows():
            body = {key: value for key, value in row.items() if key not in ("previous_hash", "sequence", "record_hash")}
            if body["record_type"] == "acq_completed" and body["acquisition_id"] == aid:
                body["failure"] = None
            row = AppendOnlyJsonl.chained(chained, body)
            chained.append(row)
            out.append(canonical_json(row))
        (rt.root / "acquisition.jsonl").write_bytes(b"".join(out))

    def test_such_a_row_is_not_a_successful_capture_and_no_start_derives_it(self):
        for label, values in REPRESENTATIVE.items():
            with self.subTest(label), scratch_root() as root:
                flow = Flow(root, values)
                before = summary(flow.rt)
                flow.divergent()
                self.as_an_earlier_version_wrote_it(flow.rt, flow.aid)
                completed = [row for row in flow.rt.stores.acquisition.rows() if row["record_type"] == "acq_completed"
                             and row["acquisition_id"] == flow.aid][0]
                self.assertIsNone(completed["failure"])
                self.assertFalse(derivation.successful_capture(
                    derivation.acquisition_rows(flow.rt.stores.acquisition, flow.aid)))
                self.assertEqual(quiescence.pending_work(flow.rt.stores), ())
                for _ in range(2):
                    flow.restart().resume()
                    self.assertEqual(summary(flow.rt), before)
                    self.assertEqual(flow.from_w2(), [])

    def test_such_a_row_is_not_a_fixture_join_either(self):
        with scratch_root() as root:
            clock = FixedClock(START, step_micros=1000)
            rt = open_rt(root, clock=clock, script=[ok(fixture_body("fixtures.json"), headers=JSON),
                                                    ok(fixture_body("fixtures.json"), headers=usage_headers("99999"))])
            first = rt.acquire(fixtures_item("wf1"))
            clock.advance(seconds=600)
            with self.assertRaises(AcquisitionHalt):
                rt.acquire(other_fixtures_item("wf2"))
            second = attempt_of(rt, "wf2")
            self.as_an_earlier_version_wrote_it(rt, second)
            process = reopen(rt)
            snapshot = derivation.fixture_snapshot_for(process.stores, process.config, process.maps,
                                                       at=ps.iso_add(clock.peek(), seconds=60))
            self.assertEqual(snapshot.observation_id, first.outcome.captured.raw_observation_id)


def attempt_of(rt, window: str) -> str:
    return [row["acquisition_id"] for row in acquisition_rows(rt)
            if row["record_type"] == "acq_planned" and row["window_id"] == window][0]


if __name__ == "__main__":
    unittest.main()
