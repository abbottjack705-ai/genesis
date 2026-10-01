"""R4 - PIT recovery and consumption (controlling hostile audit hostile_audit_cfcff3d).

HA-05 (13.2 steps 3-5, 6.3): a recorded invalidation makes its record unusable at every cutoff at or after its T_inv,
    whether or not a crash stopped it before its INVALIDATED head was emitted; historical cutoffs before T_inv are
    unchanged; and every start completes, exactly once, the invalidations a crash left incomplete - nobody has to
    call ``invalidate()`` again.
HA-06 (6.2, 6.3, 14.4): one response keeps ONE T2 and ONE T3 across a crash anywhere in its emission (a resumed
    emission reuses exactly the times the interrupted one made durable); no decision reads the market books while an
    emission is unfinished; and the adapter run lock serializes adapter phases and decisions across processes.
HA-12 (12.3 step 7): the derivation verifier is mandatory on every consumption path (reader, manifest builder); a head
    that fails it is refused as DERIVATION_UNVERIFIED and invalidated automatically (13.2, ADAPTER_AUTOMATIC).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest

from genesis_adapters import errors as err
from genesis_adapters.secrets import Secret
from genesis_adapters.oddspapi import emit
from genesis_adapters.oddspapi.derivation import DerivationError
from genesis_adapters.oddspapi.manifest import ManifestError, build_manifest_body
from genesis_adapters.oddspapi.reader import MarketBookReader, UsableBook, admissible_head

from . import emit_support as es
from .emit_support import CAPTURE_1, build_stores, capture, iso, small_payload
from .emit_support import pit_rows as store_pit_rows
from .parity_support import verifier_verdict
from .pipeline_support import JSON, approve, odds_item, odds_response, open_rt, pit_rows, reopen
from .support import REPO, SENTINEL_KEY, Crash, SequenceClock, ok, scratch_root
from .test_v05_invalidation import T_INV, invalidate, one_capture

F = err.AdapterFailure
ACCEPT = es.derivation_accepted


def crash_at(step: str):
    def hook(name):
        if name == step:
            raise Crash()
    return hook


def recorder(names: list):
    def hook(name):
        names.append(name)
    return hook


# ---------------------------------------------------------------------------------------------------------
# HA-05
# ---------------------------------------------------------------------------------------------------------
class PendingInvalidationTests(unittest.TestCase):
    STEPS = ("after_recorded", "after_invalidation_observation", "after_invalidation_pit")

    def crashed(self, root, step):
        stores, entity, record, observation = one_capture(root)
        with self.assertRaises(Crash):
            invalidate(stores, observation.observation_id, checkpoint=crash_at(step))
        return es.reopen(stores), entity, record, observation

    def test_ha05_a_pending_invalidation_leaves_nothing_readable_until_a_start_completes_it(self):
        for step in self.STEPS:
            with self.subTest(step), scratch_root() as root:
                stores, entity, record, _ = self.crashed(root, step)
                for cutoff in (iso(T_INV, seconds=-1), T_INV, iso(T_INV, seconds=2), iso(T_INV, seconds=600)):
                    verdict = admissible_head(entity, cutoff, stores=stores, derivation_check=ACCEPT)
                    self.assertNotIsInstance(verdict, UsableBook, (step, cutoff))   # never the old price
                    self.assertEqual(verdict.code, F.DATA_CAPABILITY_NOT_READY)
                emit.complete_pending_invalidations(stores, clock=self.later_clock(stores))
                before = admissible_head(entity, iso(T_INV, seconds=-1), stores=stores, derivation_check=ACCEPT)
                self.assertIsInstance(before, UsableBook)                    # history before T_inv is unchanged
                self.assertEqual(before.record, record)
                head = [row for row in store_pit_rows(stores) if row["entity_id"] == entity][-1]
                after = admissible_head(entity, iso(head["ready_at"], seconds=1), stores=stores,
                                        derivation_check=ACCEPT)
                self.assertEqual(after.code, F.INVALIDATED)                   # the INVALIDATED head from its T3

    def invalidation_history(self, stores) -> dict:
        state = {}
        for invalidation_id, entry in stores.invalidations.state().items():
            recorded, applied = entry["recorded"], entry["applied"]
            state[invalidation_id] = {
                "observation": recorded["invalidated_observation_id"], "record": recorded["invalidated_pit_record_id"],
                "head_effect": applied and applied["head_effect"],
                "invalidation_record": applied and applied["invalidation_pit_record_id"]}
        heads = sorted((row["record_id"], row["payload_hash"]) for row in store_pit_rows(stores))
        coverage = sorted(row["entry_id"] for row in es.coverage_rows(stores))
        return {"invalidations": state, "pit": heads, "coverage": coverage}

    def later_clock(self, stores):
        start = iso(T_INV, seconds=3600)
        return SequenceClock([iso(start, seconds=index) for index in range(10)])

    def test_ha05_a_restart_completes_every_pending_invalidation_exactly_once(self):
        with scratch_root() as root:                                          # the uninterrupted reference
            stores, entity, record, observation = one_capture(root)
            invalidate(stores, observation.observation_id)
            expected = self.invalidation_history(stores)
        for step in self.STEPS:
            with self.subTest(step), scratch_root() as root:
                stores, entity, record, _ = self.crashed(root, step)
                done = emit.complete_pending_invalidations(stores, clock=self.later_clock(stores))
                self.assertEqual(len(done), 1)
                once = self.invalidation_history(stores)
                again = emit.complete_pending_invalidations(es.reopen(stores), clock=self.later_clock(stores))
                self.assertEqual(again, ())                                       # nothing left to complete
                self.assertEqual(self.invalidation_history(es.reopen(stores)), once)   # exactly once
                self.assertEqual(once, expected)                                  # the uninterrupted history
                applied = next(iter(stores.invalidations.state().values()))["applied"]
                late = iso(applied["applied_at"], seconds=1)
                self.assertEqual(admissible_head(entity, late, stores=stores, derivation_check=ACCEPT).code,
                                 F.INVALIDATED)

    def test_ha05_the_pipeline_start_completes_a_pending_invalidation(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response()])
            rt.acquire(odds_item())
            approve(rt)
            row = pit_rows(rt)[0]
            observation = [item for item in rt.stores.evidence.get_observations(row["payload_hash"])
                           if item.contract_id == rt.stores.contract_id][0]
            with self.assertRaises(Crash):
                emit.emit_invalidation(invalidated_observation_id=observation.observation_id,
                                       invalidation_class="PROVIDER_ERROR_NOTICE", reason="PROVIDER_ERROR_NOTICE",
                                       actor="OPERATOR", evidence_refs=("notice-1",), stores=rt.stores,
                                       clock=rt.clock, checkpoint=crash_at("after_recorded"))
            restarted = reopen(rt)
            restarted.resume()                                                # no second invalidate() call
            state = list(restarted.stores.invalidations.state().values())
            self.assertEqual(len(state), 1)
            self.assertIsNotNone(state[0]["applied"])

    def test_ha05_the_cli_run_reconciles_before_its_first_send(self):
        import contextlib
        import io
        from types import SimpleNamespace
        from unittest import mock

        from genesis_adapters import cli
        from genesis_adapters.oddspapi import transport_http as th

        from .test_v05_tx01 import prepare
        calls = []
        real = emit.complete_pending_invalidations

        def spy(stores, *, clock):
            calls.append("reconciled")
            return real(stores, clock=clock)

        class NoSend(th.HttpsTransport):
            def send(self, request, **kw):
                calls.append("sent")
                raise AssertionError("no send expected")

        with scratch_root() as base:
            root, plan, env = prepare(base)
            plan.write_text("[]", encoding="utf-8")
            synchronized = {"synchronized": True, "method": "test", "source": "test"}
            with mock.patch.object(emit, "complete_pending_invalidations", spy), \
                    mock.patch.object(th, "HttpsTransport", NoSend), \
                    mock.patch.object(cli, "time_sync_attestation", lambda: synchronized), \
                    mock.patch.dict(os.environ, {"GENESIS_ODDSPAPI_CREDENTIAL_FILE":
                                                 env["GENESIS_ODDSPAPI_CREDENTIAL_FILE"]}), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = cli.cmd_run(SimpleNamespace(config=None, root=str(root), plan=str(plan), mode="G2"))
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(calls, ["reconciled"])


# ---------------------------------------------------------------------------------------------------------
# HA-06
# ---------------------------------------------------------------------------------------------------------
class OneResponseOneTimeTests(unittest.TestCase):
    PAYLOAD = staticmethod(lambda: small_payload(bookmakers=("pinnacle", "fixture-book-a")))

    def emission_steps(self) -> list[str]:
        with scratch_root() as root:
            names: list[str] = []
            capture(build_stores(root), self.PAYLOAD(), checkpoint=recorder(names))
        return [name for name in names if name.startswith(("after_observation", "after_structured", "after_t3",
                                                           "after_pit", "after_coverage"))]

    def response_times(self, stores):
        t3s = {row["ready_at"] for row in store_pit_rows(stores)}
        t2s = set()
        for row in store_pit_rows(stores):
            for item in stores.evidence.get_observations(row["payload_hash"]):
                if item.contract_id == stores.contract_id:
                    t2s.add(item.parse_ready_at)
        normalized = [row for row in stores.acquisition.rows() if row["record_type"] == "acq_normalized"]
        return t2s, t3s, normalized

    def test_ha06_every_record_of_a_response_keeps_one_t2_and_one_t3_after_a_crash_anywhere(self):
        steps = self.emission_steps()
        self.assertIn("after_pit:1", steps)                                   # a genuinely multi-book response
        for step in steps:
            with self.subTest(step), scratch_root() as root:
                stores = build_stores(root)
                with self.assertRaises(Crash):
                    capture(stores, self.PAYLOAD(), checkpoint=crash_at(step))
                capture(stores, self.PAYLOAD(), t2=iso(CAPTURE_1, seconds=5), t3=iso(CAPTURE_1, seconds=6),
                        stamp=iso(CAPTURE_1, seconds=7), seed=False)
                t2s, t3s, normalized = self.response_times(stores)
                self.assertEqual(len(t2s), 1, t2s)
                self.assertEqual(len(t3s), 1, t3s)
                self.assertEqual(len(normalized), 1)
                self.assertEqual(({normalized[0]["T2"]}, {normalized[0]["T3"]}), (t2s, t3s))

    def test_ha06_no_decision_reads_a_half_emitted_response_and_after_recovery_reader_and_verifier_agree(self):
        for step in self.emission_steps():
            with self.subTest(step), scratch_root() as root:
                stores = build_stores(root)
                with self.assertRaises(Crash):
                    capture(stores, self.PAYLOAD(), checkpoint=crash_at(step))
                for row in store_pit_rows(stores):                            # whatever is already appended ...
                    halfway = admissible_head(row["entity_id"], iso(row["ready_at"], seconds=1), stores=stores,
                                              derivation_check=ACCEPT)
                    self.assertEqual(halfway.code, F.DATA_CAPABILITY_NOT_READY)   # ... is unreadable meanwhile
                durable = {row["ready_at"] for row in store_pit_rows(stores)}
                capture(stores, self.PAYLOAD(), t2=iso(CAPTURE_1, seconds=5), t3=iso(CAPTURE_1, seconds=6),
                        stamp=iso(CAPTURE_1, seconds=7), seed=False)
                rows = store_pit_rows(stores)
                (t3,) = {row["ready_at"] for row in rows}                     # one T3 for the whole response ...
                self.assertTrue(durable <= {t3})                              # ... the durable one, if any
                for cutoff in (iso(t3, seconds=-1), t3, iso(t3, seconds=1)):
                    for row in rows:
                        verdict = admissible_head(row["entity_id"], cutoff, stores=stores, derivation_check=ACCEPT)
                        state = es.doc_json(stores, row["payload_hash"])["market_state"]
                        if cutoff < t3:                                       # not admissible yet, for every book
                            self.assertNotIsInstance(verdict, UsableBook, (row["entity_id"], cutoff))
                        elif state != "OPEN":                                 # the head, refused for its own state
                            self.assertEqual(verdict.code.value, state, (row["entity_id"], cutoff))
                        else:                                                 # the head, usable, verifier agrees
                            self.assertIsInstance(verdict, UsableBook, (row["entity_id"], cutoff))
                            self.assertEqual(verdict.record.record_id, row["record_id"])
                            selection = sorted(verdict.document["selections"])[0]
                            accepted, detail = verifier_verdict(stores, [(verdict.record, selection)],
                                                                decision_at=cutoff, scratch=root / "m",
                                                                label=f"{row['entity_id'][-8:]}-{cutoff[-9:-1]}")
                            self.assertTrue(accepted, detail)


class RunLockTests(unittest.TestCase):
    """Design 6.3: one adapter phase or decision at a time, across processes; a crash never leaves the lock held."""

    def hold_in_another_process(self, root):
        ready = root / "holder.ready"
        code = ("import sys, time\n"
                "from pathlib import Path\n"
                "from genesis_adapters.oddspapi import quiescence\n"
                "with quiescence.run_lock(Path(sys.argv[1])):\n"
                "    Path(sys.argv[2]).write_text('held')\n"
                "    time.sleep(600)\n")
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO / "adapters" / "src"), str(REPO / "src")]))
        proc = subprocess.Popen([sys.executable, "-B", "-c", code, str(root), str(ready)], env=env)
        deadline = time.monotonic() + 60
        while not ready.exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.kill()
                self.fail("the lock holder did not start")
            time.sleep(0.05)
        return proc

    def test_ha06_a_lock_held_by_another_process_refuses_adapter_phases_and_reads(self):
        from genesis_adapters.oddspapi import quiescence
        with scratch_root() as root:
            rt = open_rt(root / "rt", script=[odds_response()])
            rt.acquire(odds_item("w0"))
            approve(rt)
            row = pit_rows(rt)[0]
            holder = self.hold_in_another_process(rt.root)
            try:
                with self.assertRaises(quiescence.QuiescenceBusy):
                    with quiescence.run_lock(rt.root):
                        pass
                verdict = rt.reader().head(row["entity_id"], iso(row["ready_at"], seconds=1))
                self.assertEqual(verdict.code, F.DATA_CAPABILITY_NOT_READY)
                with self.assertRaises(quiescence.QuiescenceBusy):
                    rt.acquire(odds_item("w1"))
                with self.assertRaises(quiescence.QuiescenceBusy):
                    with quiescence.decision_phase(rt.stores):
                        pass
                observation = [item for item in rt.stores.evidence.get_observations(row["payload_hash"])
                               if item.contract_id == rt.stores.contract_id][0]
                with self.assertRaises(quiescence.QuiescenceBusy):                # an invalidation waits its turn too
                    emit.emit_invalidation(invalidated_observation_id=observation.observation_id,
                                           invalidation_class="PROVIDER_ERROR_NOTICE", reason="PROVIDER_ERROR_NOTICE",
                                           actor="OPERATOR", evidence_refs=("notice-1",), stores=rt.stores,
                                           clock=rt.clock)
                self.assertEqual(rt.stores.invalidations.state(), {})
            finally:
                holder.kill()                                                 # a crash: the OS releases the lock
                holder.wait(timeout=60)
            with quiescence.decision_phase(rt.stores):
                verdict = rt.reader().head(row["entity_id"], iso(row["ready_at"], seconds=1))
            self.assertIsInstance(verdict, UsableBook)

    def test_ha06_a_cli_run_is_refused_while_another_process_holds_the_lock(self):
        import contextlib
        import io
        from types import SimpleNamespace

        from genesis_adapters import cli

        from .test_v05_tx01 import prepare
        with scratch_root() as base:
            root, plan, env = prepare(base)
            holder = self.hold_in_another_process(root)
            err_out = io.StringIO()
            try:
                with contextlib.redirect_stderr(err_out), contextlib.redirect_stdout(io.StringIO()):
                    code = cli.cmd_run(SimpleNamespace(config=None, root=str(root), plan=str(plan), mode="G2"))
            finally:
                holder.kill()
                holder.wait(timeout=60)
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("another adapter phase holds the run lock", err_out.getvalue())
        self.assertFalse((root / "acquisition.jsonl").exists())                 # nothing at all was written

    def test_ha06_no_decision_reads_while_an_attempt_is_open_or_a_credential_halt_is_unrecorded(self):
        from .test_v05_r3_runner_state import CrashAfterCompleted
        echo = b'[{"note": "' + SENTINEL_KEY.encode("ascii") + b'"}]'
        for label, script, secret, crash in (
                ("an attempt still open", [odds_response()], None, "after_sent"),
                ("a secret echo whose halt is not recorded", [ok(echo, headers=JSON)], Secret(SENTINEL_KEY), None)):
            with self.subTest(label), scratch_root() as root:
                rt = open_rt(root, script=[odds_response()] + script, secret=secret)
                rt.acquire(odds_item("w0"))
                approve(rt)
                row = pit_rows(rt)[0]
                cutoff = iso(row["ready_at"], seconds=1)
                self.assertIsInstance(rt.reader().head(row["entity_id"], cutoff), UsableBook)   # control
                if crash is not None:
                    rt.runner.checkpoint = crash_at(crash)
                    with self.assertRaises(Crash):
                        rt.acquire(odds_item("w1"))
                else:
                    with CrashAfterCompleted(0).active(), self.assertRaises(Crash):
                        rt.acquire(odds_item("w1"))
                verdict = rt.reader().head(row["entity_id"], cutoff)
                self.assertEqual(verdict.code, F.DATA_CAPABILITY_NOT_READY)

    def test_ha06_the_lock_is_reentrant_within_one_process(self):
        from genesis_adapters.oddspapi import quiescence
        with scratch_root() as root:
            with quiescence.run_lock(root):
                with quiescence.run_lock(root):
                    pass
                with quiescence.run_lock(root):
                    pass
            with quiescence.run_lock(root):                                   # released after the outermost
                pass


# ---------------------------------------------------------------------------------------------------------
# HA-12
# ---------------------------------------------------------------------------------------------------------
class MandatoryDerivationTests(unittest.TestCase):
    def test_ha12_no_consumption_path_works_without_a_verifier(self):
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            cutoff = iso(record.ready_at, seconds=1)
            with self.assertRaises(TypeError):
                admissible_head(entity, cutoff, stores=stores)                # no silent default
            with self.assertRaises(TypeError):
                MarketBookReader(stores)
            self.assertEqual(admissible_head(entity, cutoff, stores=stores, derivation_check=None).code,
                             F.DERIVATION_UNVERIFIED)
            book = admissible_head(entity, cutoff, stores=stores, derivation_check=ACCEPT)
            self.assertIsInstance(book, UsableBook)
            selection = sorted(book.document["selections"])[0]
            with self.assertRaises(TypeError):
                build_manifest_body(event_id=book.document["event_id"], market_id=book.document["market_id"],
                                    decision_at=cutoff, books=[book], selections=[selection], stores=stores)

    def test_ha12_the_manifest_builder_runs_the_verifier_it_is_given(self):
        # the builder's own re-read must verify: a head that re-derived when it was read is still refused when the
        # verifier passed to the builder rejects it (nothing else - no invalidation - has changed in between)
        with scratch_root() as root:
            stores, entity, record, observation = one_capture(root)
            cutoff = iso(record.ready_at, seconds=1)
            book = admissible_head(entity, cutoff, stores=stores, derivation_check=ACCEPT)
            self.assertIsInstance(book, UsableBook)
            selection = sorted(book.document["selections"])[0]
            arguments = dict(event_id=book.document["event_id"], market_id=book.document["market_id"],
                             decision_at=cutoff, books=[book], selections=[selection], stores=stores)
            build_manifest_body(**arguments, derivation_check=ACCEPT)                       # control: it builds
            seen = []

            def reject(observation_id):
                seen.append(observation_id)
                raise DerivationError("the inputs no longer reproduce the document")

            with self.assertRaises(ManifestError):
                build_manifest_body(**arguments, derivation_check=reject)
            self.assertEqual(seen, [observation.observation_id])
            self.assertEqual(stores.invalidations.state(), {})

    def test_ha12_an_underivable_head_is_refused_and_invalidated_automatically(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response()])
            rt.acquire(odds_item())
            approve(rt)
            row = next(item for item in pit_rows(rt) if es.doc_json(rt.stores, item["payload_hash"])["market_state"]
                       == "OPEN")
            cutoff = iso(row["ready_at"], seconds=1)
            good = rt.reader().head(row["entity_id"], cutoff)
            self.assertIsInstance(good, UsableBook)                           # control: it re-derives exactly
            normalized = [r for r in rt.stores.acquisition.rows() if r["record_type"] == "acq_normalized"][0]
            scope_file = root / "scopes" / f"{normalized['expected_scope_hash']}.json"
            scope_file.write_bytes(scope_file.read_bytes() + b" ")           # a derivation input no longer reproduces
            bad = rt.reader().head(row["entity_id"], cutoff)
            self.assertEqual(bad.code, F.DERIVATION_UNVERIFIED)
            state = list(rt.stores.invalidations.state().values())
            self.assertEqual([entry["recorded"]["actor"] for entry in state], ["ADAPTER_AUTOMATIC"])
            self.assertEqual(state[0]["recorded"]["invalidated_observation_id"], good.observation.observation_id)
            selection = sorted(good.document["selections"])[0]
            with self.assertRaises(ManifestError):
                build_manifest_body(event_id=good.document["event_id"], market_id=good.document["market_id"],
                                    decision_at=cutoff, books=[good], selections=[selection], stores=rt.stores,
                                    derivation_check=rt.checked_derivation)


if __name__ == "__main__":
    unittest.main()
