"""Unit tests for the parts that must fail closed on their own."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from genesis_autonomy import heavy, review, roadmap, state as st
from genesis_autonomy.state import WorkflowError
import shard_tests

from .support import PY, dryrun_roadmap


def _state_with_one_event(repo: Path) -> dict:
    s = st.new_state(product_sha="a" * 40, evidence_sha="b" * 40, branch="x", writer=str(repo),
                     envelope_digest="e", roadmap_digest="r", milestone_ids=["M1"])
    st.append_event(repo, s, {"event": "INIT"})
    st.save(repo, s)
    return s


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_loads_clean(self):
        _state_with_one_event(self.repo)
        loaded = st.load(self.repo)
        self.assertEqual(loaded["phase"], "IDLE")
        self.assertEqual(loaded["ledger_length"], 1)

    def test_state_edited_outside_the_engine_is_refused(self):
        _state_with_one_event(self.repo)
        path = st.state_dir(self.repo) / "state.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["phase"] = "COMPLETE"
        path.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(WorkflowError) as cm:
            st.load(self.repo)
        self.assertEqual(cm.exception.code, "STATE_DIGEST_MISMATCH")

    def test_ledger_edit_is_refused(self):
        _state_with_one_event(self.repo)
        ledger = st.state_dir(self.repo) / "ledger.jsonl"
        ledger.write_text(ledger.read_text(encoding="utf-8").replace("INIT", "NOPE"), encoding="utf-8")
        with self.assertRaises(WorkflowError) as cm:
            st.load(self.repo)
        self.assertEqual(cm.exception.code, "LEDGER_TAMPERED")

    def test_one_unrecorded_ledger_entry_is_a_torn_write_and_is_adopted(self):
        s = _state_with_one_event(self.repo)
        st.append_event(self.repo, s, {"event": "CRASHED_BEFORE_SAVE"})   # appended, never saved
        loaded = st.load(self.repo)
        self.assertEqual(loaded["recovered_torn_writes"], 1)
        self.assertEqual(loaded["ledger_length"], 2)

    def test_two_unrecorded_entries_are_refused(self):
        s = _state_with_one_event(self.repo)
        st.append_event(self.repo, s, {"event": "A"})
        st.append_event(self.repo, s, {"event": "B"})
        with self.assertRaises(WorkflowError) as cm:
            st.load(self.repo)
        self.assertEqual(cm.exception.code, "LEDGER_MISMATCH")

    def test_illegal_phase_move_is_refused(self):
        s = _state_with_one_event(self.repo)
        with self.assertRaises(WorkflowError) as cm:
            st.set_phase(s, "VALIDATING")
        self.assertEqual(cm.exception.code, "MALFORMED_TRANSITION")

    def test_halt_and_unhalt_restore_the_phase_and_block_needs_clear(self):
        s = _state_with_one_event(self.repo)
        st.halt(self.repo, s, "BLOCKED", "test block")
        self.assertEqual(s["phase"], "BLOCKED")
        with self.assertRaises(WorkflowError) as cm:
            st.unhalt(self.repo, s, clear_block=False)
        self.assertEqual(cm.exception.code, "BLOCK_NOT_CLEARED")
        self.assertEqual(st.unhalt(self.repo, s, clear_block=True), "IDLE")
        self.assertEqual(s["phase"], "IDLE")


class RoadmapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / "autonomy" / "approvals").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_ids_and_missing_validation_are_malformed(self):
        doc = dryrun_roadmap()
        doc["milestones"][1]["id"] = "DR0"
        with self.assertRaises(WorkflowError):
            roadmap.validate(doc)
        doc = dryrun_roadmap()
        doc["milestones"][1]["validation"] = []
        with self.assertRaises(WorkflowError):
            roadmap.validate(doc)

    def _commit_approval(self, body: dict) -> None:
        from .support import git
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "Test Harness")
        git(self.repo, "config", "user.email", "harness@example.invalid")
        (self.repo / "autonomy" / "approvals" / "HG-X.json").write_text(json.dumps(body), encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "approval")

    def test_approval_with_wrong_approver_is_refused_not_trusted(self):
        self._commit_approval({"gate_id": "HG-X", "approved_by": "an-agent", "approval_reference": "x"})
        with self.assertRaises(WorkflowError) as cm:
            roadmap.gate_approved(self.repo, "HG-X")
        self.assertEqual(cm.exception.code, "APPROVAL_MALFORMED")

    def test_an_approval_present_but_not_committed_is_refused(self):
        (self.repo / "autonomy" / "approvals" / "HG-X.json").write_text(json.dumps(
            {"gate_id": "HG-X", "approved_by": "human-operator", "approval_reference": "adr"}), encoding="utf-8")
        with self.assertRaises(WorkflowError) as cm:
            roadmap.gate_approved(self.repo, "HG-X")
        self.assertEqual(cm.exception.code, "APPROVAL_UNCOMMITTED")

    def test_a_committed_human_approval_clears_the_gate(self):
        self._commit_approval({"gate_id": "HG-X", "approved_by": "human-operator", "approval_reference": "adr-7"})
        self.assertTrue(roadmap.gate_approved(self.repo, "HG-X"))

    def test_gated_milestone_nothing_depends_on_does_not_stop_paper_work(self):
        doc = dryrun_roadmap()
        statuses = {m["id"]: {"status": "PENDING"} for m in doc["milestones"]}
        chosen, reason, _ = roadmap.select(doc, statuses, self.repo)
        self.assertEqual((chosen["id"], reason), ("DR1", None))

    def test_only_gated_work_left_is_a_human_gate_stop(self):
        doc = dryrun_roadmap()
        statuses = {"DR0": {"status": "PENDING"}, "DR1": {"status": "PASSED"}, "DR2": {"status": "PASSED"}}
        chosen, reason, detail = roadmap.select(doc, statuses, self.repo)
        self.assertIsNone(chosen)
        self.assertEqual((reason, detail[0]["id"]), ("HUMAN_GATE", "HG-DR0"))

    def test_everything_passed_is_complete(self):
        doc = dryrun_roadmap()
        statuses = {m["id"]: {"status": "PASSED"} for m in doc["milestones"]}
        self.assertEqual(roadmap.select(doc, statuses, self.repo)[1], "COMPLETE")


class ReviewTests(unittest.TestCase):
    SHA = "c" * 40

    def _write(self, doc) -> Path:
        path = Path(tempfile.mkdtemp()) / "last.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def _verdict(self, **overrides):
        doc = {"review_complete": True, "verdict": "PASS", "reviewed_sha": self.SHA, "summary": "ok", "findings": []}
        doc.update(overrides)
        return doc

    def test_an_incomplete_review_is_not_a_code_finding(self):
        doc = self._verdict(review_complete=False, verdict="REMEDIATION_REQUIRED",
                            summary="sandbox refused the reads")
        with self.assertRaises(WorkflowError) as cm:
            review.parse_verdict(self._write(doc), self.SHA)
        self.assertEqual(cm.exception.code, "REVIEW_INCOMPLETE")

    def test_a_pass_on_the_candidate_is_accepted(self):
        self.assertEqual(review.parse_verdict(self._write(self._verdict()), self.SHA)["verdict"], "PASS")

    def test_wrong_sha_is_refused(self):
        with self.assertRaises(WorkflowError) as cm:
            review.parse_verdict(self._write(self._verdict(reviewed_sha="d" * 40)), self.SHA)
        self.assertEqual(cm.exception.code, "REVIEWED_WRONG_SHA")

    def test_pass_with_a_high_finding_is_not_a_pass(self):
        finding = {"severity": "HIGH", "file": "a.py", "line": 1, "summary": "s", "required_fix": "f"}
        with self.assertRaises(WorkflowError) as cm:
            review.parse_verdict(self._write(self._verdict(findings=[finding])), self.SHA)
        self.assertEqual(cm.exception.code, "REVIEW_INVALID")

    def test_remediation_without_findings_is_invalid(self):
        with self.assertRaises(WorkflowError):
            review.parse_verdict(self._write(self._verdict(verdict="REMEDIATION_REQUIRED")), self.SHA)

    def test_extra_fields_are_invalid(self):
        with self.assertRaises(WorkflowError):
            review.parse_verdict(self._write(self._verdict(extra=1)), self.SHA)

    def test_api_key_in_the_environment_is_refused_before_any_call(self):
        cfg = {"forbidden_env": ["OPENAI_API_KEY"], "required_login": "Logged in using ChatGPT"}
        with self.assertRaises(WorkflowError) as cm:
            review.preflight(cfg, [PY, "-B", "-c", "raise SystemExit(9)"], {"OPENAI_API_KEY": "x"})
        self.assertEqual(cm.exception.code, "BILLING_GUARD")


CHILD_HOLD = ("import sys,time; sys.path.insert(0, sys.argv[1]); from genesis_autonomy import heavy; "
              "from pathlib import Path; "
              "lock = heavy.ExclusiveFileLock(Path(sys.argv[2]) / heavy.HEAVY_LOCK, 'HEAVY_BUSY', 'busy'); "
              "lock.__enter__(); print('HELD', flush=True); time.sleep(float(sys.argv[3]))")


class HeavyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.common = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _holder(self, seconds: float) -> subprocess.Popen:
        pkg = str(Path(heavy.__file__).resolve().parents[1])
        proc = subprocess.Popen([PY, "-B", "-c", CHILD_HOLD, pkg, str(self.common), str(seconds)],
                                stdout=subprocess.PIPE, text=True, encoding="utf-8")
        self.assertEqual(proc.stdout.readline().strip(), "HELD")
        return proc

    def _stop(self, proc: subprocess.Popen) -> None:
        proc.kill()
        proc.wait()
        proc.stdout.close()

    def test_a_second_process_cannot_take_the_host_lock(self):
        holder = self._holder(8)
        try:
            with self.assertRaises(WorkflowError) as cm:
                heavy.run_heavy(self.common, purpose="t", min_available_mib=1, action=lambda: 1,
                                wait_seconds=0, memory_reader=lambda: 9999)
            self.assertEqual(cm.exception.code, "HEAVY_BUSY")
        finally:
            self._stop(holder)

    def test_the_lock_is_released_when_the_holder_dies(self):
        holder = self._holder(60)
        self._stop(holder)
        self.assertEqual(heavy.run_heavy(self.common, purpose="t", min_available_mib=1,
                                         action=lambda: "ran", wait_seconds=0, memory_reader=lambda: 9999), "ran")

    def test_memory_below_the_gate_refuses_the_run(self):
        with self.assertRaises(WorkflowError) as cm:
            heavy.run_heavy(self.common, purpose="t", min_available_mib=1536, action=lambda: "ran",
                            wait_seconds=0, memory_reader=lambda: 1013)
        self.assertEqual(cm.exception.code, "MEMORY_GATE")
        self.assertEqual(heavy.run_heavy(self.common, purpose="t", min_available_mib=1,
                                         action=lambda: "ran", wait_seconds=0, memory_reader=lambda: 9999), "ran")

    def test_this_host_reports_a_positive_memory_figure(self):
        self.assertGreater(heavy.available_memory_mib(), 0)


class RenameTests(unittest.TestCase):
    def test_a_rename_out_of_a_frozen_tree_is_still_reported_under_its_old_name(self):
        from genesis_autonomy import gitops
        from .support import git
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.name", "Test Harness")
            git(repo, "config", "user.email", "harness@example.invalid")
            (repo / "src").mkdir()
            (repo / "src" / "frozen.py").write_text("x = 1\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "base")
            base = git(repo, "rev-parse", "HEAD")
            (repo / "autonomy").mkdir()
            git(repo, "mv", "src/frozen.py", "autonomy/frozen.py")
            git(repo, "commit", "-q", "-m", "move a frozen file")
            changed = gitops.changed_paths(repo, base, gitops.head(repo))
            self.assertIn("src/frozen.py", changed)


class ShardTests(unittest.TestCase):
    TOP = str(Path(__file__).resolve().parent / "fixtures" / "shardpkg_top")

    def test_plan_puts_every_id_in_exactly_one_shard(self):
        ids = [f"t{i:03d}" for i in range(23)]
        for shards in (1, 2, 5, 8, 40):
            flat = [i for chunk in shard_tests.plan(ids, shards) for i in chunk]
            self.assertEqual(flat, ids)

    def test_reconcile_catches_missing_duplicate_failed_and_unexpected_skips(self):
        inv = ["a", "b", "c"]
        clean = [{"results": [{"id": "a", "outcome": "ok"}, {"id": "b", "outcome": "ok"},
                              {"id": "c", "outcome": "skipped"}]}]
        self.assertEqual(shard_tests.reconcile(inv, clean, {"c"})["verdict"], "PASS")
        self.assertEqual(shard_tests.reconcile(inv, clean, set())["verdict"], "FAIL")
        missing = [{"results": [{"id": "a", "outcome": "ok"}]}]
        self.assertEqual(shard_tests.reconcile(inv, missing, set())["missing"], ["b", "c"])
        dup = [{"results": [{"id": "a", "outcome": "ok"}, {"id": "a", "outcome": "ok"}]}]
        self.assertEqual(shard_tests.reconcile(["a"], dup, set())["duplicated"], ["a"])
        failing = [{"results": [{"id": "a", "outcome": "failure", "detail": "x"}]}]
        self.assertEqual(shard_tests.reconcile(["a"], failing, set())["verdict"], "FAIL")

    def test_sharded_run_on_a_fixture_package_is_exact_and_never_called_monolithic(self):
        out = Path(tempfile.mkdtemp()) / "out"
        report = shard_tests.run_sharded(self.TOP, "shard_pkg", "test*.py", 2, out,
                                         {"shard_pkg.test_b.BTests.test_four"})
        self.assertEqual(report["verdict"], "PASS", report)
        self.assertEqual(report["mode"], "SHARDED")
        self.assertFalse(report["monolithic"])
        self.assertEqual(report["executed"], report["inventory"])
        self.assertEqual(report["counts"]["skipped"], 1)
        self.assertTrue((out / "RECONCILIATION.json").exists())

    def test_an_unexpected_skip_fails_the_sharded_run(self):
        out = Path(tempfile.mkdtemp()) / "out"
        report = shard_tests.run_sharded(self.TOP, "shard_pkg", "test*.py", 2, out, set())
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["unexpected_skips"], ["shard_pkg.test_b.BTests.test_four"])


if __name__ == "__main__":
    unittest.main()
