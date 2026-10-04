"""R7 / RA6-001 (MEDIUM) - a crash at ANY persistence boundary around a derivation rejection never leaves the rejection
row, the coverage ledger and the reader silently disagreeing.

The defect (R6): ``reject_derivation`` writes the terminal ``acq_derivation_rejected`` row and then settles its REJECTED
coverage entry. A crash (or an I/O error) between the two lost that entry for ever whenever the capture was not the
NEWEST planned attempt - which is the normal G2 -> first G2R case, because ``resume()`` derives every G2 capture in ledger
order - since the restart settled only the newest attempt. Nothing reported the gap: ``pending_work()`` was empty, so the
reader served as if nothing were unfinished.

The invariant (design 11.1, 14.4, 15 D13): after a restart the stores deterministically reach the complete intended
REJECTED state, rebuilt from the durable verdict row alone, or refuse explicitly. Silent permanent loss is forbidden, a
restart is idempotent, a crash DURING the recovery is itself recoverable, and reads refuse while the gap exists.

The boundaries are injected at the persistence layer (the ledger appends), not at named checkpoints, so the same test
drives the unmodified R6 code (RED) and the fix (GREEN): immediately before / after the rejection row, immediately
before / after the coverage entry, and an I/O error on either write.
"""

from __future__ import annotations

import contextlib
import errno
import unittest
from unittest import mock

from genesis.coverage import CoverageLedger, CoverageStatus
from genesis.registry import RegistryConflict

from genesis_adapters.errors import AdapterFailure
from genesis_adapters.ids import gid
from genesis_adapters.oddspapi import acquisition, derivation, pipeline, quiescence
from genesis_adapters.oddspapi.acquisition import AcquisitionLedger
from genesis_adapters.oddspapi.endpoints import RAW_CONTRACT_ID
from genesis_adapters.oddspapi.reader import UsableBook, Unusable

from . import parser_support as ps
from .crash_support import cut
from .pipeline_support import (
    JSON, START, FixedClock, acquisition_rows, approve, coverage_rows, documents, ok, odds_item, odds_response,
    later_than, open_rt, pit_rows, reopen, summary,
)
from .support import Crash, scratch_root

GAP = "a derivation rejection's coverage entry is not recorded yet"
CONFLICT = "a derivation rejection's coverage entry conflicts with its verdict"


def poisoned_body() -> bytes:
    """A syntactically valid 200 body whose derivation is refused for good (a ``fixtureId`` outside the grammar)."""

    payload = ps.odds_payload()
    ps.fixture_of(payload)["fixtureId"] = "not a valid id"
    return ps.dump(payload)


def attempt(window: str) -> str:
    item = odds_item(window)
    return acquisition.attempt_id(item.request.provider_request_hash, window, 1)


# ---------------------------------------------------------------------------------------------------------
# fault injection at the persistence boundaries
# ---------------------------------------------------------------------------------------------------------
class Boundary:
    """One persistence boundary: the ledger whose append is cut, and whether the process dies just BEFORE the append
    (nothing written) or just AFTER it (written, durable). ``error`` replaces the death by an I/O error."""

    def __init__(self, name, ledger, where, *, error=None):
        self.name, self.ledger, self.where, self.error = name, ledger, where, error

    def __repr__(self):
        return self.name

    @contextlib.contextmanager
    def armed(self, aid: str):
        """Arm the boundary for the rejection of attempt ``aid`` (a healthy capture's own REJECTED coverage entries -
        out-of-scope books - are not the boundary), once."""

        entries = {gid("cov", acquisition_id=aid, note=failure.value) for failure in AdapterFailure}
        if self.ledger == "rejection":
            owner = AcquisitionLedger
            hit = lambda args, kwargs: args[0] == "acq_derivation_rejected" and kwargs.get("acquisition_id") == aid
        else:
            owner, hit = CoverageLedger, lambda args, kwargs: args[0].entry_id in entries
        with cut(owner, hit, where=self.where, error=self.error) as state:
            yield state


BEFORE_ROW = Boundary("before_rejection_row", "rejection", "before")
AFTER_ROW = Boundary("after_rejection_row_before_coverage", "rejection", "after")
BEFORE_COVERAGE = Boundary("before_coverage_write", "coverage", "before")
AFTER_COVERAGE = Boundary("after_coverage_write", "coverage", "after")
ROW_IO_ERROR = Boundary("rejection_row_io_error", "rejection", "before", error=OSError(errno.ENOSPC, "no space"))
COVERAGE_IO_ERROR = Boundary("coverage_io_error", "coverage", "before", error=OSError(errno.ENOSPC, "no space"))
BOUNDARIES = (BEFORE_ROW, AFTER_ROW, BEFORE_COVERAGE, AFTER_COVERAGE, ROW_IO_ERROR, COVERAGE_IO_ERROR)
# what is durable right after the cut: (rejection rows, coverage entries)
DURABLE_AFTER = {BEFORE_ROW: (0, 0), AFTER_ROW: (1, 0), BEFORE_COVERAGE: (1, 0), AFTER_COVERAGE: (1, 1),
                 ROW_IO_ERROR: (0, 0), COVERAGE_IO_ERROR: (1, 0)}


class Flow:
    """healthy w1 (normalized) -> the poisoned w2 -> [a healthy w3] -> the start that derives w2 -> restarts.

    ``live-newest``  the poisoned response is derived by the live path, right after it is received (the newest attempt);
    ``g2r-newest``   G2 captured it raw-only, the first G2R start derives it, and it is still the newest attempt;
    ``g2r-older``    G2 captured it raw-only and a healthy w3 after it, so the first G2R start derives an OLDER capture.
    """

    KINDS = ("live-newest", "g2r-newest", "g2r-older")

    def __init__(self, root, kind: str):
        self.kind = kind
        self.aid = attempt("w2")
        self.clock = FixedClock(START, step_micros=1000)
        script = [odds_response(), ok(poisoned_body(), headers=JSON)] + ([odds_response()] if kind == "g2r-older" else [])
        self.rt = open_rt(root, clock=self.clock, script=script)
        self.rt.acquire(odds_item("w1"))
        approve(self.rt)
        self.entities = sorted({row["entity_id"] for row in pit_rows(self.rt)})
        self.clock.advance(seconds=900)
        if kind != "live-newest":                                   # G2: raw evidence only, nothing derived
            self.rt.runner.acquire(odds_item("w2"))
            if kind == "g2r-older":
                self.clock.advance(seconds=900)
                self.rt.runner.acquire(odds_item("w3"))

    def first_start(self):
        """The step that derives the poisoned capture (and is cut by the armed boundary)."""

        if self.kind == "live-newest":
            return self.rt.acquire(odds_item("w2"))
        return self.restart().resume()

    def restart(self, **kw):
        """A new process over the same root, whose clock is later than anything the previous one wrote (a real clock
        never runs backwards past an aborted emission)."""

        if "clock" not in kw:
            now = max(self.rt.clock.peek(), later_than(self.rt))
            kw["clock"] = FixedClock(ps.iso_add(now, seconds=60), step_micros=1000)
        kw.setdefault("transport", self.rt.runner.transport)
        self.rt = reopen(self.rt, **kw)
        return self.rt

    def read(self, rt=None):
        rt = rt or self.rt
        return rt.reader().head(self.entities[0], ps.iso_add(rt.clock.peek(), seconds=30))


def rejection_rows(rt, aid):
    return [row for row in acquisition_rows(rt) if row.get("acquisition_id") == aid
            and row["record_type"] == "acq_derivation_rejected"]


def coverage_for(rt, aid):
    rejected = rejection_rows(rt, aid)
    if not rejected:
        return []
    wanted = gid("cov", acquisition_id=aid, note=rejected[0]["failure"])
    return [row for row in coverage_rows(rt) if row["entry_id"] == wanted]


def durable_bytes(rt):
    names = ("acquisition.jsonl", "coverage.jsonl", "pit.jsonl", "identity.jsonl")
    return {name: (rt.root / name).read_bytes() if (rt.root / name).exists() else b"" for name in names}


def content(rt):
    """The durable history without clock-dependent fields: what an uninterrupted run and a recovered run must share."""

    keep = lambda row, names: {name: row[name] for name in names}
    coverage = sorted((row["entry_id"], row["entity_id"], row["status"], tuple(row["reason_codes"]), row["note"])
                      for row in coverage_rows(rt))
    rows = sorted((row["record_type"], row.get("acquisition_id"), row.get("failure"), row.get("reason"))
                  for row in acquisition_rows(rt))
    return {"coverage": coverage, "acquisition": rows, "pit": summary(rt)}


def crashed_flow(root, kind, boundary):
    flow = Flow(root, kind)
    with boundary.armed(flow.aid) as state:
        with contextlib.suppress(Crash, OSError):
            flow.first_start()
    return flow, state


class DerivationRejectionCrashMatrixTests(unittest.TestCase):
    def test_every_boundary_for_every_flow_ends_in_the_complete_rejected_state(self):
        for kind in Flow.KINDS:
            for boundary in BOUNDARIES:
                with self.subTest(flow=kind, boundary=boundary), scratch_root() as root:
                    flow, state = crashed_flow(root, kind, boundary)
                    self.assertEqual(state["fired"], 1, "the boundary was never reached")
                    rows, entries = DURABLE_AFTER[boundary]
                    self.assertEqual((len(rejection_rows(flow.rt, flow.aid)), len(coverage_for(flow.rt, flow.aid))),
                                     (rows, entries), "the cut left a different durable state than the test models")
                    flow.restart().resume()                                      # the first start after the cut
                    rt = flow.rt
                    self.assertEqual(len(rejection_rows(rt, flow.aid)), 1)
                    covered = coverage_for(rt, flow.aid)
                    self.assertEqual(len(covered), 1, "the REJECTED coverage entry is missing or doubled")
                    self.assertEqual((covered[0]["status"], covered[0]["reason_codes"], covered[0]["note"]),
                                     ("rejected", ["schema_rejected"], rejection_rows(rt, flow.aid)[0]["failure"]))
                    self.assertEqual(quiescence.pending_work(rt.stores), ())
                    self.assertEqual(rt.stores.acquisition.attempts()[flow.aid].state, "DERIVATION_REJECTED")
                    self.assertFalse([d for d in documents(rt) if d["acquisition_id"] == flow.aid])
                    self.assertIsInstance(flow.read(), UsableBook)

    def test_the_audit_checkpoint_after_derivation_rejected_for_a_newer_attempt_is_recovered(self):
        # the audit's own reproduction (probe a01): the production checkpoint, G2 -> G2R, a newer attempt follows
        with scratch_root() as root:
            flow = Flow(root, "g2r-older")

            def die(step):
                if step == "after_derivation_rejected":
                    raise Crash()

            flow.restart(runner_checkpoint=die)
            with self.assertRaises(Crash):
                flow.rt.resume()
            self.assertEqual((len(rejection_rows(flow.rt, flow.aid)), len(coverage_for(flow.rt, flow.aid))), (1, 0))
            flow.restart().resume()
            flow.restart().resume()
            self.assertEqual(len(coverage_for(flow.rt, flow.aid)), 1)
            self.assertEqual(quiescence.pending_work(flow.rt.stores), ())

    def test_the_recovered_history_equals_an_uninterrupted_run(self):
        for kind in Flow.KINDS:
            with scratch_root() as root:
                flow = Flow(root / "reference", kind)
                flow.first_start()
                flow.restart().resume()
                reference = content(flow.rt)
            for boundary in BOUNDARIES:
                with self.subTest(flow=kind, boundary=boundary), scratch_root() as scratch:
                    flow, _ = crashed_flow(scratch, kind, boundary)
                    flow.restart().resume()
                    self.assertEqual(content(flow.rt), reference)


class ReadsBeforeAndAfterReconciliationTests(unittest.TestCase):
    """The durable state is the witness (design 6.3): the reader refuses while the gap exists and serves once it is
    closed - never as if nothing were unfinished."""

    def test_a_rejection_without_its_coverage_entry_is_pending_work_and_reads_are_refused(self):
        for kind in Flow.KINDS:
            for boundary in (AFTER_ROW, BEFORE_COVERAGE, COVERAGE_IO_ERROR):
                with self.subTest(flow=kind, boundary=boundary), scratch_root() as root:
                    flow, _ = crashed_flow(root, kind, boundary)
                    rt = flow.restart()                                          # a new process, NOT yet resumed
                    self.assertIn(GAP, quiescence.pending_work(rt.stores))
                    refused = flow.read(rt)
                    self.assertIsInstance(refused, Unusable)
                    self.assertEqual(refused.code.value, "DATA_CAPABILITY_NOT_READY")
                    rt.resume()
                    self.assertNotIn(GAP, quiescence.pending_work(rt.stores))
                    self.assertIsInstance(flow.read(rt), UsableBook)

    def test_a_rejection_that_is_fully_recorded_is_not_pending(self):
        with scratch_root() as root:
            flow, _ = crashed_flow(root, "g2r-newest", AFTER_COVERAGE)
            rt = flow.restart()
            self.assertEqual(quiescence.pending_work(rt.stores), ())
            self.assertIsInstance(flow.read(rt), UsableBook)

    def test_a_cut_before_the_row_is_the_ordinary_unfinished_capture(self):
        with scratch_root() as root:
            flow, _ = crashed_flow(root, "g2r-newest", BEFORE_ROW)
            self.assertIn("a successful ODDS capture is not normalized yet", quiescence.pending_work(flow.rt.stores))
            self.assertIsInstance(flow.read(flow.restart()), Unusable)


class RestartIsIdempotentAndRecoverableTests(unittest.TestCase):
    def test_restarting_repeatedly_changes_nothing_after_the_first_recovery(self):
        for kind in Flow.KINDS:
            for boundary in (AFTER_ROW, COVERAGE_IO_ERROR, BEFORE_ROW):
                with self.subTest(flow=kind, boundary=boundary), scratch_root() as root:
                    flow, _ = crashed_flow(root, kind, boundary)
                    flow.restart().resume()
                    settled = durable_bytes(flow.rt)
                    for _ in range(3):
                        flow.restart().resume()
                        self.assertEqual(durable_bytes(flow.rt), settled)
                    self.assertEqual(len(coverage_for(flow.rt, flow.aid)), 1)

    def test_a_crash_during_the_recovery_is_itself_recovered(self):
        for kind in Flow.KINDS:
            for first in (AFTER_ROW, BEFORE_COVERAGE):
                for second in (BEFORE_COVERAGE, AFTER_COVERAGE, COVERAGE_IO_ERROR):
                    with self.subTest(flow=kind, first=first, second=second), scratch_root() as root:
                        flow, _ = crashed_flow(root, kind, first)
                        with second.armed(flow.aid) as state, contextlib.suppress(Crash, OSError):
                            flow.restart().resume()                              # the recovery itself is cut
                        self.assertEqual(state["fired"], 1, "the recovery never reached the coverage write")
                        flow.restart().resume()
                        self.assertEqual(len(coverage_for(flow.rt, flow.aid)), 1)
                        self.assertEqual(quiescence.pending_work(flow.rt.stores), ())
                        settled = durable_bytes(flow.rt)
                        flow.restart().resume()
                        self.assertEqual(durable_bytes(flow.rt), settled)

    def test_the_rejection_is_never_derived_again(self):
        for kind in Flow.KINDS:
            with self.subTest(flow=kind), scratch_root() as root:
                flow, _ = crashed_flow(root, kind, AFTER_ROW)
                calls = []
                real = derivation.derive

                def spy(raw, ctx):
                    calls.append(ctx.acquisition_id)
                    return real(raw, ctx)

                with mock.patch.object(derivation, "derive", spy):
                    flow.restart().resume()
                    flow.restart().resume()
                self.assertNotIn(flow.aid, calls)

    def test_recovery_needs_only_the_durable_row_not_the_process_that_wrote_it(self):
        # a different process object, a different clock and a different quota ledger instance: the same entry
        with scratch_root() as root:
            flow, _ = crashed_flow(root, "g2r-older", AFTER_ROW)
            flow.restart(clock=FixedClock("2027-01-01T00:00:00.000000Z", step_micros=1000)).resume()
            self.assertEqual(len(coverage_for(flow.rt, flow.aid)), 1)
            entry = coverage_for(flow.rt, flow.aid)[0]
            self.assertEqual(entry["entity_id"], "oddspapi-request:" + odds_item("w2").request.provider_request_hash)
            # settlement never reads the clock: the entry is stamped from the durable history (never earlier than its row)
            self.assertGreaterEqual(entry["recorded_at"], rejection_rows(flow.rt, flow.aid)[0]["recorded_at"])


class ConflictingEvidenceFailsClosedTests(unittest.TestCase):
    """The recovery rebuilds the entry from the verdict row; evidence that contradicts the verdict is never adopted,
    papered over or overwritten: the start is refused, explicitly and repeatably, and nothing is written."""

    def conflicting(self, root, **changes):
        flow, _ = crashed_flow(root, "g2r-older", AFTER_ROW)
        rejected = rejection_rows(flow.rt, flow.aid)[0]
        from genesis.coverage import CoverageEntry
        from genesis.reasons import ReasonCode

        entry = dict(entry_id=gid("cov", acquisition_id=flow.aid, note=rejected["failure"]),
                     entity_id="oddspapi-request:" + odds_item("w2").request.provider_request_hash,
                     source_contract_id=RAW_CONTRACT_ID, status=CoverageStatus.REJECTED,
                     recorded_at=rejected["recorded_at"], reason_codes=(ReasonCode.SCHEMA_REJECTED,),
                     note=rejected["failure"])
        entry.update(changes)
        CoverageLedger(flow.rt.root / "coverage.jsonl").append(CoverageEntry(**entry))
        return flow

    def test_an_entry_with_the_intended_id_but_other_content_refuses_every_start(self):
        from genesis.reasons import ReasonCode

        for label, changes in {
                "status": dict(status=CoverageStatus.QUARANTINED, reason_codes=(ReasonCode.ARTIFACT_TAMPERED,)),
                "reason": dict(reason_codes=(ReasonCode.MISSING_EVIDENCE,)),
                "entity": dict(entity_id="oddspapi-request:" + "0" * 64),
                "note": dict(note="SOMETHING_ELSE")}.items():
            with self.subTest(label), scratch_root() as root:
                flow = self.conflicting(root, **changes)
                before = durable_bytes(flow.rt)
                for _ in range(2):
                    with self.assertRaises(RegistryConflict) as caught:
                        flow.restart().resume()
                    self.assertEqual(type(caught.exception).__name__, "SettlementConflict")
                self.assertEqual(durable_bytes(flow.rt)["acquisition.jsonl"], before["acquisition.jsonl"])
                self.assertEqual(len(coverage_for(flow.rt, flow.aid)), 1, "the conflicting entry was added to or replaced")
                self.assertIn(CONFLICT, quiescence.pending_work(flow.rt.stores))   # reading is refused while it stands
                self.assertIsInstance(flow.read(), Unusable)

    def test_the_runner_never_sends_while_the_conflict_stands(self):
        from genesis.reasons import ReasonCode

        with scratch_root() as root:
            flow = self.conflicting(root, status=CoverageStatus.QUARANTINED,
                                    reason_codes=(ReasonCode.ARTIFACT_TAMPERED,))
            rt = flow.restart()
            sent = len(rt.runner.transport.calls)
            with self.assertRaises(RegistryConflict):
                rt.runner.acquire(odds_item("w9"))
            self.assertEqual(len(rt.runner.transport.calls), sent)

    def test_an_identical_entry_is_idempotent_not_a_conflict(self):
        with scratch_root() as root:
            flow = self.conflicting(root)                                       # exactly the intended entry
            flow.restart().resume()
            self.assertEqual(len(coverage_for(flow.rt, flow.aid)), 1)
            self.assertNotIn(CONFLICT, quiescence.pending_work(flow.rt.stores))


class EveryOlderVerdictIsSettledTests(unittest.TestCase):
    """The root cause is not specific to the rejection row: a restart settled only the NEWEST planned attempt, so any
    verdict row written for an older attempt lost its side effects when a crash cut them short."""

    def test_the_reconciliation_of_an_older_orphan_survives_a_crash_after_its_row(self):
        with scratch_root() as root:
            clock = FixedClock(START, step_micros=1000)
            seen = []

            def die_after_sent(step):
                if step == "after_sent" and not seen:
                    seen.append(step)
                    raise Crash()

            rt = open_rt(root, clock=clock, script=[odds_response(), odds_response()], runner_checkpoint=die_after_sent)
            with self.assertRaises(Crash):
                rt.runner.acquire(odds_item("w1"))                              # open: sent, never completed
            older = attempt("w1")
            rt = reopen(rt)                                                     # NOT reconciled: a newer attempt follows
            rt.runner.acquire(odds_item("w2"))
            real = AcquisitionLedger.append
            fired = []

            def cut(this, kind, **kw):
                real(this, kind, **kw)
                if kind == "acq_reconciled" and not fired:
                    fired.append(kind)
                    raise Crash()

            rt = reopen(rt)
            with mock.patch.object(AcquisitionLedger, "append", cut), self.assertRaises(Crash):
                rt.runner.reconcile_after_restart()
            wanted = gid("cov", acquisition_id=older, note="RECONCILED")
            self.assertEqual([r for r in coverage_rows(rt) if r["entry_id"] == wanted], [])
            rt = reopen(rt)
            rt.runner.reconcile_after_restart()
            self.assertEqual(len([r for r in coverage_rows(rt) if r["entry_id"] == wanted]), 1)
            before = durable_bytes(rt)
            again = reopen(rt)
            again.runner.reconcile_after_restart()
            self.assertEqual(durable_bytes(again), before)

    def test_settling_every_attempt_never_repeats_an_effect_that_was_already_applied(self):
        # two rate-limited answers on the same UTC day (different roles): the second opens an ALL circuit, the first a
        # ROLE circuit. Settling the FIRST again must judge it as of its own verdict, not by today's later count
        from .pipeline_support import fixtures_item
        from .support import status

        with scratch_root() as root:
            clock = FixedClock(START, step_micros=1000)
            rt = open_rt(root, clock=clock, script=[status(429), status(429)])
            rt.runner.acquire(odds_item("w1"))
            clock.advance(seconds=60)
            rt.runner.acquire(fixtures_item("wf"))
            before = durable_bytes(rt)
            circuits = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_circuit_opened"]
            self.assertEqual([(c["scope"], c["role"]) for c in circuits], [("ROLE", "ODDS"), ("ALL", None)])
            rt = reopen(rt)
            rt.runner.reconcile_after_restart()
            rt.runner.settle_last()
            self.assertEqual(durable_bytes(rt), before)
            self.assertEqual([r for r in acquisition_rows(rt) if r["record_type"] == "acq_circuit_opened"], circuits)


if __name__ == "__main__":
    unittest.main()
