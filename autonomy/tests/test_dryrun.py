"""Dry run of the orchestration, against real git, the real engine and the real host locks.

Scripted only at the edges: the implementer and skeptic roles write and reply on schedule, and Codex is
the fake CLI with a scripted verdict. Nothing here touches a provider, a credential or a betting path.
Numbers in the comments match the ten demonstrations in the setup report.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from genesis_autonomy import engine, heavy, roadmap, state as st
from genesis_autonomy.state import WorkflowError

from .support import (PY, check_contains, commit_work, dryrun_roadmap, drive, git, ledger_events, make_context,
                      make_repo, write_approval)

HOLD = ("import sys,time; sys.path.insert(0, sys.argv[1]); from genesis_autonomy import heavy; "
        "from pathlib import Path; "
        "lock = heavy.ExclusiveFileLock(Path(sys.argv[2]) / heavy.HEAVY_LOCK, 'HEAVY_BUSY', 'busy'); "
        "lock.__enter__(); print('HELD', flush=True); time.sleep(float(sys.argv[3]))")

SLOW_CHECK = ("import os,sys,time\n"
              "marker = os.environ.get('DR_MARKER')\n"
              "if os.environ.get('DR_SLOW') == '1' and marker and not os.path.exists(marker):\n"
              "    open(marker, 'w').write(str(os.getpid()))\n"
              "    time.sleep(120)\n"
              "sys.exit(0)\n")


def process_alive(pid: int) -> bool:
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32")
    handle = kernel32.OpenProcess(0x00100000, False, pid)          # SYNCHRONIZE
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x102    # WAIT_TIMEOUT: still running
    finally:
        kernel32.CloseHandle(handle)

FINDING = {"severity": "HIGH", "file": "work/DR1.1.txt", "line": 1,
           "summary": "scripted reviewer finding", "required_fix": "change the work file"}


def good(ctx, action, *, tag="v1"):
    """Implementer for DR1: writes the work file and commits it, as the engine expects."""
    commit_work(ctx.repo, "work/DR1.1.txt", f"GOOD {tag}\n", f"DR1.1: write work file ({tag})")


def ok_implementer(ctx, action):
    if action["milestone"] == "DR1":
        good(ctx, action)
    else:
        commit_work(ctx.repo, f"work/{action['tasks'][0]['id']}.txt", "done\n", f"{action['tasks'][0]['id']}: work")


class DryRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _init(self, repo, ctx):
        head = git(repo, "rev-parse", "HEAD")
        return engine.init(ctx, product_sha=head, evidence_sha=head)

    def _ctx_for(self, roadmap_doc=None, scenario=None, **kw):
        repo = make_repo(self.root / f"r{time.monotonic_ns()}", roadmap_doc or dryrun_roadmap(),
                         wait_seconds=kw.pop("wait_seconds", 0))
        ctx = make_context(repo, scenario, **kw)
        return repo, ctx

    # 1. state reconstruction from disk, in a fresh interpreter
    def test_01_state_reconstructs_from_disk_in_a_fresh_process(self):
        repo, ctx = self._ctx_for()
        self._init(repo, ctx)
        first = engine.go(ctx)
        self.assertEqual((first["status"], first["action"], first["milestone"]), ("ACTION", "IMPLEMENT", "DR1"))
        cli = [PY, "-B", str(repo / "autonomy" / "genesis_workflow.py"), "status"]
        out = subprocess.run(cli, cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        fresh = json.loads(out.stdout)
        self.assertEqual((fresh["phase"], fresh["milestone"], fresh["remaining_tasks"]),
                         ("IMPLEMENTING", "DR1", ["DR1.1"]))
        # an edit outside the engine is refused by the next reader, not silently believed
        path = repo / "autonomy" / "state" / "state.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["phase"] = "COMPLETE"
        path.write_text(json.dumps(doc), encoding="utf-8")
        refused = subprocess.run(cli, cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(json.loads(refused.stdout)["code"], "STATE_DIGEST_MISMATCH")

    # 2. go selects an authorised, paper-only task; a gate it does not depend on does not stop it
    def test_02_go_selects_the_authorised_paper_only_milestone(self):
        repo, ctx = self._ctx_for()
        self._init(repo, ctx)
        picked = engine.select_only(ctx)
        self.assertEqual((picked["status"], picked["milestone"]), ("WOULD_START", "DR1"))
        self.assertEqual([g["id"] for g in engine.status(ctx)["pending_gates"]], ["HG-DR0"])
        write_approval(repo, "HG-DR0")
        self.assertEqual(engine.select_only(ctx)["milestone"], "DR0")

    # 3. writer and read-only roles are separate: dirty writers, wrong tasks, wrong SHAs and the reviewer checkout
    def test_03_writer_and_read_only_roles_are_kept_apart(self):
        repo, ctx = self._ctx_for(scenario=[{"verdict": "PASS"}])
        self._init(repo, ctx)
        action = engine.go(ctx)
        commit_work(repo, "work/DR1.1.txt", "GOOD v1\n", "DR1.1: write")
        (repo / "stray.txt").write_text("uncommitted\n", encoding="utf-8")
        with self.assertRaises(WorkflowError) as cm:
            engine.task_done(ctx, "DR1.1")
        self.assertEqual(cm.exception.code, "WRITER_DIRTY")
        (repo / "stray.txt").unlink()
        with self.assertRaises(WorkflowError) as cm:
            engine.task_done(ctx, "DR2.1")
        self.assertEqual(cm.exception.code, "TASK_ORDER")
        engine.task_done(ctx, "DR1.1")
        result = engine.go(ctx)
        self.assertEqual(result["action"], "SKEPTIC")
        reply = repo / "autonomy" / "state" / "wrong-sha.json"
        reply.write_text(json.dumps({"verdict": "CLEAR", "reviewed_sha": "0" * 40, "summary": "x", "findings": []}),
                         encoding="utf-8")
        with self.assertRaises(WorkflowError) as cm:
            engine.record_skeptic(ctx, reply)
        self.assertEqual(cm.exception.code, "SKEPTIC_WRONG_SHA")
        self.assertEqual(engine.status(ctx)["phase"], "SKEPTIC_PENDING")   # refusals change nothing
        # the reviewer runs read-only in its own detached checkout, never in the writer
        self.assertEqual(engine.record_skeptic(ctx, self._clear(repo, result["candidate"]))["skeptic"], "CLEAR")
        final = engine.go(ctx)                       # DR1 has passed; the next authorised milestone starts
        self.assertEqual((final["action"], final["milestone"]), ("IMPLEMENT", "DR2"))
        log =[json.loads(line) for line in (repo.parent / "scenario" / "codex-invocations.jsonl")
               .read_text(encoding="utf-8").splitlines()]
        real = [entry for entry in log if "exec" in entry["argv"]]
        self.assertEqual(len(real), 1)
        self.assertEqual(real[0]["sandbox"], "read-only")
        self.assertTrue(real[0]["hermetic"])
        self.assertNotEqual(Path(real[0]["cwd"]).resolve(), repo.resolve())
        self.assertFalse(Path(real[0]["cwd"]).exists(), "the reviewer checkout must be removed afterwards")

    def _clear(self, repo, sha):
        path = repo / "autonomy" / "state" / "clear.json"
        path.write_text(json.dumps({"verdict": "CLEAR", "reviewed_sha": sha, "summary": "scripted", "findings": []}),
                        encoding="utf-8")
        return path

    # 4. one heavy validation per host; a busy host defers, a low-memory host blocks, then both recover
    def test_04_heavy_validation_is_serialised_and_memory_gated(self):
        repo, ctx = self._ctx_for(scenario=[{"verdict": "PASS"}])
        self._init(repo, ctx)
        engine.go(ctx)
        commit_work(repo, "work/DR1.1.txt", "GOOD v1\n", "DR1.1: write")
        engine.task_done(ctx, "DR1.1")
        holder = subprocess.Popen([PY, "-B", "-c", HOLD, str(Path(heavy.__file__).resolve().parents[1]),
                                   str(ctx.common), "60"], stdout=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            self.assertEqual(holder.stdout.readline().strip(), "HELD")
            deferred = engine.go(ctx)
            self.assertEqual((deferred["status"], deferred["reason"]), ("STOP", "DEFERRED"))
            self.assertEqual(deferred["detail"]["code"], "HEAVY_BUSY")
            self.assertEqual(engine.status(ctx)["phase"], "VALIDATING")
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()
        low_ctx = make_context(repo, memory_mib=0, scenario=[{"verdict": "PASS"}])   # below the 1 MiB fixture gate
        first = engine.go(low_ctx)
        self.assertEqual((first["reason"], first["detail"]["code"]), ("DEFERRED", "MEMORY_GATE"))
        for _ in range(20):                           # memory that never recovers is a block, not a loop
            gated = engine.go(low_ctx)
            if gated["reason"] == "BLOCKED":
                break
        self.assertEqual((gated["reason"], gated["detail"]["code"]), ("BLOCKED", "DEFERRAL_LIMIT"))
        engine.resume(ctx, clear_block=True)
        resumed = engine.go(ctx)
        self.assertEqual((resumed["action"], resumed["phase"]), ("SKEPTIC", "SKEPTIC_PENDING"))

    # 5. interruption: a validation killed mid-run is recorded, not resumed from a half-written state
    def test_05_interrupted_validation_resumes_without_a_stale_lock(self):
        roadmap_doc = dryrun_roadmap()
        marker = self.root / "marker"
        script = self.root / "slow_check.py"
        script.write_text(SLOW_CHECK, encoding="utf-8")
        roadmap_doc["milestones"][1]["validation"] = [{"id": "slow", "argv": [PY, "-B", str(script)]}]
        repo, ctx = self._ctx_for(roadmap_doc, scenario=[{"verdict": "PASS"}])
        self._init(repo, ctx)
        engine.go(ctx)
        commit_work(repo, "work/DR1.1.txt", "GOOD v1\n", "DR1.1: write")
        engine.task_done(ctx, "DR1.1")
        child_code = ("import sys; sys.path.insert(0, sys.argv[1]); from genesis_autonomy import engine; "
                      "from tests.support import make_context; "
                      "c = make_context(sys.argv[2], extra_env={'DR_SLOW': '1', 'DR_MARKER': sys.argv[3]}); "
                      "engine.go(c)")
        autonomy_dir = str(Path(__file__).resolve().parents[1])
        child = subprocess.Popen([PY, "-B", "-c", child_code, autonomy_dir, str(repo), str(marker)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 60
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(marker.exists(), "the slow validation never started")
        check_pid = int(marker.read_text(encoding="utf-8"))
        child.kill()                                  # the crash: the engine lock and heavy lock die with it
        child.wait()
        child.stdout.close()
        child.stderr.close()
        orphan_gone = time.monotonic() + 15
        while process_alive(check_pid) and time.monotonic() < orphan_gone:
            time.sleep(0.1)
        self.assertFalse(process_alive(check_pid), "the validation process must not outlive its engine")
        recovered = engine.go(ctx)
        self.assertIn("INTERRUPTED", ledger_events(repo))
        self.assertEqual((recovered["action"], recovered["phase"]), ("SKEPTIC", "SKEPTIC_PENDING"))
        self.assertEqual(st.load(repo)["active"]["interruptions"], 1)
        orphan_check = process_alive(check_pid)
        self.assertFalse(orphan_check)

    # 6. fake Codex PASS path: a candidate is validated, skeptic-cleared, reviewed and recorded
    def test_06_fake_codex_pass_path_records_the_milestone(self):
        repo, ctx = self._ctx_for(scenario=[{"verdict": "PASS"}])
        self._init(repo, ctx)
        drive(ctx, implementer=ok_implementer, stop_when=lambda r: r.get("milestone") == "DR2")
        self.assertEqual(engine.status(ctx)["completed"], ["DR1"])
        record = json.loads((repo / "autonomy" / "records" / "DR1" / "MILESTONE.json").read_text(encoding="utf-8"))
        self.assertEqual(record["result"], "PASS")
        self.assertEqual(record["review"]["verdict"], "PASS")
        events = ledger_events(repo)
        for needed in ("CANDIDATE_FROZEN", "VALIDATION_PASSED", "SKEPTIC_RECORDED", "CODEX_VERDICT",
                       "MILESTONE_PASSED"):
            self.assertIn(needed, events)

    # 7a. REMEDIATION_REQUIRED: rejected candidate preserved in history, remediation child, new SHA, re-review
    def test_07_codex_remediation_preserves_the_rejected_candidate_then_passes(self):
        scenario = [{"verdict": "REMEDIATION_REQUIRED", "findings": [FINDING]}, {"verdict": "PASS"}]
        repo, ctx = self._ctx_for(scenario=scenario)
        self._init(repo, ctx)
        tags = iter(["v1", "v2"])

        def implementer(c, action):
            if action["milestone"] == "DR1":
                good(c, action, tag=next(tags))
            else:
                ok_implementer(c, action)

        drive(ctx, implementer=implementer, stop_when=lambda r: r.get("milestone") == "DR2")
        rejected = list((repo / "autonomy" / "records" / "DR1").glob("rejected-r1-*"))
        self.assertEqual(len(rejected), 1)
        self.assertTrue((rejected[0] / "REJECTION.json").exists())
        self.assertTrue(list(rejected[0].rglob("verdict.json")), "the rejected review's evidence is kept")
        rejected_sha = json.loads((rejected[0] / "REJECTION.json").read_text(encoding="utf-8"))["candidate"]
        record = json.loads((repo / "autonomy" / "records" / "DR1" / "MILESTONE.json").read_text(encoding="utf-8"))
        self.assertNotEqual(record["candidate"], rejected_sha)
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", rejected_sha, record["candidate"]],
                                  cwd=str(repo))
        self.assertEqual(ancestor.returncode, 0, "the remediation child descends from the preserved candidate")
        self.assertEqual(record["rounds"], 2)
        self.assertEqual(len(record["rejected"]), 1)
        self.assertEqual(record["rejected"][0]["kind"], "CODEX_REMEDIATION_REQUIRED")

    # 7b. a failing validation is remediated, not passed
    def test_07b_failing_validation_is_remediated_not_passed(self):
        repo, ctx = self._ctx_for(scenario=[{"verdict": "PASS"}])
        self._init(repo, ctx)
        tags = iter(["BAD", "GOOD"])

        def implementer(c, action):
            if action["milestone"] == "DR1":
                commit_work(c.repo, "work/DR1.1.txt", f"{next(tags)} content\n", "DR1.1: write")
            else:
                ok_implementer(c, action)

        drive(ctx, implementer=implementer, stop_when=lambda r: r.get("milestone") == "DR2")
        self.assertEqual(engine.status(ctx)["completed"], ["DR1"])
        record = json.loads((repo / "autonomy" / "records" / "DR1" / "MILESTONE.json").read_text(encoding="utf-8"))
        self.assertEqual(record["rejected"][0]["kind"], "VALIDATION_FAILED")
        self.assertEqual(record["rounds"], 2)

    # 8. the Codex reviewer is reached only through the billing guard and the login check
    def test_08_codex_preflight_checks_login_and_refuses_billing_variables(self):
        repo, ctx = self._ctx_for()
        self.assertEqual(engine.codex_preflight(ctx, probe_call=False)["preflight"]["login"],
                         "Logged in using ChatGPT")
        billed = make_context(repo, extra_env={"OPENAI_API_KEY": "must-not-be-used"})
        with self.assertRaises(WorkflowError) as cm:
            engine.codex_preflight(billed, probe_call=False)
        self.assertEqual(cm.exception.code, "BILLING_GUARD")

    # 9. a human gate stops the loop with an explanation, and only a real approval releases it
    def test_09_human_gate_stops_then_proceeds_after_a_real_approval(self):
        only_gated = dryrun_roadmap()
        only_gated["milestones"] = [only_gated["milestones"][0]]
        repo, ctx = self._ctx_for(only_gated, scenario=[{"verdict": "PASS"}])
        self._init(repo, ctx)
        head_before = git(repo, "rev-parse", "HEAD")
        stop = engine.go(ctx)
        self.assertEqual((stop["status"], stop["reason"]), ("STOP", "HUMAN_GATE"))
        self.assertEqual(git(repo, "rev-parse", "HEAD"), head_before)          # nothing was written
        explained = engine.explain_gate(ctx)
        self.assertEqual(explained["current_gate"]["id"], "HG-DR0")
        self.assertIn("approved_by", explained["how_to_clear"])
        still = engine.go(ctx)
        self.assertEqual(still["reason"], "HUMAN_GATE")
        write_approval(repo, "HG-DR0")
        released = engine.go(ctx)
        self.assertEqual((released["action"], released["milestone"]), ("IMPLEMENT", "DR0"))

    # 10. a normal milestone PASS advances to the next without returning to the operator
    def test_10_a_normal_pass_advances_without_stopping_the_operator(self):
        repo, ctx = self._ctx_for(scenario=[{"verdict": "PASS"}, {"verdict": "PASS"}])
        self._init(repo, ctx)
        results = drive(ctx, implementer=ok_implementer)
        stops = [r for r in results if r["status"] == "STOP"]
        self.assertEqual([s["reason"] for s in stops], ["HUMAN_GATE"])   # only the gated DR0 is left at the end
        self.assertIs(results[-1], stops[-1])
        milestones_started = [r["milestone"] for r in results if r.get("action") == "IMPLEMENT"]
        self.assertEqual(milestones_started, ["DR1", "DR2"])
        self.assertEqual(engine.status(ctx)["completed"], ["DR1", "DR2"])
        events = ledger_events(repo)
        first_pass = events.index("MILESTONE_PASSED")
        self.assertIn("MILESTONE_STARTED", events[first_pass:], "DR2 started straight after DR1 passed")

    # extra: the frozen tree is not reachable through the workflow
    def test_frozen_tree_change_blocks_instead_of_validating(self):
        repo, ctx = self._ctx_for(scenario=[{"verdict": "PASS"}])
        self._init(repo, ctx)
        engine.go(ctx)
        commit_work(repo, "src/frozen.py", "x = 1\n", "DR1.1: touch the frozen tree")
        engine.task_done(ctx, "DR1.1")
        stop = engine.go(ctx)
        self.assertEqual((stop["reason"], stop["detail"]["code"]), ("BLOCKED", "FROZEN_TREE_TOUCHED"))

    # extra: pause stops at the next safe point; resume continues
    def test_pause_is_honoured_at_the_next_safe_point(self):
        repo, ctx = self._ctx_for(scenario=[{"verdict": "PASS"}])
        self._init(repo, ctx)
        self.assertEqual(engine.pause(ctx, "operator asked")["status"], "PAUSED")
        self.assertEqual(engine.go(ctx)["reason"], "PAUSED")
        self.assertEqual(engine.resume(ctx, clear_block=False)["phase"], "IDLE")
        self.assertEqual(engine.go(ctx)["action"], "IMPLEMENT")

    # extra: a dirty writer at freeze is sent back as a FIX task, not frozen
    def test_dirty_writer_at_freeze_becomes_a_fix_task(self):
        repo, ctx = self._ctx_for(scenario=[{"verdict": "PASS"}])
        self._init(repo, ctx)
        engine.go(ctx)
        commit_work(repo, "work/DR1.1.txt", "GOOD v1\n", "DR1.1: write")
        engine.task_done(ctx, "DR1.1")
        (repo / "left-behind.txt").write_text("forgot to commit\n", encoding="utf-8")
        retry = engine.go(ctx)
        self.assertEqual((retry["action"], retry["tasks"][0]["id"]), ("IMPLEMENT", "FIX-1"))
        (repo / "left-behind.txt").unlink()
        engine.task_done(ctx, "FIX-1")
        self.assertEqual(engine.go(ctx)["action"], "SKEPTIC")


if __name__ == "__main__":
    unittest.main()
